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
| migration-ledger/tests | 1274 | 全量通过，零失败/错误/跳过；本轮新增 17 项 |
| migration-test/tests | 70 | 全量通过；本轮未改适配器 |
| runtime/harmony/tests | 128 | 全量通过；本轮未改运行内核 |

三套测试用 Harmony sandbox 的 Python 3.11+ 解释器经 pytest 执行（`PYTHONDONTWRITEBYTECODE=1`），零失败/错误/跳过。测试仅使用隔离临时目录、本地模拟端口和测试子进程。

新增 17 项验证：声明设备缺口的模块完成后为 Yellow 而其已执行路径（含 build）保持 Green，审计通过后全局游标以 completed-with-unverified-tests 收尾且不需要人，报告把该 CASE 与其 automation 记为 Yellow（一条未执行的应测设备路径，原因取缺口说明），阶段为带缺测结束；最小集计划（去掉四维分析引用、source_closure、target_feasibility、decision_envelope、各任务四维与 scenario_trace）在 prepared run 被接受并冻结，补全值取自已接受的四维分析与行为审阅，同一最小集文件重交不算新的规划轮次，作者自写的值被保留并照常判定（未就绪的可行性仍被拒），多任务计划按 dimension_trace 分给各任务，没有四维分析或绑定了别的分析时不补全；经验库无切分内容时不生成技能，多个 run 的同一抽象教训合并并排在前，往次切分形态与未抽象观察照录，内容不变则修订号不变、有新教训才升版，发生过拆分的 run 采集后经验库出现技能，prepare 把技能固化进下一 Run，游标只在 GO/MO 的切分步骤给出它，切分阶段之外的必读输入不含它。

