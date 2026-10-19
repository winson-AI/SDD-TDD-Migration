---
description: /sdd-context [show|init|update|history] — 保存和复用当前项目上下文
---

# /sdd-context

默认 show。自然语言提供新项目资料或明确修改配置也进入同一流程，无需手写配置 JSON。

1. 读[四条红线](../AGENTS.md#四条红线)与项目上下文协议的[初始化和增量更新](../skills/migration-protocol/references/project-context.md#初始化和增量更新)、[CLI](../skills/migration-protocol/references/project-context.md#cli)，定位当前项目固定配置目录；不明确时询问。
2. 无配置则从用户输入创建；有配置只更新明确提及的字段，明确删除才用 null，"仅本次"进运行 overrides。GO 提取需求/CASE，叶子角色编制 SPEC 与测试列表。缺的存量 / 目标预览声明按返回的 `open_statements` 原样问用户，答复经 update 写入。
3. 宿主记录真实 source_ref，用 project-context-request 的 request_id、expected_revision 经 project_context.py init/update 持久化；重试复用请求 ID，冲突重读后重算。返回项目 ID、revision、配置路径、变更字段与缺失项；show/history 不改状态。
4. 用户同时要求启动迁移时继续 prepare → Global → Ledger init/register/global-plan → MO → Auditor；普通配置更新不自行启动迁移，也不改进行中 run 的快照。

写入身份为宿主，配置更新是用户已请求的动作，无额外确认。为正在运行的 run 追加只读二方库来源时，按[来源追加协议](../skills/migration-protocol/references/source-changes.md#2-host上下文调整与明确恢复)组织 GO source-review 与 Host reconfigure-sources，是否同时保存为项目默认值以用户输入为准。长期配置含 workspace_root（默认 .sdd-migration 父目录），运行位置按 .sdd-runs/<run_id> 派生，OpenSpec 在同级 openspec。同任务一般配置修订走 [run-review/revise-run](../skills/migration-protocol/references/progress-recovery.md#同-run-上游修订)。
