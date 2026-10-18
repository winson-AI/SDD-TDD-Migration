# 二方库与已有能力：语义抽取、需求映射和依赖验证

## 总则

复用评估贯穿 GO 切片、父 MO 分工、子 MO tasks 和 Coding/Testing：先读 TARGET 及用户指定 reuse_sources 的功能语义目录，再结合需求决定直接使用、适配、仅参考或新实现；不按同名 API 认定等价、不重复实现已有能力、不为迁就库削弱需求。目录/映射经 Ledger 传递、版本冻结、实际接线与完整测试验证；外部来源只读，跨模块/不确定边界交人工。

**全局 fidelity 规范**：每次选择目标已有能力或外部二方库，都与存量源码对应功能逐行为对齐，写明复用/适配如何复现原功能，记录源码基线、差异、PATH/ASSERT 与正式复现证据；语义参考同样适用。接口可用、库测试通过或对齐报告完成都不代表迁移功能通过：规划记录随 SPEC 冻结，编码后 Main 验证，MO/Auditor 按阶段唯一验收；行为不一致为 Red，依据或执行条件不足为 Yellow。需求与存量行为冲突须人工决定并留痕。

二方库不能直接复用时，按功能目标、上下文、存量源码与目标现状选 adapt/reference/new，冻结任务后继续 Coding；只有替代实现也经核验不可行，MO 才以 suspend(reason_code=not-implemented) 留证并向用户展示"未实现"，独立模块继续（第 8 节）。目标已有实现时同样读复用/依赖二方库并查业务冗余：确认重复且复用/适配可行，就在分配范围内重构目标实现、切换真实依赖并清理冗余，不重复造轮子、不只加依赖而保留旧逻辑（第 9 节）。

能力目录写明 provider owner：null 为经评审的既有稳定能力，非空为本轮唯一叶子 owner；write_paths 只控制权限/互斥，不推断业务归属。GO 规划归属，父 MO 分配共享改动并收窄写集合，子 MO 冻结复用与适配任务；改提供方本体走旧基线→授权 owner 变更→新版本→消费者重新冻结/复测，不以 adapt 绕过 hash。

## 1. 作用与边界

复用分析是规划的必经输入；Coding 同时依据**冻结的模块需求/tasks、目标架构、经审核的能力映射**，库的行为不能反过来削减需求或替换验收。两类来源保留区别：**目标项目已有能力**（业务模块、公共服务、已接入二方库及封装）自动纳入 `TARGET` 检索，优先检查已存在的生产实现；**用户指定的其他项目模块/二方库**作为显式外部来源，读取其指定模块提取同样语义——有源码只说明可分析，能否依赖、适配或仅参考须独立核实。二方库指组织内部维护的可复用组件，任意外部源码不自动成为可接入的库；`reuse`/`adapt` 实际使用能力，`reference` 仅借鉴语义，`new` 评估后自行实现；禁止按类名、接口名或目录名相似宣称等价。

读取来源不授予修改权限：外部来源只读，编码仍限 target 中分配的 scope/write_paths；改提供方、改公共契约或新增跨模块边界走 Ledger 的 CR/依赖/人工决策，不把外部仓库静默纳入本次迁移。

## 2. 用户输入、持久化与运行版本

项目配置 `reuse_sources` 可选，留空也必须评估目标项目；用户可只描述其他项目的模块位置与用途，宿主整理成 [reuse-source.json](../../../template/reuse-source.json)：

```json
{"reuse_sources": [{"source_id": "LIB-SEARCH", "root": "/work/SharedCommerce", "module_paths": ["/work/SharedCommerce/search"], "description": "可复用的商品检索、分页和筛选能力"}]}
```

`source_id` 唯一且不为保留 ID `TARGET`；路径绝对，module_paths 包含于 root，省略时取整个 root；外部选择范围与 target 分离，可共用 monorepo 根只要显式选择的模块不与 target 相交。沿用项目上下文 init/update/prepare 的更新语义；已登记 source_id/root/module_paths 固定，同 run 只能经[来源追加事务](source-changes.md)追加新 ID。源代码不全文复制；语义报告、目录、映射经 Ledger 版本引用留档，选中的 provider/API/版本解析证据以绝对 path/sha256 固定并在运行时复核，commit 只辅助定位。`planning_context.reuse_sources` 含隐式 TARGET 与声明来源，父/子 MO 均可见；不能访问用户指定来源时明确阻塞请求补全，不写成"已扫描无匹配"；远程坐标/仓库由宿主先取得可读材料，控制器不下载依赖。

