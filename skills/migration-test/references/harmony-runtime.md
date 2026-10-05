# Android/Harmony 自动测试接入

## 定位与读取

Test-Runner 的 Android/Harmony UI/端到端 Main；构建/单测仍用项目 adapter。入口 [harmony_adapter.py](../scripts/harmony_adapter.py)，内核 [runtime/harmony](../runtime/harmony/main.py)。历史 harmony 命名与目录兼容保留。按节点取本页小节，诊断时才加载内核源码/提示词。

外层控制流保持：OpenSpec 冻结 → Implementer/Fixer 代码接受 → Test-Runner assignment → host execute_test → staging tests → Ledger submit → MO accept → DoD/Auditor。内部 Planner/Executor/Verify 是同一 Test-Runner assignment 内的执行组件，消息、工具调用和中间结果形成执行工件；不产生独立的跨模块 assignment，不直接调用 Fixer，不修改任何 SPEC 或 Ledger 状态。跨角色共享只通过 Ledger 接受的工件引用。

## 源能力与迁移位置

| 能力 | 保留内容 / 接入点 |
| --- | --- |
| 分层执行 | 原 `decision`、`planner_agent`、`decision_hooks`；单步 Observe/Act/反馈、最大步数、任务超时、禁止失败后重启掩盖问题 |
| 执行器 | Android 的 ADB/uiautomator2，Harmony 的 HDC/Hypium；general、GLM 与 Harmony MCP 执行器 |
| 验证 | 原 Verify 选择器、单图/双图/跨步骤/参考图/视频五类工具；冻结 verification 指定类型，auto 保留原动态路由 |
| 视频 | 录制分段、时间映射、拼接、裁剪、阈值压缩、动态 UI 验证；保留原片、裁剪片、mapping，修正删除证据与清理异常 |
| 记忆 | CompressedSession、上下文压缩、定期反思、XPath 层级缓存、调用录制、去冗余 |
| 回放 | 原 ToolPlayer：多步缓存、坐标/XPath、输入文本、进度条重新取坐标、临时控件、意外弹窗处理、失败重规划、总超时；verify 仍真实执行 |
| 技能 | 6 个原业务技能、自定义工具加载、技能脚本运行、媒体生成；保留全部实现，按冻结测试范围使用 |
| 输入 | Markdown 原文导入、XMind 模型转换与转换模型回退；保留全部 sheet，转换结果先审核再冻结 |
| 知识 | `knowledge_ref` 显式传入已接受的知识工件，按 hash 校验，Planner 与 Executor 可读 |
| 报告 | 原 HTML/Markdown/JSON 时间线、截图、布局、视频、工具反馈、token 统计、组合报告生成器；增加 path/ASSERT/代码/冻结版本绑定 |
| 运行隔离 | 每条 PATH 一个宿主子进程、一个新证据目录、设备互斥锁；超时杀进程组，保留已有日志 |

早期 HarmonyAgenticTesting 内核叠加 MobileAgenticOperator 的 Android 驱动、平台路由及 test 分支；来源 commit、逐文件摘要和修订见 [UPSTREAM.json](../runtime/harmony/UPSTREAM.json)。保留 Apache LICENSE；不迁入 iOS/WDA、凭证或历史报告/记忆。原生 CLI 仅兼容入口，正式验收走 adapter。

## 1. design：用例导入与冻结

[harmony_design.py](../scripts/harmony_design.py) 在工作流内接受 `--root <run_root> --input <MD或XMind绝对路径> --module M001 --output <run_root>/runs/harmony/sandbox/test-designer/<新请求>`；独立导入可从同样结构的输出路径推导 run_root。XMind 另需 `--config <配置JSON> --app-name <被测应用>`，只运行转换模型，不连接设备。

输出保留输入摘要、完整原始用例、规范化 Markdown、XMind 主题树，以及 `draft-not-executable` 的测试候选。不会复用仅同名但内容可能过期的转换文件，也不静默补齐验收语义。Test Designer 完成 CASE/REQ 映射、参数路径展开、操作与断言时序；每条参数实例独立 PATH。候选 ID 在审核时与全局已有 ID 对齐，冻结后不因名称修改而重编号。

