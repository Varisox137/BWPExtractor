from pathlib import Path
from zipfile import ZipFile

import pytest

from bwp_extractor.sources import open_source


def test_discovers_local_and_zip_npk(tmp_path: Path):
    single = tmp_path / "one.npk"
    single.write_bytes(b"NXPK-one")
    archive = tmp_path / "client.apk"
    with ZipFile(archive, "w") as z:
        z.writestr("assets/res/two.npk", b"NXPK-two")
        z.writestr("assets/readme.txt", b"ignored")

    assert [a.relative_name for a in open_source(single).archives()] == ["one.npk"]
    zipped = open_source(archive).archives()
    assert [a.relative_name for a in zipped] == ["assets/res/two.npk"]
    with zipped[0].open() as stream:
        assert stream.read() == b"NXPK-two"
    identity = zipped[0].identity()
    assert identity.size == 8
    assert len(identity.sha256) == 64


def test_directory_order_is_stable(tmp_path: Path):
    (tmp_path / "b.npk").write_bytes(b"b")
    (tmp_path / "a.npk").write_bytes(b"a")
    assert [a.relative_name for a in open_source(tmp_path).archives()] == ["a.npk", "b.npk"]


def test_rejects_duplicate_zip_npk_members(tmp_path: Path):
    archive = tmp_path / "duplicate.zip"
    with ZipFile(archive, "w") as z:
        z.writestr("assets/res/duplicate.npk", b"first")
        with pytest.warns(UserWarning, match="Duplicate name"):
            z.writestr("assets/res/duplicate.npk", b"second")

    with pytest.raises(ValueError, match="Duplicate NPK member"):
        open_source(archive).archives()


def test_directory_ignores_npk_directories(tmp_path: Path):
    (tmp_path / "directory.npk").mkdir()
    (tmp_path / "file.npk").write_bytes(b"content")

    assert [a.relative_name for a in open_source(tmp_path).archives()] == ["file.npk"]


def test_nested_directory_archive_names_are_posix(tmp_path: Path):
    nested = tmp_path / "patches" / "nested"
    nested.mkdir(parents=True)
    (nested / "high.npk").write_bytes(b"content")

    assert [a.relative_name for a in open_source(tmp_path).archives()] == [
        "patches/nested/high.npk",
    ]
