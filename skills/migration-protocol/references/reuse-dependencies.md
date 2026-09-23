# 二方库与已有能力：语义抽取、需求映射和依赖验证

## 1. 作用与边界

复用分析是迁移规划的必经输入。下游 Coding 同时依据 **冻结的模块需求/tasks、目标架构、经过审核的能力映射**；已有库的行为不能倒过来削减需求或替换验收标准。

本流程统一处理两类来源，保留来源区别：

- **目标项目已有能力**：业务模块、公共服务、已接入的二方库及其封装。自动纳入 `TARGET` 检索范围，优先检查已存在的生产实现，避免重复迁移。
- **用户指定的其他项目模块/二方库**：作为显式外部复用来源，读取其指定模块，提取同样的功能语义。存在源码只说明可以分析；能否直接依赖、适配接入或只作为语义参考，必须独立核实。

二方库在这里是组织内部维护的可复用组件；任意外部项目源码不自动成为已发布、可接入的库。`reuse` / `adapt` 表示实际使用能力，`reference` 表示仅借鉴语义，`new` 表示评估后自行实现。目标已有实现优先评估，不强制采用不匹配的能力。禁止按类名、接口名或目录名相似直接宣称功能等价。

**目标已实现也必须检查冗余。** 阅读目标生产实现和可复用/已依赖二方库，结合存量功能对齐；确认存在重复实现且库能满足需求或经适配满足需求时，直接把范围内目标实现重构为二方库依赖复用/适配，不能因“已有代码”继续保留或新增重复业务逻辑。重构进入既有 tasks/冻结/Coding/Testing，具体节点与记录见第 9 节。

**不能直接复用时继续完成当前功能。** 结合已知上下文、存量源码、新架构与目标现状选择 adapt/reference/new，并落实到冻结 tasks 后启动 Coding；不能仅因缺少可复用二方库就挂起、跳过功能或等人工。“未实现”仅用于替代实现路线也经核验证实在当前约束下不可行的情况，入口见第 8 节。

读取复用来源不授予修改权限：外部来源默认只读；编码仍限 target 中获分配的 scope/write_paths。确需改提供方、改变公共契约或新增跨模块业务边界时，通过 Ledger 的 CR/依赖/人工决策机制处理，不能把外部仓库静默纳入本次迁移。

## 2. 用户输入、持久化与运行版本

项目配置 `reuse_sources` 为可选数组；留空也必须评估目标项目。用户可只描述其他项目的模块位置和用途，宿主整理成 [reuse-source.json](../../../template/reuse-source.json)：

```json
{
  "reuse_sources": [
    {
      "source_id": "LIB-SEARCH",
      "root": "/work/SharedCommerce",
      "module_paths": ["/work/SharedCommerce/search"],
      "description": "可复用的商品检索、分页和筛选能力"
    }
  ]
}
```

`source_id` 唯一且不能为保留 ID `TARGET`；路径为绝对路径，module_paths 必须包含于 root，省略时使用整个 root。外部选择范围与 target 分离；可以共用一个 monorepo 根目录，只要显式选择的模块不与 target 相交。完整目录结构不代表获准扩大功能范围。

沿用项目上下文 init/update/prepare：数组整体替换，null 删除配置；更新影响新运行，不改旧快照。已登记 source_id/root/module_paths 固定；同 run 仅可通过 [来源追加事务](source-changes.md) 追加新 ID，生成新快照并进行影响评审。源代码不全文复制。GO 的语义报告、目录、映射通过 Ledger 版本引用留档；选中的 provider/API/版本解析证据用绝对 path/sha256 固定并在运行时复核。仓库 commit 可辅助定位，不能替代未提交改动、锁文件及实际 API 文件的内容证据。

`status.planning_context.reuse_sources` 同时包含隐式 TARGET 和声明的外部来源，父/子 MO 均可见。未能访问用户指定来源时明确阻塞并请求补全，不能写成“已扫描无匹配”。本地 prepare 检查路径可用性；远程坐标/仓库需宿主先取得可读模块/API 材料，本控制器不会自动下载依赖。

## 3. 按三层编排提取与细化

