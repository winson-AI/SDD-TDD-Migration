# 状态机与双层三态

## 三种不同字段

- `phase` 是工作阶段，不是测试结论。
- `execution_status = pending | running | suspended | completed | failed` 描述调度生命周期；failed 指基础设施或执行异常，不能直接等同产品缺陷。
- `quality = green-passed | red-bug | yellow-blocked` 用于测试路径和模块两层；全局继续聚合模块与全局用例。未运行、缺证据或过期统一 Yellow，并用 reason_code 区分 untested / stale / dependency / environment / human / tooling / flaky / incomplete。Green 不是空集合默认值。

路径 Red 表示实际断言/构建等质量门禁证明实现有错；Yellow 表示不能确定验收是否成立。Red/Yellow 均必填 root_cause，证据不足时明确 confidence=unknown、hypothesis 与 next_action，禁止编造已确认根因。

模块聚合：有效结果中任何 Red → Red；否则有 Yellow、漏测、未运行、stale、冻结/DoD未完成 → Yellow；仅全部必需路径有效 Green 且 DoD 满足 → Green。Red 与 Yellow 可以同时存在，aggregate 取 Red，但 unresolved 列表保留两类全部问题。全局还须覆盖整体用例、独立审计和集成基线；没有模块或没有必需测试不能为 Green。

## Module-Orchestrator 唯一模块守卫

| 当前 phase | 下阶段 / 动作 | 必须证据与守卫 |
| --- | --- | --- |
| context | specifying | `_input`、全局规范/架构/用例、legacy/target baseline 可读 |
| specifying | clarifying | 六件套草稿、独立 test design、覆盖映射齐全 |
| clarifying | frozen | R1/R2 人工决定绑定冻结内容摘要；所有 freeze checklist 通过；无未决阻断问题；MO 接受 |
| frozen | implementing | 全局覆盖验收通过、冻结内容摘要匹配、依赖满足、目标写锁有效、tasks 非空 |
| implementing | testing | implementation_submitted 被 MO 接受；测试路径与断言已在冻结前定义，现绑定实际代码、脚本和环境执行 |
| testing | dod | 当前全部必需路径 Green |
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

模块执行严格为 Coding → 接受代码 → Testing。测试设计保留在冻结前，实际测试执行在 Coding 后。Testing 的可修复 Red/Yellow 均先诊断并由 MO 自动派发一轮 Fixer，接受补丁后回到 Test-Runner/Main 正式复测；不能用 Fixer 自测代替复测，也不能跳过可修复问题的本地首轮而直接等待 Auditor。复测 Green 且 DoD 满足由 MO 验收；一轮仍未通过则记录根因、结果、修复 memory 和恢复点，交 Auditor 收尾。已确认依赖/外围问题沿用直接记录/挂起规则。在 pre-code 阶段发现此类问题时不得测试或修复尚未生成的代码。

`resume_phase` 只能由原暂停点及新基线验证计算，不能接受外部随意指定。Ledger 只持久化合法且带 MO 批准的模块迁移；Global 的唤醒事件不等于模块迁移批准。

## Freeze / DoD 分开

freeze checklist 仅核准需求、设计、测试设计、任务、决策和范围。freeze_accepted 是检查成功后的提交结果，不是检查本身的前置项；同理 module_completed 与全局上报可同一事务提交，不要求事先完成上报才可通过 DoD。不能要求此时测试 Green，否则形成先有代码才能冻结、先冻结才能编码的死锁。

DoD checklist 要求：当前冻结有效；所有任务有提交/文件/需求/用例追溯；正常、边界、异常及全局分配用例的必需路径覆盖齐全；Main 真实测试、静态检查、构建门禁全部 Green；有效断言；无遗留 Red/Yellow；依赖契约匹配；CR 已处理；所有历史非 Green 有同 ID 新版本复测链；无 orphan 证据；清理临时修改；全局上报。

覆盖率分母为冻结的全部必需路径与验收条目。不能通过删除测试、降低阈值、忽略失败用例过门。合法范围变更必须 CR + 人类决策，旧路径以 superseded 关联新路径保留历史，不能当作通过。

## 有限循环

