# Diagnosis {{diagnosis-id}}

- run / module / path / test_run: {{ids}}
- code / spec / environment: {{version-refs}}
- observed_quality: {{red-bug-or-yellow-blocked}}

## Symptom
{{实际 expected/actual、日志、最小复现 query}}

## Root Cause
- category: {{code|dependency|environment|test|spec|tooling|unknown}}
- summary: {{因果描述}}
- confidence: {{confirmed|suspected|unknown}}
- evidence_refs: {{绝对路径与摘要}}
- alternatives_ruled_out: {{排除依据；未排除明确写 unknown}}
- suspected_owner: {{模块/角色}}
- dependency_chain: {{生产者→契约版本→消费者；不适用写 none}}

## Next Action
{{最小修复方向 / CR / 依赖申请 / 人工决定；必须复测的 PATH-ID；诊断者不实施修改}}

## Owner Routing
- owner_module_id: {{module}}
- owner_role: {{fixer|spec-designer|global-orchestrator|host}}
- decision_envelope_impact: {{none|possible|confirmed}}
- resume_session_ref: {{session-or-null}}
- checkpoint_ref: {{ledger-reference}}
