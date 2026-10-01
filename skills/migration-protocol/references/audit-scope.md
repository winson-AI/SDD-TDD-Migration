# Auditor：整体代码治理、遗留复核与一轮修复

## 总则

全量收尾指等待全部 MO 实现/测试本轮结束，不代表测试全量重跑。Auditor 先整体审查本轮代码修改、重构、冗余、二方库接入和公共能力提取；先委派治理及影响范围回归，再收集剩余问题。新入口与门禁遵守 [代码治理协议](audit-code-review.md)。Auditor 收集 Ledger 的 Red/Yellow，读取对应 SPEC/CASE/PATH，分析根因、委派必要的一轮 Fixer并正式复核；失败输出根因待人工。无关有效 Green 保留证据；无遗留只独立审阅。global_test_paths/global_paths 允许为空，不能作为启动前置。

## 入口与范围

Auditor 在所有父/子 MO 的本轮实现、编译构建、自动化测试及本地修复收尾后统一启动。完成 DoD 或有本模块证据的明确挂起/automation-deferred，父汇总有效、无活动 worker、无可推进动作，才满足门禁；不要求所有模块已经 Green。单模块失败不能提前启动 Auditor 或结束其他 MO。

**遍历全部模块，收集 Red/Yellow；绝不默认重跑全部测试用例。** `global_test_paths`（Ledger 中为 `global_paths`）是可选的额外运行级用例，不是启动开关，缺省或 `[]` 均合法。复核的主要依据来自模块自己的冻结 SPEC、Testing list、PATH/ASSERT 和 Ledger 结果。

## 代码治理前置

先执行 [audit-code-review](audit-code-review.md)：审查所有模块改动、重构、冗余、二方库复用与公共能力。即使测试全 Green，也不能跳过。治理批次先委派 Fixer（需新任务/边界则 CR/人工重规划）、完整回归实际影响范围；刷新当前基线审查后，再收集剩余 Red/Yellow。Auditor 自己不写代码。

## 问题处理

1. GO `audit-collect` 固定当前遗留 finding、来源模块、SPEC/测试路径及基线；纯自动化环境缺测汇入收尾待验证清单，不强制当成代码缺陷。
2. Auditor 逐 finding 读取 SPEC/tasks/CASE/PATH、断言和根因证据，提交 `audit-plan`。可直接复核的用 `verify`；已有根因需要补丁的用 `fix`；业务边界不明/不可修复的用 `human`。
3. GO 审核路由，负责模块 MO `audit-work`，委派**一轮 Fixer**。同 owner 的相关问题合并处理；Auditor 自己不修代码、不修改验收标准。
4. 修复后的正式 Testing 复核和必要的受影响回归必须留新执行回执、assert、基线与 `retest_of`。一轮仍 Red/Yellow，则记录根因及证据待人工，不自动重复修复。环境仍不可启动则明确 Yellow/未测试。
5. Auditor `audit-verdict` 验收，Ledger 记录结果与修复 memory；独立分支继续，失败只影响有依赖关系的分支。父 MO 刷新汇总后，独立审阅收尾。

当前 `audit_batch.work_modules` 包括发现模块、根因 owner 和依赖图中的受影响下游。由于代码基线按模块管理，这些模块采用保守的完整模块回归，代码改变后重新构建。范围扩展必须能追溯到 finding、owner 与依赖边；**不能把无关 Green 模块加入回归，也不能在问题闭环后再跑一遍全项目**。完整测试定义仍保留用于理解与覆盖核对，不等于全部加入最终执行清单。

## 收尾的实际执行契约

`audit-assign` 不检查 global_paths 非空。Ledger 的 `audit_scope(state)` 生成本轮执行集合，并固定到 assignment：

- `scope_policy: non-green-only`。
- `path_ids`：当前模块结果为 Red/Yellow 的 PATH；已由问题闭环复核通过的不再加入。
- 若用户另外声明了运行级 global_paths，仅加入其中非 Green、从未验证或代码基线已失效的路径。未验证不能隐式算 Green；已有效 Green 的额外路径同样不重复执行。没有额外运行级用例时无需补造它们。
- 有效构建 Green 不因自动化缺测被重跑或覆盖。对原 automation-deferred 模块补验时合并 PATH 结果，保留原构建证据。

| 清单 | 上下文门禁 | 动作与报告 |
| --- | --- | --- |
| 非空 | audit-testing | 独立执行 assignment.path_ids；`kind=tests`，完整提交本清单结果和 snapshot |
| 空 | audit-verdict | 核验已接受模块/问题闭环证据；`kind=audit-review`、`paths=[]`、`execution_status=no-retest-needed`、`review_ref` 和 snapshot；不启动测试、不要求自动化环境 |
| 非空、仅自动化环境不可用 | blocked audit-testing | `audit-unavailable` 记录选中路径 Yellow/未执行并收尾，保留已有 Green；不宣称功能通过 |