## 3. 按三层编排提取与细化

| 阶段 | 责任 | 必需输出与门禁 |
| --- | --- | --- |
| GO 全局准备与切片 | 一起分析 legacy 需求、目标架构与 TARGET/外部来源，识别公共能力、稳定提供方与消费关系，再划模块 scope | 全局 `reuse-catalog.json` 与抽取报告经 context_refs 分发；每个来源有评审结论，无候选也有搜索依据 |
| 父 MO 认领与子模块划分 | 按认领模块的需求筛选/补充语义，复用公共能力，统一适配 owner，划分消费者与缺口任务 | 子 scope/context_refs 带适用能力与初步需求映射，不让每个孩子各写一套封装；GO 接受 DAG/写集合 |
| 子 MO + Spec Designer | 在子功能范围内核验候选，逐条需求形成 `reuse-plan.json`，可有依据地拒绝候选；形成设计与 tasks | requirement → capability/decision → task → PATH，连同接入路线与验证要求进入冻结 plan |
| Implementer / Fixer | 读冻结映射与语义差异，完成依赖声明、版本解析、DI/入口绑定、适配层或新实现 | Task Trace + reuse_trace + 实际版本/绑定证据；不临时改提供方、行为契约或以 mock 替代生产实现 |
| Test Runner / 子 MO | 按需求设计断言，验证复用接线与完整业务路径 | 真实提供方集成测试、适配差异回归、完整 DoD；编译/导入成功不等于 Green |
| Auditor | 全部 MO 收尾后聚合依赖与能力映射，检查共享提供方影响，委派 Fixer、Testing 并独立裁决 | 提供方版本/接线变化使消费者旧结果失效，按依赖图复测 owner/source/中间与下游；失败留根因待人工 |

GO 可先做粗粒度目录，父/子 MO 补充本模块相关语义证据并更新目录引用，旧内容留 history；目录不等于冻结批准。不为无关候选全文扫描所有项目，扫描范围、搜索词/调用链与不适用理由写入报告；交接只经 Ledger 引用。provider 归属见第 10 节。

## 4. 语义抽取必须回答什么

[reuse-catalog.json](../../../template/reuse-catalog.json) 每个 capability 有稳定 ID、来源、实际版本/API 证据及：**业务意图**（用户行为与可观察结果，沿真实入口→状态/数据→输出定位，不只 API 摘要）；**输入/输出**（模型、单位、空值、默认值、分页/排序、同步/异步）；**前置条件与状态**（认证、权限、初始化、缓存/持久化、状态所有权、线程与生命周期）；**副作用与失败**（网络/存储副作用、异常、超时、取消、重试、幂等，无副作用也写明）；**接入约束**（公开入口、版本、平台/框架/API 或 ABI、传递依赖、DI、生产绑定及与目标架构的兼容性）。报告引用真实源码、API 文档、manifest/锁文件与调用链；抽取是 Agent 的语义分析，控制器只检验结构、范围与引用。

## 5. 需求映射与 OpenSpec

使用 [reuse-plan.json](../../../template/reuse-plan.json)，覆盖该子模块每条全局需求 ID：

| decision | 含义 | Coding 指导 |
| --- | --- | --- |
| reuse | 语义与目标架构兼容，可直接使用 | 指明实际入口、版本、初始化/DI、消费者；保留完整业务验证 |
| adapt | 可复用核心能力，但有明确模型/协议/生命周期差异 | 匹配点、缺口、转换与额外行为写进 behavior_delta，拆独立适配 tasks 与回归路径 |
| reference | 不能直接接入，但业务语义有价值 | integration.mode=reference-only；提炼规则在目标架构内实现，不宣称运行时库依赖 |
| new | 无合适能力，或采用候选会违背需求/架构 | capability_id=null；解释搜索/拒绝理由与剩余实现范围 |

