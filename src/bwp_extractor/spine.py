from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import tempfile

from bwp_extractor.output import OutputStore


PAGE = re.compile(rb"(?m)^([^\r\n:]+\.(?:png|jpg|jpeg))\s*$")


def parse_atlas_pages(data: bytes) -> list[str]:
    return [m.group(1).decode("utf-8") for m in PAGE.finditer(data)]


@dataclass(frozen=True)
class SpineBundle:
    directory: str
    files: tuple[str, ...]
    missing: tuple[str, ...]


def safe_atlas_page(page: str) -> PurePosixPath:
    normalized = page.replace("\\", "/")
    pure = PurePosixPath(normalized)
    windows = PureWindowsPath(page)
    if (windows.drive or windows.root or pure.is_absolute()
            or ".." in pure.parts or not pure.parts):
        raise ValueError(f"Unsafe atlas page: {page}")
    return pure


def build_spine_bundle(store: OutputStore, atlas_path: str, atlas_data: bytes,
                       available: dict[str, Path]) -> SpineBundle:
    atlas = PurePosixPath(atlas_path)
    expected = [(str(atlas), PurePosixPath(atlas.name))]
    for page in parse_atlas_pages(atlas_data):
        relative = safe_atlas_page(page)
        expected.append((str(atlas.parent / relative), relative))
    skel = atlas.with_suffix(".skel")
    json_skeleton = atlas.with_suffix(".json")
    skeleton = json_skeleton if str(skel) not in available and str(json_skeleton) in available else skel
    expected.append((str(skeleton), PurePosixPath(skeleton.name)))

    destination = PurePosixPath("curated/spine", atlas.parent, atlas.stem)
    destination_path = store.path(str(destination))
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{atlas.stem}-", dir=destination_path.parent))
    backup = None
    files = []
    missing = []
    try:
        staging_store = OutputStore(staging)
        for name, relative in expected:
            source = available.get(name)
            if source is None:
                missing.append(name)
                continue
            staging_store.link_or_copy(source, str(relative))
            files.append(str(destination / relative))
        if destination_path.exists():
            backup = Path(tempfile.mkdtemp(
                prefix=f".{atlas.stem}-backup-", dir=destination_path.parent,
            ))
            backup.rmdir()
            os.replace(destination_path, backup)
        os.replace(staging, destination_path)
    except Exception:
        if backup is not None and backup.exists():
            if destination_path.exists():
                shutil.rmtree(destination_path)
            os.replace(backup, destination_path)
        raise
    else:
        if backup is not None:
            shutil.rmtree(backup)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return SpineBundle(str(destination), tuple(files), tuple(missing))
