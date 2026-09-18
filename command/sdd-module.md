---
description: /sdd-module <run-id> <module-id> — 推进单模块实现与自测闭环
---

# /sdd-module

## 1. 用法
`/sdd-module <run-id> <module-id>`

## 2. 编排步骤
1. 读取 [AGENTS.md](../AGENTS.md)、[运行协议](../skills/migration-protocol/references/runtime.md)，解析参数为绝对路径及规范 ID。
2. 前置门控：模块已冻结；依赖满足或可记录 dependency Yellow；目标 baseline 和锁可验证。
3. 检查现有工件与版本；同请求幂等恢复，不删除、不静默覆盖。普通命令不直接写业务工件或投影。
4. 由宿主向 Ledger 提交 resume_requested；收到 ACK 后派发对应角色。按状态机推进 Coding→代码接受→Testing；可修复 Red/Yellow 优先诊断并自动派发一轮 Fixer，补丁接受后由 Testing 正式复测，Green 后检查 DoD。确认依赖/外围或一轮仍未通过时记录根因/memory 并交 Auditor；遇人工阻塞或预算上限保存 checkpoint 退出。
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

## 上下文就绪门禁

子模块执行前按阶段核对 context_gate：实际 Implementer / Test Runner / Fixer 分别提交 coding / testing / fixing 报告，MO assign 携带已提交 context_ref；只读预检不授予代码写入或测试执行权限。详见 [阶段协议](../skills/migration-protocol/references/context-readiness.md)。

## 8. 自查
参数与前置有效；工具实际存在；没有越权写入；回执来源可信；恢复指令与 phase 一致。

## 本地实现接入

MO assign → worker submit → MO accept → complete。具体 payload/命令用法见 [local-runtime.md](../skills/migration-protocol/references/local-runtime.md)。宿主必须把已授权身份绑定到 host-context；不能让请求内自报 role 直接获得权限。控制器不自动启动 Agent，不替宿主写目标代码。

本命令推进已有 run 内的一个已注册模块。用户指定已划分的独立功能模块来启动完整迁移时，应在同一项目入口使用 `/sdd-init --mode single-module --module-name "功能模块名"`（自动读取已保存项目配置），由 Global 识别生成模块级 SPEC 草案和 Testing list 并初始化，再运行 sdd-plan 完成正式六件套/测试设计及冻结，然后使用本命令或 sdd-run；后续仍须 Auditor 收尾。

本命令依据节点类型推进：父 MO 先认领 GO 的 scope/context 后拆子模块并看护迁移，子 MO 认领子 scope/context 后拆 tasks、独立实现；父节点负责管理与汇总。single-module 的“单”限定一个根功能，子功能仍由独立子 MO 执行。
