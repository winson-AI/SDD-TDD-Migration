# Auditor 整体代码治理

## 顺序与职责

全部叶子 MO 本轮实现、Build、Automation/缺测记录和修复收尾，父 MO 汇总有效后：

```mermaid
flowchart TD
  A[全部 MO 收尾及父汇总] --> B[Auditor 整体代码审查]
  B --> C{有代码治理发现?}
  C -- 有 --> D[GO 审核 owner/影响范围 · MO 接受]
  D --> E{冻结任务及权限内可完成?}
  E -- 是 --> F[独立 Fixer TASK 重构/依赖接入/公共能力提取]
  E -- 否 --> H[CR/人工决策 · 受控恢复后重新规划冻结]
  F --> G[Build → 装机 → Testing → 受影响下游完整回归]
  G --> I[Auditor 裁决 · 父 MO 刷新汇总]
  I -- 成功且基线改变 --> B
  I -- 预算内明确技术失败 --> F
  I -- 未决或越界 --> H
  C -- 无 --> J[收集剩余 Red/Yellow · 读取 SPEC/CASE/PATH]
  J --> K[根因路由 → 预算内 Fixer/Testing → 下游复核]
  K --> L[刷新变更代码审查 · 独立收尾 · GO 报告]
```

Auditor **负责发现、委派、复核和唯一审计验收**。它不写源码、不兼 Fixer/Implementer/脚本作者。GO 管全局 owner 和依赖；父 MO 管认领范围与子模块；子 MO 守冻结任务、权限及执行预算。所有工件、路由、结论仅经 Ledger。

## 审查内容

审阅本轮所有模块（包括 Green），结合全局 legacy/target、架构/知识、四维分析、冻结 SPEC/tasks、复用目录/映射、provider owner/版本和真实生产绑定，逐模块提交：

| 检查 | 必须回答 |
| --- | --- |
| changes | 从本轮起点到当前候选的完整改动是什么？包含已提交、未提交、新增、删除、重命名及构建/依赖/资源文件；不得仅查看最后一次 commit。 |
| refactoring | 改动是否仍符合 scope、架构、调用链和 UI/Logic/Adhesive/Resource 完整性？ |
| redundancy | 目标已有实现、新迁移代码与兄弟模块有无重复业务逻辑、失效分支或重复资源？ |
| library-reuse | 对照源码行为，能否正确复用/适配 TARGET 或二方库？是否已真正切换依赖/DI/调用链并清理重复生产实现？ |
| shared-capabilities | 多个真实消费者需要的通用能力是否应提取？唯一提供方 owner、接口、写范围、消费者及回归路径是否明确？ |
| fidelity | 重构/复用后能否复现存量功能、异常、状态/副作用及资源行为？原有验收不能被削弱。 |

每项填 `satisfied/finding/not-applicable`、原因和证据。N/A 也要依据。不能因命名相似而认定复用，不能为假想消费者创建公共框架。二方库不适用时保留有证据的 adapt/reference/new 方案；外部库只读。

审查证据引用固化工件；会被修复的源码使用快照摘要绑定，避免历史报告反向引用 mutable 源码导致修改后无法保留证据。宿主提供版本化 diff/清单（含起止版本、工作区改动）作为 `diff_refs`；Auditor 审查语义并记录证据。Ledger 验证覆盖、身份、基线及工件 hash，**不会自动证明 diff 完整或代码不存在冗余**。输入无法确认时输出有根因的治理 finding，走 human/补充输入，不填虚假 satisfied。

## Ledger 接口

