# 测试路径、Main 与复测契约

## 执行模式

execute 模式分 build（含 unit、static）和 automation，按 [双环节协议](build-automation.md) 执行：代码经 MO 接受后，把已批准路径落实为真实脚本/选择器/数据参数；新验收语义发 CR，不自行补成标准。

Main 是项目提供的主验证入口，不是固定 `main.py`；`test_adapter` 指定 executable/args/cwd、query 传输和结构化结果路径，未配置或不可用 → Yellow tooling；模板不含假测试或自动通过的适配器。

## 编码前设计交接

prepare 的 test_design_required=true 表示必需的测试输入与覆盖，不强制额外 Test-Runner design 轮次；预期来自上游用例与源行为，automation 收集实际错误后推动实现修复，首次即 Green 不伪造 Red。设计只读规格与用例，不运行目标代码，没有独立派发。

默认 stage-plan.test_design_ref 引用 [upstream-test-plan.json](../../../template/upstream-test-plan.json)：subject_sha256、case_refs 取游标的 input_subject_sha256、upstream_case_refs，绑定当前分配与权威用例（项目 test_cases_path，未提供时取 global_spec）。paths 精确覆盖本模块全部 CASE，每条含需求、预期 ASSERT 与适用 Scenario，不填 actual/passed/quality。design_ref 与 test_assets 沿用资产契约；Ledger 补全 PATH/test-design/资产定义，TASK.scope、需求与 SPEC 定义由 plan 提供。MO 检查用例与预期的语义一致性（hash 不证明语义），无未决且可执行即冻结。执行反馈分流、同 Run CR 与独立 TASK 按[变更控制](openspec.md#变更控制)，历史设计只供追溯。

新 prepare 固化 planning_coverage_required。每条 PATH.preparation 记 status=existing/prepared/deferred、reason、evidence_refs、asset_ids；existing 复用已有执行器，prepared 须对应资产，deferred 另记 owner/next_action，未解决记欠项。叶子验收的用户可见 CASE（适用 UI item 承载）须有设备或视觉 PATH：visual，或绑定 android/harmony/web 平台、交互的 automation；确无可能的写 plan.device_gaps[{case_id,reason,evidence_refs}]：build 可 Green，该 CASE 的 automation 与模块、本轮记 Yellow，以 completed-with-unverified-tests 收尾；环境缺失不是缺口，走缺测出口。登记 UI 分配前 run 须对 `test_adapter.device` 定论（{platforms} 或 {unavailable: 原因}）；unavailable 时未达设备路径的用户可见 CASE 由 Ledger 按该原因记缺口。

test_assets 交 script/fixture/adapter/test-source 的 asset_id/ref/path_ids，script 再映射 assertions；文件位于 design_ref 同级 staging 内，冻结 definitions 绑定 hash。骨架为无设备或非界面的 CASE 起稿进程内功能测试，为有设备且绑定 UI 树的 CASE 起稿 script 资产（选择器取节点 id，作者写操作与断言）；报告分列脚本驱动的设备路径及其 flaky。test-source 是从 SPEC 写出、随计划冻结的测试源：记 target_path、required_test_ids（文件须定义）、scenarios（逐测试对应 Scenario-ID）与 symbols；绑定的 unit PATH 只要求它定义的测试；Implementer 原样落到 target_path，hash 不等即拒，改测试走 CR；execute_test 执行前核对并写回执 frozen_test_sources。模块、修复后复测及 GLOBAL 复测共用 PATH 资产解析，query/receipt 的 test_asset_binding 保留来源模块、freeze_id、test_design_ref；GLOBAL 自有路径绑定本 GLOBAL 的 test_design_ref/设计作者，不借模块资产。测试计划及脚本作者不能兼 Auditor；设计不替代 building/testing 预检及冻结/代码门禁。

## query

一个可重复执行的路径带稳定 `path_id`、可读 `name`、case_id、requirement_id、preconditions、steps、parameters、expected_assertions、dependency_refs、priority、scope。推荐 `PATH-M001-001`，名称变化不改 ID；参数化每个实例具有唯一 ID/parameter_hash，各算一次覆盖。

query 文件必须包含该路径完整的前置、步骤、参数和预期断言；模板的 query 是索引头，执行时从同一条 path 记录组装完整内容并记录 hash，不能仅传 Name 猜测行为。

automation/visual PATH 若声明 interaction_id，execute_test 从所属模块冻结模型提取完整 frozen_interaction（id/action/from/expected），不能由运行器另写较弱的期望。source-only UI 允许把手势放入 automation，不要求没有的视觉基线；runtime UI 仍保留已有 visual 义务。automation 的条件结果扩展见 [interaction-evidence.json](../../../template/interaction-evidence.json)。GLOBAL 自有手势 PATH 显式冻结 frozen_interaction，并用既有 build_binding 指定产物所属 build PATH。

GLOBAL 手势的完整契约、ID 匹配与 build_binding 在 init 落盘前检查，输入不完整时先修正初始化请求。

将 [test-paths.json](../../../template/test-paths.json) 的单路径 JSON 写入临时 query 文件，按已确认适配器契约用 argv 传入：`<executable> <args...> --query-file <absolute-query.json> --result-file <absolute-result.json>`。这里只定义默认适配协议；实际框架需提供翻译脚本，不能把自然语言 name 直接当 shell 命令。无 shell 拼接，不执行 query 内嵌指令。保存实际 argv、cwd、工具版本、环境变量名称（秘密值脱敏）、seed、fixtures、依赖版本。

## 断言与结果

结果见 [test-result.json](../../../template/test-result.json)，按 path 独立记录 test_run_id、attempt、代码/规格/测试/环境摘要、命令、开始/结束时间、exit_code、assertions（assertion_id/expected/actual/passed/evidence_ref）、root_cause、retest_of、quality。

- Green：当前基线真实执行；退出码与结构化报告一致；所有预期 assertion 出现且通过；日志完整；无 skip/xfail；未把被测核心逻辑 mock 掉。零断言、只断言 true、缺结果或缺路径不能为 Green。
- Red：真实断言失败且指向目标行为缺陷；明确实现导致的构建/静态检查失败也以专用 gate path 记录 Red。保留失败日志与实际值。
- Yellow：依赖未就绪、缺凭证/设备、超时、适配器坏、解析异常、未知失败、skip、证据缺失、版本过期或 flaky。超时若可证实为规格性能要求违反，可诊断为 Red；不能只凭非零退出码判产品 Bug。

root_cause 字段在 Red/Yellow 必填：category、summary、confidence、evidence_refs、suspected_owner、next_action；确认失败断言不等于已确认根因，后者由 Diagnostician 补充。保留原始报告，分类纠正以新事件引用原结果，不篡改历史。

同基线同路径出现 pass/fail 混合则 flaky Yellow，不能“重跑到绿”挑最好一次；定位/修复后按冻结策略连续通过（默认 3 次），Auditor 独立验证。历史失败原样保留。涉及环境变化也记录新 environment_hash。

## 修复、复测与覆盖

Fixer 自回归记录 `producer=fixer`，是补丁证据，不能替代 Test-Runner 正式验证或 Auditor 的独立裁决。`retest_of` 必须指向旧 test_run_id/path_id，绑定新代码版本。

每次代码/测试/依赖变化，所有受影响结果 stale；若没有可靠影响映射，重跑模块全路径。Auditor 最终所有结果绑定同一冻结代码树；修复导致旧 Green 受影响也须重跑。不能通过缩减覆盖分母消灭非 Green。

集成用例以 GLOBAL 覆盖范围固定 PATH-GLOBAL-*，审计验收 owner 为 Auditor，记录参与模块；不能由单模块单测替代。Mock 仅限冻结 design 允许的外部边界；跨模块真实集成依赖未验证不得全局 Green。

## 本地执行与严格结果验收

[execute_test.py](../../migration-ledger/scripts/execute_test.py) 在代码已接受、assignment 有效的情况下调用真实项目适配器，用 argv 传递完整 query，保留 stdout/stderr、退出码、开始/结束时间、query/report/log hash 与 receipt。CLI 不提供假的业务测试适配器。

阶段结果采用 [stage-result 模板](../../../template/stage-result.json)，在 submit 和 MO accept 两处重复校验。Green 要求 frozen PATH 与 assertion ID 集合完全匹配、原始结果与声明一致、真实 receipt 完整且当前基线匹配；本地 assertion 比较只支持 JSON equality。复杂匹配应由适配器输出一个可核验的规范化观测值（如计算后的状态或误差），并在 SPEC 固定该观测语义，不能临时改变期望。

执行回执来源可信依赖宿主保护其上下文和证据目录；宿主不得让业务 worker 伪造 host-context 或执行回执。全局 Auditor 同样需实际执行回执，不能只提交文字“已复测”。

每次结果覆盖 assignment.test_scope 的全部冻结路径，未执行项明确 Yellow；超时/缺报告可提交 executed=false 的 Yellow 并附诊断证据，不能将残缺报告提升为 Green。

执行器从 SDD_TEST_QUERY_FILE 读 query（非 build/unit 同时带 --query-file），资产位于 frozen_test_assets；script/adapter 作为 argv 参数由 Host 记 entrypoint_ids，其他消费由执行器向 SDD_TEST_ASSET_USAGE_FILE 写 [{asset_id,ref}]。Green 须覆盖所选资产（test-source 以文件 hash 与 JUnit 必需 ID 为证），哈希/来源不能变；提供不等于消费，上报不证明断言语义。

adapter 的 `skipped` / `xfail` 限制必须原样保留。原始报告声称 Green 但任一限制为真时，test_completion 将其规范化为 Yellow（`incomplete-test-execution`），保留真实断言和原报告/执行日志；已观察到的 Red 不降级。正式验收同样拒绝带限制的 Green，不能通过省略规范化版本或只看进程退出码绕过。

`global_paths` 是显式全局测试路径，可以为空或只覆盖已登记 CASE 的子集；它不代表全部模块用例。GO 的 global-plan 仍必须为所有 requirement/case 完整声明 owner，Auditor 沿既有非 Green 与变更影响范围选择复核路径。

## 逻辑单测

unit 冻结 argv/cwd/timeout/selection_ref。unit_report 固定 format=junit、runner 相对 patterns、required_test_ids（唯一 `classname#name`，参数实例也需稳定 ID），只有一个 expected=true 的完整执行断言。Gradle 默认 `outputs/**/test-results/**/TEST-*.xml`；宿主迁移输出到本轮 runner，追加 --rerun-tasks/--no-build-cache（含 KMP/native）并开启 JVM Test XML。其他工具在 `$SDD_RUNNER_DIR` 生成同格式报告。

解析 testcase/计数，保存具体 ID、执行/失败/跳过数量与报告 hash，绑定 run/module/PATH/assignment/test_run/freeze/code_baseline，接受时重核原报告。exit=0、实际执行非零、全部必需 ID 通过、无跳过/证据缺口才 Green。零执行、漏测、缺失/损坏/过期报告为 Yellow；断言失败或非环境中断的命令失败为 code Red，走既有诊断/Fixer。只收本 attempt 的新报告，旧 mtime/越界链接无效；任意可写 XML 的真实性仍依赖可信宿主执行。

冻结同一命令的 unit PATH 由 execute_test 以 `--path-id a,b` 一次执行，JUnit 按各自 required_test_ids 拆成逐 PATH 回执。作者的 `selfcheck --path-id` 记每个 required 测试的状态，实现前后两份记录是任务的 red 证据，只进报告不设门禁。进程内功能测试：kind=automation 的 PATH 带 command 与 unit_report 时按冻结命令执行、JUnit 归因，每条断言 expected=true 并以 test_id 指一个 required 测试，逐断言 pass/fail；在 automation 派发里跑，不算设备路径。prepared run 固定 unit_tests_required=true。每个 applicable Logic 项的 dimension_trace 须关联 unit PATH 或 unit_test_na 依据（缺者记欠项）。unit 无需设备，证明逻辑 Scenario，不替代 CASE 的 automation；环境缺失保留已通过 unit。枚举与唯一性断言（键只定义一次、无多余键）挂扫描类进程内路径，不挂 unit。

## 日志与按需追溯

execute_test 在 runner 持续写 stdout.log/stderr.log（原始字节）、execution.log（带采集时间/stream）、output-events.jsonl（序号/字节位置），execution-state.json 绑定本 attempt 身份、输出量及完整性；采集顺序不表示跨 stream 的因果。超时/取消标记不完整，硬终止可能只留下 running，须宿主核查，不自动重跑。receipt.capture 固化引用，提交时归档。

恢复/诊断先读当前模块状态和 trace 摘要，完整日志、历史轮次、媒体按需读取，不自动装入下次上下文。trace.py 位于 skills/migration-ledger/scripts，只读、不刷新投影或拿锁：

```sh
python3 <package>/skills/migration-ledger/scripts/trace.py query --root <run> --module M001 --scenario-id SCN-M001-query
python3 <package>/skills/migration-ledger/scripts/trace.py query --root <run> --module M001 --path-id U1 --history --offset 0 --limit 5
python3 <package>/skills/migration-ledger/scripts/trace.py evidence --root <run> --sha256 <已提交引用hash> --offset 0 --bytes 1024
python3 <package>/skills/migration-ledger/scripts/trace.py live --root <run> --module M001 --attempt <本run/runner> --stream stderr --offset 0 --bytes 1024
```

query 还支持 --task-id/--assertion-id/--test-id，默认最多5条，仅失败附1024字节日志尾，长字段截断、按 next_offset 翻页；读事件索引对应的归档，源码改变不破坏旧证据，缺损显示 evidence_issues，历史 Green 不表示当前有效。evidence 只读已提交文本证据，每次最多4096字节，媒体保留引用；live 仅供 Host 观察（accepted=false），不作跨 Agent 验收输入。

## 静态规格闭合

顺序为 build → unit → static → automation → visual。prepared run 固定 spec_closure_required=true，每模块一个 static PATH（缺者记欠项，多者拒绝）：断言为唯一 expected=true，复用已有 case_id，不替代业务覆盖；审查范围由 Ledger 派生（全部任务需求与冻结场景），PATH 不列。

独立 Test-Runner 只读 SPEC 与当前代码/测试，从 Ledger 骨架（`report_skeleton`：冻结场景逐行、反模式逐项、上下文已填）填写审查，留标记即拒：

- scenarios[]：每行 status=passed|failed、summary、production_symbols（目标绝对路径+真实符号）、evidence_refs。passed 必须给 reached_from：另一个目标文件中的调用/DI/导航/清单引用；有 unit PATH 还须 test_refs 指向真实测试符号。未接入生产不能 passed。
- anti_patterns：preview-only-wiring、dead-handler、fixed-result、placeholder-icon、unapproved-stub、swallowed-error（错误显示为空态/成功）逐项 absent|present、note、evidence_refs。批准的 capture-fixture 边界可 absent，须引用批准依据。

building 预检的 execution.commands 一并批准 build/unit/static 命令和 review 路径；同一 build assignment 依次执行 build、unit、static，到第一个非 Green 为止，一次提交和验收；结果须覆盖已到达环节的全部待测 PATH，同一代码上已 Green 的环节重试时不重跑。非 Green 即诊断/Fixer 后重跑。`execute_test.py` 调用 [spec_closure.py](../../migration-ledger/scripts/spec_closure.py)（--review、--target-root），核对上下文、场景覆盖、符号和清单；failed 场景/present 反模式为 Red。脚本不判断业务语义，Test-Runner 审阅、Auditor 抽查。static 全绿前禁止 automation/automation-unavailable；缺设备仍执行 unit/static。

## 运行时变体与冻结 SPEC 冲突

截图、运行时树或设备观察到的页面变体与冻结 SPEC/源码默认不一致时，这是用户的范围决定，不是代码缺陷：Test-Runner 记 Yellow，root_cause 为 `category=human`、`reason_code=runtime-spec-variant-conflict`、`confidence=confirmed`，引用冲突证据（外部对齐结果的同类 issue 由适配器规范化为同一根因）。MO 游标给 `suspend(kind=human)`，交 Escalation 取得用户选择后再规划或继续；不派 Fixer，不默认任选变体。

## Harmony Main

已内置 [Harmony 适配协议](../../migration-test/references/harmony-runtime.md) 与执行内核：输入冻结 PATH，输出按 ASSERT ID 绑定原生 Verify 的截图/视频结果，保留时间线、录制、布局与视频映射；UI 谓词 expected=true 的语义在 design 冻结。每次观察落盘，回放仍重新验证；同断言 pass/fail 混合为 flaky Yellow；缺设备/模型/媒体或结论不明为 Yellow。harmony_stage 把 host receipts 汇成 tests stage，Ledger 复验媒体 hash 与三态；超时终止进程组并保存已有输出。断言的 `reference_media_id`（用户截图作参考图，verification=refer_image_assert，不需 reference_step）由 adapter 核对 hash 后交引擎验证；`record_video: true` 的 PATH 以 `media_refs`（hash 绑定、在执行输出内）带回 final.mp4，报告逐 PATH 列出，diagnose/Fixer 并列用户预期媒体与实际媒体，不改三态；`media_marks` 见[用户参考媒体](project-context.md#用户参考媒体)。

Harmony 不自动生成结构化 interaction_evidence：缺这份证据时的规范化见[视觉对齐](ui-fidelity.md#视觉对齐--automation-第二层不是独立阶段)；Test-Runner 在预检说明能力缺口，换 adapter 或走缺测出口。

## web Main

已内置 web Main（`skills/migration-test/scripts/web_main.py`，adapter 见 [web-test-adapter.json](../../../template/web-test-adapter.json)）：PATH 填 `platform=web`、`task_type=test`，steps 是确定性动作对象（goto/click/fill/press/wait，首步 goto），断言 `verification=dom` 带 predicate（text/value/visible/count/url/title 的 equals/contains/matches）或 `refer_image_assert` 带用户截图（Ledger 绑定 reference_media_ref，视觉分 ≥ tolerance，默认 80），形状见 [web-test-path.json](../../../template/web-test-path.json)。Main 用 Playwright 真实浏览器走步骤，每步前后截图，谓词在其 after_step 后判定，观察逐条落盘；回执 producer=web-main，带 query_sha256、environment_ref（platform=web、browser）、step-trace（每步 hash、状态、前后截图）、observations 与 media_refs（截图，`record_video: true` 时含录像）；Ledger 核对上下文、query hash、每步证据与每条断言在其步骤后的观察，缺一为 Yellow；无法执行的步骤停止路径记 Yellow，谓词不成立记 Red。没有 producer 的项目适配器仍按 `{"assertions":[...]}` 验收，三态由断言推出。

## 分阶段唯一验收 owner

- 模块阶段：MO 唯一验收本模块 CASE/PATH：Test-Runner 提交真实结果，MO 核验完整 Green、当前基线、证据与 DoD 后提交验收记录。
- 全局审计阶段：本次独立 Auditor 唯一验收审计范围 CASE/PATH；正式复测完整 Green 且覆盖、基线门禁满足后直接提交 audit-verdict/audit。MO 仍接收 worker 结果并守护修复模块 DoD，但不能批准或替代审计结论。
- Green 验收不需人类或 Global 会签；SPEC 冻结、业务边界、语义变更及交付授权保留原有门禁。
- `case_owners` 是覆盖范围，`owner_module_ids` 是修复责任，都不是验收人；验收范围由宿主身份、assignment、CASE/PATH、基线和证据共同确定，各阶段历史分别保留，模块 Green 不等于审计通过。

## 二方库验证与根因

基于冻结需求和 reuse-plan 的行为差异设计真实提供方接线/版本/配置、边界/异常及适配路径；mock/编译通过不替代集成测试。缺真实证据为 Yellow，断言错误为 Red，根因带 source/capability/mapping/version 和影响消费者；所选提供方变化使旧证据失效，详见 [复用协议](reuse-dependencies.md)。

对 reuse/adapt/reference，fidelity.scenarios 从已审核的存量行为基线建立复现断言，execute 用同场景前置/输入/状态验证真实目标链路；每个 scenario 关联冻结 PATH/ASSERT 与 Main 回执，不能用库的当前返回值重写 expected；对齐报告不是测试通过证据。

## 测试启动前的上下文门禁

Test Runner 接到 build 派发后提交 building、接到 automation 派发后提交 testing 报告，Auditor 最终验证在 audit-assign 前提交 audit-testing 报告；ready 报告绑定派发后才执行，execute_test 只接受已绑定 ready 报告的派发并再核对命令和环境引用，不匹配须重新预检和派发，不能换命令绕过；缺条件不生成假测试结果。报告内容见[上下文就绪协议](context-readiness.md)；仅自动化环境缺失走[缺测出口](progress-recovery.md#4-自动化缺测出口)，不冒充 Green。

## 埋点上报断言

遵守[埋点协议](telemetry.md#5-验收层级与环境缺口)：事件存在才生成/关联业务 PATH/ASSERT，无埋点不增加测试或 skip；adapter 留原始观测/回执，缺证据的路径单独 Yellow，其余继续。
