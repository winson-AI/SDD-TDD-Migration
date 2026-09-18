# P1–P4 / P6 验证记录

本轮修改范围是 SDD-TDD-Migration 工作流包。参考上传的 android-to-kmp 机制，自行实现通用本地控制器；未执行上传包的迁移指令，也没有修改上传目录。

## 实际执行

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s SDD-TDD-Migration/skills/migration-ledger/tests -v
```

76 个 Ledger 测试通过（包含模块收尾门禁、finding 路由、依赖交错、人工恢复，以及既有 Harmony/host 集成回归）。测试全部在 TemporaryDirectory 中使用隔离 legacy/target/run 和可控的 Python 项目适配器；包括真实子进程执行、JSON 结果与日志采集、CLI status 调用。其证明范围是工作流控制及契约，不是某个真实业务模块迁移成功。

## 已覆盖

| 范围 | 实际验证 |
| --- | --- |
| 冻结 | 未冻结编码拒绝、代码未接受时测试拒绝、批准 hash 不符拒绝 |
| 理解门禁 | 源码未决项/目标可行性 unknown 拒绝进入可冻结计划 |
| 变更 | Fixer 越权改 SPEC 拒绝；边界内任务修订可重新冻结；改变验收不可沿用批准 |
| 结果 | 空/遗漏断言与路径、伪装 Green、flaky 标记、被篡改原始报告被拒绝 |
| 真实闭环 | 子进程输出 Red → 诊断 → Fixer → 新 test_run 正式复测 → 模块 Green |
| 部分验证 | source-only/未执行保留 Yellow，不能完成 |
| 复测 | 旧非 Green 必须有新的 test_run_id 和 retest_of；代码变化拒收旧结果 |
| 独立审计 | 实现者不能被分配 Auditor；模块测试和整体路径均独立执行，缺全局审计不全局 Green |
| 事件 | 同请求重复 ACK、同 ID 改内容拒绝、过期 revision 拒绝、两个并发请求只有一个 CAS 成功 |
| 恢复 | 事件落盘后投影崩溃可重放；伪改投影无效；不完整日志停止；证据在事件前保存快照 |
| 依赖 | 未完成生产者不放行；完成后仍需 Global 解除事件；消费者恢复原阶段且不自动 Green |
| 锁/身份 | 重叠路径拒绝并行；未知依赖拒绝；host 停止后 revoke，旧 worker 拒收 |
| 人工/会话 | 无决定不能恢复人工阻塞；原会话替换需要 checkpoint；恢复预算绑定明确决定且累计次数不清零 |

初轮测试暴露并修复了 macOS 路径规范化导致的追溯误拒绝，以及依赖版本变化错误覆盖消费者恢复阶段的问题。

## 包级核查

内部 Markdown 相对链接、JSON 模板/schema 可解析、Python 语法与 Skill frontmatter 另做结构检查；模板保留待实例化占位符，不把占位符当真实证据。

## 尚需宿主/项目集成验证

- 真实宿主的身份绑定、进程终止、每次文件写的权限/fencing、自动任务派发与原生 session 恢复。
- 真实项目全量 diff/删除/rename 与任务归属、复杂断言适配、跨运行 flaky 识别、设备/网络环境证据。
- OpenSpec CLI 实际调用及六件套正式文件物化、主分支合并/归档。
- 协议级独立 Yellow 预算、超时通知、根因 fingerprint 和全局审计预算扩展由宿主策略承担。
- KMP 资源、UI 树、设备截图、Harmony 构建等 P5 专项未接入，未做真实迁移测试。

本地运行入口、精确能力集与请求字段见 [local-runtime.md](skills/migration-protocol/references/local-runtime.md)。

## 2026-09-17 增量验证

再次阅读上传 Lean 的 NEXT/status_payload、blocked_from、require_state 和审计/恢复契约后，增加 8 个回归用例，验证：下一动作及原会话提示、查询不派发、嵌套挂起拒绝、旧任务撤销不能倒退新任务、审计不可覆盖及 ID 不复用/撤销不退还次数、挂起阶段拒收 worker 结果、根因变化重新计算停滞、失效证据不推荐派发、完成模块禁止直接挂起。部分用例同时检查多个相关不变量。

完整 34 个测试通过；仍只证明本地控制器行为，不代表真实 KMP 或宿主集成通过。上传 Skill 文件未修改、未执行。

## 控制流审查后的修复验证

本轮只修改本包，未读取或执行上传迁移包。完整 43 项通过；新增回归验证：

- DoD 暂停后恢复 testing；有效人工决定让游标就绪，旧 Green 不能直接完成。
- 阻塞中 invalidate 后可重规划、冻结、提交；旧批准边界不能绕过未决问题。
- 活动测试阻止诊断；诊断提交不改 phase，MO 接受才允许 Fixer；新测试使旧诊断失效。
- 已知 Yellow 按依赖/环境/人工分流，未知原因诊断；未登记依赖不自动解除。
- within-envelope 游标给出的冻结参数可以实际提交。
- 全局与模块审计失败产生责任项；阻止跳过路由/接受直接再审计；完整走通 MO 重开、修复、正式复测、独立审计，新报告必须关联旧失败。
- PATH ID 跨模块/全局唯一，避免审计问题归属歧义；待修复模块先完成已有重建，依赖未就绪时游标不放行。

兼容性：宿主诊断调用需从 diagnose → assign 更新为 diagnose → diagnosis-accept → assign；审计失败增加 audit-route / repair-accept 操作。没有执行真实宿主派发、OpenSpec CLI 或业务迁移。

## 本轮：全局覆盖、问题审计与 OpenSpec/memory

按用户最新策略补齐：测试设计继续提前；Red/Yellow 优先自动修复一轮；确认依赖/外围问题直接排队交 Auditor；修复生成可复用 memory。当前完整 55 项测试通过，新增 12 项覆盖：

- global-plan 缺需求/用例归属时拒绝、未验收禁止实现、新登记模块使旧覆盖验收失效。
- 一轮仍失败后交 Auditor；可修复代码不能跳过第一轮；已确认外围原因不消耗本地修复轮次。
- 问题审计无需全部模块完成；审计期间阻止业务写入；缺失非 Green 复测链拒收。
- 问题审计 Green 仍经 MO 恢复和 Main 复测/DoD；没有最终全局审计不能全局 Green。
- Auditor 委派修复、MO 验收权限和正式回归绑定；memory 失败不可复用，通过后 verified。
- pre-code 问题报告保持 Yellow，不能执行未生成代码或进入最终审计。
- OpenSpec 六件套自动生成、tasks 勾选、删除视图后重建，定义快照与 freeze 不被视图修改。
- 非法 delta、能力路径逃逸、缺失 tasks checkbox/ID 拒绝。
- 生产者变化保留消费者 waiting-auditor 队列；有可推进模块时避免反复问题审计消耗预算。

本轮包级检查：7 个 Python 文件语法有效、19 个 JSON 可解析、209 个包内 Markdown 链接存在；7 个相关 Skill 的 quick_validate 通过。

兼容性：新 init 必填 global_spec/new_architecture/requirement_ids，实现前 global-plan，Fixer 结果必填 fix_note_ref，定义需合法 OpenSpec delta 与任务 ID。没有自动迁移旧 run。问题/最终审计各有预算，不因撤销返还。

OpenSpec manifest 明确 structural-only；本轮没有执行 OpenSpec CLI、真实宿主派发或真实业务工程迁移。所有测试仍在隔离临时目录执行。

## 本轮：Auditor 跨模块修复后验证

默认收尾改为 audit-collect → audit-plan → audit-route-batch → audit-work → Fixer → 负责模块 Testing/DoD → audit-retest 原发现模块 → audit-verdict。失败停止并输出根因待人工，旧 problem-* 仅保留兼容。

完整 60 项测试通过。新增 5 项使用真实 Python 子进程读取两个模块文件验证：

- M002 暴露依赖问题，实际根因在已 Green 的 M001；未显式入队仍被扫描收集；双方 SPEC/测试上下文绑定后，修复 M001，再测试 M001 和 M002，通过后才使 memory 可复用。
- 修复后 M001 通过但 M002 仍失败：批次 awaiting-human，报告保留根因 owner、结果和上下文；禁止自动重试、普通 resume 或无批准新批次。
- 路由上下文不匹配/未经路由审核不能开始修复。
- 负责模块测试失败即停止，原发现模块不得继续测试。
- 原发现模块代码基线被外部修改时，记录验证阻塞根因并等待人工。

包级校验：9 个 Python 文件语法有效、20 个 JSON 可解析、213 个包内链接存在，相关 3 个 Skill 校验通过。修改范围仅本工作流包；未运行真实业务工程、设备或宿主派发。

失败报告投影：`<run_root>/audit-reports/<batch-id>.json` 和 `.md`。全局修复 memory 在跨模块验证完成前不可复用；失败后人工批准只允许建立新批次，不重置总预算、不把测试改 Green。


## HarmonyAgenticTesting 能力迁移（2026-09-17）

范围：只在本包新增测试内核、输入/输出适配与测试，修改 host 执行器/证据验收接点。源目录只读；源配置凭证、历史报告、用户录制未复制。91 个源文件有逐文件源摘要与迁移后摘要，3 个局部修订明确记录：验证解析/视频证据清理、XMind 全 sheet、special_test 配置传递。

本轮共 **208 项测试通过**：

- **65 项 Ledger 测试**：包含全部原 60 项；新增真实 host 子进程 → Harmony 格式 report → tests stage → submit/accept/DoD、禁止 Yellow 改 Green、媒体修改拒收、超时终止子进程组、缺执行器产生 Yellow。
- **15 项测试模块测试**：完整 query/交错断言、冻结描述替换、五类验证观察、缺媒体/异常/未知 ID、负面文本解析、flaky 留痕、设备锁、MD 草稿保留原文、缺设备结构化 Yellow；3 项使用原生依赖检查实际 decision/报告/录制接线、视频异常清理与 XMind 多 sheet。
- **128 项源项目原测试**：保留的 tool_recorder/tool_player pytest 全通过，覆盖 XPath/坐标/输入/回放/重规划等原有逻辑。

可复现入口（PYTHON 为已安装相应依赖的解释器）：

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s SDD-TDD-Migration/skills/migration-ledger/tests -q
PYTHONDONTWRITEBYTECODE=1 <PYTHON> -m unittest discover -s SDD-TDD-Migration/skills/migration-test/tests -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=<absolute-runtime-harmony> <PYTHON> -m pytest -q -p no:cacheprovider <absolute-runtime-harmony>/tests
```