每条映射含 rationale、behavior_delta、binding_plan、verification、task_ids、path_ids，后三种不能通过弱化验收消除差异；实际使用时记 integration.mode（existing-target/package/source-module/reference-only）、locator、版本、配置、传递依赖与兼容证据。源码引用不等于复制授权，新增依赖仍守项目规则与边界决策。OpenSpec 分工：proposal 写复用策略与缺口，spec 保持用户可观察行为，design 写提供方与适配边界，tasks 落接线/适配/剩余实现，checklist 核映射覆盖、版本、生产绑定与测试，status 引用当前冻结 plan；`stage-plan.reuse_plan_ref` 把目录与映射纳入 plan 摘要与后续 CR，change/reuse.md 只供规划阅读。prepare 要求复用规划（reuse_required=true），显式外部来源与子 MO 计划同样要求；无可复用能力时提交空 capabilities、有证据的来源评审与 new 映射，不编造库。

## 6. Coding、测试与失败处理

Implementer/Fixer 对每个 reuse/adapt/reference 映射提交 `reuse_trace`（mapping_id、resolved_version、属于相应 task_trace 的 files、binding_evidence_ref）；reference 记借鉴语义落在哪些目标代码，不伪造运行依赖；new 由既有 Task Trace 覆盖。Testing 至少验证正常、边界、异常/取消，以及真实提供方接线、版本/配置与适配差异；预期来自业务需求，不照抄库行为；mock 只辅助诊断，缺真实绑定测试仍 Yellow；整体用例与跨模块回归不因用库而缩小。

- 本模块接线/适配错误且可修复：保持 Red/Yellow 证据，优先一轮 Fixer，再正式 Main 复测。
- 已确认提供方缺陷、依赖不可用或外围问题：记 source/capability/mapping/version、受影响消费者与根因，留待统一 Auditor；无关模块继续。
- 提供方、锁文件或接入证据变化：相关冻结依据失效并留历史，提交当前目录/映射与历史引用，按 invalidate/CR/重新冻结恢复；不原地改旧目录或只换版本字符串复用旧 Green。
- Auditor 不改二方库或业务源码，修复委派合法 owner，外部源码未授权则人工处理或经批准选新方案；复核失败输出根因待人工，不无限重试。

脚本在 plan 验证语义结构/映射与来源范围，在 freeze/dispatch/结果接受/DoD/审计复核已选 provider 与接入证据 hash，未选候选变化不使消费者失效；包解析、依赖隔离、外部写保护、语义判断与运行测试由宿主/Agent/项目执行器完成，结构检查不等于功能迁移完成。

## 7. 全局保真规范：复用必须复现存量功能

总则的保真规范对 TARGET 与外部来源统一执行，`reuse`、`adapt`、`reference` 均不得跳过；源码中的偶然行为/缺陷与需求冲突时，Spec Designer 把差异交人工决定并经 Ledger/CR 冻结，不自行照搬缺陷或接受库默认行为。

### 7.1 落到控制节点

| 节点 | 必须完成与保留的记录 |
| --- | --- |
| GO 发现/规划 | 按功能清单定位存量入口、调用链、可观察结果与必要状态，把候选库与该功能对齐；不要求用户另填保真材料 |
| 父 MO 拆分 | 子 scope/context_refs 带存量基线与候选差异，明确共享适配 owner、消费者与跨模块复现路径，不因复用删功能 |
| 子 MO / Spec Designer planning → freeze | 每个选中映射填 fidelity，逐场景写原行为、库行为与复现方案；差异落 tasks，预期落 SPEC，Test Runner 把基线与验收转成 PATH/ASSERT；未决行为交人工，有差异但方案明确即可冻结，不要求规划期已通过运行测试 |
| Coding / Fixer | 按冻结方案接线/适配，reuse_trace 留实际版本与绑定证据，不用库行为替换冻结预期；修复记忆引用 mapping/scenario、源行为、偏差、策略与复测 |
| Testing → MO 验收 | code accepted 后用对应前置、输入/状态与真实提供方运行 Main，保存 expected/actual、断言与回执，验证结果、状态与副作用；全部必需路径与保真断言 Green 才验收 |
| 全量收尾 → Auditor | 读相关 SPEC、冻结对齐记录、PATH 与失败证据，沿共享库/适配器影响范围委派 Fixer 与 Testing，独立复核；失败输出根因待人工，不以历史对齐结论代替复测 |

