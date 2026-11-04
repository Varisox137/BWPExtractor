# 百闻牌美术资源提取器重写设计

日期：2026-11-03

## 1. 背景与目标

旧项目 <https://github.com/Varisox137/yysbwp_extractor> 是单 NPK、单目录的 PNG 提取流水线：调用 Python 2 的 NeteaseUnpackTools，随后用 Magika 识别类型、zlib 解压、KTX CLI 转换并收集 PNG。它存在以下限制：

- 依赖 Python 2、外部脚本、Magika 和 PATH 中的 KTX 工具，配置缺少示例。
- 只处理一个包，路径和目录重命名依赖 Windows 字符串及 `yysbwp` 名称。
- 多数错误只打印，可能留下看似成功的残缺结果。
- 数字文件名和多级 PNG 汇总丢失来源与资源关系，遍历顺序可能改变输出名称。
- 不支持 Spine 关联、语义命名、增量执行和结构化报告。

新项目以当前手游资源为主，首要支持 Android；本机旧 Windows 桌面版用于对照回归，不承诺 iOS 或其他 NeoX 游戏兼容性。目标是可靠提取 2D 与 Spine 美术资源，同时保留原始资源和可追踪元数据，并生成尽可能按卡牌、式神、UI 归类的成品视图。

## 2. 本机与真实样本

已确认本机环境：

- Windows + Git Bash，Python 3.14.7、uv 和 Git 可用。
- KTX-Software 4.4.2 已安装，`ktx.exe` 与 `ktx2ktx2.exe` 可用。
- 没有 Python 2、Magika 或 Pillow。
- `D:/yysbwp` 有 105 个桌面版 NPK，总计约 10.98 GiB。
- 已有 NeoXtractor 可执行程序，但只暴露 GUI 入口，不作为自动化核心。

经用户同意，从官网取得 `yysbwp-release-1.0.365_netease_96.apk`，仅用于静态分析，不安装或运行。样本事实：

- APK 大小 828,901,814 字节，SHA-256 为 `a975a42ebe93e6224348781dc96968b36096d1e8969a5453bbeabf9b98cf21fc`。
- APK 包含 19 个 NPK；`assets/update.ini` 指向官方 Android 补丁清单。
- `subpack_version.json` 的资源版本为 1.0.364，列出 `texture_card1`、`spine_hero1/2/3`、`bigtexture`、`loading` 六个独立 NPK 子包。APK 本身不包含完整卡牌和 Spine 资源。
- `gui2.npk` 使用 NXPK 头和 28 字节索引，63 个条目中有 40 个 PNG、10 个 KTX1，以及字体和配置。
- APK 中多个条目的压缩标志为 0，但内容实际是 zlib 流；仅相信标志或扩展名会漏解。
- `script.npk` 存在加密条目，不能把语义命名建立在其必然可解密之上。
- 索引中的两个校验字段均不等于标准 `zlib.crc32` 结果。当前只记录字段值，不声称 CRC 已验证；完整性由索引/数据边界、精确读取长度、zlib 完整流、解压后长度和具体格式解析共同检查。

## 3. 外部项目调研

