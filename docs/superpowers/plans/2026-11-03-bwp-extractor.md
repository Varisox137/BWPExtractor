# 百闻牌美术资源提取器 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 Python 3 重写百闻牌提取器，批量读取本地 NPK/APK/ZIP，可靠导出 2D 与 Spine 资源，并生成可追踪的原始、转换和语义分层输出。

**Architecture:** `ResourceSource` 提供统一的随机访问流，`NpkReader` 与 `EntryDecoder` 负责容器和条目完整性，格式识别、纹理转换、名称恢复、Spine 关联各自独立。`ExtractionPipeline` 先解码并收集候选名称，再转换与组织成品；`OutputStore` 统一路径约束、原子写入、硬链接回退、清单和缓存。

**Tech Stack:** Python >=3.12、uv、标准库 `argparse`/`zipfile`/`zlib`、KTX-Software 4.4.2、Pillow（DDS）、mmh3（路径哈希）、pytest。

## Global Constraints

- 首要支持 Android；本机旧 Windows 桌面版用于对照回归，不承诺 iOS 或其他 NeoX 游戏兼容性。
- 只转换 2D 与 Spine；不做 GUI、自动下载、3D、音频或视频转换。
- 已验证能力才标记为支持；其他 NeoX 变体只识别、报告并保留扩展点。
- 不移植 AGPL 代码；优先标准库，只有真实样本证明需要时才增加图像解码依赖。
- 当前版本不主动联网，不执行包内脚本，不注入或修改游戏进程，不重打包客户端。
- 索引校验字段不等于标准 `zlib.crc32`，只记录，不声称 CRC 已验证。
- `raw/`、`converted/`、`curated/`、`manifest/entries.jsonl`、`reports/run.json` 为固定输出层。
- `unresolved` 不是提取失败；`unsupported`、`corrupt`、`conversion_failed` 必须非零退出。
- 所有输出路径禁止绝对路径与 `..` 穿越；输入文件永不修改；文件校验后原子替换。
- README 开头必须有安全与使用声明；`samples/` 和提取输出不得提交。
- 自动化测试只使用合成数据，不提交 APK、NPK 或游戏素材。
- Windows Git Bash 的测试命令统一为 `uv run pytest -q`。

---

### Task 1: 项目骨架、领域状态与安全声明

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `README.md`
- Create: `src/bwp_extractor/__init__.py`
- Create: `src/bwp_extractor/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: 无。
- Produces: `Status`、`NameStatus`、`ResourceKind` 三个字符串枚举，供所有后续任务使用。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_models.py
from bwp_extractor.models import NameStatus, ResourceKind, Status


def test_status_values_are_stable():
    assert [s.value for s in Status] == [
        "success", "unsupported", "corrupt", "conversion_failed"
    ]
    assert NameStatus.UNRESOLVED.value == "unresolved"
    assert ResourceKind.KTX1.value == "ktx1"
```

- [ ] **Step 2: 验证测试因包不存在而失败**

Run: `uv run --with pytest pytest tests/test_models.py -q`
Expected: FAIL，无法导入 `bwp_extractor`。

- [ ] **Step 3: 创建最小项目与模型**

```toml
# pyproject.toml
[project]
name = "bwp-extractor"
version = "0.1.0"
description = "Static, read-only art extractor for legally obtained yysbwp resources"
requires-python = ">=3.12"
dependencies = []

[dependency-groups]
dev = ["pytest>=8"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/bwp_extractor"]
```

```python
# src/bwp_extractor/models.py
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
```

```gitignore
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
samples/
output/
dist/
```

README 开头必须包含：项目与网易及游戏官方无关；素材权利归原权利人；仅限学习、研究、个人备份；用户须合法取得文件并遵守法律、协议和授权；禁止侵犯版权与作弊；工具只静态读取本地文件，不执行脚本、不修改进程或客户端；当前版本不联网。写明 `uv sync` 和 `uv run pytest -q`。

- [ ] **Step 4: 安装项目并验证测试通过**

Run: `uv sync && uv run pytest tests/test_models.py -q`
Expected: PASS。

- [ ] **Step 5: 检查大文件未被跟踪并提交**

Run: `git status --short`
Expected: `samples/` 不出现。

```bash
git add pyproject.toml uv.lock .gitignore README.md src tests
git commit -m "chore: 建立提取器项目与安全边界"
```

### Task 2: 本地与 ZIP/APK ResourceSource

**Files:**
- Create: `src/bwp_extractor/sources.py`
- Test: `tests/test_sources.py`

**Interfaces:**
- Consumes: 无。
- Produces: `ArchiveSource.open()`、`ArchiveSource.identity()`、`SourceIdentity`、`ResourceSource.archives()`、`open_source(path)`。

- [ ] **Step 1: 写本地、目录和 ZIP 的失败测试**

```python
# tests/test_sources.py
from pathlib import Path
from zipfile import ZipFile
from bwp_extractor.sources import open_source


def test_discovers_local_and_zip_npk(tmp_path: Path):
    single = tmp_path / "one.npk"
    single.write_bytes(b"NXPK-one")
    archive = tmp_path / "client.apk"
    with ZipFile(archive, "w") as z:
        z.writestr("assets/res/two.npk", b"NXPK-two")
        z.writestr("assets/readme.txt", b"ignored")

    assert [a.relative_name for a in open_source(single).archives()] == ["one.npk"]
    zipped = open_source(archive).archives()
    assert [a.relative_name for a in zipped] == ["assets/res/two.npk"]
    with zipped[0].open() as stream:
        assert stream.read() == b"NXPK-two"
    identity = zipped[0].identity()
    assert identity.size == 8
    assert len(identity.sha256) == 64


def test_directory_order_is_stable(tmp_path: Path):
    (tmp_path / "b.npk").write_bytes(b"b")
    (tmp_path / "a.npk").write_bytes(b"a")
    assert [a.relative_name for a in open_source(tmp_path).archives()] == ["a.npk", "b.npk"]
```

