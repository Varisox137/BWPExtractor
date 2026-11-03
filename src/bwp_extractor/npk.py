from dataclasses import dataclass
import struct
from typing import BinaryIO


class NpkError(ValueError):
    pass


class UnsupportedNpkError(NpkError):
    pass


class CorruptNpkError(NpkError):
    pass


@dataclass(frozen=True)
class NpkEntry:
    index: int
    signature: int
    offset: int
    packed_size: int
    raw_size: int
    packed_checksum: int
    raw_checksum: int
    compression: int
    encryption: int


@dataclass(frozen=True)
class NpkIndex:
    entries: tuple[NpkEntry, ...]


def read_npk_index(stream: BinaryIO, stream_size: int) -> NpkIndex:
    header = stream.read(24)
    if len(header) != 24:
        raise CorruptNpkError("Truncated NPK header")
    if header[:4] != b"NXPK":
        raise UnsupportedNpkError("Only verified NXPK input is supported")
    count, var1, encrypt_mode, hash_mode, index_offset = struct.unpack(
        "<5I", header[4:]
    )
    if (var1, encrypt_mode, hash_mode) != (0, 0, 0):
        raise UnsupportedNpkError("Unsupported NXPK header mode")
    index_size = count * 28
    if index_offset < 24 or index_offset + index_size > stream_size:
        raise CorruptNpkError("Index lies outside the archive")
    stream.seek(index_offset)
    table = stream.read(index_size)
    if len(table) != index_size:
        raise CorruptNpkError("Truncated NPK index")
    entries = []
    for i in range(count):
        fields = struct.unpack_from("<7I", table, i * 28)
        signature, offset, packed, raw, packed_crc, raw_crc, flags = fields
        if offset < 24 or offset + packed > stream_size:
            raise CorruptNpkError(f"Entry {i} lies outside the archive")
        entries.append(
            NpkEntry(
                i,
                signature,
                offset,
                packed,
                raw,
                packed_crc,
                raw_crc,
                flags & 0xFFFF,
                (flags >> 16) & 0xFF,
            )
        )
    return NpkIndex(tuple(entries))
