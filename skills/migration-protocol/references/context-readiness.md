# 上下文就绪：按控制节点核对、验收与恢复

## 总则

新运行在 GO 发现/规划、父 MO 拆分、子 SPEC 冻结、Coding/Testing/Fixer 开工与 Auditor 分析/裁决/最终验证前，执行本协议。实际执行实例先核对并经 Ledger 留证：规划与审计的报告由原控制节点接受；worker 接到派发后提交，ready 报告才授权开工。缺项不得执行，必须补齐或显式记录该模块阻塞，无关模块继续。

## 1. 原则

同 Run 保留冻结的模块，执行阶段从 execution_context_ref 读取已接受上下文与分配；当前全局输入用于新规划。

全局可读、引用有效不等于子任务已经具备执行条件。每个阶段由实际执行角色核对所需内容并经 Ledger 留证，再由既有控制节点接受。执行者自己随后提交的操作（register、global-plan、decompose、plan、audit-plan、audit-verdict、audit-code-review、source-review）携带 context_ref 即随操作登记（游标 `with_operation=true`）；worker 阶段（coding、building、testing、fixing）在派发之后 `context-submit`：ready 报告绑定该派发并授权开工，blocked 报告退回派发；audit-testing 仍由 Auditor 在 audit-assign 前提交。报告是可追溯的理解与环境证据，不代替 SPEC 冻结、权限、测试或 DoD，不新增人工会签。

预检**只读**：允许读获授权材料、写自身 staging、提交 context-submit；报告未被原节点接受或未绑定派发前，不允许改目标代码或执行目标构建/测试。预检和正式执行是同一实例；换实例必须重新核对。宿主继续承担身份认证、工具可用性和文件写隔离。

## 2. 精确插入节点

| 控制节点 | stage / 提交角色 | 核对内容 | 接受节点与责任 |
| --- | --- | --- | --- |
| prepare / Ledger init 后、根模块登记前 | global-discovery / GO | 全局需求与用例来源、存量/目标代码、架构/知识、TARGET/外部来源、宿主能力 | register，GO；初始化分析结果先 staged，正式登记前留证 |
| 父 MO 拆分前 | decomposition / 父 MO | 全局/父范围、源码入口、共享接口、唯一 owner、复用来源、所需子上下文 | decompose 提案绑定；GO decompose-accept 复核同一报告 |
| 子模块全部登记后 | global-planning / GO | 全局需求/CASE 覆盖、分工/接口契约、复用 owner | global-plan，GO |
| design assign 后、随设计 submit | test-design / Test Runner | assigned-scope/spec-cases/task-coverage/independence；必读 design_input_ref 的规格/CASE/tasks | submit 绑定本实例与结果 draft_ref；MO accept(review_ref) 再验，无代码/设备前置 |
| 子 MO 组织正式 SPEC/测试设计 | planning / Spec Designer | 全局/父/子范围、source_closure、target_feasibility、接口、CASE/PATH、复用映射 | plan 绑定草稿；子 MO freeze 再验当前报告与同一 plan_ref |
| Coding 派发后、开工前 | coding / Implementer | 冻结 SPEC/tasks、完整生产链路、目标可行性、共享接口、复用接线、工具/读写授权 | ready 报告绑定 assign 后开工；锁、依赖、版本门禁在派发时执行 |
| 构建派发后、执行前 | building / Test Runner | 已接受代码、冻结构建命令、目标/JDK/SDK/Gradle 环境、工具与权限，不要求自动化设备 | ready 报告绑定 assign(test_scope=build) 后执行 |
| Main 派发后、执行前 | testing / Test Runner | 需求与 PATH、已接受代码、真实提供方、适配器、环境/数据/账号条件、工具与权限 | ready 报告绑定 assign 后执行；执行器再核对批准 argv/cwd/环境证据 |
| 首轮或审计 Fixer 派发后、修复前 | fixing / Fixer | 冻结契约、TASK、接口、复用映射、失败 PATH/assert、当前诊断、历史尝试/预算、最小修复范围 | ready 报告绑定 assign 后修复并计一轮，缺上下文不消耗修复轮次；必须确认已读诊断报告（diagnosis_ref 为必读输入）。fixing 预检绑定诊断内容本身，MO 接受诊断前后均可提交；diagnosis-accept 可带 assign 一步派发 |
| 全部 MO 收尾、收集遗留后 | audit-analysis / Auditor | 父汇总、finding、各相关 SPEC/PATH、依赖 owner、复用映射和独立性 | Auditor audit-plan；GO 后续审核路由 |
| 修复批次裁决前 | audit-verdict / Auditor | 当前汇总/遗留、SPEC/PATH、每个验证结果与受阻根因、独立性 | Auditor audit-verdict；不以预检 ready 代替验证结果 |
| 遗留路径独立复核前 | audit-testing / Auditor | 当前汇总、SPEC/PATH、代码与真实提供方、完整环境、独立性 | Auditor 自核就绪，GO audit-assign 绑定该实例；测试验收仍唯一归 Auditor |

