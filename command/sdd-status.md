---
description: /sdd-status <run-id> — 冷读全局与模块状态
---

# /sdd-status

## 1. 用法
`/sdd-status <run-id>`

## 2. 编排步骤
1. 读取 [AGENTS.md](../AGENTS.md)、[运行协议](../skills/migration-protocol/references/runtime.md)，解析参数为绝对路径及规范 ID。
2. 前置门控：run 的事实日志可读；投影缺失/过期时只能由 Ledger 重建。
3. 检查现有工件与版本；同请求幂等恢复，不删除、不静默覆盖。普通命令不直接写业务工件或投影。
4. 查询 Ledger 的可信投影。只读汇总模块 phase/execution_status/quality、Red/Yellow 路径、root cause、依赖、预算与 next_action；不能触发测试、修复或推进。
5. 输出已提交事件/当前状态/产物路径和下一动作，命令结束。角色内部按授权预算运行；命令不嵌套执行其他 slash command。

## 3. 调用契约
目标角色：[Ledger](../Agents/ledger.md)。宿主用实际可用的任务工具启动，参数只有 package_root、assignment_ref、event_ref；Ledger 按协议串行服务。定义文件不会自动安装或注册不存在的工具。

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

ledger.py status；若 observed_invalidations 非空交守卫处理。具体 payload/命令用法见 [local-runtime.md](../skills/migration-protocol/references/local-runtime.md)。宿主必须把已授权身份绑定到 host-context；不能让请求内自报 role 直接获得权限。控制器不自动启动 Agent，不替宿主写目标代码。

编排读取 `status.next_steps` 与 `global_next_step`，按 ready/reason 决定下一动作；用 session_id 恢复对应角色，只传事件和工件引用。ready 只是当前快照建议，提交时必须带 expected_revision 再过门禁；阻塞或预算不足不能自行跳步。

同时展示 module_rounds 的 registered/settled/unfinished/active/ready 模块清单及 blockers。quality 为全局聚合，不代表每个模块的测试结果或执行结束；必须分别展示各模块 phase/quality。遇到 await-all-module-rounds 时，按 continue_modules 继续执行、按 wait_for_modules 等待结果，不把等待审计的状态回写为其他模块失败。

status.module_inputs 给出每个父/子 MO 的权威 scope、context_refs、CASE、写范围和依赖；子包包含 parent_context。它与全局 planning_context 一起用于认领、规划与核对范围，不代表已启动 Agent。

同时输出 `parent_mo_names`（父 MO 统一名，如 parent-mo-M010）与 `migration_report` 的 JSON/Markdown 绝对路径和 sequence。报告包含全部 CASE/PATH 状态与非 Green 原因/证据；运行中报告明确 in-progress，不作为完成验收。GO 收尾使用 [报告协议](../skills/migration-protocol/references/migration-report.md)。

必须展示 `workflow_progress.state/signals/runnable_actions/worker_watches` 及其报告路径；`notify_user=true` 时明确告知用户受影响模块、owner、原因/证据和下一步，不能只返回 ready=false。该命令只查询；真正恢复和继续调度由宿主/编排器按 [进度恢复协议](../skills/migration-protocol/references/progress-recovery.md) 执行。仅 automation 缺测按既有出口推进到 Auditor，最终 Yellow 缺测收尾不会被当作无动作死锁。
