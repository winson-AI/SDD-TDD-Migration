# Harmony 自动测试接入

## 定位与读取

这是 Test-Runner 的一种真实 Main 执行器，适用于 HarmonyOS UI/端到端路径。普通单测、构建检查和其他平台仍使用项目已有 adapter。入口是 [harmony_adapter.py](../scripts/harmony_adapter.py)，内核在 [runtime/harmony](../runtime/harmony/main.py)。先读本页；需要诊断某项能力时再加载其内核源码，不把内核的提示词当作编排角色指令。

外层控制流保持：OpenSpec 冻结 → Implementer/Fixer 代码接受 → Test-Runner assignment → host execute_test → staging tests → Ledger submit → MO accept → DoD/Auditor。内部 Planner/Executor/Verify 是同一 Test-Runner assignment 内的执行组件，消息、工具调用和中间结果形成执行工件；不产生独立的跨模块 assignment，不直接调用 Fixer，不修改任何 SPEC 或 Ledger 状态。跨角色共享只通过 Ledger 接受的工件引用。

## 源能力与迁移位置

| 能力 | 保留内容 / 接入点 |
| --- | --- |
| 分层执行 | 原 `decision`、`planner_agent`、`decision_hooks`；单步 Observe/Act/反馈、最大步数、任务超时、禁止失败后重启掩盖问题 |
| 执行器 | general、GLM、MCP、Hypium MCP 四种实现与工厂；截图、布局、HDC 动作、特殊采集 |
| 验证 | 原 Verify 选择器、单图/双图/跨步骤/参考图/视频五类工具；冻结 verification 指定类型，auto 保留原动态路由 |
| 视频 | 录制分段、时间映射、拼接、裁剪、阈值压缩、动态 UI 验证；保留原片、裁剪片、mapping，修正删除证据与清理异常 |
| 记忆 | CompressedSession、上下文压缩、定期反思、XPath 层级缓存、调用录制、去冗余 |
| 回放 | 原 ToolPlayer：多步缓存、坐标/XPath、输入文本、进度条重新取坐标、临时控件、意外弹窗处理、失败重规划、总超时；verify 仍真实执行 |
| 技能 | 6 个原业务技能、自定义工具加载、技能脚本运行、媒体生成；保留全部实现，按冻结测试范围使用 |
| 输入 | Markdown 原文导入、XMind 模型转换与转换模型回退；保留全部 sheet，转换结果先审核再冻结 |
| 知识 | `knowledge_ref` 显式传入已接受的知识工件，按 hash 校验，Planner 与 Executor 可读 |
| 报告 | 原 HTML/Markdown/JSON 时间线、截图、布局、视频、工具反馈、token 统计、组合报告生成器；增加 path/ASSERT/代码/冻结版本绑定 |
| 运行隔离 | 每条 PATH 一个宿主子进程、一个新证据目录、设备互斥锁；超时杀进程组，保留已有日志 |

源快照包含 91 个文件，包括原源码、技能、原测试、Apache LICENSE 和当前使用的 0.6.5 Hypium MCP wheel。来源与逐文件摘要见 [UPSTREAM.json](../runtime/harmony/UPSTREAM.json)；本地修订记录在同一文件中。没有复制源项目的凭证配置、历史报告、历史用户记忆、业务知识或机器专属 lockfile。原生 CLI 留作兼容入口；SDD 正式测试须经上述 adapter，不能以原 CLI 最终文本直接改 Green。

## 1. design：用例导入与冻结

[harmony_design.py](../scripts/harmony_design.py) 接受 `--input <MD或XMind绝对路径> --module M001 --output <新目录>`。XMind 另需 `--config <配置JSON> --app-name <被测应用>`，只运行转换模型，不连接设备。

输出保留输入摘要、完整原始用例、规范化 Markdown、XMind 主题树，以及 `draft-not-executable` 的测试候选。不会复用仅同名但内容可能过期的转换文件，也不静默补齐验收语义。Test Designer 完成 CASE/REQ 映射、参数路径展开、操作与断言时序；每条参数实例独立 PATH。候选 ID 在审核时与全局已有 ID 对齐，冻结后不因名称修改而重编号。