| 阶段 | 责任 | 必需输出与门禁 |
| --- | --- | --- |
| GO 全局准备与切片 | 将 legacy 需求、目标架构与 TARGET/外部来源一起分析；识别现有公共能力、稳定提供方及消费关系，再划模块 scope | 全局 `reuse-catalog.json` 与抽取报告；经 context_refs 分发。每个声明来源有已评审结论；无候选也有搜索依据 |
| 父 MO 认领与子模块划分 | 读取全局目录，按认领模块的业务需求筛选/补充语义；复用公共能力，统一适配 owner，划分消费者与缺口任务 | 子 scope/context_refs 带适用能力及初步需求映射；避免每个孩子各写一套相同封装；GO 接受相关 DAG/写集合 |
| 子 MO + Spec Designer | 在子功能范围内核验候选，逐条需求形成 `reuse-plan.json`，允许有依据地拒绝候选；形成设计与 tasks | requirement → capability/decision → task → PATH，连同接入路线和真实验证要求进入冻结 plan |
| Implementer / Fixer | 读取冻结映射和语义差异，完成依赖声明、版本解析、DI/入口绑定、适配层或新实现 | 原 Task Trace + reuse_trace + 实际版本/绑定证据；不能临时改提供方、行为契约或以 mock 替代生产实现 |
| Test Runner / 子 MO | 依据需求设计断言，验证复用接线及完整业务路径 | 实际提供方集成测试、适配差异回归、完整模块 DoD；编译/导入成功不等于功能 Green |
| Auditor | 所有 MO 收尾后，聚合依赖和能力映射，检查共享提供方影响，委派 Fixer、Testing 并独立裁决 | 新提供方版本/接线变化使相关消费者旧结果失效；按依赖图复测 owner/source/中间与下游；失败保留根因待人工 |

GO 可以先做粗粒度能力目录；父/子 MO 补充与本模块相关的语义证据，形成新的版本化目录引用。目录不等于冻结批准。不要为无关候选全文扫描所有项目；扫描范围、搜索词/调用链和不适用理由写入报告。所有层级的交接只经 Ledger 引用。

新 v2 目录显式记录 provider_owner_module_id 和 ownership_evidence_ref；消费者仅依赖明确的本轮提供方 owner，等待其稳定后使用实际版本。write_paths 只约束修改权限与互斥，不推断 v2 业务归属。现存稳定库使用经评审的 null owner，不应虚构永远等不到完成事件的模块依赖。旧 v1 保持原写范围推断校验，升级需重新规划/冻结；字段与变更闭环见第 10 节。

## 4. 语义抽取必须回答什么

[reuse-catalog.json](../../../template/reuse-catalog.json) 每个 capability 提供稳定 ID、来源、实际版本/API 证据及以下语义：

1. **业务意图**：完成什么用户行为、可观察结果是什么；沿真实入口→状态/数据→输出定位，不能只有 API 摘要。
2. **输入/输出**：模型、单位、空值、默认值、分页/排序、同步/异步语义。
3. **前置条件与状态**：认证、权限、初始化、缓存/持久化、状态所有权、线程和生命周期。
4. **副作用与失败**：网络/存储副作用、异常、超时、取消、重试及幂等；无副作用也显式写明。
5. **接入约束**：公开入口、版本、平台/框架/API 或 ABI、传递依赖、依赖注入、生产环境绑定，以及与目标架构的兼容性。

报告引用真实源码、API 文档、manifest/锁文件和调用链。抽取是 Agent 的语义分析能力，控制器只检验结构、范围和引用，不能自动证明语义等价。冻结前不执行目标业务测试；可通过阅读源码/API、配置和已有证据判断可行性，Coding 后再正式运行 Main 验证。

## 5. 需求映射与 OpenSpec

使用 [reuse-plan.json](../../../template/reuse-plan.json)，覆盖该子模块的每条全局需求 ID：

| decision | 含义 | Coding 指导 |
| --- | --- | --- |
| reuse | 语义和目标架构兼容，可直接使用 | 指明实际入口、版本、初始化/DI、消费者；保留完整业务验证 |
| adapt | 可复用核心能力，但有明确模型/协议/生命周期差异 | 把匹配点、缺口、转换及额外行为写进 behavior_delta，拆独立适配 tasks 和回归路径 |
| reference | 其他项目能力不能直接接入，但其业务语义有价值 | integration.mode=reference-only；提炼规则，在目标架构内实现，不宣称存在运行时库依赖 |
| new | 经过评估无合适能力，或采用候选会违背需求/架构 | capability_id=null；解释搜索/拒绝理由与剩余实现范围，不能省略评估 |