本机 Ledger 使用 Python 3.9.6；原生兼容/源回归使用源项目已有只读虚拟环境 Python 3.14.7，测试时载入本机已安装 pytest，不安装/升级环境。未把该机器路径写入运行模板。

结构检查：97 个 Python 文件 AST 有效，24 个 JSON 可解析，238 个非 vendored 文档内链有效（本段和 README 新增链接指向已存在入口），91 个迁移文件与清单摘要一致；migration-test 的 quick_validate 通过。

边界：原生接线测试替换了模型与设备 I/O，host 集成用可控 Python 文件做观测；原测试也大量使用 mock。没有连接真机、调用真实模型、安装 App 或执行真实业务用例。故当前证明源码能力保留及本地契约兼容，不能将 208 项通过解释为真实 UI 测试效果无劣化。最终需用户指定设备、构建和代表用例，进行源版/迁移版同条件对照。

执行使用说明与完整能力映射见 [Harmony 运行协议](skills/migration-test/references/harmony-runtime.md)。


## 所有模块本轮结束后的 Auditor 收尾（2026-09-17）

按最新确认调整：Global 等所有模块本轮 completed 或明确挂起，且无活动 worker/可推进动作后才统一启动 Auditor；实际 subagent 与 Used Skills 由宿主运行。