使用 [harmony-test-path.json](../../../template/harmony-test-path.json)。每个 assertion 需要：

- `assertion_id`：唯一稳定 ID。
- `expected: true`：表示下方具体可观测谓词成立，不能只描述“返回 true”。
- `description`：从 SPEC 得到的明确期望，须非空。
- `matcher: exact | semantic`：按冻结要求选择；执行器不自动放宽文案匹配。
- `verification: one_image_assert | multi_image_assert | cross_step_image_assert | refer_image_assert | video_assert | auto`。
- `after_step`：在第几个冻结步骤之后立即验证；中途断言不能拖到任务末尾补做。

此适配器对观察谓词作布尔规范化。已有数值/字符串 equality 用例继续使用原项目适配器，或经 Spec-Designer 的 CR 明确迁移成有语义的 UI 谓词；不得直接把原 expected 改 true。需要更强机器可判定的精确数值时使用项目测试脚本。`after_step` 会进入完整 query 和 Planner 的交错操作指令；当前没有证明 Agent 每一步操作语义的确定性监视器，时序需通过时间线审核，真机验收仍必需。

## 2. 宿主配置

使用 [harmony-config.json](../../../template/harmony-config.json) 和 [harmony-test-adapter.json](../../../template/harmony-test-adapter.json)，替换占位符后由宿主审核并提交为受控输入。

- Python 需兼容原引擎（至少 3.10）；SDK、Hypium/HDC、图像/视频依赖见 [requirements.txt](../runtime/harmony/requirements.txt)。wheel 已保留，安装时 cwd 应是该 requirements 所在目录。源 pyproject 中机器专属的 Hypium 开发包路径没有迁移，宿主提供相应运行环境。
- `models` 使用原 `AppConfig` 字段；模型密钥用 `{"env":"变量名"}`，运行时解析，不把密钥写入模板。支持多 Planner 模型、执行器选择、Verify、压缩、反思和 special_test 配置。
- `execute_provider` 决定工厂实现，例如 `hypium_mcp_agent`；不是模型 HTTP 协议名。所有原执行器仍可配置。
- 必填设备序列号，不自动挑选设备。Global 仍分配设备资源锁，adapter 另外用本机文件锁防止并行路径争抢同一设备；多台宿主共同连接一个设备时需要全局锁协调。
- 对 `video_assert` 必须开启视频；默认模板开启，adapter 强制保留原始视频。
- 原引擎任务预算默认 1800 秒；host adapter 模板为 1860 秒，留收尾时间。总修复次数仍由 MO/Auditor 控制，内部导航重规划不会增加代码修复轮次。
- skills/自定义工具具有设备动作和脚本执行能力；宿主约束它们的权限和目标范围。测试数据不是 shell 指令。应用重置、fixture 创建等动作应写入冻结前置/步骤；不能把原批量入口的自动关 App 隐式施加到所有迁移测试。

适配器不安装 App、不自动部署代码。设备上的被测包必须由宿主确认对应已接受的 code_baseline，并把构建/安装凭证纳入 fixture/environment 证据。文件基线校验不能单独证明真机已安装同一构建。

## 3. execute：一条 PATH 到 Main

宿主按当前 [execute_test.py](../../migration-ledger/scripts/execute_test.py) 接口调用：

```text
python <execute_test.py> --root <run_root> --module M001 --assignment <id>
  --path-id PATH-M001-001 --adapter <harmony-test-adapter.json>
  --cwd <target_root> --output <新的绝对执行目录>
```

参数必须以 argv 数组传递，上述换行只是展示。host 自动组装完整 query，校验当前 assignment、代码基线，记录 command/query/report/log receipt。每条路径是独立进程；原内核全局注册表不会跨模块污染。原生相对 memory/媒体文件落入本次执行目录，不写源项目或共享包目录。

