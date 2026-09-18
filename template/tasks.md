# {{module-id}} Tasks

定义作者：Spec-Designer；正式写入：Ledger。完成勾选仅来自 MO 接受的任务证据；冻结定义保存在不可变 artifacts。

## Implementation
- [ ] TASK-{{module-id}}-001 {{可执行任务名称}}
  - Requirements: {{REQ-ID 列表}}
  - Cases / Paths: {{CASE-ID / PATH-ID 列表}}
  - Depends on: {{任务 ID 或 none}}
  - Read scope: {{绝对 legacy/契约路径}}
  - Write scope: {{绝对 target 路径与锁资源}}
  - Action: {{具体改动，明确目标架构}}
  - Done when: {{可核验结果、静态检查/测试要求}}
  - Evidence: {{接受后的 code_commit/tree hash 与事件；冻结时填 pending}}

## Traceability
| REQ-ID | 设计章节 | TASK-ID | CASE-ID | PATH-ID | 源文件 | 代码版本 | 证据事件 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| {{req}} | {{design}} | {{task}} | {{case}} | {{path}} | {{file}} | pending | pending |
