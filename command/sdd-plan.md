---
description: /sdd-plan <run-id> <module-id> — 生成六件套并完成 plan 澄清冻结
---

# /sdd-plan

## 1. 用法
`/sdd-plan <run-id> <module-id>`

## 2. 编排步骤
1. 读取 [AGENTS.md](../AGENTS.md)、[运行协议](../skills/migration-protocol/references/runtime.md)，解析参数为绝对路径及规范 ID。
2. 前置门控：run/module 已注册；处于 context/specifying/clarifying/change-review 或等待澄清；持有当前 assignment。推进前先运行只读门禁 `verify_openspec.py --root <run>`（或 `/sdd-verify`）确认本 run 确经 Ledger 管道；`verified=false` 说明被手写模拟绕过，拒绝推进并回到 prepare → init → apply。见 [投影完整性收尾门禁](../skills/migration-protocol/references/storage-layout.md#openspec-投影完整性收尾门禁)。
3. 检查现有工件与版本；同请求幂等恢复，不删除、不静默覆盖。普通命令不直接写业务工件或投影。
4. 宿主先让父/子 MO 读取全局代码、架构、知识及分工。根功能先 decompose→GO decompose-accept，派独立子 MO；已拆分父节点只管理/汇总，不进入代码或测试。叶子由 MO 派 Spec-Designer 与 Test-Runner design，冻结前请 Escalation 展示必须的人工决定；未获所需答案保存 waiting-human，已获批准且 hash 有效才冻结。
5. 输出已提交事件/当前状态/产物路径和下一动作，命令结束。角色内部按授权预算运行；命令不嵌套执行其他 slash command。

## 3. 调用契约
目标角色：[Module-Orchestrator](../Agents/module-orchestrator.md)。宿主用实际可用的任务工具启动，参数只有 package_root、assignment_ref、event_ref；Ledger 按协议串行服务。定义文件不会自动安装或注册不存在的工具。

## 4. 参数验证
run-id/change-name 为 kebab-case，module-id 为 `M[0-9]{3,}`；禁止路径逃逸。JSON 中占位符、未决必填值、零必需用例不能作为有效运行输入。status 可读取尚未完成的输入状态。

## 5. 硬约束
命令只解析、门控、提交/查询和派发；无业务代码、无状态双写；叶子不能私传结果；无有效批准不推断已冻结；所有门禁由对应守卫/权限校验再次验证。

## 6. 期望输出
```text
✅ accepted | event=<id> | run=<run-id> | next=<账本动作>
⚠️ blocked | reason=<门禁/依赖/人工> | evidence=<绝对路径或事件>
❌ failed | reason=<实际错误> | recorded=<event-id或transport-unavailable>
```
status 使用 `snapshot sequence=<n>` 及当前三态摘要，不伪造事件接受回执。

## 7. 对应规格
[状态机](../skills/migration-protocol/references/state-machine.md)、[OpenSpec 契约](../skills/migration-protocol/references/openspec.md)。

## 8. 自查
参数与前置有效；工具实际存在；没有越权写入；回执来源可信；恢复指令与 phase 一致。

## 本地实现接入

Spec plan → host decision → MO freeze。具体 payload/命令用法见 [local-runtime.md](../skills/migration-protocol/references/local-runtime.md)。宿主必须把已授权身份绑定到 host-context；不能让请求内自报 role 直接获得权限。控制器不自动启动 Agent，不替宿主写目标代码。

规划按三层分工推进：GO 分配模块 scope/context；父 MO 认领后拆子模块 scope/context；子 MO 拆 tasks 并组织正式六件套。父 decompose、子 plan 都绑定 status.planning_context 和 status.module_inputs 对应的 assigned_module，保留全局可读视野，执行限于分配范围。

正式子 plan 必须提供 reuse_plan_ref：读取目标及已声明外部模块的能力目录，逐需求映射 reuse/adapt/reference/new 决策、tasks 与 PATH；无候选也记录来源评审和新实现理由。版本和生产接线方案一起冻结。见 [复用协议](../skills/migration-protocol/references/reuse-dependencies.md)。

## 上下文就绪门禁

父 decompose 前提交 decomposition 预检，子 plan 前提交 planning 预检并绑定同一 plan_ref；GO decompose-accept / 子 MO freeze 再验原报告。缺项或证据失效时不得冻结。详见 [阶段协议](../skills/migration-protocol/references/context-readiness.md)。

## 功能清单来源与完备性

global-plan 需绑定 feature_inventory_ref 与 feature_owners；功能清单默认来自测试用例汇总，无汇总则先从源码抽取。父/子 MO 核对所属功能完整覆盖，疑问同步 boundary_review 并交人工；未分类、未决、遗漏归属不得接受规划。

规划须读取 [四维协议](../skills/migration-protocol/references/dimension-slicing.md)，先基于认领子模块实现/分析等上下文划定任务 scope，再逐任务完成四维分析，将具体实现指导及认领条目完整映射至 design/spec/tasks、PATH 与 ASSERT，禁止删除上游适用项；缺口回上游澄清后再冻结。