每条映射含 rationale、behavior_delta、binding_plan、verification、task_ids、path_ids；后三种情况不能通过弱化验收消除差异。实际使用时记录 integration.mode（existing-target/package/source-module/reference-only）、locator、版本、配置、传递依赖和兼容证据。源码引用方式不等于源码复制授权；新增依赖仍遵守项目规则和原有边界决策。

OpenSpec 分工：proposal 说明复用策略和缺口；spec 保持用户可观察行为；design 说明提供方与适配边界；tasks 落接线/适配/剩余实现；checklist 核对映射覆盖、版本、生产绑定及测试；status 引用当前冻结 plan 与依赖问题。`stage-plan.reuse_plan_ref` 将目录和映射纳入 plan 摘要、人工冻结及后续 CR。change/reuse.md 投影当前已接受的 plan；冻结前仅供规划阅读，不表示可以编码。

新 prepare 运行自动要求复用规划；显式外部来源、所有新的子 MO 计划也要求。旧扁平 run 未启用 reuse_required 时兼容原有输入；新的 global-input 默认 reuse_required=true。不存在可复用能力时提交空 capabilities + 有证据的来源评审 + new 映射，不编造库。

## 6. Coding、测试与失败处理

Implementer/Fixer 对每个 reuse/adapt/reference 映射提交 `reuse_trace`：mapping_id、resolved_version、files（属于相应 task_trace）和 binding_evidence_ref。reference 记录借鉴语义落在哪些目标代码，不伪造运行依赖。new 映射由既有 Task Trace 覆盖。

Testing 至少验证正常、边界、异常/取消，以及真实提供方接线、版本/配置和适配差异；预期结果来自业务需求，不能照抄现有库行为充当验收。mock 可辅助诊断，缺少必要真实绑定测试时仍为 Yellow。整体用例和跨模块回归覆盖不能因使用二方库而缩小。

- 本模块接线/适配错误且可修复：保持 Red/Yellow 证据，按既有规则优先一轮 Fixer，再正式 Main 复测。
- 已确认提供方缺陷、依赖不可用、外围条件问题：记录 source/capability/mapping/version、影响消费者及根因，直接留待统一 Auditor；无关模块继续。
- 提供方、锁文件或接入证据发生变化：相关冻结依据失效，保留历史；提交新的版本化目录/映射，按 invalidate/CR/重新冻结恢复。不得原地改旧目录或只替换版本字符串复用旧 Green。
- Auditor 不修改二方库或业务源码；修复委派给合法 owner，外部源码未授权则人工处理或经批准选择新接入方案。复核失败输出根因和证据待人工，不无限重试。

当前脚本在 plan 验证语义结构/映射和来源范围，freeze/dispatch/结果接受/DoD/审计复核已选 provider 与接入证据 hash；未选候选变化不单独使消费者失效。实际包解析、依赖隔离、外部写保护、语义判断和运行测试仍由宿主/Agent/项目执行器完成。不要将结构检查称为完成了功能迁移。

## 7. 全局保真规范：复用必须复现存量功能

对 TARGET 和外部来源统一执行；`reuse`、`adapt`、`reference` 均不得跳过。以**存量源码项目对应功能的实际业务行为**为对齐基准，结合明确需求确认应保留的契约。提供方有类似功能、API 可调用、库自身测试通过，都不能证明本次迁移保真。源码中的偶然行为/缺陷与明确需求冲突时，Spec Designer 将差异交人工决定，经 Ledger/CR 冻结；不能自行照搬缺陷或接受库默认行为。

### 7.1 落到控制节点