- [ ] **Step 2: 验证导入失败**

Run: `uv run pytest tests/test_sources.py -q`
Expected: FAIL，`sources` 不存在。

- [ ] **Step 3: 实现随机访问来源与内容身份**

```python
# src/bwp_extractor/sources.py
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
```

- [ ] **Step 4: 运行来源测试**

Run: `uv run pytest tests/test_sources.py -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/bwp_extractor/sources.py tests/test_sources.py
git commit -m "feat: 支持本地与 APK 资源来源"
```

### Task 3: NXPK 索引读取与边界校验

**Files:**
- Create: `src/bwp_extractor/npk.py`
- Test: `tests/test_npk.py`

**Interfaces:**
- Consumes: `ArchiveSource.open()` 返回的可 seek 二进制流。
- Produces: `NpkEntry`、`NpkIndex`、`read_npk_index(stream, stream_size)`；不支持格式抛出 `UnsupportedNpkError`，损坏输入抛出 `CorruptNpkError`。

- [ ] **Step 1: 写有效、截断、变体与越界测试**

```python
# tests/test_npk.py
from io import BytesIO
import struct
import pytest
from bwp_extractor.npk import CorruptNpkError, UnsupportedNpkError, read_npk_index


def package(payload=b"abc", compression=0, encryption=0, offset=24):
    entry = struct.pack("<7I", 0x1234, offset, len(payload), len(payload), 11, 22,
                        compression | (encryption << 16))
    header = b"NXPK" + struct.pack("<5I", 1, 0, 0, 0, offset + len(payload))
    return header + payload + entry


def test_reads_28_byte_index():
    data = package()
    index = read_npk_index(BytesIO(data), len(data))
    assert index.entries[0].signature == 0x1234
    assert index.entries[0].packed_checksum == 11
    assert index.entries[0].raw_checksum == 22


def test_rejects_unknown_magic():
    with pytest.raises(UnsupportedNpkError):
        read_npk_index(BytesIO(b"EXPK" + bytes(48)), 52)


def test_rejects_truncated_index():
    data = package()
    with pytest.raises(CorruptNpkError):
        read_npk_index(BytesIO(data[:-1]), len(data) - 1)


def test_rejects_entry_past_eof():
    data = bytearray(package())
    struct.pack_into("<I", data, 27 + 8, 999)
    with pytest.raises(CorruptNpkError):
        read_npk_index(BytesIO(data), len(data))
```

- [ ] **Step 2: 验证失败**

Run: `uv run pytest tests/test_npk.py -q`
Expected: FAIL，`npk` 不存在。

- [ ] **Step 3: 实现严格索引解析**

```python
# src/bwp_extractor/npk.py
from dataclasses import dataclass
import struct
from typing import BinaryIO


class NpkError(ValueError):
    pass


class UnsupportedNpkError(NpkError):
    pass


class CorruptNpkError(NpkError):
    pass


@dataclass(frozen=True)
class NpkEntry:
    index: int
    signature: int
    offset: int
    packed_size: int
    raw_size: int
    packed_checksum: int
    raw_checksum: int
    compression: int
    encryption: int


@dataclass(frozen=True)
class NpkIndex:
    entries: tuple[NpkEntry, ...]


def read_npk_index(stream: BinaryIO, stream_size: int) -> NpkIndex:
    header = stream.read(24)
    if len(header) != 24:
        raise CorruptNpkError("Truncated NPK header")
    if header[:4] != b"NXPK":
        raise UnsupportedNpkError("Only verified NXPK input is supported")
    count, _var1, _encrypt_mode, _hash_mode, index_offset = struct.unpack("<5I", header[4:])
    index_size = count * 28
    if index_offset < 24 or index_offset + index_size > stream_size:
        raise CorruptNpkError("Index lies outside the archive")
    stream.seek(index_offset)
    table = stream.read(index_size)
    if len(table) != index_size:
        raise CorruptNpkError("Truncated NPK index")
    entries = []
    for i in range(count):
        fields = struct.unpack_from("<7I", table, i * 28)
        signature, offset, packed, raw, packed_crc, raw_crc, flags = fields
        if offset < 24 or offset + packed > stream_size:
            raise CorruptNpkError(f"Entry {i} lies outside the archive")
        entries.append(NpkEntry(i, signature, offset, packed, raw, packed_crc,
                                raw_crc, flags & 0xFFFF, (flags >> 16) & 0xFF))
    return NpkIndex(tuple(entries))
```

- [ ] **Step 4: 运行索引测试和全量测试**

Run: `uv run pytest tests/test_npk.py -q && uv run pytest -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/bwp_extractor/npk.py tests/test_npk.py
git commit -m "feat: 严格解析 NXPK 索引"
```

### Task 4: 单条目解码与完整性检查

**Files:**
- Create: `src/bwp_extractor/decode.py`
- Test: `tests/test_decode.py`

**Interfaces:**
- Consumes: `NpkEntry`。
- Produces: `decode_entry(stream, entry) -> bytes`、`EntryDecodeError`、`UnsupportedEntryError`。

- [ ] **Step 1: 写存储、隐式 zlib、损坏流和加密测试**

```python
# tests/test_decode.py
from io import BytesIO
import struct
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


def test_rejects_encryption():
    with pytest.raises(UnsupportedEntryError):
        decode_entry(BytesIO(b"abc"), entry(b"abc", 3, encryption=2))
```

- [ ] **Step 2: 验证失败**

Run: `uv run pytest tests/test_decode.py -q`
Expected: FAIL，`decode` 不存在。

- [ ] **Step 3: 实现完整流与长度检查**

