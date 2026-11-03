from pathlib import Path
import struct
import zlib

import pytest

from bwp_extractor.pipeline import ExtractionPipeline
from test_textures import make_png


def npk_with(entries: list[tuple[int, bytes]]) -> bytes:
    payloads = bytearray()
    indices = bytearray()
    for signature, raw in entries:
        packed = zlib.compress(raw)
        offset = 24 + len(payloads)
        payloads.extend(packed)
        indices.extend(struct.pack("<7I", signature, offset, len(packed), len(raw),
                                   0, 0, 0))
    header = b"NXPK" + struct.pack("<5I", len(entries), 0, 0, 0, 24 + len(payloads))
    return bytes(header + payloads + indices)


def test_extracts_and_reuses_valid_output(tmp_path: Path):
    source = tmp_path / "sample.npk"
    source.write_bytes(npk_with([(1, make_png() + bytes(8))]))
    output = tmp_path / "out"
    pipeline = ExtractionPipeline(output)
    first = pipeline.run(source)
    assert first[0].status == "success"
    assert first[0].raw_path == "raw/sample.npk/00000001.png"
    raw = output / first[0].raw_path
    before = raw.stat().st_mtime_ns
    second = ExtractionPipeline(output).run(source)
    assert second[0].raw_path == first[0].raw_path
    assert raw.stat().st_mtime_ns == before


def test_changed_source_does_not_use_stale_cache(tmp_path: Path):
    source = tmp_path / "sample.npk"
    source.write_bytes(npk_with([(1, make_png() + bytes(8))]))
    output = tmp_path / "out"
    ExtractionPipeline(output).run(source)
    changed = make_png() + bytes(9)
    source.write_bytes(npk_with([(1, changed)]))
    record = ExtractionPipeline(output).run(source)[0]
    assert (output / record.raw_path).read_bytes() == changed


def test_patch_priority_controls_curated_output(tmp_path: Path):
    base = make_png() + b"base"
    patch = make_png() + b"patch"
    (tmp_path / "base.npk").write_bytes(npk_with([(1, base)]))
    (tmp_path / "patch.npk").write_bytes(npk_with([(1, patch)]))
    names = tmp_path / "names.json"
    names.write_text('{"00000001": "cards/a.png"}', encoding="utf-8")
    output = tmp_path / "out"
    pipeline = ExtractionPipeline(output, names, ["patch.npk"])
    records = pipeline.run(tmp_path)
    patch_record = next(r for r in records if r.archive == "patch.npk")
    assert (output / patch_record.curated_path).read_bytes() == patch
    assert pipeline.duplicates[0]["signature"] == "00000001"


def test_base_change_keeps_cached_patch_curated_without_reconversion(tmp_path: Path):
    original = make_png() + b"base-one"
    changed = make_png() + b"base-two"
    patch = make_png() + b"patch"
    base = tmp_path / "base.npk"
    base.write_bytes(npk_with([(1, original)]))
    (tmp_path / "patch.npk").write_bytes(npk_with([(1, patch)]))
    names = tmp_path / "names.json"
    names.write_text('{"00000001": "cards/a.png"}', encoding="utf-8")
    output = tmp_path / "out"
    first = ExtractionPipeline(output, names, ["patch.npk"]).run(tmp_path)
    patch_record = next(r for r in first if r.archive == "patch.npk")
    converted = output / patch_record.converted_path
    before = converted.stat().st_mtime_ns

    base.write_bytes(npk_with([(1, changed)]))
    records = ExtractionPipeline(output, names, ["patch.npk"]).run(tmp_path)

    patch_record = next(r for r in records if r.archive == "patch.npk")
    assert (output / patch_record.curated_path).read_bytes() == patch
    assert converted.stat().st_mtime_ns == before


def test_cached_raw_provides_name_for_reextracted_entry(tmp_path: Path):
    from bwp_extractor.names import NameResolver

    candidate = "ui/cached.txt"
    signature = NameResolver.signature(candidate)
    source = tmp_path / "sample.npk"
    source.write_bytes(npk_with([(1, candidate.encode()), (signature, b"target")]))
    output = tmp_path / "out"
    first = ExtractionPipeline(output).run(source)
    target = next(r for r in first if r.signature == f"{signature:08x}")
    target_raw = output / target.raw_path
    target_raw.unlink()
    target_raw.write_bytes(b"tampered")

    records = ExtractionPipeline(output).run(source)

    target = next(r for r in records if r.signature == f"{signature:08x}")
    assert target.name_status == "resolved"
    assert target.curated_path == "ui/ui/cached.txt"
    assert (output / target.curated_path).read_bytes() == b"target"


def test_tampered_converted_and_curated_outputs_are_rebuilt(tmp_path: Path):
    from hashlib import sha256

    payload = make_png() + b"image"
    source = tmp_path / "sample.npk"
    source.write_bytes(npk_with([(1, payload)]))
    names = tmp_path / "names.json"
    names.write_text('{"00000001": "cards/a.png"}', encoding="utf-8")
    output = tmp_path / "out"
    record = ExtractionPipeline(output, names).run(source)[0]

    for relative in (record.converted_path, record.curated_path):
        tampered = output / relative
        tampered.unlink()
        tampered.write_bytes(b"tampered")
        record = ExtractionPipeline(output, names).run(source)[0]
        assert tampered.read_bytes() == payload
        assert record.converted_sha256 == sha256(payload).hexdigest()
        assert record.curated_sha256 == sha256(payload).hexdigest()


