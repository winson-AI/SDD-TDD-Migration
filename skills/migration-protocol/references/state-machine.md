# 状态机与双层三态

## 三种不同字段

- `phase` 是工作阶段，不是测试结论。
- `execution_status = pending | running | suspended | completed | failed（最终报告另可为 completed-with-unverified-tests）` 描述调度生命周期；failed 指基础设施或执行异常，不能直接等同产品缺陷。
- `quality = green-passed | red-bug | yellow-blocked` 用于测试路径和模块两层；全局继续聚合模块与全局用例。未运行、缺证据或过期统一 Yellow，并用 reason_code 区分 untested / stale / dependency / environment / human / tooling / flaky / incomplete。Green 不是空集合默认值。

路径 Red 表示实际断言/构建等质量门禁证明实现有错；Yellow 表示不能确定验收是否成立。Red/Yellow 均必填 root_cause，证据不足时明确 confidence=unknown、hypothesis 与 next_action，禁止编造已确认根因。

模块聚合：有效结果中任何 Red → Red；否则有 Yellow、漏测、未运行、stale、冻结/DoD未完成 → Yellow；仅全部必需路径有效 Green 且 DoD 满足 → Green。Red 与 Yellow 可以同时存在，aggregate 取 Red，但 unresolved 列表保留两类全部问题。全局还须覆盖本轮已声明用例、独立遗留审计和当前基线；没有模块或没有必需测试不能为 Green。

## 模块隔离与全量收尾

1. **独立执行与验收**：GO 切片后，以已接受 global-plan 对应的完整 registry 为本轮集合。每个 MO 独立拥有 phase、CASE/PATH 结果、修复预算、DoD 与恢复点。单模块 Red/Yellow、异常或超限不得取消无关 MO，不得修改无关模块的质量、结果、revision、assignment 或预算。全局 quality 只从模块结果聚合，不向模块反向传播。
2. **逐个等待**：宿主按 module_id 收集成功、失败和异常，采用 all-settled 语义；收到首个失败后继续其他 ready 模块并等待运行中的 MO。worker 退出/抛错只结束该 assignment；MO 仍需接受证据、执行修复/恢复或显式挂起。未派发、排队、锁等待、无活动 worker、全局 Red 均不等于模块本轮结束。
3. **真实依赖限定范围**：只有已登记依赖不可用或确认本模块受影响时，才能记录该模块阻塞；不得把独立同伴作为依赖原因。新增业务授权或未决边界须人工决策。受影响模块保留自己的历史断言，依赖缺证据记 Yellow，不复制生产者 Red；无关模块继续执行。已完成模块仅因真实基线/契约失效才重开。
4. **全量收尾门禁**：每个已登记模块必须有自身 DoD 完成记录，或基于自身证据的 waiting-auditor / waiting-dependency / waiting-human / automation-deferred 记录；所有 worker 结束且没有 ready 的推进/恢复动作。禁止为凑齐门禁给其他模块批量挂起。只有上述条件同时成立，GO 才拉起独立 audit-code-review，治理闭环后再提交 audit-collect 或符合收尾门禁的 audit-assign；不派发局部问题审计。
5. **阶段区分**：本轮结束不等于全部通过。Auditor 统一启动后先整体审查代码/委派治理，再收集各模块真实遗留；审计内部仍按已批准 finding 与依赖交错修复，失败只隔离相关分支。模块期末的全量等待不要求审计内每一修复步骤全批同步。

## Module-Orchestrator 唯一模块守卫

