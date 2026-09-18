## ADDED Requirements

### Requirement: {{requirement-name}}
REQ-{{module-id}}-001: The system SHALL {{可观察的行为及边界}}.

#### Scenario: {{normal-path-name}}
- **GIVEN** {{前置条件}}
- **WHEN** {{触发行为}}
- **THEN** {{可断言结果}}

#### Scenario: {{boundary-or-error-path-name}}
- **GIVEN** {{边界/异常前置}}
- **WHEN** {{触发}}
- **THEN** {{可断言结果与错误语义}}

<!-- 实例化到 specs/<capability>/spec.md。按实际差异选择 ADDED/MODIFIED/REMOVED，删除本说明；MODIFIED 给完整最终需求，REMOVED 给理由/迁移路径。不得为了填模板虚构行为变化。ID 与 case/path 的映射放到追溯工件。 -->
