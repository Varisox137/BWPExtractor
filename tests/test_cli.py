import json
from pathlib import Path

from bwp_extractor.cli import main
from test_pipeline import npk_with


PNG = b"\x89PNG\r\n\x1a\n" + bytes(8)
ATLAS = (b"hero.png\nsize: 4,4\nformat: RGBA8888\nfilter: Linear,Linear\n"
         b"repeat: none\nbody\n  bounds: 0,0,4,4\n")


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

    assert not (tmp_path / "output").exists()
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