使用 [harmony-test-path.json](../../../template/harmony-test-path.json)，冻结 kind=automation、platform=android|harmony、task_type=test；同 CASE 两端分别编号 PATH。旧 PATH 沿用配置平台，缺省 Harmony。每个 assertion 需要：

- `assertion_id`：唯一稳定 ID。
- `expected: true`：表示下方具体可观测谓词成立，不能只描述“返回 true”。
- `description`：从 SPEC 得到的明确期望，须非空。
- `matcher: exact | semantic`：按冻结要求选择；执行器不自动放宽文案匹配。
- `verification: one_image_assert | multi_image_assert | cross_step_image_assert | refer_image_assert | video_assert | auto`。
- `after_step`：在第几个冻结步骤之后立即验证；中途断言不能拖到任务末尾补做。

expected=true 须有冻结业务含义；数值/字符串用项目脚本或经 CR 明确转为谓词，不能直接改 true。after_step 交错传入 Planner，但不是确定性时序监视器，需结合本次时间线与真机验收核查。

## 2. 宿主配置

推荐先使用 [独立 uv sandbox](../runtime/harmony/README.md)：`uv sync --locked` 安装本目录 `.venv`；`sandbox.py` 提供离线 doctor、用例导入、单 PATH 调试和宿主 adapter 生成。公开默认 LLM 配置复用 MobileAgenticOperator；`.env` 只留本地，角色密钥优先于公共密钥，支持用户自定义配置。独立调试不能代替 host receipt 和 Ledger 验收。

使用 [harmony-config.json](../../../template/harmony-config.json) 和 [harmony-test-adapter.json](../../../template/harmony-test-adapter.json)，替换占位符后由宿主审核并提交为受控输入。

- Python 需兼容原引擎（至少 3.10）；SDK、Hypium/HDC、图像/视频依赖见 [requirements.txt](../runtime/harmony/requirements.txt)。wheel 已保留，安装时 cwd 应是该 requirements 所在目录。源 pyproject 中机器专属的 Hypium 开发包路径没有迁移，宿主提供相应运行环境。
- `models` 使用原 `AppConfig` 字段；模型密钥用 `{"env":"变量名"}`，运行时解析，不把密钥写入模板。支持多 Planner 模型、执行器选择、Verify、压缩、反思和 special_test 配置。
- 密钥也可用 `{"env":["角色变量","公共变量"]}` 按顺序回退；sandbox 加载指定 `.env` 且不覆盖进程同名变量。设备可由 `--device`、配置或 `HARMONY_DEVICE` 按优先级指定。UI 不要求 XMind 转换密钥，XMind 导入只读取转换所需模型配置。
- Android 需 ADB/uiautomator2，使用 general/glm；Harmony 需 HDC/Hypium，四种原执行器均可。拒绝不兼容 provider，不静默切换；模型和凭证可共享。
- 设备：`--device` → `devices[platform]` → 同平台 `device` → `ANDROID_DEVICE/HARMONY_DEVICE`。`--platform` 必须与冻结 PATH 一致；未传时取 PATH 再取配置。GO 锁与 adapter 本机端口租约共同隔离；同一 Android serial 不因 Harmony ip/port 不同而解除互斥。
- 对 `video_assert` 必须开启视频；默认模板开启，adapter 强制保留原始视频。
- 原引擎任务预算默认 1800 秒；host adapter 模板为 1860 秒，留收尾时间。总修复次数仍由 MO/Auditor 控制，内部导航重规划不会增加代码修复轮次。
- skills/自定义工具具有设备动作和脚本执行能力；宿主约束它们的权限和目标范围。测试数据不是 shell 指令。应用重置、fixture 创建等动作应写入冻结前置/步骤；不能把原批量入口的自动关 App 隐式施加到所有迁移测试。

配置可给 `apps.android={name,package}`、`apps.harmony={name,package,ability}`，在当前进程补入包名映射并记录 environment。适配器不部署 App、不自动清空前置状态；重置须写入冻结步骤。宿主预检须绑定已安装 APK/HAP 与 code_baseline、fixture、设备及模型连通性。

## 3. execute：一条 PATH 到 Main

宿主按当前 [execute_test.py](../../migration-ledger/scripts/execute_test.py) 接口调用：