```python
# src/bwp_extractor/decode.py
import zlib
from typing import BinaryIO
from bwp_extractor.npk import NpkEntry


class EntryDecodeError(ValueError):
    pass


class UnsupportedEntryError(EntryDecodeError):
    pass


def decode_entry(stream: BinaryIO, entry: NpkEntry) -> bytes:
    if entry.encryption:
        raise UnsupportedEntryError(f"Unsupported encryption: {entry.encryption}")
    if entry.compression not in {0, 1}:
        raise UnsupportedEntryError(f"Unsupported compression: {entry.compression}")
    stream.seek(entry.offset)
    packed = stream.read(entry.packed_size)
    if len(packed) != entry.packed_size:
        raise EntryDecodeError("Truncated entry data")
    looks_zlib = len(packed) >= 2 and packed[0] == 0x78
    compressed = entry.compression == 1 or entry.packed_size != entry.raw_size or looks_zlib
    if not compressed:
        if len(packed) != entry.raw_size:
            raise EntryDecodeError("Stored entry length mismatch")
        return packed
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(packed) + decoder.flush()
    except zlib.error as exc:
        raise EntryDecodeError("Invalid zlib stream") from exc
    if not decoder.eof or decoder.unused_data:
        raise EntryDecodeError("Incomplete or trailing zlib data")
    if len(raw) != entry.raw_size:
        raise EntryDecodeError("Decoded entry length mismatch")
    return raw
```

- [ ] **Step 4: 运行解码测试**

Run: `uv run pytest tests/test_decode.py -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/bwp_extractor/decode.py tests/test_decode.py
git commit -m "feat: 校验并解码 NPK 条目"
```

### Task 5: 魔数与文本格式识别

**Files:**
- Create: `src/bwp_extractor/formats.py`
- Test: `tests/test_formats.py`

**Interfaces:**
- Consumes: `ResourceKind`。
- Produces: `detect_format(data: bytes) -> ResourceKind`；二进制 `.skel` 留待名称解析后由 Spine 组件识别。

- [ ] **Step 1: 写各格式与未知二进制测试**

```python
# tests/test_formats.py
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
```

- [ ] **Step 2: 验证失败**

Run: `uv run pytest tests/test_formats.py -q`
Expected: FAIL，`formats` 不存在。

- [ ] **Step 3: 实现无第三方依赖的识别器**

```python
# src/bwp_extractor/formats.py
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
```

- [ ] **Step 4: 运行识别测试**

Run: `uv run pytest tests/test_formats.py -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/bwp_extractor/formats.py tests/test_formats.py
git commit -m "feat: 按内容识别美术资源格式"
```

### Task 6: 安全输出、清单与可验证缓存

**Files:**
- Create: `src/bwp_extractor/output.py`
- Create: `src/bwp_extractor/manifest.py`
- Test: `tests/test_output.py`
- Test: `tests/test_manifest.py`

**Interfaces:**
- Consumes: `SourceIdentity`、`NpkEntry`、`Status`、`NameStatus`、`ResourceKind`。
- Produces: `OutputStore.write_bytes()`、`link_or_copy()`、`write_json()`、`write_jsonl()`；`EntryRecord`、`Manifest.load()`、`EntryRecord.cache_key()`。

- [ ] **Step 1: 写路径穿越、原子覆写和硬链接回退测试**

```python
# tests/test_output.py
from pathlib import Path
import pytest
from bwp_extractor.output import OutputStore


def test_rejects_path_traversal(tmp_path: Path):
    store = OutputStore(tmp_path)
    with pytest.raises(ValueError):
        store.write_bytes("../escape", b"bad")
    with pytest.raises(ValueError):
        store.write_bytes("/absolute", b"bad")


def test_write_and_link_or_copy(tmp_path: Path):
    store = OutputStore(tmp_path)
    target, written = store.write_bytes("raw/a.png", b"png")
    assert written and target.read_bytes() == b"png"
    target, written = store.write_bytes("raw/a.png", b"png")
    assert not written
    linked, mode = store.link_or_copy(target, "curated/a.png")
    assert linked.read_bytes() == b"png"
    assert mode in {"hardlink", "copy"}


def test_jsonl_is_utf8(tmp_path: Path):
    store = OutputStore(tmp_path)
    store.write_jsonl("manifest/entries.jsonl", [{"name": "百闻牌"}])
    assert "百闻牌" in (tmp_path / "manifest/entries.jsonl").read_text(encoding="utf-8")
```

- [ ] **Step 2: 写缓存键与清单往返测试**

```python
# tests/test_manifest.py
from pathlib import Path
from bwp_extractor.manifest import EntryRecord, Manifest, make_cache_key
from bwp_extractor.models import NameStatus, ResourceKind, Status
from bwp_extractor.npk import NpkEntry
from bwp_extractor.sources import SourceIdentity


def record():
    return EntryRecord("a.npk", 0, "00000001", Status.SUCCESS,
                       NameStatus.UNRESOLVED, ResourceKind.PNG, "raw/a.png", None,
                       None, "sha", None)


def test_manifest_roundtrip_and_cache_key(tmp_path: Path):
    path = tmp_path / "entries.jsonl"
    Manifest.save(path, [record()])
    loaded = Manifest.load(path)
    assert loaded["a.npk:0:00000001"].raw_path == "raw/a.png"
    identity = SourceIdentity("a.npk", 10, "source-sha")
    entry = NpkEntry(0, 1, 0, 3, 3, 11, 22, 0, 0)
    key = record().cache_key(identity, entry, "converter-v1")
    assert "source-sha" in key and "11" in key and "22" in key
```

- [ ] **Step 3: 验证失败**

Run: `uv run pytest tests/test_output.py tests/test_manifest.py -q`
Expected: FAIL，模块不存在。

- [ ] **Step 4: 实现安全写入与记录模型**

```python
# src/bwp_extractor/output.py
from pathlib import Path, PurePosixPath
import json
import os
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
```

