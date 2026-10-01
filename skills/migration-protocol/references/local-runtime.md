# 本地运行指南

## 专题规则入口

本文件只记录本地控制器的命令、操作字段、游标与审计批次细节。以下规则以专题协议为准，这里不再重复：

| 主题 | 权威协议 |
| --- | --- |
| 同 run 来源追加 | [来源变更](source-changes.md) |
| 全局覆盖验收、模块隔离与全量收尾 | [状态机](state-machine.md#模块隔离与全量收尾) |
| 本地修复轮次（`local_fix_rounds`）与预算 | [状态机：有限循环](state-machine.md#有限循环)、[构建预算单位](build-automation.md#本地一轮的预算单位) |
| 项目级/单模块入口、功能清单完备性 | [切片规约](../../migration-global/references/slicing.md) |
| 项目上下文 prepare/init 绑定 | [项目上下文](project-context.md) |
| 二方库与已有能力复用 | [复用协议](reuse-dependencies.md) |
| 上下文就绪控制节点 | [上下文就绪](context-readiness.md) |
| 停滞信号与 invalidate 恢复 | [恢复与进度](progress-recovery.md) |
| build → static → automation → visual | [构建与自动化](build-automation.md)、[静态规格闭合](testing.md#静态规格闭合) |
| 四维分配与冻结字段 | [四维协议](dimension-slicing.md) |

## 已实现与宿主责任

本地实现使用 Python 3.10+ 标准库，在 macOS/Linux 上用 `fcntl.flock` 串行提交；不支持 Windows 原生文件锁。单进程或多个 CLI 进程都通过同一个 run root 的锁写日志。模块工作可并行，只有事务提交串行。

脚本负责：合法阶段、结果/版本/路径校验、请求幂等、revision CAS、活动 assignment 资源冲突、证据快照、日志 hash 链、冷读投影、恢复预算和独立审计身份冲突检查。

宿主负责：认证调用者、限制其可用 role/module/operation、保护 `--host-context` 与证据目录、真正停止旧进程、限制实际源码写范围、审核测试 argv、启动/恢复 Agent、执行可选 OpenSpec CLI 验证及最终基线同步/归档。**任意本机进程都能修改所有文件时，CLI 不是安全隔离边界。** 不得给 worker 自选 host-context 的能力；本地 receipt 检查也不是对任意伪造文件的密码学认证。

没有宿主适配器时可运行这里的隔离测试与手工受控调用，但不能声称已具备无人值守迁移服务。

## 命令

以下路径中的 `<package>`、`<run>`、`<request>`、`<principal>` 均需换成绝对路径。

```text
python3 <package>/skills/migration-ledger/scripts/ledger.py init --root <run> --request <request.json> --host-context <principal.json>
python3 <package>/skills/migration-ledger/scripts/ledger.py apply --root <run> --request <request.json> --host-context <principal.json>
python3 <package>/skills/migration-ledger/scripts/ledger.py status --root <run>
python3 <package>/skills/migration-ledger/scripts/ledger.py resume --root <run> --request <request.json> --host-context <principal.json>
python3 <package>/skills/migration-ledger/scripts/ledger.py recover --root <run> --request <request.json> --host-context <principal.json>
python3 <package>/skills/migration-ledger/scripts/verify_openspec.py --root <run> --scope module --module-id <module-id>
```

`verify_openspec.py` 只读核验指定范围的记录/投影：global 用于公共基础，module 用于当前模块、祖先和实际依赖，projection（默认）检查全量视图，final 另要求正式收尾报告。planning 阶段 projection 可以通过；这不证明真实派发、命令执行或功能 Green。失败按 scope/module_id/recovery_action 恢复相关范围，无关 MO 继续，不把全量 projection 失败作为所有模块的共同门禁。详见 [留存布局](storage-layout.md#openspec-投影完整性收尾门禁)。

`init/resume/recover` 是对同名 operation 的入口校验，仍经过同一事务函数。成功返回 event_id/sequence/duplicate，拒绝返回 exit 1 和原因。业务状态以日志/投影为准，CLI exit 0 仅说明请求已接受。

宿主 context 的最小结构：`{"role":"module-orchestrator","instance_id":"mo-M001"}`。这些值必须由宿主认证后注入，不能从业务请求推导。请求参考 [ledger-request.json](../../../template/ledger-request.json)：

```json
{
  "schema_version": 1,
  "request_id": "unique-request-id",
  "run_id": "migration-demo",
  "module_id": "M001",
  "expected_revision": 3,
  "operation": "plan",
  "payload": {"plan_ref": {"path": "/workspace/migration/.sdd-runs/run-demo/staging/stage-plan.json", "sha256": "actual-sha256"}}
}
```

相同 request_id+完整请求+调用身份重复提交返回原 ACK，内容变化拒绝。module_id 非空校验模块 revision，否则校验全局 revision；**decision/register/global-plan/problem-assign/problem-audit/audit-collect/audit-plan/audit-route-batch/audit-verdict/audit-release/audit-assign/audit/audit-revoke/audit-route 的请求顶层 module_id 必须为 null**，其适用模块在 payload 中记录。每次有效模块操作增加模块 revision；跨模块失效会增加相关消费者 revision。

hash 算法：`contracts.digest(value)` 为排序键、无多余空格、UTF-8 JSON 的 SHA256；`contracts.file_ref(path)` 返回真实绝对路径与文件字节 SHA256。不要用系统 `shasum` 计算 JSON 对象摘要冒充 canonical digest。

## 操作矩阵

这是本地控制器的完整支持集；其他抽象事件由宿主翻译，未知 operation 拒绝。

| operation | 调用角色 | payload 必需内容 / 行为 |
| --- | --- | --- |
| init | host | target_root、legacy_root、非空唯一 case_ids；必填 global_spec/new_architecture 文件引用、非空唯一 requirement_ids；可选 global_paths、max_fix_rounds/max_no_progress_rounds/max_parallel_modules/max_audit_rounds；默认 3/2/3/3 |
| register | Global | module_id、case_ids、write_paths、dependencies；按拓扑顺序登记，依赖必须已存在，从而拒绝环/未知模块。原子根功能可登记为 `lean_leaf=true`：须有 scope（in/out/requirement_ids）、context_refs 与 GO 的 leaf_review_ref，不可同时 decomposition_required |
| decompose | 父 MO / 父 module_id | plan_ref；planning_context + assigned_module，子功能 scope/context_refs/CASE/写范围/依赖提案 |
| decompose-accept | Global / 父 module_id | review_ref；复核 MO 提案并原子登记子模块，父移入 module_groups |
| module-summary | 父 MO / 父 module_id | summary_ref、subject_sha256；全部后代收尾后绑定当前版本汇总 |
| decision | host | decision_id、decision=approved、module_id、subject_sha256、human_source_ref；保存真实人类决定引用。`kind=batch-envelope` 时 module_id 为父模块，envelope_ref 指向 [批量信封](../../../template/batch-envelope.json)，subject_sha256 等于其文件 hash，children 只能是该父的孩子 |
| global-plan | Global | plan_ref + review_ref；验收全部需求/用例归属，绑定当前 registry；新增模块后必须重审，通过前禁止实现派发 |
| audit-collect | Global | batch_id、独立 auditor_instance_id；所有模块本轮完成/明确挂起且没有可推进工作后，收集 finding/PATH、上下文和 round_snapshot |
| audit-plan | Auditor | plan_ref；每个 finding_id 一个路由，source_module_id、owner_module_ids、source_context/owner_contexts、analysis_ref、root_cause、action=fix/verify/human |
| audit-route-batch | Global | review_ref；审核 finding 责任映射及依赖图；human 分支挂起，独立分支继续 |
| audit-work | MO | 顶层 module_id 指负责模块；接受被冻结的修复任务，一轮 Fixer 授权；前置不可满足则报告待人工 |
| audit-retest | MO | 顶层 module_id 指发现模块或受影响中间模块；只等待本模块的上游修复/复测完成，执行完整模块路径 |
| audit-verdict | Auditor | review_ref；双方验证齐全、同基线、DoD 完成才裁决通过；过期证据报告待人工 |
| audit-defer | MO | root_cause + evidence_ref；记录根因、结果和恢复点，进入 waiting-auditor；可修复错误先本地一轮，确认的依赖/外围问题直接交接 |
| problem-assign | Global | assignment_id、独立 instance_id，可选 module_ids（默认全部队列）；只要求这些模块的依赖闭包与下游消费者（及其依赖）已收尾、空闲；assignment 记录 closure，审计锁只作用于 closure 内模块与全局操作，其他模块继续。预算按模块计（max_audit_rounds）；游标在闭包就绪且全局未收尾时给出 `problem-assign`（reason=audit-closure-settled） |
| problem-audit | Auditor | report_ref；覆盖本次所有排队模块；有效代码独立 tests result，无法运行保留 Yellow；输出 retry/fix/change/wait/human 裁决 |
| audit-resume | MO | 接受本模块问题审计裁决；human 需 decision_id；wait 保持队列；retry 回 testing，fix 授权一轮，change/human 回规划 |
| plan | Spec-Designer | plan_ref；完整 [stage-plan](../../../template/stage-plan.json) |
| freeze | MO | 初始/边界外变更 decision_id；边界内变更 change_class=within-envelope + impact_ref；批量信封 decision_id 另需 review_ref（MO 对详细 tasks/PATH 的审阅），子 plan 的 decision_envelope 必须与信封条目完全一致，信封可被多个孩子使用并记录 used_by |
| change | MO | request_ref + impact_ref；无 blocker 时进入 change-review，记录 from_freeze_id；within-envelope 的 impact JSON 必须绑定该旧 freeze 与新 to_plan_hash，见 change-impact 模板 |
| assign | MO | assignment_id、role=implementer/fixer/test-runner、instance_id，可选 session_id、card_sha256（宿主实际采用的提示，仅记录）；阶段合法且无活动 worker；返回的投影含 fencing_token |
| submit | 对应 worker | assignment_id、fencing_token、result_ref；只提交，不改变业务阶段 |
| accept | MO | assignment_id；再次检查工件和版本后关闭 assignment、推进阶段 |
| diagnose | Diagnostician（轻量叶子本地轮为 Fixer） | diagnosis_ref、owner、root_cause；仅保存绑定当前冻结、代码和未解决结果的 diagnosis_submission，不改变 phase；模块必须无活动 worker |
| diagnosis-accept | MO | 可选 `assign`（fixer 的 assign 参数 + context_ref）；重验诊断后进入 diagnosing，带 assign 时同一事务校验 fixing 预检并按 assign 守卫派发，失败整体拒绝 |
| suspend | MO | kind=dependency/human/tooling、reason、root_cause、owner；保存原阶段，必须先停止活动 worker |
| dependency-ready | Global | 消费者 module_id 在请求顶层；检查生产者完成，记录当前版本的解除许可 |
| resume | MO | 依赖等待检查 Global 许可；其他等待需 decision_id，其 subject 是当前 blocked 对象摘要；恢复不变 Green |
| recover | MO | decision_id、additional_rounds；仅修复/停滞预算耗尽后增加预算，保留累计使用量 |
| session | MO | role、session_id；替换原会话须 reason=session-unavailable、checkpoint_ref，且旧 assignment 已关闭 |
| revoke | host | assignment_id、stopped_worker_ref；实际停止/隔离后才释放活动占用；旧 token 不再被接受 |
| invalidate | MO/host | reason；旧 worker 必须先 revoke；重新进入 specifying，并使消费者及全局审计失效 |
| checkpoint | host | receipt_ref（git_checkpoint.py 回执）；仅 git_checkpoint 开启且模块在 DoD 时，逐文件 blob 必须等于当前已接受代码，见 [模块 Git 检查点](engineering-disciplines.md#模块-git-检查点可选默认关闭) |
| complete | MO | dod_ref、checks_passed=true；开启 git_checkpoint 时须已有当前 code_baseline 的检查点；当前模块全路径 Green、版本有效、依赖完成才可接受 |
| audit-assign | Global | assignment_id、instance_id；全部模块完成后固定快照；审计实例不能是任意实现/修复/测试作者实例 |
| audit-route | Global | path_id、非空唯一 module_ids、reason_ref；给尚无负责模块的全局审计问题分配责任，不修改模块阶段 |
| repair-accept | MO | 非空唯一 path_ids；接受分配给本模块的审计问题，在依赖就绪且无 worker/blocker 时从 completed/testing 重开 testing；保留原失败供诊断分流 |
| audit-revoke | host | assignment_id、stopped_worker_ref；停止活动审计，保留已用次数，才能分配下一轮 |
| audit | Auditor | report_ref；按 tests 提交 assignment.path_ids 的复核结果；空清单按 audit-review 提交独立审阅；均带 snapshot |

`init` 的 case_ids/global_paths 来源于 global-input 的整体用例及 global_test_paths；Global 负责把其余规范/架构信息引用进每个 stage-plan，控制器不替模型拆分需求。global_paths 为可选项，缺失或 [] 都不阻止 Auditor。不同模块及全局 PATH ID 必须全局唯一。audit-assign 从遗留状态生成 path_ids，排除有效 Green；空清单只做独立审阅，详见 [审计范围协议](audit-scope.md)。

本地角色身份校验不自动完成业务审核：source_closure 是否真实完整、测试语义是否正确、envelope 是否被违反、DoD 内容是否成立均需对应独立角色审查。脚本校验的是工件与守卫条件，不能用布尔 `checks_passed` 替代人工/Agent 的实际审核过程。

## 阶段结果

所有结果必需 schema_version=1、kind、run_id、module_id、assignment_id、actor_instance_id、freeze_id、code_baseline。

implementation 另需：

```json
{
  "code_files": [{"path": "/target/module/source.py", "sha256": "actual-file-hash"}],
  "task_trace": [{"task_id": "TASK-M001-001", "files": ["/target/module/source.py"]}],
  "production_binding_evidence": {"path": "/run/evidence/binding.md", "sha256": "actual-file-hash"},
  "authoring_diagnostics": {"status": "passed", "tool": "IDE/MCP changed-file diagnostics", "log_ref": {"path": "/run/evidence/diagnostics.log", "sha256": "actual-file-hash"}}
}
```

`authoring_diagnostics` 是代码作者（Implementer/Fixer）交付前的轻量自检：`passed` 表示已运行改动文件诊断并修完全部错误，附 tool 与 log_ref；宿主不提供诊断时用 `unavailable` + reason，并在 `version_sensitive_apis` 为每个新引入的版本敏感 API 引用其固定版本依赖源码（source_ref），没有则为空列表。它不是正式构建，也不能代替 Test-Runner 的 build PATH。

code_baseline = `contracts.baseline(code_files)`，源码文件必须仍存在且摘要匹配；目标写范围以 realpath 检查，任务必须完整映射代码文件。code_files 是 worker 自填的结果清单，不能单独证明没有越界写入；开启 `write_scope_check` 后由[写范围核验](engineering-disciplines.md#写范围核验可选默认关闭)比对实际改动。

tests 另需 paths，见 [stage-result.json](../../../template/stage-result.json)。每个冻结 PATH 都要有结果；Green 需实际回执、断言集合一致、预期值不变，且 JSON equality 成立。Red 需真实失败；Yellow 需 root_cause.category/summary/confidence/owner/next_action。失败不等于已确认根因。

## 实际测试适配器

宿主先审核并配置 [test-adapter.json](../../../template/test-adapter.json) 的 argv，再运行：

```text
python3 <package>/skills/migration-ledger/scripts/execute_test.py --root <run> --module M001 --assignment TEST-001 --path-id PATH-M001-001 --adapter <adapter.json> --cwd <target> --output <run>/runs/harmony/automation/<new-attempt>
```

适配器接收 `--query-file <json> --result-file <json>`，写 `{"assertions":[{"assertion_id":"A1","expected":2,"actual":2,"passed":true}]}`。具体测试逻辑来自真实项目，本包只负责调用与采集。

每条执行使用新目录，不覆盖历史。`receipt.json` 包含 test_run_id、代码/SPEC/路径绑定、实际 argv/cwd、时间、退出码及 result/log/query refs。执行结束不直接推进 Ledger：Test-Runner 整理完整 paths 后 submit，MO 再 accept。缺报告、超时、适配器异常保留日志并报告 Yellow；不拼造 Green。不得把同基线 flaky 结果择优记绿；稳定性判断由 Test-Runner/Auditor 承担，本地字段 `flaky=true` 会拒绝 Green，跨进程历史 flaky 自动识别尚不提供。

全局审计由 Global audit-assign 后，使用 `--module GLOBAL --assignment <audit-id>` 仅对 audit_assignment.path_ids 分别执行。报告 kind=tests、module_id=GLOBAL，freeze_id/code_baseline 来自 `ledger.audit_scope(state)`，另带 `snapshot={module_id: code_baseline}`。非 Green 报告生成 audit_repairs：模块 PATH 自动对应所属模块；全局 PATH 由 Global audit-route 分配一个或多个责任模块，MO repair-accept 后重开。Auditor 不改源码。

## 恢复与预算

先 status 重放事实，读取 session、phase、blocked、计数和 observed_invalidations。文件变动导致证据过期时先由 host revoke 活动 worker，再由 MO invalidate；status 不悄悄写业务完成事件。

recover 的批准 subject：

```text
digest({module_id, revision, recovery_cycle, additional_rounds})
```

decision 为全局操作，不增加模块 revision，因此记录批准后 recover 可验证同一模块修订号。普通 resume 的 subject 为整个 blocked 对象摘要。恢复会话以 session 记录；冷恢复 checkpoint 包含 Ledger sequence、模块 revision、冻结引用、当前代码和 next_action，不依赖聊天摘要。

recover 只授权增加预算；已有 human、tooling 或 dependency 阻塞时，保留 blocked、当前等待阶段及 resume_phase，继续展示原阻塞和恢复动作。human/tooling 仍须绑定该 blocked 摘要的单独 resume 决定；dependency 仍须依赖就绪和 GO 的 dependency-ready。预算批准不能同时充当解除阻塞的批准。无阻塞时保持原恢复行为：有 diagnosis 回到 diagnosing，否则回到 testing；不改变其他模块状态或测试颜色。

本地使用 fix_rounds_used（累计）+ recovery_cycle + 可增加的 fix_budget；no_progress 根据未解决 PATH 的 ID、三态、根因 category/summary/owner 的稳定摘要计数；相同问题才累加，根因改变会重新观察。此处比较结构化声明，语义真实性仍由诊断者和 MO 审核。审计达到 max_audit_rounds 后停止，须显式建立后续受控运行；本地 recover 不重置全局审计预算。协议里的独立 yellow retry/超时升级由宿主策略执行，本地重复验证另受 no-progress 守卫限制。

本地锁不使用自动租约超时重授：活动 assignment 一直占用模块资源，直到 accept 或带真实停止证据的 revoke。此方式避免仅因时钟到期就允许两个 worker 写同一路径。宿主仍必须在每次真实写操作执行 ACL/fencing。

## 证据、崩溃与已知边界

- 输入 ref 工件在提交事件前复制到 artifacts/<sha256>，历史事件引用副本；代码原路径同时用于新鲜度校验。
- hash 链可检测非授权意外篡改，但不是抵御能够重写整本日志的攻击者的签名链。
- 事件落盘后投影失败，下次 status/重复请求会从日志重建；不会重新派发已确认请求。
- 完整事件中部或尾部损坏均停止；不自动删除证据。宿主须从已校验备份恢复或人工处置。
- global/module JSON、OpenSpec 六件套及 memory 已实现自动投影；从 Ledger 与定义快照重建，不能成为第二事实源。

## 编排游标

采用上传包的 NEXT/next_skill、blocked_from、阶段 require_state 和轮次保留机制，适配为 Ledger 派生游标：

- `status.next_steps`：每模块 operation、role、worker_role（如适用）、session_id、assignment_id、expected_revision、ready、reason。每个有 operation 的步骤带 `must_read` 阅读卡（[reading.py](../../migration-ledger/scripts/reading.py)：ref、section、bytes）及其摘要 `card_sha256`，随派发交给角色；assign 时宿主回填实际使用的 `session_id` 与交付的 `card_sha256`，Ledger 在 assignment.hints 记录建议值、实际值与是否采纳，汇总到 `status.hint_adoption` 和 `ledger/model-usage.json`。提示不是门禁，不回填记为 unreported；`global_next_step` 同样提供。本地修复无 fixer 会话时，session_id 指向原 Implementer 会话（`session_affinity=implementer`）；审计期修复不做此提示。未解决结果含已确认 `runtime-spec-variant-conflict` 时，游标为 `suspend(kind=human)`，不进入诊断或修复。
- `status.ready_modules`：当前有可推进步骤的模块；并非可以同时启动的预约。多个候选可能争用同一资源，真正 assign 仍在事务内再次校验。
- `status.global_next_step`：等待模块完成、创建审计、等待活动审计、撤销失效审计或等待交付授权。游标不自动派发，也不赋予额外权限。
- 已提交 worker 结果对应 `accept`；未提交对应 `await-result`。原会话通过 session_id 提示复用；短交接只传 Ledger/assignment/artifact 引用。
- 禁止重复 suspend 覆盖原恢复点；completed 不能经 suspend 偷偷重新打开。需要重开时使用 invalidate/CR 的正式路径。
- submit 与 accept 均核验角色对应的当前 phase、blocked 和生产者实际基线，防止依赖失效后旧 worker 推进消费者。
- revoke 只作用于仍活动的任务，已关闭旧任务不能把新任务阶段倒退；依赖挂起时撤销 worker 保留原 blocker。
- 活动审计不能被另一轮覆盖；audit 成功接收后关闭 assignment；中断必须 host audit-revoke 提交实际停止证据。assignment_id 不复用，撤销不返还已用轮次。

这些规则保留本系统的 9+1 分工和跨模块并行，不采用全流程单切片串行，也不采用部分验证即 COMPLETE 的语义。

## 控制流闭环修订

- `diagnose` 现在只提交诊断，调用方必须追加 MO 的 `diagnosis-accept`；旧宿主不得在诊断 ACK 后直接 assign Fixer。复测后旧诊断作废，不能用旧问题的报告批准新修复。
- `next_steps` 对 Red/Yellow 共用一轮策略：已确认依赖/外围根因 → audit-defer；其余先 diagnose → diagnosis-accept → 一轮 Fixer → Main 复测，仍非 Green → audit-defer。未知根因不能伪报已确认。
- 人工恢复游标返回当前有效 `decision_id`；再冻结游标返回可提交的 `payload`，包括 within-envelope 的影响分析引用。候选 ready 仍需宿主补齐实际审查证据并经事务复核。
- DoD 挂起恢复进入 testing，旧结果 stale，正式新一轮复测后才能 complete；其余恢复点保持原阶段。`invalidate` 清除阻塞及解除许可、旧 freeze_id；历史 blocker 留在事件中。原来有 blocker 时同时撤销批准边界复用，重规划必须取得新人工冻结批准，不能靠 invalidate 绕过未决问题。存在 blocker 时禁止 CR 和 assign。
- 审计问题保存在 `audit_repairs`，`module_ids/accepted_by` 记录责任和 MO 接受情况。全局游标先提示 audit-route 或等待 MO 接受；未路由/未接受的问题禁止下一轮 audit-assign。有关联依赖的模块先完成原有恢复/重建，再接收其修复项。
- MO repair-accept 保留 `repair_findings` 供 diagnose/Yellow 路由，按原有 CR、修复预算和复测规则执行。模块正式测试接受后清除此轮 repair_findings；这只表示模块验证结束，审计问题仍须 Auditor 重跑裁决。
- `audit_results` 保留上一轮独立审计结果，不随代码失效清空。下一轮非 Green 同 PATH 必须提供新的 test_run_id 和 retest_of；模块重新 Green 不能解除这一要求。新审计覆盖完整集合后替换当前 repair 列表，旧报告保留于事件和工件。
- 若全局问题无法归属现有模块，Global 交 Escalation 取得范围/架构决策，不能随意指定模块或跳过问题。全局审计预算耗尽仍沿用受控新运行规则。

## 当前策略：全局验收、问题审计、OpenSpec 与修复 memory

### 问题审计与最终审计

问题审计：problem-assign → Auditor 用 execute_test --module Mxxx --assignment <problem-id> 执行 → problem-audit → MO audit-resume。assignment 对应的 module_ids 全部必须在报告中出现。可执行模块 result 使用既有 tests 结构，actor_instance_id 为独立 Auditor；冻结、代码、所有 PATH/断言、历史非 Green retest_of 均校验。缺代码、定义失效或生产者未就绪的模块禁止执行，只报 quality=yellow-blocked、result=null 和结构化根因。

Auditor 裁决：

- retry：独立复测全部 Green；MO 恢复 testing 且 stale，仍需 Main 新复测与 DoD，不能直接 completed。
- fix：独立复测仍有问题；MO 接受后按现有契约授权一轮 Fixer，总预算不足仍须显式 recover 决策。该轮失败再交 Auditor。
- change：需调整契约；MO 回 specifying，新的人类批准后重新冻结，不授权 Auditor/Fixer 改验收。
- wait：依赖/外围问题未解除，保留队列；先解决前置，再按问题审计预算重新复测。
- human：人工裁决；批准 subject=digest(audit_resolution)，MO 接受后重新规划与冻结。

问题审计不发布全局 Green。收尾仍要求 audit_queue 清空、模块完成或合法 automation-deferred；只处理剩余待验证路径，空清单使用 audit-review。失败沿用 audit-route/repair-accept 闭环，保留独立性。问题审计与最终审计各自受 max_audit_rounds 限制，次数在撤销后不返还。

审计期间冻结业务操作和 worker 派发；旧进程必须真正停止。使用既有 audit-revoke 撤销问题/最终审计，附宿主停止证据。问题快照绑定模块 revision/phase/freeze/code/blocker/results；源码或定义变动会使执行不可用或结果拒收，不能混用新旧证据。

### OpenSpec 自动物化

提交事件后及 status 重放时，生成 `<workspace_root>/openspec/changes/<run-id>-<module-id小写>/`：proposal.md、specs/<capability>/spec.md、design.md、tasks.md、status.md、checklist.md，以及 memory.md/manifest.json。定义作者仍为 Spec-Designer；Ledger 复制已提交的不可变定义快照，不凭空发明需求。spec 引用可带合法 capability；默认使用小写模块编号。

tasks 定义必须含每个 TASK-ID 对应的 Markdown checkbox；依据已接受 task_trace 更新 `- [ ] TASK-ID` 勾选；checklist 保留定义并追加机器证据，status 记录阶段、有效三态和下一步。更新视图不会改定义快照、freeze_id 或验收。视图丢失/被改后可由日志重建，旧生成的能力文件由 manifest 清理。可见文件是投影，不可直接编辑作为新 SPEC；变更必须提交 plan/CR。

当前执行 OpenSpec delta 结构检查，manifest 标 structural-only；未伪称 CLI 验证成功。CLI 验证、正式基线合并/归档仍由宿主按项目门禁执行。

### 修复 memory

Fixer 的 implementation 必须带 fix_note_ref，内容见 [fix-note 模板](../../../template/fix-note.json)：root_cause、strategy、applicability、risks。Ledger 保存 diagnosis、问题快照、冻结版本、前后代码基线、任务/补丁引用和正式回归证据，生成模块 memory.md 与全局 ledger/repair-memory.json。

pending / interrupted / awaiting-regression / failed / verified 区分修复事实；只有正式回归全 Green 的记录 reusable=true。复用前按根因、适用条件和当前 SPEC 比较，引用 memory 所属事件/工件；memory 不授予写权限，不替代本轮测试，也不允许降低验收。失败记录仍可用于避免重复无效方案。

兼容性：旧 init 请求需补整体输入与 requirement_ids；实现前新增 global-plan；旧自由文本 spec 需符合 delta 结构；Fixer 结果需新增 fix_note_ref。已有日志不自动伪造这些缺失事实；本次未实现旧运行自动升级，缺少新输入的运行应以完整输入建立新的受控 run。

## 当前默认 Auditor 收尾：修复后验证，失败待人工

本节采用 schema_version=2 的 finding 批次。旧 problem-* 仅作兼容，并同样受“所有模块本轮收尾”门禁约束。新宿主使用 audit-collect；角色及 Used Skills 由宿主实际启动/恢复，本控制器提供状态与门禁，不自带 Agent 调度服务。

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

## 功能切片输入与边界批准

高层 global-input 可省略 `module_slicing`，也可设置 `module_import_ref`、`functional_use_cases_complete`、`functional_directory_level`。字段与人工导入格式见 [切片规约](../../migration-global/references/slicing.md)。宿主/Global 读取并校验输入，形成 register 和模块 `_input`；Ledger 不自动扫描业务目录或执行语义切片。

global-plan 必须增加 `boundary_review: {"issues": []}`。无边界问题时 Global 自主提交；有跨模块或不确定业务边界时，先记录 question_id/kind/module_ids/question/proposed_resolution，再获取真实人工决定。宿主提交全局 `decision`（payload.module_id=null、decision=approved、human_source_ref），其 subject_sha256 使用 `contracts.digest({"plan": 完整global-plan内容, "registry": workflow.registry(当前状态)})`；Global 再以 `boundary_decision_id` 提交 global-plan。Ledger 校验问题、模块、精确摘要、批准作用域与未消费状态，成功后消费批准；修改方案或 registry 必须重新批准。

新 global-plan 请求缺少 boundary_review 会被拒绝。旧已接受日志不会自动补造边界审核；需要重新规划时补齐字段并实际审核。空 issues 代表已检查无问题，语义真实性由角色负责。运行中发现新边界问题，受影响模块先 suspend/CR；审计中走 human 路由与原有人工释放门禁，不靠覆盖全局规划绕过活动审计锁。

`case_owners`/`requirement_owners` 是覆盖/责任映射，允许多模块；不是多人验收。模块 `complete` 仅 MO 可提交，审计 `audit-verdict`/`audit` 仅对应 Auditor 可提交；Green 且原有证据、DoD、覆盖门禁满足后直接记录，不新增人工批准。审计期间 MO complete 表示修复模块的执行/DoD 完成，审计验收仍由 Auditor 独立提交。

## 父 MO 命名与 GO 报告投影

`status.parent_mo_names` 派生统一父名称 parent-mo-M<编号>；父 MO next_steps.agent_name 同步给宿主。父 session(role=module-orchestrator) 自动补全 agent_name，显式错名拒绝；不改变 role/instance/session 身份规则及冻结分配包。

Ledger 在事件接受/状态重建时生成 `<run_root>/reports/migration-report.json` 与 `.md`。`status.migration_report` 返回路径和 sequence。报告完整列出 case_ids 对应的 CASE、模块/PATH 明细及非 Green 原因和证据；尚无路径/结果同样列入 Yellow。GO 在迁移本轮收尾时读取并交付该报告，人工待决/缺测不得省略。它是可重建投影，不是新的状态或验收权威。字段、证据规则见 [GO 报告协议](migration-report.md)。

## Auditor 整体代码治理前置

新增全局 operation `audit-code-review`，actor=auditor，payload={report_ref, context_ref}。全部 MO 收尾后先提交 audit-code-review context receipt（draft_ref=report_ref），报告绑定 status.global_next_step.snapshot，覆盖所有执行叶子，并以必填 change_inventory_ref 引用 [本次代码修改清单](../../../template/audit-change-inventory.md)。Ledger 验证清单 hash，GO migration-report 提供同版链接；旧报告缺少清单须补交新版审查。`audit-collect` 有 CR-* 治理 finding 时先生成治理批次；无治理发现才收集剩余 Red/Yellow。代码变更后必须刷新整体审查；无问题报告 findings=[]。旧 run 无需重新初始化，但不能跳过新门禁。`audit-assign`/`audit-unavailable` 必须当前审查有效且无待处理治理发现。详见 [代码治理协议](audit-code-review.md)，模板 [audit-code-review.json](../../../template/audit-code-review.json)。

文件留存门禁：正式 Ledger CLI 必须使用 prepare 固化的 `.sdd-runs/<run_id>`，init 绑定 project_context_ref；历史任意根目录使用 `ledger.py history --root <旧根>` 只读重放。重新执行应 prepare 新 run，不修改旧引用 hash。详见 [留存文件系统](storage-layout.md)。
