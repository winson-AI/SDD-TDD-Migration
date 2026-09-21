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
3. **真实依赖限定范围**：只有已登记依赖不可用或确认本模块受影响时，才能记录该模块阻塞；不得把独立同伴作为依赖原因。跨模块新增业务边界须人工决策。受影响模块保留自己的历史断言，依赖缺证据记 Yellow，不复制生产者 Red；无关模块继续执行。已完成模块仅因真实基线/契约失效才重开。
4. **全量收尾门禁**：每个已登记模块必须有自身 DoD 完成记录，或基于自身证据的 waiting-auditor / waiting-dependency / waiting-human / automation-deferred 记录；所有 worker 结束且没有 ready 的推进/恢复动作。禁止为凑齐门禁给其他模块批量挂起。只有上述条件同时成立，GO 才拉起独立 audit-code-review，治理闭环后再提交 audit-collect 或符合收尾门禁的 audit-assign；兼容 problem-assign 同样受约束。
5. **阶段区分**：本轮结束不等于全部通过。Auditor 统一启动后先整体审查代码/委派治理，再收集各模块真实遗留；审计内部仍按已批准 finding 与依赖交错修复，失败只隔离相关分支。模块期末的全量等待不要求审计内每一修复步骤全批同步。

## Module-Orchestrator 唯一模块守卫

| 当前 phase | 下阶段 / 动作 | 必须证据与守卫 |
| --- | --- | --- |
| context | specifying | `_input`、全局规范/架构/用例、legacy/target baseline 可读 |
| specifying | clarifying | 六件套草稿、独立 test design、覆盖映射齐全 |
| clarifying | frozen | R1/R2 人工决定绑定冻结内容摘要；所有 freeze checklist 通过；无未决阻断问题；MO 接受 |
| frozen | implementing | 全局覆盖验收通过、冻结内容摘要匹配、依赖满足、目标写锁有效、tasks 非空 |
| implementing | testing | implementation_submitted 被 MO 接受；测试路径与断言已在冻结前定义，现绑定实际代码、脚本和环境执行 |
| testing / build | testing / automation | 当前代码全部 build PATH Green；同一 Test-Runner 职责切换 |
| testing / automation | automation-deferred | 仅自动化环境缺失，automation-unavailable 留逐 PATH Yellow/未执行；构建保持 Green |
| automation-deferred | testing / automation | 新 testing ready 报告 + automation-resume；无需人工批准，仍须真实补测 |
| testing | dod | 当前全部构建及自动化必需路径 Green |
| testing | diagnosing | 存在未解决问题；Diagnostician 仅提交报告，MO 接受当前版本诊断；无活动 worker |
| diagnosing | fixing | 根因报告、模块本地一轮或 Auditor 明确授权一轮、总预算内、合法写锁；不需改验收的补丁任务 |
| fixing | testing | 补丁与回归证据已接收、代码版本更新、受影响路径标 stale；正式 Test-Runner 复测 |
| diagnosing / fixing | change-review | 修改需求/验收/冻结任务或设计契约才可解决，提出 CR |
| change-review | specifying | Spec-Designer 影响分析、MO 审核；语义变化需人工；新 revision 重走冻结 |
| 未完成阶段 | waiting-auditor | 已确认依赖/外围问题或本地一轮仍未通过；MO audit-defer，保存根因、结果与恢复点 |
| waiting-auditor | testing / diagnosing / specifying | Auditor 问题审计裁决经 MO audit-resume 接受；wait 留队；不能直接 completed |
| 规划/重建阶段 | waiting-dependency | 普通 DAG 前置等待；需全局裁决时 audit-defer |
| 任意未完成阶段 | waiting-human | 非依赖 Yellow 需人工或预算耗尽，Escalation 已登记 |
| waiting-dependency | 恢复点 | Global 的 dependency_resolved + 重获锁 + baseline 复核；测试仍需复测 |
| waiting-human | 恢复点（原 dod 改为 testing） | decision 已接受且绑定当前问题/版本；若改契约则先 specifying |
| dod | completed | 所有 DoD 检查与证据齐全，MO 提 module_completed，Ledger 提交 |
| completed | testing / specifying | 审计问题经 MO repair-accept 进入 testing；代码/证据失效经 invalidate 进入 specifying；不能保留旧 Green |

模块执行严格为 Coding → 接受代码 → Test-Runner 编译构建 → 自动化预检/Testing。测试设计保留在冻结前，实际测试执行在 Coding 后。Testing 的可修复 Red/Yellow 均先诊断并由 MO 自动派发一轮 Fixer，接受补丁后回到 Test-Runner/Main 正式复测；不能用 Fixer 自测代替复测，也不能跳过可修复问题的本地首轮而直接等待 Auditor。复测 Green 且 DoD 满足由 MO 验收；一轮仍未通过则记录根因、结果、修复 memory 和恢复点，交 Auditor 收尾。已确认依赖/外围问题沿用直接记录/挂起规则。在 pre-code 阶段发现此类问题时不得测试或修复尚未生成的代码。

