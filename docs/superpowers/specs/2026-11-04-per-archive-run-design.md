# 按 NPK 隔离的全量提取运行设计

## 目标

处理 `E:/yysbwp_data/com.netease.yysbwp/files/netease/g97/` 下现有的全部 52 个 NPK，让每个原始包的提取结果、清单和报告完全独立。

## 方案

复用现有单包 CLI，不修改提取器代码。以 `g97` 为相对路径基准，去掉 `.npk` 后缀，将路径分隔符 `/` 替换为 `_`，并在目录末尾追加本地开始时刻 `_YYYYMMDD_HHMMSS`。直接在 `output/` 下形成一层输出目录，不保留 `g97` 这一层：

```text
output/Documents_res_texture_card1_20261104_153000/
  raw/
  converted/
  curated/
  manifest/
  reports/
```

逐包调用 `uv run bwp-extractor extract <绝对NPK路径> --output <对应输出目录>`。本次不提供名称映射或补丁优先级，避免重新引入跨包合并。每包完成后，若其输出目录中没有 `converted/`，将目录改名为以 `.` 开头的默认隐藏目录，例如 `output/.res_common_20261104_153100/`。

## 错误处理与验收

单包失败后继续处理其余包，保留该包报告。在每包子进程启动前记录带时区的本地开始时刻，目录名使用同一时刻；另以 ISO 8601 格式精确到秒写入 `output/batch-summary.json` 的 `started_at` 字段。汇总中的 `output` 记录隐藏改名后的最终目录名。已知 `spine_hero3.npk` 的一个未知编码条目预计仍会明确失败，不据此中止其他包。

验收时核对 52 个一层输出目录、目录末尾时间戳、隐藏规则、每包清单和报告，并确认输入未被修改。若空间不足则停止并报告，不删除既有结果。
