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

每条可带 `test_order`（tests-first / code-first）与 `red_evidence={before_ref, after_ref}`（同一 unit PATH 的两份自查记录）。

## Self Verification
{{实际执行的静态检查/单测命令、cwd、版本、退出码、结果引用；未执行写原因}}

- authoring_diagnostics.status: {{passed | unavailable}}；passed 给 tool 与 log_ref（无错误），unavailable 给 reason 与 version_sensitive_apis（api + 固定版本依赖源码 source_ref，没有则 []）

## Impact / Rollback
{{受影响接口、路径、消费者、数据兼容性、回滚方式与未解决问题}}

## Delivery
{{提交到 Ledger 的事件；无 commit 时记录可重建的 tree + patch}}

## Fixer memory（仅修复提交）
- fix_note_ref: {{fix-note.json 的绝对路径与 sha256}}

## reuse_trace（每个 reuse / adapt / reference 映射一行；new 映射走 Task Trace）
| 映射 ID | 来源 / 能力 / 实际版本 | 接入文件 / DI / 调用入口 | 适配差异 | 真实提供方绑定证据 |
| --- | --- | --- | --- | --- |
| {{mapping}} | {{source/capability/version}} | {{files-and-binding}} | {{delta}} | {{evidence-ref}} |

正式 JSON 中每条 reuse_trace 含 mapping_id、resolved_version、files 与 binding_evidence_ref；冗余重构另附切换的调用、删除的重复与保留理由（reuse-dependencies.md 第 9 节）。

## dimension_evidence（冻结的每个 item）
```json
{"dimension_evidence": [{"item_id": "DIM-M001-LOGIC-001", "task_ids": ["TASK-M001-001"], "summary": "{{actual-behavior-and-production-binding}}",
                         "evidence_refs": [{"path": "{{absolute-evidence-file}}", "sha256": "{{sha256}}"}]}]}
```
Resource item 另附 target_resource_ref 与 consumer_refs（逐消费者文件 hash）；规则见 dimension-slicing.md 第 4 节。
