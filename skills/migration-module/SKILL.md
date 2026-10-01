---
name: migration-module
description: 模块状态机门禁、DoD、子任务验收与循环控制，用于 SDD-TDD-Migration 的 Module-Orchestrator 任务。
---

# migration-module

父 MO 给共享实现分配唯一叶子 owner，收窄写集合并审核消费者；子 MO 分清稳定 provider 与任务修改目标，按最新影响评审重新规划受影响部分。来源追加不清除旧失败/预算，无关模块保留有效结果，父摘要仍由父 MO 接受。详见 [来源变更协议](../migration-protocol/references/source-changes.md) 及 [provider 变更闭环](../migration-protocol/references/reuse-dependencies.md#10-显式-provider-归属与合法版本变更)。

## 1. 定位
服务 Module-Orchestrator；先读取 [共享协议](../migration-protocol/SKILL.md)，再按阅读卡读 [职责协议](../migration-protocol/references/state-machine.md) 的相应小节。

## 2. 核心规约
每个迁移事件验证前置 phase、版本、产物与批准者；仅 MO 决定模块状态，Ledger 验证写入。

所有跨层输入输出通过 Ledger 已提交引用传递；本技能不授予角色之外的写权限。

## 3. 标准模式
推荐：收到 worker submission → 独立核验 → 接受/驳回事件 → 下一合法阶段；失败按预算分流。

禁止：看到文件已存在就标 done；先更新 Green 再补复测；恢复时清空计数。

## 4. 接口契约
输入 assignment_ref + event_ref + absolute artifact refs；输出角色权限矩阵许可的事件及模板工件。文件已生成不等于已接受，必须收到 Ledger ACK。

## 5. 检查
所有转移符合状态表；冻结与完成清单分离；未解决问题都有 next_action；已用预算不会回退。

## 6. 配套资产
使用 [主要模板](../../template/module-input.json)；其他工件由 [模板索引](../../template/INDEX.md) 定位。无项目执行器时按 Yellow 处理，不能生成假测试结果。

角色义务、调度/审计规则与专题入口以 [Agent 定义](../../Agents/module-orchestrator.md#专题义务) 和 [状态机](../migration-protocol/references/state-machine.md) 为准；本技能只保留执行规约与检查，不重复专题细则。
