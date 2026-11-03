from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
import re

import mmh3


@dataclass(frozen=True)
class ResolvedName:
    path: str | None
    source: str


class NameResolver:
    EXTENSIONS = "png|ktx|ktx2|dds|atlas|skel|json|xml|txt"
    CANDIDATE = re.compile(rb"[A-Za-z0-9_./\\-]+\.(?:" + EXTENSIONS.encode() + rb")")

    def __init__(self):
        self._paths: dict[int, tuple[str, str]] = {}

    @staticmethod
    def signature(path: str) -> int:
        return mmh3.hash(path, 0x9747B28C, signed=False)

    @staticmethod
    def safe(path: str) -> str | None:
        normalized = path.replace("\\", "/")
        windows = PureWindowsPath(path)
        pure = PurePosixPath(normalized)
        if (windows.drive or windows.root or pure.is_absolute()
                or ".." in pure.parts or not pure.parts):
            return None
        return str(pure)

    def add_path(self, path: str, source: str = "candidate") -> None:
        safe = self.safe(path)
        if safe:
            for candidate in {path, safe}:
                self._paths[self.signature(candidate)] = (safe, source)

    def load_mapping(self, mapping: dict[str, str]) -> None:
        for signature, path in mapping.items():
            if not re.fullmatch(r"[0-9A-Fa-f]{8}", signature):
                raise ValueError(f"Invalid signature: {signature}")
            self.add_path(path, "mapping")
            safe = self.safe(path)
            if safe:
                self._paths[int(signature, 16)] = (safe, "mapping")

    def harvest(self, data: bytes) -> None:
        for match in self.CANDIDATE.finditer(data):
            self.add_path(match.group().decode("ascii"))

    def resolve(self, signature: int) -> ResolvedName:
        result = self._paths.get(signature)
        return ResolvedName(*result) if result else ResolvedName(None, "unresolved")


def curated_relative(path: str) -> str:
    pure = PurePosixPath(path)
    lowered = [part.lower() for part in pure.parts]
    category = "cards" if any("card" in p for p in lowered) else \
               "ui" if any(p in {"gui", "ui"} for p in lowered) else "other"
    return str(PurePosixPath(category, *pure.parts))
