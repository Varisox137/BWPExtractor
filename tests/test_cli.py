import json
from pathlib import Path
import struct

import pytest

from bwp_extractor.cli import main
from test_pipeline import npk_with
from test_textures import make_png


PNG = make_png()
ATLAS = (b"hero.png\nsize: 4,4\nformat: RGBA8888\nfilter: Linear,Linear\n"
         b"repeat: none\nbody\n  bounds: 0,0,4,4\n")


def npk_entry(signature: int, packed: bytes, raw_size: int, flags: int = 0) -> bytes:
    index = struct.pack("<7I", signature, 24, len(packed), raw_size, 0, 0, flags)
    header = b"NXPK" + struct.pack("<5I", 1, 0, 0, 0, 24 + len(packed))
    return header + packed + index


def write_spine_source(tmp_path: Path, skeleton_extension: str = "skel"):
    source = tmp_path / "a.npk"
    source.write_bytes(npk_with([
        (1, ATLAS),
        (2, PNG),
        (3, b'{"bones":[]}' if skeleton_extension == "json" else b"skeleton"),
    ]))
    names = tmp_path / "names.json"
    names.write_text(json.dumps({
        "00000001": "spine/hero.atlas",
        "00000002": "spine/hero.png",
        "00000003": f"spine/hero.{skeleton_extension}",
    }), encoding="utf-8")
    return source, names


def test_extract_command_writes_report(tmp_path: Path):
    source = tmp_path / "a.npk"
    source.write_bytes(npk_with([(1, PNG)]))
    output = tmp_path / "out"

    assert main(["extract", str(source), "--output", str(output)]) == 0

    assert (output / "manifest/entries.jsonl").is_file()
    report_path = output / "reports/run.json"
    assert report_path.is_file()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == {"success": 1}
    assert report["kinds"] == {"png": 1}
    assert report["failures"] == []
    assert report["spine_issues"] == []


def test_inspect_does_not_create_output(tmp_path: Path, capsys):
    source = tmp_path / "a.npk"
    source.write_bytes(npk_with([(1, PNG)]))

    assert main(["inspect", str(source)]) == 0

    assert set(tmp_path.iterdir()) == {source}
    summary = json.loads(capsys.readouterr().out)
    assert summary == {
        "entries": 1,
        "status": {"success": 1},
        "kinds": {"png": 1},
        "archive_issues": [],
    }


def test_inspect_returns_failure_for_invalid_archive(tmp_path: Path, capsys):
    source = tmp_path / "broken.npk"
    source.write_bytes(b"not an npk")

    assert main(["inspect", str(source)]) == 1

    summary = json.loads(capsys.readouterr().out)
    assert summary["entries"] == 0
    assert summary["archive_issues"][0]["archive"] == "broken.npk"


def test_extract_names_and_patch_arguments(tmp_path: Path):
    source = tmp_path / "input"
    source.mkdir()
    base = PNG + b"base"
    patch = PNG + b"patch"
    (source / "base.npk").write_bytes(npk_with([(1, base)]))
    (source / "patch.npk").write_bytes(npk_with([(1, patch)]))
    names = tmp_path / "names.json"
    names.write_text('{"00000001": "cards/a.png"}', encoding="utf-8")
    output = tmp_path / "out"

    assert main([
        "extract", str(source), "--output", str(output),
        "--names", str(names), "--patch", "patch.npk",
    ]) == 0

    assert (output / "cards/cards/a.png").read_bytes() == patch


def test_extract_report_includes_spine_missing_files(tmp_path: Path):
    source = tmp_path / "a.npk"
    source.write_bytes(npk_with([(1, ATLAS)]))
    names = tmp_path / "names.json"
    names.write_text('{"00000001": "spine/hero.atlas"}', encoding="utf-8")
    output = tmp_path / "out"

    assert main([
        "extract", str(source), "--output", str(output), "--names", str(names),
    ]) == 0

    report = json.loads((output / "reports/run.json").read_text(encoding="utf-8"))
    assert report["spine_issues"] == [{
        "atlas": "spine/hero.atlas",
        "missing": ["spine/hero.png", "spine/hero.skel"],
    }]


@pytest.mark.parametrize("status", ["unsupported", "corrupt", "conversion_failed"])
def test_extract_entry_failure_exit_code_and_report(tmp_path: Path, monkeypatch, status: str):
    source = tmp_path / "a.npk"
    if status == "unsupported":
        source.write_bytes(npk_entry(1, b"packed", 6, flags=2))
    elif status == "corrupt":
        source.write_bytes(npk_entry(1, b"invalid", 7, flags=1))
    else:
        source.write_bytes(npk_with([(1, PNG)]))
        from bwp_extractor.textures import TextureConverter

        def fail_conversion(*args):
            raise RuntimeError("conversion unavailable")

        monkeypatch.setattr(TextureConverter, "convert", fail_conversion)
    output = tmp_path / "out"

    assert main(["extract", str(source), "--output", str(output)]) == 1

    report = json.loads((output / "reports/run.json").read_text(encoding="utf-8"))
    assert report["status"] == {status: 1}
    assert report["unresolved"] == 1
    assert len(report["failures"]) == 1
    failure = report["failures"][0]
    assert failure["archive"] == "a.npk"
    assert failure["signature"] == "00000001"
    assert failure["status"] == status
    assert failure["error"]


def test_extract_archive_error_exit_code_and_report(tmp_path: Path):
    source = tmp_path / "broken.npk"
    source.write_bytes(b"not an npk")
    output = tmp_path / "out"

    assert main(["extract", str(source), "--output", str(output)]) == 1

    report = json.loads((output / "reports/run.json").read_text(encoding="utf-8"))
    assert report["archive_issues"][0]["archive"] == "broken.npk"
    assert report["archive_issues"][0]["error"]
    assert report["failures"] == []
    assert report["unresolved"] == 0


