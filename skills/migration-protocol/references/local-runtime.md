# 本地运行指南

本文件只记录本地控制器的命令、操作字段与游标；专题规则见各专题协议的总则。

## 能力边界与宿主责任

本地实现使用 Python 3.10+ 标准库，在 macOS/Linux 上用 `fcntl.flock` 串行提交；不支持 Windows 原生文件锁。单进程或多个 CLI 进程都通过同一个 run root 的锁写日志。模块工作可并行，只有事务提交串行。

脚本负责：合法阶段、结果/版本/路径校验、请求幂等、revision CAS、活动 assignment 资源冲突、证据快照、日志 hash 链、冷读投影、恢复预算和独立审计身份冲突检查。

宿主负责：认证调用者、限制其可用 role/module/operation、保护 `--host-context` 与证据目录、真正停止旧进程、限制实际源码写范围、审核测试 argv、启动/恢复 Agent、执行可选 OpenSpec CLI 验证及最终基线同步/归档。**任意本机进程都能修改所有文件时，CLI 不是安全隔离边界。** 不得给 worker 自选 host-context 的能力；本地 receipt 检查也不是对任意伪造文件的密码学认证。

没有宿主适配器时可运行这里的隔离测试与手工受控调用，但不能声称已具备无人值守迁移服务。

## 命令

以下路径中的 `<package>`、`<run>`、`<request>`、`<principal>` 均需换成绝对路径。

```text
python3 <package>/skills/migration-ledger/scripts/ledger.py init --root <run> --request <request.json> --host-context <principal.json>
python3 <package>/skills/migration-ledger/scripts/ledger.py apply --root <run> --request <request.json> --host-context <principal.json>
python3 <package>/skills/migration-ledger/scripts/ledger.py status --root <run> [--view cursor|step|module|full] [--module <id>] [--since <sequence>]
python3 <package>/skills/migration-ledger/scripts/ledger.py resume --root <run> --request <request.json> --host-context <principal.json>
python3 <package>/skills/migration-ledger/scripts/ledger.py recover --root <run> --request <request.json> --host-context <principal.json>
python3 <package>/skills/migration-ledger/scripts/ledger.py advance --root <run> --module <module-id> --host-context <mo-principal.json> [--worker <role>=<instance>]
python3 <package>/skills/migration-ledger/scripts/verify_openspec.py --root <run> --scope module --module-id <module-id>
```