`resume_phase` 只能由原暂停点及新基线验证计算，不能接受外部随意指定。Ledger 只持久化合法且带 MO 批准的模块迁移；Global 的唤醒事件不等于模块迁移批准。

## Freeze / DoD 分开

freeze checklist 仅核准需求、设计、测试设计、任务、决策和范围。freeze_accepted 是检查成功后的提交结果，不是检查本身的前置项；同理 module_completed 与全局上报可同一事务提交，不要求事先完成上报才可通过 DoD。不能要求此时测试 Green，否则形成先有代码才能冻结、先冻结才能编码的死锁。

DoD checklist 要求：当前冻结有效；所有任务有提交/文件/需求/用例追溯；正常、边界、异常及全局分配用例的必需路径覆盖齐全；Main 真实测试、静态检查、构建门禁全部 Green；有效断言；无遗留 Red/Yellow；依赖契约匹配；CR 已处理；所有历史非 Green 有同 ID 新版本复测链；无 orphan 证据；清理临时修改；全局上报。

覆盖率分母为冻结的全部必需路径与验收条目。不能通过删除测试、降低阈值、忽略失败用例过门。合法范围变更必须 CR + 人类决策，旧路径以 superseded 关联新路径保留历史，不能当作通过。

## 有限循环

输入配置 `max_fix_rounds=3`、`max_yellow_retries=2`、`max_audit_rounds=3`、`max_no_progress_rounds=2` 为默认值，可由初始化明确调整。一次修复派发计一轮；失败或中断也消耗轮次；恢复不会清零。本地自动轮数固定为 1，后续由 Auditor 按一轮授权，总预算仍约束全部轮次。no-progress 使用未解决 path_id + 根因 fingerprint + 有效版本变化判断，单纯重跑不算进展。

到上限：保留实际 Red/Yellow，execution_status=suspended，转 Escalation 并让其余就绪模块继续；超时不准通过。增加预算必须绑定 run/module 的显式决策事件。依赖唤醒不耗修复轮次，但不能因反复醒来规避停滞检测。

## Auditor 与全局完成

Auditor 依次执行整体代码审查/治理、问题审计与最终审计；[代码治理](audit-code-review.md) 是必经前置，即使用例全 Green。两者都须等待全部模块本轮独立结束；问题审计允许部分模块基于自身证据明确挂起，无需全部 Green。最终审计要求全部模块 DoD 完成且队列清空，才可发布全局 Green。

Auditor 从 Ledger 固定 sequence 与 target tree/commit、SPEC revision、环境/测试定义摘要构成 audit snapshot。只复核收集到的 Red/Yellow 遗留，按 SPEC/CASE/PATH 分析根因、必要时委派一轮 Fixer，再以正式 Testing 验证；仍失败输出根因待人工。修复导致失效的相关模块按依赖图补回归，无关有效 Green 不重跑。无遗留只独立审阅现有证据；global_test_paths=[] 不阻止启动，绝不默认全量重跑。详见 [审计范围协议](audit-scope.md)。

Auditor 可执行既有脚本并生成日志，不能编辑源码/脚本。发现问题经 repair_requested → MO 审核/派发 → Fixer；结果仍由 Auditor 独立重跑和裁决。每轮新补丁会使旧 snapshot 失效，重新固定快照，重跑受影响路径及整体集成用例。不能混用不同代码树的结果出最终 Green。

最终报告列清所有非 Green 及原因；仅无遗留问题、全部必需用例/路径覆盖且同一最终基线通过，audit_verdict 才为 Green。仅自动化环境缺失时，本轮允许 completed-with-unverified-tests + Yellow 收尾，不等于功能验收；其他可执行工作继续，不以缺测强制全局等待人工。Global 仍需人类交付/核心架构/合并授权后才归档；普通 module completed 不代表已合并或已交付。

## 本地控制器映射（P2–P4）

可执行入口与操作矩阵见 [local-runtime.md](local-runtime.md)。它支持本地事件提交/重放、模块阶段串行和不同模块并行；控制器本身不常驻派发 Agent。

新增冻结前证据：`source_closure` 至少含真实入口、事件→状态/数据→结果执行链、生产绑定、证据引用与未决项；`target_feasibility` 包含已核实的目标接口/依赖/版本路线及证据。未知可行性先阻塞，不先写代码再隐瞒替代。

