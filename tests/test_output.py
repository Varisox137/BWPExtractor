from pathlib import Path

import pytest

from bwp_extractor.output import OutputStore


def test_rejects_path_traversal(tmp_path: Path):
    store = OutputStore(tmp_path)
    with pytest.raises(ValueError):
        store.write_bytes("../escape", b"bad")
    with pytest.raises(ValueError):
        store.write_bytes("/absolute", b"bad")


def test_write_and_link_or_copy(tmp_path: Path):
    store = OutputStore(tmp_path)
    target, written = store.write_bytes("raw/a.png", b"png")
    assert written and target.read_bytes() == b"png"
    target, written = store.write_bytes("raw/a.png", b"png")
    assert not written
    linked, mode = store.link_or_copy(target, "curated/a.png")
    assert linked.read_bytes() == b"png"
    assert mode in {"hardlink", "copy"}


def test_jsonl_is_utf8(tmp_path: Path):
    store = OutputStore(tmp_path)
    store.write_jsonl("manifest/entries.jsonl", [{"name": "百闻牌"}])
    assert "百闻牌" in (tmp_path / "manifest/entries.jsonl").read_text(encoding="utf-8")
