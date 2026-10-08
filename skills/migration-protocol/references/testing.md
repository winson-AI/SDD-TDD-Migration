# 测试路径、Main 与复测契约

## 执行模式

execute 模式分 build（含 unit、static）和 automation，按 [双环节协议](build-automation.md) 执行。代码已生成并经 MO 接受后，把已批准路径落实为技术栈真实脚本/选择器/数据参数。若发现新验收语义，发 CR，不自行补成新标准。设计与执行可由不同实例担任，仍属于同一角色。Auditor 不能是该轮脚本作者。

Main 是项目提供的主验证入口，不是固定 `main.py`。输入 `test_adapter` 指定 executable/args/cwd、query 传输和结构化结果路径；未配置或不可用 → Yellow tooling。模板不包含假测试或自动通过的适配器。

## 编码前设计交接

GO/父 MO 在冻结前将上游全量 CASE 分配到独立 scope，子 MO 拆 TASK；Spec-Designer 一次形成可执行 SPEC 和测试路径，MO 审核后冻结、派发 Implementer。prepare 的 test_design_required=true 表示必需的测试输入与覆盖，不强制额外 Test-Runner design 轮次。TDD 的预期来自上游用例与源行为，automation 收集实际错误后推动实现修复；首次即 Green 不伪造 Red。

默认 stage-plan.test_design_ref 引用 [upstream-test-plan.json](../../../template/upstream-test-plan.json)：subject_sha256、case_refs 分别取游标 input_subject_sha256、upstream_case_refs，绑定当前分配及权威用例（项目 test_cases_path，未单独提供时取 global_spec）。paths 精确覆盖本模块全部 CASE，每条含需求、预期 ASSERT 与适用 Scenario；不得填 actual/passed/quality 或执行结果。design_ref 和 test_assets 沿用下述资产契约。Ledger 补全 PATH/test-design/资产定义；TASK.scope、需求和 SPEC 定义由 plan 明确提供。MO 检查原始用例与预期的语义一致性，hash 不证明语义；无未决且完整可执行即冻结，无需等待实现后才能发现的问题。

只有确需独立设计协助时，MO 显式 assign(role=test-runner, mode=design, design_input_ref)，输入仍为本叶子 SPEC 草稿、tasks.scope/需求、case_refs 和游标 subject。设计者不得兼 MO/Spec/代码作者；submit 同带 test-design 预检 context_ref，kind=test-design，freeze_id/code_baseline=null。MO accept 后 plan 必须绑定接受的设计、任务与断言；过期/撤销的显式设计仍需重交，不能冒充已接受。设计只读规格与用例，不运行目标代码。