```python
# src/bwp_extractor/manifest.py
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from bwp_extractor.models import NameStatus, ResourceKind, Status
from bwp_extractor.npk import NpkEntry
from bwp_extractor.sources import SourceIdentity


def make_cache_key(archive: str, entry_index: int, source: SourceIdentity,
                   entry: NpkEntry, converter_version: str) -> str:
    return ":".join((source.sha256, archive, str(entry_index),
                     str(entry.packed_checksum), str(entry.raw_checksum), converter_version))


@dataclass
class EntryRecord:
    archive: str
    entry_index: int
    signature: str
    status: Status
    name_status: NameStatus
    kind: ResourceKind | None
    raw_path: str | None
    converted_path: str | None
    curated_path: str | None
    raw_sha256: str | None
    error: str | None
    cache_identity: str | None = None

    @property
    def key(self) -> str:
        return f"{self.archive}:{self.entry_index}:{self.signature}"

    def cache_key(self, source: SourceIdentity, entry: NpkEntry, converter_version: str) -> str:
        return make_cache_key(self.archive, self.entry_index, source, entry, converter_version)

    def to_dict(self) -> dict:
        result = asdict(self)
        result["cache_key"] = self.key
        return result


class Manifest:
    @staticmethod
    def save(path: Path, records: list[EntryRecord]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r.to_dict(), ensure_ascii=False) + "\n"
                                for r in records), encoding="utf-8")

    @staticmethod
    def load(path: Path) -> dict[str, EntryRecord]:
        result = {}
        if not path.exists():
            return result
        for line in path.read_text(encoding="utf-8").splitlines():
            data = json.loads(line)
            data["status"] = Status(data["status"])
            data["name_status"] = NameStatus(data["name_status"])
            data["kind"] = ResourceKind(data["kind"]) if data["kind"] else None
            item = EntryRecord(**{k: v for k, v in data.items() if k != "cache_key"})
            result[item.key] = item
        return result
```

实际由 `ExtractionPipeline` 使用 `OutputStore.write_jsonl()` 原子保存清单，不能直接调用 `Manifest.save()` 写最终文件；`Manifest.save()` 仅用于测试与临时数据。

- [ ] **Step 5: 运行输出和清单测试**

Run: `uv run pytest tests/test_output.py tests/test_manifest.py -q`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add src/bwp_extractor/output.py src/bwp_extractor/manifest.py tests/test_output.py tests/test_manifest.py
git commit -m "feat: 增加安全输出与可追踪清单"
```

### Task 7: PNG/KTX/DDS 转换器

**Files:**
- Modify: `pyproject.toml`
- Create: `src/bwp_extractor/textures.py`
- Test: `tests/test_textures.py`

**Interfaces:**
- Consumes: `ResourceKind`、`OutputStore`。
- Produces: `TextureConverter.convert(raw_path, kind, relative_output) -> Path`；KTX 默认 `--level 0`，原始文件不删除。

- [ ] **Step 1: 添加 Pillow 并写 PNG/DDS/未知格式测试**

Run: `uv add pillow`

```python
# tests/test_textures.py
from io import BytesIO
from pathlib import Path
import struct
from PIL import Image
import pytest
from bwp_extractor.models import ResourceKind
from bwp_extractor.output import OutputStore
from bwp_extractor.textures import TextureConverter


def test_png_is_copied_without_reencoding(tmp_path: Path):
    store = OutputStore(tmp_path)
    raw, _ = store.write_bytes("raw/a.png", b"original-png-bytes")
    output = TextureConverter(store).convert(raw, ResourceKind.PNG, "converted/a.png")
    assert output.read_bytes() == b"original-png-bytes"


def test_uncompressed_dds_to_png(tmp_path: Path):
    store = OutputStore(tmp_path)
    header = bytearray(128)
    header[:4] = b"DDS "
    struct.pack_into("<I", header, 4, 124)
    struct.pack_into("<I", header, 12, 1)
    struct.pack_into("<I", header, 16, 1)
    struct.pack_into("<I", header, 76, 32)
    struct.pack_into("<I", header, 80, 0x41)
    struct.pack_into("<I", header, 88, 32)
    struct.pack_into("<I", header, 108, 0x00FF0000)
    struct.pack_into("<I", header, 112, 0x0000FF00)
    struct.pack_into("<I", header, 116, 0x000000FF)
    struct.pack_into("<I", header, 120, 0xFF000000)
    raw, _ = store.write_bytes("raw/a.dds", bytes(header) + bytes([0, 0, 255, 255]))
    output = TextureConverter(store).convert(raw, ResourceKind.DDS, "converted/a.png")
    with Image.open(output) as image:
        assert image.size == (1, 1)


def test_unknown_kind_fails(tmp_path: Path):
    store = OutputStore(tmp_path)
    raw, _ = store.write_bytes("raw/a.bin", b"bin")
    with pytest.raises(ValueError):
        TextureConverter(store).convert(raw, ResourceKind.BINARY, "converted/a.png")
```

- [ ] **Step 2: 验证转换器不存在**

Run: `uv run pytest tests/test_textures.py -q`
Expected: FAIL，`textures` 不存在。

- [ ] **Step 3: 实现转换器及 KTX 子进程**

```python
# src/bwp_extractor/textures.py
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
```

- [ ] **Step 4: 运行纹理测试并检查本机 KTX**

Run: `uv run pytest tests/test_textures.py -q && ktx --version && ktx2ktx2 --version`
Expected: 测试 PASS；两个工具均为 v4.4.2。

- [ ] **Step 5: 提交**

```bash
git add pyproject.toml uv.lock src/bwp_extractor/textures.py tests/test_textures.py
git commit -m "feat: 转换 PNG KTX 与 DDS 纹理"
```

### Task 8: 哈希名称恢复与安全语义路径

**Files:**
- Modify: `pyproject.toml`
- Create: `src/bwp_extractor/names.py`
- Test: `tests/test_names.py`

**Interfaces:**
- Consumes: NPK `signature`。
- Produces: `ResolvedName`、`NameResolver.add_path()`、`harvest()`、`resolve()`、`curated_relative()`。百闻牌 32 位哈希使用 `mmh3.hash(path, 0x9747B28C, signed=False)`。

- [ ] **Step 1: 添加 mmh3 并写哈希、映射、收集和穿越测试**

Run: `uv add mmh3`

```python
# tests/test_names.py
from bwp_extractor.names import NameResolver, curated_relative


