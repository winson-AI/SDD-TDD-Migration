---
name: migration-module
description: 模块状态机门禁、DoD、子任务验收与循环控制，用于 SDD-TDD-Migration 的 Module-Orchestrator 任务。
---

# migration-module

父 MO 给共享实现分配唯一叶子 owner，收窄写集合并审核消费者；子 MO 分清稳定 provider 与任务修改目标，按最新影响评审重新规划受影响部分。来源追加不清除旧失败/预算，无关模块保留有效结果，父摘要仍由父 MO 接受。详见 [来源变更协议](../migration-protocol/references/source-changes.md) 及 [provider 变更闭环](../migration-protocol/references/reuse-dependencies.md#10-显式-provider-归属与合法版本变更)。

## 1. 定位
服务 Module-Orchestrator；[职责协议](../migration-protocol/references/state-machine.md)。

## 2. 核心规约
每个迁移事件验证前置 phase、版本、产物与批准者；仅 MO 决定模块状态，Ledger 验证写入。

## 3. 标准模式
推荐：收到 worker submission → 独立核验 → 接受/驳回事件 → 下一合法阶段；失败按预算分流。

禁止：看到文件已存在就标 done；先更新 Green 再补复测；恢复时清空计数。

## 4. 接口契约
见[通用约定](../migration-protocol/SKILL.md#通用约定)。

## 5. 检查
所有转移符合状态表；冻结与完成清单分离；未解决问题都有 next_action；已用预算不会回退。

## 6. 配套资产
使用 [主要模板](../../template/status.md)。

角色硬约束、调度/审计规则以 [Agent 定义](../../Agents/module-orchestrator.md#6-硬约束) 和 [状态机](../migration-protocol/references/state-machine.md#module-orchestrator-唯一模块守卫) 为准。
