from io import BytesIO
from pathlib import Path
import struct
import subprocess

from PIL import Image
import pytest

from bwp_extractor.models import ResourceKind
from bwp_extractor.output import OutputStore
from bwp_extractor.textures import TextureConverter


def make_png(color=(255, 0, 0, 255)) -> bytes:
    buffer = BytesIO()
    Image.new("RGBA", (1, 1), color).save(buffer, "PNG")
    return buffer.getvalue()


def test_png_is_copied_without_reencoding(tmp_path: Path):
    store = OutputStore(tmp_path)
    original = make_png()
    raw, _ = store.write_bytes("raw/a.png", original)
    output = TextureConverter(store).convert(raw, ResourceKind.PNG, "converted/a.png")
    assert output.read_bytes() == original
    assert raw.read_bytes() == original


@pytest.mark.parametrize("damage", ["truncated", "crc"])
def test_invalid_png_is_rejected_before_output(tmp_path: Path, damage: str):
    data = bytearray(make_png())
    if damage == "truncated":
        del data[len(data) // 2:]
    else:
        data[29] ^= 1
    store = OutputStore(tmp_path)
    raw, _ = store.write_bytes("raw/a.png", bytes(data))

    with pytest.raises(ValueError, match="Invalid PNG"):
        TextureConverter(store).convert(raw, ResourceKind.PNG, "converted/a.png")

    assert not (tmp_path / "converted/a.png").exists()
    assert raw.read_bytes() == bytes(data)


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
        if command[1] == "--version":
            return subprocess.CompletedProcess(command, 0, stdout="ktx-v1", stderr="")
        commands.append(command)
        if command[1] == "extract":
            if fail:
                raise subprocess.CalledProcessError(1, command)
            Path(command[-1]).write_bytes(b"converted-png")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

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


def make_ktx1(
    internal_format: int, payload: bytes, *, width=4, height=4, key_value=b"",
    depth=0, array_elements=0, faces=1,
) -> bytes:
    header = bytearray(64)
    header[:12] = b"\xabKTX 11\xbb\r\n\x1a\n"
    struct.pack_into(
        "<13I", header, 12,
        0x04030201, 0, 1, 0, internal_format, 0x1908, width, height,
        depth, array_elements, faces, 1, len(key_value),
    )
    return bytes(header) + key_value + struct.pack("<I", len(payload)) + payload


def set_selectors(block: bytes, selectors: dict[tuple[int, int], int]) -> bytes:
    bits = 0
    for (x, y), selected in selectors.items():
        pixel = x * 4 + y
        bits |= (selected & 1) << pixel
        bits |= ((selected >> 1) & 1) << (pixel + 16)
    return block[:4] + bits.to_bytes(4, "big")


def make_alpha_block(base: int, multiplier: int, table: int, selectors) -> bytes:
    if isinstance(selectors, int):
        selectors = {(x, y): selectors for x in range(4) for y in range(4)}
    indices = 0
    for (x, y), selected in selectors.items():
        indices |= selected << (3 * (15 - (x * 4 + y)))
    return bytes([base, (multiplier << 4) | table]) + indices.to_bytes(6, "big")


def solid_etc1(value: int) -> bytes:
    return bytes([value * 17] * 3) + bytes(5)


def convert_ktx1_data(tmp_path: Path, data: bytes) -> Image.Image:
    store = OutputStore(tmp_path)
    raw, _ = store.write_bytes("raw/a.ktx", data)
    output = TextureConverter(store).convert(raw, ResourceKind.KTX1, "converted/a.png")
    return Image.open(output)


def convert_synthetic_ktx1(
    tmp_path: Path, internal_format: int, payload: bytes, **options,
) -> Image.Image:
    return convert_ktx1_data(tmp_path, make_ktx1(internal_format, payload, **options))


def test_etc1_ktx1_is_decoded_without_ktx_cli(tmp_path: Path):
    with convert_synthetic_ktx1(tmp_path, 0x8D64, solid_etc1(1)) as image:
        assert image.mode == "RGBA"
        assert image.size == (4, 4)
        assert image.getpixel((0, 0)) == (19, 19, 19, 255)
        assert len(image.getcolors(16)) == 1


def test_etc2_t_mode_uses_unpacked_red_and_all_selectors(tmp_path: Path):
    color = set_selectors(
        bytes([0x14, 0x23, 0x45, 0x62, 0, 0, 0, 0]),
        {(1, 0): 1, (2, 0): 2, (3, 0): 3},
    )
    with convert_synthetic_ktx1(tmp_path, 0x9274, color) as image:
        assert image.getpixel((0, 0)) == (136, 34, 51, 255)
        assert image.getpixel((1, 0)) == (71, 88, 105, 255)
        assert image.getpixel((2, 0)) == (68, 85, 102, 255)
        assert image.getpixel((3, 0)) == (65, 82, 99, 255)


def test_etc2_h_mode_orders_colors_and_uses_all_selectors(tmp_path: Path):
    color = set_selectors(
        bytes([0x11, 0xF3, 0x45, 0x62, 0, 0, 0, 0]),
        {(1, 0): 1, (2, 0): 2, (3, 0): 3},
    )
    with convert_synthetic_ktx1(tmp_path, 0x9274, color) as image:
        assert image.getpixel((0, 0)) == (159, 255, 57, 255)
        assert image.getpixel((1, 0)) == (147, 249, 45, 255)
        assert image.getpixel((2, 0)) == (74, 91, 108, 255)
        assert image.getpixel((3, 0)) == (62, 79, 96, 255)


def test_etc2_h_mode_color0_below_color1_clears_distance_low_bit(tmp_path: Path):
    color = set_selectors(
        bytes([0x01, 0xF3, 0xF4, 0x52, 0, 0, 0, 0]), {(2, 0): 2},
    )
    with convert_synthetic_ktx1(tmp_path, 0x9274, color) as image:
        assert image.getpixel((0, 0)) == (20, 255, 54, 255)
        assert image.getpixel((2, 0)) == (255, 71, 88, 255)


def test_eac_alpha_applies_positive_and_negative_modifiers(tmp_path: Path):
    alpha = make_alpha_block(100, 2, 0, {(1, 0): 1, (2, 0): 4, (3, 0): 7})
    color = bytes([0xF9, 0x23, 0x45, 0x62, 0, 0, 0, 0])
    with convert_synthetic_ktx1(tmp_path, 0x9278, alpha + color) as image:
        assert image.getpixel((0, 0))[3] == 94
        assert image.getpixel((1, 0))[3] == 88
        assert image.getpixel((2, 0))[3] == 104
        assert image.getpixel((3, 0))[3] == 128


def test_individual_mode_uses_flip_tables_and_selectors(tmp_path: Path):
    color = set_selectors(
        bytes([0x28, 0x4A, 0x6C, 0x05, 0, 0, 0, 0]),
        {(1, 0): 2, (0, 2): 1, (1, 2): 3},
    )
    with convert_synthetic_ktx1(tmp_path, 0x8D64, color) as image:
        assert image.getpixel((0, 0)) == (36, 70, 104, 255)
        assert image.getpixel((1, 0)) == (32, 66, 100, 255)
        assert image.getpixel((0, 2)) == (153, 187, 221, 255)
        assert image.getpixel((1, 2)) == (119, 153, 187, 255)


def test_differential_mode_uses_subblocks_tables_and_selectors(tmp_path: Path):
    color = set_selectors(
        bytes([0x51, 0x67, 0x72, 0x4E, 0, 0, 0, 0]),
        {(1, 0): 2, (2, 0): 1, (3, 0): 3},
    )
    with convert_synthetic_ktx1(tmp_path, 0x8D64, color) as image:
        assert image.getpixel((0, 0)) == (91, 108, 124, 255)
        assert image.getpixel((1, 0)) == (73, 90, 106, 255)
        assert image.getpixel((2, 0)) == (132, 132, 174, 255)
        assert image.getpixel((3, 0)) == (48, 48, 90, 255)


def test_etc2_planar_mode_is_decoded(tmp_path: Path):
    color = bytes.fromhex("2221041ffdcf985a")
    with convert_synthetic_ktx1(tmp_path, 0x9274, color) as image:
        assert image.getpixel((0, 0)) == (69, 32, 130, 255)
        assert image.getpixel((3, 0)) == (62, 198, 206, 255)
        assert image.getpixel((0, 3)) == (200, 154, 111, 255)


def test_multiple_blocks_edge_crop_and_key_value_offset(tmp_path: Path):
    payload = b"".join(solid_etc1(value) for value in (1, 2, 3, 4))
    with convert_synthetic_ktx1(
        tmp_path, 0x8D64, payload, width=5, height=6, key_value=b"test",
    ) as image:
        assert image.size == (5, 6)
        assert image.getpixel((0, 0)) == (19, 19, 19, 255)
        assert image.getpixel((4, 0)) == (36, 36, 36, 255)
        assert image.getpixel((0, 5)) == (53, 53, 53, 255)
        assert image.getpixel((4, 5)) == (70, 70, 70, 255)


def test_truncated_etc_ktx1_level_is_rejected(tmp_path: Path):
    data = make_ktx1(0x8D64, solid_etc1(1))[:64]
    with pytest.raises(ValueError, match="^Truncated ETC KTX1 level$"):
        convert_ktx1_data(tmp_path, data)


def test_truncated_etc_ktx1_data_is_rejected(tmp_path: Path):
    data = make_ktx1(0x8D64, solid_etc1(1))[:-1]
    with pytest.raises(ValueError, match="^Truncated ETC KTX1 data$"):
        convert_ktx1_data(tmp_path, data)


@pytest.mark.parametrize("options", [
    {"width": 0}, {"height": 0}, {"depth": 1}, {"array_elements": 1}, {"faces": 2},
])
def test_unsupported_etc_ktx1_dimensions_are_rejected(tmp_path: Path, options):
    with pytest.raises(ValueError, match="^Unsupported ETC KTX1 dimensions$"):
        convert_synthetic_ktx1(tmp_path, 0x8D64, solid_etc1(1), **options)


@pytest.mark.parametrize("options", [
    {"width": 0xFFFFFFFF, "height": 0xFFFFFFFF},
    {"width": 16385, "height": 1},
])
def test_etc_dimensions_exceeding_memory_limits_are_rejected_before_allocation(
    tmp_path: Path, options,
):
    with pytest.raises(ValueError, match="^ETC KTX1 dimensions exceed limits$"):
        convert_synthetic_ktx1(tmp_path, 0x8D64, solid_etc1(1), **options)