- [NeoXResearch](https://github.com/ZhangFengze/NeoXResearch) 记录了 24 字节 NXPK 头、28 字节索引、zlib/LZ4 和加密标志，也指出部分版本会在 NPK 之外再次加密文件。
- [unnpk](https://github.com/YJBeetle/unnpk) 根据标志及上下层长度尝试 zlib，再按内容识别类型；其失败后直接导出原文的行为不采用。
- [neox-tools](https://github.com/xNul/neox-tools) 使用 filelist 哈希映射恢复路径，未命中项进入 `unknown_file_name`；还展示了其他 NeoX 变体的 40 字节索引。
- [zed-0xff/nxpk](https://github.com/zed-0xff/nxpk) 从文本和二进制中收集候选路径，再计算哈希恢复名称。
- [NeoXtractor](https://github.com/NeoXtractor/NeoXtractor) 展示 NXPK/EXPK、NXFN 文件名、更多压缩/加密及 KTX/PVR/ASTC/DDS 格式，但其 CLI 尚未完成、依赖较重且采用 AGPL-3.0。
- [denpk2](https://github.com/hax0r31337/denpk2) 展示 NeoX 2 的格式差异，证明不能把所有网易 NPK 当作同一种格式。
- 本轮未找到另一个可参考的百闻牌专用公开实现；`Aexadev_NeoX_Extractor` 明确表示暂无公开代码计划。

以上项目只作为格式与流程参考。本项目不移植 AGPL 代码，不继承其依赖和许可证义务。

## 4. 方案选择

采用 **Python 3 自研轻量核心 + 本机 KTX-Software**。项目使用 uv 管理环境，优先使用标准库完成 CLI、APK/ZIP、NXPK 和 zlib 处理；只有真实样本证明需要时才增加图像解码依赖。

未采用的方案：

1. 移植 NeoXtractor：格式覆盖较快，但引入 AGPL-3.0、重依赖和 GUI 数据模型耦合。
2. 封装 NeoXtractor 可执行程序：自动化、错误报告和断点恢复受未完成 CLI 限制。

格式支持遵循样本驱动：已验证能力才标记为支持；其他 NeoX 变体只识别、报告并保留扩展点。

## 5. 架构与组件

CLI 提供两个主要命令：

```text
bwp-extractor inspect INPUT [--platform android]
bwp-extractor extract INPUT --output DIR [--platform android]
```

输入可以是 NPK、包含 NPK 的目录、APK 或 ZIP。`inspect` 只读扫描并汇总格式、条目类型与问题；`extract` 执行完整提取。

组件边界：

- `ResourceSource`：统一列举容器、读取元数据和按偏移读取。当前实现本地文件、目录和 ZIP/APK；未来下载器实现相同接口。当前版本不主动联网。
- `NpkReader`：读取头和索引，检查容器类型、索引大小、偏移和条目边界；逐项读取，不载入整个 NPK。
- `EntryDecoder`：处理已验证的存储与 zlib 条目。结合索引标志、上下层长度和内容魔数判断，但任何解压失败都显式报告。加密、未知压缩和未知索引变体标记为不支持。
- `FormatDetector`：以魔数和专用解析器识别 PNG、KTX1/KTX2、DDS、Spine atlas/skel/json 及文本；不依赖 Magika。PVR、ASTC 等只有在本项目样本中出现并验证后才加入转换支持。
- `TextureConverter`：PNG 原样保留；KTX1/KTX2 使用检测到的 KTX-Software；真实 APK 验收确认其不能直接输出 ETC1/ETC2 PNG，因此这两类 KTX1（含 ETC2/EAC alpha）由本地解码器处理；DDS 由独立适配器处理。外部工具用参数数组调用，不经过 shell 拼接。
- `SpineAssembler`：根据 atlas 引用及 skel/json 关系组织完整资源组，保留相对路径；缺文件时保留已得资源并报告不完整组。
- `NameResolver`：依次使用内嵌文件名清单、用户显式映射、从已解码文本收集的候选路径哈希。未命中项使用稳定哈希名并标记 `unresolved`。不执行游戏脚本，不要求解密 `script.npk` 才能提取图片。
- `ManifestWriter`：输出逐条来源、转换、命名和错误记录。

主流程：

```text
ResourceSource → NpkReader → EntryDecoder → FormatDetector
             → 原始导出 / 图片转换 → SpineAssembler → NameResolver → 成品视图与清单
```

## 6. 输出与更新语义

```text
<输出目录>/
  raw/                  # 解压并验证后的原始资源
  converted/            # 转为通用 PNG 的纹理
  curated/              # 按卡牌、式神、UI 等组织的成品视图
  manifest/entries.jsonl
  reports/run.json
```

- `raw/` 使用来源包相对路径和条目哈希形成稳定名称，不依赖遍历顺序。
- `converted/` 默认导出最高分辨率层级；原始 KTX 保留完整 mipmap 和容器信息。PNG 不二次编码。
- Spine 文件与其图片作为关联组输出，不拆成无上下文的散图。
- `curated/` 优先用同一卷上的硬链接引用已有输出，避免重复占用；硬链接不可用时回退为复制，并在报告中记录实际方式。
- 未解析名称的资源保留在稳定目录并进入 `unresolved` 统计，不伪造式神或卡牌名称。
- 基础包与补丁包的所有来源均记录。成品视图按用户明确配置的补丁优先级选择，重复与冲突写入报告，不依赖文件系统遍历顺序。
- `entries.jsonl` 至少记录来源、条目哈希、偏移、上下层尺寸、索引校验字段、类型、各输出路径、名称状态和错误。

## 7. 安全与使用声明

README 开头必须设置醒目的独立章节，并作为验收项：

- 本项目与网易及《阴阳师：百闻牌》官方无关，也未获得其背书。
- 游戏资源、APK 和相关素材的权利归原权利人所有。
- 工具仅用于学习、研究和个人备份；用户须合法取得文件，并遵守适用法律、用户协议和授权范围，不得利用本工具侵犯版权或从事作弊等行为。
- 仓库不提交 APK、NPK、提取成品或含版权资源的名称映射；`samples/` 与提取输出必须被版本控制忽略。
- 工具只静态读取用户指定的本地文件，不执行包内脚本，不注入或修改游戏进程，不重打包客户端。
- 当前版本不发起网络请求；未来下载器必须由用户显式触发，并展示来源、大小和目标位置。
- 所有来自容器的路径都经过清理，禁止绝对路径和 `..` 穿越，写入范围限制在输出目录；输入文件永不修改。
- 文件先写临时位置，完成校验后原子替换，避免半成品被当成成功结果。

## 8. 错误、性能与恢复

- 提取状态 `status` 至少区分 `success`、`unsupported`、`corrupt` 和 `conversion_failed`；名称状态 `name_status` 独立记录为 `resolved` 或 `unresolved`。
- `unresolved` 不视为提取失败；其他失败在终端汇总、写入 `run.json`，并使命令以非零状态结束。
- 单条目解码失败不得产生伪原始文件；批量模式可以继续处理其他条目，但最终报告不能显示全绿。
- 每次只处理有限数量条目，限制工作线程和内存。KTX 子进程有独立错误捕获和输出路径约束。
- 源文件身份由规范化来源标识、文件大小和内容 SHA-256 组成；缓存键另含条目校验字段、转换器及工具版本。只有完整且验证过的输出才可跳过；源文件变化后不得复用旧结果。

## 9. 验证与完成标准

项目建立 pytest 自动化测试，但不包含版权游戏素材：

- 用合成 NPK 覆盖存储/zlib、错误魔数、索引越界、截断、长度不符、路径穿越、重复条目和中断恢复。
- 用程序生成的小图片及工具生成的纹理验证格式识别和转换。
- 用合成 atlas/skel/json 验证 Spine 关联、缺失引用和名称回退。
- 验证 CLI 的成功、部分失败、未知格式与非零退出码。

真实资源验收：

1. 在 APK 的 `gui2.npk`、`sticker.npk` 等包上执行 inspect/extract，核对条目数、类型数、输出可打开性和报告。
2. 在本机桌面版代表性包上对照旧流程，确认新版不丢资源且名称稳定。
3. 在当前手游 `texture_card1` 与 `spine_hero1/2/3` 上执行 inspect/extract，验证卡牌纹理、真实 atlas/图片、页面引用、错误报告与路径安全；APK 内置样本不替代这些输入。
4. 重复执行相同输入应跳过已校验结果；修改来源后不得错误跳过。

真实验收定案（用户已接受）：

- `texture_card1` 为 2739/2739 成功；`spine_hero1` 为 760/760 成功，`spine_hero2` 为 1107/1107 成功。
- `spine_hero3` 为 921 成功、1 失败；签名 `a02fb7d2` 的 1495 字节条目编码未确认，手机与桌面字节完全一致，保留失败报告且不生成伪成品。
- 真实包没有可靠的名称映射，相关条目均为 `unresolved`；真实 atlas、图片和页面引用已验证，但没有完成真实语义 Spine bundle，也不声称其成功。
- 上述未知编码与语义分组是用户接受的当前交付限制，不是遗留的完成承诺；后续取得可靠映射时可再增强。

## 10. 明确不在当前范围

- GUI、自动下载与更新器实现。
- iOS 或其他手游平台的兼容性承诺。
- 3D 模型、3D 动画、音频和视频转换。
- 游戏脚本反编译、进程调试、内存读取、客户端修改或 NPK 重打包。
- 对未见 EXPK、NeoX 2 或加密资源的兼容性声明。