本轮运行 Ledger 完整测试集，**76 项通过**。新增 11 项：

- 正常 dependency-ready、resume 与未结束的独立模块阻止提前 audit-collect；明确 suspend 后计入本轮收尾。
- 依赖图调度探针验证 A 修复/测试 → B 复测 → C 修复，且原 Green 中间模块需要新证据。
- 同发现模块的两个 finding 可分别路由给不同 owner；单 finding 可有多个 owner；归属引入依赖环时拒绝路由。
- 人工分支不会阻断独立修复；包括通过真实 Ledger 操作与 Python 子进程完成另一模块修复/两侧测试/部分审计报告的回归。
- 失败报告批准后 audit-release 能解锁重新规划；失败结果保持原样。上下文/blocker 未处理时禁止立刻重新收集。
- 释放后批准 recover 可追加预算，保留累计使用量。

早期“无在途 worker 即可审计”行为已经替换；历史章节描述旧验证，不作为当前调度规则。旧 problem-assign 兼容入口也采用本轮收尾门禁。修复批次 schema_version=2，按 finding_id 保存来源、责任和依赖验证；人工决定只释放批次，不隐式批准新 SPEC 或把测试改绿。

结构校验：98 个 Python 文件 AST 有效，24 个 JSON 可解析，243 个非 vendored 文档内链存在；migration-audit/global/module/ledger 四个 Skill 校验通过。