| 节点 | 必须完成与保留的记录 |
| --- | --- |
| GO 发现/规划 | 按功能清单定位存量入口、调用链、可观察结果和必要状态；将候选库与该功能对齐。全局规范无开关，不要求用户额外填写保真材料 |
| 父 MO 拆分 | 子 scope/context_refs 带对应存量基线和候选差异；明确共享适配 owner、消费者及跨模块复现路径，不能因复用删除功能 |
| 子 MO / Spec Designer planning → freeze | 每个选中映射填写 fidelity；逐场景明确原行为、库行为与复现方案。差异落入 tasks，预期行为落入 SPEC，独立 Test Runner 将基线与验收转成 PATH/ASSERT。未决行为交人工；有差异但已有明确适配方案可冻结，不要求规划期已经通过运行测试 |
| Coding / Fixer | 按冻结对齐方案接线/适配，reuse_trace 留实际版本和绑定证据；不能用库的行为替换冻结预期。修复记忆引用 mapping/scenario、源行为、偏差、策略与复测记录 |
| Testing → MO 验收 | code accepted 后，用对应前置条件、输入/状态与真实生产提供方运行 Main；保存 expected/actual、断言与回执，验证结果、状态和副作用。全部必需路径及保真断言正式 Green 才验收 |
| 全量收尾 → Auditor | 读取各相关 SPEC、冻结对齐记录、PATH 和失败证据，沿共享库/适配器影响范围委派 Fixer 与 Testing；独立复核原功能是否复现。失败输出根因待人工；不以历史对齐结论代替本次复测 |

### 7.2 对齐记录与证据链

`reuse-plan.mappings[].fidelity` 包含：

- `legacy_root`：必须等于本轮 Ledger 的存量项目根目录。
- `legacy_source_refs`：该目录内真实入口/调用链源码的 path/sha256；不能以提供方源码冒充存量基线。
- `alignment_ref`：按 [reuse-fidelity.md](../../../template/reuse-fidelity.md) 形成的逐行为对齐报告引用。正常/边界/失败、默认值、输入输出、状态/生命周期、副作用等逐项核对，不适用项有理由。
- `scenarios`：稳定 scenario_id、legacy_behavior、reuse_behavior、reproduction_strategy，以及现有冻结的 path_id/assertion_ids；必须覆盖该映射全部 path_ids。scenario 通过 mapping 的 requirement_ids/task_ids 和 PATH 的 case_id 关联需求及用例，不另建验收状态机。

报告必须区分**源码分析得出的基线**与**已有真实运行证据**。规划/design 只读分析；不能为了完成对齐在代码生成前运行目标测试。已有存量运行轨迹可辅助固化场景；没有轨迹不能伪造，记录未执行/限制。源码与明确需求足以确定行为时可据此冻结；无法确定预期、基线缺失或存在疑问时先补材料/人工澄清。正式目标复现仍必须执行 Main。

复现不是要求新旧内部实现完全相同，而是满足冻结的业务可观察契约；数据/平台差异的转换及允许偏差必须有明确依据，不能用宽泛的“相似”替代断言。Test Runner 从已审核的存量契约与需求设计预期，不从目标实现或提供方返回值倒推验收。

记录链固定为：**存量源码引用 → alignment_ref → mapping/scenario → REQ/CASE/TASK/PATH/ASSERT → 冻结版本 → reuse_trace → Main 结果/回执 → MO 或 Auditor 裁决**。规划报告保持不可变；结果沿现有测试记录保留 test_run_id、freeze_id、code_baseline、环境、日志、expected/actual 和 execution_receipt，通过 PATH/ASSERT 关联。所有共享记录经 Ledger，不新建可手改的第二份通过状态。

### 7.3 失败、变化与实现边界

- 真实行为与冻结基线不符为 Red；缺真实提供方、数据、环境或无法证明为 Yellow，并记录根因/owner/next_action。可修复问题先一轮 Fixer 再 Main；已确认依赖/外围原因直接留待统一 Auditor，无关 MO 继续。
- 原源码基线、对齐报告、提供方/版本或接线依据改变，相关旧依据失效；按原 invalidate/CR/重新冻结和复测机制更新，保留旧证据。旧计划缺少 fidelity 时需补录并重新冻结，不能将历史 Green 宣称满足新增规范。
- 控制器在 plan 检查存量根、源码范围、引用及 PATH/ASSERT 覆盖，在后续 verify_plan 检查基线和报告漂移；既有测试门禁验证每条冻结断言的真实回执及 expected/actual。**结构和 hash 检查不能证明语义等价或对齐完备**，实际分析、场景质量及真实复现仍由角色/宿主负责，并由阶段验收 owner 审核。

