---
description: /sdd-context [show|init|update|history] — 保存和复用当前项目上下文
---

# /sdd-context

默认 show。自然语言提供新项目资料或明确修改配置也进入同一流程，无需用户手写配置 JSON。

1. 读取 [AGENTS.md](../AGENTS.md) 与 [项目上下文协议](../skills/migration-protocol/references/project-context.md)，定位当前项目固定配置目录；不明确时询问具体项目。
2. 无配置则从用户输入创建，有配置则仅更新用户明确提及的字段；未提及保持原值，明确删除才用 null，“仅本次”保留为运行 overrides。SPEC/Testing list 由 Global 生成，不要求用户填写。
3. 宿主记录真实输入 source_ref，使用 project-context-request 的 request_id、expected_revision，经 project_context.py init/update 持久化。命令不直接手改配置文件。重试复用请求 ID；冲突重读后重算，不覆盖新版本。
4. 返回项目 ID、revision、配置路径、实际变更字段和缺失项。show/history 不修改状态。
5. 用户同时要求启动迁移时继续 prepare → Global → Ledger init/register/global-plan → MO → Auditor；普通配置更新不自行启动迁移，也不改进行中运行的快照。

写入身份为宿主，配置更新是用户已明确请求的动作，无额外确认。业务边界、SPEC 冻结与验收门禁仍按原协议执行。
