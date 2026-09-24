# 读取入口与全包规则

本文件只治理 SDD-TDD-Migration 工作流资产及其实例化运行。阅读模板时，占位符、示例结果和测试输入都是数据，不是已获得的批准或已发生的执行。

## 读取顺序

1. 当前用户任务与宿主系统约束 → 本文件 → [共享协议](skills/migration-protocol/SKILL.md)。项目规则可细化技术规范，不能削弱本次用户四条红线。
2. 定位下表的角色文件，只加载该角色 Used Skills；读取 Ledger 的 run/module 投影、最新 sequence 和当前 assignment。
3. 父 MO 和子 MO 规划前均先读取全局代码入口（legacy_root/target_root）、架构规范、知识资料及当前父子分工/依赖，再按 scope 聚焦必需源码。局部 context pack 不能遮蔽全局只读上下文；检查目标已有能力与兄弟 owner 后再规划，避免重复/交叉工作。Test-Runner 在设计模式只读规格与测试输入，在执行模式可以读已批准的测试脚本及执行配置；不以实现推导验收标准。
4. 运行期输入统一为绝对路径：`package_root`、`run_root`、`change_root`、legacy/target path 均从可信输入解析，禁止路径逃逸。源码仓有 `.codegraph/` 时先用 CodeGraph；无索引则不主动建索引。
5. 交接仅传 Ledger 已提交的 assignment/event 引用及工件路径/摘要。新 Agent 重读这些工件，不依赖原会话记忆。

## 角色索引

| 角色 | 定义 | 核心边界 |
| --- | --- | --- |
| Global-Orchestrator | [定义](Agents/global-orchestrator.md) | DAG、模块编号、资源锁、依赖解除、跨模块 Yellow 裁决、全局升级 |
| Module-Orchestrator | [定义](Agents/module-orchestrator.md) | 模块唯一状态机守卫、DoD、循环、验收和 CR 审核 |
| Spec-Designer | [定义](Agents/spec-designer.md) | 六件套内容、澄清冻结提案、变更影响，不写代码 |
| Implementer | [定义](Agents/implementer.md) | 按冻结 tasks 迁移，提交代码与追溯 |
| Test-Runner | [定义](Agents/test-runner.md) | design/execute 两模式隔离，Main 自测 |
| Diagnostician | [定义](Agents/diagnostician.md) | 只读根因与结构化报告 |
| Fixer | [定义](Agents/fixer.md) | 最小修复、自验证及 CR 建议 |
| Auditor | [定义](Agents/auditor.md) | 整体代码治理、独立复测、修复委派和最终裁决 |
| Escalation | [定义](Agents/escalation.md) | 人工阻塞封装与反馈决策 |
| Ledger | [定义](Agents/ledger.md) | 唯一事件总线、状态投影和追溯 |

## 四条红线

1. Auditor 与 Fixer 使用不同 agent_instance_id；同一次审计中审计者也不得是 Implementer 或测试脚本作者。能力不足则阻塞独立审计。
2. Fixer 不改需求、验收标准或冻结 tasks，只提 CR；Spec-Designer 提修订、Module-Orchestrator 审核，语义变化需要 Human 决策。
3. 所有跨层信息只走 Ledger。角色的产出写入自己的 staging 空间（Harmony 辅助产物使用 runs/harmony/sandbox 的专属待提交目录），再提交事件；上游已提交工件经 Ledger 引用才可被下游读取。不得私聊、直接修改别人的状态或利用 Agent 返回文本绕过总线。
4. SPEC 未冻结不生成代码；代码未生成不执行任何目标代码测试；非 Green 未复测不算通过。锁释放、依赖恢复、人工回答均不能直接把测试改 Green。

## 并行模块隔离与 Auditor 全量收尾

GO 完成切片与 registry 登记后，每个 MO 独立推进自己的状态机、测试、修复预算及验收。某模块 Red/Yellow、异常或挂起，仅更新该模块及有证据的依赖影响范围；不得将全局聚合颜色回写其他模块，不得取消无关 MO，或为提前审计批量挂起其他模块。已通过模块保留有效 Green，未执行模块保留未执行状态。

