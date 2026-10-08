# SDD-TDD-Migration

按功能切片迁移的 Agent 工作流包：9 个执行/治理角色 + 1 个 Ledger。输入整体规范、新架构、存量代码路径、目标代码路径及整体测试用例，先拆分模块和用例，再并行迁移，最后独立审计。

## 从这里开始

可选旁路 [Watchdog](skills/migration-protocol/references/watchdog.md) 提供 `check/watch` 状态监听与通知、`ack` 交付确认；未确认通知可重放，Host 按 notice_id 去重展示。支持真实本机进程检查及宿主 API 状态导出；未接入时显示 unknown。不会自动启动、派发 Agent、提交恢复操作或影响迁移门禁。

1. 读取 [AGENTS.md](AGENTS.md)，按角色索引渐进加载。
2. 首次提供项目资料，宿主根据 [project-context.json](template/project-context.json) 保存到固定 `<workspace_root>/.sdd-migration/project-context.json`（首次未指定 workspace_root 时取配置目录父级）；后续按该目录读取，用户明确更新时增量保存。无需每次重填运行输入。
3. 在支持此包的宿主中执行 `/sdd-init`，先固定项目配置和本次请求快照，再由 Global 生成 [运行输入](template/global-input.json)、宿主业务契约、需求/用例输入、账本和模块规划；`/sdd-plan <run-id> <module-id>` 组织叶子 TASK、六件套与上游用例路径，由 MO 审核冻结；真实未决或需求/验收/授权变化才交人工。旧 input.json 也可导入。
4. `/sdd-run <run-id>` 调度已冻结且依赖就绪的模块，单模块也可用 `/sdd-module <run-id> <module-id>`。模块内自动推进到完成、挂起或预算耗尽。
5. 用 `/sdd-status <run-id>` 冷读状态；用 `/sdd-resume <run-id> [module-id] [decision.json绝对路径]` 恢复；用 `/sdd-audit <run-id>` 执行独立遗留复核与收尾审阅。
6. 全局审计通过后，`/sdd-archive <run-id> <decision.json绝对路径>` 验证人类交付授权并同步、归档 OpenSpec。授权必须绑定具体交付内容摘要。

这些 slash command 是待宿主加载的命令定义，未安装到用户配置；本包已提供本地 Ledger 控制器、阶段校验和测试调用适配器；没有常驻 Agent 调度服务或内置业务测试。本地控制器实现事件提交、单写者和模块资源占用检查；宿主仍须提供身份认证、写权限隔离、Agent 派发与项目真实测试适配器。具体能力见 [本地运行指南](skills/migration-protocol/references/local-runtime.md)。仅加载 Markdown 不会产生操作系统级权限隔离。没有这些能力时应显式阻塞，不能宣称端到端迁移已执行。

要在其他仓库真实跑起来，按 [宿主接入契约](skills/migration-protocol/references/host-integration.md) 接入真实角色派发与执行回执。推进按 global/module 范围运行 `/sdd-verify`，巡检用 projection、交付用 final；核验只证明记录和投影一致，无关模块视图错误不阻塞当前 MO，也不能由核验通过推断实际执行或功能全绿。UI 分析、资源转换与受限视觉取证按 [领域工具受限接入](skills/migration-protocol/references/domain-tools.md) 使用，保持既有角色、Ledger 和修复预算。

## 流程图

