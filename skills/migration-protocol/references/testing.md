# 测试路径、Main 与复测契约

## 设计模式与执行模式

design 模式：冻结前只读整体/模块测试输入及规格，补齐正常/边界/异常、权限/数据等适用路径，输出 CASE-ID → PATH-ID/Name 与验收映射；不读取实现源码推导预期、不执行测试。缺失业务预期经 Spec-Designer 澄清。

execute 模式分 build 和 automation，按 [双环节协议](build-automation.md) 执行。代码已生成并经 MO 接受后，把已批准路径落实为技术栈真实脚本/选择器/数据参数。若发现新验收语义，发 CR，不自行补成新标准。设计与执行可由不同实例担任，仍属于同一角色。Auditor 不能是该轮脚本作者。

Main 是项目提供的主验证入口，不是固定 `main.py`，也不是某个产品特有 Agent。输入 `test_adapter` 指定 executable/args/cwd、query 传输和结构化结果路径；未配置或不可用 → Yellow tooling。模板不包含假测试或自动通过的适配器。

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

本地一轮策略与问题审计：Red/Yellow 可修复根因先自动一轮，确认依赖/外围或仍失败时 audit-defer；问题审计独立执行有效代码，缺代码/前置时只记 Yellow。Auditor 对正式复测证据直接作审计验收；MO 只接收模块恢复/修复任务并执行模块门禁，不会签审计结论；最终审计不能跳过。

## 静态规格闭合

拆分测试的 Ledger 顺序为 build → static → automation → visual。static 是 Test-Runner 在当前已构建代码上做的独立规格闭合审查（吸收 lean Validator 的逐场景核对与假实现清单），位于昂贵的设备自动化之前；prepared run 固定 `spec_closure_required=true`，每个拆分模块冻结恰好一条 `kind=static` PATH：`scenario_requirement_ids` 等于模块全部任务需求，`expected_assertions` 只有一个 `expected: true`，case_id 复用本模块已有 CASE，不能新增或替代业务覆盖。

Test-Runner 只读冻结 SPEC、当前代码与测试，写审查记录（staging）：

- `scenarios[]`：每个冻结需求一条，`status=passed|failed`、summary、`production_symbols[]`（目标文件绝对路径 + 文件内真实存在的符号）与 evidence_refs。
- `anti_patterns`：`preview-only-wiring`、`dead-handler`、`fixed-result`、`placeholder-icon`、`unapproved-stub` 逐项 `absent|present` + note + evidence_refs。经冻结批准的 capture-fixture 边界记 absent 并在 note 引用批准依据。

static 不需要设备，与 build 共用一次派发：building 预检在 `execution.commands` 中同时为 build PATH 与 static PATH 预批准命令（static 的 review 路径提前确定）；MO 接受全绿 build 结果后，同一 assignment 保持打开并切换为 `test_scope=static`，由同一 Test-Runner 继续，无需新的派发或预检，MO 仍单独接受 static 结果。build 未全绿时 assignment 正常关闭。运行时经 `execute_test.py` 调用 [spec_closure.py](../../migration-ledger/scripts/spec_closure.py)（argv：`--review <记录> --target-root <target>`）。适配器只核对上下文、需求覆盖、引用符号确实存在于目标文件、清单完整，然后生成唯一断言；任一场景 failed 或反模式 present 即 Red（root_cause 列出缺口），进入原诊断 → Fixer → 重新 build/static 复测闭环。适配器不自行评判代码，审查质量由独立 Test-Runner 负责、Auditor 抽查。static 全 Green 前不能派发 automation 或记录 automation-unavailable；仅自动化环境缺失时 static 照常执行。

## 运行时变体与冻结 SPEC 冲突

截图、运行时树或设备观察显示的页面变体（如 live 页签）与冻结 SPEC/源码默认（如 trending）不一致时，这是用户的范围决定，不是代码缺陷：Test-Runner 记 Yellow，root_cause 为 `category=human`、`reason_code=runtime-spec-variant-conflict`、`confidence=confirmed`，引用冲突证据。lean 验证/对齐结果中同类 issue 由适配器自动规范化为同一根因。MO 游标直接给出 `suspend(kind=human)`，交 Escalation 取得用户选择后再按决定重新规划或继续；不派 Fixer，也不默认任选一种变体。

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

Test Runner 编译前提交 building、自动化前提交 testing 报告，Auditor 最终验证先提交 audit-testing 报告；包括已接受代码、冻结 PATH/assert、提供方、工具/环境/数据与 execution.argv/cwd/environment_ref。原 assign/audit-assign 接受后 execute_test 再核对命令和环境引用；不匹配须重新预检和派发，不能换命令绕过。缺条件不生成假测试结果。见 [上下文就绪协议](context-readiness.md)。

仅自动化环境缺失采用 automation-unavailable/automation-deferred 专门分流；不耗修复轮次、不阻塞可执行的下游或并行工作，也不冒充 Green。Auditor 可记录完整缺测清单后完成本轮；其余真实 Red/Yellow 保持原诊断修复流程。

## 埋点上报断言

遵守 [埋点协议](telemetry.md)：测试预期从已审核的源行为冻结，事件存在才生成/关联业务 PATH/ASSERT；无埋点不增加测试或 skip。明确 emitted/sdk-dispatched/server-received 验收层级，验证正确事件/参数/次数及适用的禁止触发/边界情况，项目 adapter 留原始观测/回执。部分路径缺证据单独 Yellow，其余可执行路径继续；不得用图片、空实现或被 mock 的核心逻辑充当上报验收。