执行反馈分流、同 Run CR 及独立 TASK 保留统一按[变更控制](openspec.md#变更控制)；不强制重做独立 design，当前计划仍绑定上游用例，历史设计只供追溯。

新 prepare 固化 planning_coverage_required。每条 PATH.preparation 记 status=existing/prepared/deferred、reason、evidence_refs、asset_ids；已有执行器可复用，prepared 须对应资产，deferred 另记 owner/next_action，解决后才能冻结。测试准备不执行目标代码，不编造 Red。

test_assets 交 script/fixture/adapter 的 asset_id/ref/path_ids，script 再映射 assertions；文件位于 design_ref 同级 staging 内，冻结 definitions 绑定 hash。模块、修复后复测及 GLOBAL 复测共用 PATH 资产解析，query/receipt 的 test_asset_binding 保留来源模块、freeze_id、test_design_ref。GLOBAL 自有路径显式绑定本 GLOBAL 的 test_design_ref/设计作者，不借用模块资产；作者不能兼 Auditor/审计 Test-Runner。

所有执行器可从 SDD_TEST_QUERY_FILE 读 query（非 build/unit 同时带 --query-file）；资产位于 frozen_test_assets。script/adapter 直接作为 argv 参数由 Host 记录 entrypoint_ids；其他消费由执行器向 SDD_TEST_ASSET_USAGE_FILE 写 [{asset_id,ref}]，回执保存 reported_ids 和文件引用。新冻结有资产时，Green 须覆盖所有所选资产，哈希/来源不能变；提供资产不等于消费，执行器上报也不自动证明断言语义。缺证据允许记录真实失败/阻塞。

显式 design 设计者与 MO/Spec/实现/修复/Auditor 独立；直接测试计划及脚本作者同样不能兼 Auditor。Host 落实派发及 staging 隔离。结构/hash 不证明语义；设计不替代 building/testing 预检及冻结/代码门禁。

## query

一个可重复执行的路径带稳定 `path_id`、可读 `name`、case_id、requirement_id、preconditions、steps、parameters、expected_assertions、dependency_refs、priority、scope。推荐 `PATH-M001-001`，名称变化不改 ID；参数化每个实例具有唯一 ID/parameter_hash，不能把十个参数只算一次覆盖。

query 文件必须包含该路径完整的前置、步骤、参数和预期断言；模板的 query 是索引头，执行时从同一条 path 记录组装完整内容并记录 hash，不能仅传 Name 猜测行为。

automation/visual PATH 若声明 interaction_id，execute_test 从所属模块冻结模型提取完整 frozen_interaction（id/action/from/expected），不能由运行器另写较弱的期望。source-only UI 允许把手势放入 automation，不要求没有的视觉基线；runtime UI 仍保留已有 visual 义务。automation 的条件结果扩展见 [interaction-evidence.json](../../../template/interaction-evidence.json)：绑定当前代码、已接受 HAP、真实动作/起点/观测及证据。GLOBAL 自有手势 PATH 显式冻结 frozen_interaction，并用既有 build_binding 指定产物所属 build PATH。

GLOBAL 手势的完整契约、ID 匹配与 build_binding 在 init 落盘前检查，输入不完整时先修正初始化请求，避免到审计才发现无法执行。

将 [test-paths.json](../../../template/test-paths.json) 的单路径 JSON 写入临时 query 文件，按已确认适配器契约用 argv 传入：`<executable> <args...> --query-file <absolute-query.json> --result-file <absolute-result.json>`。这里只定义默认适配协议；实际框架需提供翻译脚本，不能把自然语言 name 直接当 shell 命令。无 shell 拼接，不执行 query 内嵌指令。保存实际 argv、cwd、工具版本、环境变量名称（秘密值脱敏）、seed、fixtures、依赖版本。

## 断言与结果

结果见 [test-result.json](../../../template/test-result.json)，按 path 独立记录 test_run_id、attempt、代码/规格/测试/环境摘要、命令、开始/结束时间、exit_code、assertions（assertion_id/expected/actual/passed/evidence_ref）、root_cause、retest_of、quality。

- Green：当前基线真实执行；退出码与结构化报告一致；所有预期 assertion 出现且通过；日志完整；无 skip/xfail；未把被测核心逻辑 mock 掉。零断言、只断言 true、缺结果或缺路径不能为 Green。
- Red：真实断言失败且指向目标行为缺陷；明确实现导致的构建/静态检查失败也以专用 gate path 记录 Red。保留失败日志与实际值。
- Yellow：依赖未就绪、缺凭证/设备、超时、适配器坏、解析异常、未知失败、skip、证据缺失、版本过期或 flaky。超时若可证实为规格性能要求违反，可诊断为 Red；不能只凭非零退出码判产品 Bug。

root_cause 字段在 Red/Yellow 必填：category、summary、confidence、evidence_refs、suspected_owner、next_action；确认失败断言不等于已确认根因，后者由 Diagnostician 补充。保留原始报告，分类纠正以新事件引用原结果，不篡改历史。

同基线同路径出现 pass/fail 混合则 flaky Yellow，不能“重跑到绿”挑最好一次；定位/修复后按冻结策略连续通过（默认 3 次），Auditor 独立验证。历史失败原样保留。涉及环境变化也记录新 environment_hash。

## 修复、复测与覆盖

Fixer 自回归记录 `producer=fixer`，是补丁证据，不能替代 Test-Runner 正式验证或 Auditor 的独立裁决。`retest_of` 必须指向旧 test_run_id/path_id，绑定新代码版本。依赖解除或人工确认都只改变可执行条件，不生成 pass。

每次代码/测试/依赖变化，所有受影响结果 stale；若没有可靠影响映射，重跑模块全路径。Auditor 最终所有结果绑定同一冻结代码树；修复导致旧 Green 受影响也须重跑。不能通过缩减覆盖分母消灭非 Green。

集成用例以 GLOBAL 覆盖范围固定 PATH-GLOBAL-*，审计验收 owner 为 Auditor，记录参与模块；不能由单模块单测替代。Mock 仅限冻结 design 允许的外部边界；跨模块真实集成依赖未验证不得全局 Green。

## 本地执行与严格结果验收

[execute_test.py](../../migration-ledger/scripts/execute_test.py) 在代码已接受、assignment 有效的情况下调用真实项目适配器，用 argv 传递完整 query，保留 stdout/stderr、退出码、开始/结束时间、query/report/log hash 与 receipt。CLI 不提供假的业务测试适配器。

阶段结果采用 [stage-result 模板](../../../template/stage-result.json)，在 submit 和 MO accept 两处重复校验。Green 要求 frozen PATH 与 assertion ID 集合完全匹配、原始结果与声明一致、真实 receipt 完整且当前基线匹配；本地 assertion 比较只支持 JSON equality。复杂匹配应由适配器输出一个可核验的规范化观测值（如计算后的状态或误差），并在 SPEC 固定该观测语义，不能临时改变期望。

执行回执来源可信依赖宿主保护其上下文和证据目录。本地检查不能独立证明一份任意可写 JSON 来自可信执行；宿主不得让业务 worker 伪造 host-context 或执行回执。全局 Auditor 同样需实际执行回执，不能只提交文字“已复测”。

新拆分运行每次结果覆盖 assignment.test_scope 对应的全部冻结路径，Ledger 合并构建和自动化两部分；DoD 仍检查完整集合，未执行项明确 Yellow。超时/缺报告可提交 executed=false 的 Yellow 并附诊断证据；不能将残缺报告提升为 Green。旧非 Green 与 stale 路径需新的 test_run_id 和 retest_of。

adapter 的 `skipped` / `xfail` 限制必须原样保留。原始报告声称 Green 但任一限制为真时，test_completion 将其规范化为 Yellow（`incomplete-test-execution`），保留真实断言和原报告/执行日志；已观察到的 Red 不降级。正式验收同样拒绝带限制的 Green，不能通过省略规范化版本或只看进程退出码绕过。

`global_paths` 是显式全局测试路径，可以为空或只覆盖已登记 CASE 的子集；它不代表全部模块用例。GO 的 global-plan 仍必须为所有 requirement/case 完整声明 owner，Auditor 沿既有非 Green 与变更影响范围选择复核路径。

模块修复按[有限循环](state-machine.md#有限循环)执行；在预算内局部收敛，阻塞/超限留证待统一宿主审计。独立 Test-Runner 提交正式复测证据，Auditor 审阅并裁决；MO 执行模块恢复/修复门禁，最终审计不能跳过。

## 逻辑单测

unit 冻结 argv/cwd/timeout/selection_ref。unit_report 固定 format=junit、runner 相对 patterns、required_test_ids（唯一 `classname#name`，参数实例也需稳定 ID），只有一个 expected=true 的完整执行断言。Gradle 默认 `outputs/**/test-results/**/TEST-*.xml`；宿主迁移输出到本轮 runner，追加 --rerun-tasks/--no-build-cache（含 KMP/native）并开启 JVM Test XML。其他工具在 `$SDD_RUNNER_DIR` 生成同格式报告。

解析 testcase/计数，保存具体 ID、执行/失败/跳过数量与报告 hash，绑定 run/module/PATH/assignment/test_run/freeze/code_baseline，接受时重核原报告。exit=0、实际执行非零、全部必需 ID 通过、无跳过/证据缺口才 Green。零执行、漏测、缺失/损坏/过期报告为 Yellow；断言失败或非环境中断的命令失败为 code Red，走既有诊断/Fixer。只收本 attempt 的新报告，旧 mtime/越界链接无效；任意可写 XML 的真实性仍依赖可信宿主执行。

prepared run 固定 unit_tests_required=true。每个 applicable Logic 项的 dimension_trace 须关联 unit PATH 或 unit_test_na 依据。unit 无需设备，可证明逻辑 Scenario，但不替代 CASE 的 automation；环境缺失保留已通过 unit，Red/Yellow 仅影响本模块及实际依赖。

## 日志与按需追溯

execute_test 在同一 runner 持续写 stdout.log/stderr.log（原始字节）、execution.log（带采集时间/stream）、output-events.jsonl（序号/字节位置），execution-state.json 绑定本 attempt 身份、输出量及完整性。子进程自身缓冲可能延迟输出；采集顺序不表示跨 stream 的严格因果。超时/取消标记不完整；硬终止可能仅留下 running/不完整，须宿主核查，不自动修复或重跑。receipt.capture 固化引用，提交时沿 Ledger 归档；原有三态/终止验收不变。

恢复/诊断先读当前模块状态和 trace 摘要，完整日志、历史轮次、媒体按需读取，不自动装入下次上下文。以下 trace.py 位于 skills/migration-ledger/scripts；命令只读、不刷新投影或拿业务锁：

```sh
python3 <package>/skills/migration-ledger/scripts/trace.py query --root <run> --module M001 --scenario-id SCN-M001-query
python3 <package>/skills/migration-ledger/scripts/trace.py query --root <run> --module M001 --path-id U1 --history --offset 0 --limit 5
python3 <package>/skills/migration-ledger/scripts/trace.py evidence --root <run> --sha256 <已提交引用hash> --offset 0 --bytes 1024
python3 <package>/skills/migration-ledger/scripts/trace.py live --root <run> --module M001 --attempt <本run/runner> --stream stderr --offset 0 --bytes 1024
```

query 还支持 --task-id/--assertion-id/--test-id，默认最多5条，仅失败附1024字节日志尾；列表/长字段截断，按 next_offset 翻页。读取事件索引对应的归档，当前源码改变不破坏旧证据；缺损显示 evidence_issues，历史 Green 不表示当前有效。evidence 仅读取已提交文本证据，每次最多4096字节，媒体保留引用。live 仅供 Host 观察，accepted=false，不能作为跨 Agent 验收输入。<run> 为 .sdd-runs/<run_id>；输出到 stdout，不产生新状态库。

## 静态规格闭合

顺序为 build → unit → static → automation → visual。prepared run 固定 spec_closure_required=true，每模块恰好一个 static PATH：断言为唯一 expected=true，复用已有 case_id，不替代业务覆盖；审查范围由 Ledger 派生（全部任务需求与冻结场景），PATH 不列。

独立 Test-Runner 只读 SPEC、当前代码/测试，将审查写入 staging：

- scenarios[]：按 scenario_id + requirement_id 逐场景记录；execute_test 注入 Ledger 派生的 scenario_index 与场景清单。每行 status=passed|failed、summary、production_symbols（目标绝对路径+真实符号）、evidence_refs。passed 必须给 reached_from：另一个目标文件中的调用/DI/导航/清单引用；有 unit PATH 还须 test_refs 指向真实测试符号。未接入生产不能 passed。
- anti_patterns：preview-only-wiring、dead-handler、fixed-result、placeholder-icon、unapproved-stub、swallowed-error（错误显示为空态/成功）逐项 absent|present、note、evidence_refs。批准的 capture-fixture 边界可 absent，须引用批准依据。

building 预检的 execution.commands 一并批准 build/unit/static 命令和 review 路径；同一 build assignment 依次执行 build、unit、static，到第一个非 Green 为止，一次提交和验收；结果须覆盖已到达环节的全部待测 PATH，同一代码上已 Green 的环节重试时不重跑。非 Green 即诊断/Fixer 后重跑。`execute_test.py` 调用 [spec_closure.py](../../migration-ledger/scripts/spec_closure.py)（--review、--target-root），核对上下文、场景覆盖、符号和清单；failed 场景/present 反模式为 Red。脚本不判断业务语义，Test-Runner 审阅、Auditor 抽查。static 全绿前禁止 automation/automation-unavailable；缺设备仍执行 unit/static。

## 运行时变体与冻结 SPEC 冲突

截图、运行时树或设备观察显示的页面变体（如 live 页签）与冻结 SPEC/源码默认（如 trending）不一致时，这是用户的范围决定，不是代码缺陷：Test-Runner 记 Yellow，root_cause 为 `category=human`、`reason_code=runtime-spec-variant-conflict`、`confidence=confirmed`，引用冲突证据。外部验证/对齐结果中的同类 issue 由适配器自动规范化为同一根因。MO 游标直接给出 `suspend(kind=human)`，交 Escalation 取得用户选择后再按决定重新规划或继续；不派 Fixer，也不默认任选一种变体。

## Harmony Main

已内置 [Harmony 适配协议](../../migration-test/references/harmony-runtime.md) 与执行内核。输入为完整冻结 PATH；输出按 ASSERT ID 绑定原生 Verify 的截图/视频结果，保留原时间线、工具录制、压缩记忆、布局、视频时间映射。UI 谓词 expected=true 的语义须在 design 冻结，不能从旧 scalar equality 静默转换。

执行期间每次观察落盘；回放仍重新验证；同断言 pass/fail 混合为 flaky Yellow。缺设备/模型/媒体或不明确结论为 Yellow，不用最终自然语言判断通过。harmony_stage 将 host receipts 汇成现有 tests stage，Ledger 双重校验媒体 hash 与捕获三态。host 超时终止整个进程组并保存已有 stdout/stderr，避免子工具继续操作设备。

默认 Harmony 当前不会自动生成上述结构化 interaction_evidence。对有 frozen_interaction 的 automation，报告仅有 Green 断言而缺这份证据时，test_completion 保留实际断言、媒体和原报告，记录 executed=true 的 Yellow tooling / interaction-evidence-unavailable；正式 submit/accept 使用同一解释，不会先报 Green 再无法收尾。已观察到的 Red 保持 Red；绝不从 expected 或自然语言结论合成 observed。Test-Runner 在预检中说明能力缺口，使用具备此能力的已配置 adapter，或沿原环境不可用/缺测路径交给 MO/Auditor 收尾；无手势路径不增加此要求。

## 分阶段唯一验收 owner

- 模块阶段：对应 Module-Orchestrator 唯一验收本模块 CASE/PATH。Test-Runner 提交真实结果，MO 核验完整 Green、当前基线、证据与 DoD 后直接提交验收记录。
- 全局审计阶段：本次独立 Auditor 唯一验收审计范围 CASE/PATH；正式复测完整 Green 且覆盖、基线门禁满足后直接提交 audit-verdict/audit。MO 仍接收 worker 结果并守护修复模块 DoD，但不能批准或替代审计结论。
- 无需为 Green 验收额外请求人类或 Global 会签；SPEC 冻结、业务边界、语义变更及最终交付授权保留原有门禁。
- `case_owners` 表示覆盖范围，`owner_module_ids` 表示修复责任；均不表示验收人。验收事件的宿主身份、模块/审计 assignment、CASE/PATH、基线和证据共同确定唯一验收范围。不同阶段分别保留历史，不覆盖此前失败或把模块 Green 当审计通过。

## 二方库验证与根因

基于冻结需求和 reuse-plan 中的行为差异设计真实提供方接线/版本/配置、边界/异常及适配路径；完整模块和全局用例仍须覆盖。mock/编译通过不替代必要集成测试。结果缺真实证据为 Yellow，实际断言错误为 Red；根因带 source/capability/mapping/version 和影响消费者。所选提供方变化使旧证据失效，Auditor 按 finding 依赖图重测，详见 [复用协议](reuse-dependencies.md)。

对 reuse/adapt/reference，design 从已审核的存量行为基线与需求建立 fidelity.scenarios 的复现断言；execute 用同场景前置/输入/状态验证真实目标链路，记录实际输出及副作用。每个 scenario 关联冻结 PATH/ASSERT 与 Main 回执，不能用库的当前返回值重写 expected。未确定基线先澄清，未执行不能 Green；对齐报告不是测试通过证据。MO/Auditor 验收沿用同一条完整证据链。

## 测试启动前的上下文门禁

Test Runner 接到 build 派发后提交 building、接到 automation 派发后提交 testing 报告，ready 报告绑定派发后才执行；Auditor 最终验证在 audit-assign 前提交 audit-testing 报告。报告包括已接受代码、冻结 PATH/assert、提供方、工具/环境/数据与 execution.argv/cwd/environment_ref。execute_test 只接受已绑定 ready 报告的派发，并再核对命令和环境引用；不匹配须重新预检和派发，不能换命令绕过。缺条件不生成假测试结果。见 [上下文就绪协议](context-readiness.md)。

仅自动化环境缺失采用 automation-unavailable/automation-deferred 专门分流；不耗修复轮次、不阻塞可执行的下游或并行工作，也不冒充 Green。Auditor 可记录完整缺测清单后完成本轮；其余真实 Red/Yellow 保持原诊断修复流程。

## 埋点上报断言

遵守 [埋点协议](telemetry.md)：测试预期从已审核的源行为冻结，事件存在才生成/关联业务 PATH/ASSERT；无埋点不增加测试或 skip。明确 emitted/sdk-dispatched/server-received 验收层级，验证正确事件/参数/次数及适用的禁止触发/边界情况，项目 adapter 留原始观测/回执。部分路径缺证据单独 Yellow，其余可执行路径继续；不得用图片、空实现或被 mock 的核心逻辑充当上报验收。
