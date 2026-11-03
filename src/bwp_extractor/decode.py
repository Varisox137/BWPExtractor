from typing import BinaryIO
import zlib

from bwp_extractor.npk import NpkEntry


class EntryDecodeError(ValueError):
    pass


class UnsupportedEntryError(EntryDecodeError):
    pass


def decode_entry(stream: BinaryIO, entry: NpkEntry) -> bytes:
    if entry.encryption:
        raise UnsupportedEntryError(f"Unsupported encryption: {entry.encryption}")
    if entry.compression not in {0, 1}:
        raise UnsupportedEntryError(f"Unsupported compression: {entry.compression}")
    stream.seek(entry.offset)
    packed = stream.read(entry.packed_size)
    if len(packed) != entry.packed_size:
        raise EntryDecodeError("Truncated entry data")
    looks_zlib = len(packed) >= 2 and packed[0] == 0x78
    compressed = entry.compression == 1 or entry.packed_size != entry.raw_size or looks_zlib
    if not compressed:
        if len(packed) != entry.raw_size:
            raise EntryDecodeError("Stored entry length mismatch")
        return packed
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(packed) + decoder.flush()
    except zlib.error as exc:
        raise EntryDecodeError("Invalid zlib stream") from exc
    if not decoder.eof or decoder.unused_data:
        raise EntryDecodeError("Incomplete or trailing zlib data")
    if len(raw) != entry.raw_size:
        raise EntryDecodeError("Decoded entry length mismatch")
    return raw
