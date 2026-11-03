from pathlib import Path
import struct
import subprocess

from PIL import Image
import pytest

from bwp_extractor.models import ResourceKind
from bwp_extractor.output import OutputStore
from bwp_extractor.textures import TextureConverter


def test_png_is_copied_without_reencoding(tmp_path: Path):
    store = OutputStore(tmp_path)
    raw, _ = store.write_bytes("raw/a.png", b"original-png-bytes")
    output = TextureConverter(store).convert(raw, ResourceKind.PNG, "converted/a.png")
    assert output.read_bytes() == b"original-png-bytes"


def test_uncompressed_dds_to_png(tmp_path: Path):
    store = OutputStore(tmp_path)
    header = bytearray(128)
    header[:4] = b"DDS "
    struct.pack_into("<I", header, 4, 124)
    struct.pack_into("<I", header, 12, 1)
    struct.pack_into("<I", header, 16, 1)
    struct.pack_into("<I", header, 76, 32)
    struct.pack_into("<I", header, 80, 0x41)
    struct.pack_into("<I", header, 88, 32)
    struct.pack_into("<I", header, 108, 0x00FF0000)
    struct.pack_into("<I", header, 112, 0x0000FF00)
    struct.pack_into("<I", header, 116, 0x000000FF)
    struct.pack_into("<I", header, 120, 0xFF000000)
    raw, _ = store.write_bytes("raw/a.dds", bytes(header) + bytes([0, 0, 255, 255]))
    output = TextureConverter(store).convert(raw, ResourceKind.DDS, "converted/a.png")
    with Image.open(output) as image:
        assert image.size == (1, 1)


def test_unknown_kind_fails(tmp_path: Path):
    store = OutputStore(tmp_path)
    raw, _ = store.write_bytes("raw/a.bin", b"bin")
    with pytest.raises(ValueError):
        TextureConverter(store).convert(raw, ResourceKind.BINARY, "converted/a.png")


def install_fake_ktx_tools(monkeypatch: pytest.MonkeyPatch, commands: list[list[str]], fail=False):
    monkeypatch.setattr("bwp_extractor.textures.shutil.which", lambda name: f"tools/{name}")

    def fake_run(command, check, capture_output, text):
        assert check and capture_output and text
        commands.append(command)
        if command[1] == "extract":
            if fail:
                raise subprocess.CalledProcessError(1, command)
            Path(command[-1]).write_bytes(b"converted-png")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("bwp_extractor.textures.subprocess.run", fake_run)


def test_ktx1_is_upgraded_then_extracted_at_level_zero(tmp_path: Path, monkeypatch):
    store = OutputStore(tmp_path)
    raw, _ = store.write_bytes("raw/a.ktx", b"original-ktx")
    commands = []
    install_fake_ktx_tools(monkeypatch, commands)

    output = TextureConverter(store).convert(raw, ResourceKind.KTX1, "converted/a.png")

    assert output.read_bytes() == b"converted-png"
    assert raw.read_bytes() == b"original-ktx"
    assert commands[0][1:3] == ["-f", "-o"]
    assert commands[0][-1] == str(raw)
    assert commands[1][1:4] == ["extract", "--level", "0"]
    assert commands[0][3] == commands[1][4]


def test_ktx2_is_extracted_directly_at_level_zero(tmp_path: Path, monkeypatch):
    store = OutputStore(tmp_path)
    raw, _ = store.write_bytes("raw/a.ktx2", b"original-ktx2")
    commands = []
    install_fake_ktx_tools(monkeypatch, commands)

    output = TextureConverter(store).convert(raw, ResourceKind.KTX2, "converted/a.png")

    assert output.read_bytes() == b"converted-png"
    assert raw.read_bytes() == b"original-ktx2"
    assert len(commands) == 1
    assert commands[0][1:4] == ["extract", "--level", "0"]
    assert commands[0][4] == str(raw)


def test_failed_ktx_conversion_preserves_existing_output(tmp_path: Path, monkeypatch):
    store = OutputStore(tmp_path)
    raw, _ = store.write_bytes("raw/a.ktx2", b"original-ktx2")
    target, _ = store.write_bytes("converted/a.png", b"existing-output")
    commands = []
    install_fake_ktx_tools(monkeypatch, commands, fail=True)

    with pytest.raises(subprocess.CalledProcessError):
        TextureConverter(store).convert(raw, ResourceKind.KTX2, "converted/a.png")

    assert target.read_bytes() == b"existing-output"
