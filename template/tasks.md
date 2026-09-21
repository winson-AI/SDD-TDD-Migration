# {{module-id}} Tasks

定义作者：Spec-Designer；正式写入：Ledger。完成勾选仅来自 MO 接受的任务证据；冻结定义保存在不可变 artifacts。

## Implementation
- [ ] TASK-{{module-id}}-001 {{可执行任务名称}}
  - Requirements: {{REQ-ID 列表}}
  - Cases / Paths: {{CASE-ID / PATH-ID 列表}}
  - Depends on: {{任务 ID 或 none}}
  - Read scope: {{绝对 legacy/契约路径}}
  - Write scope: {{绝对 target 路径与锁资源}}
  - Action: {{具体改动，明确目标架构}}
  - Done when: {{可核验结果、静态检查/测试要求}}
  - Evidence: {{接受后的 code_commit/tree hash 与事件；冻结时填 pending}}

## Traceability
| REQ-ID | 设计章节 | TASK-ID | CASE-ID | PATH-ID | 源文件 | 代码版本 | 证据事件 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| {{req}} | {{design}} | {{task}} | {{case}} | {{path}} | {{file}} | pending | pending |

## 四维追溯规则

先定义每个 TASK 的 scope.in/out/write_paths，再逐任务按 UI → Logic → Adhesive → Resource 分析适用性、源码依据和具体 implementation，使用 scope_sha256 绑定范围。每个可执行 TASK 关联至少一个认领的 DIM item ID；全部 applicable item 必须在任务定义中出现，配套 CASE/PATH/ASSERT。跨维度任务可合并；not-applicable 不生成空任务，依赖决定实际执行顺序。

## 埋点职责（条件适用）

逐 TASK 标 applicable 或 not-applicable 并说明认领范围内依据。仅适用任务填写事件 ID、源→目标参数/触发/生产接线、冻结 PATH/ASSERT/观测层级；无埋点任务不创建事件或空测试。同模块可混合两类任务，参见 [telemetry-analysis.md](telemetry-analysis.md)。