| 当前 phase | 下阶段 / 动作 | 必须证据与守卫 |
| --- | --- | --- |
| context | specifying | `_input`、全局规范/架构/用例、legacy/target baseline 可读 |
| specifying | clarifying | 六件套草稿、独立 test design、覆盖映射齐全 |
| clarifying | frozen | MO 技术审核绑定 plan 摘要；仅所需 Human 决定须精确绑定；freeze checklist 通过，无未决阻断；MO 接受 |
| frozen | implementing | 全局覆盖验收通过、冻结内容摘要匹配、依赖满足、目标写锁有效、tasks 非空 |
| implementing | testing | 实现结果 submit 后被 MO accept；测试路径与断言已在冻结前定义，现绑定实际代码、脚本和环境执行 |
| testing / build | testing / automation | 当前代码全部 build PATH Green；同一 Test-Runner 职责切换 |
| testing / automation | testing / visual | 功能用例层全 Green（`functional_ready`）；仅存在 visual PATH 时进入，逐基线节点对齐 |
| testing / automation | automation-deferred | 仅自动化环境缺失，automation-unavailable 留逐 PATH Yellow/未执行；构建保持 Green |
| automation-deferred | testing / automation | 新 testing ready 报告 + automation-resume；无需人工批准，仍须真实补测 |
| testing | dod | 冻结的全部必需路径 Green（build + automation 功能层 + visual 基线对齐层，`all_green`） |
| testing | diagnosing / change-review / waiting-upstream | 现有诊断经 MO 分流：实现错误接受后 Fixer；规划缺口 CR；超 scope 上溯，见 OpenSpec 变更控制 |
| diagnosing | fixing | 根因报告、当前版本本地预算或 Auditor 明确授权、合法写锁；不需改验收的补丁任务 |
| fixing | testing | 补丁与回归证据已接收、代码版本更新、受影响路径标 stale；正式 Test-Runner 复测 |
| diagnosing / fixing | change-review | 修改需求/验收/冻结任务或设计契约才可解决，提出 CR |
| change-review | specifying | Spec-Designer 影响分析、MO 审核；语义变化需人工；更新规划后重走冻结 |
| 未完成阶段 | waiting-auditor | 依赖/外围阻塞或适用预算耗尽；MO audit-defer，保存根因、结果与恢复点 |
| waiting-auditor | testing / diagnosing / specifying | 统一审计经 audit-work/retest/release 回到模块；依赖未解除留队，不能直接 completed |
| 规划/重建阶段 | waiting-dependency | 普通 DAG 前置等待；需全局裁决时 audit-defer |
| 任意未完成阶段 | waiting-human | 非依赖 Yellow 需人工或预算耗尽，Escalation 已登记 |
| waiting-dependency | 恢复点 | Global 的 dependency-ready + MO resume + baseline 复核；测试仍需复测 |
| waiting-human | 恢复点（原 dod 改为 testing） | decision 已接受且绑定当前问题/版本；若改契约则先 specifying |
| dod | completed | 所有 DoD 检查与证据齐全，MO 提 complete，Ledger 接受 |
| completed | testing / specifying | 审计问题经 MO repair-accept 进入 testing；代码/证据失效经 invalidate 进入 specifying；不能保留旧 Green |

模块执行为 Coding → 接受代码 → Test-Runner build/unit/static → automation/visual → DoD。按总预算局部收敛。Fixer 自测不替代正式复测；规划期不执行目标测试。

`resume_phase` 只能由原暂停点及新基线验证计算，不能接受外部随意指定。Ledger 只持久化合法且带 MO 批准的模块迁移；Global 的唤醒事件不等于模块迁移批准。

## Freeze / DoD 分开

