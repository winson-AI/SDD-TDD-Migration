# {{module-id}} Design

## Context
{{全局规范/架构/legacy 基线引用；相关模块接口}}

## Goals / Non-Goals
{{功能与技术范围；批准的行为保真/差异}}

## Legacy → Target Mapping
| Legacy 路径/符号与证据 | 行为 | Target 架构/路径 | 保留/替换/删除依据 | REQ-ID |
| --- | --- | --- | --- | --- |
| {{legacy-ref}} | {{behavior}} | {{target-ref}} | {{decision}} | {{req-id}} |

## Decisions
{{候选方案、选择及理由；接口入出参/错误码、数据模型/状态、鉴权、兼容性与资源释放}}

## 埋点上报（条件适用）

{{applicable / not-applicable 及范围内源码检查依据。N/A 到此结束，不加 SDK/环境/空任务；适用时引用 telemetry-analysis.md 的实例，记录事件/参数/触发/禁止条件、真实 provider 接线与版本、实际已有失败/重试语义、任务/消费者及 emitted/sdk-dispatched/server-received 验收层级，绑定 stage-plan.telemetry 与 PATH/ASSERT。}}

## Dependencies / Resources
{{DAG 上游、契约版本、owner、唤醒条件；源码/公共文件/测试环境读写锁}}

## Test Design
{{正常/边界/异常路径、参数化、真实集成范围、允许 Mock 的外部边界；Main 适配器及构建/静态检查要求}}

## Risks / Rollback
{{数据迁移/一致性/性能风险、回滚条件与操作；禁止仅写“无风险”}}

## Open Questions / Decisions
{{question_id、人工答案引用、影响范围；不得保留未决阻断问题进入冻结}}

## Source Closure / Target Feasibility
{{入口、状态/数据/平台执行链、可观察结果和真实生产绑定的 path/symbol/hash；当前切片依赖的已解析版本、reuse/port/approved-alternative/blocked 路线、未决风险；证据与当前源码版本一致}}

## Decision Envelope
{{scope / acceptance / allowed_alternatives / forbidden_changes；用户批准的替代方案必须具体；不允许以“可优化”之类泛化措辞绕过验收变更}}

## UI → Logic → Adhesive → Resource

模块/子模块先确定 scope，再按顺序逐维填写适用性、N/A 理由及证据；任务也先划 scope，再填写任务四维分析及具体实现指导；关联冻结 dimension_analysis_ref。适用项逐 item ID 说明源行为闭包、架构位置、二方库/目标已有能力决策与差异、真实接线、实现 owner 及 PATH/ASSERT。Resource 明确源素材/目标访问器/生产消费者及 qualifier；本节与调度资源锁分开。