审计复测先由独立 Test-Runner 提交 audit-execution ready 预检，再由 GO audit-test-assign；不沿用 Auditor 的预检。审计期间下游 Fixer/Testing 仍分别通过 fixing/testing，不沿用 Auditor 的报告。

## 3. 报告与传递

模板：[context-readiness.json](../../../template/context-readiness.json)。stage、subject_sha256 与必需检查项取自步骤视图（`status --view step`）的 `context`；checks 的键必须与其 required_checks 完全一致。同一文件被多次引用时，在报告顶层 `refs` 写一次，`evidence_refs` 写其 id。

报告包含：

- `schema_version/run_id/module_id/stage/producer`：实际身份与作用域；全局 module_id=null。
- `subject_sha256`：复制 `context.subject_sha256`；绑定分配、冻结、代码、依赖或审计批次，不绑定无关兄弟的进度。
- 必读输入由 Ledger 从状态派生（步骤视图给出 `input_count` 与 `inputs_sha256`），报告不列：ready 报告绑定该摘要，任一输入变化或漂移即过期，须重读重报；读过什么由 checks 的具体摘要与证据说明。worker 只读所需：Test-Runner 为冻结计划与测试资产；Implementer/Fixer 另含本叶子四维分析、架构/项目规则/知识，Fixer 再含诊断。分配包的存量源码按条目 source_locator 取用，不整份读。
- `draft_ref`：global-plan/decompose/plan/audit-plan 必须绑定正在提交的同一 plan_ref。
- `checks`：每项 `status=ready|blocked`、具体理解摘要；ready 必须给 evidence_refs，blocked 必须给 missing/owner/next_action。
- `verdict`：任一检查 blocked 则必须 blocked；无可复用库、无历史修复或无依赖可在 ready 中记录“不适用的事实与依据”，不编造材料。
- `execution`：building/testing/audit-testing 的 ready 报告必填 argv、绝对 cwd、environment_ref；说明工具版本、构建、设备/服务、fixtures/账号可用性、seed、重置/清理方法。秘密值不入报告。

先在自身 staging 写报告，再按本地 CLI 提交：

```json
{
  "operation": "context-submit",
  "module_id": "M001",
  "payload": {"report_ref": {"path": "/workspace/migration/.sdd-runs/run-demo/staging/context.json", "sha256": "<actual-sha256>"}}
}
```

仍需完整 request 信封及宿主绑定 principal。worker 的报告与它的活动派发同阶段时由 Ledger 直接绑定，无需再引用；没有派发时报告只留证，下次派发同一实例时自动绑定其当前 ready 报告。随操作登记的报告作为该操作的 context_ref；freeze/decompose-accept 自动使用原提案接受的引用。Ledger 保存 `context_receipts` 与 `context_acceptances`，不存在另一份可手改的权威状态。

## 4. 检查内容必须具体

