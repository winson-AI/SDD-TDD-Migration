---
description: /sdd-plan <run-id> <module-id> — 生成六件套并完成 plan 澄清冻结
---

# /sdd-plan

## 1. 用法
`/sdd-plan <run-id> <module-id>`

## 2. 编排步骤
1. 按[命令通用约定](../skills/migration-protocol/references/host-integration.md#命令通用约定)读取入口、解析参数并检查现有工件。
2. 前置门控：run/module 已注册；处于 context/specifying/clarifying/change-review 或等待澄清；持有当前 assignment。推进前运行 `verify_openspec.py --root <run> --scope module --module-id <module-id>`，核验模块、祖先和实际依赖；按 recovery_action 局部恢复，保留无关进度。核验不代替派发或冻结。见 [核验范围](sdd-verify.md)。
3. MO 先读全局代码、架构、知识及分工。按原子性选择细分或叶子规划；MO 原子结论同样经 decompose→GO decompose-accept，不创建同范围孩子。已拆父只管理/汇总。叶子拆 TASK 后由 Spec-Designer 直接写 SPEC/上游用例路径，MO plan-review/freeze；Test-Runner design 仅按需派发；实际未决或需求/验收/授权变化才交 Escalation，待答保存 waiting-human。

## 3. 调用契约
目标角色：[Module-Orchestrator](../Agents/module-orchestrator.md)。

## 4. 对应规格
[编码前设计交接](../skills/migration-protocol/references/testing.md#编码前设计交接)、[冻结算法](../skills/migration-protocol/references/openspec.md#冻结算法)。

## 本地实现接入

scope/CASE 分配 → 子 MO 拆 TASK → Spec plan（绑定上游全量用例）→ MO plan-review/freeze → Implementer/Test-Runner/Fixer。执行中按 CR 修订当前 SPEC 后更新已有代码；不强制独立 design 或反复完整重规划。未决或语义/授权变化才需 Human 决定；见[设计交接](../skills/migration-protocol/references/testing.md#编码前设计交接)。

步骤视图提供 planning_context/module_input，接受时绑定当前内容摘要。子 plan 的 reuse_plan_ref 逐需求映射来源、reuse/adapt/reference/new、TASK/PATH；无候选也给证据。版本与接线一起冻结，见[复用协议](../skills/migration-protocol/references/reuse-dependencies.md#5-需求映射与-openspec)。

## 上下文就绪门禁

父 decompose/子 plan 分别绑定 decomposition/planning 预检；GO decompose-accept/MO freeze 重验，缺项或过期不冻结。见[阶段协议](../skills/migration-protocol/references/context-readiness.md#2-精确插入节点)。

## 功能清单来源与完备性

global-plan 绑定 feature_inventory_ref/feature_owners；父子 MO 核覆盖和 owner，未分类/未决先补齐或交人工。

按[任务四维协议](../skills/migration-protocol/references/dimension-slicing.md#7-任务级四维分析契约)先划 task scope，再分析四维，完整映射至 design/spec/tasks、PATH/ASSERT；不删上游适用项，缺口回溯后重冻。