def test_verified_redirect_hash_and_resolution():
    resolver = NameResolver()
    resolver.add_path("redirect.nxs")
    resolved = resolver.resolve(0xF416002A)
    assert resolved.path == "redirect.nxs"
    assert resolved.source == "candidate"


def test_harvests_paths_and_preserves_unknown():
    resolver = NameResolver()
    resolver.harvest(b"image/cards/1001.png")
    signature = resolver.signature("image/cards/1001.png")
    assert resolver.resolve(signature).path == "image/cards/1001.png"
    unknown = resolver.resolve(123)
    assert unknown.path is None and unknown.source == "unresolved"


def test_rejects_unsafe_paths():
    resolver = NameResolver()
    resolver.add_path("../escape.png")
    assert resolver.resolve(resolver.signature("../escape.png")).path is None


def test_curated_categories():
    assert curated_relative("image/cards/1001.png").startswith("cards/")
    assert curated_relative("gui/login/a.png").startswith("ui/")
    assert curated_relative("misc/a.png").startswith("other/")
```

- [ ] **Step 2: 验证失败**

Run: `uv run pytest tests/test_names.py -q`
Expected: FAIL，`names` 不存在。

- [ ] **Step 3: 实现候选路径哈希和分类**

```python
# src/bwp_extractor/names.py
from dataclasses import dataclass
from pathlib import PurePosixPath
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
        pure = PurePosixPath(normalized)
        if pure.is_absolute() or ".." in pure.parts or not pure.parts:
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
```

- [ ] **Step 4: 运行名称测试**

Run: `uv run pytest tests/test_names.py -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add pyproject.toml uv.lock src/bwp_extractor/names.py tests/test_names.py
git commit -m "feat: 恢复资源路径并生成语义分类"
```

### Task 9: Spine atlas、图片和骨骼关联

**Files:**
- Create: `src/bwp_extractor/spine.py`
- Test: `tests/test_spine.py`

**Interfaces:**
- Consumes: 已解析路径、原始/转换输出和 `OutputStore.link_or_copy()`。
- Produces: `parse_atlas_pages()`、`SpineBundle`、`build_spine_bundle()`；缺文件不抛掉整批任务，而是在 `missing` 中列出。

- [ ] **Step 1: 写完整组与缺失图片测试**

```python
# tests/test_spine.py
from pathlib import Path
from bwp_extractor.output import OutputStore
from bwp_extractor.spine import build_spine_bundle, parse_atlas_pages


ATLAS = (b"hero.png\nsize: 4,4\nformat: RGBA8888\nfilter: Linear,Linear\n"
         b"repeat: none\nbody\n  bounds: 0,0,4,4\n")


def test_reads_atlas_pages():
    assert parse_atlas_pages(ATLAS) == ["hero.png"]


def test_builds_complete_spine_bundle(tmp_path: Path):
    store = OutputStore(tmp_path)
    for name, data in [("hero.atlas", ATLAS), ("hero.skel", b"skeleton"),
                       ("hero.png", b"png")]:
        store.write_bytes(f"raw/{name}", data)
    available = {f"spine/hero.{ext}": tmp_path / f"raw/hero.{ext}"
                 for ext in ("atlas", "skel", "png")}
    bundle = build_spine_bundle(store, "spine/hero.atlas", ATLAS, available)
    assert bundle.missing == ()
    assert (tmp_path / "curated/spine/hero/hero.skel").read_bytes() == b"skeleton"


def test_missing_page_is_reported(tmp_path: Path):
    store = OutputStore(tmp_path)
    store.write_bytes("raw/hero.atlas", ATLAS)
    bundle = build_spine_bundle(store, "spine/hero.atlas", ATLAS,
                                {"spine/hero.atlas": tmp_path / "raw/hero.atlas"})
    assert bundle.missing == ("spine/hero.png", "spine/hero.skel")
```

- [ ] **Step 2: 验证失败**

Run: `uv run pytest tests/test_spine.py -q`
Expected: FAIL，`spine` 不存在。

- [ ] **Step 3: 实现 atlas 页面与同级骨骼关联**

```python
# src/bwp_extractor/spine.py
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
    skeleton = skel if str(skel) in available else json_skeleton
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
```

 `available` 中的图片路径优先指向 `converted/`，atlas/skel/json 指向 `raw/`；只有名称已解析的条目才能进入此映射。

- [ ] **Step 4: 运行 Spine 测试**

Run: `uv run pytest tests/test_spine.py -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/bwp_extractor/spine.py tests/test_spine.py
git commit -m "feat: 关联 Spine 图集图片与骨骼"
```

### Task 10: 提取流水线与增量恢复

**Files:**
- Create: `src/bwp_extractor/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: 前述全部组件。
- Produces: `ExtractedEntry`、`ExtractionPipeline.run(source_path) -> list[EntryRecord]`；缓存键使用 `SourceIdentity`、条目索引、两个校验字段和 `TextureConverter.VERSION`。

- [ ] **Step 1: 写端到端合成包与中断恢复测试**

