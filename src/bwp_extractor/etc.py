import struct

from PIL import Image


KTX1_IDENTIFIER = b"\xabKTX 11\xbb\r\n\x1a\n"
ETC1_RGB = 0x8D64
ETC2_RGB = 0x9274
ETC2_RGBA = 0x9278
MAX_TEXTURE_DIMENSION = 16384
MAX_TEXTURE_PIXEL_BYTES = 256 * 1024 * 1024

MODIFIERS = (
    (2, 8), (5, 17), (9, 29), (13, 42),
    (18, 60), (24, 80), (33, 106), (47, 183),
)
DISTANCES = (3, 6, 11, 16, 23, 32, 41, 64)
ALPHA_MODIFIERS = (
    (-3, -6, -9, -15, 2, 5, 8, 14),
    (-3, -7, -10, -13, 2, 6, 9, 13),
    (-2, -5, -8, -13, 1, 4, 7, 12),
    (-2, -4, -6, -13, 1, 3, 5, 12),
    (-3, -6, -8, -12, 2, 5, 7, 11),
    (-3, -7, -9, -11, 2, 6, 8, 10),
    (-4, -7, -8, -11, 3, 6, 7, 10),
    (-3, -5, -8, -11, 2, 4, 7, 10),
    (-2, -6, -8, -10, 1, 5, 7, 9),
    (-2, -5, -8, -10, 1, 4, 7, 9),
    (-2, -4, -8, -10, 1, 3, 7, 9),
    (-2, -5, -7, -10, 1, 4, 6, 9),
    (-3, -4, -7, -10, 2, 3, 6, 9),
    (-1, -2, -3, -10, 0, 1, 2, 9),
    (-4, -6, -8, -9, 3, 5, 7, 8),
    (-3, -5, -7, -9, 2, 4, 6, 8),
)


def clamp(value: int) -> int:
    return max(0, min(255, value))


def expand4(value: int) -> int:
    return (value << 4) | value


def expand5(value: int) -> int:
    return (value << 3) | (value >> 2)


def expand6(value: int) -> int:
    return (value << 2) | (value >> 4)


def expand7(value: int) -> int:
    return (value << 1) | (value >> 6)


def signed3(value: int) -> int:
    return value - 8 if value & 4 else value


def selector(block: bytes, x: int, y: int) -> int:
    pixel = x * 4 + y
    bits = int.from_bytes(block[4:8], "big")
    return (((bits >> (pixel + 16)) & 1) << 1) | ((bits >> pixel) & 1)


def regular_colors(block: bytes) -> tuple[list[tuple[int, int, int]], int, int]:
    differential = bool(block[3] & 2)
    tables = ((block[3] >> 5) & 7, (block[3] >> 2) & 7)
    flip = block[3] & 1
    colors = []
    for subblock in range(2):
        values = []
        for byte in block[:3]:
            if differential:
                first = (byte >> 3) & 31
                value = first if subblock == 0 else first + signed3(byte & 7)
                values.append(expand5(value))
            else:
                value = (byte >> 4) if subblock == 0 else (byte & 15)
                values.append(expand4(value))
        colors.append(tuple(values))
    return colors, tables, flip


def decode_regular(block: bytes, x: int, y: int) -> tuple[int, int, int]:
    colors, tables, flip = regular_colors(block)
    subblock = (y >= 2) if flip else (x >= 2)
    selected = selector(block, x, y)
    small, large = MODIFIERS[tables[subblock]]
    modifier = (small, large, -small, -large)[selected]
    return tuple(clamp(value + modifier) for value in colors[subblock])


def th_colors(block: bytes, h_mode: bool) -> tuple[tuple[int, int, int], tuple[int, int, int], int]:
    first_raw = (
        ((block[0] & 0x18) >> 1) | (block[0] & 3),
        block[1] >> 4,
        block[1] & 15,
    )
    second_raw = (block[2] >> 4, block[2] & 15, block[3] >> 4)
    first = tuple(expand4(value) for value in first_raw)
    second = tuple(expand4(value) for value in second_raw)
    distance_index = (block[3] & 12) >> 1
    if h_mode:
        color0 = (first_raw[0] << 8) | (first_raw[1] << 4) | first_raw[2]
        color1 = (second_raw[0] << 8) | (second_raw[1] << 4) | second_raw[2]
        distance_index |= color0 >= color1
    else:
        distance_index |= block[3] & 1
    return first, second, DISTANCES[distance_index]


def decode_t(block: bytes, x: int, y: int) -> tuple[int, int, int]:
    first, second, distance = th_colors(block, False)
    colors = (
        first,
        tuple(clamp(value + distance) for value in second),
        second,
        tuple(clamp(value - distance) for value in second),
    )
    return colors[selector(block, x, y)]


def decode_h(block: bytes, x: int, y: int) -> tuple[int, int, int]:
    first, second, distance = th_colors(block, True)
    colors = (
        tuple(clamp(value + distance) for value in first),
        tuple(clamp(value - distance) for value in first),
        tuple(clamp(value + distance) for value in second),
        tuple(clamp(value - distance) for value in second),
    )
    return colors[selector(block, x, y)]


