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
| Auditor | [定义](Agents/auditor.md) | 独立复测、修复委派和最终裁决 |
| Escalation | [定义](Agents/escalation.md) | 人工阻塞封装与反馈决策 |
| Ledger | [定义](Agents/ledger.md) | 唯一事件总线、状态投影和追溯 |

## 四条红线

1. Auditor 与 Fixer 使用不同 agent_instance_id；同一次审计中审计者也不得是 Implementer 或测试脚本作者。能力不足则阻塞独立审计。
2. Fixer 不改需求、验收标准或冻结 tasks，只提 CR；Spec-Designer 提修订、Module-Orchestrator 审核，语义变化需要 Human 决策。
3. 所有跨层信息只走 Ledger。角色的产出写入自己的 staging 空间，再提交事件；上游已提交工件经 Ledger 引用才可被下游读取。不得私聊、直接修改别人的状态或利用 Agent 返回文本绕过总线。
4. SPEC 未冻结不生成代码；代码未生成不执行任何目标代码测试；非 Green 未复测不算通过。锁释放、依赖恢复、人工回答均不能直接把测试改 Green。

## 并行模块隔离与 Auditor 全量收尾

GO 完成切片与 registry 登记后，每个 MO 独立推进自己的状态机、测试、修复预算及验收。某模块 Red/Yellow、异常或挂起，仅更新该模块及有证据的依赖影响范围；不得将全局聚合颜色回写其他模块，不得取消无关 MO，或为提前审计批量挂起其他模块。已通过模块保留有效 Green，未执行模块保留未执行状态。

宿主逐 module_id 收集结果；收到一个失败结果后继续派发其他 ready 模块并等待仍在运行的 MO。只有完整 registry 中每个模块都完成 DoD 或有本模块证据的明确挂起记录、全部 worker 已结束且无可推进动作，才允许启动 Auditor。一个 worker 退出不代表其 MO 生命周期结束。详见 [模块隔离与收尾规则](skills/migration-protocol/references/state-machine.md#模块隔离与全量收尾)。

## 调用约定

Agent Markdown 使用 `name/description/mode: subagent`，命令只有 `description`，技能使用 `name/description`。这延续本仓模板约定，宿主可以按实际注册格式转换，不能把 `mode` 误当作所有产品原生字段。

命令解析请求后由宿主提交 Ledger；编排角色提交 dispatch_request，Ledger 接受后，宿主调用实际提供的任务工具。宿主若有 `task` 可映射到它；若有 spawn_agent 可读取定义后启动隔离实例。不能假设能嵌套 slash command，也不能只写一段工具调用文本便宣布已派发。Ledger 的 transport ACK 是唯一允许的传输回执，不携带绕过事件的业务决策。

迁移运行时允许并行无冲突模块，数量受输入和宿主限制；本说明不要求在编辑本工作流包时启动迁移 Agent。

## 本轮增强的读取入口

运行本地控制器时，再读 [local-runtime.md](skills/migration-protocol/references/local-runtime.md)。默认优先恢复同角色原 session；缺失时按 checkpoint 冷恢复，不要求永久保留一个已失效的宿主会话。角色只在当前阶段需要时创建，9+1 职责不变。所有恢复/修复请求仍经过 Ledger，不能恢复为角色私聊。

## 项目上下文入口

宿主先按 [项目上下文协议](skills/migration-protocol/references/project-context.md) 读取/初始化/更新当前项目配置，再 prepare 固化本轮版本。Global 生成完整输入后，Ledger init 绑定 project_context_ref；下游只读 Ledger 引用的本轮快照，不追随 mutable project-context.json。用户明确更新直接保存，运行选择和临时 overrides 不写回项目默认值。项目配置不是模块状态总线。

## 入口范围与父子 MO

project 指完整项目及其功能树；single-module 只选择一个根功能，但父 MO 仍拆分子功能并交独立子 MO。职责固定为 GO 划分模块 scope/所需上下文 → 父 MO 认领后在范围内划分子 scope/所需上下文 → 子 MO 拆 tasks。父子均读全局代码/架构/知识，执行权限限定于认领 scope；规划绑定 Ledger 的 planning_context 和 module_inputs 分配包。父节点保存管理/汇总记录，叶子持有自己的 SPEC、代码、测试与验收；禁止把父聚合失败回写兄弟。全部叶子本轮结束且所有父 MO 提交当前版本汇总后，GO 才统一启动 Auditor。操作与全局上下文要求见 [父子 MO 协议](skills/migration-protocol/references/module-decomposition.md)。

## 二方库与目标已有能力

复用评估贯穿 GO 切片、父 MO 分工、子 MO tasks 和 Coding/Testing。先读取 TARGET 及用户指定 reuse_sources 的功能语义目录，再结合需求决定直接使用、适配、仅参考或新实现；不得按同名 API 认定等价、重复实现已有能力，或为迁就库削弱需求。目录/映射经 Ledger 传递、版本冻结、实际接线及完整测试验证；外部来源只读，跨模块/不确定边界交人工。详见 [二方库复用协议](skills/migration-protocol/references/reuse-dependencies.md)。

**全局 fidelity 规范**：每次选择目标已有能力或外部二方库，必须与存量源码项目对应功能逐行为对齐，明确直接复用/适配如何复现原功能，并记录源码基线、差异、PATH/ASSERT 和正式复现证据。语义参考同样适用；接口可用、库测试通过或对齐报告完成均不能代表迁移功能通过。规划记录随 SPEC 冻结，编码后 Main 验证，MO/Auditor 按阶段唯一验收；行为不一致为 Red，依据或执行条件不足为 Yellow，不能凭复用决策跳过保真验证。明确需求与存量行为冲突须人工决定并留痕。

## 阶段上下文就绪

新运行在 GO 发现/规划、父 MO 拆分、子 SPEC 冻结、Coding/Testing/Fixer 派发与 Auditor 分析/裁决/最终验证前，执行 [上下文就绪协议](skills/migration-protocol/references/context-readiness.md)。实际执行实例先只读核对并经 Ledger context-submit 留证，原控制节点接受；缺项不得执行，必须补齐或显式记录该模块阻塞，无关模块继续。

## 功能清单来源与完备性

功能列表默认从测试用例汇总总结/拆分；缺少汇总则先理解存量待迁移源码并完整抽取，再生成测试草案。完整性覆盖本轮范围的全部根功能、子功能和行为分支，任何疑问立即人工介入；不得以没有 CASE、准备复用二方库或难以理解为由遗漏。遵守 [切片规范](skills/migration-global/references/slicing.md)。

## Test-Runner 双环节与自动化缺测例外

Test-Runner 在 Coding 接受后先编译构建，再执行自动化测试；构建命令优先用户指定，否则全目标搜索脚本并默认评估 Gradle assemble。构建/真实用例错误记录三态与根因，修复仍由 Fixer。仅自动化环境不可启动时，保留当前构建 Green，逐用例记录 Yellow/未执行，经 automation-unavailable 进入 automation-deferred；独立任务及依赖当前构建产物的下游继续，不传播 Yellow、不强制人工恢复。全量收尾后 Auditor 保留缺测清单，本轮可 completed-with-unverified-tests，但不称功能/fidelity 验证通过。规范见 [构建与自动化分流](skills/migration-protocol/references/build-automation.md)。本节细化既有“缺条件挂起”规则，不允许跳过构建或吞掉已观察到的 Red。
