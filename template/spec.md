## ADDED Requirements

### Requirement: {{requirement-name}}
Requirement-ID: REQ-{{module-id}}-001
REQ-{{module-id}}-001: The system SHALL {{可观察的行为及边界}}.

#### Scenario: {{normal-path-name}}
Scenario-ID: SCN-{{module-id}}-001
- **GIVEN** {{前置条件}}
- **WHEN** {{触发行为}}
- **THEN** {{可断言结果}}

#### Scenario: {{boundary-or-error-path-name}}
Scenario-ID: SCN-{{module-id}}-002
- **GIVEN** {{边界/异常前置}}
- **WHEN** {{触发}}
- **THEN** {{可断言结果与错误语义}}

<!-- 实例化到 specs/<capability>/spec.md。按实际差异选择 ADDED/MODIFIED/REMOVED，删除本说明；MODIFIED 给完整最终需求，REMOVED 给理由/迁移路径及可验证的删除/替代 Scenario。每项 Requirement/Scenario 恰好一个独立行 ID；Scenario-ID 在 run 内唯一，重命名标题保留 ID。不得为了填模板虚构行为变化。scenario_index 从本文件派生，TASK/PATH/ASSERT 映射放到 stage-plan.scenario_trace。 -->

<!-- 埋点条件适用：无埋点在 design/checklist/telemetry 索引记录有据 N/A，不增加空 Requirement/Scenario。有埋点则在实际需求的 Scenario 中写明触发/禁止触发、源→目标事件/参数、次数与验证层级，绑定已分配 CASE/PATH/ASSERT；不把截图或构建通过写成上报成功。 -->