主线：GO/父 MO 划分 scope/全量 CASE → 子 MO 拆 TASK → SPEC/路径审核冻结 → Implementer → build/unit/static → automation → 反馈分流与复测 → 统一 Auditor。SDD 先规划后执行、边执行边调整，完整可执行即开工；独立 design 按需。实现错误交 Fixer，规划/功能/依赖契约缺口走 CR 更新 SPEC 和已有代码，超 scope 上溯父 MO/GO。同 Run 保留历史和预算；有 TASK 独立性证明才保留未影响验收与成功路径，否则全模块重验。build/unit/static 始终验证新代码。见[变更控制](skills/migration-protocol/references/openspec.md#变更控制)。

按三层编排阅读 [完整图集](diagrams/README.md)：[总览](diagrams/workflow.svg) → [子 MO 执行与修复](diagrams/module-execution.svg) → [Auditor 跨模块处理](diagrams/auditor-closure.svg)，另见贯穿各阶段的 [二方库语义与复用](diagrams/reuse-dependencies.svg)。SVG 入库，PNG 由源文件在本地再生成。自动化详见 [外层执行闭环](diagrams/automation-flow.svg) 与 [Android/Harmony 单 PATH 内核](diagrams/automation-engine.svg)。

## 目录

| 目录 | 用途 |
| --- | --- |
| `Agents/` | 10 个角色定义，含输入输出、边界与自查 |
| `skills/` | 共享协议与 10 个职责技能，按需读取 |
| `command/` | 10 个命令入口，负责上下文配置、参数、门控、派发与投影完整性核验 |
| `template/` | 全局输入、模块输入、六件套及诊断、测试、Ledger 请求、人工决策等运行工件模板 |
| `diagrams/` | 三层编排、子 MO/Auditor、复用与自动化图及生成源文件 |

运行期资产集中在固定 `workspace_root`，其下 `.sdd-migration`（长期配置）、`.sdd-runs/<run_id>`（运行证据）、`openspec`（规格与状态中枢）顶层并列；包目录自身不存迁移状态。Harmony 执行统一在 `.sdd-runs/<run_id>/runs/harmony/`（automation/sandbox），构建资产在 runs/build；临时文件归 runner，结束清理，失败留存原因。项目模型参考配置/凭证在 `.sdd-migration/harmony/`；Test-Runner 首次准备时复制到本轮 `runs/harmony/sandbox/environment/`，各模块共享本轮副本。入口为 `openspec/runs/<run_id>/workflow.md`。见 [完整留存布局与二次启动](skills/migration-protocol/references/storage-layout.md)。模块 ID 永久稳定，如 `M001`；OpenSpec change 名如 `migration-demo-m001`。新增模块只追加编号，不因排序改变历史 ID。顶层 `openspec` 是 prepare→init→apply 真实跑通后的投影，不能手写；最终交付用只读门禁 `verify_openspec.py --root <run> --scope final` 核验投影与正式收尾报告；缺事件证据时恢复其有效来源，不由核验结果推断真实派发或功能通过，细则见 [投影完整性收尾门禁](skills/migration-protocol/references/storage-layout.md#openspec-投影完整性收尾门禁)。

## 对现有 guidance 的适配

依据 [flow_spec.md](../flow_spec.md)、[dingpan 分析](../dingpan_harness_architecture_analysis.md) 与 [原 Agent 模板](../template/agent_template_guide.md)、[Skill 模板](../template/skills_template_guide.md)、[Command 模板](../template/command_template_guide.md)。本次用户明确要求优先，覆盖关系如下：

| 现有机制 | 本包机制及理由 |
| --- | --- |
| Command/Agent 分别写 `plan.md` | Ledger 唯一写事件与状态投影，杜绝并发双写；命令只提交请求 |
| 所有 Agent 不能调用其他 Agent | 叶子角色单步退出；编排角色提出派发事件，由宿主执行；Auditor 可经 Ledger 委派修复 |
| 每一步均人工确认 | 清晰规划由 MO 审核冻结；真实未决、需求/验收/授权变化与主分支合并保留人工门禁 |
| 文件存在即可修正阶段为完成 | 校验文件、摘要、当前基线及已接受事件；文件存在不能证明通过 |
| 删除已存在文件再运行 | 使用不可变历史工件和事件恢复；不删除用户成果、不静默覆盖 |
| 运行失败测试后再实现 | 本次硬红线要求代码先生成才运行测试；测试设计和脚本准备前移，缺陷闭环保留真实 red→green 证据 |

因此本包是规格与测试设计前置的迁移流程，不声称每个成功路径都做过严格 test-first RED；首次即 Green 时记录 `red_evidence: not-observed`，不伪造失败。`plan` 指文档澄清阶段，不假定宿主能自动切换某产品的 Plan Mode。

## 验证范围

本包可检查入口引用、frontmatter、JSON 模板与流程契约；真实迁移须在填写技术栈、宿主适配和真实测试命令后验证。推荐的行为验收场景见 [workflow-verification.md](template/workflow-verification.md)。协议总量与单文件大小受 `reading.py` 的 PROTOCOL_BUDGET/FILE_BUDGET 棘轮约束，阅读卡另有 60KB 预算：新增规则写入其专题协议并合并重复表述，不在运行指南中再追加一份。

## 规划、执行与反馈控制

GO/父 MO 负责模块与子模块的 scope 切片，并在冻结前分配上游全量 CASE；原子能力可直接作为叶子。子 MO 在叶子范围内拆 TASK、组织四维分析，Spec-Designer 编制 proposal/spec/design/tasks 与 CASE/PATH/ASSERT；MO 决策经 Ledger 投影为 status，包内 checklist 由 Ledger 绑定并投影，组成 OpenSpec 六件套。SPEC 是 Implementer 的执行规范，四维分析描述业务、功能与代码边界，两者承担不同职责。规划完整可执行即可由 MO 审核冻结，不增加预演全部缺陷的规划轮次；Test-Runner 的独立 design 仅按需协助。

```text
GO / 父 MO：scope + CASE → 子 MO：TASK + 四维 → SPEC / PATH 审核冻结
  → Implementer → MO 接受代码
  → Test-Runner：build → unit → static（同一派发）
  → automation：逐 PATH / ASSERT → visual（适用时）
  ├─ 全部必需路径有效 Green → MO 验收 DoD → 模块收尾
  └─ 非 Green → 现有诊断 / MO 归因分流 → 更新后正式复测
全部模块本轮收尾、父汇总有效、无 worker / 可推进动作 → 统一宿主 Auditor
```

**SDD 先规划后执行、边执行边调整；TDD 从上游全量用例建立冻结前覆盖，在 automation 中收集实现错误和不符合预期的证据，再调整 TASK 实现。** 未生成代码不执行目标测试，首次即 Green 如实记录，不伪造 test-first RED。

| 执行反馈 | 控制分支 | 后续动作 |
| --- | --- | --- |
| 实现违反当前 SPEC | `fixer` | MO 在累计预算内派发 Fixer；最小补丁、自验证、MO 接受后正式复测 |
| 当前 scope 内规划遗漏、功能/依赖契约缺口、fidelity 规划不足 | `spec` → CR（`change`） | Spec-Designer 修订 SPEC，MO 审核再冻结，Implementer 更新已经 coding 的代码 |
| 原分配范围不足 | `upstream` → `realloc-request` | 上溯负责的父 MO/GO，修正分配后 top-down 更新受影响规划，再冻结执行 |
| 已有提供方暂不可用或环境/外围阻塞 | 既有等待/恢复分支 | 留存根因和证据；自动化环境缺测保持 Yellow/未执行，条件恢复后真实验证 |

分类在派发修复前完成；不把所有问题先交 Fixer 再判断。Fixer 不修改需求、验收或冻结 TASK，只能提出 CR。原预期内的技术补全由 MO 审核；真实未决或需求、验收、授权变化交 Human。源码实现错误造成的 fidelity 偏差仍走 Fixer，规划遗漏造成的偏差才走 CR。

修订默认全模块重验。MO 可在 CR 的 plan-review 提交 [TASK 独立性证明](template/task-independence.json)：核对定义、写范围、读依赖、共享 PATH、未变需求及文件追溯后，只重开受影响 TASK，保留未影响 TASK 和有效成功证据。无证明或共享影响则全模块重验；过期或漏报变更的证明拒收。**新代码始终重跑 build/unit/static**，automation/visual 重跑受影响及非 Green 路径；原回执、test_run_id 和执行基线保留，另记 `validation_reuse`，不能标为本次新执行。详见 [TASK 局部重验](skills/migration-protocol/references/openspec.md#task-局部重验)。

Ledger 按宿主任务、模块和 TASK 汇总 automation 的应测、已尝试、完整执行、有效成功、Red/Yellow 和缺路径 CASE；参数/平台实例分别计 PATH，重试不增加分母。`reused_passed_paths` 单列，排除在 `current_executed_paths` 之外；成功集合附原始执行身份与证据。缺路径、缺测或失效证据不能据现有成功集合宣称全量通过。

同一宿主迁移任务始终沿用一个 Run，保留失败、规划 history 和累计预算；执行仅绑定当前冻结 SPEC。只有新宿主任务新建 Run，抽象且已验证的经验可跨 Run 复用。各 MO 独立推进；某个失败只影响自身及有证据的依赖范围。统一 Auditor 审阅全部模块与宿主目标、治理代码并独立裁决；实际复测覆盖遗留和受影响路径，空清单只做独立审阅。TASK 局部证明不削弱 Auditor 的权限，Fixer 自测也不能代替正式测试或独立审计。

## 专题速览

各专题的权威规则只在对应协议中陈述一次（`AGENTS.md` 的专题索引列出触发条件），这里只给方向：

| 专题 | 一句话 | 协议 |
| --- | --- | --- |
| 二方库与已有能力 | 复用必须逐行为对齐存量功能；能力目录显式 provider owner | [复用](skills/migration-protocol/references/reuse-dependencies.md)、[来源变更](skills/migration-protocol/references/source-changes.md) |
| OpenSpec 边界 | 标准基线/增量结构；status/checklist/Ledger 是本包扩展，Ledger 投影不可手改 | [OpenSpec](skills/migration-protocol/references/openspec.md) |
| 本地控制器与游标 | 单写事件事务、`status` 游标与阅读卡、恢复与显式追加预算 | [本地运行](skills/migration-protocol/references/local-runtime.md)、[宿主接入](skills/migration-protocol/references/host-integration.md) |
| 并行 MO 与统一收尾 | 各 MO 独立推进；全量收尾后统一审计 | [状态机](skills/migration-protocol/references/state-machine.md#模块隔离与全量收尾) |
| Auditor | 先整体代码治理，再复核遗留；修复后验证，失败待人工 | [审计范围](skills/migration-protocol/references/audit-scope.md)、[代码治理](skills/migration-protocol/references/audit-code-review.md) |
| Android/Harmony 自动测试 | MobileAgenticOperator test 模式，逐 PATH/ASSERT 证据接入 Ledger | [移动端运行](skills/migration-test/references/harmony-runtime.md) |
| 切片与功能清单 | 默认由 Agent 决定粒度；清单完整可追溯，疑问交人工；一条 CASE 一个验收切片，成链须写理由；往次切分经验生成技能，供后续 Run 的 GO/MO 加载 | [切片规约](skills/migration-global/references/slicing.md) |
| 项目上下文 | 首次保存，增量更新，每次运行 prepare 固化快照 | [项目上下文](skills/migration-protocol/references/project-context.md) |
| 上下文就绪 | 规划与审计者随操作登记预检；worker 派发后预检，ready 才开工；worker 只读执行所需 | [上下文就绪](skills/migration-protocol/references/context-readiness.md) |
| 构建、单测、静态审查、自动化、视觉 | build → unit → static → automation → visual；自动化缺失仅 Yellow | [构建与自动化](skills/migration-protocol/references/build-automation.md)、[UI 保真](skills/migration-protocol/references/ui-fidelity.md) |
| 资源与参数搬运 | 文件资源按清单原样复制、按 accessor 引用；布局、图层与代码里的取值记成参数表，生成到目标后按键取用；Spec 只写例外，验收比对字节与引用；登记 UI/Resource 分配前对约定定论（声明，或写明目标不接收的原因） | [搬运](skills/migration-protocol/references/resource-transfer.md#总则) |
| 图片与图标对齐 | 图片来源逐条记录并入资源闭包；树上每处静态图片都上屏核对或带证据豁免：存量资源离线渲染为参考，目标屏幕节点与之比较（另有文本与节点检查），结论由 Ledger 重算；手工替换的图片须测量或获批偏差 | [图片与图标对齐](skills/migration-protocol/references/ui-fidelity.md#图片与图标对齐) |
| 四维切片与语义模型 | UI → Logic → Adhesive → Resource 逐层映射到 TASK/PATH/ASSERT | [四维](skills/migration-protocol/references/dimension-slicing.md)、[语义抽取](skills/migration-protocol/references/semantic-extraction.md) |
| 阻塞感知与恢复 | 局部校验、invalidate 出口、进度信号；watchdog 只观察 | [恢复与进度](skills/migration-protocol/references/progress-recovery.md)、[watchdog](skills/migration-protocol/references/watchdog.md) |
| 埋点 | 有则迁移，无则有据 N/A 正常推进 | [埋点](skills/migration-protocol/references/telemetry.md) |
| 留存与资产根 | `.sdd-migration`、`.sdd-runs`、`openspec` 并列 | [留存文件系统](skills/migration-protocol/references/storage-layout.md) |

## 单个功能模块入口

默认 [global-input.json](template/global-input.json) 的 `entry_mode=project` 覆盖完整项目；`single-module` 选择一个根功能。两种模式均由 GO/MO 按原子性决定是否继续拆 scope，原子根直接进入叶子规划。

单模块只是同一入口的两个参数：`entry_mode=single-module` 与 `module_name`（如“用户登录”）。沿用当前项目输入，用户无需提供模块描述、scope、模块代码路径、SPEC 或 Testing list；由 GO 识别业务范围并分配上游 CASE，MO 按需细分，叶子组织实施规范和测试路径。[single-module-input.json](template/single-module-input.json) 仅展示这两个参数，不是独立运行资料包。

完整流程：选择项目或根功能 → **GO/父 MO 划 scope/CASE 并审查 registry 覆盖** → **子 MO 拆 tasks、四维、形成可执行 SPEC 和测试路径** → **MO 审核冻结** → **Implementer、Test-Runner build/automation、Fixer/复测** → **父节点汇总，统一宿主 Auditor**。独立 design 按需协助；执行中发现遗漏/fidelity 偏差，在同 Run 更新受影响 SPEC 和已有代码，只越 scope 才上溯。历史只留痕，每叶子执行唯一当前 SPEC。父子 MO 都读全局代码、架构、知识与分工，见[父子 MO 协议](skills/migration-protocol/references/module-decomposition.md)。

宿主接入命令后，可按以下阶段执行（路径和 run-id 为示例，冻结须绑定当前规划审核及适用的人工决定）：

```text
/sdd-init --mode single-module --module-name "用户登录"
/sdd-plan <初始化返回的run-id> <Global生成的module-id>
/sdd-run <初始化返回的run-id>
/sdd-status <初始化返回的run-id>
/sdd-audit <初始化返回的run-id>
```

首轮 Green 仍需最终独立审计，Red/Yellow 在累计预算内局部收敛后统一审计。`/sdd-module` 是推进已注册模块的命令；新单模块运行从 `/sdd-init` 开始。字段、独立性与范围限制见 [切片规约](skills/migration-global/references/slicing.md#项目级与单模块入口)。

## 版本记录

协议、模板、脚本与测试只描述当前版本；不同版本之间的差异只在此处记录。宿主新迁移任务才 prepare 新 Run；同任务调整走 Ledger 事件事务。规划过程只保留 history，不形成可选的流程或计划版本。工件只在被接受时按内容规则判定，之后只因自身或所引文件漂移被拒；后增规则约束新提交，已接受工件与当前规则的差异列入报告的规则欠账，交统一 Auditor 评估。

| 日期 | 主要变化 |
| --- | --- |
| 2026-10-09 | 按步取用再收紧。预检：coding 的预检只核对输入，由 Ledger 在派发时逐项核对必读输入并以 Implementer 名义登记、绑定派发，Implementer 直接开工；输入不符时不代写，仍由其自报，自报的报告取代代写的那份；需要执行者陈述命令、环境或开工意愿的 building/testing/fixing 照旧自报。Test-Runner：构建与自动化仍是先后两次派发、各自验收，两阶段共读一份角色文本，会话按小节保留读过的每个版本，后一阶段只追加本阶段小节，复测只带红线。卡片与模板：分析已登记的叶子，计划步不再带分析与语义模型模板，四份文档由骨架起稿、修订时才带文档模板，影响说明只随变更请求；执行角色仅在冻结计划从 provider 取用时带复用小节；等待依赖的步骤不带卡。必读输入：规划与拆分不把存量/目标源码树内的文件列为必读，按条目定位符打开，这些文件漂移仍使报告过期。 |
| 2026-10-08 | 回放在途 run 后的修正与补齐。报告：人工决定的用途改由日志读出（旧决定不再显示为未使用，批量信封显示它承载的冻结），等待依赖或自动化不再记为阻塞教训，规划体量把为计划撰写的文件与只被引用的来源分列，切分技能随宿主取到的卡片一并写出。在途可见：规则欠账列出未定论的搬运约定、设备环境和缺设备路径的已持有计划，任何 run 的报告都把仅有进程内路径的用户可见 CASE 列为保真限制。设备环境定论：prepared run 登记 UI 分配前须对 `test_adapter.device` 定论（平台，或没有设备的原因）；声明没有设备时，未达设备路径的用户可见 CASE 由 Ledger 按该原因记缺口。run 内定论的搬运约定与设备环境随采集进入经验库，项目配置未声明时下一 Run 取用。纵向切片：拆分按各切片四维分析判定某 CASE 的界面与逻辑是否分属两个切片，分属时与成链、过半等待一样须写明不能按行为切的理由；报告与切分技能记录分层用例、单层切片与最多改交次数。收尾复盘：结束的 run 在有未抽象观察或切分信号时由全局游标给出 retrospective_due。骨架：`spec_skeleton.py` 按叶子四维分析生成 proposal/spec/design/tasks 骨架，留有待写标记的计划被拒。 |
| 2026-10-08 | 设备缺口落到质量上：声明了缺口的叶子可以完成，它跑过的路径（含 build）各自保持 Green，该 CASE 的 automation 记 Yellow，模块与本轮质量为 Yellow；其余全部 Green 且审计通过后以 completed-with-unverified-tests 收尾，不征求 Green 交付授权。叶子最小集：叶子有已登记的四维分析时，计划只写六件套、tasks（范围/路径/需求）、测试计划引用与 dimension_trace，四维分析引用、source_closure、target_feasibility、decision_envelope、各任务四维与 scenario_trace 由 Ledger 据已接受的分析与行为审阅补全后存储冻结；作者写了的保留并照常判定，计划模板随之缩为最小集。切分技能：每次经验采集在经验库重生成 `skills/migration-slicing-experience/SKILL.md`（多个 run 印证的抽象教训在前，附往次切分形态与未抽象的观察，内容变才升版），下一 Run 的 prepare 将其固化，GO/MO 在登记、全局规划、拆分与接受、上溯和上游修订步骤经游标 slicing_skill 加载，其余阶段不读。 |
| 2026-10-08 | 用户可见 CASE 在用户看得到的地方验证：prepared run 中叶子所验收、由适用 UI item 承载的每条 CASE 须有设备或视觉 PATH（visual，或绑定设备平台、交互的 automation），确无可能的在 plan.device_gaps 写明原因与证据，报告列为 Yellow 缺口且不计完整验证；automation 统计按宿主任务/模块/TASK 分列设备、进程内与视觉路径。运行记忆：阻塞及其解除依据、一次冻结三次以上改交计划、同一操作同因被拒三次以上进入经验；项目可用 `experience_root` 指定多工作区共享的经验库。人工与成本可见：游标每一步给出 human_required，报告按用途列出每个人工决定（解除阻塞的带原因），并列出各叶子的规划体量（冻结计划所依据的文件数与字节，对照 CASE/TASK 数）。 |
| 2026-10-08 | 上游修订按叶子边界分流：再拆分或 run 修订改到的已冻结叶子，边界保持（原 scope 语句、需求、CASE、验收归属、写范围与依赖俱在，无新增排除）时以 CR 接收并保留 plan 与代码，TASK 未变即重冻后直接重建复测，其消费者只等 provider；边界改写、收缩或迁移才整叶重规划；只更新证据的再拆分不清全局规划；独立性证明可声明无 TASK 受影响。资源搬运先定论：prepared run 登记 UI/Resource 适用的分配前，`target_resources` 的 copy 与 parameters 须已声明约定或写明目标不接收的原因，尚未登记任何根时也可经 run 修订写入；约定已声明时可原样加载的文件必须走复制清单；手工替换存量图片的 item 写明不能复制的原因并随报告披露；API 清单按 transport 登记路由，rpc/sdk 以调用名登记。 |
| 2026-10-08 | 已接受工件沿用接受时的规则：四维分析登记时判定（叶子冻结对它的要求在首次冻结时），设计验收时、计划提交与冻结时判定，此后各步只读取，仅漂移拒收；逐案豁免移除，差异进报告“规则欠账”。拆分写明每条 CASE 的唯一验收切片、支撑切片的理由，依赖成链或过半切片等待时写明不能按行为切的理由；报告列出各拆分的切片形态。渐进加载：worker 的必读输入收敛为执行所需（Test-Runner 为冻结计划与测试资产，代码作者另含本叶子四维分析与目标规范），报告所依据的全部证据仍核对漂移；阅读卡增量按执行实例计算、无需宿主回报，红线每张卡都带，机械验收步骤不带卡，同一小节在一张卡内只出现一次；拒绝消息指向规则小节的比例设为棘轮。 |
| 2026-10-08 | README 与六张图统一当前主线、按需设计、三类反馈、局部重验和成功统计；PNG 仅本地渲染。执行反馈在派 Fixer 前明确分流：实现错误修代码、规划/功能/依赖契约缺口修 SPEC、超 scope 上溯父 MO/GO。可选 MO 独立性证明保留未影响 TASK 与既有 Green，原回执/执行基线不变；新 build/unit/static 与受影响/非 Green 路径真实复测，共享影响回退全验。统一 GO 测试分工，不新增前置规划轮次或流程版本。 |
| 2026-10-07 | 执行反馈驱动规划修正：GO/父 MO 分配 scope/上游 CASE，子 MO 拆 TASK 后直接形成 SPEC 并冻结执行；独立 design 改为按需。修复中可补充原预期的路径/断言，MO 审核后再冻结、更新已有代码并复测；保留旧计划与失败证据，不新增 Run 或计划版本。 |
| 2026-10-05 | 规划闭环与原子叶子：MO 通过 decompose 提交 atomic-leaf 结论，GO 接受后保留当前节点进入 SPEC 规划；完整 registry 可先验覆盖，无关根待拆不阻挡就绪叶子，受影响依赖仍受门禁约束。bottom-up 修正、top-down 重规划只留不可执行 history；不恢复局部 Auditor 分支。 |
| 2026-10-05 | Workflow 统一发布：删除运行期 control_policy_version、策略升级及旧提前审计分支；统一 MO 冻结、累计修复预算、TASK/PATH 执行和独立 Test-Runner/宿主 Auditor。编码前规划变化仅留不可执行 history，不形成计划版本；旧 Run 在当前门禁下继续，历史配置只读投影。版本差异仅在本表留档。 |
| 2026-10-04 | 同 Run 上溯修订根/父分配、上下文和遗漏需求/CASE；按影响闭包重规划，未变 worker 保留冻结上下文；验收变更复测，抽象经验跨 Run 复用。 |
| 2026-10-02 | 编码前独立测试设计接入 Ledger 派发/提交/验收链；prepare 固定该门禁，plan/freeze 绑定同一份已接受设计；过期设计明确撤销或重新规划，保留历史证据。 |
| 2026-10-02 | 行为完整性：prepare 固定行为契约门禁；GO/父 MO/子 MO 行为闭包审阅；OpenSpec 派生 Scenario 索引与任务/断言追溯；单测核验当前 runner 的 JUnit 实际测试 ID、计数与报告证据。 |
| 2026-10-02 | 日志与追溯：执行期间持续留存分流日志、时间/字节索引及不完整标记；只读 trace 支持场景/路径/测试 ID、历史归档与分页；watchdog 可附输出观察，仍不改变业务状态。 |
| 2026-09-18 | 初始工作流：9+1 角色、Ledger 单写事件、冻结门禁、本地控制器 |
| 2026-09-19 | Test-Runner 先构建后自动化；Harmony 自动测试内核与独立 uv 环境 |
| 2026-09-20 | 自动化缺测 Yellow 收尾；父 MO 命名与用例报告；四维切片；同 run 来源追加；显式 provider owner |
| 2026-09-21 | Auditor 代码治理前置；埋点适用性；统一资产根与顶层 OpenSpec |
| 2026-09-22 ~ 09-24 | Watchdog 旁路通知、执行器中断收尾、OpenSpec 分范围核验、宿主接入契约 |
| 2026-09-25 | 机器可读语义模型；模型路由档位 |
| 2026-09-27 | UI 保真证据、受限领域工具 worker、精确资源策略、视觉对齐阶段、手势、HAP 绑定、Foundation 解析门禁；prepared run 默认开启 UI fidelity |
| 2026-10-01 | 模块控制器在规划/测试阶段的守卫增强；证据契约与复用目录统一为单一当前版本，删除旧版本兼容分支 |
| 2026-10-01 | 修复闭环与独立审查：可配置 build 本地修复轮次、作者自检、本地修复复用 Implementer 会话；build → static → automation 的静态规格闭合审查；按步骤阅读卡（单卡不超过 60KB）；轻量叶子、父级批量冻结信封、运行时变体冲突交人工；可选模块 Git 检查点 |
| 2026-10-01 | 降低流程成本：static 并入 build 派发（绿色叶子 21→19 事件、4→3 次派发）；会话/阅读卡采纳可审计；流程成本指标进入状态与报告；运行指南去重与协议体积棘轮；静态审查要求调用位置；依赖闭包空闲即可提前审计；可选全模块 Fixer 自诊断 |
| 2026-10-01 | 文档瘦身：角色定义与角色技能改为“专题义务”表，规则只在专题协议中陈述一次；协议总量 516KB → 476KB，最大阅读卡 49KB → 45KB，体积棘轮降至 480KB |
| 2026-10-01 | 补齐独立验证：逻辑单测关卡（与构建同一派发）、候选 App 崩溃判为缺陷、视觉修复聚焦、静态审查增加吞错反例与单测引用、可选写范围核验 |
| 2026-10-01 | 渐进式加载：规则不常驻——AGENTS.md 由 19KB 缩至 8KB（红线、角色索引、专题索引），专题规则在各自协议的“总则”中只陈述一次；阅读卡按操作与触发（UI/复用/埋点/轻量叶子）取小节，可物化为单文件，恢复会话只交新增小节，拒绝响应附小节指针；status 默认精简视图；角色通用约定并入共享协议；清除旧运行兼容叙述与三个恒开开关 |
| 2026-10-02 | 阅读卡再收窄：审计/GO 规划/MO 按操作取小节，技能文件只带执行规则，专题义务表与操作矩阵按行取；任意模块请求可报告会话与卡片以做增量交付；流程成本统计阅读卡字节；Harmony 写入路径约束移入 Harmony 运行协议；README 精简为入口与专题速览；清除变更日志口吻措辞 |
| 2026-10-02 | 堵住整份加载的入口：渲染后的阅读卡不再含指向整份协议的链接，小节引用改为可直接取用的选择器；游标轮询只带卡片大小并支持 `--since` 增量；步骤直接给出本步模板，不再读模板索引；Test-Runner 定义按测试阶段取块；会话持有协议文本超阈值时建议按 checkpoint 冷启动；请求级 `hint` 成为统一回报通道 |
| 2026-10-02 | 流程与契约精简：build、unit、static 合成一份结果一次验收，设计预检随提交登记（绿色叶子 24 → 19 个事件）；scenario_index 与静态审查范围由 Ledger 派生，不再手写；叶子的行为审阅并入 source_closure；共享能力归属与复用目录互相校验；步骤模板按操作收窄并设预算；设计说明合为一节 |
| 2026-10-02 | 控制器减负：事件日志只记录变化、工件索引不重复列出（模拟运行 8.07MB → 0.30MB，旧事件仍可重放）；状态只存报告与结果的哈希引用；执行者自己的预检随操作登记（绿色叶子 19 → 18 个事件）；全绿测试结果的验收标为机械步骤；plan 只引用已接受设计，PATH 与任务范围由 Ledger 补全；模板去重 |
| 2026-10-03 | 状态与入口按需取用：`status --view step` 只给一步所需（两叶子模拟中角色取状态 228KB → 约 8KB），输出改紧凑 JSON；plan、拆分提案与设计输入不再抄写全局上下文，由 Ledger 绑定摘要（plan 事件 27KB → 18KB）；卡片与命令不再指向整份协议文件，角色与技能中的协议链接改为小节定位；协议只用操作矩阵的词汇，删除未实现的抽象事件层；测试阶段的派发标为机械步骤；`contracts.py` 提供摘要命令 |
| 2026-10-03 | 派发后预检：执行派发不再等待 worker 的预检报告，worker 在同一次启动内预检后开工，ready 报告授权工作、blocked 报告退回派发且不耗修复轮次；执行派发都是机械步骤；绿色叶子的模型调用 16 → 10 次 |
| 2026-10-03 | 流程收尾：`ledger.py advance` 一次提交一个模块的全部机械步骤并给出下一张阅读卡；等待人工决定的步骤都给出要批准的摘要；8 个命令重复的约定合到宿主接入的“命令通用约定”（命令 49KB → 37KB）；共享协议进卡只带规则小节（每张卡小约 0.9KB）；行为契约由 Ledger 写入 plan；协议体积上限 554.8KB → 543.2KB |
| 2026-10-03 | 作者不再抄写 Ledger 已知的值：test_design_ref、行为审阅与任务四维分析中的范围摘要和需求/CASE 列表、global-plan 的规范与架构引用、PATH 的 required 及两个勾选标志都可省略，写了必须一致；plan 不再要求 global-contract 定义；删除无人读取的 freeze.json，module-input 模板改为 register 实际载荷（3.3KB → 1.7KB），模板索引只保留索引（14.1KB → 8.0KB）；图集改为派发后预检的顺序；协议体积上限 543.2KB → 537.0KB |
| 2026-10-03 | checklist 改为包内固定的评审清单：Ledger 接受 plan 时按内容哈希存入本 run 并绑定到模块（不进 plan 摘要），投影时附证据链接与运行勾选，Spec-Designer 不再实例化（规划卡模板 24.7KB → 19.6KB）；运行输入只有一种形状：prepare 直接返回 init 载荷，GO 补齐需求、CASE、规范与全局路径后原样提交，删除 10 个不生效的配置项（含 repair_policy，已有项目配置需执行一次 update 删除该键），global_test_paths 统一为 global_paths；协议体积上限 537.0KB → 536.8KB |
| 2026-10-03 | 图片与图标对齐：collector 记录嵌套 drawable、非布局 XML 图标、主题属性与没有资源文件的图片来源（URL/API 字段、拼接名、绑定、绘制代码），闭包要求逐项有 Resource item 或带证据的排除；存量资源离线渲染为参考，图像检查把目标屏幕节点与参考比较并由 Ledger 重算，存量不必可运行；手工替换的图片须有图像检查或人类批准的偏差（无法离线测量的动画与 .9.png 只接受偏差）；收尾报告披露每个非精确图片 |
| 2026-10-04 | 资源与参数按搬运对齐：collector 记录每处资源使用点，代码用到的文件资源须由节点声明或带证据排除，同一张图的密度与平台版本副本归为一个资源；项目声明一次资源落点约定后，`resource-plan` 派生复制清单与参数表（布局属性、图层、代码里的 setter 与布局参数），冻结时由 Ledger 重算，`resource-sync` 一次复制文件并写出参数文件，验收比对字节并核对代码按 accessor 与键引用；Spec 只写不适用、获批偏差、token 映射与表达式定值；树上每处静态图片须有图像检查或带证据豁免，`screen-checks` 派生检查，新增文本与节点检查及铺满画面图片的内容比较；逐项登记的资源同样在验收时比对字节与引用；收尾报告披露复制文件数、检查覆盖与参数填充率 |
| 2026-10-04 | 作者不再重述 Ledger 已知的值：预检报告不写必读输入（Ledger 派生并把 ready 报告绑定到其摘要，输入变化即过期，使用回执时重新核对），任务级四维行的证据可省略，JSON 文档可在顶层 `refs` 写一次文件引用并按 id 引用，hash 不符的拒绝点名文件与实际摘要。设计跟随 SPEC：设计输入必须引用叶子自己的 SPEC 草稿（带 Requirement-ID/Scenario-ID），设计断言用 `scenario_ids` 写明所验证的场景，`scenario_trace` 的断言由 Ledger 补全，设计文档只记依据；设计不再因全局规格先行而返工。模块状态视图不带 plan 正文，触发后的模板总量加棘轮，角色定义与命令文件删去只指向通用约定的重复文字（协议 536.8KB → 532.1KB，棘轮降至 532.2KB）；图集只保留 SVG，PNG 由生成脚本在本地渲染、不入库 |

## 控制工作流

当前统一主线为 GO/父 MO 切 scope/CASE → 子 MO 拆 TASK/四维 → SPEC 冻结 → Implementer/Test-Runner/Fixer 任务执行与反馈调整 → 统一宿主 Auditor。同 Run 修正保留历史证据，人工仅裁决实际未决或业务授权变化。规则见[控制主线](skills/migration-protocol/references/state-machine.md#控制主线)。
