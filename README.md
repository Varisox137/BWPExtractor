# BWP Extractor

## 安全与权利声明

本项目与网易及《阴阳师：百闻牌》官方无关，也未获得其背书。游戏资源、APK 和相关素材的权利归原权利人所有。本工具仅限学习、研究和个人备份；用户须合法取得文件，并遵守适用法律、用户协议和授权范围，不得用于侵犯版权或作弊。

工具只静态读取用户指定的本地 NPK、目录或 APK，不执行包内脚本，不注入或修改游戏进程，不重打包客户端，也永不修改输入文件。所有输出路径都会清理，禁止绝对路径和 `..` 穿越，写入范围仅限指定输出目录。仓库不提交 APK、NPK、名称映射或提取成品；`samples/` 与 `output/` 均被版本控制忽略。

当前版本不发起网络请求。未来下载器也必须由用户显式触发，并在下载前展示来源、大小和目标位置；提取、检查和增量更新不会隐式联网。

## 安装

要求 Python 3.12 或更高版本，以及 [uv](https://docs.astral.sh/uv/)：

```bash
uv sync
```

PNG、DDS 以及 ETC1/ETC2 KTX1 可直接处理。其他 KTX1/KTX2 纹理需要安装 KTX-Software，并确保 `ktx`（或 `ktx.exe`）和 `ktx2ktx2`（或 `ktx2ktx2.exe`）位于 `PATH`；缺少工具或转换失败会写入报告并产生非零退出码。

## 使用

先检查输入，再提取到独立目录：

```bash
uv run bwp-extractor inspect path/to/game.apk --platform android
uv run bwp-extractor extract path/to/game.apk --platform android --output output/apk
```

`inspect` 输出条目、状态、类型和包级错误的 JSON 摘要。`extract` 也接受单个 NPK 或包含 NPK 的目录；桌面文件不需要额外平台参数：

```bash
uv run bwp-extractor extract path/to/sticker.npk --output output/desktop-sticker
```

可用 `--names names.json` 提供名称映射。文件为 JSON 对象，键是 8 位十六进制条目签名，值是相对资源路径，例如：

```json
{"0123abcd": "ui/example.png"}
```

名称解析优先使用显式映射和从已解码文本发现的候选路径。未命中项保留稳定的哈希文件名，`name_status` 标为 `unresolved`，不伪造名称，也不视为提取失败。存在基础包和补丁包时，可按从低到高优先级重复传入 `--patch 包相对路径`；重复与冲突会记录在报告中。

## 输出

```text
<输出目录>/
  raw/                  # 解码并校验后的原始资源，保留完整容器与 mipmap
  converted/            # 第 0 层纹理转换出的 PNG；原 PNG 不二次编码
  curated/              # 已解析名称的 cards/ui/other 成品视图
  manifest/entries.jsonl # 每条资源的来源、类型、哈希、输出路径、命名与错误
  reports/run.json      # 状态汇总、包错误、Spine 缺失引用与重复项
```

`curated/` 优先使用硬链接，不可用时复制。Spine atlas、skel/json 与引用图片按同组组织；缺失引用保留已得文件并写入 `spine_issues`。

相同输入重复执行时，只有来源身份、缓存键和已有输出哈希均通过校验才会跳过，已验证资源不会被改写。来源、名称映射、补丁顺序或转换器变化会使相关缓存失效；损坏或被篡改的输出会重新生成。

## 错误与退出码

成功且无包级问题时退出码为 0。存在 `unsupported`、`corrupt`、`conversion_failed` 或加密/未知包等 `archive_issues` 时，批量处理会尽量保留其他有效结果，但最终退出码为 1，详情见 `manifest/entries.jsonl` 和 `reports/run.json`。不要把部分失败目录当作完整提取结果。

当前不支持加密资源、未见的 NPK 变体、iOS、3D、音频或视频转换；这些限制不会被静默跳过。

## 测试

```bash
uv run pytest -q
```

自动化测试只使用合成数据，不包含版权游戏素材。
