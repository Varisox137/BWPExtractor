from pathlib import Path

import pytest

from bwp_extractor.output import OutputStore


@pytest.mark.parametrize("relative", [
    "../escape",
    "/absolute",
    "C:/absolute",
    r"sub\..\file",
])
def test_rejects_path_traversal(tmp_path: Path, relative: str):
    store = OutputStore(tmp_path)
    with pytest.raises(ValueError):
        store.write_bytes(relative, b"bad")


def test_normalizes_windows_relative_path(tmp_path: Path):
    store = OutputStore(tmp_path)
    target, written = store.write_bytes(r"raw\a.png", b"png")
    assert written
    assert target == tmp_path / "raw" / "a.png"


def test_write_and_link_or_copy(tmp_path: Path):
    store = OutputStore(tmp_path)
    target, written = store.write_bytes("raw/a.png", b"png")
    assert written and target.read_bytes() == b"png"
    target, written = store.write_bytes("raw/a.png", b"png")
    assert not written
    linked, mode = store.link_or_copy(target, "curated/a.png")
    assert linked.read_bytes() == b"png"
    assert mode in {"hardlink", "copy"}


def test_link_or_copy_falls_back_to_copy(tmp_path: Path, monkeypatch):
    store = OutputStore(tmp_path)
    source, _ = store.write_bytes("raw/a.png", b"png")

    def fail_link(source, target):
        raise OSError("hard links unavailable")

    monkeypatch.setattr("bwp_extractor.output.os.link", fail_link)
    linked, mode = store.link_or_copy(source, "curated/a.png")
    assert linked.read_bytes() == b"png"
    assert mode == "copy"


def test_jsonl_is_utf8(tmp_path: Path):
    store = OutputStore(tmp_path)
    store.write_jsonl("manifest/entries.jsonl", [{"name": "百闻牌"}])
    assert "百闻牌" in (tmp_path / "manifest/entries.jsonl").read_text(encoding="utf-8")
