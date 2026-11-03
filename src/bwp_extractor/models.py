from enum import StrEnum


class Status(StrEnum):
    SUCCESS = "success"
    UNSUPPORTED = "unsupported"
    CORRUPT = "corrupt"
    CONVERSION_FAILED = "conversion_failed"


class NameStatus(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


class ResourceKind(StrEnum):
    PNG = "png"
    KTX1 = "ktx1"
    KTX2 = "ktx2"
    DDS = "dds"
    ATLAS = "atlas"
    JSON = "json"
    TEXT = "text"
    BINARY = "binary"
