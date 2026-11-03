import json

from bwp_extractor.formats import detect_format
from bwp_extractor.models import ResourceKind


def test_detects_real_headers():
    assert detect_format(b"\x89PNG\r\n\x1a\n" + bytes(8)) == ResourceKind.PNG
    assert detect_format(b"\xabKTX 11\xbb\r\n\x1a\n" + bytes(8)) == ResourceKind.KTX1
    assert detect_format(b"\xabKTX 20\xbb\r\n\x1a\n" + bytes(8)) == ResourceKind.KTX2
    assert detect_format(b"DDS " + bytes(124)) == ResourceKind.DDS
    assert detect_format(b"page.png\nsize: 4,4\nformat: RGBA8888\nfilter: Linear,Linear\n") == ResourceKind.ATLAS
    assert detect_format(json.dumps({"bones": []}).encode()) == ResourceKind.JSON
    assert detect_format(b"precision mediump float;\n") == ResourceKind.TEXT
    assert detect_format(b"\x00\x01\x02\x03") == ResourceKind.BINARY