### 7.2 对齐记录与证据链

`reuse-plan.mappings[].fidelity` 含：`legacy_root`（等于本轮 Ledger 的存量根）；`legacy_source_refs`（该目录内真实入口/调用链的 path/sha256，不以提供方源码冒充基线）；`alignment_ref`（按 [reuse-fidelity.md](../../../template/reuse-fidelity.md) 的逐行为对齐报告：正常/边界/失败、默认值、输入输出、状态/生命周期、副作用逐项核对，不适用有理由）；`scenarios`（稳定 scenario_id、legacy_behavior、reuse_behavior、reproduction_strategy 及已冻结的 path_id/assertion_ids，覆盖该映射全部 path_ids；经 mapping 的 requirement_ids/task_ids 与 PATH 的 case_id 关联需求和用例，不另建验收状态机）。

报告区分**源码分析得出的基线**与**已有真实运行证据**：规划只读分析，代码生成前不运行目标测试；存量运行轨迹可辅助固化场景，没有就记未执行，不伪造。源码与需求足以确定行为即可冻结，预期不定或基线缺失先补材料/人工澄清；正式复现仍须执行 Main。复现是满足冻结的业务可观察契约，不是内部实现相同；数据/平台差异的转换与允许偏差须有依据，不用"相似"代替断言；Test Runner 从已审核的存量契约与需求设计预期，不从目标实现或提供方返回值倒推。记录链固定为：**存量源码引用 → alignment_ref → mapping/scenario → REQ/CASE/TASK/PATH/ASSERT → 冻结版本 → reuse_trace → Main 结果/回执 → MO 或 Auditor 裁决**；规划报告不可变，结果沿测试记录保留 test_run_id、freeze_id、code_baseline、环境、日志、expected/actual 与 execution_receipt，经 Ledger 共享，不建第二份可手改的通过状态。

### 7.3 失败、变化与实现边界

- 原基线、对齐报告、提供方/版本或接线依据改变，相关旧依据失效，按 invalidate/CR/重新冻结与复测更新，保留旧证据；旧计划缺 fidelity 须补录重冻结，历史 Green 不算满足新增规范。
- 控制器在 plan 检查存量根、源码范围、引用与 PATH/ASSERT 覆盖，在 verify_plan 检查基线与报告漂移，测试门禁验证每条冻结断言的真实回执与 expected/actual。**结构和 hash 检查不证明语义等价或对齐完备**，分析、场景质量与真实复现仍由角色/宿主负责并由阶段验收 owner 审核。

## 8. 复用不可行 → Coding；确实无法实现 → “未实现”提醒

### 8.1 默认继续实现

1. GO/父 MO/子 MO 先明确功能目标、scope、需求/CASE，读全局与本模块上下文、存量源码闭包、新架构、目标生产实现/资源/接线及分工。
2. 记录二方库不能直接复用的具体原因，评估适配、借鉴语义后实现、自主实现；至少一条路线可行时，Spec-Designer 把源码行为、目标差异、实现方案与完整测试映射到 tasks，在任务 scope 内做四维分析。`new` 不要求存在可复用 capability，不虚构库依赖或等待不存在的提供方 MO。
3. 冻结后 MO assign Implementer；改路线走 CR 与重新冻结，已批准范围内的普通实现选择不需新增人工会签，跨范围或业务预期不确定仍交人工。
4. Coding → build → automation → MO 验收完整；自主实现也保留源行为、真实生产接线与完整断言，不用 stub、mock、空返回、TODO 或删 CASE 代替交付。

### 8.2 核验后才能声明未实现

"库不能直接用"只说明候选路线不可用；适配/参考/自主实现均有已证实障碍时，记录**当前条件下具体未实现的功能**，不声称永久不可能，也不为已证实的硬约束做无意义编码尝试。使用 [implementation-gap.json](../../../template/implementation-gap.json)：功能目标、已分配 REQ/CASE/TASK、当前 module_revision、全局规范/架构与代码根、上下文审阅、复用失败原因、三种替代方案及证据、实际尝试或约束核验结果；context_review_ref 具体引用源入口/行为、新架构、知识、目标已有能力与缺口，不只写"已了解"；未进入任务规划时 task_ids 可为空，不编造。

