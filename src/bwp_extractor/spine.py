from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re

from bwp_extractor.output import OutputStore


PAGE = re.compile(rb"(?m)^([^\r\n:]+\.(?:png|jpg|jpeg))\s*$")


def parse_atlas_pages(data: bytes) -> list[str]:
    return [m.group(1).decode("utf-8") for m in PAGE.finditer(data)]


@dataclass(frozen=True)
class SpineBundle:
    directory: str
    files: tuple[str, ...]
    missing: tuple[str, ...]


def build_spine_bundle(store: OutputStore, atlas_path: str, atlas_data: bytes,
                       available: dict[str, Path]) -> SpineBundle:
    atlas = PurePosixPath(atlas_path)
    expected = [str(atlas)]
    expected.extend(str(atlas.with_name(page)) for page in parse_atlas_pages(atlas_data))
    skel = atlas.with_suffix(".skel")
    json_skeleton = atlas.with_suffix(".json")
    skeleton = json_skeleton if str(skel) not in available and str(json_skeleton) in available else skel
    expected.append(str(skeleton))
    files = []
    missing = []
    destination = PurePosixPath("curated/spine", atlas.stem)
    for name in expected:
        source = available.get(name)
        if source is None:
            missing.append(name)
            continue
        target, _ = store.link_or_copy(source, str(destination / PurePosixPath(name).name))
        files.append(str(target.relative_to(store.root)))
    return SpineBundle(str(destination), tuple(files), tuple(missing))
