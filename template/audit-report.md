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

## Scope Selection
- policy: non-green-only
- collected_red_yellow: {{PATH IDs、原 test_run、SPEC/CASE 引用}}
- affected_regression: {{finding → owner/依赖边 → 受影响模块/路径；没有则空}}
- retained_green: {{未重跑、仍有效的已有证据引用}}
- optional_global_paths: {{已声明但未验证/失效/非 Green 的额外路径；允许空}}
- execution_status: {{reviewed|no-retest-needed|completed-with-unverified-tests}}

无待验证路径时只记录独立审阅，不填造本轮 test_run；不得默认重跑全部测试。

## Verdict
- quality: {{green-passed|red-bug|yellow-blocked}}
- unresolved: {{完整剩余问题，空必须有全覆盖证据}}
- conclusion: {{本次实际验证的范围与限制}}
- next_action: {{继续修复/人工介入/等待交付批准}}

最终通过须绑定同一最终快照；修改后的旧 Green 若受影响必须复测。
