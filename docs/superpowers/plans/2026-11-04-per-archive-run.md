# Per-archive Extraction Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 g97 下全部 52 个 NPK 分别提取到来历和开始时刻可辨识的一层目录，并隐藏没有 `converted/` 的结果目录。

**Architecture:** 复用现有 `bwp-extractor extract` 单包入口，由一次性 Python 进程逐包调用 CLI。输出目录由来历相对路径和本地开始时刻组成；单包失败后按规则改名并继续后续任务。

**Tech Stack:** Python 3.12、uv、现有 BWP Extractor CLI、Git Bash。

## Global Constraints

- 输入根目录固定为 `E:/yysbwp_data/com.netease.yysbwp/files/netease/g97/`。
- 输出直接位于 `D:/Programming/BWPExtractor/output/`，不保留 `g97` 层或 `.npk` 后缀。
- 目录名以来源相对路径下划线连接，末尾追加 `_YYYYMMDD_HHMMSS`。
- 每包完成后没有 `converted/` 的目录改名为以 `.` 开头。
- 不修改输入、不传入名称映射或补丁优先级、不修改提取器代码。
- 每包启动前记录带时区的本地时刻，ISO 8601 格式精确到秒；所有包处理后写入 `output/batch-summary.json`。

---

### Task 1: 全量逐包运行与验收

**Files:**
- Create: `output/batch-summary.json`
- Create: `output/<来源与开始时刻>/manifest/entries.jsonl`
- Create: `output/<来源与开始时刻>/reports/run.json`

**Interfaces:**
- Consumes: `bwp-extractor extract <NPK路径> --output <独立目录>`。
- Produces: 每包独立提取结果，以及包含 `source`、`output`、`returncode`、`started_at` 的批量 JSON 汇总；`output` 是最终目录名。

- [ ] **Step 1: 清理旧结果并检查来源和基础目录名**

经用户确认删除本轮新建的 `output/`，使用 `Path.rglob("*.npk")` 枚举，断言共有 52 个文件且来源基础目录名无重复。

- [ ] **Step 2: 逐包执行、追加开始时刻并按需隐藏**

```bash
uv run python - <<'PY'
import json
from datetime import datetime
from pathlib import Path
import subprocess

source_root = Path("E:/yysbwp_data/com.netease.yysbwp/files/netease/g97")
output_root = Path("D:/Programming/BWPExtractor/output")
archives = sorted(source_root.rglob("*.npk"))
assert len(archives) == 52, f"Expected 52 NPK files, found {len(archives)}"
base_names = ["_".join(p.relative_to(source_root).with_suffix("").parts) for p in archives]
assert len(base_names) == len(set(base_names)), "Output directory collision"
results = []
for archive, base_name in zip(archives, base_names):
    started = datetime.now().astimezone()
    started_at = started.isoformat(timespec="seconds")
    output = output_root / f"{base_name}_{started:%Y%m%d_%H%M%S}"
    completed = subprocess.run([
        "uv", "run", "bwp-extractor", "extract", str(archive),
        "--output", str(output),
    ])
    if not (output / "converted").is_dir():
        hidden = output.with_name(f".{output.name}")
        output.rename(hidden)
        output = hidden
    result = {
        "source": archive.relative_to(source_root).as_posix(),
        "output": output.name,
        "returncode": completed.returncode,
        "started_at": started_at,
    }
    results.append(result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
summary = {
    "total": len(results),
    "succeeded": sum(r["returncode"] == 0 for r in results),
    "failed": sum(r["returncode"] != 0 for r in results),
    "archives": results,
}
output_root.mkdir(parents=True, exist_ok=True)
(output_root / "batch-summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
)
print(json.dumps({k: v for k, v in summary.items() if k != "archives"}, ensure_ascii=False))
PY
```

预期：52 个包均被尝试；已知 `Documents/res/spine_hero3.npk` 可能因一个未知编码条目返回 1，其余有效条目仍保留。

- [ ] **Step 3: 核对全部输出、开始时刻和隐藏规则**

读取批量汇总及每包 `reports/run.json`，断言 52 项均有独立清单和报告，目录名末尾时间戳与 `started_at` 一致。断言有点前缀的目录恰好是没有 `converted/` 的结果，且没有 `.npk` 后缀。列出所有非零项及失败原因。

- [ ] **Step 4: 检查仓库与磁盘状态**

运行 `git status --short` 和 `df -h /d`，确认输出没有进入版本控制、没有意外代码改动，并报告剩余空间。不修改 Git 作者配置。