```text
python <execute_test.py> --root <run_root> --module M001 --assignment <id>
  --path-id PATH-M001-001 --adapter <harmony-test-adapter.json>
  --cwd <target_root> --output <新的绝对执行目录>
```

参数必须以 argv 数组传递，上述换行只是展示。host 自动组装完整 query，校验当前 assignment、代码基线，记录 command/query/report/log receipt。每条路径是独立进程；原内核全局注册表不会跨模块污染。原生相对 memory/媒体文件落入本次执行目录，不写源项目或共享包目录。

preconditions、steps、parameters、dependency_refs 与 ASSERT 传入 Planner。Verify 以单个 `[ASSERT:id]` 找回冻结描述，不能改写期望；固定 verification 不被替换，auto 按原策略选。正式入口固定 test，结果/环境记录 platform、task_type、device，Ledger 核对冻结平台。最终文本/回放成功数不能代替断言；Android 截图失败不生成黑图证据，媒体遵守受管路径。

## 4. 输出与三态

目录包含：`query.json / result.json / execution.log / receipt.json`，以及 `harmony/observations.json`、environment、原生 reports、memory、engine.log、所有媒体工件。每个观察记录 ASSERT ID、顺序、真实工具、布尔结果、原始理由和媒体 SHA256，每次立即落盘。

- Green：完整 ASSERT 集合、有真实媒体证据、匹配冻结验证类型、全部观察通过、无执行异常；host exit=0。
- Red：完成验证后观察到冻结谓词失败；保留实际失败和证据，根因归属仍由 Diagnostician 确认；host exit=1。
- Yellow：缺设备/依赖/模型、运行异常/超时、缺 ASSERT/媒体、验证解析歧义、模式不符、未知身份，或同 ASSERT 同轮 pass/fail 混合；host exit=2 或宿主异常码。

所有尝试保留；不能只取最后一次 Green。视频异常、无法加载图片等不被判产品 Red。原 parser 对“不通过”可能误识别为通过，迁移版要求明确结论，歧义触发 Yellow。

使用 [harmony_stage.py](../scripts/harmony_stage.py)：

```text
python <harmony_stage.py> --root <run_root> --module M001 --assignment <id>
  --receipt <PATH1/receipt.json> --receipt <PATH2/receipt.json> --output <run_root>/runs/harmony/sandbox/test-runner/<新请求>/stage-result.json
```

它只生成 runs/harmony/sandbox 工件，不自动提交或验收；要求所有冻结路径各有一个 receipt，自动连接旧结果 `retest_of`。超时/缺报告以 executed=false Yellow 保留 receipt/log。随后照现有流程 submit/accept，GLOBAL 最终测试可用 `--module GLOBAL`。Ledger 再核对 query/context/三态、assertions 和媒体摘要，不能把 adapter 的 Yellow 改报 Green。证据损坏会拒绝接受，需要重新取证或显式记录不可执行 Yellow，不能伪造新摘要。

## 5. 回放、memory 与 Auditor

`recording_ref` 是经 Ledger 传入的显式录制文件引用。必须校验 hash 和任务文本；知识变化也改变任务文本。接受前一代码基线的录制作为导航提示，但每次 verify 都用本轮实际媒体执行，并绑定本轮 code_baseline。原 XPath/坐标回放、失败重规划和弹窗处理全部保留。未指定录制时正常规划并产生新的候选录制。

原引擎保存的 memory 只是执行优化素材，不能直接成为全局“修复已验证”memory。候选是否可复用由 Ledger 对应验收决定；Auditor 跨模块失败、目标变更、flaky 历史都不因回放而消失。Auditor 仍委派 Fixer，一轮后负责模块 Testing、原发现模块 Testing、独立裁决；失败输出根因待人工。本引擎不绕过这些边界。

## 底层直接调用的留存路径约束

路径约束必须落在实际写入/清理函数中，不能只依靠 CLI 或技能说明。Harmony 原生写入器统一调用 AutoTest/storage.py：