`verify_openspec.py` 只读核验指定范围的记录/投影：global 用于公共基础，module 用于当前模块、祖先和实际依赖，projection（默认）检查全量视图，final 另要求正式收尾报告。planning 阶段 projection 可以通过；这不证明真实派发、命令执行或功能 Green。失败按 scope/module_id/recovery_action 恢复相关范围，无关 MO 继续，不把全量 projection 失败作为所有模块的共同门禁。详见 [留存布局](storage-layout.md#openspec-投影完整性收尾门禁)。

正式 CLI 只用 prepare 固化的 `.sdd-runs/<run_id>`（init 绑定 project_context_ref）；任意旧根目录用 `ledger.py history --root <旧根>` 只读重放，重新执行应 prepare 新 run。`init/resume/recover` 是对同名 operation 的入口校验，仍经过同一事务函数。成功返回 event_id/sequence/duplicate，拒绝返回 exit 1 和原因。业务状态以日志/投影为准，CLI exit 0 仅说明请求已接受。

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

hash 算法：`contracts.digest(value)` 为排序键、无多余空格、UTF-8 JSON 的 SHA256；`contracts.file_ref(path)` 返回真实绝对路径与文件字节 SHA256。命令行为 `contracts.py ref <文件>...`、`contracts.py baseline <代码文件>...`（输出 code_files 与 code_baseline）、`contracts.py digest <json 文件>`。不要用系统 `shasum` 计算 JSON 对象摘要冒充 canonical digest。

## 操作矩阵

这是完整支持集，未知 operation 拒绝。

| operation | 调用角色 | payload 必需内容 / 行为 |
| --- | --- | --- |
| init | host | prepare 返回、GO 补齐的 input.json 原样作为载荷：target_root、legacy_root、非空唯一 case_ids 与 requirement_ids、global_spec/new_architecture 文件引用；可选 global_paths；预算缺省 3/2/3/3 |
| register | Global | module_id、case_ids、write_paths、dependencies；按拓扑顺序登记，依赖必须已存在，从而拒绝环/未知模块。原子根功能可登记为 `lean_leaf=true`：须有 scope（in/out/requirement_ids）、context_refs 与 GO 的 leaf_review_ref，不可同时 decomposition_required |
| decompose | 父 MO / 父 module_id | plan_ref（子功能 scope/context_refs/CASE/写范围/依赖提案）、context_ref；不抄写全局上下文与分配包，Ledger 绑定当前版本，接受时仍须一致 |
| decompose-accept | Global / 父 module_id | review_ref；复核 MO 提案并原子登记子模块，父移入 module_groups |
| realloc-request | 子 MO / 子 module_id | reason、evidence_refs；切片/边界冲突向上提单，进入 waiting-upstream |
| redecompose | 父 MO / 父 module_id | plan_ref（重组方案）；重新拆分 children 覆盖父 scope |
| redecompose-accept | Global / 父 module_id | review_ref；复核重组方案，保留未变孩子 Green，重置受影响孩子，下线模块转入 superseded_modules 供 Auditor 治理 |
| module-summary | 父 MO / 父 module_id | summary_ref、subject_sha256；全部后代收尾后绑定当前版本汇总 |
| decision | host | decision_id、decision=approved、module_id、subject_sha256（取等待该决定的游标步骤的 approval_subject_sha256：冻结、恢复、审计放行、审计处置）、human_source_ref；保存真实人类决定引用。`kind=batch-envelope` 时 module_id 为父模块，envelope_ref 指向 [批量信封](../../../template/batch-envelope.json)，subject_sha256 等于其文件 hash，children 只能是该父的孩子 |
| global-plan | Global | plan_ref + review_ref；验收全部需求/用例归属，绑定当前 registry；新增模块后必须重审，通过前禁止实现派发 |
| audit-collect | Global | batch_id、独立 auditor_instance_id；所有模块本轮完成/明确挂起且没有可推进工作后，收集 finding/PATH、上下文和 round_snapshot |
| audit-plan | Auditor | plan_ref；每个 finding_id 一个路由，source_module_id、owner_module_ids、source_context/owner_contexts、analysis_ref、root_cause、action=fix/verify/human |
| audit-route-batch | Global | review_ref；审核 finding 责任映射及依赖图；human 分支挂起，独立分支继续 |
| audit-work | MO | 顶层 module_id 指负责模块；接受被冻结的修复任务，一轮 Fixer 授权；前置不可满足则报告待人工 |
| audit-retest | MO | 顶层 module_id 指发现模块或受影响中间模块；只等待本模块的上游修复/复测完成，执行完整模块路径 |
| audit-verdict | Auditor | review_ref；双方验证齐全、同基线、DoD 完成才裁决通过；过期证据报告待人工 |
| audit-defer | MO | root_cause + evidence_ref；记录根因、结果和恢复点，进入 waiting-auditor；可修复错误先本地一轮，确认的依赖/外围问题直接交接 |
| problem-assign | Global | assignment_id、独立 instance_id，可选 module_ids（默认全部队列）；只要求这些模块的依赖闭包与下游消费者（及其依赖）已收尾、空闲；assignment 记录 closure，审计锁只作用于 closure 内模块与全局操作，其他模块继续。预算按模块计（max_audit_rounds）；游标在闭包就绪且全局未收尾时给出 `problem-assign`（reason=audit-closure-settled） |
| audit-code-review | Auditor | report_ref、context_ref（预检随本操作登记）；全部 MO 收尾后、audit-collect 前提交，字段与治理闭环见[代码治理](audit-code-review.md#ledger-接口) |
| problem-audit | Auditor | report_ref；覆盖本次所有排队模块；有效代码独立 tests result，无法运行保留 Yellow；输出 retry/fix/change/wait/human 裁决 |
| audit-resume | MO | 接受本模块问题审计裁决；human 需 decision_id；wait 保持队列；retry 回 testing，fix 授权一轮，change/human 回规划 |
| plan | Spec-Designer | plan_ref、context_ref（planning 预检随本操作登记）；[stage-plan](../../../template/stage-plan.json)；test_design_ref、PATH、任务范围与 spec 由 Ledger 从已接受设计补全，checklist 由 Ledger 绑定包内清单；不抄写全局上下文与分配包，Ledger 绑定当前版本并在冻结、派发时复核 |
| freeze | MO | 初始/边界外变更 decision_id；边界内变更 change_class=within-envelope + impact_ref；批量信封 decision_id 另需 review_ref（MO 对详细 tasks/PATH 的审阅），子 plan 的 decision_envelope 必须与信封条目完全一致，信封可被多个孩子使用并记录 used_by |
| change | MO | request_ref + impact_ref；无 blocker 时进入 change-review，记录 from_freeze_id；within-envelope 的 impact JSON 必须绑定该旧 freeze 与新 to_plan_hash，见 change-impact 模板 |
| assign | MO | assignment_id、role=implementer/fixer/test-runner、instance_id；design 用 mode=design + design_input_ref，无执行 test_scope；可选 session_id/card_sha256；合法阶段且无活动 worker，返回 fencing_token。不等预检：worker 派发后 context-submit；该实例已有当前 ready 报告时直接绑定，当前 blocked 时拒绝派发。执行派发 `mechanical=true` 时宿主按步骤 payload 直接提交 |
| context-submit | 执行者 | report_ref；登记预检报告，同 stage/实例的最新报告生效。worker 有同阶段的活动派发时：ready 绑定并授权开工（Fixer 此时计一轮），blocked 退回派发 |
| submit | worker | assignment_id、fencing_token、result_ref；执行派发须已绑定 ready 预检；design 另需 test-design context_ref，kind=test-design；不推进阶段 |
| accept | MO | assignment_id；重验工件和版本后关闭；design 必需 review_ref，保持规划阶段与质量。`mechanical=true` 时宿主直接提交 |
| diagnose | Diagnostician（轻量叶子本地轮为 Fixer） | diagnosis_ref、owner、root_cause；仅保存绑定当前冻结、代码和未解决结果的 diagnosis_submission，不改变 phase；模块必须无活动 worker |
| diagnosis-accept | MO | 可选 `assign`（fixer 的 assign 参数）；重验诊断后进入 diagnosing，带 assign 时同一事务按 assign 守卫派发（已提交的 fixing 预检随之绑定），失败整体拒绝 |
| suspend | MO | kind=dependency/human/tooling、reason、root_cause、owner；保存原阶段，必须先停止活动 worker |
| dependency-ready | Global | 消费者 module_id 在请求顶层；检查生产者完成，记录当前版本的解除许可 |
| resume | MO | 依赖等待检查 Global 许可；其他等待需 decision_id，其 subject 是当前 blocked 对象摘要；恢复不变 Green |
| recover | MO | decision_id、additional_rounds；仅修复/停滞预算耗尽后增加预算，保留累计使用量，停滞计数随新周期清零 |
| session | MO | role、session_id；替换原会话须 reason=session-unavailable、checkpoint_ref，且旧 assignment 已关闭 |
| revoke | host | assignment_id、stopped_worker_ref；实际停止/隔离后才释放活动占用；旧 token 不再被接受 |
| invalidate | MO/host | reason；旧 worker 必须先 revoke；重新进入 specifying，并使消费者及全局审计失效 |
| checkpoint | host | receipt_ref（git_checkpoint.py 回执）；仅 git_checkpoint 开启且模块在 DoD 时，逐文件 blob 必须等于当前已接受代码，见 [模块 Git 检查点](engineering-disciplines.md#模块-git-检查点可选默认关闭) |
| complete | MO | dod_ref；开启 git_checkpoint 时须已有当前 code_baseline 的检查点；当前模块全路径 Green、版本有效、依赖完成才可接受 |
| audit-assign | Global | assignment_id、instance_id；全部模块完成后固定快照；审计实例不能是任意实现/修复/测试作者实例 |
| audit-route | Global | path_id、非空唯一 module_ids、reason_ref；给尚无负责模块的全局审计问题分配责任，不修改模块阶段 |
| repair-accept | MO | 非空唯一 path_ids；接受分配给本模块的审计问题，在依赖就绪且无 worker/blocker 时从 completed/testing 重开 testing；保留原失败供诊断分流 |
| audit-revoke | host | assignment_id、stopped_worker_ref；停止活动审计，保留已用次数，才能分配下一轮 |
| audit | Auditor | report_ref；按 tests 提交 assignment.path_ids 的复核结果；空清单按 audit-review 提交独立审阅；均带 snapshot |

`init` 的需求、CASE 与 global_paths 由 GO 写入 input；控制器不替模型拆分需求。global_paths 为可选项，缺失或 [] 都不阻止 Auditor。不同模块及全局 PATH ID 必须全局唯一。audit-assign 从遗留状态生成 path_ids，排除有效 Green；空清单只做独立审阅，详见 [审计范围协议](audit-scope.md#总则)。

本地角色身份校验不自动完成业务审核：source_closure 是否真实完整、测试语义是否正确、envelope 是否被违反、DoD 内容是否成立均需对应独立角色审查。脚本校验的是工件与守卫条件，不能替代人工/Agent 的实际审核过程。

## 阶段结果

所有结果必需 schema_version=1、kind、run_id、module_id、assignment_id、actor_instance_id、freeze_id、code_baseline。

`kind=test-design` 的 freeze_id/code_baseline 为 null，含 input_ref/design_ref/预期 paths。门禁与恢复见 [编码前设计](testing.md#编码前设计交接)。

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

decision 为全局操作，不增加模块 revision，因此记录批准后 recover 可验证同一模块修订号。普通 resume 的 subject 为整个 blocked 对象摘要（游标的 approval_subject_sha256）。恢复会话以 session 记录；冷恢复 checkpoint 包含 Ledger sequence、模块 revision、冻结引用、当前代码和 next_action，不依赖聊天摘要。

recover 只授权增加预算；已有 human、tooling 或 dependency 阻塞时，保留 blocked、当前等待阶段及 resume_phase，继续展示原阻塞和恢复动作。human/tooling 仍须绑定该 blocked 摘要的单独 resume 决定；dependency 仍须依赖就绪和 GO 的 dependency-ready。预算批准不能同时充当解除阻塞的批准。无阻塞时保持原恢复行为：有 diagnosis 回到 diagnosing，否则回到 testing；不改变其他模块状态或测试颜色。

本地使用 fix_rounds_used（累计）+ recovery_cycle + 可增加的 fix_budget；no_progress 根据未解决 PATH 的 ID、三态、根因 category/summary/owner 的稳定摘要计数；相同问题才累加，根因改变会重新观察。此处比较结构化声明，语义真实性仍由诊断者和 MO 审核。审计达到 max_audit_rounds 后停止，须显式建立后续受控运行；本地 recover 不重置全局审计预算。协议里的独立 yellow retry/超时升级由宿主策略执行，本地重复验证另受 no-progress 守卫限制。

本地锁不使用自动租约超时重授：活动 assignment 一直占用模块资源，直到 accept 或带真实停止证据的 revoke。此方式避免仅因时钟到期就允许两个 worker 写同一路径。宿主仍必须在每次真实写操作执行 ACL/fencing。

## 编排游标

游标由 Ledger 派生，沿用 NEXT/next_skill、blocked_from、阶段 require_state 和轮次保留机制：

- `status.next_steps`：每模块 operation、role、worker_role（如适用）、session_id、assignment_id、expected_revision、ready、reason；执行其中一步所需的状态用 `--view step` 取。每个有 operation 的步骤带阅读卡摘要 `card_sha256` 与本步模板 `templates`，`global_next_step` 同样提供；取卡、增量交付、会话轮换与采纳统计见[宿主接入](host-integration.md#提示采纳回报)。本地修复无 fixer 会话时，session_id 指向原 Implementer 会话（`session_affinity=implementer`）；审计期修复不做此提示。未解决结果含已确认 `runtime-spec-variant-conflict` 时，游标为 `suspend(kind=human)`，不进入诊断或修复。
- `status.ready_modules`：当前有可推进步骤的模块；并非可以同时启动的预约。多个候选可能争用同一资源，真正 assign 仍在事务内再次校验。
- `status.global_next_step`：等待模块完成、创建审计、等待活动审计、撤销失效审计或等待交付授权。游标不自动派发，也不赋予额外权限。
- 已提交 worker 结果对应 `accept`；未提交对应 `await-result`。原会话通过 session_id 提示复用；短交接只传 Ledger/assignment/artifact 引用。
- 禁止重复 suspend 覆盖原恢复点；completed 不能经 suspend 偷偷重新打开。需要重开时使用 invalidate/CR 的正式路径。
- submit 与 accept 均核验角色对应的当前 phase、blocked 和生产者实际基线，防止依赖失效后旧 worker 推进消费者。
- revoke 只作用于仍活动的任务，已关闭旧任务不能把新任务阶段倒退；依赖挂起时撤销 worker 保留原 blocker。
- 活动审计不能被另一轮覆盖；audit 成功接收后关闭 assignment；中断必须 host audit-revoke 提交实际停止证据。assignment_id 不复用，撤销不返还已用轮次。

## 功能切片输入与边界批准

高层 global-input 可省略 `module_slicing`，也可设置 `module_import_ref`、`functional_use_cases_complete`、`functional_directory_level`。字段与人工导入格式见 [切片规约](../../migration-global/references/slicing.md)。宿主/Global 读取并校验输入，形成 register 和模块 `_input`；Ledger 不自动扫描业务目录或执行语义切片。

global-plan 必须增加 `boundary_review: {"issues": []}`。无边界问题时 Global 自主提交；有跨模块或不确定业务边界时，先记录 question_id/kind/module_ids/question/proposed_resolution，再获取真实人工决定。宿主提交全局 `decision`（payload.module_id=null、decision=approved、human_source_ref），其 subject_sha256 使用 `contracts.digest({"plan": 完整global-plan内容, "registry": workflow.registry(当前状态)})`；Global 再以 `boundary_decision_id` 提交 global-plan。Ledger 校验问题、模块、精确摘要、批准作用域与未消费状态，成功后消费批准；修改方案或 registry 必须重新批准。

新 global-plan 请求缺少 boundary_review 会被拒绝。旧已接受日志不会自动补造边界审核；需要重新规划时补齐字段并实际审核。空 issues 代表已检查无问题，语义真实性由角色负责。运行中发现新边界问题，受影响模块先 suspend/CR；审计中走 human 路由与原有人工释放门禁，不靠覆盖全局规划绕过活动审计锁。

`case_owners`/`requirement_owners` 是覆盖/责任映射，允许多模块；不是多人验收。模块 `complete` 仅 MO 可提交，审计 `audit-verdict`/`audit` 仅对应 Auditor 可提交；Green 且原有证据、DoD、覆盖门禁满足后直接记录，不新增人工批准。审计期间 MO complete 表示修复模块的执行/DoD 完成，审计验收仍由 Auditor 独立提交。