空清单仍需独立 Auditor 审阅，不能自动生成通过结论。`audit-review` 不能关闭尚有待复核路径的 assignment；正常 `tests` 报告不能用空 paths 冒充测试。模板见 [audit-review.json](../../../template/audit-review.json)。审计结果的 quality 表示证据裁决，execution_status 区分是否实际执行；不要把 no-retest-needed 写成“全部独立复测通过”。

## 活动审计的游标恢复

读取 `module_rounds`、`global_next_step`、`context_gate` 后按下一动作提交事件；活动 audit 快照过期时游标给出 audit-revoke，宿主确认旧 worker 已停止并留证后撤销再创建新 assignment，不得边运行旧审计边替换范围，撤销不返还既有预算。宿主仍负责启动 subagent、加载 skills、执行脚本及绑定真实身份；Ledger 只治理状态、范围、证据与门禁。

## 问题审计与最终审计

问题审计：problem-assign → Auditor 用 execute_test --module Mxxx --assignment <problem-id> 执行 → problem-audit → MO audit-resume。assignment 对应的 module_ids 全部必须在报告中出现。可执行模块 result 使用既有 tests 结构，actor_instance_id 为独立 Auditor；冻结、代码、所有 PATH/断言、历史非 Green retest_of 均校验。缺代码、定义失效或生产者未就绪的模块禁止执行，只报 quality=yellow-blocked、result=null 和结构化根因。

Auditor 裁决：

- retry：独立复测全部 Green；MO 恢复 testing 且 stale，仍需 Main 新复测与 DoD，不能直接 completed。
- fix：独立复测仍有问题；MO 接受后按现有契约授权一轮 Fixer，总预算不足仍须显式 recover 决策。该轮失败再交 Auditor。
- change：需调整契约；MO 回 specifying，新的人类批准后重新冻结，不授权 Auditor/Fixer 改验收。
- wait：依赖/外围问题未解除，保留队列；先解决前置，再按问题审计预算重新复测。
- human：人工裁决；批准 subject=digest(audit_resolution)，MO 接受后重新规划与冻结。

问题审计不发布全局 Green。收尾仍要求 audit_queue 清空、模块完成或合法 automation-deferred；只处理剩余待验证路径，空清单使用 audit-review。失败沿用 audit-route/repair-accept 闭环，保留独立性。问题审计与最终审计各自受 max_audit_rounds 限制，次数在撤销后不返还。

审计期间冻结业务操作和 worker 派发；旧进程必须真正停止。使用既有 audit-revoke 撤销问题/最终审计，附宿主停止证据。问题快照绑定模块 revision/phase/freeze/code/blocker/results；源码或定义变动会使执行不可用或结果拒收，不能混用新旧证据。

## 默认收尾：修复后验证，失败待人工

本节描述 finding 批次（audit-collect）；problem-assign/problem-audit 只用于闭包提前审计，最终全量审计仍待所有模块收尾。角色及 Used Skills 由宿主实际启动/恢复，本控制器提供状态与门禁，不自带 Agent 调度服务。

### 1. 所有模块执行阶段结束后统一启动

`audit-collect` 同时要求：

- 全部模块处于 completed、waiting-auditor、waiting-dependency 或 waiting-human。
- 没有活动 worker，也没有 ready 的下一动作；包括 dependency-ready、resume、已有人工批准后的恢复。
- 未完成的 context/specifying/clarifying/frozen/testing/dod 等阶段不能被当作遗留直接收走。正常模块继续推进；需人工澄清的模块由 MO 明确 suspend，不能仅因“当前没人运行”就启动审计。
- 尚不能运行的下游模块可记录依赖阻塞并挂起；这表示本轮明确受阻，不表示测试通过。已确认依赖/外围问题与本地一轮未修复问题执行 audit-defer 后退出。

模块失败只影响自身记录和有证据的依赖影响范围；全局 quality=Red 不得反向改写其他 MO，也不能触发取消其他并行 worker。宿主逐个收集 MO 结果、继续 ready 模块、等待运行中的 MO，不能使用首个失败即取消整组的策略。suspend(kind=dependency) 必须存在已登记且尚未满足的依赖，Ledger 保存 dependency_module_ids；无关同伴失败不能充当依赖。human/tooling 挂起须有本模块的真实阻塞原因，不能用它们规避全量等待。

status.module_rounds 返回 registered_modules、settled_modules、unfinished_modules、active_modules、ready_modules、blockers 和 all_settled；这些字段表示调度进度，与质量结论分离。存在遗留但其他模块尚未结束时，global_next_step.operation=null、ready=false、reason=await-all-module-rounds，并分别通过 continue_modules / wait_for_modules 指明继续与等待对象；next_steps 保留每个 MO 的下一动作。all_settled 不是审计授权，提交仍校验 global-plan、版本、预算和独立身份。

Global 等上述条件全部满足才统一启动 Auditor。`status.global_next_step.module_barrier` 列出未收尾原因；直接调用 audit-collect 也会重新验证，不能绕过状态建议。全部模块已 Green 时直接进入 audit-assign；若无额外待验证路径，则 audit-review 记录 no-retest-needed，无需空收尾批次和测试环境。

### 2. 收集、根因分析与 finding 路由