边界：本次未执行真实宿主 Agent 派发、模型调用或真机业务测试；Harmony 内核未修改，未重复运行其独立原生回归。依赖调度的部分组合使用纯状态机测试，独立分支修复和人工恢复另有真实 Ledger 事务/本地子进程回归。

## 功能切片与分阶段验收（2026-09-17）

新增可选 module_slicing 高层输入及人工模块方案模板，明确完整功能 use case 可按一级/二级功能目录初分，再分析 scope、测试列表和模块 SPEC。输入解释与业务边界识别由宿主/Global 执行；没有新增自动目录扫描器。

明确 case_owners 为覆盖范围；模块验收由对应 MO 唯一提交，审计验收由对应 Auditor 唯一提交，完整 Green 且原门禁满足后无需额外会签。新增 global-plan.boundary_review 声明，涉及边界问题时校验真实人工批准，绑定完整 plan 和 registry；消费批准并保留证据引用。

本轮 Ledger 完整测试集 **81 项通过**，新增 5 项覆盖：审核字段缺失/无问题自主接受；缺批准/错误作用域/重复使用批准；方案或注册表变化后的批准失效；未知模块/重复问题；Green 模块的 MO 验收权限、无额外人工批准及审计权限隔离。其余既有审计、恢复与证据回归全部通过。

结构检查：21 个 JSON 模板可解析，3 个变更 Python 文件 AST 有效，69 个相关文档内链可定位，migration-global/module/audit/protocol 四个技能通过 quick_validate。

兼容性：新 global-plan 请求必须包含 boundary_review；旧已接受事件不回写。重新规划时需补充实际边界审核。边界声明的语义真实性、真实宿主模块导入与 Agent 切片效果仍需真实运行验证；本轮未运行模型或真机测试，未修改 Harmony 内核。

## 单模块完整运行入口（2026-09-17）

新增 entry_mode=project/single-module，默认项目级切片；single-module-input 模板直接指定独立模块，复用高层 SPEC/Testing list 字段。宿主将选定模块映射到 Ledger init 的 single_module_id，Global 保留注册、覆盖验收、MO 派发与审计收尾职责。Ledger 拒绝模式错误、缺少选定 ID、追加模块、非空内部依赖及未覆盖全部输入 CASE。

本轮 Ledger 完整测试集 **86 项通过**，新增 5 项：默认项目模式可注册多模块；模式/选定 ID 校验；单模块范围与完整用例约束；单模块通过真实 Ledger 事务和子进程证据完成 MO→独立 Auditor 的 Green 流程；单模块 Red/Yellow 遗留进入统一 audit-collect。

结构检查：22 个 JSON 模板、2 个变更 Python 文件 AST、102 个相关文档内链有效；migration-global quick_validate 通过。旧运行未记录 entry_mode 时仍按 project 解释；无就地模式切换。高层配置解析、真实 Agent 派发与语义独立性审查仍由宿主负责，本次未运行真实宿主 Agent 或真机业务测试。

