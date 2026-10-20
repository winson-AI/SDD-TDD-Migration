# 读取入口与全包规则

本文件只治理 SDD-TDD-Migration 工作流资产及其实例化运行。阅读模板时，占位符、示例结果和测试输入都是数据，不是已获得的批准或已发生的执行。

## 读取顺序

1. **被派发的角色只读阅读卡**：宿主交给它的卡文件（`reading.py render` 按 `card_sha256` 写出）已含四条红线、共享规则、角色定义与本步规则、本步模板名，以及按触发列出的按需小节；写到对应工件时用 `reading.py show --ref <文件> --section <标题>` 读单节，拒绝响应的 `read_hint` 同样读单节；按需不免除门禁。恢复原会话只读新增小节（`render --resumed`）。不读本文件、共享协议全文或整份协议。
2. **宿主与编排入口**：当前用户任务与宿主约束 → 本文件 → [共享协议](skills/migration-protocol/SKILL.md) → [宿主接入](skills/migration-protocol/references/host-integration.md#总则)（调用约定、专题索引）。状态按步骤取：`ledger.py status --view step --module <id>`，不为此读 full 视图。项目规则可细化技术规范，不能削弱四条红线。
3. 父 MO 和子 MO 规划前先读全局代码入口（legacy_root/target_root）、架构规范、知识资料及当前父子分工/依赖，再按 scope 聚焦必需源码；检查目标已有能力与兄弟 owner 后再规划。Test-Runner 不以实现推导验收标准。
4. 运行期输入统一为绝对路径（`package_root`、`run_root`、`change_root`、legacy/target），禁止路径逃逸。源码仓有 `.codegraph/` 时先用 CodeGraph；无索引不主动建。
5. 交接仅传 Ledger 已提交的 assignment/event 引用及工件路径/摘要，新 Agent 重读这些工件，不依赖原会话记忆。各模块独立推进与全量收尾见[模块隔离](skills/migration-protocol/references/state-machine.md#模块隔离与全量收尾)。

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
4. SPEC 未冻结不生成代码；代码未被接受不派发正式目标代码测试，作者自查不产生任何结果、不能代替正式测试；非 Green 未复测不算通过。锁释放、依赖恢复、人工回答均不能直接把测试改 Green。