上游接受当前分配，叶子规划完备才 freeze；独立叶子分别推进。修订按 [同 Run 回溯](progress-recovery.md#同-run-上游修订) 更新影响闭包。

freeze checklist 仅核准需求、设计、测试设计、任务、决策和范围。freeze 被接受是检查成功后的提交结果，不是检查本身的前置项；同理 complete 与全局上报可同一事务提交，不要求事先完成上报才可通过 DoD。不能要求此时测试 Green，否则形成先有代码才能冻结、先冻结才能编码的死锁。

DoD checklist 要求：当前冻结有效；所有任务有提交/文件/需求/用例追溯；正常、边界、异常及全局分配用例的必需路径覆盖齐全；Main 真实测试、静态检查、构建门禁全部 Green；有效断言；无遗留 Red/Yellow；依赖契约匹配；CR 已处理；所有历史非 Green 有同 ID 新版本复测链；无 orphan 证据；清理临时修改；全局上报。

覆盖率分母为冻结的全部必需路径与验收条目。不能通过删除测试、降低阈值、忽略失败用例过门。合法范围变更必须 CR + 人类决策，旧路径以 superseded 关联新路径保留历史，不能当作通过。

## 有限循环

默认预算 `max_fix_rounds=3`、`max_yellow_retries=2`、`max_audit_rounds=3`、`max_no_progress_rounds=2` 可由初始化调整。一次修复派发计一轮，中断也消耗轮次，恢复不清零。MO 在总预算内继续局部诊断、修复和正式复测；只有本模块有证据的依赖/外围阻塞或预算耗尽才留证进入统一收尾。停滞指纹只比较 PATH、三态、根因分类/代码及失败断言实际值，改写描述不算进展。失败后以 CR 返工仍消耗修复轮次；用尽须 recover 人工决定。

到上限：保留实际 Red/Yellow，execution_status=suspended，转 Escalation 并让其余就绪模块继续；超时不准通过。增加预算必须绑定 run/module 的显式决策事件。依赖唤醒不耗修复轮次，但不能因反复醒来规避停滞检测。

## Auditor 与全局完成

完整 registry 本轮收尾、全部 worker 结束且无可推进动作后，Auditor 先做宿主目标与整体代码审阅（含 Green），再经统一 finding 闭环委派修复和必要复测。全量审阅范围与复测 PATH 范围分别核对，空 global_paths 不阻止独立证据审阅。流程见[宿主目标审计](audit-code-review.md#宿主目标审计)与[审计范围](audit-scope.md#总则)。

snapshot 固定代码、SPEC、上下文与验证定义。必要复测由独立 Test-Runner 任务执行，Auditor 原样消费证据并裁决。补丁使快照失效后，受影响模块/消费者与必要集成 PATH 补回归，无关有效 Green 保留。Auditor 不编辑源码/脚本，不混用代码树结果。

最终 Green 要求全部模块 DoD、父汇总有效、队列清空、宿主目标满足及全部必需路径在当前基线通过；非 Green/未执行仍列明原因。仅自动化环境缺失可 completed-with-unverified-tests + Yellow 收尾，其他可执行工作继续。交付、核心架构和合并授权仍需真实 Human 决定后归档；模块 completed 不代表合并或交付。

## 冻结前证据与部分验证

`source_closure` 至少含真实入口、事件→状态/数据→结果执行链、生产绑定、证据引用与未决项；`target_feasibility` 包含已核实的目标接口/依赖/版本路线及证据。未知可行性先阻塞，不先写代码再隐瞒替代。

部分验证（如 source-only）保存 Yellow 和具体缺失证据；不能映射为 completed/Green。OpenSpec 六件套和修复 memory 由 Ledger 自动投影；当前冻结定义不被动态勾选修改。操作字段、游标与恢复规则见[操作矩阵](local-runtime.md#操作矩阵)，审计闭环见[默认收尾](audit-scope.md#默认收尾修复后验证失败待人工)。

## 父子 MO 的规划与汇总

根功能 context → MO decompose → GO decompose-accept → 父节点 coordinating + 独立子模块 context。GO 分配根模块 scope/context；父 MO 认领后只在其范围内拆子模块并分配 scope/context；子 MO 认领后拆 tasks，不再创建 MO，沿本页原状态机执行。父 MO 不编码、不重复验收子 CASE；所有子 MO 逐个结束后，父 MO 按当前子模块快照 module-summary。Auditor 门禁同时检查所有叶子和父汇总，见 [父子 MO 协议](module-decomposition.md)。

二方库复用评估在冻结前完成，实际提供方测试在 Coding 接受后执行。新的子 plan/prepare 运行要求 reuse_plan_ref，所选 provider/API 或接入证据变更被 current 校验识别为 stale；按 invalidate/CR 重新规划冻结，不直接恢复 Green。根因确认是提供方/外围问题则沿 audit-defer 进入统一收尾。详见 [二方库协议](reuse-dependencies.md)。

## 上下文门禁嵌入原状态机

各阶段的预检报告经 Ledger 留证（执行者自己的操作随操作登记；worker 在派发后 context-submit，ready 报告授权开工、blocked 报告退回派发；审计派发仍需 Auditor 事先的报告），原 plan/freeze/audit 操作或派发本身接受报告；该事件不改变业务 phase、不消费修复预算、不直接赋予 Green。缺失经既有 suspend/audit-defer/audit-block 记录后才可作为明确收尾；无关兄弟继续。详见 [上下文就绪协议](context-readiness.md)。

## 自动化缺测与代码依赖就绪

遵守 [双环节协议](build-automation.md)。dependencies_ready 允许 completed 或当前构建通过且未过期的 automation-deferred 上游；构建失败或实际不可用依赖仍阻塞实际消费者。仅自动化环境缺失不走普通 tooling→waiting-human 分支。build/automation 分开记录，父汇总接受缺测收尾，Auditor 最终保留完整缺测清单。

## 失效恢复与停滞感知

证据失效 → 实际停止/revoke 活动 worker → invalidate 归档旧 plan 并进入 specifying → 分配有效则 plan，分配无效则 GO allocation-review-required。旧计划不能反复挡住重新规划；新 SPEC 仍须冻结。status.workflow_progress 对无动作且无 worker、超时 worker、连续门禁拒绝和人工待决给出责任与证据；宿主继续独立动作并明确提醒用户。详见 [进度恢复协议](progress-recovery.md)。

## 埋点适用性不产生新状态

按 [埋点协议](telemetry.md)，无埋点模块/任务的 not-applicable 只记录范围判断，不转换为 waiting/Yellow/skip，不消耗修复预算，不增加全局等待条件。有埋点时沿已有 SPEC冻结→Coding→Build→业务Testing→三态/Fixer→Auditor；真实未知或失败仅影响本模块及实际依赖，其他 MO 继续。

## 控制流闭环细则

- `diagnose` 只提交诊断，调用方必须追加 MO 的 `diagnosis-accept`；不得在诊断 ACK 后直接 assign Fixer。复测后旧诊断作废，不能用旧问题的报告批准新修复。
- `next_steps` 按统一规则执行有限循环；未知根因不能伪报已确认，实际依赖/外围或适用预算耗尽才留证待审计。
- 人工恢复游标返回当前有效 `decision_id`；再冻结游标返回可提交的 `payload`，包括 within-envelope 的影响分析引用。候选 ready 仍需宿主补齐实际审查证据并经事务复核。
- DoD 挂起恢复进入 testing，旧结果 stale，正式新一轮复测后才能 complete；其余恢复点保持原阶段。`invalidate` 清除阻塞及解除许可、旧 freeze_id；历史 blocker 留在事件中。原来有 blocker 时同时撤销批准边界复用，重规划必须取得新人工冻结批准，不能靠 invalidate 绕过未决问题。存在 blocker 时禁止 CR 和 assign。
- 审计问题保存在 `audit_repairs`，`module_ids/accepted_by` 记录责任和 MO 接受情况。全局游标先提示 audit-route 或等待 MO 接受；未路由/未接受的问题禁止下一轮 audit-assign。有关联依赖的模块先完成原有恢复/重建，再接收其修复项。
- MO repair-accept 保留 `repair_findings` 供 diagnose/Yellow 路由，按原有 CR、修复预算和复测规则执行。模块正式测试接受后清除此轮 repair_findings；这只表示模块验证结束，审计问题仍须 Auditor 重跑裁决。
- `audit_results` 保留上一轮独立审计结果，不随代码失效清空。下一轮非 Green 同 PATH 必须提供新的 test_run_id 和 retest_of；模块重新 Green 不能解除这一要求。新审计覆盖完整集合后替换当前 repair 列表，旧报告保留于事件和工件。
- 全局问题无法归属现有模块时，GO 经 Escalation 取得范围/架构决策，禁止随意归属或跳过。审计预算耗尽凭具体决定 audit-recover，同 Run 续作。

## 控制主线

一个宿主 migration 任务对应一个 Run。主线是宿主目标/全量用例 → GO/父 MO 划分 scope 与 CASE → 子 MO 拆 TASK/四维 → 可执行六件套/SPEC/测试路径审核冻结 → Implementer → Test-Runner build/unit/static → 逐路径 automation → 按需诊断/Fixer/复测 → MO DoD/父节点汇总 → 统一宿主任务 Auditor。独立 test design 仅按需协助。先规划后执行，执行中调整：遗漏/fidelity 问题沿 CR 更新受影响 SPEC、再冻结并更新已编码模块；只越 scope 才上溯，不要求冻结前反复规划穷尽实现问题。

`global_spec` 是宿主目标/业务契约，GO 不生成下游实现 SPEC。分析和分配先从上到下接受当前规划；叶子 plan、四维和测试设计完整、问题已解，MO 以 `plan-review` 提交 [审核工件](../../../template/plan-review.json)，随后 `freeze {review_ref}`。未决问题绑定当前内容摘要、证据和可选方案交 Escalation；需求/验收/授权变化绑定真实 Human 决定。技术 hash 变化本身不触发人工批准。

编码前 MO 可 planning-reopen 保留历史并重做受影响规划/测试设计。已授权实现默认走 CR；宿主 revoke 停止 worker 且 allow_planning_reopen 核实派发前 Git HEAD/本任务写范围无差异、无代码提交后，才可回规划。reopen 再次重核快照，缺证据仍走 CR。编码后由 Spec-Designer 提修订、MO 审核重冻；Fixer 只修代码或提 CR。历史保留，跨 Run 只复用有适用条件及证据的抽象经验。

修正从当前层向子 MO、父 MO、GO 逐级追溯，最低有权层裁决后向下更新实际影响闭包。保留的子契约须仍满足父边界；父规划调整不等于全体孩子重做。新宿主任务才新 Run。


规划始终只有一份当前候选和一份当前有效执行基线。Implementer 执行前的草稿、分析、拆分和澄清调整存为 planning_history（history-only、不可执行），无计划版本编号或版本选择；重新规划须撤销当前冻结及旧设计授权，审核后重新冻结。plan_hash、freeze_id、事件 sequence/revision 和设计 generation 仅用于内容校验、并发及拒收过期交接；schema_version 等字段只校验工件格式，不选择执行流程。历史记录不能直接恢复冻结、派发实现或证明通过。