| 产物 | 缺省处理 | 无运行上下文时 |
| --- | --- | --- |
| XMind 转换 Markdown | 当前 runner/design/<源文件名>.md | 必须显式传入本轮 sandbox/automation 下的绝对输出目录；禁止写回源文件旁 |
| HTML/JSON/Markdown 报告、截图布局 | runner/reports 或显式受管位置 | 缺省相对路径拒绝；显式位置仍检查三目录归属 |
| 录制记忆 | runner/memory | 可只读加载外部旧记忆；新录制必须受管 |
| 图片/视频/时间映射、结果 JSON、日志 | 当前 runner 或显式受管位置 | 不能退回 cwd、包目录或来源旁 |
| 截图、裁剪、拼接临时文件 | runner/temp；独立媒体处理可用显式受管输出旁的 temp | 无 runner 且无可判定的受管输出时拒绝，不使用系统 temp |
| SDK/设备报告 | 本轮 sdk 或已校验报告目录 | SDK 执行需进入 runner scope，禁止退回第三方默认 dumps/reports |
| shell/扩展 skill | runner cwd；子进程固定存储环境变量 | 缺 runner 拒绝，不能覆盖 TMPDIR/SDK/cache 等受管变量 |

显式输出不能跨当前 run、不能经符号链接或 .. 跳转；报告文件名生成后也重新检查。外部源码、原始用例、历史报告/视频保持只读；裁剪证据在本轮保存，自动清理不能删除外部输入。直接调用如果不进入 scope，受管 temp 残留仍在该 run；宿主确认 worker 结束后处理，不做系统目录清理。

Test-Runner 对非法路径返回的错误保留执行日志并按现有 Yellow/环境预检失败提交；不得为了继续执行而改用任意目录或取消无关模块。生成资产经既有 Ledger 提交/验收，存储校验本身不构成测试通过。

这些检查约束本包的写入器与子进程启动参数。任意 shell 命令、扩展 Python 或构建插件仍可自行使用绝对路径/修改 cwd；Host 必须按冻结命令与文件权限约束实际写入，不能把路径校验声明成 OS 沙箱。工具安装、开发验证夹具和设备端路径遵循此前列明的例外。

## 验证边界

离线模拟只证明接线、三态、报告/录制及 Ledger 门禁，不证明业务 App 真机通过。正式验收需已部署构建、冻结 PATH、真实模型和 Android/Harmony 设备；对照源版核查适用验证类型、回放、输入、临时控件、视频映射、逐 ASSERT 证据及误报/遗漏。

## 编译与自动化环境分离

Harmony 内核仅运行 automation PATH；build PATH 由 Test-Runner 经通用 execute_test 直接执行目标构建命令，harmony_stage 支持两种回执并按 test_scope 组装。Harmony 缺设备/模型/运行环境不能阻止已授权编译及其他任务；留原始诊断证据后按 [双环节协议](../../migration-protocol/references/build-automation.md) 提交 automation-unavailable，保持原自动化内核能力和逐 ASSERT 验证。

## 本轮共享环境准备

Test-Runner 首次设计转换或 automation 预检前执行 `sandbox.py prepare --root <run_root>`；参考/default 复制到 `runs/harmony/sandbox/environment/config.json` 和 `.env` 后使用，所有子模块共享这一份配置，各执行仍独立 attempt。显式 --config/--env-file 是首次复制来源；既有本轮配置不随来源更新。生成 adapter 绑定本轮配置及 root；凭证不入 Ledger。缺环境仍 Yellow/未执行且不影响独立任务。操作示例见 [sandbox README](../runtime/harmony/README.md#4-本轮共享配置与离线检查)。

## 异常完成与部分证据

Host execute_test 在当前 attempt 内保留原始 result.json、observations.json、execution.log 和 receipt.json；observations 优先取本 attempt 的 harmony/observations.json，兼容根部 observations.json，引用绑定到 receipt.partial_observations_ref。不改写原结果，也不重新采样来替换失败。

harmony_stage 与 Ledger 共用 test_completion.interpret：完整失败报告不因 Host 124/异常退出消失；不完整报告从已绑定的部分观测恢复有媒体证据的 ASSERT，整条路径保持 Yellow；截断/非法格式报告形成带解析原因的 Yellow。阶段结果包含 host_completion_version=1，验收根据原回执重新计算，核对身份、query、hash 和媒体；不能用解释结果绕过原冻结验收标准。正常 accept 关闭 Test-Runner assignment，后续继续 MO/Auditor 原分流；已有真实失败仍禁止作为纯环境缺测退出。
