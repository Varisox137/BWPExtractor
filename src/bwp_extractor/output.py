import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
from typing import Iterable


class OutputStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, relative: str) -> Path:
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts or not pure.parts:
            raise ValueError(f"Unsafe output path: {relative}")
        target = self.root.joinpath(*pure.parts).resolve()
        if self.root not in target.parents:
            raise ValueError(f"Output escapes root: {relative}")
        return target

    def write_bytes(self, relative: str, data: bytes) -> tuple[Path, bool]:
        target = self.path(relative)
        if target.exists() and target.read_bytes() == data:
            return target, False
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return target, True

    def link_or_copy(self, source: Path, relative: str) -> tuple[Path, str]:
        target = self.path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=target.parent)
        os.close(fd)
        os.unlink(temporary)
        try:
            try:
                os.link(source, temporary)
                mode = "hardlink"
            except OSError:
                shutil.copy2(source, temporary)
                mode = "copy"
            os.replace(temporary, target)
            return target, mode
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def write_json(self, relative: str, value) -> Path:
        data = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
        return self.write_bytes(relative, data)[0]

    def write_jsonl(self, relative: str, rows: Iterable[dict]) -> Path:
        data = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode("utf-8")
        return self.write_bytes(relative, data)[0]