协议体积为 538996 / 539000 字节，最大单文件 31702 / 32000 字节。504 个全专题触发的阅读组合中最大卡片 56267 / 60000 字节，最大模板组合 52847 / 56200 字节；拒绝消息带小节指引的比例 83.4%（棘轮 80%）；未放宽门禁。源码语法、JSON、引用与 `git diff --check` 通过。

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
| 阅读卡与协议体积 | 每个角色/阶段/操作/UI/复用/埋点组合的卡片引用真实小节、包含四条红线与三条通用总则且不超过 60KB；无触发条件的典型步骤卡片不超过 34KB、本步模板不超过 20KB；审计、GO 规划、MO 各操作取各自小节，技能只带执行规则，专题义务表按触发条件取行，操作矩阵只带当前操作的行；AGENTS.md 专题索引指向的每个“总则”都有卡片可达；协议、命令与模板索引总量不超过 539000 字节、单文件不超过 32KB，任何步骤在触发条件全部成立时携带的模板总量不超过 56.2KB；共享协议进卡时只带规则小节；游标步骤携带 must_read 与绑定小节正文的 card_sha256；任何角色、操作与触发组合的卡片里，链接只指向小节或模板，不出现整份协议文件；角色定义进卡时不带技能文件清单和只指向通用约定的小节；模块编排者未列出的操作只带状态模板 |
| 提示采纳与流程成本 | assign 回填的会话/阅读卡与建议比对并汇总为 hint_adoption；workflow_cost 按模块统计事件、派发、回执、验收、人工决定与修复轮次并进入收尾报告 |
| 单文件卡与增量交付 | `reading.py render` 以摘要命名写出单个卡片文件且幂等；`show` 只读包内 Markdown 单节并拒绝越界路径；会话已持有的小节不再进入 `must_read_new`，正文变化的小节重新交付；任意模块请求可带 `hint` 报告所用会话与卡片，匹配当前游标步骤才计入，格式不符被拒；流程成本统计每模块完整/实际交付的阅读卡字节；渲染后的卡片不含指向包内文件的链接（整份协议链接变纯文本、小节链接变“文件 § 小节”选择器），卡尾列出本步模板；Test-Runner 的角色定义按测试阶段取块；每步 `templates` 指向真实模板；会话累计持有的协议文本超过阈值时步骤带 `session_rotate` 建议 |
| 精简状态与拒绝提示 | `status --view cursor/module` 不含模块正文、卡片行清单与信号证据，卡片只给字节数与小节数（单模块夹具 13.7KB → 1.8KB）；`--since` 命中当前 sequence 时只返回 unchanged 与信号摘要（约 0.4KB），有新事件即返回完整游标；`--view step` 只给一个模块当前步骤所需：请求信封字段、本阶段预检要求（含必读引用）、分配包、当前 assignment 与待验收提交，规划类步骤和设计派发另带 planning_context，运行中的设计者得到自己阶段的要求，不含其他模块（已冻结叶子的派发步骤小于 module 视图的一半、full 视图的八分之一）；父模块汇总步骤同样带阅读卡与模板；CLI 输出为单行紧凑 JSON；未知模块或视图被拒；拒绝记录带 `read_hint`，每个提示指向真实小节 |
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
| 事件日志与状态 | 首个事件记录初始状态，其后每个事件只记录变化；写入前校验补丁能还原已提交状态，重放结果与投影的全局状态一致；模块事件不重写兄弟模块或未变的计划；嵌套删除可重放；整键写法的事件仍可重放并可在其上续写；重放不改写已读事件；每个事件只列出此前未归档的工件，漂移与历史快照记录照常保留，累计索引仍能找到被多次引用的工件；状态只保存预检报告、提交结果与设计输入的哈希引用，验收时重读文件，被改动即拒收 |
| 预检随操作与机械步骤 | 执行者自己的预检报告随 plan/register/global-plan/decompose 等操作登记，他人的报告或跨角色阶段未先提交即拒绝；全绿测试结果的 accept 游标带 mechanical，代码结果与非全绿结果不带；执行派发（Implementer/Test-Runner/Fixer）在可派发时带 mechanical 与载荷（已有预检时含该实例及其报告），照此提交仍过全部派发守卫；设计派发与仍被 blocked 报告挡住的派发不带；`ledger.py advance` 以 MO 身份依次提交一个模块的全部机械步骤（默认实例 `<role>-<module>`，可指定），停在需要模型或人的步骤并写出其阅读卡，非 MO 身份或未知模块被拒；等待人工决定的步骤（冻结、恢复、审计放行、审计处置）都给出要绑定的 approval_subject_sha256 |
| 派发后预检 | 执行派发不等预检：worker 派发后 context-submit，ready 报告绑定派发并授权开工（Fixer 此时才计一轮），其他实例的报告不绑定；未绑定时提交结果与执行测试都被拒；blocked 报告退回派发、不耗轮次，游标 reason=context-blocked，该实例仍 blocked 时再派发被拒；仅自动化环境缺失时退回后走 automation-unavailable；派发前已有的当前 ready 报告在派发时直接绑定；诊断接受可带派发，被挡时整体回滚；证据漂移时 ready 报告无法提交，工作不被授权；模拟中绿色叶子每个执行阶段只启动一次 worker，模型调用 16 → 10 次（编排者 5、worker 5），事件数不变 |
| 上下文绑定 | 行为契约由运行状态写入 plan，作者可不声明、不能声明为 false；plan 与拆分提案不抄写全局上下文和分配包，Ledger 接受时在 plan 之外保存两者的摘要；全局上下文变化后冻结、派发与接受拆分被拒；来源追加时未受影响的模块沿用冻结 plan；设计输入引用游标给出的摘要，缺失或过期被拒 |
| 接受即定规 | 已登记的四维分析与行为审阅、已验收的设计、已登记的计划在之后各步只读取：其后写入的规则不重判它们，所引文件漂移仍拒收；叶子首次冻结后，冻结门禁不再重判同一份分配；与当前规则的差异列入报告的规则欠账，不作门禁 |
| 切片独立性 | 拆分写明每条 CASE 的唯一验收切片并记入切片；不验收任何 CASE 的切片须有支撑理由；三段依赖链或过半切片等待须有理由和证据；切片与根不得验收别处已验收的 CASE；再拆分移动验收时两侧重规划；报告列出各拆分的切片形态 |
| 上游修订分流 | 再拆分与 run 修订改到的已冻结叶子：边界保持的以 CR 接收并保留 plan、冻结记录与代码，其消费者只等 provider；边界改写、收缩、新增排除或依赖变化的整叶重规划；只更新证据的再拆分保留全局规划；独立性证明可声明无 TASK 受影响，全部 TASK 保留且已有代码时重冻直接进入重建复测 |
| 搬运约定定论 | prepared run 登记 UI/Resource 适用的分配前 copy 与 parameters 须已声明或带原因拒收；已登记的分析不重判；有叶子或尚无根的 run 均可经修订写入；约定已声明时可原样加载的文件必须走复制清单；计划中手工替换图片须写明不能复制的原因，报告随图披露并列出项目拒收的部分 |
| API 路由 | 调用与目标按 transport 登记：http 记 method/URL，rpc/sdk 记调用名；exact 契约保持 transport 与路由，义务与覆盖不变 |
| 用户路径 | prepared run 中叶子验收的用户可见 CASE 须有设备或视觉 PATH，或带原因与证据的缺口声明；只约束验收该 CASE 的叶子；有缺口的模块完成后为 Yellow、已执行路径保持 Green，该 CASE 与其 automation 在报告中为 Yellow，本轮以 completed-with-unverified-tests 收尾；统计按宿主任务/模块/TASK 分列设备、进程内、视觉路径的成功与应测及缺口 CASE |
| 叶子最小集 | 叶子有已登记的四维分析时，计划可只含六件套、tasks、测试计划引用与 dimension_trace；其余由 Ledger 据已接受的四维分析与行为审阅补全后存储冻结，作者自写的值保留并照常判定；同一文件重交补全结果相同 |
| 切分技能 | 采集时由经验库生成：合并各 run 的抽象切分/边界/规划教训、往次切分形态与未抽象观察，内容变才升版；prepare 固化进下一 Run；游标只在 GO/MO 的切分步骤给出，且只是切分阶段的必读输入 |
| 运行记忆 | 阻塞与解除依据、一次冻结三次以上改交计划、达三次的同因拒绝进入本 Run 经验与采集；拒绝仍在日志之外；共享经验库按 `<project_id>/<run_id>` 分块，prepare 读取项目指定的库 |
| 人工与成本可见 | 游标每一步给出是否需要人；人工决定被使用时记下用途，报告按用途列出并附解除阻塞的原因；报告列出各叶子的规划文件数、字节与 CASE/TASK 数 |
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

## 包级核查

内部 Markdown 相对链接、JSON 模板可解析、Python AST、Skill frontmatter 与 `git diff --check` 另做结构检查；模板保留待实例化占位符，不把占位符当真实证据。

## 尚需宿主/项目集成验证

- 真实宿主的身份绑定、进程终止、每次写入的权限/fencing、自动任务派发与原生 session 恢复。
- 真实项目全量 diff/删除/rename 与任务归属、复杂断言适配、跨运行 flaky 识别、设备/网络环境证据。
- Gradle/KMP/native 其他配置、Hvigor 构建、设备安装与截图、外部 LLM 语义裁决质量。
- OpenSpec CLI 实际调用、主分支合并与归档。

本地运行入口、精确能力集与请求字段见 [local-runtime.md](skills/migration-protocol/references/local-runtime.md)。