发现者经本角色 `context-submit` 的 blocked 检查项 evidence_refs 引用核验材料，由 Ledger 交 MO，不私传、不直接写状态；MO 独立核验并按最新 module_revision 生成审阅后的报告，仍有可行路线则返回规划/Coding，确实不可行才接受专用标记：

```json
{
  "operation": "suspend",
  "module_id": "M001",
  "payload": {
    "kind": "human",
    "reason_code": "not-implemented",
    "reason": "具体功能在当前约束下未实现：<已证实原因>",
    "root_cause": {"category": "capability", "summary": "<核验结论>", "evidence_refs": [{"path": "<staging>/gap-review/verification.md", "sha256": "<actual>"}]},
    "owner": "module-orchestrator",
    "next_action": "<需要人工补充的能力、材料或架构/范围决策>",
    "implementation_gap_ref": {"path": "<staging>/gap-review/implementation-gap.json", "sha256": "<actual>"}
  }
}
```

这是现有 suspend 的专用入口，外层仍补 run_id/request_id/expected_revision 与宿主身份；只许 MO 接受，活动 worker 先真实停止并 revoke。控制器校验报告范围、revision、上下文、三种替代路线与证据，语义上是否不可行仍由 MO 审阅。

### 8.3 可见信号与恢复

- `status.workflow_progress.signals` 输出 `reason=not-implemented`、`label=未实现`、人工提醒、owner、next_action 与完整核验证据；宿主向用户展示具体功能及 REQ/CASE/TASK。
- GO 报告加 `unimplemented` 清单与"未实现：需要人工决策"入口，对应路径标 `implementation_status=not-implemented`；这是实现缺口标记，质量仍用原 Green/Red/Yellow，历史测试不改写。
- 模块进入 waiting-human，旧证据失效，未执行仍 Yellow，真实失败保留；独立模块继续，全量收尾后 Auditor 读该缺口与对应 SPEC/路径审查；不用 dependency/tooling 文本隐藏已核实的未实现。
- 人工补充条件后按 resume/invalidate/CR/重新冻结恢复再 Coding 与正式测试；提醒随阻塞解除撤下，旧报告与事件永久保留，解除阻塞不代表已实现或 Green。
- 仅 automation 环境缺失用 automation-unavailable，它表示缺测试证据，不适用"未实现"入口。

## 9. 目标已有实现与二方库冗余：直接重构复用

