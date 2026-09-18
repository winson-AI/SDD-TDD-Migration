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

## 二方库 / 已有能力的实际使用

- reuse_plan_ref: {{冻结的需求—能力—任务—PATH 映射}}
- 每个 reuse/adapt/reference 映射提交 reuse_trace；new 映射继续使用 Task Trace。
- 正式 implementation JSON 中每条 reuse_trace 含 mapping_id、resolved_version、files（属于对应 task_trace）和 binding_evidence_ref（绝对 path/sha256）。Implementer 与 Fixer 都需要提交。

| 映射 ID | 来源 / 能力 / 实际版本 | 接入文件 / DI / 调用入口 | 适配差异 | 真实提供方绑定证据 |
| --- | --- | --- | --- | --- |
| {{mapping}} | {{source/capability/version}} | {{files-and-binding}} | {{delta}} | {{evidence-ref}} |

reference-only 说明借鉴了哪些业务语义及目标实现差异，不宣称已建立运行时依赖。provider_refs 用于核验依据版本，不授予修改来源项目的权限。