角色按需创建，9+1 是职责边界，不是固定同时驻留的十个实例。同角色优先恢复原 session；session 失效时，宿主先停止/隔离旧 worker，MO 记录 checkpoint 与替换原因后冷恢复。所有结果仍重新验证 assignment、冻结和代码基线；会话连续性不是验收证据。

`recover` 创建 recovery_cycle，并增加经批准的预算，不清零累计 fix_rounds_used/total_fix_rounds。审批 subject 同时绑定 module revision、cycle 与 additional_rounds；普通 resume 不增加预算。停滞检测触发后的新周期可清理本周期停滞计数，旧事实永久留在日志中。

部分验证（如 source-only）保存 Yellow 和具体缺失证据；不能映射为 completed/Green。视觉/资源能力暂不进入本轮实现，P5 保持可选。

本地审计闭环为 audit → audit_repairs → Global audit-route（全局 PATH）→ MO repair-accept → 诊断提交/接受或 Yellow 挂起 → 修复/复测 → 模块完成 → 新独立审计。具体字段、游标与恢复规则以 [本地操作矩阵](local-runtime.md) 为准。

OpenSpec 六件套和修复 memory 已由 Ledger 自动投影；版本化定义不被动态勾选修改。问题审计/全局覆盖/物化字段详见 [当前策略](local-runtime.md#当前策略全局验收问题审计openspec-与修复-memory)。

当前默认在所有模块本轮 completed/明确挂起且无可推进动作后，先 audit-code-review 及治理闭环，再采用剩余问题的 audit-collect 批次：Auditor 绑定发现/负责模块 SPEC 与测试路径，Global 路由审核，MO 接受一轮 Fixer；按 finding 路由及依赖交错 Testing；失败关联分支待人工，其他分支继续，汇总后 awaiting-human；批准 audit-release 后再进入正常恢复。旧 problem-* 重复问题审计保留兼容，详见 [默认收尾](local-runtime.md#当前默认-auditor-收尾修复后验证失败待人工)。

## 父子 MO 的规划与汇总

根功能 context → MO decompose → GO decompose-accept → 父节点 coordinating + 独立子模块 context。GO 分配根模块 scope/context；父 MO 认领后只在其范围内拆子模块并分配 scope/context；子 MO 认领后拆 tasks，不再创建 MO，沿本页原状态机执行。父 MO 不编码、不重复验收子 CASE；所有子 MO 逐个结束后，父 MO 按当前版本 module-summary。Auditor 门禁同时检查所有叶子和父汇总，见 [父子 MO 协议](module-decomposition.md)。

二方库复用评估在冻结前完成，实际提供方测试在 Coding 接受后执行。新的子 plan/prepare 运行要求 reuse_plan_ref，所选 provider/API 或接入证据变更被 current 校验识别为 stale；按 invalidate/CR 重新规划冻结，不直接恢复 Green。根因确认是提供方/外围问题则沿 audit-defer 进入统一收尾。详见 [二方库协议](reuse-dependencies.md)。

## 上下文门禁嵌入原状态机

各阶段先通过 context-submit 留证，原 plan/freeze/assign/audit 操作接受报告；该事件不改变业务 phase、不消费修复预算、不直接赋予 Green。缺失经既有 suspend/audit-defer/audit-block 记录后才可作为明确收尾；无关兄弟继续。详见 [上下文就绪协议](context-readiness.md)。

## 自动化缺测与代码依赖就绪

遵守 [双环节协议](build-automation.md)。dependencies_ready 允许 completed 或当前构建通过且未过期的 automation-deferred 上游；构建失败或实际不可用依赖仍阻塞实际消费者。仅自动化环境缺失不走普通 tooling→waiting-human 分支。build/automation 分开记录，父汇总接受缺测收尾，Auditor 最终保留完整缺测清单。

## 失效恢复与停滞感知

证据失效 → 实际停止/revoke 活动 worker → invalidate 归档旧 plan 并进入 specifying → 分配有效则 plan，分配无效则 GO allocation-review-required。旧计划不能反复挡住重新规划；新 SPEC 仍须冻结。status.workflow_progress 对无动作且无 worker、超时 worker、连续门禁拒绝和人工待决给出责任与证据；宿主继续独立动作并明确提醒用户。详见 [进度恢复协议](progress-recovery.md)。

## 埋点适用性不产生新状态

按 [埋点协议](telemetry.md)，无埋点模块/任务的 not-applicable 只记录范围判断，不转换为 waiting/Yellow/skip，不消耗修复预算，不增加全局等待条件。有埋点时沿已有 SPEC冻结→Coding→Build→业务Testing→三态/Fixer→Auditor；真实未知或失败仅影响本模块及实际依赖，其他 MO 继续。