## 单模块用户输入修正（2026-09-17）

修正上节入口描述：用户仅需指定已划分的独立功能模块、描述与代码上下文，现成 SPEC/Testing list 可选。Global 必须主动识别生成模块级 SPEC 草案、Testing list 和运行级审计路径，再启动 MO 正式规格/测试设计及执行，最后进入 Auditor。默认 project 项目切片保持不变。

single-module-input 增加 description/context_refs；global_spec=null、需求/测试/审计路径空列表表示高层待分析输入，不是可执行的低层请求。宿主先执行 Global 初始化分析并保存 staged 工件，整理为完整非空输入后才提交严格 Ledger init；正式派发与交接仍经 Ledger。输入整理后的 input_ref 可通过现有 init 引用归档保留。本次只修正文档、技能和模板，没有新增模型生成脚本或放宽 Ledger 守卫。

验证：现有 Ledger 全部 **86 项通过**；22 个 JSON 模板可解析，项目/单模块模板默认值已检查，102 个相关文档内链有效，migration-global quick_validate 通过。未实际运行宿主 Agent 的需求生成、真实迁移或设备测试。

## 单模块作为同一入口参数（2026-09-17）

以本节取代此前要求用户提供单模块 description/scope/路径的入口说明。高层仅增加 entry_mode=single-module 与 module_name，沿用项目上下文；single-module-input.json 缩为两个参数示例，global-input 保留 project 默认并提供可选 module_name。Global 定位功能并生成稳定 ID、scope、读写路径、SPEC/Testing list，宿主再映射为原有严格 Ledger init/register，后续 MO 与 Auditor 流程保持完整。

命令定义新增 --mode/--module-name 参数，由宿主解析。没有新增或注册实际 CLI，也未改变 Ledger 低层 single_module_id 契约。无歧义的模块输入不再要求用户额外提供模块资料；未知业务边界仍提具体人工决策。

验证：22 个 JSON 模板可解析，单模块参数恰为两字段、项目默认值校验通过，94 个相关文档内链有效，migration-global quick_validate 通过。运行时代码未修改，本轮未重跑此前 86 项回归或实际启动 Agent。

## 项目上下文持久化闭环（2026-09-17）

新增 project_context.py：宿主 init/update/show/history/prepare。默认工作目录 .sdd-migration 保存当前配置、内容寻址的历史链与用户输入来源副本；patch 递归合并，明确 null 删除，数组替换，锁/CAS/幂等保护更新。允许先保存部分共享输入，prepare 前要求可用根目录与架构。

prepare 固化本次项目版本、临时覆盖、模式/模块名及引用文档。快照与原项目配置/文档独立，同一请求重试仍读取原版本，新请求不能覆盖旧 run。Ledger init 校验 run/root、代码根目录、模式/名称、架构与预算，保存 project_context_ref/project_id/project_revision；后续操作和状态读取验证证据。旧无快照运行继续兼容，新宿主入口必须固化。运行状态和跨角色交接仍只走 Ledger。

本轮完整 Ledger 回归 **99 项通过**（原 86 项 + 新增 13 项）。新测试覆盖初始化、嵌套增量更新/删除/历史、来源副本、幂等/过期更新、并发单赢家、部分配置保存/运行阻塞、身份与字段限制、临时覆盖、单模块选择不污染默认、更新后旧运行稳定/新运行采用新值、脱离原配置目录仍可运行、Ledger 绑定与拒绝错配、手改/损坏拒绝、CLI show/prepare、JSON 来源的独立保存。

结构校验：25 个 JSON 模板、3 个变更 Python 文件 AST、150 个相关文档内链有效；migration-global/ledger/protocol 三个技能校验通过。

本轮使用临时目录和本地进程验证真实配置读写/归档/Ledger 绑定。未为用户实际项目创建配置，未启动真实迁移 Agent 或设备测试。自然语言字段提取、生成业务 SPEC/Testing list 和宿主命令注册仍由宿主执行；配置脚本不提供额外身份认证、整个源码树/设备快照或活动 run 上下文就地替换。需要采用新配置的迁移使用新 run 并重新满足已有门禁。