## 8. 复用不可行 → Coding；确实无法实现 → “未实现”提醒

### 8.1 默认继续实现

1. GO/父 MO/子 MO 先明确当前功能目标、scope、需求/CASE，读取全局和本模块上下文、存量源码闭包、新架构、目标生产实现/资源/接线及已有分工。
2. 记录二方库不能直接复用的具体原因，评估适配、借鉴语义后实现、自主实现。至少一个路线可行时，由 Spec-Designer 将源码行为、目标差异、实现方案及完整测试映射到 tasks；在任务 scope 内做四维分析。`new` 不要求存在可复用 capability，不能虚构库依赖或等待不存在的提供方 MO。
3. 完成既有澄清/冻结后，MO assign Implementer，宿主真正启动 Coding；按目标架构完成真实功能。已冻结计划需要改路线时走 CR/影响分析及重新冻结，不能由 Implementer 私改 SPEC。已有批准范围内的普通实现选择无需新增人工会签；跨范围或业务预期不确定仍按原规则交人工。
4. Coding → build → automation → MO 验收保持完整。自主实现也要保留源行为、真实生产接线及完整断言；不能用 stub、mock、空返回、TODO 或删 CASE 代替交付。

### 8.2 核验后才能声明未实现

“库不能直接用”只说明候选路线不可用。若适配/参考/自主实现均有已证实障碍，记录**当前条件下具体未实现的功能**，不得声称永久不可能，也不要求为已证实的硬约束进行无意义编码尝试。

使用 [implementation-gap.json](../../../template/implementation-gap.json)，记录功能目标、已分配 REQ/CASE/TASK、当前 module_revision、全局规范/架构及代码根目录、上下文审阅、复用失败原因、三种替代方案及证据、实际实现尝试或约束核验结果。context_review_ref 应具体引用源入口/行为、新架构、知识内容、目标已有能力和缺口，不能只写“已了解”。未进入正式任务规划时 task_ids 可为空，不编造任务；有对应任务则逐项列出。

发现者通过本角色 `context-submit` 的 blocked 检查项 evidence_refs 引用核验材料，经 Ledger 交 MO；不得私传或直接写状态。MO 读取已提交材料并独立核验，按最新 module_revision 生成审阅后的报告。仍有可行路线则返回规划/Coding；确实不可行才接受下面的专用标记。

```json
{
  "operation": "suspend",
  "module_id": "M001",
  "payload": {
    "kind": "human",
    "reason_code": "not-implemented",
    "reason": "具体功能在当前约束下未实现：<已证实原因>",
    "root_cause": {"category": "capability", "summary": "<核验结论>", "evidence_refs": [{"path": "/workspace/migration/.sdd-runs/run-demo/staging/module-orchestrator/gap-review/verification.md", "sha256": "<actual>"}]},
    "owner": "module-orchestrator",
    "next_action": "<需要人工补充的能力、材料或架构/范围决策>",
    "implementation_gap_ref": {"path": "/workspace/migration/.sdd-runs/run-demo/staging/module-orchestrator/gap-review/implementation-gap.json", "sha256": "<actual>"}
  }
}
```

这是现有 suspend 的专用入口；外层仍补 run_id/request_id/expected_revision 和宿主身份。只允许 MO 接受，活动 worker 先真实停止并 revoke。控制器校验报告范围、revision、上下文、三种替代路线和证据；语义上是否确实不可行仍由 MO 审阅，字段齐全不能代替核验。

### 8.3 可见信号与恢复

- `status.workflow_progress.signals` 输出 `reason=not-implemented`、`label=未实现`、人工提醒、owner、next_action 和完整核验证据。宿主必须向用户展示具体功能及 REQ/CASE/TASK。
- GO 报告新增 `unimplemented` 清单和“未实现：需要人工决策”入口；对应路径标记 `implementation_status=not-implemented`。这是实现缺口标记，质量仍使用原 Green/Red/Yellow；历史测试不会改写为“本轮已实现”。
- 模块进入既有 waiting-human，旧证据失效；未执行仍 Yellow，历史真实失败保留。独立模块继续，全量收尾后 Auditor 读取该缺口和对应 SPEC/路径审查；缺代码不能伪造复测。不要用普通 dependency/tooling 文本隐藏已核实的未实现功能。
- 人工补充条件后按原 resume/invalidate/CR/重新冻结恢复，再 Coding 和正式测试。当前提醒随阻塞解除撤下，旧报告及事件永久保留；解除阻塞不代表功能已实现或测试 Green。
- 仅 automation 环境缺失使用 automation-unavailable；它表示功能缺少测试证据，不适用“未实现”入口。

