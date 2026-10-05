---
description: /sdd-plan <run-id> <module-id> — 生成六件套并完成 plan 澄清冻结
---

# /sdd-plan

## 1. 用法
`/sdd-plan <run-id> <module-id>`

## 2. 编排步骤
1. 按[命令通用约定](../skills/migration-protocol/references/host-integration.md#命令通用约定)读取入口、解析参数并检查现有工件。
2. 前置门控：run/module 已注册；处于 context/specifying/clarifying/change-review 或等待澄清；持有当前 assignment。推进前运行 `verify_openspec.py --root <run> --scope module --module-id <module-id>`，核验本模块、祖先与实际依赖。失败按 recovery_action 处理相关范围，无关模块继续；核验不证明真实派发或取代冻结。见 [核验范围](sdd-verify.md)。
3. 宿主先让父/子 MO 读取全局代码、架构、知识及分工。根功能先 decompose→GO decompose-accept，派独立子 MO；已拆分父节点只管理/汇总，不进入代码或测试。叶子先由 Spec-Designer 在 staging 写 SPEC 草稿，再由 MO 派 Test-Runner design，完整清晰规划由 MO plan-review/freeze；实际未决或需求/验收/授权变化才交 Escalation，待答时保存 waiting-human。

## 3. 调用契约
目标角色：[Module-Orchestrator](../Agents/module-orchestrator.md)。

## 4. 对应规格
[编码前设计交接](../skills/migration-protocol/references/testing.md#编码前设计交接)、[冻结算法](../skills/migration-protocol/references/openspec.md#冻结算法)。

## 本地实现接入

Spec 草稿 → MO assign(mode=design, design_input_ref) → 独立 Test-Runner submit（附预检）→ MO accept(review_ref) → Spec plan → host decision → MO freeze。见 [编码前交接](../skills/migration-protocol/references/testing.md#编码前设计交接)和[操作矩阵](../skills/migration-protocol/references/local-runtime.md#操作矩阵)。

规划按三层分工推进：GO 分配模块 scope/context；父 MO 认领后拆子模块 scope/context；子 MO 拆 tasks 并组织正式六件套。父 decompose、子 plan 不抄写全局上下文与分配包：步骤视图给出 planning_context 与 module_input，Ledger 接受时绑定其当前版本；保留全局可读视野，执行限于分配范围。

正式子 plan 必须提供 reuse_plan_ref：读取目标及已声明外部模块的能力目录，逐需求映射 reuse/adapt/reference/new 决策、tasks 与 PATH；无候选也记录来源评审和新实现理由。版本和生产接线方案一起冻结。见 [复用协议](../skills/migration-protocol/references/reuse-dependencies.md#5-需求映射与-openspec)。

## 上下文就绪门禁

decomposition 预检随父 decompose 提交，planning 预检随子 plan 提交并绑定同一 plan_ref；GO decompose-accept / 子 MO freeze 再验原报告。缺项或证据失效时不得冻结。详见 [阶段协议](../skills/migration-protocol/references/context-readiness.md#2-精确插入节点)。

## 功能清单来源与完备性

global-plan 需绑定 feature_inventory_ref 与 feature_owners；功能清单默认来自测试用例汇总，无汇总则先从源码抽取。父/子 MO 核对所属功能完整覆盖，疑问同步 boundary_review 并交人工；未分类、未决、遗漏归属不得接受规划。

规划须读取 [四维协议](../skills/migration-protocol/references/dimension-slicing.md#7-任务级四维分析契约)，先基于认领子模块实现/分析等上下文划定任务 scope，再逐任务完成四维分析，将具体实现指导及认领条目完整映射至 design/spec/tasks、PATH 与 ASSERT，禁止删除上游适用项；缺口回上游澄清后再冻结。
