# Audit {{run-id}} / {{audit-id}}

## Frozen Snapshot
- Auditor instance / independence evidence: {{refs}}
- Ledger sequence: {{sequence}}
- Code tree / SPEC manifest / test definitions / environment: {{hashes}}
- Participant modules / global cases: {{complete-list}}

## Coverage
| 范围 | 必需路径数 | 执行数 | Green | Red | Yellow（含未执行/过期） |
| --- | --- | --- | --- | --- | --- |
| {{module-or-global}} | {{n}} | {{n}} | {{n}} | {{n}} | {{n}} |

## Non-Green and Retests
| PATH-ID / Name | 原 test_run | 原状态/根因 | 本轮 test_run / baseline | 新状态/断言证据 | next_action / owner |
| --- | --- | --- | --- | --- | --- |
| {{path/name}} | {{old}} | {{quality/cause}} | {{new}} | {{result}} | {{action}} |

## Repair Delegation / Rounds
{{repair_requested → MO acceptance → Fixer patch → independent retest；已用轮次、停滞判断、版本失效/重跑集合}}

## Global Tests
{{整体测试及跨模块真实集成的 query、版本、断言与日志；不能只列模块单测}}

## Verdict
- quality: {{green-passed|red-bug|yellow-blocked}}
- unresolved: {{完整剩余问题，空必须有全覆盖证据}}
- conclusion: {{本次实际验证的范围与限制}}
- next_action: {{继续修复/人工介入/等待交付批准}}

最终通过须绑定同一最终快照；修改后的旧 Green 若受影响必须复测。
