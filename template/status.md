# {{module-id}} Status

仅 Ledger 物化的视图，禁止 Agent 直接编辑；以下为可机读 JSON 状态块，读取时解析 JSON，不搜索 Markdown 勾选。

```json
{
  "schema_version": 1,
  "run_id": "{{run-id}}",
  "module_id": "{{module-id}}",
  "revision": 0,
  "last_sequence": 0,
  "phase": "context",
  "execution_status": "pending",
  "quality": "yellow-blocked",
  "reason_code": "untested",
  "root_cause": {"category": "untested", "summary": "尚未完成验证", "confidence": "confirmed", "next_action": "read-context"},
  "freeze_id": null,
  "code_baseline": null,
  "current_assignment": null,
  "resume_phase": null,
  "fix_rounds_used": 0,
  "yellow_retries_used": 0,
  "no_progress_rounds": 0,
  "input_refs": [],
  "output_refs": [],
  "unresolved_paths": [],
  "dependency_refs": [],
  "question_refs": [],
  "decision_refs": [],
  "change_request_refs": [],
  "next_action": "read-context"
}
```