1. `status.global_next_step.operation=audit-code-review` 出现在全部 MO 收尾后；`snapshot` 是报告必须原样绑定的快照。先提交本实例 `stage=audit-code-review` 的 context receipt，`draft_ref` 指向待审报告。
2. Auditor 先按 [代码修改清单模板](../../../template/audit-change-inventory.md) 生成本版清单，再由 [audit-code-review.json](../../../template/audit-code-review.json) 的必填 `change_inventory_ref={path,sha256}` 引用；最后提交 `audit-code-review`，payload 为 `{report_ref, context_ref}`。报告覆盖全部执行叶子，六项检查、diff、SPEC/code/context 及实际审计者身份；无需自动化环境。
3. `CR-*` findings 是**代码治理发现**，不修改测试三态，不伪造失败断言。记录 source_module_id、category、analysis_ref、root_cause、affected_module_ids；影响集合必须有接口/调用/依赖证据，含公共提供方的实际消费者。
4. 有治理发现时，`audit-collect` **优先仅收集治理批次**；无治理发现才收集剩余 Red/Yellow。复用 `audit-plan → audit-route-batch → audit-work → Fixer → Testing/audit-retest → audit-verdict`。治理路线只能 fix 或 human，不能以旧 Green 或纯 verify 关闭冗余。
5. 路由明确唯一公共能力 owner、改动与回归。Fixer 按冻结 TASK/写权限做行为等价修正；新增任务、provider 接口/职责或授权变化走 CR/上游审核，真实未决交 Human，release 后重规划/重冻。活动批次不偷改 SPEC、写集合或 provider hash，见[复用协议](reuse-dependencies.md#10-显式-provider-归属与合法版本变更)。
6. work_modules 含来源、合法 owners、显式受影响消费者/下游。Build → 装机 → Automation，完整验证这些模块并留 retest_of，逐依赖推进。v2 已审技术失败按累计预算重试，保留各轮根因/补丁/日志；CR-ID 跨版本稳定，重复 finding 按停滞/预算裁决。v1 保留一轮失败/再现后人工恢复；无关有效 Green 不重跑。
7. 修改代码/SPEC/context 使代码审查失效；本批裁决且父汇总刷新后，必须对新版本重新提交审查。旧报告归档，不得删除未解决 finding。人工释放后已通过 CR/重新冻结和实现解决的问题，可在新基线审查中填 recovery_resolutions（finding_id、decision_id、reason、evidence_refs）；决策必须绑定该 finding 所属批次的人工作业报告且已 audit-release，不能仅删除 findings 冒充解决。复核已整改处并保留不受影响模块的有效审查证据；不能凭测试 Green 自动断言冗余已消除。然后收集仍遗留的 Red/Yellow，完成缺陷闭环和最终独立审计。
8. `audit-assign` 与 `audit-unavailable` 都要求当前代码审查和无待处理治理发现。自动化不可用不阻止代码审查；unverified_findings 与 verification_deferral_history 保留未复核事实，不再次派发 Fixer，刷新代码审查后仍可按 Yellow/未测试收尾。受影响消费者缺测也不能把 finding 标 resolved。

## 复测与报告

### 必交输出：本次代码修改清单

Auditor 在自己的 staging 中生成版本化的 `audit-change-inventory-<revision>.md`，包含本轮起点至当前候选的全量修改，而非最后一次 commit 或只有 Red/Yellow 的模块。它与 JSON 报告绑定相同 run、Ledger sequence 和候选快照；后续治理/修复后更新清单版本，保留旧版。

- **模块与功能**：根模块/父 MO、子模块/owner、功能 ID/名称、scope、REQ/TASK、四维及业务行为变化；直接复用而无修改的功能、未实现功能也列明。
- **逐文件修改**：稳定 CHG-ID、add/modify/delete/rename、前后绝对路径、符号/行段、原因、前后摘要、固化 diff/源码快照。覆盖源文件、测试、依赖/构建、配置和资源；起点已有工作区修改单列归属，不能当成本轮成果。
- **影响范围**：直接入口/接口/状态/平台、provider owner/版本、真实消费者/下游及影响依据，说明复用/适配、冗余清理和公共能力沉淀的实际接线。
- **测试对应**：功能/CHG → 所属模块+CASE-ID/Name → PATH-ID/Name/query → ASSERT，另列测试脚本/配置/数据的文件路径及证据；区分测试场景标识与文件系统路径。状态、executed/stale、基线、test_run/retest_of、根因来自 Ledger。
- **核对与缺口**：全量 diff 的文件、功能、任务、用例双向映射，去重统计和待决 CR/owner/下一步。没有 CASE/PATH、脚本或执行结果时如实列缺口，不为表格完整编造记录。

清单引用归档证据，删除/重命名保留前后快照链接；目标 live 路径仅作定位，不能当永久证据。清单不反向引用尚未生成的本版 JSON，避免循环 hash 依赖。内容/链接发生变化须新版本及新 `change_inventory_ref`，JSON 与清单一起重新提交。

Ledger 校验清单必填、工件存在及 hash，并将引用投影到 GO 的 migration-report JSON/Markdown；语义完整性仍由 Auditor 审查。旧审查未含该字段时，status 提示补交新版 audit-code-review；不会自动生成清单或改变测试结果。

“完整复测”明确为 **Red/Yellow + 本次重构/复用/公共能力变化影响到的全部用例**；采用受影响模块完整回归，必要下游包含原 Green。无关有效 Green 保留，不做全项目无差别重跑。纯缺测不能伪装成代码错误。

报告保留：审查起止基线/工件、冗余定位、复用/不复用依据、实际依赖接线与删除冗余证据、公共能力 owner/消费者、CR 和修复记录、影响范围/复测依据、Build/Automation 状态、失败根因及人工下一步。公共能力目录/映射、设计/tasks、fix memory 和测试证据按既有冻结/版本协议更新，供后续模块复用；不直接改全局 mutable 配置或旧工件。

### 埋点的条件审查

审查 changes/fidelity/library-reuse 时显式核对 [埋点协议](telemetry.md#总则)：无埋点的模块/任务只核查 N/A 依据，不增加治理 finding 或环境门禁；存在埋点则追踪事件→功能/TASK→修改路径→CASE/PATH/ASSERT/观测层级，检查遗漏、重复、参数及生产接线。真实问题和未知范围才记录 finding/根因，独立任务继续。

## 宿主目标审计

v2 审计范围从原始 global_spec 开始，goal_review 完整列出宿主 requirement、feature 与实际模块 TASK/PATH 证据，逐项给出 satisfied/finding/blocked 和原因。遗漏即使没有 Red PATH 也需登记 host-goal finding，由既有统一修复/上游调整闭环处理；受阻目标不能得到最终 Green。snapshot 同时绑定原始业务契约，防止只核对后来收窄的计划。

局部问题由 MO/Diagnostician/Fixer/Test-Runner 在配置预算内收敛；v2 禁止新增 problem-assign，明确挂起与残留统一进入完整 registry 收尾。Auditor 全量审阅宿主目标与代码，复测只覆盖有必要的残留/过期/集成 PATH，保留有效 Green。

整体审计需执行 PATH 时，GO `audit-test-assign` 为独立 Test-Runner 指派全部所选 PATH；其自身 audit-execution 预检先经 Ledger 提交，`audit-test-submit {result_ref}` 校验宿主执行回执。Auditor 最终 report 引用 test_result_ref、review_ref，原样消费测试观察并给出裁决，不直接执行测试或修改观察。测试实例独立于 Auditor、代码及测试脚本作者。撤销活动审计时，尚在运行的测试 worker 必须另附 test_worker_stopped_ref。