def test_extract_multiple_patches_and_duplicates_report(tmp_path: Path):
    source = tmp_path / "input"
    source.mkdir()
    base = PNG + b"base"
    low = PNG + b"low"
    high = PNG + b"high"
    (source / "base.npk").write_bytes(npk_with([(1, base)]))
    (source / "low.npk").write_bytes(npk_with([(1, low)]))
    (source / "high.npk").write_bytes(npk_with([(1, high)]))
    names = tmp_path / "names.json"
    names.write_text('{"00000001": "cards/a.png"}', encoding="utf-8")
    output = tmp_path / "out"

    assert main([
        "extract", str(source), "--output", str(output), "--names", str(names),
        "--patch", "low.npk", "--patch", "high.npk",
    ]) == 0

    assert (output / "cards/cards/a.png").read_bytes() == high
    report = json.loads((output / "reports/run.json").read_text(encoding="utf-8"))
    assert [item["patch"] for item in report["duplicates"]] == [
        "low.npk:0:00000001", "high.npk:0:00000001",
    ]
    assert all(item["base"] == "base.npk:0:00000001" for item in report["duplicates"])


@pytest.mark.parametrize("skeleton_extension", ["skel", "json"])
def test_extract_builds_complete_spine_bundle_from_raw_and_converted(
    tmp_path: Path, monkeypatch, skeleton_extension: str,
):
    source, names = write_spine_source(tmp_path, skeleton_extension)
    output = tmp_path / "out"
    from bwp_extractor import pipeline as pipeline_module

    original = pipeline_module.build_spine_bundle
    captured = {}

    def capture_available(store, atlas_path, atlas_data, available):
        captured.update(available)
        return original(store, atlas_path, atlas_data, available)

    monkeypatch.setattr(pipeline_module, "build_spine_bundle", capture_available)

    assert main([
        "extract", str(source), "--output", str(output), "--names", str(names),
    ]) == 0

    bundle = output / "curated/spine/spine/hero"
    assert (bundle / "hero.atlas").read_bytes() == ATLAS
    assert (bundle / "hero.png").read_bytes() == PNG
    skeleton = b'{"bones":[]}' if skeleton_extension == "json" else b"skeleton"
    assert (bundle / f"hero.{skeleton_extension}").read_bytes() == skeleton
    assert captured["spine/hero.atlas"] == output / "raw/a.npk/00000001.atlas"
    assert captured["spine/hero.png"] == output / "converted/a.npk/00000002.png"
    raw_skeleton_suffix = "json" if skeleton_extension == "json" else "text"
    assert captured[f"spine/hero.{skeleton_extension}"] == (
        output / f"raw/a.npk/00000003.{raw_skeleton_suffix}"
    )
    report = json.loads((output / "reports/run.json").read_text(encoding="utf-8"))
    assert report["spine_issues"] == []


def test_unresolved_atlas_does_not_generate_spine_bundle(tmp_path: Path):
    source = tmp_path / "a.npk"
    source.write_bytes(npk_with([(1, ATLAS)]))
    output = tmp_path / "out"

    assert main(["extract", str(source), "--output", str(output)]) == 0

    assert (output / "raw/a.npk/00000001.atlas").is_file()
    assert not (output / "curated/spine").exists()
    report = json.loads((output / "reports/run.json").read_text(encoding="utf-8"))
    assert report["spine_issues"] == []
    assert report["unresolved"] == 1


def test_cached_extraction_rebuilds_spine_bundle(tmp_path: Path):
    source, names = write_spine_source(tmp_path)
    output = tmp_path / "out"
    arguments = ["extract", str(source), "--output", str(output), "--names", str(names)]
    assert main(arguments) == 0
    converted = output / "converted/a.npk/00000002.png"
    before = converted.stat().st_mtime_ns
    bundled_skeleton = output / "curated/spine/spine/hero/hero.skel"
    bundled_skeleton.unlink()

    assert main(arguments) == 0

    assert bundled_skeleton.read_bytes() == b"skeleton"
    assert converted.stat().st_mtime_ns == before


def test_nested_windows_patch_name_matches_posix_archive_name(tmp_path: Path):
    source = tmp_path / "input"
    nested = source / "patches" / "nested"
    nested.mkdir(parents=True)
    (source / "base.npk").write_bytes(npk_with([(1, PNG + b"base")]))
    (nested / "high.npk").write_bytes(npk_with([(1, PNG + b"patch")]))
    names = tmp_path / "names.json"
    names.write_text('{"00000001": "cards/a.png"}', encoding="utf-8")
    output = tmp_path / "out"

    assert main([
        "extract", str(source), "--output", str(output), "--names", str(names),
        "--patch", r"patches\nested\high.npk",
    ]) == 0

    assert (output / "cards/cards/a.png").read_bytes() == PNG + b"patch"
    report = json.loads((output / "reports/run.json").read_text(encoding="utf-8"))
    assert report["patch_issues"] == []


def test_unmatched_patch_name_is_reported_and_fails(tmp_path: Path):
    source = tmp_path / "a.npk"
    source.write_bytes(npk_with([(1, PNG)]))
    output = tmp_path / "out"

    assert main([
        "extract", str(source), "--output", str(output),
        "--patch", r"missing\nested.npk",
    ]) == 1

    report = json.loads((output / "reports/run.json").read_text(encoding="utf-8"))
    assert report["patch_issues"] == [{
        "patch": "missing/nested.npk",
        "error": "Patch archive not found",
    }]