## 9. 目标已有实现与二方库冗余：直接重构复用

适用于目标已经迁移、已有功能实现或已有相应测试的场景。GO/MO 必须实际读取目标代码及二方库源码/API、版本与调用链，比较功能语义、状态/副作用、失败行为及架构约束。类名相同不足以判定冗余；二方库存在符合当前需求的真实可用能力时，也不能仅因目标代码已存在而拒绝复用。

| 控制节点 | 必须执行的动作 |
| --- | --- |
| GO 评估/切片 | 将目标重复实现与二方库 capability 对齐，记录冗余位置、真实消费者、复用/适配可行性；功能及 CASE 保持完整，规划共享重构 owner 和受影响依赖 |
| 父 MO 划子模块 | 在认领 scope 内安排唯一 owner 负责公共适配与去重，消费者共享同一提供方；不能让多个子 MO 各保留一份重复实现 |
| 子 MO / Spec Designer 规划冻结 | 选择 reuse 或 adapt，将依赖接入、调用迁移、去重清理及回归覆盖拆进 tasks；四维分析覆盖受影响 UI/Logic/Adhesive/Resource，不能只替换接口声明 |
| Implementer / Fixer Coding | 按冻结任务直接重构目标：接入实际库版本，切换 DI/路由/消费者，保留必要的差异适配，删除被替代且确认无消费者的冗余实现、配置/资源；提交 task_trace、reuse_trace 和生产绑定证据 |
| Test-Runner / MO 验收 | 先 build 再正式业务测试；验证真实提供方调用、存量行为保真及受影响消费者，核验重复生产实现已移除或剩余内容确为必要适配；原测试随新接线调整执行入口，保留业务断言 |
| Auditor | 按既有遗留/受影响范围检查重构与共享依赖影响；问题委派 Fixer，独立复核，不能凭“换成二方库”判 Green |

### 记录与完成准则

复用对齐报告记录“目标冗余文件/符号 → 库 source/capability/version → 消费者 → 保留差异/适配 → 清理范围 → TASK/PATH/ASSERT”。沿用 reuse-plan 的 rationale、behavior_delta、binding_plan、verification 及 fidelity.alignment_ref；无需新增状态机或第二套验收来源。

- 可直接替代时选 `reuse`；有真实行为/模型/生命周期差异时选 `adapt`，适配层只实现必要差异，不复制库已经提供的业务逻辑。
- 重构完成要求所有受影响生产调用转到真实库/适配入口，重复实现已清理；必要兼容 façade 可保留并说明消费者/兼容理由。不能只增加库依赖而仍走旧实现，也不能保留两套等价实现长期并行。
- 清理代码前核对全局调用者及唯一 owner；状态持久化、数据格式和公共契约保持冻结语义。已授权范围且符合冻结任务时直接执行，无需因“重构”额外询问人工；冻结路线需变化则先走 CR/重新冻结，跨模块边界或行为不确定仍按原人工决策规则处理。
- 已有测试用于补充回归依据，不能删除失败断言或以库自测替代目标完整业务验证。自动化环境缺失仍 Yellow/缺测，不宣称重构已通过功能验收。
- 库实际不兼容或无法接入时，记录具体证据，按第 8 节继续适配/参考/自主实现；不能为消除表面重复削弱需求，也不能以没有评估过的“不适合”为由重复造轮子。

是否存在业务冗余、适配是否必要及调用链是否穷尽由 Agent 审查；现有脚本校验版本、范围、映射和证据，不自动证明代码已经完成语义去重。

## 10. 显式 provider 归属与合法版本变更

