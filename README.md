# SDD-TDD-Migration

按功能切片迁移的 Agent 工作流包：9 个执行/治理角色 + 1 个 Ledger。输入整体规范、新架构、存量代码路径、目标代码路径及整体测试用例，先拆分模块和用例，再并行迁移，最后独立审计。

## 从这里开始

可选旁路 [Watchdog](skills/migration-protocol/references/watchdog.md) 提供 `check/watch` 状态监听与通知、`ack` 交付确认；未确认通知可重放，Host 按 notice_id 去重展示。支持真实本机进程检查及宿主 API 状态导出；未接入时显示 unknown。不会自动启动、派发 Agent、提交恢复操作或影响迁移门禁。

1. 宿主读取 [AGENTS.md](AGENTS.md)；被派发的角色只读它的阅读卡，专题小节按需取。
2. 首次提供项目资料，宿主根据 [project-context.json](template/project-context.json) 保存到固定 `<workspace_root>/.sdd-migration/project-context.json`（首次未指定 workspace_root 时取配置目录父级）；后续按该目录读取，用户明确更新时增量保存。无需每次重填运行输入。
3. 在支持此包的宿主中执行 `/sdd-init`，先固定项目配置和本次请求快照，再由 Global 生成 [运行输入](template/global-input.json)、宿主业务契约、需求/用例输入、账本和模块规划；`/sdd-plan <run-id> <module-id>` 从 Ledger 写出的六件套与计划集骨架起笔，组织叶子 TASK、四维追溯与上游用例路径，由 MO 审核冻结；真实未决或需求/验收/授权变化才交人工。旧 input.json 也可导入。
4. `/sdd-run <run-id>` 调度已冻结且依赖就绪的模块，单模块也可用 `/sdd-module <run-id> <module-id>`。模块内自动推进到完成、挂起或预算耗尽。
5. 用 `/sdd-status <run-id>` 冷读状态；用 `/sdd-resume <run-id> [module-id] [decision.json绝对路径]` 恢复；用 `/sdd-audit <run-id>` 执行独立遗留复核与收尾审阅。
6. 全局审计通过后，`/sdd-archive <run-id> <decision.json绝对路径>` 验证人类交付授权并同步、归档 OpenSpec。授权必须绑定具体交付内容摘要。

这些 slash command 是待宿主加载的命令定义，未安装到用户配置；本包已提供本地 Ledger 控制器、阶段校验和测试调用适配器；没有常驻 Agent 调度服务或内置业务测试。本地控制器实现事件提交、单写者和模块资源占用检查；宿主仍须提供身份认证、写权限隔离、Agent 派发与项目真实测试适配器。具体能力见 [本地运行指南](skills/migration-protocol/references/local-runtime.md)。仅加载 Markdown 不会产生操作系统级权限隔离。没有这些能力时应显式阻塞，不能宣称端到端迁移已执行。

要在其他仓库真实跑起来，按 [宿主接入契约](skills/migration-protocol/references/host-integration.md) 接入真实角色派发与执行回执。推进按 global/module 范围运行 `/sdd-verify`，巡检用 projection、交付用 final；核验只证明记录和投影一致，无关模块视图错误不阻塞当前 MO，也不能由核验通过推断实际执行或功能全绿。UI 分析、资源转换与受限视觉取证按 [领域工具受限接入](skills/migration-protocol/references/domain-tools.md) 使用，保持既有角色、Ledger 和修复预算。

## 流程图

