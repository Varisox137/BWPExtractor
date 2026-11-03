from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import BinaryIO, Iterator
from zipfile import ZipFile


@dataclass(frozen=True)
class SourceIdentity:
    source: str
    size: int
    sha256: str


@dataclass(frozen=True)
class ArchiveSource:
    location: Path
    relative_name: str
    member: str | None = None

    @contextmanager
    def open(self) -> Iterator[BinaryIO]:
        if self.member is None:
            with self.location.open("rb") as stream:
                yield stream
        else:
            with ZipFile(self.location) as package:
                with package.open(self.member) as stream:
                    yield stream

    def identity(self) -> SourceIdentity:
        digest = sha256()
        size = 0
        with self.open() as stream:
            while block := stream.read(8 * 1024 * 1024):
                size += len(block)
                digest.update(block)
        return SourceIdentity(str(self.location), size, digest.hexdigest())


class ResourceSource:
    def archives(self) -> list[ArchiveSource]:
        raise NotImplementedError


class LocalSource(ResourceSource):
    def __init__(self, paths: list[ArchiveSource]):
        self._paths = paths

    def archives(self) -> list[ArchiveSource]:
        return self._paths


class ZipSource(ResourceSource):
    def __init__(self, path: Path):
        self.path = path

    def archives(self) -> list[ArchiveSource]:
        with ZipFile(self.path) as package:
            names = sorted(n for n in package.namelist() if n.lower().endswith(".npk"))
        return [ArchiveSource(self.path, n, n) for n in names]


def open_source(path: Path) -> ResourceSource:
    if path.is_dir():
        files = sorted(p for p in path.rglob("*") if p.suffix.lower() == ".npk")
        return LocalSource([ArchiveSource(p, str(p.relative_to(path))) for p in files])
    if path.suffix.lower() == ".npk":
        return LocalSource([ArchiveSource(path, path.name)])
    if path.suffix.lower() in {".apk", ".zip"}:
        return ZipSource(path)
    raise ValueError(f"Unsupported input: {path}")
