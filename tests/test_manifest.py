from pathlib import Path

from bwp_extractor.manifest import EntryRecord, Manifest, make_cache_key
from bwp_extractor.models import NameStatus, ResourceKind, Status
from bwp_extractor.npk import NpkEntry
from bwp_extractor.sources import SourceIdentity


def record():
    return EntryRecord("a.npk", 0, "00000001", Status.SUCCESS,
                       NameStatus.UNRESOLVED, ResourceKind.PNG, "raw/a.png", None,
                       None, "sha", None)


def test_manifest_roundtrip_and_cache_key(tmp_path: Path):
    path = tmp_path / "entries.jsonl"
    Manifest.save(path, [record()])
    loaded = Manifest.load(path)
    assert loaded["a.npk:0:00000001"].raw_path == "raw/a.png"
    identity = SourceIdentity("a.npk", 10, "source-sha")
    entry = NpkEntry(0, 1, 0, 3, 3, 11, 22, 0, 0)
    key = record().cache_key(identity, entry, "converter-v1")
    assert "source-sha" in key and "11" in key and "22" in key


def test_cache_key_preserves_field_boundaries():
    entry = NpkEntry(0, 1, 0, 3, 3, 11, 22, 0, 0)
    first = make_cache_key(
        "a", 0, SourceIdentity("a", 10, "source:sha"), entry, "converter-v1"
    )
    second = make_cache_key(
        "sha:a", 0, SourceIdentity("a", 10, "source"), entry, "converter-v1"
    )
    assert first != second
