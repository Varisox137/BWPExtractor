from io import BytesIO
import zlib

import pytest

from bwp_extractor.decode import EntryDecodeError, UnsupportedEntryError, decode_entry
from bwp_extractor.npk import NpkEntry


def entry(data: bytes, raw_size: int, compression=0, encryption=0):
    return NpkEntry(0, 1, 0, len(data), raw_size, 0, 0, compression, encryption)


def test_reads_stored_entry():
    assert decode_entry(BytesIO(b"abc"), entry(b"abc", 3)) == b"abc"


def test_detects_zlib_when_flag_is_zero():
    packed = zlib.compress(b"KTX payload")
    assert decode_entry(BytesIO(packed), entry(packed, 11)) == b"KTX payload"


def test_rejects_truncated_zlib():
    packed = zlib.compress(b"payload")[:-1]
    with pytest.raises(EntryDecodeError):
        decode_entry(BytesIO(packed), entry(packed, 7))


def test_rejects_unknown_compression():
    with pytest.raises(UnsupportedEntryError):
        decode_entry(BytesIO(b"abc"), entry(b"abc", 3, compression=2))


def test_rejects_encryption():
    with pytest.raises(UnsupportedEntryError):
        decode_entry(BytesIO(b"abc"), entry(b"abc", 3, encryption=2))


def test_zlib_output_is_limited_to_declared_size_plus_one():
    packed = zlib.compress(bytes(16 * 1024 * 1024))

    with pytest.raises(EntryDecodeError, match="exceeds declared raw size"):
        decode_entry(BytesIO(packed), entry(packed, 16))


def test_entry_larger_than_explicit_limit_is_rejected_before_decoding():
    from bwp_extractor.decode import MAX_ENTRY_SIZE

    packed = zlib.compress(b"small")
    with pytest.raises(EntryDecodeError, match="exceeds entry limit"):
        decode_entry(BytesIO(packed), entry(packed, MAX_ENTRY_SIZE + 1))
