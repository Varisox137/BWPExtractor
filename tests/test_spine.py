from pathlib import Path

from bwp_extractor.output import OutputStore
from bwp_extractor.spine import build_spine_bundle, parse_atlas_pages


ATLAS = (b"hero.png\nsize: 4,4\nformat: RGBA8888\nfilter: Linear,Linear\n"
         b"repeat: none\nbody\n  bounds: 0,0,4,4\n")


def test_reads_atlas_pages():
    assert parse_atlas_pages(ATLAS) == ["hero.png"]


def test_builds_complete_spine_bundle(tmp_path: Path):
    store = OutputStore(tmp_path)
    for name, data in [("hero.atlas", ATLAS), ("hero.skel", b"skeleton"),
                       ("hero.png", b"png")]:
        store.write_bytes(f"raw/{name}", data)
    available = {f"spine/hero.{ext}": tmp_path / f"raw/hero.{ext}"
                 for ext in ("atlas", "skel", "png")}
    bundle = build_spine_bundle(store, "spine/hero.atlas", ATLAS, available)
    assert bundle.missing == ()
    assert (tmp_path / "curated/spine/hero/hero.skel").read_bytes() == b"skeleton"


def test_uses_json_skeleton_when_skel_is_unavailable(tmp_path: Path):
    store = OutputStore(tmp_path)
    for name, data in [("hero.atlas", ATLAS), ("hero.json", b"skeleton"),
                       ("hero.png", b"png")]:
        store.write_bytes(f"raw/{name}", data)
    available = {f"spine/hero.{ext}": tmp_path / f"raw/hero.{ext}"
                 for ext in ("atlas", "json", "png")}
    bundle = build_spine_bundle(store, "spine/hero.atlas", ATLAS, available)
    assert bundle.missing == ()
    assert (tmp_path / "curated/spine/hero/hero.json").read_bytes() == b"skeleton"


def test_missing_page_is_reported(tmp_path: Path):
    store = OutputStore(tmp_path)
    store.write_bytes("raw/hero.atlas", ATLAS)
    bundle = build_spine_bundle(store, "spine/hero.atlas", ATLAS,
                                {"spine/hero.atlas": tmp_path / "raw/hero.atlas"})
    assert bundle.missing == ("spine/hero.png", "spine/hero.skel")
