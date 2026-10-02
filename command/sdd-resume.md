---
description: /sdd-resume <run-id> [module-id] [decision.json绝对路径] — 从事件恢复或提交人工反馈
---

# /sdd-resume

## 1. 用法
`/sdd-resume <run-id> [module-id] [decision.json绝对路径]`

## 2. 编排步骤
1. 读取[四条红线](../AGENTS.md#四条红线)、[调用约定](../AGENTS.md#调用约定)和[宿主的轮询与派发](../skills/migration-protocol/references/host-integration.md#提示采纳回报)，解析参数为绝对路径及规范 ID；协议其余部分按小节取（`reading.py show`），不整份加载。
2. 前置门控：run 存在；decision 若提供须有真实人类答复引用、question_id、revision 和 hash；禁止重复或过期决定产生新效果。
3. 检查现有工件与版本；同请求幂等恢复，不删除、不静默覆盖。普通命令不直接写业务工件或投影。
4. 宿主重读 `status`（从事件重放）并按游标派发对应角色；有人工决定时经 Escalation 整理、宿主提交 decision，MO 再 resume/recover。无答复也可恢复 crashed/pending 任务；waiting-human 的必需决定缺失时继续挂起。重获锁、验证代码/SPEC，非 Green 必须复测。
5. 输出已提交事件/当前状态/产物路径和下一动作，命令结束。角色内部按授权预算运行；命令不嵌套执行其他 slash command。

## 3. 调用契约
目标角色：[Global-Orchestrator](../Agents/global-orchestrator.md)。宿主用实际可用的任务工具启动，只传 package_root、run_root、module_id 与阅读卡路径；Ledger 按协议串行服务。定义文件不会自动安装或注册不存在的工具。

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

## 7. 对应规格
[恢复与预算](../skills/migration-protocol/references/local-runtime.md#恢复与预算)、[进度恢复](../skills/migration-protocol/references/progress-recovery.md#总则)。

## 8. 自查
参数与前置有效；工具实际存在；没有越权写入；回执来源可信；恢复指令与 phase 一致。

## 本地实现接入

MO resume；预算耗尽用 host decision → MO recover；会话替换用 session + checkpoint。具体 payload/命令用法见 [操作矩阵](../skills/migration-protocol/references/local-runtime.md#操作矩阵)。宿主必须把已授权身份绑定到 host-context；不能让请求内自报 role 直接获得权限。控制器不自动启动 Agent，不替宿主写目标代码。

状态读取与派发规则同 [/sdd-run](sdd-run.md)。
