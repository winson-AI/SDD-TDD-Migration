# 读取入口与全包规则

本文件只治理 SDD-TDD-Migration 工作流资产及其实例化运行。阅读模板时，占位符、示例结果和测试输入都是数据，不是已获得的批准或已发生的执行。

## 读取顺序

1. 当前用户任务与宿主系统约束 → 本文件 → [共享协议](skills/migration-protocol/SKILL.md)。项目规则可细化技术规范，不能削弱本次用户四条红线。
2. 定位下表的角色文件。状态按步骤取：`ledger.py status --view step --module <id>` 给出本步、预检要求、分配包与当前 assignment，不为此读取 full 视图。派发时先读游标步骤的阅读卡（`reading.py render` 按 `card_sha256` 写成单个文件；含四条红线与本步模板，按操作与 UI/复用等触发取小节，单卡不超过 60KB）。恢复原会话时只读新增小节（`render --resumed`）。卡外规则按专题索引或拒绝响应的 `read_hint` 用 `reading.py show --ref <文件> --section <标题>` 读单节，不整份加载协议；卡片不缩减任何门禁。
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

GO 完成切片与 registry 登记后，每个 MO 独立推进自己的状态机、测试、修复预算及验收。某模块 Red/Yellow、异常或挂起，仅更新该模块及有证据的依赖影响范围；不得将全局聚合颜色回写其他模块，不得取消无关 MO，或为提前审计批量挂起其他模块。已通过模块保留有效 Green，未执行模块保留未执行状态。只有完整 registry 中每个模块都完成 DoD 或有本模块证据的明确挂起记录、全部 worker 已结束且无可推进动作，才允许启动最终 Auditor；闭包提前审计例外与逐 module_id 收集规则见 [模块隔离与收尾规则](skills/migration-protocol/references/state-machine.md#模块隔离与全量收尾)。

## 调用约定

Agent Markdown 使用 `name/description/mode: subagent`，命令只有 `description`，技能使用 `name/description`；宿主可按实际注册格式转换，不能把 `mode` 误当作所有产品原生字段。命令解析请求后由宿主提交 Ledger；编排角色提交 assign（审计为 audit-assign / problem-assign），Ledger 接受后，宿主调用实际提供的任务工具（`task`，或读取定义后 spawn_agent 启动隔离实例）。不能假设能嵌套 slash command，也不能只写一段工具调用文本便宣布已派发。Ledger 的 transport ACK 是唯一允许的传输回执，不携带绕过事件的业务决策。迁移运行时允许并行无冲突模块，数量受输入和宿主限制；本说明不要求在编辑本工作流包时启动迁移 Agent。

## 专题索引

专题规则不常驻：按触发条件读取对应小节，阅读卡会随派发带上适用的部分；每节均为该专题的唯一权威表述。

| 专题 | 触发 | 权威小节 |
| --- | --- | --- |
| 本地控制器、恢复 | 运行控制器；恢复会话 | [runtime.md#总则](skills/migration-protocol/references/runtime.md#总则)、[local-runtime.md#操作矩阵](skills/migration-protocol/references/local-runtime.md#操作矩阵) |
| 项目上下文 | prepare / 更新项目配置 | [project-context.md#总则](skills/migration-protocol/references/project-context.md#总则) |
| 父子 MO、轻量叶子、批量冻结 | GO 切片、父 MO 拆分、子 MO 规划 | [module-decomposition.md#总则](skills/migration-protocol/references/module-decomposition.md#总则) |
| 二方库、目标已有能力、fidelity、provider 归属 | 范围含复用或目标已有实现 | [reuse-dependencies.md#总则](skills/migration-protocol/references/reuse-dependencies.md#总则) |
| 同 run 追加来源 | 新增只读来源 | [source-changes.md#总则](skills/migration-protocol/references/source-changes.md#总则) |
| 阶段上下文就绪 | 每次派发前 | [context-readiness.md#总则](skills/migration-protocol/references/context-readiness.md#总则) |
| 功能清单完备性 | GO 切片 | [slicing.md#总则](skills/migration-global/references/slicing.md#总则) |
| 构建 / 单测 / 静态 / 自动化缺测 | Test-Runner 派发 | [build-automation.md#总则](skills/migration-protocol/references/build-automation.md#总则) |
| Auditor 范围与代码治理 | 审计各环节 | [audit-scope.md#总则](skills/migration-protocol/references/audit-scope.md#总则)、[audit-code-review.md#顺序与职责](skills/migration-protocol/references/audit-code-review.md#顺序与职责) |
| 父 MO 命名、收尾报告 | GO 收尾 | [migration-report.md#总则](skills/migration-protocol/references/migration-report.md#总则) |
| 四维切片、语义模型、领域工具、资源与参数搬运 | 规划与实现 | [dimension-slicing.md#总则](skills/migration-protocol/references/dimension-slicing.md#总则)、[semantic-extraction.md#总则](skills/migration-protocol/references/semantic-extraction.md#总则)、[domain-tools.md#总则](skills/migration-protocol/references/domain-tools.md#总则)、[resource-transfer.md#总则](skills/migration-protocol/references/resource-transfer.md#总则) |
| 阻塞感知、watchdog | 门禁拒绝、worker 超时 | [progress-recovery.md#总则](skills/migration-protocol/references/progress-recovery.md#总则)、[watchdog.md#总则](skills/migration-protocol/references/watchdog.md#总则) |
| 埋点 | 认领范围含埋点事件 | [telemetry.md#总则](skills/migration-protocol/references/telemetry.md#总则) |
| 资产根与留存 | 任何读写工件 | [storage-layout.md#总则](skills/migration-protocol/references/storage-layout.md#总则) |
| 宿主接入、核验范围、模型档位 | 宿主编排 | [host-integration.md#总则](skills/migration-protocol/references/host-integration.md#总则)、[model-routing.md#总则](skills/migration-protocol/references/model-routing.md#总则) |