收集所有模块的 results、repair_findings、blocker、audit_queue，固定 sources、contexts（freeze_id/code_baseline/spec_ref/test_paths）和 round_snapshot。每个失败 PATH 得到稳定 finding_id；没有执行结果的模块生成 blocker finding。

Auditor 读取对应 SPEC/tasks/CASE/PATH、断言及日志，提交 [audit-closure-plan](../../../template/audit-closure-plan.json)：

- 每个 finding_id 恰好一条路由，source_module_id 必须对应收集记录。
- `fix`：owner_module_ids 非空，可有多个；owner_contexts 按模块 ID 精确绑定各自 SPEC 与完整测试路径。同一发现模块的不同问题可路由给不同 owner。
- `verify`：有证据说明依赖/环境已恢复、无需代码补丁，直接重新执行完整模块测试；不能伪造通过或绕过尚未解决的 human blocker。
- `human`：需澄清验收、无已冻结可修代码或不可控外围条件。该分支记录原因，其他独立分支继续。

旧单 owner 写法仅在该 source 恰好一个 finding 时转换；多个 finding 必须显式按 ID 路由，避免隐含遗漏。Global 审核路由；声明依赖加 source→owner 形成执行前置图，出现环拒绝该计划，修正后重新提交。

### 3. 按问题依赖交错修复和回归

仅 finding 来源、根因 owner 和依赖图上受影响模块进入 work_modules；无关有效 Green 不进入执行集合，禁止追加全项目回归。当前模块级基线模型对这些受影响模块保守执行完整模块回归（并按需重建），不是将全部 registry 的测试重新运行。负责模块 MO audit-work 接受该模块所有相关 finding，委派一轮 Fixer。Fixer 按自身冻结 tasks 与写范围修复，提交补丁、任务追溯和 fix_note。相同 owner 的多个问题合并为这一轮修复，不能越过累计预算。

调度不等待全批所有 owner。每个模块只等自身上游：

```text
A 修复 → A 全路径 Testing/DoD → B 全路径复测/DoD
                              → 依赖 B 的 C 修复 → C 全路径 Testing/DoD
```

即使 owner 原来 completed，也必须完成本批修复与验证，才能释放审计中的下游。受影响的原 Green 中间模块和下游同样进入 work_modules，依赖变更后需要新 Main 结果。发现模块就是 owner 时，同一轮完整 Main 结果同时作为两侧证据。无有效冻结 SPEC/代码的模块保持 Yellow，进入人工恢复/规划，不凭审计授权生成未冻结代码。

### 4. 失败隔离与审计报告

Red/Yellow 复核失败、worker 中断、预算不足、证据失效通过 test acceptance 或 `audit-block` 记录到 human_issues。只挂起该问题关联模块与依赖下游，不停止无冲突分支。已在途且受阻的 worker 由宿主实际停止并提交 revoke；写状态不等于进程已停止。

剩余可执行分支验证完毕后，Auditor audit-verdict 汇总 resolved_findings、human_issues、owner_tests/source_tests。全部成功则 verified；存在人工问题则 awaiting-human，并生成 `<run_root>/audit-reports/<batch-id>.json/.md`。若没有其他可推进分支，失败时即可进入 awaiting-human。报告保留 SPEC、路径、根因、各次结果和证据；后续信息更新报告时，也更新审批绑定的摘要。

### 5. 人工审核后恢复

1. Host 保存真实批准：decision.module_id=null，subject_sha256=digest(当前 human_report)。
2. Global `audit-release {decision_id}` 结束失败/部分完成批次；记录 audit_batch_history，清理批次授权，保留失败、memory、累计预算与原报告。
3. 回到正常带守卫的操作：预算不足用 recover（另有预算决定）；SPEC/代码上下文失效用 invalidate 后重新 plan/freeze；人工阻塞用 resume（绑定当前 blocker）；需求变化用正式 CR 与冻结。release 不自动批准新验收或追加预算，也不把测试改 Green。
4. release 会记录 recovery_contexts；未处理的人工作业保持相同上下文/blocker 时禁止直接重新收集，单纯改 session/revision 不算恢复。所有模块再次完成本轮或明确挂起后，才能建立新 batch_id 收集；不能在旧活动批次直接循环 audit-collect。

运行中会话恢复允许 session/checkpoint 记录，实际创建/恢复 subagent 和加载 Used Skills 均由宿主执行。协议不要求永久保留失效的 session。

| 新操作 | 角色/范围 | 输入与约束 |
| --- | --- | --- |
| audit-block | MO / 指定模块 | reason、evidence_ref；活动收尾中的证据/执行条件受阻，挂起关联分支 |
| audit-release | Global / module_id=null | decision_id；当前报告摘要批准、无在途 worker，结束失败批次以进入正常恢复 |

修复 memory 在 owner 测试后仍为 awaiting-cross-verification、reusable=false；关联失败记录 failed。只有完整批次 audit-verdict 通过才能变为 verified/reusable=true。部分成功的证据会保留，但不将未完成跨模块验证的 memory 提升为可复用。最后独立审阅收尾；问题已复核通过不再重复执行。