```python
# tests/test_pipeline.py
from pathlib import Path
import struct
import zlib
from bwp_extractor.pipeline import ExtractionPipeline


def npk_with(entries: list[tuple[int, bytes]]) -> bytes:
    payloads = bytearray()
    indices = bytearray()
    for signature, raw in entries:
        packed = zlib.compress(raw)
        offset = 24 + len(payloads)
        payloads.extend(packed)
        indices.extend(struct.pack("<7I", signature, offset, len(packed), len(raw),
                                   0, 0, 0))
    header = b"NXPK" + struct.pack("<5I", len(entries), 0, 0, 0, 24 + len(payloads))
    return bytes(header + payloads + indices)


def test_extracts_and_reuses_valid_output(tmp_path: Path):
    source = tmp_path / "sample.npk"
    source.write_bytes(npk_with([(1, b"\x89PNG\r\n\x1a\n" + bytes(8))]))
    output = tmp_path / "out"
    pipeline = ExtractionPipeline(output)
    first = pipeline.run(source)
    assert first[0].status == "success"
    assert first[0].raw_path == "raw/sample.npk/00000001.png"
    raw = output / first[0].raw_path
    before = raw.stat().st_mtime_ns
    second = ExtractionPipeline(output).run(source)
    assert second[0].raw_path == first[0].raw_path
    assert raw.stat().st_mtime_ns == before


def test_changed_source_does_not_use_stale_cache(tmp_path: Path):
    source = tmp_path / "sample.npk"
    source.write_bytes(npk_with([(1, b"\x89PNG\r\n\x1a\n" + bytes(8))]))
    output = tmp_path / "out"
    ExtractionPipeline(output).run(source)
    source.write_bytes(npk_with([(1, b"\x89PNG\r\n\x1a\n" + bytes(9))]))
    record = ExtractionPipeline(output).run(source)[0]
    assert (output / record.raw_path).stat().st_size == 17


def test_patch_priority_controls_curated_output(tmp_path: Path):
    base = b"\x89PNG\r\n\x1a\n" + b"base"
    patch = b"\x89PNG\r\n\x1a\n" + b"patch"
    (tmp_path / "base.npk").write_bytes(npk_with([(1, base)]))
    (tmp_path / "patch.npk").write_bytes(npk_with([(1, patch)]))
    names = tmp_path / "names.json"
    names.write_text('{"00000001": "cards/a.png"}', encoding="utf-8")
    output = tmp_path / "out"
    pipeline = ExtractionPipeline(output, names, ["patch.npk"])
    records = pipeline.run(tmp_path)
    patch_record = next(r for r in records if r.archive == "patch.npk")
    assert (output / patch_record.curated_path).read_bytes() == patch
    assert pipeline.duplicates[0]["signature"] == "00000001"
```

- [ ] **Step 2: 验证失败**

Run: `uv run pytest tests/test_pipeline.py -q`
Expected: FAIL，`pipeline` 不存在。

- [ ] **Step 3: 实现两阶段流水线**

```python
# src/bwp_extractor/pipeline.py
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import subprocess
from bwp_extractor.decode import EntryDecodeError, UnsupportedEntryError, decode_entry
from bwp_extractor.formats import detect_format
from bwp_extractor.manifest import EntryRecord, Manifest, make_cache_key
from bwp_extractor.models import NameStatus, ResourceKind, Status
from bwp_extractor.names import NameResolver, curated_relative
from bwp_extractor.npk import NpkEntry, NpkError, read_npk_index
from bwp_extractor.output import OutputStore
from bwp_extractor.sources import ArchiveSource, open_source
from bwp_extractor.textures import TextureConverter


@dataclass
class ExtractedEntry:
    archive: ArchiveSource
    entry: NpkEntry
    kind: ResourceKind
    raw_path: str
    raw_sha256: str


class ExtractionPipeline:
    def __init__(self, output: Path, names: Path | None = None,
                 patch_priority: list[str] | None = None):
        self.store = OutputStore(output)
        self.output = output
        self.names = names
        self.patch_priority = patch_priority or []
        name_data = names.read_bytes() if names else b""
        config_data = name_data + "\0".join(self.patch_priority).encode("utf-8")
        self.cache_salt = sha256(config_data).hexdigest()
        self.issues: list[dict] = []
        self.duplicates: list[dict] = []

    def _cache_valid(self, old: EntryRecord | None, identity: str) -> bool:
        if not old or old.status != Status.SUCCESS or old.cache_identity != identity or not old.raw_path:
            return False
        for relative in (old.raw_path, old.converted_path, old.curated_path):
            if relative and not self.store.path(relative).is_file():
                return False
        raw = self.store.path(old.raw_path)
        return sha256(raw.read_bytes()).hexdigest() == old.raw_sha256

    def run(self, source_path: Path) -> list[EntryRecord]:
        previous = Manifest.load(self.output / "manifest/entries.jsonl")
        resolver = NameResolver()
        if self.names:
            resolver.load_mapping(json.loads(self.names.read_text(encoding="utf-8")))
        converter = TextureConverter(self.store)
        extracted: list[ExtractedEntry] = []
        records: dict[str, EntryRecord] = {}
        seen_signatures: dict[int, str] = {}
        archives = open_source(source_path).archives()
        priority = {name: i + 1 for i, name in enumerate(self.patch_priority)}
        archives.sort(key=lambda a: (priority.get(a.relative_name, 0), a.relative_name))
        for archive in archives:
            identity = archive.identity()
            try:
                with archive.open() as stream:
                    index = read_npk_index(stream, identity.size)
                    for entry in index.entries:
                        key = f"{archive.relative_name}:{entry.index}:{entry.signature:08x}"
                        if entry.signature in seen_signatures:
                            self.duplicates.append({"signature": f"{entry.signature:08x}",
                                "base": seen_signatures[entry.signature], "patch": key})
                        else:
                            seen_signatures[entry.signature] = key
                        cache_identity = make_cache_key(archive.relative_name, entry.index, identity, entry, f"{TextureConverter.VERSION}:{self.cache_salt}")
                        old = previous.get(key)
                        if self._cache_valid(old, cache_identity):
                            records[key] = old
                            continue
                        try:
                            data = decode_entry(stream, entry)
                            kind = detect_format(data)
                            relative = f"raw/{archive.relative_name}/{entry.signature:08x}.{kind.value}"
                            self.store.write_bytes(relative, data)
                            digest = sha256(data).hexdigest()
                            resolver.harvest(data)
                            extracted.append(ExtractedEntry(archive, entry, kind, relative, digest))
                            records[key] = EntryRecord(archive.relative_name, entry.index,
                                f"{entry.signature:08x}", Status.SUCCESS, NameStatus.UNRESOLVED,
                                kind, relative, None, None, digest, None, cache_identity)
                        except UnsupportedEntryError as exc:
                            records[key] = EntryRecord(archive.relative_name, entry.index,
                                f"{entry.signature:08x}", Status.UNSUPPORTED, NameStatus.UNRESOLVED,
                                None, None, None, None, None, str(exc))
                        except EntryDecodeError as exc:
                            records[key] = EntryRecord(archive.relative_name, entry.index,
                                f"{entry.signature:08x}", Status.CORRUPT, NameStatus.UNRESOLVED,
                                None, None, None, None, None, str(exc))
            except NpkError as exc:
                self.issues.append({"archive": archive.relative_name, "error": str(exc)})
        for item in extracted:
            key = f"{item.archive.relative_name}:{item.entry.index}:{item.entry.signature:08x}"
            record = records[key]
            resolved = resolver.resolve(item.entry.signature)
            if resolved.path:
                record.name_status = NameStatus.RESOLVED
                record.curated_path = curated_relative(resolved.path)
            if item.kind in {ResourceKind.PNG, ResourceKind.KTX1, ResourceKind.KTX2, ResourceKind.DDS}:
                converted = f"converted/{item.archive.relative_name}/{item.entry.signature:08x}.png"
                try:
                    converter.convert(self.store.path(item.raw_path), item.kind, converted)
                    record.converted_path = converted
                    if record.curated_path:
                        record.curated_path = str(PurePosixPath(record.curated_path).with_suffix(".png"))
                        self.store.link_or_copy(self.store.path(converted), record.curated_path)
                except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
                    record.status = Status.CONVERSION_FAILED
                    record.converted_path = None
                    record.curated_path = None
                    record.error = str(exc)
            elif record.curated_path:
                self.store.link_or_copy(self.store.path(item.raw_path), record.curated_path)
        ordered = [records[key] for key in sorted(records)]
        self.store.write_jsonl("manifest/entries.jsonl", [r.to_dict() for r in ordered])
        return ordered
```

