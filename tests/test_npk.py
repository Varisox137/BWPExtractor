from io import BytesIO
import struct

import pytest

from bwp_extractor.npk import CorruptNpkError, UnsupportedNpkError, read_npk_index


def package(payload=b"abc", compression=0, encryption=0, offset=24):
    entry = struct.pack(
        "<7I",
        0x1234,
        offset,
        len(payload),
        len(payload),
        11,
        22,
        compression | (encryption << 16),
    )
    header = b"NXPK" + struct.pack("<5I", 1, 0, 0, 0, offset + len(payload))
    return header + payload + entry


def test_reads_28_byte_index():
    data = package()
    index = read_npk_index(BytesIO(data), len(data))
    assert index.entries[0].signature == 0x1234
    assert index.entries[0].packed_checksum == 11
    assert index.entries[0].raw_checksum == 22


def test_reads_two_entries_with_28_byte_stride():
    first = struct.pack("<7I", 0x1234, 24, 3, 3, 11, 22, 2 | (3 << 16))
    second = struct.pack("<7I", 0x5678, 27, 3, 4, 33, 44, 4 | (5 << 16))
    header = b"NXPK" + struct.pack("<5I", 2, 0, 0, 0, 30)
    data = header + b"abcdef" + first + second

    index = read_npk_index(BytesIO(data), len(data))

    assert [
        (
            entry.index,
            entry.signature,
            entry.offset,
            entry.packed_size,
            entry.raw_size,
            entry.compression,
            entry.encryption,
        )
        for entry in index.entries
    ] == [
        (0, 0x1234, 24, 3, 3, 2, 3),
        (1, 0x5678, 27, 3, 4, 4, 5),
    ]


def test_rejects_unknown_magic():
    with pytest.raises(UnsupportedNpkError):
        read_npk_index(BytesIO(b"EXPK" + bytes(48)), 52)


@pytest.mark.parametrize("field_index", [1, 2, 3])
def test_rejects_unknown_header_modes(field_index):
    data = bytearray(package())
    struct.pack_into("<I", data, 4 + field_index * 4, 1)
    with pytest.raises(UnsupportedNpkError):
        read_npk_index(BytesIO(data), len(data))


def test_rejects_truncated_index():
    data = package()
    with pytest.raises(CorruptNpkError, match="^Truncated NPK index$"):
        read_npk_index(BytesIO(data[:-1]), len(data))


def test_rejects_entry_past_eof():
    data = bytearray(package())
    struct.pack_into("<I", data, 27 + 8, 999)
    with pytest.raises(CorruptNpkError):
        read_npk_index(BytesIO(data), len(data))
