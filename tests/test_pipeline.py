from pathlib import Path
import struct
import zlib

from bwp_extractor.pipeline import ExtractionPipeline


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
    source.write_bytes(npk_with([(1, b"\x89PNG\r\n\x1a\n" + bytes(8))]))
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
    source.write_bytes(npk_with([(1, b"\x89PNG\r\n\x1a\n" + bytes(8))]))
    output = tmp_path / "out"
    ExtractionPipeline(output).run(source)
    source.write_bytes(npk_with([(1, b"\x89PNG\r\n\x1a\n" + bytes(9))]))
    record = ExtractionPipeline(output).run(source)[0]
    assert (output / record.raw_path).stat().st_size == 17


def test_patch_priority_controls_curated_output(tmp_path: Path):
    base = b"\x89PNG\r\n\x1a\n" + b"base"
    patch = b"\x89PNG\r\n\x1a\n" + b"patch"
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
