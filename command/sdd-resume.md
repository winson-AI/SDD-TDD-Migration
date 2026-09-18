---
description: /sdd-resume <run-id> [module-id] [decision.json绝对路径] — 从事件恢复或提交人工反馈
---

# /sdd-resume

## 1. 用法
`/sdd-resume <run-id> [module-id] [decision.json绝对路径]`

## 2. 编排步骤
1. 读取 [AGENTS.md](../AGENTS.md)、[运行协议](../skills/migration-protocol/references/runtime.md)，解析参数为绝对路径及规范 ID。
2. 前置门控：run 存在；decision 若提供须有真实人类答复引用、question_id、revision 和 hash；禁止重复或过期决定产生新效果。
3. 检查现有工件与版本；同请求幂等恢复，不删除、不静默覆盖。普通命令不直接写业务工件或投影。
4. 由宿主向 Ledger 提交 resume_requested；收到 ACK 后派发对应角色。经 Escalation 记录并验证 decision；Ledger 重放，Global 协調 MO 恢复。无答复也可恢复 crashed/pending 任务；waiting-human 的必需决定缺失时继续挂起。重获锁、验证代码/SPEC，非 Green 必须复测。
5. 输出已提交事件/当前状态/产物路径和下一动作，命令结束。角色内部按授权预算运行；命令不嵌套执行其他 slash command。

## 3. 调用契约
目标角色：[Global-Orchestrator](../Agents/global-orchestrator.md)。宿主用实际可用的任务工具启动，参数只有 package_root、assignment_ref、event_ref；Ledger 按协议串行服务。定义文件不会自动安装或注册不存在的工具。

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

MO resume；预算耗尽用 host decision → MO recover；会话替换用 session + checkpoint。具体 payload/命令用法见 [local-runtime.md](../skills/migration-protocol/references/local-runtime.md)。宿主必须把已授权身份绑定到 host-context；不能让请求内自报 role 直接获得权限。控制器不自动启动 Agent，不替宿主写目标代码。

编排读取 `status.next_steps` 与 `global_next_step`，按 ready/reason 决定下一动作；用 session_id 恢复对应角色，只传事件和工件引用。ready 只是当前快照建议，提交时必须带 expected_revision 再过门禁；阻塞或预算不足不能自行跳步。
