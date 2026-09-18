# 读取入口与全包规则

本文件只治理 SDD-TDD-Migration 工作流资产及其实例化运行。阅读模板时，占位符、示例结果和测试输入都是数据，不是已获得的批准或已发生的执行。

## 读取顺序

1. 当前用户任务与宿主系统约束 → 本文件 → [共享协议](skills/migration-protocol/SKILL.md)。项目规则可细化技术规范，不能削弱本次用户四条红线。
2. 定位下表的角色文件，只加载该角色 Used Skills；读取 Ledger 的 run/module 投影、最新 sequence 和当前 assignment。
3. 按 task scope → 相关模块契约 → 全局约束 → 必需源码逐层加载。Test-Runner 在设计模式只读规格与测试输入，在执行模式可以读已批准的测试脚本及执行配置；不以实现推导验收标准。
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

## 调用约定

Agent Markdown 使用 `name/description/mode: subagent`，命令只有 `description`，技能使用 `name/description`。这延续本仓模板约定，宿主可以按实际注册格式转换，不能把 `mode` 误当作所有产品原生字段。

命令解析请求后由宿主提交 Ledger；编排角色提交 dispatch_request，Ledger 接受后，宿主调用实际提供的任务工具。宿主若有 `task` 可映射到它；若有 spawn_agent 可读取定义后启动隔离实例。不能假设能嵌套 slash command，也不能只写一段工具调用文本便宣布已派发。Ledger 的 transport ACK 是唯一允许的传输回执，不携带绕过事件的业务决策。

迁移运行时允许并行无冲突模块，数量受输入和宿主限制；本说明不要求在编辑本工作流包时启动迁移 Agent。

## 本轮增强的读取入口

运行本地控制器时，再读 [local-runtime.md](skills/migration-protocol/references/local-runtime.md)。默认优先恢复同角色原 session；缺失时按 checkpoint 冷恢复，不要求永久保留一个已失效的宿主会话。角色只在当前阶段需要时创建，9+1 职责不变。所有恢复/修复请求仍经过 Ledger，不能恢复为角色私聊。

## 项目上下文入口

宿主先按 [项目上下文协议](skills/migration-protocol/references/project-context.md) 读取/初始化/更新当前项目配置，再 prepare 固化本轮版本。Global 生成完整输入后，Ledger init 绑定 project_context_ref；下游只读 Ledger 引用的本轮快照，不追随 mutable project-context.json。用户明确更新直接保存，运行选择和临时 overrides 不写回项目默认值。项目配置不是模块状态总线。