新 reuse-catalog 使用 schema_version=2。每个 capability 必填 provider_owner_module_id（null 或叶子 Mxxx）及 ownership_evidence_ref；缺失不等于 null。null 表示经 GO/MO 评审的现有稳定基线，非空表示本轮交付/变更的唯一叶子 owner。外部来源只能 null；指定 owner 必须存在、不是父节点，所有 provider_refs 位于其写权限内；消费者须登记该 owner 依赖，自身 owner 不需自依赖。依赖环、无效 owner、冲突的活动 capability owner 被拒绝。

归属声明不改变 write_paths 锁、不授予外部修改权限。GO 确定全局归属与依赖；父 MO 将共享实现交唯一子 MO 并收窄实际写集合；子 MO 冻结具体调用/适配 tasks。普通已批准边界内由 GO/MO 评审，跨模块或不确定业务边界沿用人工决定。运行期继续校验选中 provider、接入证据、归属证据及 fidelity，null 不免除 hash 漂移检查。

### 稳定提供方与修改目标分别建模

`adapt` 表示围绕真实能力实现必要差异，不表示可修改被冻结为稳定 provider 的文件。消费者/DI/适配层/待清理冗余文件放入 tasks 与 task_trace；只有实际复用且本轮保持稳定的 API/实现才列入该计划的 provider_refs。不能指向历史副本或任意无关接口规避漂移。知识快照可解释旧实现，但不替代 live provider 验证。

### 确需修改 provider 本体

沿用现有 CR、invalidate、冻结、代码验收和依赖恢复，按以下顺序执行，不增加隐藏写通道：

1. 父 MO/GO 提供变更与影响报告，确认唯一 owner、消费者闭包、写集合及公共契约；跨模块/语义变化交人工。记录旧版本及不可变旧证据，历史中仍可追溯。
2. 在实际修改前停止相关活动 worker 并经 Host revoke；相关消费者执行 invalidate，保留旧测试/失败，重新规划。无关模块继续；不要仅解除依赖就把旧测试当 Green。
3. owner 对既有冻结计划提出 CR/影响分析或 invalidate 后重新规划、获必要批准。其被修改文件作为明确的实现目标，不再同时声明为该 owner 计划中的不变 provider；仍使用的稳定依赖继续保持真实映射与 hash 校验。
4. owner Coding → Build → Automation → MO 验收，保存新实现的 code baseline。缺自动化时沿用现有 Yellow/可用构建规则，不能称 fidelity 通过。
5. 使用 owner 已接受的真实文件/hash/version 生成新 v2 catalog，消费者重新形成映射/六件套并冻结，再正式构建与业务回归；不得在旧冻结 plan 中静默替换 ref。已有 waiting-dependency 按 dependency-ready/resume 恢复，需要重规划时明确进入 specifying。
6. 非 Green 的正式复测必须保留 retest_of；父 MO 重汇总，Auditor 全量收尾后复核遗留/受影响问题。任何失败仍遵守现有预算、Fixer 与人工升级规则。

本轮尚未交付、文件不存在的 provider 不能伪造 ref 供消费者冻结；先完成 owner 或选取真实稳定接口及有依据的方案。若 registry 尚无必要 owner/依赖，先解决分配，不能以 null 隐藏本轮写入责任。同 run 来源追加只处理只读来源，不负责修改既有分工。

## 11. Auditor 全局复用治理

全部 MO 收尾后，Auditor 整体查看所有迁移改动（包括 Green），重新对照存量源码行为、目标已有实现及二方库。发现重复业务逻辑、未实际接入的复用或多个真实消费者的公共能力提取需求，记录代码治理 finding，经 GO/父子 MO 委派，受影响消费者完整复测。提供方 owner/接口/版本与消费者映射沉淀到受控目录/SPEC，保留 fidelity 及生产接线证据。按 [整体代码治理](audit-code-review.md) 优先治理后再处理剩余 Red/Yellow；不由 Auditor 直接改代码，不以公共化为由制造无实际用途的抽象。

## 12. 埋点 SDK / 二方库

有埋点职责时将目标 SDK/封装作为 capability，逐事件对齐名称、参数、时机、实际已有缓存/重试/生命周期语义及真实接线；不因 API 同名认定保真。共享提供方唯一 owner，业务触发各归消费模块；不适用则记录 N/A，不添加 SDK 或依赖。验收层级与异常分流见 [埋点协议](telemetry.md)。
