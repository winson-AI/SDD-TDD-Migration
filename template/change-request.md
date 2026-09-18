# CR {{cr-id}}

- requested_by: {{fixer-or-author-instance}}
- module_id / freeze_id / code_baseline: {{refs}}
- causing_event / diagnosis: {{refs}}
- status: proposed

## Problem / Evidence
{{冻结契约无法满足或有歧义的原因、复现、真实日志}}

## Proposed Change
{{当前→建议行为；REQ/design/tasks/checklist/test-design 的具体定义差异}}

## Impact
{{受影响模块、DAG/锁、CASE/PATH、代码/数据/外部 API 与必须失效的证据}}

## Regression / Rollback
{{重跑集合、覆盖保证、回滚步骤；不能靠删除失败路径通过}}

## Decisions
- Spec-Designer impact analysis: pending
- Module-Orchestrator review: pending
- Human decision if semantic/core architecture change: pending
- New revision / manifest / freeze acceptance: pending

批准前不得实施受 CR 影响的语义变化；纯实现补丁不需要为每个修改建立 CR。

## Decision Envelope Classification
- change_class: {{evidence-only|within-envelope|outside-envelope}}
- prior_execution_baseline / proposed_plan_hash: {{hashes}}
- envelope_diff / acceptance_diff: {{具体差异或 none}}
- owner_module_id / owner_role: {{routing}}

within-envelope 仍需 Spec-Designer 修订、MO 审查和新执行 freeze；不得由 Fixer 直接改 tasks。
