from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import subprocess

from bwp_extractor.decode import EntryDecodeError, UnsupportedEntryError, decode_entry
from bwp_extractor.formats import detect_format
from bwp_extractor.manifest import EntryRecord, Manifest, make_cache_key
from bwp_extractor.models import NameStatus, ResourceKind, Status
from bwp_extractor.names import NameResolver, curated_relative
from bwp_extractor.npk import NpkEntry, NpkError, read_npk_index
from bwp_extractor.output import OutputStore
from bwp_extractor.sources import ArchiveSource, open_source
from bwp_extractor.textures import TextureConverter


@dataclass
class ExtractedEntry:
    archive: ArchiveSource
    entry: NpkEntry
    kind: ResourceKind
    raw_path: str
    raw_sha256: str


class ExtractionPipeline:
    def __init__(self, output: Path, names: Path | None = None,
                 patch_priority: list[str] | None = None):
        self.store = OutputStore(output)
        self.output = output
        self.names = names
        self.patch_priority = patch_priority or []
        name_data = names.read_bytes() if names else b""
        config_data = name_data + "\0".join(self.patch_priority).encode("utf-8")
        self.cache_salt = sha256(config_data).hexdigest()
        self.issues: list[dict] = []
        self.duplicates: list[dict] = []

    def _cache_valid(self, old: EntryRecord | None, identity: str) -> bool:
        if not old or old.status != Status.SUCCESS or old.cache_identity != identity or not old.raw_path:
            return False
        for relative in (old.raw_path, old.converted_path, old.curated_path):
            if relative and not self.store.path(relative).is_file():
                return False
        raw = self.store.path(old.raw_path)
        return sha256(raw.read_bytes()).hexdigest() == old.raw_sha256

    def run(self, source_path: Path) -> list[EntryRecord]:
        previous = Manifest.load(self.output / "manifest/entries.jsonl")
        resolver = NameResolver()
        if self.names:
            resolver.load_mapping(json.loads(self.names.read_text(encoding="utf-8")))
        converter = TextureConverter(self.store)
        extracted: list[ExtractedEntry] = []
        records: dict[str, EntryRecord] = {}
        seen_signatures: dict[int, str] = {}
        archives = open_source(source_path).archives()
        priority = {name: i + 1 for i, name in enumerate(self.patch_priority)}
        archives.sort(key=lambda a: (priority.get(a.relative_name, 0), a.relative_name))
        for archive in archives:
            identity = archive.identity()
            try:
                with archive.open() as stream:
                    index = read_npk_index(stream, identity.size)
                    for entry in index.entries:
                        key = f"{archive.relative_name}:{entry.index}:{entry.signature:08x}"
                        if entry.signature in seen_signatures:
                            self.duplicates.append({"signature": f"{entry.signature:08x}",
                                "base": seen_signatures[entry.signature], "patch": key})
                        else:
                            seen_signatures[entry.signature] = key
                        cache_identity = make_cache_key(
                            archive.relative_name, entry.index, identity, entry,
                            f"{TextureConverter.VERSION}:{self.cache_salt}",
                        )
                        old = previous.get(key)
                        if self._cache_valid(old, cache_identity):
                            records[key] = old
                            continue
                        try:
                            data = decode_entry(stream, entry)
                            kind = detect_format(data)
                            relative = f"raw/{archive.relative_name}/{entry.signature:08x}.{kind.value}"
                            self.store.write_bytes(relative, data)
                            digest = sha256(data).hexdigest()
                            resolver.harvest(data)
                            extracted.append(ExtractedEntry(archive, entry, kind, relative, digest))
                            records[key] = EntryRecord(
                                archive.relative_name, entry.index, f"{entry.signature:08x}",
                                Status.SUCCESS, NameStatus.UNRESOLVED, kind, relative,
                                None, None, digest, None, cache_identity,
                            )
                        except UnsupportedEntryError as exc:
                            records[key] = EntryRecord(
                                archive.relative_name, entry.index, f"{entry.signature:08x}",
                                Status.UNSUPPORTED, NameStatus.UNRESOLVED,
                                None, None, None, None, None, str(exc),
                            )
                        except EntryDecodeError as exc:
                            records[key] = EntryRecord(
                                archive.relative_name, entry.index, f"{entry.signature:08x}",
                                Status.CORRUPT, NameStatus.UNRESOLVED,
                                None, None, None, None, None, str(exc),
                            )
            except NpkError as exc:
                self.issues.append({"archive": archive.relative_name, "error": str(exc)})
        for item in extracted:
            key = f"{item.archive.relative_name}:{item.entry.index}:{item.entry.signature:08x}"
            record = records[key]
            resolved = resolver.resolve(item.entry.signature)
            if resolved.path:
                record.name_status = NameStatus.RESOLVED
                record.curated_path = curated_relative(resolved.path)
            if item.kind in {ResourceKind.PNG, ResourceKind.KTX1, ResourceKind.KTX2, ResourceKind.DDS}:
                converted = f"converted/{item.archive.relative_name}/{item.entry.signature:08x}.png"
                try:
                    converter.convert(self.store.path(item.raw_path), item.kind, converted)
                    record.converted_path = converted
                    if record.curated_path:
                        record.curated_path = str(PurePosixPath(record.curated_path).with_suffix(".png"))
                        self.store.link_or_copy(self.store.path(converted), record.curated_path)
                except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
                    record.status = Status.CONVERSION_FAILED
                    record.converted_path = None
                    record.curated_path = None
                    record.error = str(exc)
            elif record.curated_path:
                self.store.link_or_copy(self.store.path(item.raw_path), record.curated_path)
        ordered = [records[key] for key in sorted(records)]
        self.store.write_jsonl("manifest/entries.jsonl", [r.to_dict() for r in ordered])
        return ordered