`cache_identity` 统一由 `make_cache_key()` 生成；名称映射和补丁优先级经 `cache_salt` 进入缓存键。`self.issues` 由 CLI 写入 `run.json`，包级错误必须使退出码非零。

- [ ] **Step 4: 运行流水线测试与全量测试**

Run: `uv run pytest tests/test_pipeline.py -q && uv run pytest -q`
Expected: PASS；第二个测试证明来源变化后重新写入。

- [ ] **Step 5: 提交**

```bash
git add src/bwp_extractor/pipeline.py src/bwp_extractor/manifest.py tests/test_pipeline.py
git commit -m "feat: 串联提取流水线与增量恢复"
```

### Task 11: inspect/extract CLI、Spine 集成和最终报告

**Files:**
- Modify: `pyproject.toml`
- Create: `src/bwp_extractor/cli.py`
- Modify: `src/bwp_extractor/pipeline.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `ExtractionPipeline`、`open_source`、所有状态。
- Produces: `main(argv=None) -> int`、命令 `bwp-extractor inspect INPUT` 与 `bwp-extractor extract INPUT --output DIR`；报告包含按状态和类型统计、失败详情、Spine 缺失项。

- [ ] **Step 1: 写 CLI 退出码与输出文件测试**

```python
# tests/test_cli.py
from pathlib import Path
from bwp_extractor.cli import main
from tests.test_pipeline import npk_with


def test_extract_command_writes_report(tmp_path: Path):
    source = tmp_path / "a.npk"
    source.write_bytes(npk_with([(1, b"\x89PNG\r\n\x1a\n" + bytes(8))]))
    output = tmp_path / "out"
    assert main(["extract", str(source), "--output", str(output)]) == 0
    assert (output / "manifest/entries.jsonl").is_file()
    assert (output / "reports/run.json").is_file()


def test_inspect_does_not_create_output(tmp_path: Path):
    source = tmp_path / "a.npk"
    source.write_bytes(npk_with([(1, b"\x89PNG\r\n\x1a\n" + bytes(8))]))
    assert main(["inspect", str(source)]) == 0
    assert not (tmp_path / "output").exists()
```

- [ ] **Step 2: 验证失败**

Run: `uv run pytest tests/test_cli.py -q`
Expected: FAIL，`cli` 不存在。

- [ ] **Step 3: 实现 CLI 与结构化报告**

```python
# src/bwp_extractor/cli.py
import argparse
from collections import Counter
import json
from pathlib import Path
from bwp_extractor.pipeline import ExtractionPipeline


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="bwp-extractor")
    sub = result.add_subparsers(dest="command", required=True)
    for name in ("inspect", "extract"):
        command = sub.add_parser(name)
        command.add_argument("input", type=Path)
        command.add_argument("--platform", choices=["android"], default="android")
        if name == "extract":
            command.add_argument("--output", type=Path, required=True)
            command.add_argument("--names", type=Path)
            command.add_argument("--patch", action="append", default=[],
                                 help="Archive relative name; repeat from low to high priority")
    return result


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    if args.command == "inspect":
        records, issues = ExtractionPipeline.inspect(args.input)
        summary = {
            "entries": len(records),
            "status": dict(Counter(r.status.value for r in records)),
            "kinds": dict(Counter(r.kind.value for r in records if r.kind)),
            "archive_issues": issues,
        }
        print(json.dumps(summary, ensure_ascii=False))
        return 1 if issues or any(r.status != "success" for r in records) else 0
    pipeline = ExtractionPipeline(args.output, args.names, args.patch)
    records = pipeline.run(args.input)
    counts = Counter(r.status.value for r in records)
    pipeline.store.write_json("reports/run.json", {
        "status": dict(counts),
        "failures": [r.to_dict() for r in records if r.status != "success"],
        "archive_issues": pipeline.issues,
        "spine_issues": pipeline.spine_issues,
        "duplicates": pipeline.duplicates,
        "unresolved": sum(r.name_status == "unresolved" for r in records),
    })
    failed = counts["unsupported"] or counts["corrupt"] or counts["conversion_failed"]
    return 1 if failed or pipeline.issues else 0
