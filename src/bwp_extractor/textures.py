from pathlib import Path
import shutil
import subprocess
import tempfile

from PIL import Image

from bwp_extractor.models import ResourceKind
from bwp_extractor.output import OutputStore


class TextureConverter:
    VERSION = "texture-v1"

    def __init__(self, store: OutputStore):
        self.store = store

    def convert(self, raw_path: Path, kind: ResourceKind, relative_output: str) -> Path:
        if kind == ResourceKind.PNG:
            return self.store.link_or_copy(raw_path, relative_output)[0]
        if kind == ResourceKind.DDS:
            with Image.open(raw_path) as image:
                buffer = tempfile.SpooledTemporaryFile()
                image.save(buffer, "PNG")
                buffer.seek(0)
                return self.store.write_bytes(relative_output, buffer.read())[0]
        if kind in {ResourceKind.KTX1, ResourceKind.KTX2}:
            return self._convert_ktx(raw_path, kind, relative_output)
        raise ValueError(f"Not a supported texture: {kind}")

    def _convert_ktx(self, raw_path: Path, kind: ResourceKind, output: str) -> Path:
        ktx2ktx2 = shutil.which("ktx2ktx2.exe") or shutil.which("ktx2ktx2")
        ktx = shutil.which("ktx.exe") or shutil.which("ktx")
        if not ktx or (kind == ResourceKind.KTX1 and not ktx2ktx2):
            raise RuntimeError("KTX-Software is required")
        target = self.store.path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=target.parent) as temporary:
            temp = Path(temporary)
            source = raw_path
            if kind == ResourceKind.KTX1:
                source = temp / "input.ktx2"
                subprocess.run([ktx2ktx2, "-f", "-o", str(source), str(raw_path)],
                               check=True, capture_output=True, text=True)
            produced = temp / "output.png"
            subprocess.run([ktx, "extract", "--level", "0", str(source), str(produced)],
                           check=True, capture_output=True, text=True)
            if not produced.is_file() or produced.stat().st_size == 0:
                raise RuntimeError("KTX did not produce a PNG")
            produced.replace(target)
        return target