输入配置 `max_fix_rounds=3`、`max_yellow_retries=2`、`max_audit_rounds=3`、`max_no_progress_rounds=2` 为默认值，可由初始化明确调整。一次修复派发计一轮；失败或中断也消耗轮次；恢复不会清零。本地自动轮数固定为 1，后续由 Auditor 按一轮授权，总预算仍约束全部轮次。no-progress 使用未解决 path_id + 根因 fingerprint + 有效版本变化判断，单纯重跑不算进展。

到上限：保留实际 Red/Yellow，execution_status=suspended，转 Escalation 并让其余就绪模块继续；超时不准通过。增加预算必须绑定 run/module 的显式决策事件。依赖唤醒不耗修复轮次，但不能因反复醒来规避停滞检测。

## Auditor 与全局完成

Auditor 分问题审计与最终审计。问题审计处理 waiting-auditor 队列，不要求所有模块完成；最终审计仍要求全部完成且队列清空，才可发布全局 Green。

Auditor 从 Ledger 固定 sequence 与 target tree/commit、SPEC revision、环境/测试定义摘要构成 audit snapshot。先重跑所有历史未解决非 Green/过期/未运行路径，再执行全部整体测试和受影响回归；即便各模块全 Green，也不能跳过全局集成测试。

Auditor 可执行既有脚本并生成日志，不能编辑源码/脚本。发现问题经 repair_requested → MO 审核/派发 → Fixer；结果仍由 Auditor 独立重跑和裁决。每轮新补丁会使旧 snapshot 失效，重新固定快照，重跑受影响路径及整体集成用例。不能混用不同代码树的结果出最终 Green。

最终报告列清所有非 Green 及原因；仅无遗留问题、全部必需用例/路径覆盖且同一最终基线通过，audit_verdict 才为 Green。Global 仍需人类交付/核心架构/合并授权后才归档；普通 module completed 不代表已合并或已交付。

## 本地控制器映射（P2–P4）

可执行入口与操作矩阵见 [local-runtime.md](local-runtime.md)。它支持本地事件提交/重放、模块阶段串行和不同模块并行；控制器本身不常驻派发 Agent。

新增冻结前证据：`source_closure` 至少含真实入口、事件→状态/数据→结果执行链、生产绑定、证据引用与未决项；`target_feasibility` 包含已核实的目标接口/依赖/版本路线及证据。未知可行性先阻塞，不先写代码再隐瞒替代。

角色按需创建，9+1 是职责边界，不是固定同时驻留的十个实例。同角色优先恢复原 session；session 失效时，宿主先停止/隔离旧 worker，MO 记录 checkpoint 与替换原因后冷恢复。所有结果仍重新验证 assignment、冻结和代码基线；会话连续性不是验收证据。

`recover` 创建 recovery_cycle，并增加经批准的预算，不清零累计 fix_rounds_used/total_fix_rounds。审批 subject 同时绑定 module revision、cycle 与 additional_rounds；普通 resume 不增加预算。停滞检测触发后的新周期可清理本周期停滞计数，旧事实永久留在日志中。

部分验证（如 source-only）保存 Yellow 和具体缺失证据；不能映射为 completed/Green。视觉/资源能力暂不进入本轮实现，P5 保持可选。

本地审计闭环为 audit → audit_repairs → Global audit-route（全局 PATH）→ MO repair-accept → 诊断提交/接受或 Yellow 挂起 → 修复/复测 → 模块完成 → 新独立审计。具体字段、游标与恢复规则以 [本地操作矩阵](local-runtime.md) 为准。

OpenSpec 六件套和修复 memory 已由 Ledger 自动投影；版本化定义不被动态勾选修改。问题审计/全局覆盖/物化字段详见 [当前策略](local-runtime.md#当前策略全局验收问题审计openspec-与修复-memory)。

当前默认在所有模块本轮 completed/明确挂起且无可推进动作后，统一采用 audit-collect 批次：Auditor 绑定发现/负责模块 SPEC 与测试路径，Global 路由审核，MO 接受一轮 Fixer；按 finding 路由及依赖交错 Testing；失败关联分支待人工，其他分支继续，汇总后 awaiting-human；批准 audit-release 后再进入正常恢复。旧 problem-* 重复问题审计保留兼容，详见 [默认收尾](local-runtime.md#当前默认-auditor-收尾修复后验证失败待人工)。