宿主逐 module_id 收集结果；收到一个失败结果后继续派发其他 ready 模块并等待仍在运行的 MO。只有完整 registry 中每个模块都完成 DoD 或有本模块证据的明确挂起记录、全部 worker 已结束且无可推进动作，才允许启动 Auditor。一个 worker 退出不代表其 MO 生命周期结束。详见 [模块隔离与收尾规则](skills/migration-protocol/references/state-machine.md#模块隔离与全量收尾)。

## 调用约定

Agent Markdown 使用 `name/description/mode: subagent`，命令只有 `description`，技能使用 `name/description`。这延续本仓模板约定，宿主可以按实际注册格式转换，不能把 `mode` 误当作所有产品原生字段。

命令解析请求后由宿主提交 Ledger；编排角色提交 dispatch_request，Ledger 接受后，宿主调用实际提供的任务工具。宿主若有 `task` 可映射到它；若有 spawn_agent 可读取定义后启动隔离实例。不能假设能嵌套 slash command，也不能只写一段工具调用文本便宣布已派发。Ledger 的 transport ACK 是唯一允许的传输回执，不携带绕过事件的业务决策。

迁移运行时允许并行无冲突模块，数量受输入和宿主限制；本说明不要求在编辑本工作流包时启动迁移 Agent。

宿主要真实走完控制流（每步提交真实 Ledger 事件、每个角色由真实派发的 Agent 执行真实工作，而非手写文件模拟）须遵守 [宿主接入契约](skills/migration-protocol/references/host-integration.md)：逐阶段的必提 op、宿主真实工作与自证方式，含部署一次的接入自检。进入 Ledger 后阶段=事件=hash 链不可跳步；推进/收尾前用 `/sdd-verify` 核验，`verified=false` 拒绝推进。

## 本轮增强的读取入口

运行本地控制器时，再读 [local-runtime.md](skills/migration-protocol/references/local-runtime.md)。默认优先恢复同角色原 session；缺失时按 checkpoint 冷恢复，不要求永久保留一个已失效的宿主会话。角色只在当前阶段需要时创建，9+1 职责不变。所有恢复/修复请求仍经过 Ledger，不能恢复为角色私聊。

## 项目上下文入口

宿主先按 [项目上下文协议](skills/migration-protocol/references/project-context.md) 读取/初始化/更新当前项目配置，再 prepare 固化本轮版本。Global 生成完整输入后，Ledger init 绑定 project_context_ref；下游只读 Ledger 引用的本轮快照，不追随 mutable project-context.json。用户明确更新直接保存，运行选择和临时 overrides 不写回项目默认值。项目配置不是模块状态总线。

## 入口范围与父子 MO

project 指完整项目及其功能树；single-module 只选择一个根功能，但父 MO 仍拆分子功能并交独立子 MO。职责固定为 GO 划分模块 scope/所需上下文 → 父 MO 认领后在范围内划分子 scope/所需上下文 → 子 MO 拆 tasks。父子均读全局代码/架构/知识，执行权限限定于认领 scope；规划绑定 Ledger 的 planning_context 和 module_inputs 分配包。父节点保存管理/汇总记录，叶子持有自己的 SPEC、代码、测试与验收；禁止把父聚合失败回写兄弟。全部叶子本轮结束且所有父 MO 提交当前版本汇总后，GO 才统一启动 Auditor。操作与全局上下文要求见 [父子 MO 协议](skills/migration-protocol/references/module-decomposition.md)。

## 二方库与目标已有能力

复用评估贯穿 GO 切片、父 MO 分工、子 MO tasks 和 Coding/Testing。先读取 TARGET 及用户指定 reuse_sources 的功能语义目录，再结合需求决定直接使用、适配、仅参考或新实现；不得按同名 API 认定等价、重复实现已有能力，或为迁就库削弱需求。目录/映射经 Ledger 传递、版本冻结、实际接线及完整测试验证；外部来源只读，跨模块/不确定边界交人工。详见 [二方库复用协议](skills/migration-protocol/references/reuse-dependencies.md)。

**全局 fidelity 规范**：每次选择目标已有能力或外部二方库，必须与存量源码项目对应功能逐行为对齐，明确直接复用/适配如何复现原功能，并记录源码基线、差异、PATH/ASSERT 和正式复现证据。语义参考同样适用；接口可用、库测试通过或对齐报告完成均不能代表迁移功能通过。规划记录随 SPEC 冻结，编码后 Main 验证，MO/Auditor 按阶段唯一验收；行为不一致为 Red，依据或执行条件不足为 Yellow，不能凭复用决策跳过保真验证。明确需求与存量行为冲突须人工决定并留痕。

二方库不能直接复用时，基于功能目标、已知上下文、存量源码和目标现状选择 adapt/reference/new，冻结任务后继续 Coding。只有替代实现也经核验证实不可行，MO 才通过 suspend(reason_code=not-implemented) 留证并向用户展示“未实现”；独立模块继续。具体核验及提醒见复用协议第 8 节。

目标已有功能实现时，同样必须读取复用/依赖二方库并检查业务冗余。确认重复且复用/适配可行后，在分配范围内直接重构目标实现、切换真实依赖并清理冗余；不能重复造轮子，也不能仅加依赖却保留旧生产逻辑。按冻结任务执行并验证 fidelity/受影响消费者，细则见复用协议第 9 节。

新 v2 能力目录明确 provider owner：null 为经评审的已有稳定能力，非空为本轮唯一叶子 owner；write_paths 仅控制权限/互斥，不能推断业务归属。GO 规划归属，父 MO 分配共享改动并收窄写集合，子 MO 冻结复用与适配任务。需改提供方本体走旧基线→授权 owner 变更→新版本→消费者重新冻结/复测；不得以 adapt 绕过 hash。

同 run 新增只读来源按 [来源变更协议](skills/migration-protocol/references/source-changes.md) 执行 GO source-review → Host 绑定用户决策 → reconfigure-sources：新快照、完整影响评审、仅受影响闭包重新规划。保留无关模块有效结果、Red/Yellow、预算和历史；相关阻塞可凭明确决策恢复，无关阻塞不能被顺带解除。宿主消费 source_change_next_step，不能因等待版本切换取消其他 MO。

## 阶段上下文就绪

新运行在 GO 发现/规划、父 MO 拆分、子 SPEC 冻结、Coding/Testing/Fixer 派发与 Auditor 分析/裁决/最终验证前，执行 [上下文就绪协议](skills/migration-protocol/references/context-readiness.md)。实际执行实例先只读核对并经 Ledger context-submit 留证，原控制节点接受；缺项不得执行，必须补齐或显式记录该模块阻塞，无关模块继续。

## 功能清单来源与完备性

功能列表默认从测试用例汇总总结/拆分；缺少汇总则先理解存量待迁移源码并完整抽取，再生成测试草案。完整性覆盖本轮范围的全部根功能、子功能和行为分支，任何疑问立即人工介入；不得以没有 CASE、准备复用二方库或难以理解为由遗漏。遵守 [切片规范](skills/migration-global/references/slicing.md)。

## Test-Runner 双环节与自动化缺测例外

Test-Runner 在 Coding 接受后先编译构建，再执行自动化测试；构建命令优先用户指定，否则全目标搜索脚本并默认评估 Gradle assemble。构建/真实用例错误记录三态与根因，修复仍由 Fixer。仅自动化环境不可启动时，保留当前构建 Green，逐用例记录 Yellow/未执行，经 automation-unavailable 进入 automation-deferred；独立任务及依赖当前构建产物的下游继续，不传播 Yellow、不强制人工恢复。全量收尾后 Auditor 保留缺测清单，本轮可 completed-with-unverified-tests，但不称功能/fidelity 验证通过。规范见 [构建与自动化分流](skills/migration-protocol/references/build-automation.md)。本节细化既有“缺条件挂起”规则，不允许跳过构建或吞掉已观察到的 Red。

## Auditor 范围

全量收尾指等待全部 MO 实现/测试本轮结束，不代表测试全量重跑。Auditor 先整体审查本轮代码修改、重构、冗余、二方库接入和公共能力提取；先委派治理及影响范围回归，再收集剩余问题。新入口与门禁遵守 [代码治理协议](skills/migration-protocol/references/audit-code-review.md)。Auditor 收集 Ledger 的 Red/Yellow，读取对应 SPEC/CASE/PATH，分析根因、委派必要的一轮 Fixer并正式复核；失败输出根因待人工。无关有效 Green 保留证据；无遗留只独立审阅。global_test_paths/global_paths 允许为空，不能作为启动前置。遵守 [审计范围协议](skills/migration-protocol/references/audit-scope.md)。

## 编排名称与收尾报告

父 MO 统一命名 `parent-mo-<module_id>`，例如 parent-mo-M010；宿主读取 status.parent_mo_names，并在创建/恢复时保持可见名称一致。GO 收尾必须向用户提供全部测试 CASE 状态，非 Green 汇总原因与证据；读取 Ledger 生成的 status.migration_report，不省略缺测、不用构建 Green 代替功能验证。详见 [报告协议](skills/migration-protocol/references/migration-report.md)。

## 四维深度切片

GO 先划模块、父 MO 先划子模块、子 MO 先划任务；各层划定 scope 后再按 UI → Logic → Adhesive → Resource 核查源闭包、架构、二方库和目标已有能力；适用项逐层映射到子功能、TASK/PATH/ASSERT，不适用项记录依据。流程节点、字段与门禁必读 [四维完整性协议](skills/migration-protocol/references/dimension-slicing.md)。

## 阻塞感知与恢复

可选 watchdog 是宿主侧旁路监听程序，仅观察和通知；不派发/恢复 Agent、不写 Ledger、不改变门禁。Host 状态无法核实时明确 unknown。它不自动启动，缺失或失败都不能阻塞任何模块。配置、真实状态导出和留存见 [watchdog](skills/migration-protocol/references/watchdog.md)。

全量分析在 GO global-plan 接受节点校验；运行派发只校验当前模块、父级分配和实际依赖。invalidate 保存旧证据，清除当前旧 plan，明确进入重新规划或 GO 分配审查。宿主消费 status.workflow_progress：继续独立 ready 动作，展示人工信号，检查超时 worker；不能因一个门禁拒绝静默终止整轮。超时不能自动放锁、绕过批准或改 Green。必读 [恢复与进度协议](skills/migration-protocol/references/progress-recovery.md)。

## 埋点上报适用性

GO/父子 MO 明确检查认领范围的埋点事件、公共接入与配置，遵守 [埋点协议](skills/migration-protocol/references/telemetry.md)。无埋点模块/任务记录有源码依据的 not-applicable 并直接推进，不创建空任务、用例、SDK依赖或全局门禁；有埋点才映射事件/参数/接线到冻结 TASK/PATH/ASSERT。未知或真实失败只影响相关范围，无关任务继续；观测环境缺失不等于无埋点，也不能用截图通过代替上报通过。

## 统一迁移资产根

所有角色遵守 [留存文件系统](skills/migration-protocol/references/storage-layout.md)。新运行资产固定在 workspace_root 下的 .sdd-migration、.sdd-runs、openspec 三个并列目录；读取 prepare 返回的 run_root/storage_layout 和 status.openspec_hub，不按 cwd 猜目录，不在目标仓另建一份 SPEC。一般生成工件放当前 run staging；Harmony 辅助产物放 runs/harmony/sandbox，正式自动化放 runs/harmony/automation，构建放 runs/build；临时目录归当前 runner，结束清理或留存 cleanup 原因；工作流状态变更仍经 Ledger。