def decode_planar(block: bytes, x: int, y: int) -> tuple[int, int, int]:
    origin = (
        expand6((block[0] & 0x7E) >> 1),
        expand7(((block[0] & 1) << 6) | ((block[1] & 0x7E) >> 1)),
        expand6(
            ((block[1] & 1) << 5) | (block[2] & 0x18)
            | ((block[2] & 3) << 1) | ((block[3] & 0x80) >> 7)
        ),
    )
    horizontal = (
        expand6(((block[3] & 0x7C) >> 1) | (block[3] & 1)),
        expand7(block[4] >> 1),
        expand6(((block[4] & 1) << 5) | (block[5] >> 3)),
    )
    vertical = (
        expand6(((block[5] & 7) << 3) | (block[6] >> 5)),
        expand7(((block[6] & 31) << 2) | (block[7] >> 6)),
        expand6(block[7] & 63),
    )
    return tuple(
        clamp((x * (h - o) + y * (v - o) + 4 * o + 2) >> 2)
        for o, h, v in zip(origin, horizontal, vertical)
    )


def decode_color(block: bytes, x: int, y: int, etc2: bool) -> tuple[int, int, int]:
    if etc2 and block[3] & 2:
        red = (block[0] >> 3) + signed3(block[0] & 7)
        green = (block[1] >> 3) + signed3(block[1] & 7)
        blue = (block[2] >> 3) + signed3(block[2] & 7)
        if not 0 <= red < 32:
            return decode_t(block, x, y)
        if not 0 <= green < 32:
            return decode_h(block, x, y)
        if not 0 <= blue < 32:
            return decode_planar(block, x, y)
    return decode_regular(block, x, y)


def decode_alpha(block: bytes, x: int, y: int) -> int:
    pixel = x * 4 + y
    bits = int.from_bytes(block[2:8], "big")
    selected = (bits >> (3 * (15 - pixel))) & 7
    modifier = ALPHA_MODIFIERS[block[1] & 15][selected]
    return clamp(block[0] + (block[1] >> 4) * modifier)


def decode_blocks(data: bytes, width: int, height: int, alpha: bool, etc2: bool) -> bytes:
    result = bytearray(width * height * 4)
    block_size = 16 if alpha else 8
    columns = (width + 3) // 4
    rows = (height + 3) // 4
    for block_y in range(rows):
        for block_x in range(columns):
            offset = (block_y * columns + block_x) * block_size
            block = data[offset:offset + block_size]
            color = block[8:] if alpha else block
            for y in range(min(4, height - block_y * 4)):
                for x in range(min(4, width - block_x * 4)):
                    pixel_x = block_x * 4 + x
                    pixel_y = block_y * 4 + y
                    target = (pixel_y * width + pixel_x) * 4
                    result[target:target + 3] = bytes(decode_color(color, x, y, etc2))
                    result[target + 3] = decode_alpha(block, x, y) if alpha else 255
    return bytes(result)


def is_etc_ktx1(data: bytes) -> bool:
    if len(data) < 64 or data[:12] != KTX1_IDENTIFIER or data[12:16] != b"\x01\x02\x03\x04":
        return False
    return struct.unpack_from("<13I", data, 12)[4] in {ETC1_RGB, ETC2_RGB, ETC2_RGBA}


def decode_etc_ktx1(data: bytes) -> Image.Image | None:
    if len(data) < 64 or data[:12] != KTX1_IDENTIFIER or data[12:16] != b"\x01\x02\x03\x04":
        return None
    fields = struct.unpack_from("<13I", data, 12)
    internal_format = fields[4]
    if internal_format not in {ETC1_RGB, ETC2_RGB, ETC2_RGBA}:
        return None
    width, height, depth, array_elements, faces = fields[6:11]
    key_value_bytes = fields[12]
    if not width or not height or depth or array_elements or faces != 1:
        raise ValueError("Unsupported ETC KTX1 dimensions")
    if (width > MAX_TEXTURE_DIMENSION or height > MAX_TEXTURE_DIMENSION
            or width * height * 4 > MAX_TEXTURE_PIXEL_BYTES):
        raise ValueError("ETC KTX1 dimensions exceed limits")
    offset = 64 + key_value_bytes
    if len(data) < offset + 4:
        raise ValueError("Truncated ETC KTX1 level")
    image_size = struct.unpack_from("<I", data, offset)[0]
    offset += 4
    alpha = internal_format == ETC2_RGBA
    block_size = 16 if alpha else 8
    expected_size = ((width + 3) // 4) * ((height + 3) // 4) * block_size
    if image_size < expected_size or len(data) < offset + expected_size:
        raise ValueError("Truncated ETC KTX1 data")
    pixels = decode_blocks(
        data[offset:offset + expected_size], width, height, alpha, internal_format != ETC1_RGB,
    )
    return Image.frombytes("RGBA", (width, height), pixels)