GO/父 MO 划分 scope 和全量 CASE → 子 MO 拆 TASK → SPEC 与路径审核冻结 → Implementer → build/unit/static → automation → 反馈分流与复测 → 统一 Auditor。叶子满足起步门禁即可开工，欠项在需要它的阶段前补齐。实现错误交 Fixer，范围内的规划缺口在同一 Run 内用 CR 修订，分配范围不足才上溯父 MO/GO。见 [变更控制](skills/migration-protocol/references/openspec.md#变更控制)。

按三层编排阅读 [完整图集](diagrams/README.md)：[总览](diagrams/workflow.svg) → [子 MO 执行与修复](diagrams/module-execution.svg) → [Auditor 跨模块处理](diagrams/auditor-closure.svg)，另见贯穿各阶段的 [二方库语义与复用](diagrams/reuse-dependencies.svg)。SVG 入库，PNG 由源文件在本地再生成。自动化详见 [外层执行闭环](diagrams/automation-flow.svg) 与 [Android/Harmony 单 PATH 内核](diagrams/automation-engine.svg)。

## 目录

| 目录 | 用途 |
| --- | --- |
| `Agents/` | 10 个角色定义，含输入输出、边界与自查 |
| `skills/` | 共享协议与 10 个职责技能，按需读取 |
| `command/` | 10 个命令入口，负责上下文配置、参数、门控、派发与投影完整性核验 |
| `template/` | 全局输入、模块输入、六件套及诊断、测试、Ledger 请求、人工决策等运行工件模板 |
| `diagrams/` | 三层编排、子 MO/Auditor、复用与自动化图及生成源文件 |

运行期资产集中在固定 `workspace_root`，其下 `.sdd-migration`（长期配置）、`.sdd-runs/<run_id>`（运行证据）、`openspec`（规格与状态中枢）顶层并列；包目录自身不存迁移状态。run 固定 prepare 时的包提交（`package_sha`）：宿主用该提交的 worktree 跑完整个 run，新规则只对新 run 生效。Harmony 执行统一在 `.sdd-runs/<run_id>/runs/harmony/`（automation/sandbox），构建资产在 runs/build；临时文件归 runner，结束清理，失败留存原因。项目模型参考配置/凭证在 `.sdd-migration/harmony/`；Test-Runner 首次准备时复制到本轮 `runs/harmony/sandbox/environment/`，各模块共享本轮副本。入口为 `openspec/runs/<run_id>/workflow.md`。见 [完整留存布局与二次启动](skills/migration-protocol/references/storage-layout.md)。模块 ID 永久稳定，如 `M001`；OpenSpec change 名如 `migration-demo-m001`。新增模块只追加编号，不因排序改变历史 ID。顶层 `openspec` 是 prepare→init→apply 真实跑通后的投影，不能手写；最终交付用只读门禁 `verify_openspec.py --root <run> --scope final` 核验投影与正式收尾报告；缺事件证据时恢复其有效来源，不由核验结果推断真实派发或功能通过，细则见 [投影完整性收尾门禁](skills/migration-protocol/references/storage-layout.md#openspec-投影完整性收尾门禁)。

## 对现有 guidance 的适配

依据 [flow_spec.md](../flow_spec.md)、[dingpan 分析](../dingpan_harness_architecture_analysis.md) 与 [原 Agent 模板](../template/agent_template_guide.md)、[Skill 模板](../template/skills_template_guide.md)、[Command 模板](../template/command_template_guide.md)。本次用户明确要求优先，覆盖关系如下：

| 现有机制 | 本包机制及理由 |
| --- | --- |
| Command/Agent 分别写 `plan.md` | Ledger 唯一写事件与状态投影，杜绝并发双写；命令只提交请求 |
| 所有 Agent 不能调用其他 Agent | 叶子角色单步退出；编排角色提出派发事件，由宿主执行；Auditor 可经 Ledger 委派修复 |
| 每一步均人工确认 | 清晰规划由 MO 审核冻结；真实未决、需求/验收/授权变化与主分支合并保留人工门禁 |
| 文件存在即可修正阶段为完成 | 校验文件、摘要、当前基线及已接受事件；文件存在不能证明通过 |
| 删除已存在文件再运行 | 使用不可变历史工件和事件恢复；不删除用户成果、不静默覆盖 |
| 运行失败测试后再实现 | 正式测试在代码被接受之后；测试在编码前设计并冻结，作者在任务循环里先写单测、自查看到失败再实现，两次自查记为该任务的 red 证据（统计，不设门禁） |

因此本包的 TDD 是：测试在编码前设计并冻结，正式执行在代码接受之后；每个任务的 red→green 由作者自查留证，报告按任务统计有证据 / 无证据 / 不适用，不伪造失败。`plan` 指文档澄清阶段，不假定宿主能自动切换某产品的 Plan Mode。

## 验证范围

本包可检查入口引用、frontmatter、JSON 模板与流程契约；真实迁移须在填写技术栈、宿主适配和真实测试命令后验证。推荐的行为验收场景见 [workflow-verification.md](template/workflow-verification.md)。`reading.py` 约束的是加载进模型的内容，不是协议文件体量：阅读卡（常驻 + 按需一步 ≤ 51,200 字节）、模板、入口 AGENTS.md，以及 `reading.py show` 一次读出的一节（超出时给小节目录）。新增规则写入其专题协议并合并重复表述，不在运行指南中再追加一份。

## 规划、执行与反馈控制

GO/父 MO 负责模块与子模块的 scope 切片，并在冻结前分配上游全量 CASE；原子能力可直接作为叶子。子 MO 在叶子范围内拆 TASK、组织四维分析，Spec-Designer 编制 proposal/spec/design/tasks 与 CASE/PATH/ASSERT；MO 决策经 Ledger 投影为 status，包内 checklist 由 Ledger 绑定并投影，组成 OpenSpec 六件套。SPEC 是 Implementer 的执行规范，四维分析描述业务、功能与代码边界，两者承担不同职责。规划完整可执行即可由 MO 审核冻结，不增加预演全部缺陷的规划轮次；Test-Runner 的独立 design 仅按需协助。

叶子是功能树上的子业务流（页面是 TASK 不是叶，3–30 条 CASE，功能叶之间不重叠、并集覆盖父的功能），自带四维分析与实现 SPEC；用户给了用例则用例范围界定叶子，没给则先读源码建功能树再派生用例，切片与用例同源。冻结只核起步门禁（范围、写锁、任务、PATH、四维追溯、六件套）与一致性，完备性（资源闭包、源闭包证据面、UI 目标的 PATH、场景/四维/埋点追溯、API/数据行为测试、复用来源审阅、测试准备、参数表决定、单测与静态 PATH 的缺项）记 gap、DoD 前结清；六件套与计划集、执行侧报告（Test-Runner 预检与静态审查、Auditor 清单与代码审查）由 Ledger 写骨架，留标记的提交被拒。

```text
GO / 父 MO：scope + CASE → 子 MO：TASK + 四维 → SPEC / PATH 审核冻结
  → Implementer（Ledger 代写预检，步骤先列提交必备证据）→ MO 接受代码
  → Test-Runner：build → unit（同命令一次执行）→ static（可与模型执行的 automation 同派）
  → automation：逐 PATH / ASSERT → visual（适用时）
  ├─ 全部必需路径有效 Green → MO 验收 DoD → 模块收尾
  └─ 非 Green → 现有诊断 / MO 归因分流 → 更新后正式复测
全部模块本轮收尾、父汇总有效、无 worker / 可推进动作 → 统一宿主 Auditor
```

**SDD 先规划后执行、边执行边调整；TDD 从上游全量用例建立冻结前覆盖，在 automation 中收集实现错误和不符合预期的证据，再调整 TASK 实现。** 未生成代码不执行目标测试，首次即 Green 如实记录，不伪造 test-first RED。

**冻结前定清行为断言和保真义务。** 每个已纳入 SPEC 的 Scenario 需要行为 PATH 上的预期断言。 适用的 API/URL、图片来源与图标、XML 布局参数沿四维条目绑定目标消费者、迁移策略和验收义务。优先原样复制可加载资源，复用解析后的参数值。Ledger 按内容归档派生的复制清单、参数表和四维分析，派发时只同步当前 TASK 拥有的输出。CR 更新同名输出时先核对上一份验收哈希。复制与参数生成落到同一路径时由冻结门禁报冲突，目标文件出现独立修改时保留原字节，冲突与回执关联当前派发。`drive` 先交付独立派发，再由宿主在原 assignment 和 fence 下执行资源同步。并行名额被运行中的 worker、已交付的规划或待交接的编码会话占满时，冻结 TASK 仍可登记资源准备并取得对应写范围锁。同步完成的回执会唤醒等待中的 `drive`，有空位且证据通过核验后，Ledger 以 `resource-start` 在原 fence 下启动 coder。复制清单记录完整限定符、源哈希和选用依据。目标支持多档时用 `preserve_density` 和 `{qualifier}` 分别交付可加载档位，报告披露折叠及未测档位。可预览的存量先捕获基线，确实捕获不到则给出原因与证据。未结清的保真门禁回 Spec-Designer，已结清后直接进入实现。运行证据由 Test-Runner 按冻结 PATH 收集。

`target_resources.parameters.configurations` 可按完整限定符生成 XML 字面值。需要在设备上验证的档位与值由视觉 PATH 冻结 `device_configuration`，并将源限定符绑定到截图、视图树和本次采集的设备配置。Test-Runner 比对图片、边界尺寸或间距、颜色采样和文本，Ledger 重算后记账。设备配置缺失或不匹配时留缺口。报告按平台、源限定符和 PATH 展示搬运、资源取值与画面。Harmony 的限定 PATH 在同一 HAP 与设备锁内，用 HDC 保存 PNG 及前后视图树，从应用内的探针读取实际配置和资源取值。 [资源与参数搬运](skills/migration-protocol/references/resource-transfer.md)

**按欠项影响的阶段安排修订。** unit 缺资产时先完成就绪的 build，automation 中先派发资产齐备的 PATH，再为待执行 PATH 修订 SPEC。静态审查与 DoD 继续核对各自的义务，未执行路径仍计入应测范围。实质性欠项在静态审查前补齐，纯四维条目 ID 引用可在首轮自动化后、DoD 前补录。已有欠项到期时，同一 CR 可一起处理其余欠项。

**独立叶子就绪即派发。** `drive.py` 先向宿主返回新分配的 Implementer、Fixer 和首次就绪的 Spec-Designer。编码角色需要轮换会话时，也按并行预算和步骤修订号提前交付一次，后续轮次继续执行无关的冻结命令。已交付的轮换名额保留到交接后的编码派发，资源同步完成的其他叶子等空位再启动。编码仍须满足资源同步、预检与写入授权。分批构建在派发、执行和验收使用同一提供方输入。若本批构建暂时无法派发，已冻结且就绪的剩余 TASK 可先编码。同一构建单元的编码与构建仍互斥。Android/Harmony 视觉派发若只消费已验收 APK/HAP，可使用受限工具和内置视觉校验器，与不重叠的编码并行。设备锁照常检查，需运行自定义命令的派发沿用原互斥。

**机械验证可从完整回执恢复。** 宿主在命令结束与结果入账之间中断时，同一派发核验现有 PATH 回执后继续。已完成的命令沿用原 test_run_id，待执行的命令从下一组接续。回执不完整时先核实旧进程已停止或隔离，再按原恢复流程处理。

**按步加载。** 调度循环读取当前游标，机械动作成批入账后集中生成报告和 OpenSpec 投影。派发只交当前阅读卡，平台专题和模板按当前选中的 PATH 列出。规划尚无 PATH 时按 Run 声明列出候选专题，推理专题在根因未确认或推进停滞时按需取单节。宿主消费 drive 的模型等级和提交所需的 Run、作用域及修订号；已交付上下文达到阈值时，在安全交接点通过 `rotate` 从同 Run 检查点启动新会话。

| 执行反馈 | 控制分支 | 后续动作 |
| --- | --- | --- |
| 实现违反当前 SPEC | `fixer` | MO 在累计预算内派发 Fixer；最小补丁、自验证、MO 接受后正式复测 |
| 当前 scope 内规划遗漏、功能/依赖契约缺口、fidelity 规划不足 | `spec` → CR（`change`） | Spec-Designer 修订 SPEC，MO 审核再冻结，Implementer 更新已经 coding 的代码；只改测试写法而身份与期望不变的 CR 不要人工决定 |
| 原分配范围不足 | `upstream` → `realloc-request` | 上溯负责的父 MO/GO，分配变化后更新受影响规划，再冻结执行；待审期间拒绝重复请求，保留首个请求及原恢复阶段 |
| 已有提供方暂不可用或环境/外围阻塞 | 既有等待/恢复分支 | 留存根因和证据；自动化环境缺测保持 Yellow/未执行，条件恢复后真实验证 |

只观察到自动化断言失败时，诊断按需核对冻结预期、实际观测和存量依据，再决定修复路径。Fixer 不修改需求、验收或冻结 TASK，只能提出 CR。原预期内的技术补全由 MO 审核；真实未决或需求、验收、授权变化交 Human。源码实现错误造成的 fidelity 偏差仍走 Fixer，规划遗漏造成的偏差才走 CR。

统一审计把回溯发现逐条按根因路由。同一叶子同时收到两类发现时，先修订叶子 SPEC，再将范围缺口交父 MO/GO。叶子重冻结清对应 SPEC 问题，分配审核被接受后结清对应范围问题。全局 `revise-run` 只处理报告 `root_updates` 明确列出的根模块，结论可为维持或调整分配；未列出的请求及子叶请求继续待审。 [审计回溯](skills/migration-protocol/references/audit-scope.md#问题处理)

同 Run 的局部分配修订或重切等待全局覆盖重审时，Ledger 核验未受影响叶子的冻结、依赖闭包、验收归属和写范围。通过校验的独立叶子沿用已接受的覆盖证据继续派发。父 MO 重切时，分配未变且只消费独立制品的视觉派发可按原 fence 收尾，再处理受影响的依赖。统一 Auditor 收尾仍须当前的完整覆盖。

`planning-reopen` 后的首次新计划仍与上一份计划比较，MO 可依据差异审核。更新后的 SPEC 经现有门禁重冻，受影响的 TASK 再更新代码。修订默认全模块重验；MO 可在 CR 的 plan-review 提交 [TASK 独立性证明](template/task-independence.json)，核对定义、写范围、读依赖、共享 PATH、未变需求及文件追溯后，只重开受影响 TASK，保留未影响 TASK 和有效成功证据。共享影响须全模块重验，过期或漏报变更的证明拒收。**新代码始终重跑 build/unit/static**，局部重验时 automation/visual 重跑受影响及非 Green 路径。原回执、test_run_id 和执行基线保留，另记 `validation_reuse`。详见 [TASK 局部重验](skills/migration-protocol/references/openspec.md#task-局部重验)。

视觉分批以未通过的 PATH 判定缺口。先跑就绪项，剩余视觉 PATH 缺资产时打开对应补资产 CR。只为待测 PATH 补充 staging 中的执行资产，且生产契约、冻结命令、断言和目标测试源都未变化时，重冻保留已验收 TASK。可核验的原回执继续有效，Test-Runner 执行受影响或证据失效的 PATH。需要写入目标项目的新测试源仍走实现交付与正式复测。

Ledger 为待测 PATH 发起补资产 CR 时，已验收实现和前置证据仍有效的提供方继续供依赖代码的消费者使用。需上游验收的消费者继续等验证，重冻发现生产契约、目标测试源或执行基线变化时按现有规则传播影响。

补录独立行的四维条目 ID 时，已通过其他 DoD 门禁的提供方可以维持下游依赖及预检。提供方继续审查新 SPEC，证据漂移、实质变更或验证非 Green 时恢复依赖等待与复测。build/unit 回执复用仍核对目标树、命令、测试资产、宿主环境和产物。证据不足或 Gradle 使用外部共享缓存时，提供方重跑对应验证。

提供方修订时，消费者原有的人工阻塞与决定摘要继续有效。恢复须同时满足原阻塞的人工批准与依赖的当前验证门禁。

同 Run 追加复用来源时，GO 仍记录每个叶子的影响结论。评审与等待范围绑定需要重规划的叶子及受影响消费者。已有冻结实现且只需核对提供方变化的消费者可选 `reverify`，保留 SPEC 和代码。独立叶子沿用原派发、冻结和执行上下文。尚未提交 Plan 的草案沿用分配和规划游标，即使提供方需要重规划。首次提交按新目录核对复用候选，编码仍须等提供方就绪。相同输入上的 Green 回执入账以及独立叶子的同语义重冻可继续沿用评审。受影响消费者正在验证的视觉 PATH 若只绑定未变的制品和提供方输入，可以在原上下文及 fence 下继续提交，再按实际依赖处理剩余验证。活动的受管集成按实际依赖判断是否需要等待。

仅调整 build、runtime 或 test_adapter 的技术修订，可以等待受影响 worker 正常提交。相同冻结和代码基线上的 Green 回执不使评审失效。评审时正在验证的受影响叶子在修订应用后再领新测试派发。分配、冻结、代码、人工阻塞或失败证据变化仍须重新核对评审。

提供方恢复后，消费者保留冻结 SPEC、已接受代码和原有人工阻塞。Ledger 对照 PATH 验收时的提供方闭包、冻结、代码和构建产物引用，输入一致时沿用结果，变化或旧回执缺绑定时从最早失效阶段开始复测，原回执保留追溯。

设备变更走同 Run 的 `reverify`。设备评审生效后，暂停受影响 PATH 的旧环境新派发。同叶子输入可核验且与变更无交集的受管视觉派发可按原 fence 完成。无关叶子冻结时，只要其相关设备义务及分配仍一致，评审继续有效。范围外 GLOBAL PATH 的同输入 Green 可继续入账，受影响结果、失败或输入变化仍进入评审。重冻后沿用的 Green 经 Ledger 复用证明、原始回执与当前输入核验后可继续保留。构建回执和产物按 PATH 校验，失效制品只影响实际消费它的受管测试，输入不透明的设备路径继续保守复测。Harmony 可为 `emulator`、`physical` 或 `physical-high-dpi` 等独立配置冻结 PATH，换绑只影响对应配置。未配置设备的已冻结 PATH 仍为待验证。混合环境变更走常规重验，冻结的应用、入口或 URL 变更由 SPEC 修订处理。

持有 GLOBAL PATH 用例的叶子完成后，GO 可派独立 Test-Runner 做波次集成。受限 Android/Harmony 视觉 PATH 用冻结的 build binding，按 owner、提供方闭包、验收产物与环境绑定执行及复用。内置 GLOBAL automation 的设备输入按实际平台绑定，设备修订与审计沿用同一范围，继续核验代码和构建产物。已评审的设备变更使内置 PATH 失效时，owner 就绪即可进入下一波集成，叶子均已收尾时也可在审计前复测。单条 GLOBAL PATH 的配置缺失或漂移记录为该路径的输入缺口，其他就绪路径照常派发。共同依赖的代码基线无效时，依赖该基线的波次等待恢复；缺口仍纳入后续审计。自定义命令或输入范围不明的 PATH 按全局快照验收。仅其他叶子改变全局快照时，统一审计在基线稳定后复测。活动波次的输入失效后，宿主凭停止或隔离证据执行 `integration-revoke`，同 Run 恢复派发。Run 修订等待活动波次时，先完成仍有效的原派发，再应用修订。有效 Green 在统一审计复用，Red 路由给 owner。

已 prepare 的 Run 在首次执行可核验的 Build／Unit 时记录实际输入指纹，同一批 Unit PATH 共用一次记录。增量 CR 开启时，只有原始指纹与当前受保护输入一致的回执可复用。审计点名重验某条 build PATH 时，Ledger 核对冻结或有效的重冻复用证明、代码基线、命令、宿主输入与产物哈希，保留证明有效的其他 build PATH。同次判定共享一次目标树扫描。补齐构建后合并产物，才继续下游验证。设备单独变更后，冻结 Gradle 构建可用封存的旧上下文复核原指纹，同时核对当前构建配置、命令、工具、目标树与产物；补测试资产和纯四维 ID 的增量重冻沿用同一核验。其他命令沿用完整上下文指纹。受管叶子 visual PATH 可绑定提供方的指定 build PATH。在功能门禁通过后，先派发制品和实际提供方闭包已就绪的 PATH。提供方在模块内回溯或经 `revise-run` 重规划时，无关且输入仍一致的活动视觉派发可继续提交，MO 再处理依赖和剩余验证。共享执行上下文或工作流包变更时采用常规依赖等待。输入不可核验、代码变化或涉及跨边界共享影响时重新构建受影响范围。

纯设备变更后，Auditor 可沿用 SPEC、代码、分配和归档证据仍有效的模块代码评审。新报告引用原评审，独立核对当前宿主目标、受影响 PATH 的复测证据与最终结论。

Harmony 真机的限定资源 PATH 绑定已接受的签名 HAP、运行中应用的构建标识及设备身份。Ledger 核对 WindowManager 回读的焦点窗口、定向 UI 树和 PNG，验证采集与下载的完整时序。新版资源探针分别报告系统配置和应用窗口有效配置，并回读正式消费者选中的 HAP 资源成员或 XML 分支。按冻结的配置来源与标识判定覆盖。等值且不可区分的候选只确认值一致。详见 [Harmony 限定资源取证](skills/migration-protocol/references/resource-transfer.md#harmony)。

Ledger 按宿主任务、模块和 TASK 汇总 automation 的应测、已尝试、完整执行、有效成功、Red/Yellow 和缺路径 CASE；参数/平台实例分别计 PATH，重试不增加分母。设备或视觉缺口按 CASE 单列为 Yellow 验收义务。实际 PATH 分母只计已冻结路径，缺口仍影响定义覆盖与完整验证。`reused_passed_paths` 单列，排除在 `current_executed_paths` 之外；成功集合附原始执行身份与证据，报告分别给出完整执行和全部通过；TASK 行的缺路径只计模块整体缺的 CASE。缺路径、缺测或失效证据不能据现有成功集合宣称全量通过。

同一宿主迁移任务始终沿用一个 Run，保留失败、规划 history 和累计预算；执行仅绑定当前冻结 SPEC。只有新宿主任务新建 Run，抽象且已验证的经验可跨 Run 复用。各 MO 独立推进；某个失败只影响自身及有证据的依赖范围。统一 Auditor 审阅全部模块与宿主目标、治理代码并独立裁决。审计复测先核对 finding 指定的 PATH 和提供方输入，从最早失效阶段执行，并用累计的有效 PATH 回执结案。空清单只做独立审阅。TASK 局部证明不削弱 Auditor 的权限，Fixer 自测也不能代替正式测试或独立审计。

## 专题速览

各专题的权威规则只在对应协议中陈述一次（[宿主接入](skills/migration-protocol/references/host-integration.md#专题索引)的专题索引列出触发条件），这里只给方向：

| 专题 | 一句话 | 协议 |
| --- | --- | --- |
| 二方库与已有能力 | 复用必须逐行为对齐存量功能；能力目录显式 provider owner | [复用](skills/migration-protocol/references/reuse-dependencies.md)、[来源变更](skills/migration-protocol/references/source-changes.md) |
| 数据与 API 复用 | 复用的数据在取数与计算处对齐：数据契约（来源 / 取数条件 / 派生字段 / 失效）随维度 → TASK → PATH；API 契约与适配同理，目标已有实现直接重构复用 | [数据契约](skills/migration-protocol/references/resource-transfer.md#数据契约)、[复用](skills/migration-protocol/references/reuse-dependencies.md#9-目标已有实现与二方库冗余直接重构复用) |
| 包版本与产物体量 | run 固定 prepare 时的包提交，新规则只约束新 run；运行产物不设体量上限，棘轮只约束包自身的协议、卡片与模板 | [运行时](skills/migration-protocol/references/runtime.md#总则)、[OpenSpec](skills/migration-protocol/references/openspec.md) |
| OpenSpec 边界 | 标准基线/增量结构；status/checklist/Ledger 是本包扩展，Ledger 投影不可手改 | [OpenSpec](skills/migration-protocol/references/openspec.md) |
| 本地控制器与游标 | 单写事件事务、`status` 游标与阅读卡、Ledger 起稿的计划集与执行侧报告骨架、恢复与显式追加预算 | [本地运行](skills/migration-protocol/references/local-runtime.md)、[宿主接入](skills/migration-protocol/references/host-integration.md) |
| 并行 MO 与统一收尾 | 各 MO 独立推进；全量收尾后统一审计 | [状态机](skills/migration-protocol/references/state-machine.md#模块隔离与全量收尾) |
| Auditor | 先整体代码治理，再复核遗留；修复后验证，失败待人工 | [审计范围](skills/migration-protocol/references/audit-scope.md)、[代码治理](skills/migration-protocol/references/audit-code-review.md) |
| Android/Harmony 自动测试 | MobileAgenticOperator test 模式，逐 PATH/ASSERT 证据接入 Ledger；snapshot / recording 媒体任务供存量捕获与录屏取证，PATH 可录屏 | [移动端运行](skills/migration-test/references/harmony-runtime.md) |
| 切片与功能清单 | 叶子是功能树上的子业务流（页面是 TASK，3–30 条 CASE），自带四维分析与实现 SPEC；无用例先读源码建树再派生用例，有用例以用例范围为抓手；清单完整可追溯，疑问交人工；一条 CASE 一个验收切片；往次切分经验生成技能，供后续 Run 的 GO/MO 加载 | [切片规约](skills/migration-global/references/slicing.md) |
| 项目上下文 | 首次保存，增量更新，每次运行 prepare 固化快照；三条只有人能给的声明（存量怎样跑、目标在哪些设备上怎样预览、资源怎样进目标）问到为止，目标预览（可带目标 app_id / launch）由 init 写成运行环境文件并预填 visual PATH，`harmony_reference` 让 init 备好 Harmony sandbox；知识文档可查，缺的知识登 knowledge-need 交人补充 | [项目上下文](skills/migration-protocol/references/project-context.md) |
| 目标画像 | GO 逐功能记目标状态（absent/shell-only/partial/existing）；脚手架只在缺外壳处，持有代码的叶子欠复用说明 | [父子拆分](skills/migration-protocol/references/module-decomposition.md) |
| 用户参考媒体 | 存量截图/录屏与目标预期随项目上下文固化、下发到持有叶子：截图是 user-reference 视觉基线，录屏是交互预期，目标预期取代存量基线；规划步骤列尚未引用的媒体，未引用即欠项；截图可作断言参考图，录屏可标时间段；诊断/修复并列预期与实际媒体 |
| 存量预览与捕获 | 项目声明存量怎样跑（Android 设备 / 模拟器 / 虚拟机、鸿蒙设备、浏览器 / 不能跑；没有真机时由我们启动声明的模拟器）；legacy-capture 在包内装机、走冻结动作把界面写成参考记录，走不成确定性动作的界面由声明的 navigator 走到后再按选择器捕获；浏览器按同一滚动契约捕获，web / 鸿蒙存量的 UI 树从运行时索引派生；规划步骤带 capture_due，无法捕获时在冻结前记录原因和证据；Android 目标装 APK、web 目标以页面声明的构建哈希进入同一视觉对齐；测试结果带截图 / 录屏证据 | [项目上下文](skills/migration-protocol/references/project-context.md#存量预览)、[视觉执行](skills/migration-protocol/references/visual-execution.md) | [项目上下文](skills/migration-protocol/references/project-context.md#用户参考媒体)、[UI 保真](skills/migration-protocol/references/ui-fidelity.md) |
| 上下文就绪 | 规划与审计者随操作登记预检，coding 与无待复测的审计由 Ledger 机械预检；worker 的 building/testing 从 Ledger 骨架起笔，ready 才开工；worker 只读执行所需 | [上下文就绪](skills/migration-protocol/references/context-readiness.md) |
| 构建、单测、静态审查、自动化、视觉 | build → unit → static → automation → visual；自动化缺失仅 Yellow；PATH 可声明 record_video，录屏随结果入 Ledger；Android/Harmony 走内置 Harmony Main，web 走内置 web Main（冻结的确定性步骤与 DOM 谓词或用户截图，plan 时按形状校验，真实浏览器执行、每步截图，表单动作与谓词齐全，谓词有界重读、多次尝试识别 flaky），适配器按 PATH 平台自动选取，项目适配器只需写断言 | [构建与自动化](skills/migration-protocol/references/build-automation.md)、[UI 保真](skills/migration-protocol/references/ui-fidelity.md) |
| 资源与参数搬运 | 文件资源按清单原样复制、按 accessor 引用；布局、图层与代码里的取值记成参数表，生成到目标后按键取用；Spec 只写例外，验收比对字节与引用；登记 UI/Resource 分配前对约定定论（声明，或写明目标不接收的原因） | [搬运](skills/migration-protocol/references/resource-transfer.md#总则) |
| 图片与图标对齐 | 图片来源逐条记录并入资源闭包；树上每处静态图片都上屏核对或带证据豁免：存量资源离线渲染为参考，目标屏幕节点与之比较（另有文本与节点检查），结论由 Ledger 重算；手工替换的图片须测量或获批偏差 | [图片与图标对齐](skills/migration-protocol/references/ui-fidelity.md#图片与图标对齐) |
| 四维切片与语义模型 | UI → Logic → Adhesive → Resource 逐层映射到 TASK/PATH/ASSERT | [四维](skills/migration-protocol/references/dimension-slicing.md)、[语义抽取](skills/migration-protocol/references/semantic-extraction.md) |
| 阻塞感知与恢复 | 局部校验、invalidate 出口、进度信号；watchdog 只观察 | [恢复与进度](skills/migration-protocol/references/progress-recovery.md)、[watchdog](skills/migration-protocol/references/watchdog.md) |
| 埋点 | 有则迁移，无则有据 N/A 正常推进 | [埋点](skills/migration-protocol/references/telemetry.md) |
| 留存与资产根 | `.sdd-migration`、`.sdd-runs`、`openspec` 并列 | [留存文件系统](skills/migration-protocol/references/storage-layout.md) |

## 单个功能模块入口

默认 [global-input.json](template/global-input.json) 的 `entry_mode=project` 覆盖完整项目；`single-module` 选择一个根功能。两种模式均由 GO/MO 按原子性决定是否继续拆 scope，原子根直接进入叶子规划。

单模块只是同一入口的两个参数：`entry_mode=single-module` 与 `module_name`（如“用户登录”）。沿用当前项目输入，用户无需提供模块描述、scope、模块代码路径、SPEC 或 Testing list；由 GO 识别业务范围并分配上游 CASE，MO 按需细分，叶子组织实施规范和测试路径。[single-module-input.json](template/single-module-input.json) 仅展示这两个参数，不是独立运行资料包。

完整流程：选择项目或根功能（声明存量怎样跑，可附存量截图/录屏与目标预期） → **GO/父 MO 划 scope/CASE 并审查 registry 覆盖** → **子 MO 拆 tasks、四维、形成可执行 SPEC 和测试路径** → **MO 审核冻结** → **Implementer、Test-Runner build/automation、Fixer/复测** → **父节点汇总，统一宿主 Auditor**。独立 design 按需协助；执行中发现遗漏/fidelity 偏差，在同 Run 更新受影响 SPEC 和已有代码，只越 scope 才上溯。历史只留痕，每叶子执行唯一当前 SPEC。父子 MO 都读全局代码、架构、知识与分工，见[父子 MO 协议](skills/migration-protocol/references/module-decomposition.md)。

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
| 2026-11-14 | 并行名额保留期间可先准备冻结 TASK 的资源，追加复用来源时独立视觉 PATH 可收尾，GLOBAL 单条配置缺口局部报告，首次 Build／Unit 记录可核验指纹，纯设备变更复用有效代码评审。 |
| 2026-11-14 | 保留编码会话轮换名额直到新会话派发，父 MO 重切期间独立视觉继续收尾，设备变更影响的内置 GLOBAL PATH 进入下一波集成，有效 Gradle 回执跨增量 CR 复用。 |
| 2026-11-14 | 编码会话轮换优先交付。追加复用来源时未提交 Plan 的消费者继续规划。内置 GLOBAL PATH 的设备修订与审计按平台复用，部分 Gradle 构建补跑后保留输入未变的回执。 |
| 2026-11-13 | Fixer 优先交付宿主。Run 级提供方回溯允许输入独立的视觉派发收尾。设备切换可保留有跨冻结证明的 Green，范围外同输入的 GLOBAL Green 入账保留有效评审。 |
| 2026-11-12 | 视觉分批可回到补资产 CR，资源准备在名额满时也能排队并唤醒调度。设备切换和制品失效按 PATH 收窄。Harmony 多真机覆盖独立保留，取证核对系统与窗口配置、原生窗口时序和实际资源标识。 |
| 2026-11-12 | 待同步派发释放 worker 名额，按就绪 PATH 验证，独立草案保留，调度结束再发布投影。Harmony 模拟器和真机分项记账，真机核对构建、主屏窗口和实际资源档位。 |
| 2026-11-12 | 独立派发先返回，资源同步在原 fence 下恢复。来源评审保留同输入的 Green 进展，受管 PATH 按实际产物重验。Harmony 用应用探针、原生 PNG 和前后视图树证明限定值与选档，按平台披露证据。 |
| 2026-11-12 | 资源同步冲突保留原文件并局部报告，审计只重验失效构建 PATH。追加复用来源时缩小评审与等待范围。图片完整档位与 XML 限定值绑定实测配置和视觉回执。 |
| 2026-11-12 | 审计按 PATH 输入复测并累计证据。分批构建统一依赖守卫，Run 修订等待时活动波次可以先提交。资源按 TASK 同步并用已验收哈希更新，复制清单记录密度变体和视觉验证范围。 |
| 2026-11-12 | 依赖恢复核对 PATH 的提供方输入。受限视觉波次按构建产物及依赖闭包复用，过期任务可回收。派生资源按内容归档，已验收 APK/HAP 的视觉验证可与独立编码并行。 |
| 2026-11-12 | 局部回溯期间，已冻结的独立叶子沿用有效覆盖派发。设备缺口与冻结 PATH 分开统计，平台专题和模板按本次 PATH 按需列出。 |
| 2026-11-12 | 机械验证从同一派发的完整回执恢复。就绪 Spec-Designer 优先交付。补资产 CR 保留有效的提供方代码依赖。技术修订可沿用 worker 收尾前的有效评审。 |
| 2026-11-12 | 依赖变更保留消费者人工阻塞。独立叶子的 Implementer 先收到派发。仅变更设备输入时按 PATH 复测，保留有效回执。 |
| 2026-11-11 | 全局修订按明确列出的根模块处理重分配。只补执行资产的重冻保留已验收实现；纯四维 ID 补录期间，下游沿用仍有效的提供方证据与预检。 |
| 2026-11-11 | 审计发现按 SPEC 与范围分别回溯，接受重冻或分配审核时结案。unit 缺资产时先跑就绪 build，自动化先派发就绪 PATH。纯四维 ID 补录重冻可复用仍有效的 build/unit 回执。 |
| 2026-11-11 | 欠项按所需阶段处理，测试资产在对应 PATH 派发前补齐，纯四维条目 ID 引用缺口可留到 DoD。重开规划后的新计划与上一份对比，待审重分配保留首次请求。 |
| 2026-11-11 | 自动化断言失败且根因未确认时先诊断，首冻须覆盖 SPEC 的 Scenario 断言。宿主行携带提交修订号，报告分别展示完整执行与全部通过。 |
| 2026-11-11 | 宿主循环交付模型等级并在安全交接点输出会话轮换，推理专题按需取单节。API/URL 断言、图像资源策略、布局参数和可预览存量基线或证据缺口在首冻前结清；有缺口时返回叶子规划。 |
| 2026-10-29 | 静态审查随模型执行的自动化同派：run 没有声明驱动某叶子自动化的命令或适配器时，Ledger 把静态闭合与这些功能 PATH 放进同一次 automation 派发，静态在前、非 Green 即停，一次预检、一次提交；此前静态审查单独派发、自动化再派一次，同一份代码两次模型轮次，每次修复后又是两次。声明了适配器的 run 静态审查仍单独派发；漏掉静态 PATH 的 automation 派发被拒。连续演练 11 → 9 次模型轮次（Test-Runner 4 → 2），界面叶子演练 13 → 11，首版失败演练 Test-Runner 6 → 3，各修复演练 Test-Runner 2 → 1。静态闭合等调用方代码（awaiting-assembly）时，本模块的自动化先跑，调用方到位后静态闭合单独派发；此前自动化跟着静态一起等，上游要等依赖方写完代码才知道自身行为是否成立。另更正上一行的轮次：界面叶子演练当时是 15 → 13，不是 16 → 14 |
| 2026-10-28 | 首版欠项在静态审查前补齐：构建与单测已过、只剩静态审查而计划仍欠 Ledger 记的欠项时，Ledger 先开修订，静态审查只在修订后的计划上做一次；此前首版先做一次静态审查、跑完自动化再被重开，修订后又审一次。修订只补文本，代码与 Green 保留。界面叶子演练 16 → 14 次模型轮次（Test-Runner 6 → 4），没有欠项的 run 不变。经验效果按下发时点算：下发记录按模块记首次下发时间，只有其后、在已下发模块中的同一规则拒绝才算复发，此前下发前的拒绝或从未拿到该经验的叶子的拒绝也会把它排到后面 |
| 2026-10-28 | 经验按规则计：拒绝消息遮去 ID、路径、文件名、hash 与数字后作为规则，次数、跨 run 合并与是否复发都按规则算；此前约九分之一的拒绝消息带具体值，同一规则换个用例或文件就从头计数、攒不成经验，下一 run 也认不出它复发，效果排序会误把它当成有效。同一 run 内，其他叶子在同一操作 × 角色被拒的规则即时出现在后续卡片上（修复经验之后、跨 run 经验之前）。包反馈列出改进候选：两个 run 以上或一次满三次被拒的规则附所指小节、每个 run 都出现的缺口族、复发两个 run 的经验；done 行给出报告路径，仍只报告、不改规则 |
| 2026-10-28 | 经验闭环（自我改进）：反复被拒的门禁由 Ledger 从拒绝记录与日志填齐全部抽象字段，下一 run 按操作 × 角色优先下发给同一步（所引小节已不在当前包则不下发），此前这类观察缺字段、在下一 run 读取前就被丢弃；下发过的经验记入 run，采集时看同因拒绝是否复发，复发两个 run 的排后、未复发的排前，从不删除；每次采集在经验库旁（包外）写 package-feedback.json/.md，按包提交统计拒绝、缺口族、规则债、切分、每叶模型轮次、最大卡片、经验效果与复盘情况，只报告、不改规则；收尾复盘由 Ledger 预填观察写骨架、派给统一 Auditor（卡片 14 KB），可交 nothing_to_abstract 与理由，交付不等它，未交的在报告中记为欠账。脚本演练只证明经验送达，效果要看真实 run 与这份报告的数据 |
| 2026-10-28 | prepare 生成的 run 用项目声明的适配器：init 输入未写 test_adapter 时取快照里的（目标预览与鸿蒙沙箱随之推出），写了不一致即拒绝；此前只认输入，漏写就当没有适配器，构建、资源、预算与门禁却都与快照核对。项目声明了适配器的 run，功能路径由 advance 代跑：两叶子的真实配置 run 走到结论 9 次模型轮次（Test-Runner 只剩各叶子的静态审查），漏掉适配器时为 11 次。视觉链路（界面 run 以全绿收尾）按建议留给 X4 真实 run |
| 2026-10-28 | 界面叶子从登记走到结论：存量不能运行、目标没有设备的界面 run 在 prepare 生成的配置下走通（15 次模型轮次：GO 1、MO 1、Spec-Designer 4、Implementer 2、Test-Runner 6、Auditor 1，以带未验证用例收尾）。走这一遍补上的缺口：Ledger 起草切分时按父 UI 条目所含用例代填 anchor_ui；建好测好但首版计划留有欠项（界面闭包、文档里的条目 ID）的叶子此前无人接手、run 停住，现在由 Ledger 开 change 补齐，修订只补文本（任务、PATH、测试资产不变）时 Ledger 写任务独立证明，代码与 Green 保留，只重跑构建与静态审查；重写文件后字节相同的 PATH 与测试资产在重验中视为同一份；实现提交引用无追溯行的条目时按名拒绝而不是 KeyError。资源搬运交给 Ledger：计划未写复制清单与参数表时 Ledger 派生绑定，派发 coder 时 advance 以其名义执行 resource-sync，图片与参数文件在编码前已到目标 |
| 2026-10-28 | 并行预算管住叶子规划：drive 只在占用名额的叶子（有 worker 在跑，或已交出的模型步骤尚未推进）少于 max_parallel_modules 时交出新叶子的行，空出名额再按提供方优先交给后面的叶子，tick 行计 modules_waiting；此前预算只限住 Ledger 派发的 worker，七个叶子同一 tick 拿到七行规划。按 tick 启动全部行的宿主把七个叶子从切分走到结论用 11 个 tick，任一 tick 至多五个叶子在做。只给作者要写的模板：Ledger 代写预检的步骤不再附预检模板，登记根模块不再附全局覆盖模板（prepare 生成的 run 里 GO 登记步 9 份 → 7 份，15.4 → 13.8 KB）。已核实跨 run 经验：一个 run 里已验证的修复在审计结论后自动入项目经验库，同项目下一个 run 的快照带上，相似叶子检索得到 |
| 2026-10-28 | 统一代码审查只留判断：改动清单的测试映射（每条 PATH 的运行来源、回归选择、执行回执与非 Green 根因）由 Ledger 填；prepare 记下目标所在提交，目标是 Git 检出时每个文件的新增/修改、修改前路径与 sha、行段、按模块固化的 diff 及起点/当前候选也由 Ledger 按 git diff 写出，审查报告的 diff_refs 指向模块 diff。Auditor 一轮要填的标记：30 个叶子 1126 → 404（2 / 10 个叶子 90 → 40、386 → 144），骨架 121.2 → 127.4 KB；非 Git 目标为 586。标记数随叶子增长作为报告数记录，超出只告警 |
| 2026-10-28 | 叶子并行编码，构建在无人写入时：同一构建命令的叶子可同时编码（各写各的文件），该单元的构建、单测、静态审查与设备路径只在无人写入时派发，写入也不在其构建时开始；此前第二个写入者被拒，单构建命令的目标逐个编码，而一个叶子的构建却可在另一叶子写入同一单元时派发。波次集成与审计复测先派发给独立 Test-Runner、预检在派发内提交，命令冻结或适配器驱动时预检与执行都由 Ledger 完成，Auditor 的派发预检也由 Ledger 写；此前这些只在关闭预检时机械，prepare 生成的 run 里每个波次与审计复测要 GO 一轮，波次集成的预检在其他叶子未收尾时被拒，审计有全局路径要复测时还会停在无人收到的 Auditor 预检上。Fixer 的预检与 coder 一样由 Ledger 在派发时写（Fixer 自报 blocked 退回并退还轮次），running 行交给 coder 与 Fixer 的卡不再带预检规则（14280 → 11900、14054 → 11674 字节） |
| 2026-10-28 | 回溯与收尾在宿主循环里走得通：统一审计把 SPEC 缺口回溯给叶子后，叶子的下一步直接是带 resolves 的 change（审计已确认根因时由 Ledger 提交，范围缺口给 realloc-request）；此前该叶子没有任何操作，宿主只收到两条信号，run 停住。叶子修订后，回溯的发现不再挡住复审。修订与冻结计划按引用内容比较，重写文件后只新增 PATH 的计划仍由 Ledger 代审。run 到终点时 drive 输出 done 行（质量、原因、报告，未验证收尾时带缺测用例），宿主停止并请用户授权交付；此前终点没有任何行。三种修复都在 prepare 生成的配置（预检、静态审查、单测全开）下演练：审查路由给负责叶子的发现 5 次模型轮次，审计回溯的 SPEC 缺口 6 次，自动化发现的保真缺口在该叶子 5 次，都没有编排者轮次；演练按 drive 的方式推进到无可推进为止 |
| 2026-10-28 | 修复路径只留判断：统一审计送回的问题自带路由时（代码审查 finding 写了 route，或遗留失败的根因已确认并指名模块），收集、路由、审核、派修复、复测，以及复测全绿后的裁决都由 Ledger 机械提交；修复后的复审只看改动过的模块；最终独立复测全绿且审查无发现时，结论由 Ledger 代 Auditor 提交。一个跨模块缺陷从交接到结论由 14 次模型轮次降到 6 次（Auditor 2、Fixer 1、Test-Runner 3）。诊断确认的 SPEC 缺口由 Ledger 开 change；编码后只新增 TASK/PATH 的修订由 Ledger 记事实并代审，改已冻结内容仍由 MO 评审；一轮规划缺口修复只剩诊断、规划、编码、复测 4 次（少 MO 2 次）。同一 run 内一个叶子已验证可复用的修复，作为 run-fix 经验推给其他叶子的执行角色；经验与切片技能随 drive 交出的阅读卡送达（此前只在步骤视图里，宿主照 drive 行启动的角色看不到） |
| 2026-10-28 | 一次 run 从登记连续走到审计结论：根模块登记后 Ledger 写覆盖（需预检时连同功能归属）、起草切分并在 MO 确认后接受，两个叶子规划、编码、测试到审计结论，共 11 次模型轮次（GO 1、MO 1、Spec-Designer 2、Implementer 2、Test-Runner 4、Auditor 1），取代拼算的约 11；走这一遍查出三处让真实 run 退回 GO 的缺口并由 Ledger 补齐：根模块有排除项时切出的叶子分析未带排除项、行为契约下切分缺 case_acceptance、需预检时登记起草的覆盖缺功能归属；宿主冒烟只以命令执行 `drive.py` 与 `ledger.py`，从登记走到结论；同一信号只印一次，tick 行计 signals_held；PATH 的默认字段与准备方式不写时由 Ledger 补（准备证据取冻结测试资产或命令选择依据），骨架每例少约 0.5 KB，作者不再逐条写证据；确认起草切分的 MO 卡只常驻拆分总则，手工切分规则按需读 |
| 2026-10-28 | 宿主照命令就走 drive 循环：`/sdd-run`、`/sdd-resume` 改为反复执行 `drive.py`、按行启动或接续角色，不再读游标、逐模块 advance；drive 行覆盖全部游标（同 Run 修订、来源变更、宿主自交步骤、带所问内容的待人工行、停滞 / 规划超时 / 被拒请求 / 待复盘信号）；只改上溯叶子自身且不挪用例的重切由 Ledger 接受；演练实测：从登记到叶子开始规划只需 GO 1、MO 1，范围偏差只重做提出的叶子（另一叶子版本不变），回溯只需叶子 MO 1、父 MO 1 |
| 2026-10-28 | 照抄的判断交给 Ledger：登记已说明每条用例唯一持有者与需求范围（需预检的 run 根模块带完整功能清单）时，全局覆盖由 Ledger 起草；没有可复测项且 Auditor 的代码审查无发现时，审计结论取自该审查，不再单独派 Auditor；`drive.py` 的派发行带实例与可接续的会话（如 Fixer 接 Implementer 会话），接续时卡片只含未读小节，已派的 worker 行也带卡片；全流程演练加入首版失败、修复、复测的一轮（全绿 13 次模型轮次、带一轮修复 16 次，单轮最大卡 19.6 KB） |
| 2026-10-28 | 断言失败直接交 Fixer 自行诊断：本模块功能/单测 PATH 的断言失败（与写范围内的构建报错一样）由 Ledger 写诊断（期望与实际、步骤轨迹），advance 接受诊断并派 Fixer，Fixer 步骤带 failed_assertions、自行定位根因写入 fix_note；视觉对齐、Yellow、代码外根因与审计轮仍由 Diagnostician 独立诊断；一次断言 Red 的修复从诊断 + 修复两轮降到修复一轮 |
| 2026-10-28 | 判断只留给需要判断的地方：无人提问的计划由 Ledger 记评审并冻结，MO 只在已有代码后改计划、门禁不过、有阻塞 issue 或作者在 plan.review_questions 提问时评审；计划卡只带作者要写的内容（24.2 → 19.6 KB），由 Ledger 补全或执行的规则在被拒时按指引取；`drive.py` 一条命令推进全部模块与全局的机械步，只交回待派、运行中、待人工各一行 JSON，无可派时 tail 事件日志等待；派发已做代码审查的 Auditor、适配器驱动的波次集成由 `advance_run` 完成；全流程演练按角色报告模型轮次（两叶子到审计结论共 14 次，单轮最大卡 20.5 KB） |
| 2026-10-28 | 模型只做需要判断的事：命令经 `run_command.py` 执行，只交回退出码与失败时从日志 grep 出的报错定位（failures.json），日志按需 grep、不整读；构建报错全在写范围内时 Ledger 直接写诊断并派 Fixer，定位就是 Fixer 的输入；确认的代码缺陷转 Fixer、提供方完成后的依赖放行与恢复、审计延期、缺测收尾由 `advance` 提交；声明了适配器或内置 Main 的自动化也由 advance 代跑，静态审查在 build/unit 通过后单独派发；协议文件不再限总量，只限加载进模型的内容（阅读卡、单次 show 一节）；每叶模型轮次只报告、不卡测试（声明适配器的叶子 3 次、未声明 4 次），迁移报告按模块列出 |
| 2026-10-27 | 叶子少走模型轮次：作者编译通过的实现、每条 PATH 为 Green 或确定 Red 的测试结果由 `ledger.py advance` 机械接受，确定 Red 直接进诊断；所派 PATH 全有冻结命令（build、unit、进程内功能测试）时 Ledger 机械预检、advance 以该 worker 名义按序执行并提交，同命令的 unit 只跑一次；演练测试把每叶模型轮次卡成棘轮（带设备自动化的叶子 6 → 4） |
| 2026-10-27 | 父层只确认切在哪里，首版先跑：首次切分可不全覆盖父模块（漏掉的记为父的 COVER 欠项，孩子首版收尾后补齐）；孩子的四维分析与行为评审由 Ledger 切出；与 Ledger 起草一致的拆分当场接受，全局覆盖自动沿用；28 处规划期完整性检查改为欠项 |
| 2026-10-27 | 让 run 动起来、停了能接上：首版骨架每条 CASE 一个场景并从功能清单预填，可后补部分记 debt；首版计划限时并标出规划期原型，拿不准的库写成 spike 任务；定时检查由人安装，`handover` 写接手说明；run revision 可带 package_sha 改钉新规则；intake 增问迁移范围与依赖授权；`split_draft.py` 起草切分 |
| 2026-10-21 | 减少拒绝与往返：手续问题放行并计数，Ledger 已有的事实由 Ledger 代填，被拒请求附同一请求的其余问题（`further`）且任意请求可 `preview --request`；构建跟随 PATH 平台、目标工程基线失败走审计延期、Gradle 缓存默认预热；冻结测试源须能失败、可落在写范围外、缺陷走 change；小根只确认原子叶、横切功能随主流程叶子；依赖方并行规划，watchdog 报宿主空闲；存量按 prepare 时的提交冻结，声明平台无适配器时用内置 Main |
| 2026-10-20 | 无需判断的步骤不占模型轮次：评审或决定已记录后的 freeze、DoD 守卫通过的 complete、子模块收尾后的父 module-summary 由游标标为机械，`ledger.py advance` 以 MO 身份提交，DoD 与汇总记录由 Ledger 写入 reports/；全绿叶子每次实现-测试的 MO 模型调用由 4 次降到 2 次，父模块汇总不再派模型 |
| 2026-10-20 | 被派发的角色只读阅读卡：卡已含红线与共享规则，AGENTS.md 只作宿主入口（8.7 KB → 4.0 KB，调用约定与专题索引移入宿主接入，设入口棘轮）；每步计量改为「常驻卡 + 按需小节」（最坏 51.2 KB），模板写到才取、单列计量；协议 457,300 |
| 2026-10-20 | 专题规则按需读取：阅读卡常驻红线、角色与本步规则，UI / 资源 / 复用 / 埋点 / 平台 Main 等专题小节按触发列为按需清单（名字、用途、大小），写到对应工件时用 reading.py show 读单节，拒绝提示指向同一小节；常驻卡最坏 29.1 KB（此前 51.2 KB），按需小节最坏 25.9 KB，一步全部可取 82.2 KB；步骤视图与卡文件带 read_when_writing 清单 |
| 2026-10-20 | 按需加载：卡与模板按声明的平台取（web Main / Harmony Main 与各自的 PATH、adapter 模板），整文件入卡改为按节（审计范围、代码审查、视觉执行），模板瘦身（语义模型 17 KB → 6 KB、四维分析 8 KB → 5.6 KB、提交模板 4 KB → 2.3 KB，工具产物与骨架已写的报告不再下发），角色与技能文本去重，Spec-Designer 常驻小节与规划模板再压一遍；每步「卡 + 模板」计量并设棘轮（最坏 82.2 KB，无触发步骤 29.5 KB + 13.5 KB）；目标 app_id / launch 随设备声明，visual PATH 预填完整；协议压缩至 458,800 |
| 2026-10-20 | web Main 补齐表单动作（select/check/uncheck/hover/scroll_to）与谓词（attribute/checked/enabled、count 的 at_least），重读中变化的观察记 unstable，适配器 attempts>1 时整条路径重跑、同断言混合结果记 flaky Yellow；鸿蒙存量的 UI 树与 web 一样从运行时索引派生；骨架为用户截图的 visual PATH 预填 visual_execution，`test_adapter.harmony_reference` 由 init 备好 Harmony sandbox；图与 README 同步三条声明与两个内置 Main；协议压缩至 462,500 |
| 2026-10-20 | 适配器随 PATH 平台自动选取，Test-Runner 预检由 Ledger 预填同一命令；目标预览随设备声明（serial/avd 或 url/viewport）由 init 写成运行环境文件；web PATH 在 plan 时按 web Main 的形状校验，web Main 走通 Ledger 黄金路径到 DoD，谓词有界重读、按 PATH 标志录像；欠项按族计数；鸿蒙存量可预览（hdc 装 HAP、启 ability，无真机时 boot.argv）；doctor 探测适配器；协议压缩至 464,000 |
| 2026-10-20 | 完备性欠账、一致性拒绝：十一族共 36 处冻结期完备性门禁改为叶子的欠项（首版继续，DoD 前结清），同时守一致性的门禁拆开后矛盾仍拒绝 |
| 2026-10-20 | 内置 web Main 与实跑收口：web PATH 以冻结的确定性步骤和 DOM 谓词/用户截图在真实浏览器里验收，回执绑定每步证据；项目适配器只写断言即可被验收；intake 第三问（目标资源约定）；拒绝提示覆盖 99%；浏览器、模拟器与 web Main 三份实跑冒烟，实跑暴露的装机与前台时序缺口已修；协议压缩至 465,500 |
| 2026-10-19 | 没有真机时启动模拟器：存量与目标声明可带 avd 或启动命令，设备不应答时 worker 启动 Android Studio 的 SDK 模拟器（或声明的命令）并等开机，启动留证、模拟器留给后续捕获 |
| 2026-10-19 | web 目标的浏览器预览：目标在浏览器里预览时不装机，宿主部署已接受构建并让页面声明其哈希，visual-install 与每次捕获重读核对；候选经共用观察器写 web-candidate 记录进入同一对齐链路；黄金路径补 web → web |
| 2026-10-19 | 预览需求确认与媒体兜底：init/update/prepare 返回待问用户的 open_statements（存量怎样跑、目标在哪验证），status 持续提示到声明为止；断言可引用用户截图作参考图进入功能 automation 的 Verify；PATH 可标注录屏时间段供诊断并列 |
| 2026-10-18 | 媒体、知识与目标现状：规划步骤带 media_due、持有媒体的叶子卡片带用户参考媒体小节；诊断/修复并列预期媒体与实际媒体；knowledge_paths 接受 wiki 目录，人工知识答复随经验库沉淀并在下次 run 自动并入；只读 target-scan 给目标画像候选证据 |
| 2026-10-18 | 存量捕获闭环：规划步骤带 capture_due、卡片带捕获小节；首版先跑——未捕获的界面与未引用的截图/预期是欠项不是门禁；宿主职责、doctor 探针、经验携带 legacy_preview 与每个操作的请求模板；三条存量→目标黄金路径端到端测试；协议去重压缩（棘轮 468,000），section 读取忽略代码块注释；agent 导航的存量捕获（navigator 走 snapshot 任务，未到达附 capture_gap 建议）；web 证据链（浏览器滚动、DOM 派生 UI 树、无源索引的 web 树校验） |
| 2026-10-17 | 存量预览与媒体取证：项目上下文声明存量 App 怎样跑（设备 / 模拟器 / 虚拟机 / 浏览器 / 不能跑），可执行性随声明、未捕获的界面写 capture_gap；包内 legacy-capture 装机、走冻结动作、把存量界面写成参考记录（adb 或 Playwright），参考与候选记录的判定各归一函数；内置运行时移植 snapshot/recording 任务类型并产出媒体回执；测试结果带截图 / 录屏引用，报告逐 PATH 列出，diagnose/Fixer 带非 Green 路径的媒体；Android 目标装 APK 并进入视觉对齐 |
| 2026-10-16 | 项目理解：目标画像（GO 逐功能记目标状态，脚手架只在缺外壳处，持有代码的叶子冻结时欠复用说明，报告列迁移前状态）；项目知识文档可查（knowledge-query project 模式），knowledge-need 交人以 kind=knowledge 决定补充并成为本 run 的知识文档；用户参考媒体（存量截图/录屏）随项目上下文固化并下发到持有叶子：截图作 user-reference 视觉基线（存量不可预览也有基线）、录屏作功能 PATH 的交互预期、骨架为每张截图起稿 visual PATH、未被 PATH 引用即欠项；target-expectation 取代存量基线、design 须引用、报告披露 |
| 2026-10-16 | 进程内功能测试代码化：automation PATH 带冻结命令与 unit_report 时按 JUnit 执行，每条断言指一个具名测试、逐断言给结果；骨架为无设备或非界面的 CASE 起稿 <Case>FlowTest，为有设备且绑定 UI 树的 CASE 起稿设备脚本（选择器取节点 id）作为 script 资产；报告分列脚本驱动的设备路径及其 flaky，作为推广前的对照。 |
| 2026-10-16 | 测试代码成为冻结资产：Logic 条目的单测源从 SPEC 写出（Ledger 按条目起稿骨架，每个 CASE 一个测试方法），作为 test-source 资产随计划冻结，记 target_path、required_test_ids、scenarios 与 symbols；Implementer 原样交付到 target_path，hash 不等即拒，改测试走 CR；execute_test 执行前核对文件并写回执；红→绿由作者自查对冻结测试留证。 |
| 2026-10-15 | 红线 4 分层：正式目标代码测试在代码被接受之后派发，作者自查不产生结果、不能代替正式测试；作者对任务的 unit PATH 自查两次（实现前失败、实现后通过），两份记录是该任务的 red 证据，报告按任务统计有证据 / 无 / 不适用，不设门禁；报告加规划占比（冻结 / 首次 Green）。issue 增 debt 类型，审计骨架预列。只改测试写法（步骤、参数、前置、措辞）而 PATH 身份与断言期望不变的 CR 由 MO 审核即可，Ledger 记事实。波次集成：global path 在持有其用例的叶子全部完成时即由独立 Test-Runner 执行，结果绑定 owner 代码基线，审计只重跑 owner 代码变动的路径，Red 路由给 owner 叶子。 |
| 2026-10-15 | 起步与执行侧骨架。run 固定 prepare 时的包提交（package_sha），新规则只约束新 run；Implementer 按 TASK 派发，path_ids 随任务；冻结只核起步门禁（范围/写锁/任务/PATH/四维追溯/六件套），保真欠项记 gap、DoD 前结清；Ledger 写叶子的计划集骨架（六件套、stage-plan、上游测试计划、复用计划）与执行侧报告骨架（Test-Runner 预检与静态审查、Auditor 清单与代码审查），留标记的提交被拒；coding 与无待复测的审计由 Ledger 机械预检；卡片只在设备/视觉/图片/资源适用时带 UI 保真节，角色文件去掉专题表；冻结同一命令的 unit PATH 一次执行、逐 PATH 归因；实现派发先列提交必备证据，冻结落点文件在交付内即视为 conformance；报告列首版耗时与被拒次数，TASK 行按模块缺口计缺路径，任务按层切记为事实。数据契约：复用的数据在取数与计算处对齐（来源/取数条件/派生字段/失效随维度→TASK→PATH）。运行产物不设体量上限，棘轮只约束包。 |
| 2026-10-14 | 切片标准与同源用例。叶子是功能树上的子业务流：页面是 TASK 不是叶，3–30 条 CASE，功能叶之间不重叠、并集覆盖父的功能，PATH 不取兄弟叶的证据；无用例时先读源码建功能树再派生用例，有用例时用例范围界定叶子；根登记时带功能清单，清单接受时记树形事实。一种版本学说：重新提交按当前规则全判，已接受工件只因漂移被拒。脚手架两阶段（骨架 TASK 接受且构建 Green 即放功能叶）；事实记录不欠任何人，步骤只列十条问题，常规规则随卡一次；provider 修订 SPEC 不再卡住需要其代码的叶子，依赖方按 provider 已接受代码规划；Ledger 能派生的指针自行填写；单版本改动过多的任务成为游标与审计可见的信号；包文件不作证据；独立模块评审并行派发；卡片按步列模板、按名取用；草稿与日志留在 scratch/；协议、运行指南、模板索引与命令文件去重压缩。 |
| 2026-10-13 | 叶子是一个界面及其背后各层，外壳是脚手架，只在目标缺外壳时设脚手架；不验收用例的切片是脚手架，切片成链不再要理由；测试设计归 Spec-Designer，取消编码前 design 派发；评审一次看全部失败门禁，叶子只固定自己的代码；一次请求记录或结清多个问题，计划/评审/结果回答的问题随之结清；run 未写入的输入引用不抄录，Ledger 为自报操作代写预检；provider 恢复后全部任务已接受的依赖方直接回到测试。 |
| 2026-10-11 | 首版先通过：评审默认通过并记录问题，计划一次判完；预览点名缺失的 run，Implementer 逐任务声明测试与代码的次序；绘制参数进入采集，被取代的 provider 计划记为 gap，恢复卡只说变化；根为每个孩子加的排除项随分配到达，不计入孩子边界；评审中的计划显示重提绑定什么；协议每条共享规则只说一次。 |
| 2026-10-10 | 叶子点名发起调用的文件并在冻结时核对；问题记录并随身携带，任务写完即测；切片按波次推进，审计回溯，保留已建成果；宿主可为每次执行预热冷 Gradle 主目录；修订只花它改动的代价，人决定边界一次。 |
| 2026-10-10 | 叶子补齐自己的资源闭包。参数表携带的取值（文案、尺寸、颜色等 values 条目）连同其语言等变体即算被资源闭包覆盖：它们由参数表物化到目标并按键取用，参数表在冻结时重算比对，不再要求逐条资源条目；图片仍由复制清单或条目覆盖。叶子的细化版可以把分配的一个资源条目细分为逐文件、逐绘制的条目：新条目以 detail_of 指明所细分的分配条目、编号以它为前缀，需求、用例与父条目不出其范围，分配的条目原样保留；其余维度仍不增删条目。细分条目按登记条目的规则判定，计划须像其他条目一样为它建立追溯。 |
| 2026-10-10 | 切片用自己的用例验证自己的条目。拆分时子条目挂本子模块持有的用例即可，不必取自所引父条目的用例；子条目的需求仍不得超出父条目。这样“验收用例的切片只持有它验收的用例”才能成立：资源、接线这类父条目在上层只挂了横切用例时，各行为切片用自己的行为用例承载它们，横切用例只归一个切片。父条目的用例若由引用它的孩子持有，仍须挂在该孩子引用它的子条目上。 |
| 2026-10-10 | 界面采集按类限定范围。analyze-ui 的入口写成 `文件#类名` 时，只采集该类（含其内部声明）源码段内的资源引用、使用点、参数与呈现变更，行号保持原文件行号，源索引记录所取的类与行段；同一文件可同时指定多个类，未指定类的入口仍采集整个文件；文件里没有声明该类时记为未解析且不采集。一个源文件含多屏时，各叶子只为自己那一屏写 UI 树，校验规则不变。类也可以用限定名（包名.类名）定位文件。工具产出的索引可以作为证据引用：被引用的 JSON 里路径不是绝对路径的“路径 + 摘要”对象是该文档对文件的记录，不当作本 run 的证据引用，既不核对也不归档；请求自身的引用与文档内的绝对路径引用照旧核对。 |
| 2026-10-09 | 叶子细化自己的分析。叶子计划的 dimension_analysis_ref 可以是它据分配分析写出的细化版：分配所写的一切原样保留（Ledger 逐项比对：对象可增字段，留空的字段可填，证据与条件断言可追加，条目、条件与维度按编号对应且不增删不换序），界面证据、参数表、复制清单与资源精确策略由叶子写在其中；细化版在计划提交时按登记分析的规则判定，分配本身不变。此后该叶子的冻结门禁、worker 必读输入与报告读取细化版；首次冻结按所绑定的那份分析判定。带界面的叶子的计划步重新带语义模型模板，分析模板不带（从分配文件起稿）。规划中的叶子不被其 provider 待处理的上溯请求挡住，派发时才等待。 |
| 2026-10-09 | 先动起来、再调整。修订只触及引用者：根分析修订后，Ledger 按孩子分析所引用的父条目与接口契约比较新旧两版（只换证据引用不算改），引用到被改内容的孩子须重规划或修订，其余孩子原样沿用、不被打回也不等待；父 MO 的再拆分只重写游标 affected_children 列出的孩子，没有孩子受影响时不再拆分；新增的父条目须有叶子承接；孩子沿用登记时所写的父排除项，现行排除项随父分配到达其规划者。依赖方不随 provider 重规划：只依赖被打回叶子的叶子保留计划继续推进，已有代码的等 provider 后复验。一条用例一个持有者：验收用例的切片只持有它验收的用例，为别的切片供给能力写进对方的 provider_inputs，各切片都须满足的约束写成各自条目的保真条件；只有不验收任何用例的支撑切片持有它所服务切片的用例；父条目的用例由持有它并引用该条目的孩子承载。接口适配只决定一次：人工可用 kind=api-adaptation 的 run 级决定逐契约命名替代方案，或批准父批量信封，此后持有这些契约的叶子凭 MO 评审冻结；冻结步骤在适配未决时标明需要人并列出本 run 全部未决适配。并行预算：max_parallel_modules 默认 5，游标 module_rounds.start_modules 列出当前应推进的叶子（持有 worker 的在先，其余 provider 优先）。叶子绑定条件断言：分配里适用的保真条件由叶子计划在该条目的 dimension_trace.condition_assertions 绑定自己的断言，报告据此判定。 |
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