- **source-closure**：入口→调用链→状态/数据→可观察结果，包含正常/边界/异常、必要生命周期和生产绑定，不能只有目录名。
- **interfaces-ownership**：接口入口、输入输出模型、错误/取消语义、初始化顺序、提供方/消费方、文件 owner、允许修改范围；未决业务边界或需求/验收/授权变化仍交人工。
- **reuse-mapping**：读取冻结的需求→能力→TASK/PATH、差异、版本、接线；没有匹配候选要有评审依据。
- **复用 fidelity（沿用现有检查项）**：GO/父 MO 的 reuse-sources 核对存量功能与候选的对应关系；planning/coding/fixing/audit-analysis 的 reuse-mapping 核对 fidelity 的存量基线、对齐报告、复现方案及 PATH/ASSERT。Testing 的真实提供方核对与 Auditor 的 spec-paths/验证结果核对必须包含保真断言、实际结果及未决差异；不新增独立状态或把规划 ready 当成复现通过。见 [全局保真规范](reuse-dependencies.md#7-全局保真规范复用必须复现存量功能)。
- **test-environment**：实际可用的命令、依赖服务、测试数据和部署构建；编码前只可静态核查可行性，不得提前跑目标测试。
- **failure-diagnosis / repair-history**：本次失败证据、当前根因、已试策略及效果、剩余预算与适用的 memory；没有历史尝试要明确。
- **permissions-tools / host-capabilities**：宿主确认实际可读/可写范围、角色 skills、工具和隔离能力；提供全局视野不扩大写 scope。

规划阶段不要求实现或测试已经完成；审计分析中发现 SPEC/代码缺失，可以将“缺失已定位，必须走 human 恢复”作为分析结论，不能因此批准 Fixer 或 Main。

## 5. 缺失、失效与恢复

`status.next_steps/global_next_step.context_gate` 展示当前必需 stage、检查项及可用报告；已派发但未授权的 worker 步骤（await-result）同样带出所欠的报告。worker 的 blocked 报告退回派发（尚未授权执行，无需停止证据），游标 reason=context-blocked：补齐后由 worker 重新提交 ready 报告，或按原因挂起；该实例当前仍 blocked 时 assign 被拒。审计派发因 context-readiness-required 未就绪时，宿主启动 Auditor 预检，不得把它当作全局无工作可做。

blocked 报告提交会保留缺失项，但**不会自动将整个 MO 标记收尾**。例外分流：当前构建通过且仅自动化 test-environment 缺失时，游标提示 automation-unavailable；MO 接受后进入 automation-deferred，保留 Yellow/未执行并允许其他可执行任务继续，不要求人工批准。最终审计同类问题使用 audit-unavailable。见 [双环节协议](build-automation.md)。责任编排者必须继续补材料，或基于本模块实际原因提交已有 suspend（dependency/human/tooling）；已确认依赖/外围问题符合 audit-defer 条件时走该分支。审计修复中的阻塞经 audit-block 进入相关 finding 的人工报告。缺失不伪造失败测试，未执行路径仍为未执行；保留 Yellow 原因和恢复条件。

同 stage/实例的最新报告覆盖可用索引，旧报告留在事件历史；最新 blocked 不能被旧 ready 绕过。草稿、已选提供方、证据、代码或分配变化后重新核对。原计划需要变更时仍经 CR/重新冻结；freeze 依据失效时重新提交 plan 与对应报告。恢复后新报告通过不直接 Green，仍须正式执行、复测与验收。

无关模块继续；收尾规则仍为所有叶子本轮完成/明确挂起、父汇总有效、无 worker/可推进动作。

## 6. 实现范围

上下文就绪是必选门禁，prepare 强制启用，运行中无切换开关。

控制器验证角色、作用域、必读输入摘要、检查项、摘要、草稿、版本、身份和正式操作门禁；测试执行器校验 argv/cwd/环境证据。它不能自动证明语义理解充分、账号真实可用或 OS 已隔离，这些仍须执行者提供真实证据、宿主落实并由对应 owner 审核。

## 功能清单来源与完备性

global-discovery/global-planning/decomposition/planning 必需检查 feature-inventory。GO 先形成完整功能草案，父 MO 核对子清单；global-plan 接受最终清单与执行叶子归属后，planning_context 和 module_inputs 提供 feature_inventory_ref/feature_ids，后续预检将清单作为必读输入。疑问不是 ready，须按 [功能发现与完备性规范](../../migration-global/references/slicing.md) 交人工。

同一 assignment 需运行多个构建命令或最终审计混合路径时，可在 execution.commands 按 path_id 保存各自 argv/cwd；环境证据仍由 environment_ref 绑定。execute_test 逐路径校验该命令，build 另核对冻结 command。

收尾 audit-assign 的阶段由 Ledger 实际选集决定：有路径用 audit-testing；无待验证路径用 audit-verdict，仅核验已接受证据与独立性，不要求设备/自动化环境。空 global_paths 不影响此选择。见 [审计范围协议](audit-scope.md)。

## Auditor 代码审查预检

`audit-code-review` 是全部 MO 收尾后的首个独立审计动作；检查项见步骤视图，draft_ref 绑定代码审查报告，无需自动化运行环境。后续 audit-analysis/verdict/testing 同时读取已提交的代码审查报告。见 [代码治理协议](audit-code-review.md)。