```

```toml
# 加入 pyproject.toml
[project.scripts]
bwp-extractor = "bwp_extractor.cli:main"
```

在 `ExtractionPipeline` 中加入不创建输出目录的检查入口，以及 Spine 汇总：

```python
# src/bwp_extractor/pipeline.py
from bwp_extractor.spine import build_spine_bundle

# __init__() 增加：
self.spine_issues: list[dict] = []

@staticmethod
def inspect(source_path: Path) -> tuple[list[EntryRecord], list[dict]]:
    records = []
    issues = []
    for archive in open_source(source_path).archives():
        try:
            with archive.open() as stream:
                stream.seek(0, 2)
                size = stream.tell()
                stream.seek(0)
                index = read_npk_index(stream, size)
                for entry in index.entries:
                    key = f"{archive.relative_name}:{entry.index}:{entry.signature:08x}"
                    try:
                        data = decode_entry(stream, entry)
                        kind = detect_format(data)
                        records.append(EntryRecord(archive.relative_name, entry.index,
                            f"{entry.signature:08x}", Status.SUCCESS, NameStatus.UNRESOLVED,
                            kind, None, None, None, sha256(data).hexdigest(), None))
                    except UnsupportedEntryError as exc:
                        records.append(EntryRecord(archive.relative_name, entry.index,
                            f"{entry.signature:08x}", Status.UNSUPPORTED, NameStatus.UNRESOLVED,
                            None, None, None, None, None, str(exc)))
                    except EntryDecodeError as exc:
                        records.append(EntryRecord(archive.relative_name, entry.index,
                            f"{entry.signature:08x}", Status.CORRUPT, NameStatus.UNRESOLVED,
                            None, None, None, None, None, str(exc)))
        except NpkError as exc:
            issues.append({"archive": archive.relative_name, "error": str(exc)})
    return records, issues

# run() 中，在排序 records 前执行：
available = {}
for item in extracted:
    resolved = resolver.resolve(item.entry.signature)
    if resolved.path:
        record = records[f"{item.archive.relative_name}:{item.entry.index}:{item.entry.signature:08x}"]
        output = record.converted_path if item.kind in {ResourceKind.PNG, ResourceKind.KTX1, ResourceKind.KTX2, ResourceKind.DDS} else item.raw_path
        if output:
            available[resolved.path] = self.store.path(output)
for item in extracted:
    if item.kind != ResourceKind.ATLAS:
        continue
    resolved = resolver.resolve(item.entry.signature)
    if not resolved.path:
        continue
    bundle = build_spine_bundle(self.store, resolved.path,
                                self.store.path(item.raw_path).read_bytes(), available)
    if bundle.missing:
        self.spine_issues.append({"atlas": resolved.path, "missing": bundle.missing})
```

名称未解析的 atlas 只保留 raw 输出；`--patch` 按从低到高排列，高优先级包在成品视图后写入；`--names` 接受 Task 8 定义的十六进制签名到路径 JSON 映射。

- [ ] **Step 4: 运行 CLI 测试与安装后命令**

Run: `uv sync && uv run pytest tests/test_cli.py -q && uv run bwp-extractor --help`
Expected: 测试 PASS；帮助展示 `inspect`、`extract` 和 `--platform android`。

- [ ] **Step 5: 提交**

```bash
git add pyproject.toml uv.lock src/bwp_extractor/cli.py src/bwp_extractor/pipeline.py tests/test_cli.py
git commit -m "feat: 提供提取检查命令与运行报告"
```

### Task 12: 真实样本验收与使用文档

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-11-03-bwp-extractor-design.md`（仅当实现与已批准设计有事实差异时记录）
- Test: 本地真实样本，不创建包含版权素材的测试文件。

**Interfaces:**
- Consumes: 完整 CLI。
- Produces: 可复现的安装、输入、输出、安全、错误和增量使用说明；真实样本验收结果。

- [ ] **Step 1: 运行全部自动化测试**

Run: `uv run pytest -q`
Expected: PASS。

- [ ] **Step 2: 对 APK 做只读检查**

Run: `uv run bwp-extractor inspect samples/yysbwp-release-1.0.365_netease_96.apk --platform android`
Expected: 至少识别 `gui2.npk` 63 项、`sticker.npk` 156 项；`gui2.npk` 包含 40 PNG、10 KTX1；加密 `script.npk` 明确报告不支持，不能静默跳过。

- [ ] **Step 3: 对 APK 内美术包做真实转换验收**

Run: `uv run bwp-extractor extract samples/yysbwp-release-1.0.365_netease_96.apk --platform android --output output/apk`
Expected: KTX 成功生成可打开 PNG；所有来源可追踪；加密/未知资源进入非零汇总；输出中无路径穿越。

- [ ] **Step 4: 做桌面版对照与增量验收**

Run: `uv run bwp-extractor extract D:/yysbwp/Documents/res/sticker.npk --output output/desktop-sticker`
Expected: 条目数和类型与 inspect 一致，重复执行不修改已验证输出，来源变更后缓存失效。

- [ ] **Step 5: 验收完整手游卡牌与 Spine**

由用户提供或显式下载当前手游 `texture_card1` 和至少一个 `spine_hero*` 包后，分别执行 `inspect` 与 `extract`。Expected: 卡牌纹理转换成功；Spine atlas 引用图片可找到，skel/json 被同组保留，缺失引用写入报告。没有这两类真实包时不得宣布完整手游目标已完成。

- [ ] **Step 6: 更新 README 并检查仓库无版权样本**

README 写明两条命令、三层输出、名称回退、非零退出、KTX-Software 要求、安全声明和未来下载器不联网边界。

Run: `git status --short && git ls-files`
Expected: 不包含 `samples/`、`output/`、APK、NPK 或提取成品。

- [ ] **Step 7: 提交**

```bash
git add README.md docs
git commit -m "docs: 完善提取器使用与验收说明"
```
