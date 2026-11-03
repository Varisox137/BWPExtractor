import os
from pathlib import Path, PurePosixPath

import pytest

from bwp_extractor.output import OutputStore
from bwp_extractor.spine import build_spine_bundle, parse_atlas_pages


ATLAS = (b"hero.png\nsize: 4,4\nformat: RGBA8888\nfilter: Linear,Linear\n"
         b"repeat: none\nbody\n  bounds: 0,0,4,4\n")


def test_reads_atlas_pages():
    assert parse_atlas_pages(ATLAS) == ["hero.png"]


def available_files(tmp_path: Path, atlas_path: str, atlas_data: bytes = ATLAS,
                    page_path: str = "spine/hero.png", skeleton_extension: str = "skel"):
    atlas = PurePosixPath(atlas_path)
    paths = {
        atlas_path: (atlas_path, atlas_data),
        str(atlas.with_suffix(f".{skeleton_extension}")): (
            str(atlas.with_suffix(f".{skeleton_extension}")), b"skeleton",
        ),
    }
    if page_path is not None:
        paths[page_path] = (page_path, b"page:" + page_path.encode())
    available = {}
    for name, (relative, data) in paths.items():
        target, _ = OutputStore(tmp_path / "sources").write_bytes(relative, data)
        available[name] = target
    return available


def test_builds_complete_spine_bundle(tmp_path: Path):
    store = OutputStore(tmp_path)
    available = available_files(tmp_path, "spine/hero.atlas")
    bundle = build_spine_bundle(store, "spine/hero.atlas", ATLAS, available)
    assert bundle.missing == ()
    assert (tmp_path / "curated/spine/spine/hero/hero.skel").read_bytes() == b"skeleton"


def test_uses_json_skeleton_when_skel_is_unavailable(tmp_path: Path):
    store = OutputStore(tmp_path)
    available = available_files(
        tmp_path, "spine/hero.atlas", skeleton_extension="json",
    )
    bundle = build_spine_bundle(store, "spine/hero.atlas", ATLAS, available)
    assert bundle.missing == ()
    assert (tmp_path / "curated/spine/spine/hero/hero.json").read_bytes() == b"skeleton"


def test_missing_page_is_reported(tmp_path: Path):
    store = OutputStore(tmp_path)
    store.write_bytes("raw/hero.atlas", ATLAS)
    bundle = build_spine_bundle(store, "spine/hero.atlas", ATLAS,
                                {"spine/hero.atlas": tmp_path / "raw/hero.atlas"})
    assert bundle.missing == ("spine/hero.png", "spine/hero.skel")


def test_same_stem_atlases_in_different_directories_do_not_overlap(tmp_path: Path):
    store = OutputStore(tmp_path)
    first_path = "characters/first/hero.atlas"
    second_path = "characters/second/hero.atlas"
    build_spine_bundle(
        store, first_path, ATLAS,
        available_files(tmp_path, first_path, page_path="characters/first/hero.png"),
    )
    build_spine_bundle(
        store, second_path, ATLAS,
        available_files(tmp_path, second_path, page_path="characters/second/hero.png"),
    )

    first = tmp_path / "curated/spine/characters/first/hero/hero.png"
    second = tmp_path / "curated/spine/characters/second/hero/hero.png"
    assert first.read_bytes() == b"page:characters/first/hero.png"
    assert second.read_bytes() == b"page:characters/second/hero.png"


def test_nested_atlas_page_preserves_its_relative_directory(tmp_path: Path):
    atlas_data = ATLAS.replace(b"hero.png", b"pages/back/hero.png")
    atlas_path = "spine/hero/hero.atlas"
    store = OutputStore(tmp_path)
    available = available_files(
        tmp_path, atlas_path, atlas_data, page_path="spine/hero/pages/back/hero.png",
    )

    bundle = build_spine_bundle(store, atlas_path, atlas_data, available)

    assert bundle.missing == ()
    page = tmp_path / "curated/spine/spine/hero/hero/pages/back/hero.png"
    assert page.read_bytes() == b"page:spine/hero/pages/back/hero.png"


def test_atlas_page_cannot_escape_bundle(tmp_path: Path):
    atlas_data = ATLAS.replace(b"hero.png", b"../outside.png")
    store = OutputStore(tmp_path)
    available = available_files(
        tmp_path, "spine/hero.atlas", atlas_data, page_path="spine/outside.png",
    )

    with pytest.raises(ValueError, match="Unsafe atlas page"):
        build_spine_bundle(store, "spine/hero.atlas", atlas_data, available)

    assert not (tmp_path / "curated").exists()


def test_rebuilding_bundle_removes_page_that_became_missing(tmp_path: Path):
    store = OutputStore(tmp_path)
    build_spine_bundle(
        store, "spine/hero.atlas", ATLAS, available_files(tmp_path, "spine/hero.atlas"),
    )
    page = tmp_path / "curated/spine/spine/hero/hero.png"
    assert page.is_file()

    available = available_files(tmp_path, "spine/hero.atlas", page_path=None)
    bundle = build_spine_bundle(store, "spine/hero.atlas", ATLAS, available)

    assert bundle.missing == ("spine/hero.png",)
    assert not page.exists()


def test_rebuilding_bundle_removes_renamed_page(tmp_path: Path):
    store = OutputStore(tmp_path)
    build_spine_bundle(
        store, "spine/hero.atlas", ATLAS, available_files(tmp_path, "spine/hero.atlas"),
    )
    old_page = tmp_path / "curated/spine/spine/hero/hero.png"
    renamed_data = ATLAS.replace(b"hero.png", b"renamed.png")
    available = available_files(
        tmp_path, "spine/hero.atlas", renamed_data, page_path="spine/renamed.png",
    )

    build_spine_bundle(store, "spine/hero.atlas", renamed_data, available)

    assert not old_page.exists()
    assert (tmp_path / "curated/spine/spine/hero/renamed.png").is_file()


def test_failed_bundle_replacement_restores_previous_bundle(tmp_path: Path, monkeypatch):
    store = OutputStore(tmp_path)
    build_spine_bundle(
        store, "spine/hero.atlas", ATLAS, available_files(tmp_path, "spine/hero.atlas"),
    )
    destination = tmp_path / "curated/spine/spine/hero"
    old_page = destination / "hero.png"
    before = old_page.read_bytes()
    real_replace = os.replace
    failed = False

    def fail_destination_once(source, target):
        nonlocal failed
        if Path(target) == destination and not failed:
            failed = True
            raise RuntimeError("replacement failed")
        return real_replace(source, target)

    monkeypatch.setattr(os, "replace", fail_destination_once)
    renamed_data = ATLAS.replace(b"hero.png", b"renamed.png")
    available = available_files(
        tmp_path, "spine/hero.atlas", renamed_data, page_path="spine/renamed.png",
    )

    with pytest.raises(RuntimeError, match="replacement failed"):
        build_spine_bundle(store, "spine/hero.atlas", renamed_data, available)

    assert old_page.read_bytes() == before
    assert not (destination / "renamed.png").exists()