def test_changed_names_mapping_rebuilds_curated_output(tmp_path: Path):
    payload = make_png() + b"image"
    source = tmp_path / "sample.npk"
    source.write_bytes(npk_with([(1, payload)]))
    names = tmp_path / "names.json"
    names.write_text('{"00000001": "cards/a.png"}', encoding="utf-8")
    output = tmp_path / "out"
    ExtractionPipeline(output, names).run(source)

    names.write_text('{"00000001": "cards/b.png"}', encoding="utf-8")
    record = ExtractionPipeline(output, names).run(source)[0]

    assert record.curated_path == "cards/cards/b.png"
    assert (output / record.curated_path).read_bytes() == payload


def test_changed_patch_order_rebuilds_curated_output(tmp_path: Path):
    base = make_png() + b"base"
    first_patch = make_png() + b"first"
    second_patch = make_png() + b"second"
    (tmp_path / "base.npk").write_bytes(npk_with([(1, base)]))
    (tmp_path / "first.npk").write_bytes(npk_with([(1, first_patch)]))
    (tmp_path / "second.npk").write_bytes(npk_with([(1, second_patch)]))
    names = tmp_path / "names.json"
    names.write_text('{"00000001": "cards/a.png"}', encoding="utf-8")
    output = tmp_path / "out"
    ExtractionPipeline(output, names, ["first.npk", "second.npk"]).run(tmp_path)

    records = ExtractionPipeline(output, names, ["second.npk", "first.npk"]).run(tmp_path)

    record = next(r for r in records if r.archive == "first.npk")
    assert (output / record.curated_path).read_bytes() == first_patch


def test_conversion_failure_is_not_reused_as_success(tmp_path: Path, monkeypatch):
    from bwp_extractor.textures import TextureConverter

    source = tmp_path / "sample.npk"
    source.write_bytes(npk_with([(1, make_png() + b"image")]))
    output = tmp_path / "out"
    original = TextureConverter.convert

    def fail_conversion(*args):
        raise RuntimeError("conversion unavailable")

    monkeypatch.setattr(TextureConverter, "convert", fail_conversion)
    failed = ExtractionPipeline(output).run(source)[0]
    assert failed.status == "conversion_failed"

    monkeypatch.setattr(TextureConverter, "convert", original)
    recovered = ExtractionPipeline(output).run(source)[0]
    assert recovered.status == "success"
    assert (output / recovered.converted_path).is_file()


def install_versioned_ktx_tool(monkeypatch, state):
    import subprocess

    monkeypatch.setattr("bwp_extractor.textures.shutil.which", lambda name: f"tools/{name}")

    def fake_run(command, check, capture_output, text):
        if command[1] == "--version":
            if state.get("version_error"):
                raise subprocess.CalledProcessError(1, command)
            return subprocess.CompletedProcess(command, 0, stdout=state["version"], stderr="")
        Path(command[-1]).write_bytes(state["version"].encode())
        state.setdefault("extractions", 0)
        state["extractions"] += 1
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("bwp_extractor.textures.subprocess.run", fake_run)


def test_ktx_tool_version_change_invalidates_cached_output(tmp_path: Path, monkeypatch):
    state = {"version": "ktx-v1"}
    install_versioned_ktx_tool(monkeypatch, state)
    source = tmp_path / "sample.npk"
    source.write_bytes(npk_with([(1, b"\xabKTX 20\xbb\r\n\x1a\n" + bytes(8))]))
    output = tmp_path / "out"

    first = ExtractionPipeline(output).run(source)[0]
    converted = output / first.converted_path
    assert converted.read_bytes() == b"ktx-v1"
    ExtractionPipeline(output).run(source)
    assert state["extractions"] == 1

    state["version"] = "ktx-v2"
    changed = ExtractionPipeline(output).run(source)[0]

    assert changed.status == "success"
    assert converted.read_bytes() == b"ktx-v2"
    assert state["extractions"] == 2


@pytest.mark.parametrize("failure", ["missing", "version_error"])
def test_unavailable_ktx_tool_does_not_reuse_cached_output(tmp_path: Path, monkeypatch, failure):
    import subprocess

    state = {"version": "ktx-v1"}
    install_versioned_ktx_tool(monkeypatch, state)
    source = tmp_path / "sample.npk"
    source.write_bytes(npk_with([(1, b"\xabKTX 20\xbb\r\n\x1a\n" + bytes(8))]))
    output = tmp_path / "out"
    assert ExtractionPipeline(output).run(source)[0].status == "success"

    if failure == "missing":
        monkeypatch.setattr("bwp_extractor.textures.shutil.which", lambda name: None)
    else:
        state["version_error"] = True
    record = ExtractionPipeline(output).run(source)[0]

    assert record.status == "conversion_failed"
    assert record.converted_path is None
