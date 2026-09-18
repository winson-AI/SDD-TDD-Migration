# {{module-id}} Implementation Submission

- assignment_id: {{assignment}}
- freeze_id / spec_revision: {{freeze}}
- base_commit_or_tree: {{base}}
- code_commit: {{commit-or-null}}
- code_tree_sha256 / patch_sha256: {{hashes}}
- workspace / patch_ref: {{absolute-paths}}
- lock_tokens: {{resources-and-fencing-tokens}}

## Task Trace
| TASK-ID | REQ-ID | CASE/PATH | 改动文件 | 实际改动 | 证据 |
| --- | --- | --- | --- | --- | --- |
| {{task}} | {{req}} | {{case/path}} | {{file}} | {{change}} | {{ref}} |

## Self Verification
{{代码生成后实际执行的静态检查/单测命令、cwd、版本、退出码、结果引用；未执行写原因，不能宣称通过}}

## Impact / Rollback
{{受影响接口、路径、消费者、数据兼容性、回滚方式与未解决问题}}

## Delivery
{{提交到 Ledger 的事件；无 commit 时必须记录可重建 tree+patch，不伪造 commit，不自动 commit 用户无关改动}}

## Fixer memory（仅修复提交必填）

- fix_note_ref: {{fix-note.json 的绝对路径与 sha256}}
- 内容包括根因、修复策略、适用条件、风险；Ledger 绑定本次补丁与正式回归证据后决定是否 verified。