输入中的 preconditions、steps、parameters、dependency_refs、ASSERT ID/描述全部传入 Planner。Verify 入口凭单个 `[ASSERT:id]` 找回冻结描述，防止 Agent 改写期望后自证；仍使用原选择器和对应媒体验证能力。固定 verification 不被低成本类型替代；auto 按原策略选择。原最终任务文本和播放总成功数仅作原始报告内容。

## 4. 输出与三态

目录包含：`query.json / result.json / execution.log / receipt.json`，以及 `harmony/observations.json`、environment、原生 reports、memory、engine.log、所有媒体工件。每个观察记录 ASSERT ID、顺序、真实工具、布尔结果、原始理由和媒体 SHA256，每次立即落盘。

- Green：完整 ASSERT 集合、有真实媒体证据、匹配冻结验证类型、全部观察通过、无执行异常；host exit=0。
- Red：完成验证后观察到冻结谓词失败；保留实际失败和证据，根因归属仍由 Diagnostician 确认；host exit=1。
- Yellow：缺设备/依赖/模型、运行异常/超时、缺 ASSERT/媒体、验证解析歧义、模式不符、未知身份，或同 ASSERT 同轮 pass/fail 混合；host exit=2 或宿主异常码。

所有尝试保留；不能只取最后一次 Green。视频异常、无法加载图片等不被判产品 Red。原 parser 对“不通过”可能误识别为通过，迁移版要求明确结论，歧义触发 Yellow。

使用 [harmony_stage.py](../scripts/harmony_stage.py)：

```text
python <harmony_stage.py> --root <run_root> --module M001 --assignment <id>
  --receipt <PATH1/receipt.json> --receipt <PATH2/receipt.json> --output <新stage-result.json>
```

它只生成 staging 工件，不自动提交或验收；要求所有冻结路径各有一个 receipt，自动连接旧结果 `retest_of`。超时/缺报告以 executed=false Yellow 保留 receipt/log。随后照现有流程 submit/accept，GLOBAL 最终测试可用 `--module GLOBAL`。Ledger 再核对 query/context/三态、assertions 和媒体摘要，不能把 adapter 的 Yellow 改报 Green。证据损坏会拒绝接受，需要重新取证或显式记录不可执行 Yellow，不能伪造新摘要。

## 5. 回放、memory 与 Auditor

`recording_ref` 是经 Ledger 传入的显式录制文件引用。必须校验 hash 和任务文本；知识变化也改变任务文本。接受前一代码基线的录制作为导航提示，但每次 verify 都用本轮实际媒体执行，并绑定本轮 code_baseline。原 XPath/坐标回放、失败重规划和弹窗处理全部保留。未指定录制时正常规划并产生新的候选录制。

原引擎保存的 memory 只是执行优化素材，不能直接成为全局“修复已验证”memory。候选是否可复用由 Ledger 对应验收决定；Auditor 跨模块失败、目标变更、flaky 历史都不因回放而消失。Auditor 仍委派 Fixer，一轮后负责模块 Testing、原发现模块 Testing、独立裁决；失败输出根因待人工。本引擎不绕过这些边界。

## 验证边界

原录制回放单测与适配器/账本测试用于验证逻辑兼容、身份绑定、三态、证据及超时行为；模拟设备/模型的 native 集成测试只验证接线、报告和录制。没有用真实设备、真实模型或业务 App 宣称“能力无劣化”。上线前在相同用例/设备/模型/预算下对照源版，覆盖五类验证、回放重规划、输入、临时控件、视频时间映射及完整报告；比较断言、动作、遗漏、误报和证据可读性，不只比较最终通过率。

## 编译与自动化环境分离

Harmony 内核仅运行 automation PATH；build PATH 由 Test-Runner 经通用 execute_test 直接执行目标构建命令，harmony_stage 支持两种回执并按 test_scope 组装。Harmony 缺设备/模型/运行环境不能阻止已授权编译及其他任务；留原始诊断证据后按 [双环节协议](../../migration-protocol/references/build-automation.md) 提交 automation-unavailable，保持原自动化内核能力和逐 ASSERT 验证。
