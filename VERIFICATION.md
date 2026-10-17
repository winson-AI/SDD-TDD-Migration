# 验证记录

本文件只记录当前版本的验证方式、结果与边界；版本演进见 [README 版本记录](README.md#版本记录)。

## 运行方式

三套测试相互独立，均在临时目录中构造隔离的 legacy/target/run，不读取包内 `.env`、不连接真机或外部 LLM。使用 Python 3.11+（`foundation-verify` 需要 tomllib，视觉比较需要 Pillow，矢量参考渲染另用 `rsvg-convert`、未安装时对应测试跳过，可直接用 Harmony sandbox 的解释器）；禁用字节码、pytest 插件自动加载与缓存，不安装依赖。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q -p no:cacheprovider skills/migration-ledger/tests
```

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q -p no:cacheprovider skills/migration-test/tests
```

```bash
cd skills/migration-test/runtime/harmony && PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests
```

## 当前结果

| 测试集 | 通过 | 本次核验 |
| --- | ---: | --- |
| migration-ledger/tests | 1588 | 全量通过，零失败/错误/跳过；本轮新增捕获到期、欠项门禁、黄金路径、agent 导航、web 证据链与宿主探针的测试 |
| migration-test/tests | 73 | 全量通过；本轮新增 doctor 探针的测试 |
| runtime/harmony/tests | 128 | 全量通过；本轮无改动 |

三套测试用 Harmony sandbox 的 Python 3.11+ 解释器经 pytest 执行（`PYTHONDONTWRITEBYTECODE=1`），零失败/错误/跳过。测试仅使用隔离临时目录、本地模拟端口和测试子进程。

本轮：存量捕获闭环（E1–E7）：Spec-Designer 的 plan 步骤带 capture_due、卡片带存量预览与存量捕获小节；未捕获的界面、未引用的用户截图/预期与未引用预期的 design 是首版携带的欠项（owed），一致性矛盾仍拒绝；宿主职责、sandbox doctor 的 adb/Playwright 探针、经验库携带 legacy_preview、每个 worker 操作的请求模板；三条存量→目标黄金路径（Android→Harmony、Android→Android、web→Android）以假设备端到端走通，adb 候选的 pull/screencap 计为原生捕获证据；重复的测试/构建/存储/收尾/复用/埋点表述各留一处权威并加指引，section 读取忽略代码块内注释，棘轮 483,500 → 468,000；navigation.mode=agent 的目标由声明的 navigator（adapter snapshot 任务）走到界面后仍按冻结选择器捕获，未到达记 navigation-unverified 并附 capture_gap 建议；浏览器按同一滚动契约滚到冻结终点，analyze-ui platform=web 从运行时索引派生 DOM 树（无源索引，节点 id 取元素 id，图片来源只记录），web 树只绑定运行时索引并通过冻结证据、adapter 与语义门禁。上一轮：存量预览与媒体取证（D1–D6）：项目上下文声明存量怎样跑（android-device/android-emulator/vm/browser/none），可执行性随声明、未捕获的界面写 capture_gap；运行时移植上游的 snapshot/recording 任务类型并产出媒体回执；legacy-capture 在包内装机、按冻结动作走到界面、写 android-reference/legacy-reference 记录（adb 或 Playwright）；测试结果带 media_refs，报告逐 PATH 列媒体、diagnose/Fixer 带非 Green 路径的媒体；Android 目标走 adb 装 APK 并写 android-candidate；候选与参考谓词各归一函数。上一轮：项目理解（U3、U4、U1、U2）：目标画像逐功能记 absent/shell-only/partial/existing，脚手架只在缺外壳处、持有代码的叶子欠复用说明；项目知识文档可按 project 模式检索，knowledge-need 由人以 kind=knowledge 决定补充并写成本 run 文档；用户参考媒体随项目上下文固化并下发到持有叶子，截图作 user-reference 基线、录屏作交互预期、未被 PATH 引用即欠项；target-expectation 取代存量基线、design 须引用、报告披露。

协议体积为 467903 / 468000 字节，最大单文件 25280 / 32000 字节。test_reading 枚举的 1584 个角色/范围/触发组合中最大卡片 50574 / 60000 字节，最大模板组合 50912 / 56200 字节；拒绝消息带小节指引的比例 83.3%（棘轮 80%）；未放宽门禁。源码语法、JSON、引用与 `git diff --check` 通过。

## 已覆盖

| 范围 | 实际验证 |
| --- | --- |
| 执行反馈与 TASK 独立性 | 现有诊断直接分流 Fixer/CR/上溯，不新增冻结前规划轮次；MO 可选证明绑定新旧计划、TASK/读写依赖/原验收，局部更新保留未影响 TASK/Green，构建等前置门禁与受影响路径正式复测；保护输入改变则失效，原回执/执行基线和有效基线分开统计。 |
| 统一控制与历史 | 初始化拒绝流程版本选择，历史标记不改变当前门禁；编码前调整只保留不可执行 planning_history，过期冻结与缺 TASK/PATH 契约的 assignment 不可执行或提交；Auditor 仅统一宿主审计，独立 Test-Runner 提交复测；旧封存配置按当前预算投影，同 Run 调整不改历史字节 |
| 上游用例与按需设计 | prepared Run 默认直接提交 SPEC 与 upstream-test-plan，完整 CASE/PATH/ASSERT 绑定权威输入、当前 scope 与 Scenario；无需 design worker 即可 MO 审核冻结并完成 build/unit/static/automation。缺 CASE、替换来源、过期分配、伪造实际结果或资产越 staging 均拒绝。显式 design 仍走 assign/submit/accept，保持身份、预检、规格/任务/断言一致性与过期拒收；运行级门禁要求覆盖，不强制增加设计轮次。 |
| 行为契约与场景追溯 | GO/父 MO/子 MO 行为审阅按 scope/REQ/CASE 校验；共享能力按父子归属解析唯一执行 owner，跨模块集成 CASE 归消费者，无关模块证据漂移不阻塞当前模块；SPEC 每个 Scenario-ID 派生并冻结到 TASK/PATH/ASSERT，缺场景、重复 ID、过期索引和以构建替代行为断言均拒绝；scenario_index 与静态审查范围由 Ledger 从 SPEC 派生，plan 携带过期或不全的值被拒；叶子的 source_closure 即其行为审阅；复用目录的 provider owner 与行为审阅解析出的叶子 owner 不一致时拒绝 |
| 单测报告核验 | JUnit 核验本次 attempt 的测试 ID、计数、报告 hash 与执行身份；零执行、跳过、缺损、错选、过期、越界证据不为 Green，断言失败为 Red，进程信号中断为 Yellow；Gradle 追加 --rerun-tasks --no-build-cache |
| 日志与按需追溯 | 进程退出前可读双流日志，大输出不依赖内存缓冲；超时、取消、硬终止保留不完整标记，原终止/验收规则不变；capture 引用与身份在接受时复核；trace 只读已提交事件索引对应的归档，按 Scenario/TASK/PATH/ASSERT/测试 ID 过滤并分页、限字节，实时观察标为未验收，查询不取业务锁、不写文件；watchdog 可观察输出但不以此替代存活证明 |
| 包内文件漂移 | 嵌套的控制器/协议引用在文件变化后，凭本 run 已提交事件的路径与哈希读取同哈希归档；未提交或外来归档、缺损或被重定向的归档均拒绝；SPEC、源码、环境与顶层输入仍校验当前字节 |
| 真实工具探针 | 在一次性宿主 workspace 用 Gradle 7.6 + JDK 17 + JUnit4 实跑：通过与故意失败的用例分别识别为 Green/Red，JUnit 报告核验无缺口；KMP/native、装机与设备自动化未覆盖 |
| 冻结与理解门禁 | 未冻结编码、代码未接受即测试、批准 hash 不符、源码未决/目标可行性 unknown 均拒绝 |
| 变更 | Fixer 越权改 SPEC 拒绝；MO 审核受影响规划后再冻结，保留现有代码与失败证据、清除旧任务验收并要求更新提交及正式复测；旧 plan/执行进入不可执行 history。原 scope 内新增验证路径/断言可技术审核，修改旧预期、删除旧路径/断言或越界仍需明确决定。 |
| 结果与复测 | 空/遗漏断言、伪装 Green、篡改原始报告拒绝；非 Green 复测需新 test_run_id/retest_of，代码变化拒收旧结果 |
| 真实闭环 | 子进程 Red → 诊断 → Fixer → 正式复测 → 模块 Green；构建与业务失败共享累计修复预算；实际依赖/外围阻塞或预算耗尽转 waiting-auditor，全模块收尾后统一宿主审计 |
| 作者自检与会话 | 实现/修复结果缺 authoring_diagnostics、诊断无日志或版本敏感 API 无固定源码引用均拒收；本地修复游标指向原 Implementer 会话 |
| 静态规格闭合 | build 全绿后同一派发继续 static，再到 automation；passed 场景须给出另一目标文件中的调用位置（reached_from）；审查需覆盖全部冻结需求、引用目标文件中真实存在的符号、逐项判定假实现清单；反模式 present 为 Red 并进入修复；prepared run 必须冻结 static PATH |
| 文本压缩 | 说了两三遍的规则各留一处权威表述、其余处改为指引（测试与构建的阶段顺序和缺测出口、运行根与 prepare 与 sandbox 留存、预算与锁与验收 owner、复用冗余表、埋点卫星节、切片规约的复用/埋点/验收段）；section 读取忽略代码块内的 `#` 注释；棘轮 483,500 → 468,000 |
| run 固定包版本 | prepare 记 package_sha（包目录的 git HEAD），init 存入状态；此后每个请求都核对执行中的包提交，不同则拒绝并指引用该提交的 worktree；未记 pin 的旧 run 不判 |
| Implementer 只选 TASK | assign 省略 path_ids 时 Ledger 取所选 TASK 的 PATH 并集并记入 assignment；Test-Runner/Fixer 仍显式 |
| 任务按层信号 | plan 接受时过半行为 PATH（automation）绑定过半 TASK 则记事实 SLICE-<module>-tasks-by-layer（一次）；build/unit/static 共享不计；不阻塞 |
| 完整性标志一致 | module_slicing.functional_use_cases_complete=true 而无 test_cases_path 时 prepare 校验与 init 均拒绝 |
| 角色文件无专题表 | Agents/*.md 不再带专题义务表，卡片按触发直接携带协议小节；section() 不再按专题过滤行 |
| 卡片按运行事实取 UI 保真节 | ui-fidelity 的小节只在有设备平台、视觉 PATH、图片条目或 Resource 维度时进卡；无设备且无图片的 UI 模块从源码编码、进程内测试，卡片不带这些节；最大卡片 42131 → 35228 字节 |
| 骨架由 Ledger 写 | spec_skeleton.py 从分配、清单、CASE 与能力目录写出六件套、stage-plan、upstream-test-plan（含 test-plan.md）与 reuse-plan（含 reuse-fidelity.md）的桩：每 CASE 一条 automation PATH、每 Logic 条目一条 unit PATH、build/static PATH、每功能一个 TASK、逐条目 trace；`[[待写]]` 由作者填，plan 时计划及其 test_design_ref / reuse_plan_ref 文件含标记即拒绝；`contracts.py refs <目录>` 一次给出整目录引用（scratch/ 除外） |
| 起步门禁与完成门禁 | 冻结只拒绝范围/写锁/任务/PATH/四维追溯/六件套的缺失；UI item 的语义模型与 ui_evidence、reuse-fidelity 逐场景记录改为欠项（记 gap，DoD 前结清），无 ui_evidence 的条目不再要求判定存量可执行性，视觉路径门禁跳过它；run 声明无设备（test_adapter.device.unavailable）时不欠 UI 树与基线 |
| 首版耗时与被拒次数 | workflow_cost 逐叶从日志算登记到首次 plan / 冻结 / 首次 implementer 派发 / 首次 Green 的分钟数，并从 reports/rejections 计被拒请求数；报告列表，不是门禁 |
| 产物体量不是门禁 | 运行产物（六件套、上游测试计划、fixture 契约、reuse-plan、评审证据、issue 摘要、任务 scope、设备缺口原因）不设大小上限，Ledger 不因大小拒绝或记欠项；体量棘轮只约束工作流包自身的协议、卡片与模板；step 视图仍只显示 issue 摘要前 200 字符 |
| 数据契约 | 四维 data_review 适用时 data_inventory_ref 绑定清单：实体逐字段的 sources / fetch_conditions / derived_fields / invalidation 义务，contracts 的目标 repository#symbol 与四个映射逐义务覆盖，fidelity exact / approved-adaptation（适配须信封 alternative），existing_target 须 refactor/adapt 决定；plan 时 data_obligations 覆盖全部义务且 PATH 为 unit/automation 并绑定 fixture；freeze 时目标与 fixture 已定、repository 在写范围或目标已有；实现提交 repository 文件与符号证据 |
| 一种版本学说 | 已接受的工件沿用接受时的规则，重新提交按当前规则全判：取消 restated_shape / restated_task_scope 豁免；原样复述且分配未变的孩子不再判，分配任一字段变动即全判 |
| 根自带清单 | readiness 开启且 decomposition_required 的根在 register 时必须带 feature_inventory_ref；分配包在 global-plan 之前暴露它；拆分计划不写引用则取根的 |
| 树形事实 | 清单接受时记 SLICE-tree-fine（二级节点过半少于 3 条 CASE）与 SLICE-tree-flat（每功能一条用例）；少于 5 个功能不记；事实不阻塞 |
| 切片与用例同源 | decompose 计划带 feature_inventory_ref，功能叶声明 functional_paths；Ledger 推导叶子的功能并要求功能叶不重叠、并集覆盖父的全部功能、case_ids 精确等于这些功能的 CASE 并集，脚手架不声明节点；readiness 开启的首次拆分必须带清单；global-plan 的 feature_owners 等于推导出的唯一 owner，叶子与最终清单不一致拒绝并提示 redecompose |
| 用户用例锚定 | 清单带 test_summary_ref 时功能叶至少含一个 test-case-group 覆盖的功能，只由源码派生功能组成的叶拒绝；叶内派生功能记事实 SLICE-<module>-derived，复判不记 |
| 用例来源规则单处 | slicing.md「用例来源与切片抓手」是唯一表述，其余入口为指针；切片标准改为列表并写明每叶自带四维分析与六件套；角色专题表每行一句义务 + 协议链接 |
| 阅读卡与协议体积 | 每个角色/阶段/操作/UI/复用/埋点组合的卡片引用真实小节、包含四条红线与共享协议核心小节（核心规则/模式/取用/检查/通用约定）；runtime 总则与渐进加载只随 GO/MO 与会话恢复，业务边界与阶段验收只随 GO/MO/Auditor/Escalation，storage-layout 总则只随写工件的角色，context-readiness 总则只随要求就绪报告的 run且不超过 60KB；无触发条件的典型步骤卡片不超过 34KB、本步模板不超过 20KB；审计、GO 规划、MO 各操作取各自小节，技能只带执行规则，专题义务表按触发条件取行，操作矩阵只带当前操作的行；AGENTS.md 专题索引指向的每个“总则”都有卡片可达；协议、命令与模板索引总量不超过 539000 字节、单文件不超过 32KB，任何步骤在触发条件全部成立时携带的模板总量不超过 56.2KB；共享协议进卡时只带规则小节；游标步骤携带 must_read 与绑定小节正文的 card_sha256；任何角色、操作与触发组合的卡片里，链接只指向小节或模板，不出现整份协议文件；角色定义进卡时不带技能文件清单和只指向通用约定的小节；模块编排者未列出的操作只带状态模板 |
| 提示采纳与流程成本 | assign 回填的会话/阅读卡与建议比对并汇总为 hint_adoption；workflow_cost 按模块统计事件、派发、回执、验收、人工决定与修复轮次并进入收尾报告 |
| 单文件卡与增量交付 | `reading.py render` 以摘要命名写出单个卡片文件且幂等；`show` 只读包内 Markdown 单节并拒绝越界路径；会话已持有的小节不再进入 `must_read_new`，正文变化的小节重新交付；任意模块请求可带 `hint` 报告所用会话与卡片，匹配当前游标步骤才计入，格式不符被拒；流程成本统计每模块完整/实际交付的阅读卡字节；渲染后的卡片不含指向包内文件的链接（整份协议链接变纯文本、小节链接变“文件 § 小节”选择器），卡尾列出本步模板；Test-Runner 的角色定义按测试阶段取块；每步 `templates` 指向真实模板；会话累计持有的协议文本超过阈值时步骤带 `session_rotate` 建议 |
| 精简状态与拒绝提示 | `status --view cursor/module` 不含模块正文、卡片行清单与信号证据，卡片只给字节数与小节数（单模块夹具 13.7KB → 1.8KB）；`--since` 命中当前 sequence 时只返回 unchanged 与信号摘要（约 0.4KB），有新事件即返回完整游标；`--view step` 只给一个模块当前步骤所需：请求信封字段、本阶段预检要求（含必读引用）、分配包、当前 assignment 与待验收提交，规划类步骤和设计派发另带 planning_context，运行中的设计者得到自己阶段的要求，不含其他模块（已冻结叶子的派发步骤小于 module 视图的一半、full 视图的八分之一）；父模块汇总步骤同样带阅读卡与模板；CLI 输出为单行紧凑 JSON；未知模块或视图被拒；拒绝记录带 `read_hint`，每个提示指向真实小节 |
| 草稿不进证据 | 引用 run 内任何 scratch/ 下的文件被拒并指向 storage-layout 总则；收尾报告给出 staging 字节、未被事件引用占比与 scratch 字节，核验沿用投影时的这一观测，之后 staging 的增减不算投影失真 |
| 模板按名取用 | 卡片只列本步模板名并在脚注说明按名取用；`reading.py show --template <名>` 打印单份包模板并拒绝越界路径与不存在的名字 |
| issue 卫生 | fact 记录即对每个目标结清、不能 blocks、不挡 complete；step 视图最多列 10 条 open issue（blocking 优先、最新优先）并给总数；standing 规则在 `--since` 之后无新增时只给数量与摘要 |
| 提供方修订不挡依赖方 | 提供方打开 CR 后，依赖方的规划与派发仍以其已接受代码为准（providers 行带 revising）；修订冻结后被替代的引用按既有规则记 gap 并失效复测 |
| 薄脚手架 | 脚手架计划多于 3 个 TASK 须声明 ≤3 个 skeleton_task_ids，骨架 TASK 的 PATH 只许 build/unit/static，功能叶不得声明；骨架被接受且 build Green 即视为提供方就位（providers / dependencies_ready），其余 TASK 落地不逐次失效依赖方，全部落地时失效一次 |
| 在途形状沿用 | 再拆分复述一个已登记孩子时，若其切片形状（kind / 依赖边 / CASE 集 / anchor_ui）与账本所持一致，切片标准不追溯重判（`restated_shape` grandfather）；只判新叶与被重切的叶。后增切片规则约束新提交，已接受形状的差异进规则欠账交审计，不在 standard() 拒绝 |
| 调用登记不重切 | `api-register` 把分配后发现的调用登记给叶子与其 Logic/Adhesive 条目（run 内新 id、call/contract 形状、证据、角色与全局作用域校验，不推进修订号）；该叶 refinement 的清单可多出已登记行（narrowed、partition 放行，item api_ids / discovery_refs 可增），其他新增仍拒；step 视图列出本叶登记 |
| 可推导指针 | 计划只带一个 test-fixture 定义且 verification 未写 fixture 时，Ledger 补全指针并绑到行为 PATH；Logic/Adhesive 的 target_binding 未定在 plan/freeze 判定里记为欠项而非拒绝，Resource 目标侧字段仍拒 |
| 包文件不是证据 | evidence_refs 指向包内协议/角色/技能/命令 Markdown 或脚本被拒并指向 storage-layout 总则；包内知识资产（如 catalog）仍可引用；相对路径仍先报须为绝对路径 |
| 任务体量信号 | 实现结果里一个 TASK 超过 40 个文件时 Ledger 记一条已结清的 fact，游标 slicing_signals 加 large-tasks 标志；不挡接受与完成 |
| 投影文本确定 | 投影里的 JSON 一律按键排序写出，状态重放的键序变化不再使 change-content / status 投影被判失真 |
| 依赖阶段缺省 implemented | provider_inputs 不写 required_stage 时按 implemented 处理（providers、dependencies_ready、静态闭合等待、独立性统计一致）；写 verified 必须带 reason，否则拒绝 |
| PATH 不在别叶取证 | plan 与冻结时核对每条 PATH 的 preconditions/steps：提到已登记但非提供方的模块 id，或目标工程内本叶与提供方写范围之外的绝对文件路径，均拒绝并指向切片标准 |
| 子业务流切片 | 功能叶少于 3 条 CASE 被拒（父不足 3 条除外），多于 30 条被拒，21–30 条在父上记已结清 fact；父下功能叶多于 6 个记 fact；游标 slicing_signals 加 wide-leaf 与父级 many-features；anchor_ui 可为页面列表；规则欠账重判不写事实 |
| 统一全量审计 | 独立同伴运行时仅保留本模块问题；全部模块本轮收尾后启动宿主审计，不允许提前派发局部审计 |
| 轻量叶子与批量信封 | lean_leaf 登记需 scope/context/不可再拆审阅；本地轮由 Fixer 自诊断（`fixer_self_diagnosis` 对全部模块开启），未开启的普通模块拒绝；批量信封绑定文件 hash 与父的孩子，条目完全匹配且 MO 附 review_ref 才冻结 |
| 原子规划与历史 | MO 原子结论经 decompose/GO accept 保留节点；缺预检、行为/验证边界或扩大范围均拒绝；无关根待拆时叶子可完成实现/验证，依赖待拆仍阻塞；兄弟拆分保留冻结/活动执行和独立测试设计；reopen 留不可执行 history、重新冻结唯一 SPEC，禁止提前 coding/testing/fixer 或宿主审计 |
| 构建阶段一次验收 | build、unit、static 在同一派发内顺序执行，一份结果、一次验收；结果必须覆盖到第一个非 Green 环节为止的全部待测 PATH，build 未过不得带单测行、build 全绿不得省略单测；同一代码上重试不重跑已 Green 的环节；单测失败为 code Red 且先于设备自动化；自动化环境缺失时单测 Green 保留；applicable 的 Logic 项须有 unit PATH 或不适用依据；绿色叶子 18 个事件、4 次派发 |
| 崩溃归类与视觉聚焦 | 候选 App 启动后退出记 Red 候选而非环境缺测，只读设备查询超时重试一次；纯视觉诊断只接受 1–2 条结构化问题 |
| 写范围核验 | 开启后范围内未申报的改动、范围外未授权的改动、缺少或过期的回执均拒收；派发前的脏文件与工作流资产不计入 |
| 变体冲突 | runtime-spec-variant-conflict 规范化为确认的 human 根因，游标给出 suspend(kind=human)，拒绝派发 Fixer |
| Git 检查点 | 仅在运行分支提交模块文件、既有脏文件不暂存、重复执行复用 HEAD；伪造 blob 被 Ledger 拒绝；开启后无检查点不能 complete |
| 独立审计 | 实现者/修复者/测试作者不能兼任 Auditor；审计只复核遗留并按依赖补回归 |
| 事件与恢复 | 同请求幂等、同 ID 改内容拒绝、过期 revision 拒绝、并发 CAS 单赢家；投影崩溃可重放、伪改投影无效 |
| 事件日志与状态 | 首个事件记录初始状态，其后每个事件只记录变化；写入前校验补丁能还原已提交状态，重放结果与投影的全局状态一致，全局投影里模块 plan 只以 plan_ref 引用而模块投影保留正文；变更历史只以 plan_ref/plan_hash 记旧计划（打开中的 CR 仍带正文供任务复核）；冻结的验收只存逐 PATH/断言摘要，削弱断言仍被拒、新增断言可过；模块事件不重写兄弟模块或未变的计划；嵌套删除可重放；整键写法的事件仍可重放并可在其上续写；重放不改写已读事件；每个事件只列出此前未归档的工件，漂移与历史快照记录照常保留，累计索引仍能找到被多次引用的工件；状态只保存预检报告、提交结果与设计输入的哈希引用，验收时重读文件，被改动即拒收 |
| 按步取用 | coding 的预检由 Ledger 在派发时核对输入后代为登记并绑定，自报仍可取代或退回；Test-Runner 两个执行阶段共读角色文本，会话按小节保留读过的各版本；模板限本步所写工件；执行角色按冻结计划是否取用 provider 决定带不带复用小节；等待依赖的步骤不带卡；规划与拆分的必读输入不含源码树内文件而漂移仍被拒 |
| 预检随操作与机械步骤 | 执行者自己的预检报告随 plan/register/global-plan/decompose 等操作登记，他人的报告或跨角色阶段未先提交即拒绝；全绿测试结果的 accept 游标带 mechanical，代码结果与非全绿结果不带；执行派发（Implementer/Test-Runner/Fixer）在可派发时带 mechanical 与载荷（已有预检时含该实例及其报告），照此提交仍过全部派发守卫；设计派发与仍被 blocked 报告挡住的派发不带；`ledger.py advance` 以 MO 身份依次提交一个模块的全部机械步骤（默认实例 `<role>-<module>`，可指定），停在需要模型或人的步骤并写出其阅读卡，非 MO 身份或未知模块被拒；等待人工决定的步骤（冻结、恢复、审计放行、审计处置）都给出要绑定的 approval_subject_sha256 |
| 派发后预检 | 执行派发不等预检：worker 派发后 context-submit，ready 报告绑定派发并授权开工（Fixer 此时才计一轮），其他实例的报告不绑定；未绑定时提交结果与执行测试都被拒；blocked 报告退回派发、不耗轮次，游标 reason=context-blocked，该实例仍 blocked 时再派发被拒；仅自动化环境缺失时退回后走 automation-unavailable；派发前已有的当前 ready 报告在派发时直接绑定；诊断接受可带派发，被挡时整体回滚；证据漂移时 ready 报告无法提交，工作不被授权；模拟中绿色叶子每个执行阶段只启动一次 worker，模型调用 16 → 10 次（编排者 5、worker 5），事件数不变 |
| 上下文绑定 | 行为契约由运行状态写入 plan，作者可不声明、不能声明为 false；plan 与拆分提案不抄写全局上下文和分配包，Ledger 接受时在 plan 之外保存两者的摘要；全局上下文变化后冻结、派发与接受拆分被拒；来源追加时未受影响的模块沿用冻结 plan；设计输入引用游标给出的摘要，缺失或过期被拒 |
| 接受即定规 | 已登记的四维分析与行为审阅、已验收的设计、已登记的计划在之后各步只读取：其后写入的规则不重判它们，所引文件漂移仍拒收；叶子首次冻结后，冻结门禁不再重判同一份分配；与当前规则的差异列入报告的规则欠账，不作门禁 |
| 切片独立性 | 拆分写明每条 CASE 的唯一验收切片并记入切片；验收用例的切片只持有它验收的用例，其子条目挂自己持有的用例而不限于父条目所列，不验收任何 CASE 的支撑切片须有理由并可持有所服务切片的用例；三段依赖链或过半切片等待须有理由和证据；切片与根不得验收别处已验收的 CASE；再拆分移动验收时两侧重规划；报告列出各拆分的切片形态，共享用例按被多个切片持有统计 |
| 上游修订分流 | 根分析修订只触及引用了被改条目或契约的孩子，其余孩子原样沿用并继续推进，无孩子受影响时不再拆分；再拆分与 run 修订改到的已冻结叶子：边界保持的以 CR 接收并保留 plan、冻结记录与代码；边界改写、收缩、新增排除或依赖变化的整叶重规划；依赖被改叶子的叶子保留计划，已有代码的等 provider 后复验；只更新证据的再拆分保留全局规划；独立性证明可声明无 TASK 受影响，全部 TASK 保留且已有代码时重冻直接进入重建复测 |
| 界面采集范围 | analyze-ui 的入口指定类时只采集该类的源码段并记录行段，多屏同文件时各屏分别采集，未声明的类不采集并报告；工具索引里相对路径的文件记录不当作证据引用，索引可被计划与就绪报告引用 |
| 叶子细化分析 | 计划可绑定分配分析的细化版：分配所写的一切原样保留，只增加证据与实现层字段，资源条目可细分为逐文件的条目；参数表携带的取值计入资源闭包；细化版在提交时按登记分析的规则判定，冻结门禁、worker 输入与报告读取它，分配引用不变 |
| 人工决定一次与并行预算 | 接口适配由一次 run 级决定或父批量信封覆盖全部持有该契约的叶子；游标给出并行预算内当前应推进的叶子；叶子计划为分配里适用的保真条件绑定自己的断言 |
| 搬运约定定论 | prepared run 登记 UI/Resource 适用的分配前 copy 与 parameters 须已声明或带原因拒收；已登记的分析不重判；有叶子或尚无根的 run 均可经修订写入；约定已声明时可原样加载的文件必须走复制清单；计划中手工替换图片须写明不能复制的原因，报告随图披露并列出项目拒收的部分 |
| API 路由 | 调用与目标按 transport 登记：http 记 method/URL，rpc/sdk 记调用名；exact 契约保持 transport 与路由，义务与覆盖不变 |
| 用户路径 | prepared run 中叶子验收的用户可见 CASE 须有设备或视觉 PATH，或带原因与证据的缺口声明；只约束验收该 CASE 的叶子；有缺口的模块完成后为 Yellow、已执行路径保持 Green，该 CASE 与其 automation 在报告中为 Yellow，本轮以 completed-with-unverified-tests 收尾；统计按宿主任务/模块/TASK 分列设备、进程内、视觉路径的成功与应测及缺口 CASE |
| 叶子最小集 | 叶子有已登记的四维分析时，计划可只含六件套、tasks、测试计划引用与 dimension_trace；其余由 Ledger 据已接受的四维分析与行为审阅补全后存储冻结，作者自写的值保留并照常判定；同一文件重交补全结果相同 |
| 切分技能 | 采集时由经验库生成：合并各 run 的抽象切分/边界/规划教训、往次切分形态与未抽象观察，内容变才升版；prepare 固化进下一 Run；游标只在 GO/MO 的切分步骤给出，且只是切分阶段的必读输入 |
| 运行记忆 | 人工或工具阻塞与解除依据、一次冻结三次以上改交计划、达三次的同因拒绝进入本 Run 经验与采集，依赖与自动化等待不计；拒绝仍在日志之外；共享经验库按 `<project_id>/<run_id>` 分块，prepare 读取项目指定的库 |
| 人工与成本可见 | 游标每一步给出是否需要人；人工决定的用途取自日志，报告按用途列出并附解除阻塞的原因；报告把各叶子为计划撰写的文件与只被引用的来源分列，并给出 CASE/TASK 数 |
| 设备环境与在途可见 | prepared run 登记 UI 分配前须对设备验证环境定论；声明无设备时缺口由 Ledger 按该原因补入计划；规则欠账列出未定论的约定、设备环境与缺设备路径的已持有计划；仅有进程内路径的用户可见 CASE 在任何 run 都是保真限制；run 内定论的约定随采集入库并在项目配置未声明时带入下一 Run |
| 纵向切片与收尾复盘 | 拆分按四维分析判定界面与逻辑分属两个切片的用例并要求独立性审阅；报告与切分技能记录分层用例、单层切片、最多改交次数；结束的 run 在有未抽象观察或切分信号且尚无复盘时由游标给出 retrospective_due |
| 文档骨架 | 按叶子已接受的四维分析生成 proposal/spec/design/tasks 骨架，含全部 item、需求与场景编号；定义中留有待写标记的计划被拒 |
| 按需加载 | worker 的必读输入只含执行所需，ready 报告依据的全部证据仍核对漂移；未回报时按执行实例记卡并给出增量，红线每张卡都带；机械验收步骤无卡；同一小节在一张卡内只出现一次；拒绝消息指向规则小节的比例不低于棘轮 |
| 作者可省略的推导值 | test_design_ref、行为审阅的范围摘要与需求/CASE、任务四维分析的范围摘要与 parent_ref、global-plan 的规范与架构引用、PATH required、冻结与完成的勾选标志省略时由 Ledger 补全或按分配核对，写错被拒；plan 不含 global-contract 定义也能冻结 |
| 包内评审清单 | plan 自带 checklist 定义被拒；接受 plan 时 Ledger 把包内清单按内容哈希存入本 run 并绑定到模块，人工批准的 plan 摘要不变；投影替换模块号并附证据链接与 Ledger 勾选；重新规划时解除绑定 |
| 作者不重述已知值 | 预检报告不写必读输入：报告缺省 `read_refs` 即被接受，回执记录 Ledger 派生的输入摘要，使用回执时重新派生并比较——任一必读输入变化或被改动、其 JSON 引用的证据漂移、预检之后换了诊断，报告即过期或被拒；步骤视图只给输入个数与摘要；blocked 报告不绑定输入。任务级四维行省略 `evidence_refs` 时以所绑定的分配分析为证据，写了的仍受 hash 约束。JSON 文档顶层的 `refs` 表写一次文件引用，`evidence_refs`/`context_refs` 按 id 引用：读者看到写开的形式，plan 摘要与写开的写法相同，未知 id 被拒，表里被引用的条目照常校验和归档。hash 不符的拒绝点名文件与实际摘要，并指向引用规则。模块状态视图不含 plan 与场景索引正文。 |
| 设计跟随 SPEC | 行为契约下设计输入的 `spec_refs` 必须是带 Requirement-ID/Scenario-ID 的叶子 SPEC 草稿且需求与其任务一致，全局规格与上下文文件被拒，游标步骤说明设计输入需要什么；设计断言用 `scenario_ids` 写明所验证的场景，缺失、未知、需求不符、build/static 断言带场景、或有场景无断言验证均在设计提交时被拒；plan 的 `scenario_trace` 行只写 task_ids，断言由 Ledger 按设计断言补全并随 plan 存储和哈希，写了则须相同 |
| 单一运行输入 | prepare 返回的 input 由 GO 补齐后原样作为 init 载荷，通过快照、预算与门禁校验；repair_policy 不再是合法项目配置 |
| 摘要命令 | `contracts.py ref/baseline/digest` 输出的文件引用、代码基线和 JSON 摘要与 Ledger 校验所用一致，缺失文件报错 |
| 依赖/锁/身份 | 未完成生产者不放行；重叠写路径拒绝并行；revoke 后旧 worker 拒收；会话替换需 checkpoint |
| 并行隔离 | 单模块失败/挂起不回写兄弟；全部 MO 收尾后才启动 Auditor |
| 项目上下文 | prepare 固化配置/文档/知识快照；配置更新只影响新 run；快照篡改拒绝 |
| 复用与 provider | 能力目录必须显式 provider owner；null 为稳定基线、非空为唯一叶子 owner；owner 依赖、写权限、环与冲突拒绝；provider/归属证据漂移拒绝 |
| 来源追加 | source-review → reconfigure-sources 仅重规划受影响闭包，保留无关结果与预算 |
| 四维与语义模型 | UI/Logic/Adhesive/Resource 逐层映射到 TASK/PATH/ASSERT；N/A 需源证据；语义模型 hash 冻结 |
| UI 保真 | 原生 collector/selector → UI 树 → 冻结门禁；每个 runtime 目标独立 visual PATH；source-only 不伪造基线 |
| 资源精确性 | 精确策略枚举、源文件事实/qualifier/.9.png/sp 校验；裸附加 ID 不填闭包；跨配置路由需冻结证据 |
| 图片与图标对齐 | collector 记录嵌套 drawable、非布局 XML 图标、主题属性、assets 与没有资源文件的图片来源（URL/API 字段、运行时拼接名、数据绑定、绘制代码），资源文件带文件头事实；闭包要求每个触达的资源文件和每条图片来源各有一个 Resource item 或带证据的排除，并给出预填骨架；图像检查用存量资源离线渲染的参考与目标屏幕节点比较，Ledger 用哈希绑定的输入重算 MATCH/MISMATCH/INCOMPARABLE（Green/Red/Yellow），伪造的指标、节点、参考、选择器、容差、断言、构建、基线或其他 assignment 的报告均被拒；只带图像检查、没有基线的 visual PATH 可冻结并取证，runtime 目标仍须基线 PATH；静态图的 manual_exact 须带已声明且被承载的检查或计划信封内的偏差，动画与 .9.png 只接受偏差，绘制代码保留评审，raw/assets 中的非图片文件不算图片；树上每处静态图片须有同节点同资源的图像检查或带证据的豁免，缺一即拒绝冻结；`screen-checks` 为缺少检查的使用点派生检查并渲染参考，渲染不了的单独列出；文本检查的期望值须等于源索引中的字符串，节点检查找不到节点为 Red；铺满画面的不透明图片按内容相似度比较；收尾报告逐项披露非精确图片及其验证状态，不改变验收 |
| 资源与参数搬运 | collector 记录每处资源引用的行号、所在类/方法与接收它的调用；范围内代码用到而树未声明的文件资源被拒，按类、方法或引用带证据排除后通过；密度与平台版本限定符归为同一资源的副本；项目的 `target_resources` 约定随 prepare 固化，随包约定模板可通过校验并写出文件；复制清单由 UI 证据与约定派生，冻结时重算并逐行比较，同一资源只由清单或 item 之一覆盖；`resource-sync` 只在任务写范围内复制，相同文件保留、不同文件拒绝覆盖；验收比对副本哈希并在提交的代码中查找 accessor，副本自身和前缀相同的更长名字都不算引用；逐项登记的资源核对目标与消费者位于目标工程、字节或条目与存量一致、消费者文件完整出现 accessor；参数表从布局属性（style 展开、引用跟随）、drawable 图层与代码里的 setter、属性赋值和布局参数派生并分类；声明了参数约定的项目中有 UI 的模块必须引用参数表，未定值的 expression 与未映射的 token 拒绝冻结，偏差须是计划已批准的替代方案；参数文件由参数表、例外与模板决定，验收重新生成并比较，提交的代码须按键出现每个参数，前缀相同的更长名字不算；收尾报告给出复制文件数、检查覆盖与参数填充率；拒绝原因指向对应小节 |
| 视觉执行 | 正式 Green 绑定当前代码、本轮构建 HAP、本轮受管 capture 与 assignment/fence；semantic finding 需逐项裁决 |
| 手势 | 仅 Spec 声明的 interaction 生效；Green 需同 HAP/代码的真实设备观测；缺证据为 Yellow |
| Foundation 知识 | 冻结时按随包 catalog 重算解析；demo-source 仅候选；目标 TOML 版本核对 |
| 构建与自动化 | 构建 → 自动化拆分；自动化不可用走 automation-deferred Yellow，不阻塞独立任务 |
| OpenSpec 投影 | global/module/projection/final 分范围核验；模块隔离、内容失真、失效后重新规划 |
| 报告 | 全部 CASE 状态、非 Green 根因与证据进入 migration-report |
| 执行侧骨架 | report_skeleton.py 为 Test-Runner 写 building/testing 预检（Ledger 核对的检查项已填、冻结命令已复制、环境/提供方/权限留标记）与静态审查（冻结场景逐行、反模式逐项），为 Auditor 写代码修改清单（模块/功能/CHG/测试映射已填）与 audit-code-review.json（snapshot、goal_review 的 TASK/PATH、各检查引用清单）；派发与审查步骤带命令；context-submit、audit-code-review 与静态 PATH 的审查留标记即拒，标记按解析后的 JSON 判定 | test_report_skeleton |
| 同命令 unit 一次执行 | execute_test 的 path_id 可为冻结同一命令的多个 unit PATH：一次运行、一份日志与捕获，每个 PATH 自己的 query/result/receipt 与 JUnit 归因，回执记 batch；混入非 unit、不同命令或重复 PATH 被拒 | test_batched_units |
| 提交证据先列、conformance 派生 | implementer/fixer 派发步骤的 submission 列出结果必备证据（任务追溯、完整 manifest、绑定、诊断、逐映射 reuse_trace、四维证据）；semantic_conformance 在冻结落点文件属于本次交付时由 Ledger 派生，带 ui_evidence 的 UI 模型仍须作者写 baseline_conformance | test_start_gates、test_semantics |
| 无待复测的审计由 Ledger 预检 | audit_scope 为空时 audit-assign 不带 context_ref：Ledger 以 Auditor 名义写 audit-verdict 机械预检并登记；步骤标 mechanical；no-retest-needed 的 audit-review 照常裁决 | test_start_gates |
| TASK 行按模块缺口计缺路径 | automation 统计里 TASK 行的缺路径 CASE 只计模块整体缺的 CASE，只绑 unit PATH 的任务不再把兄弟任务覆盖的 CASE 记为缺口 | test_migration_report |
| 红线 4 分层与 red 证据 | 正式目标代码测试在代码被接受之后派发；作者自查不产生结果、不能代替正式测试。`selfcheck --root --module --path-id` 写 selfcheck.json（命令、退出码、时间、日志，逐 required 测试状态）；task_trace 可带 red_evidence={before_ref, after_ref}：同一 unit PATH 的两份自查记录，前者至少一个 required 未通过、后者全部通过且先后有序，Ledger 核验并记 task_red（observed / not-observed / not-applicable），不设门禁 | test_tdd_evidence |
| 规划占比与测试先行计数 | workflow_cost 每叶给 planning_share = 冻结分钟 / 首次 Green 分钟，tdd 计数按任务；报告首版耗时表增列 | test_tdd_evidence |
| 技术债 issue | issue kind=debt：与 fact 一样记录即结清、不能 blocks；审计骨架的清单第 8 节预列各 debt，审查 JSON 带 debts 清单 | test_report_skeleton |
| 只改测试写法的 CR 归 MO | approved_acceptance_digests 另记每条 PATH 的 identity 与每条断言的 expected/matcher/verification/after_step 摘要；CR 只改步骤、参数、前置、措辞而身份与期望不变时 needs_human 为空，plan-review 记 SPEC-<mid>-tests-revised 事实；期望、matcher 或身份变化仍要人工决定 | test_iterative_spec |
| 冻结测试源 | test_assets 增 kind=test-source：从 SPEC 写出的测试源文件随计划冻结，记 target_path、required_test_ids（文件须定义 class 与方法）、scenarios（逐测试对应 Scenario-ID，行为契约开启时须在 SPEC 内）、symbols（须出现在文件中）；绑定的 unit PATH 只要求它定义的测试；留标记即拒。实现提交时，持有其 PATH 的任务必须把文件原样交付到 target_path（hash 相等），否则拒绝；派发步骤的 submission 列出 frozen_tests；execute_test 执行前核对文件 hash 并写回执 frozen_test_sources，同命令批量执行逐 PATH 带绑定；Green 不要求 test-source 的消费上报 | test_frozen_tests |
| 测试源骨架 | spec_skeleton 为每个 Logic 条目写 test-sources/<Class>.kt（目标有 Kotlin 源时；否则 .txt），每个 CASE 一个 @Test 方法，Given/When/Then 留标记；unit PATH 预填 unit_report（required_test_ids）、expected=true、command 占位与 prepared 准备，test_assets 预填 test-source 条目 | test_frozen_tests |
| 进程内功能测试 | kind=automation 的 PATH 带 command 与 unit_report 时按冻结命令执行、JUnit 归因：每条断言 expected=true 并以 test_id 指一个 required 测试（plan_check 核对一一对应），结果逐断言给 pass/fail/未观察，红由失败的具名测试决定；在 automation 派发里跑，不是设备路径；同命令可批量 | test_functional_paths |
| 骨架按场景选测试形态 | 无设备或非界面的 CASE：进程内功能测试（platform=jvm、unit_report、命令占位、test-source 资产 <Case>FlowTest#flow）；有设备且 UI 项绑定 UI 树的 CASE：设备 automation PATH 加 script 资产骨架（Kotlin 或 ArkTS/Hypium，选择器取 UI 树节点 id，断言映射 ASSERT），无树则留给引擎 | test_functional_paths |
| 脚本驱动的设备路径计数 | 接受测试结果时从宿主回执的 test_asset_usage.entrypoint_ids 记 scripted；automation 统计分列脚本驱动的设备路径数及其中 flaky 数，作为 T6 试点的对照 | test_functional_paths |
| 存量预览 | project context 的 legacy_preview（android-device/android-emulator/vm：device.serial、app_id、artifact 或 build、launch；browser：url；none：reason）经校验后由 prepare 记 artifact 哈希；UI 登记前须声明，否则是运行的规则欠账；legacy_executable 随声明（矛盾被拒、缺省补齐），存量可跑的界面须 runtime 捕获或用户截图，否则写 ui_evidence.capture_gap（reason、evidence_refs），报告逐界面写基线来源并把 capture_gap 列为保真限制 |
| 媒体任务与回执 | 内置运行时接受 task_type=snapshot|recording：不要求 verify，snapshot 保存连续两帧一致的终帧与布局，recording 保留 final.mp4，走不到终点标 needs-review；结果写成报告目录的 media_outcome.json；adapter 的媒体查询须有步骤、不带断言、命名 path_id 或 capture_id，回执 status=reached|needs-review|blocked 带 snapshot/layout/recording 引用，不是测试结论；test PATH 带 record_video 时强制录屏并把 final.mp4 列入 media_refs |
| 存量捕获 | legacy-capture 对 Spec-Designer/Test-Runner 开放、绑定 assignment 而不要求计划、须宿主锁住声明的设备：adb 后端按声明装机（artifact 哈希或 build 命令）、启动、走冻结 tap/swipe/back、核对前台与选择器、截图前后树稳定、有界滚动，写 android-reference 记录；浏览器后端用 Playwright 打开 url、走冻结 click、DOM 转成同形视图树，写 legacy-reference/web 记录（仅 viewport）；捕不到的目标带原因（PARTIAL/BLOCKED），manifest 经 validate_manifest、capture_target、select_runtime_ui 原样读取 |
| 媒体证据 | 结果行的 media_refs（screenshot|recording，hash 绑定、须在执行输出内）由宿主完成解释从 adapter 回执复制；报告路径明细与非 Green 原因列媒体，视觉覆盖表列目标媒体；diagnose 步骤与 Fixer 派发带非 Green 路径的媒体；record_video 只允许在 automation/visual PATH 上 |
| Android 目标捕获 | 视觉 worker 的 adb 后端：visual-install 装 APK 并用设备自算的哈希核对已装包与接受产物一致，visual-capture 启动 activity、走冻结动作、复用 Android 观测写 android-candidate 记录；候选谓词 is_candidate 覆盖 harmony/android 两种候选，参考谓词 is_reference 覆盖 android-reference 与 legacy-reference（android/harmony/web）；APK 可作构建产物 |
| 目标画像 | global-plan 绑定 target-profile.json：逐功能 state（absent/shell-only/partial/existing）、入口、符号、构建单元、已有测试与证据，缺功能或无证据被拒；脚手架子叶只在 absent/shell-only 处允许；state 为 partial/existing 的叶子冻结时无 TARGET 映射或 existing_target 契约即记欠项；分配包带本叶画像，报告列迁移前状态 |
| 知识需要与补充决定 | knowledge-query 的 project 模式检索 knowledge_paths 文档并返回可引用 ref；issue kind=knowledge-need 只能由 kind=knowledge 决定或项目知识文档结清；决定须答案与来源，Ledger 写成 artifacts/knowledge/<decision_id>.md 并随游标步骤下发 |
| 存量捕获到期与首版先跑 | Spec-Designer 的 plan 步骤带 capture_due（尚无 runtime 证据的 UI 项与最近一次捕获的 manifest），卡片在存量可跑时带存量预览与存量捕获小节，领域工具表给 legacy-capture；未捕获的界面、未引用的用户截图/预期、未引用预期的 design 是 owed 欠项，声明矛盾、错引他人截图、媒体种类错误仍拒绝 |
| agent 导航的存量捕获 | legacy_preview 可带 navigator（adapter 的绝对命令）；目标的 navigation {mode: agent, steps} 交 navigator 以 snapshot 任务走到界面（query 绑定设备与 app），到达后仍按冻结选择器与稳定树捕获并在 meta 记导航回执；needs-review/blocked 记 navigation-unverified 并附引用回执的 capture_gap 建议；浏览器声明拒绝 agent 导航，缺 navigator 是环境缺口 |
| web 证据链 | 浏览器与 adb 设备共用一个观察器：按冻结 scroll_region 滚到 scroll_end_match，截图前后树稳定；analyze-ui platform=web 只读浏览器捕获，产出运行时索引与 DOM 派生的 UI 树（generatedFrom.platform=web、无源索引、每个 capture 一个 screen、节点 id 取元素 id 否则取路径、runtimeObservations 定位、imageSources 只记录）；web 树校验只绑运行时索引，拒绝带源索引、指向他索引或命名 DOM 未显示元素的树；冻结证据、adapter 与语义门禁接受 web 树 |
| 黄金路径 | Android→Harmony、Android→Android、web→Android 三条通道以假 adb/假页面端到端走通：存量捕获、候选装机与捕获、ALIGNED 结果、comparison_evidence、validate_alignment 的 capture 证明与 visual_results 裁决；adb 候选的 pull 与 screencap 计为原生捕获命令证据 |
| 宿主职责与探针 | 宿主接入列 legacy_preview 配置、adb/Playwright 可用、navigator 与 device_lock 的职责；sandbox doctor 探测 adb-on-path 与 playwright（缺省为 optional-absent，不阻塞）；经验库携带 legacy_preview，配置沉默时下次 prepare 取用；media-task-query、compare-only、render-reference、import-evidence 各有请求模板 |
| 用户参考媒体 | project context 的 reference_media（media_id/kind/path/role/screen/case_ids/note）经校验后由 prepare 复制并绑定 hash；持有其 CASE 的叶子在分配包读到并以之为就绪证据；visual_mode=user-reference 以用户截图为基线，用户展示过的界面不得 source-only，错引非该 CASE 截图被拒；visual PATH 的 baseline_ref 可为用户截图，冻结证据与 reference manifest 按其截图集合核对；reference_media_ids 只能引用本 CASE 的媒体；冻结时用户展示过的用户可见 CASE 无 PATH 引用即欠项（已声明设备缺口除外）；骨架为每张截图起稿 visual PATH、把录屏挂到功能 PATH；报告列媒体覆盖 |
| 目标预期 | role=target-expectation 覆盖的界面以其为基线（存量可预览时亦然；runtime 或存量截图作基线被拒），其 CASE 的存量截图不再欠引用；design 定义须引用其 media_id；报告媒体表列出被取代的存量截图，保真限制披露该界面按目标预期对齐 |
| 波次集成 | 持有某条 global path 用例的叶子全部完成且该路径无当前 Green 时，全局游标给 integration-assign（wave-complete）；独立 Test-Runner 以 GLOBAL 执行、integration-submit 提交，结果进 audit_results 并绑定各 owner 的 code_baseline，audit_scope 对 owner 代码未变的 Green 不重跑；Red 入 audit_repairs 由 owner MO repair-accept，同一代码上不重跑；证据漂移时不派发 | test_integration_wave |

## 包级核查

内部 Markdown 相对链接、JSON 模板可解析、Python AST、Skill frontmatter 与 `git diff --check` 另做结构检查；模板保留待实例化占位符，不把占位符当真实证据。

## 尚需宿主/项目集成验证

- 真实宿主的身份绑定、进程终止、每次写入的权限/fencing、自动任务派发与原生 session 恢复。
- 真实项目全量 diff/删除/rename 与任务归属、复杂断言适配、跨运行 flaky 识别、设备/网络环境证据。
- Gradle/KMP/native 其他配置、Hvigor 构建、设备安装与截图、外部 LLM 语义裁决质量。
- OpenSpec CLI 实际调用、主分支合并与归档。

本地运行入口、精确能力集与请求字段见 [local-runtime.md](skills/migration-protocol/references/local-runtime.md)。
