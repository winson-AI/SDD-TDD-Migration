# Escalation {{question-id}}

- run / module / phase: {{refs}}
- reason_code / root_cause: {{reason}}
- spec_revision / subject_sha256 / code_baseline: {{version}}
- owner / deadline: {{human-owner-and-time}}
- status: pending

## Impact and Evidence
{{受影响 PATH/模块；阻塞证据；已尝试修复及剩余预算}}

## Decision Needed
{{一个可独立理解的阻断问题}}

| 选项 | 影响 | 推荐依据 |
| --- | --- | --- |
| {{option-a}} | {{impact}} | {{reason}} |
| {{option-b}} | {{impact}} | {{reason}} |

## Feedback / Resume
{{真实用户答复引用；对应 human-decision.json；允许恢复的阶段与复测要求}}

到期仍 pending，由 Escalation 记录超时升级；沉默不代表批准。存在已授权且与当前版本一致的答案时引用原记录，不重复索要。
