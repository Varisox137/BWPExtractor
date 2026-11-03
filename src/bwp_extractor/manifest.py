from dataclasses import asdict, dataclass
import json
from pathlib import Path

from bwp_extractor.models import NameStatus, ResourceKind, Status
from bwp_extractor.npk import NpkEntry
from bwp_extractor.sources import SourceIdentity


def make_cache_key(archive: str, entry_index: int, source: SourceIdentity,
                   entry: NpkEntry, converter_version: str) -> str:
    return json.dumps(
        [source.sha256, archive, entry_index, entry.packed_checksum,
         entry.raw_checksum, converter_version],
        ensure_ascii=False,
        separators=(",", ":"),
    )


@dataclass
class EntryRecord:
    archive: str
    entry_index: int
    signature: str
    status: Status
    name_status: NameStatus
    kind: ResourceKind | None
    raw_path: str | None
    converted_path: str | None
    curated_path: str | None
    raw_sha256: str | None
    error: str | None
    cache_identity: str | None = None

    @property
    def key(self) -> str:
        return f"{self.archive}:{self.entry_index}:{self.signature}"

    def cache_key(self, source: SourceIdentity, entry: NpkEntry, converter_version: str) -> str:
        return make_cache_key(self.archive, self.entry_index, source, entry, converter_version)

    def to_dict(self) -> dict:
        result = asdict(self)
        result["cache_key"] = self.key
        return result


class Manifest:
    @staticmethod
    def save(path: Path, records: list[EntryRecord]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r.to_dict(), ensure_ascii=False) + "\n"
                                for r in records), encoding="utf-8")

    @staticmethod
    def load(path: Path) -> dict[str, EntryRecord]:
        result = {}
        if not path.exists():
            return result
        for line in path.read_text(encoding="utf-8").splitlines():
            data = json.loads(line)
            data["status"] = Status(data["status"])
            data["name_status"] = NameStatus(data["name_status"])
            data["kind"] = ResourceKind(data["kind"]) if data["kind"] else None
            item = EntryRecord(**{k: v for k, v in data.items() if k != "cache_key"})
            result[item.key] = item
        return result
