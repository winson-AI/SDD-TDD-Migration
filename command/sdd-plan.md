---
description: /sdd-plan <run-id> <module-id> — 生成六件套并完成 plan 澄清冻结
---

# /sdd-plan

## 1. 用法
`/sdd-plan <run-id> <module-id>`

## 2. 编排步骤
1. 先按[命令通用约定](../skills/migration-protocol/references/host-integration.md#命令通用约定)。
2. 前置门控：run/module 已注册，处于 context/specifying/clarifying/change-review 或等待澄清，持有当前 assignment；先 `verify_openspec.py --scope module --module-id <module-id>`，按 recovery_action 局部恢复，见[核验范围](sdd-verify.md)。
3. MO 先读全局代码、架构、知识与分工；按原子性细分或叶子规划（原子结论同样经 decompose → GO decompose-accept）；叶子拆 TASK 后由 Spec-Designer 直接写 SPEC 与上游用例路径，MO plan-review/freeze；只有真实未决或需求/验收/授权变化交 Escalation，待答保存 waiting-human。

## 3. 契约与规格
目标角色 [Module-Orchestrator](../Agents/module-orchestrator.md)；[编码前设计交接](../skills/migration-protocol/references/testing.md#编码前设计交接)、[冻结算法](../skills/migration-protocol/references/openspec.md#冻结算法)、[任务四维协议](../skills/migration-protocol/references/dimension-slicing.md#7-任务级四维分析契约)。

## 4. 接入要点
- 流程：scope/CASE 分配 → 子 MO 拆 TASK → Spec plan（绑定上游全量用例）→ MO plan-review/freeze → Implementer/Test-Runner/Fixer；执行中按 CR 修订当前 SPEC 后更新已有代码，不反复完整重规划。
- 步骤视图提供 planning_context/module_input，接受时绑定摘要；reuse_plan_ref 逐需求映射来源与 reuse/adapt/reference/new，版本与接线一起冻结，见[复用协议](../skills/migration-protocol/references/reuse-dependencies.md#5-需求映射与-openspec)。父 decompose/子 plan 分别绑定 decomposition/planning 预检，GO decompose-accept/MO freeze 重验。
- global-plan 绑定 feature_inventory_ref/feature_owners，父子 MO 核覆盖与 owner；任务先划 scope 再四维分析，完整映射到 design/spec/tasks 与 PATH/ASSERT，缺口回溯后重冻。
