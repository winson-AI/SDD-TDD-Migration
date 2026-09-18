---
description: /sdd-run <run-id> — 并行推进就绪模块
---

# /sdd-run

## 1. 用法
`/sdd-run <run-id>`

## 2. 编排步骤
1. 读取 [AGENTS.md](../AGENTS.md)、[运行协议](../skills/migration-protocol/references/runtime.md)，解析参数为绝对路径及规范 ID。
2. 前置门控：run 已初始化；可调度工作存在；宿主提供隔离实例/身份与单写 Ledger；max_parallel_modules 合法。
3. 检查现有工件与版本；同请求幂等恢复，不删除、不静默覆盖。普通命令不直接写业务工件或投影。
4. 由宿主向 Ledger 提交 resume_requested；收到 ACK 后派发对应角色。Global 在 DAG 与锁约束内派发模块；仅已冻结模块可以编码。消费事件推进至全部完成或无可运行工作；不得绕过待澄清模块，也不因它阻止其他模块。完成后请求独立审计。
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

Global 选择 ready 模块 → MO assign/accept。具体 payload/命令用法见 [local-runtime.md](../skills/migration-protocol/references/local-runtime.md)。宿主必须把已授权身份绑定到 host-context；不能让请求内自报 role 直接获得权限。控制器不自动启动 Agent，不替宿主写目标代码。

编排读取 `status.next_steps` 与 `global_next_step`，按 ready/reason 决定下一动作；用 session_id 恢复对应角色，只传事件和工件引用。ready 只是当前快照建议，提交时必须带 expected_revision 再过门禁；阻塞或预算不足不能自行跳步。

当前策略：本地优先修复一轮，确认依赖/外围或一轮未通过则 audit-defer 并退出。Global 必须等待全部模块本轮 completed 或明确挂起，且没有活动 worker/可推进动作，再统一 audit-collect。正常依赖解除和已有批准的 resume 先执行；不能仅因当前没有 worker 就拉起 Auditor。

活动批次按 finding 路由、按依赖交错修复与 Testing，失败仅挂起关联分支。部分成功汇总后待人工；audit-release 需要当前报告摘要批准。主循环及 subagent/skills 调用均由宿主执行，Ledger 返回游标并在每次提交复核门禁。
