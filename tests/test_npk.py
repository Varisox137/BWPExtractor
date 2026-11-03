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


def test_rejects_unknown_magic():
    with pytest.raises(UnsupportedNpkError):
        read_npk_index(BytesIO(b"EXPK" + bytes(48)), 52)


def test_rejects_truncated_index():
    data = package()
    with pytest.raises(CorruptNpkError):
        read_npk_index(BytesIO(data[:-1]), len(data) - 1)


def test_rejects_entry_past_eof():
    data = bytearray(package())
    struct.pack_into("<I", data, 27 + 8, 999)
    with pytest.raises(CorruptNpkError):
        read_npk_index(BytesIO(data), len(data))