适用于目标已迁移、已有功能实现或已有测试的场景：GO/MO 实际读目标代码及二方库源码/API、版本与调用链，比较功能语义、状态/副作用、失败行为与架构约束；类名相同不足以判冗余，二方库有真实可用能力时也不因目标代码已存在而拒绝复用。同一数据在目标已有另一套取数或计算时按[数据契约](resource-transfer.md#数据契约)决定重构或适配，不并存。

控制节点：GO 评估/切片时把目标重复实现与二方库 capability 对齐，记冗余位置、真实消费者与复用/适配可行性，规划共享重构 owner 与受影响依赖；父 MO 在 scope 内安排唯一 owner 负责公共适配与去重，消费者共享同一提供方；子 MO / Spec Designer 选 reuse 或 adapt，把依赖接入、调用迁移、去重清理与回归覆盖拆进 tasks，四维分析覆盖受影响 UI/Logic/Adhesive/Resource；Implementer / Fixer 按冻结任务接入实际库版本、切换 DI/路由/消费者、保留必要差异适配、删除被替代且无消费者的冗余实现与配置/资源，提交 task_trace、reuse_trace 与生产绑定证据；Test-Runner / MO 先 build 再业务测试，验证真实提供方调用、存量行为保真与受影响消费者，核验重复实现已移除或剩余确为必要适配，原测试随新接线调整入口、保留业务断言；Auditor 按受影响范围检查重构与共享依赖影响，问题委派 Fixer、独立复核，不凭"换成二方库"判 Green。

### 记录与完成准则

对齐报告记"目标冗余文件/符号 → 库 source/capability/version → 消费者 → 保留差异/适配 → 清理范围 → TASK/PATH/ASSERT"，沿用 reuse-plan 的 rationale、behavior_delta、binding_plan、verification 与 fidelity.alignment_ref，不另设验收。可直接替代选 `reuse`，有真实行为/模型/生命周期差异选 `adapt`，适配层只实现必要差异；完成 = 受影响生产调用全部转到真实库/适配入口且重复实现已清理，必要兼容 façade 可保留并说明理由，不能只加依赖仍走旧实现或两套并行；清理前核对全局调用者与唯一 owner，持久化、数据格式与公共契约保持冻结语义；授权范围内直接执行，路线变化走 CR/重新冻结，未决或授权变化交人工；已有测试只补回归，不删失败断言、不以库自测代替目标验证；库不兼容时记证据按第 8 节继续，不为消除表面重复削弱需求，也不以未评估的"不适合"造轮子。冗余、适配必要性与调用链穷尽由 Agent 审查，脚本只校验版本、范围、映射与证据。

## 10. 显式 provider 归属与合法版本变更

reuse-catalog 用 schema_version=2，每个 capability 必填 provider_owner_module_id（null 或叶子 Mxxx）与 ownership_evidence_ref，缺失不等于 null：null 是经 GO/MO 评审的现有稳定基线，非空是本轮交付/变更的唯一叶子 owner；外部来源只能 null；指定 owner 须存在、不是父节点，provider_refs 位于其写权限内，消费者登记该 owner 依赖；依赖环、无效 owner、冲突的活动 owner 被拒。运行期继续校验选中 provider、接入证据、归属证据与 fidelity，null 不免除 hash 漂移检查。

### 稳定提供方与修改目标分别建模

`adapt` 是围绕真实能力实现必要差异，不是修改被冻结为稳定 provider 的文件：消费者/DI/适配层/待清理冗余放入 tasks 与 task_trace，只有实际复用且本轮稳定的 API/实现列入 provider_refs，不指向历史副本或无关接口规避漂移；知识快照可解释旧实现，不替代 live provider 验证。

### 确需修改 provider 本体

沿用 CR、invalidate、冻结、代码验收与依赖恢复，按序执行，不加隐藏写通道：

1. 父 MO/GO 给变更与影响报告，确认唯一 owner、消费者闭包、写集合与公共契约；需求/验收/授权变化交人工；记旧版本与不可变旧证据。
2. 修改前停止相关活动 worker 并经 Host revoke；相关消费者 invalidate，保留旧测试/失败并重新规划；无关模块继续，不把解除依赖当 Green。
3. owner 对既有冻结计划提 CR/影响分析或 invalidate 后重规划并获批准；被修改文件是明确实现目标，不再同时声明为不变 provider，仍用的稳定依赖保持真实映射与 hash 校验。
4. owner Coding → Build → Automation → MO 验收，保存新 code baseline；缺自动化沿用 Yellow/可用构建规则，不称 fidelity 通过。
5. 用 owner 已接受的真实文件/hash/version 生成新目录，消费者重新映射/六件套并冻结，再正式构建与回归；不在旧冻结 plan 静默换 ref；waiting-dependency 按 dependency-ready/resume 恢复，需重规划则进入 specifying。
6. 非 Green 复测保留 retest_of；父 MO 重汇总，Auditor 全量收尾后复核；失败仍守预算、Fixer 与人工升级规则。

未交付、文件不存在的 provider 不能伪造 ref 供消费者冻结，先完成 owner 或选真实稳定接口；registry 缺必要 owner/依赖先解决分配，不以 null 隐藏本轮写入责任；同 run 来源追加只处理只读来源。

## 11. Auditor 全局复用治理

全部 MO 收尾后，Auditor 整体查看所有迁移改动（含 Green），重新对照存量源码、目标已有实现与二方库；发现重复业务逻辑、未实际接入的复用或多个消费者的公共能力提取需求，记代码治理 finding，经 GO/父子 MO 委派，受影响消费者完整复测；owner/接口/版本与消费者映射沉淀到受控目录/SPEC，保留 fidelity 与生产接线证据。按[整体代码治理](audit-code-review.md)先治理再处理剩余 Red/Yellow；Auditor 不直接改代码，不为公共化造无用抽象。

## 12. 埋点 SDK / 二方库

有埋点职责时把目标 SDK/封装作为 capability，按[埋点协议](telemetry.md#3-事件对齐与二方库复用)逐事件对齐与接线；不适用记 N/A，不添加 SDK 或依赖。
