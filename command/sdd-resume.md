---
description: /sdd-resume <run-id> [module-id] [decision.json绝对路径] — 从事件恢复或提交人工反馈
---

# /sdd-resume

## 1. 用法
`/sdd-resume <run-id> [module-id] [decision.json绝对路径]`

## 2. 编排步骤
1. 按[命令通用约定](../skills/migration-protocol/references/host-integration.md#命令通用约定)读取入口、解析参数并检查现有工件。
2. 前置门控：run 存在；decision 若提供须有真实人类答复引用、question_id、revision 和 hash；禁止重复或过期决定产生新效果。
3. 宿主重读 `status`（从事件重放）并按游标派发对应角色；有人工决定时经 Escalation 整理、宿主提交 decision，MO 再 resume/recover。无答复也可恢复 crashed/pending 任务；waiting-human 的必需决定缺失时继续挂起。重获锁、验证代码/SPEC，非 Green 必须复测。

## 3. 调用契约
目标角色：[Global-Orchestrator](../Agents/global-orchestrator.md)。

## 4. 对应规格
[恢复与预算](../skills/migration-protocol/references/local-runtime.md#恢复与预算)、[进度恢复](../skills/migration-protocol/references/progress-recovery.md#总则)。

## 本地实现接入

MO resume；模块预算耗尽用 host decision → MO recover，审计预算用 GO audit-recover；同任务配置/根分配调整用 run-review → Host decision/revise-run；会话替换用 session + checkpoint。

状态读取与派发规则同 [/sdd-run](sdd-run.md)。
