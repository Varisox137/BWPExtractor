import json

from bwp_extractor.models import ResourceKind


def detect_format(data: bytes) -> ResourceKind:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ResourceKind.PNG
    if data.startswith(b"\xabKTX 11\xbb\r\n\x1a\n"):
        return ResourceKind.KTX1
    if data.startswith(b"\xabKTX 20\xbb\r\n\x1a\n"):
        return ResourceKind.KTX2
    if data.startswith(b"DDS "):
        return ResourceKind.DDS
    stripped = data.lstrip()
    if stripped.startswith((b"{", b"[")):
        try:
            json.loads(stripped)
            return ResourceKind.JSON
        except (UnicodeDecodeError, json.JSONDecodeError):
            return ResourceKind.BINARY
    if b"\0" not in data[:4000]:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return ResourceKind.BINARY
        if "format:" in text and "filter:" in text and ".png" in text.lower():
            return ResourceKind.ATLAS
        return ResourceKind.TEXT
    return ResourceKind.BINARY
