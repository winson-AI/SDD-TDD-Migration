# 验证记录

本文件只记录当前版本的验证方式、结果与边界；版本演进见 [README 版本记录](README.md#版本记录)。

## 运行方式

三套测试相互独立，均在临时目录中构造隔离的 legacy/target/run，不读取包内 `.env`、不连接真机或外部 LLM。使用 Python 3.11+（`foundation-verify` 需要 tomllib，视觉比较需要 Pillow，可直接用 Harmony sandbox 的解释器）；禁用字节码、pytest 插件自动加载与缓存，不安装依赖。

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

| 测试集 | 通过 |
| --- | ---: |
| migration-ledger/tests | 799 |
| migration-test/tests | 47 |
| runtime/harmony/tests | 128 |
| 合计 | **974** |

全部无失败、无跳过。适配器夹具仍有既有 engine.log ResourceWarning，不影响断言。系统 python3 低于 3.11 时改用 Harmony sandbox 的解释器，并让它能导入已安装的 pytest；不为此安装依赖。

## 已覆盖

| 范围 | 实际验证 |
| --- | --- |
| 编码前独立设计 | assign(mode=design) → submit（预检报告随提交登记，一个事件）→ MO accept(review_ref) 走原 Ledger；Spec plan/freeze 绑定同一规格、任务范围与预期 PATH/ASSERT；设计不能执行或带实际断言；缺预检、角色重叠、错身份/围栏、覆盖缺失、输入漂移均拒绝；撤销/失效回规划并保留历史，不改 CASE 质量或兄弟状态；prepare 固定的门禁不能关闭；plan 可只引用已接受设计，PATH/ASSERT、任务范围与 spec 定义由 Ledger 补全，携带且不一致的部分被拒，批准绑定补全后 plan 的摘要（freeze 游标的 approval_subject_sha256） |
| 行为契约与场景追溯 | GO/父 MO/子 MO 行为审阅按 scope/REQ/CASE 校验；共享能力按父子归属解析唯一执行 owner，跨模块集成 CASE 归消费者，无关模块证据漂移不阻塞当前模块；SPEC 每个 Scenario-ID 派生并冻结到 TASK/PATH/ASSERT，缺场景、重复 ID、过期索引和以构建替代行为断言均拒绝；scenario_index 与静态审查范围由 Ledger 从 SPEC 派生，plan 携带过期或不全的值被拒；叶子的 source_closure 即其行为审阅；复用目录的 provider owner 与行为审阅解析出的叶子 owner 不一致时拒绝 |
| 单测报告核验 | JUnit 核验本次 attempt 的测试 ID、计数、报告 hash 与执行身份；零执行、跳过、缺损、错选、过期、越界证据不为 Green，断言失败为 Red，进程信号中断为 Yellow；Gradle 追加 --rerun-tasks --no-build-cache |
| 日志与按需追溯 | 进程退出前可读双流日志，大输出不依赖内存缓冲；超时、取消、硬终止保留不完整标记，原终止/验收规则不变；capture 引用与身份在接受时复核；trace 只读已提交事件索引对应的归档，按 Scenario/TASK/PATH/ASSERT/测试 ID 过滤并分页、限字节，实时观察标为未验收，查询不取业务锁、不写文件；watchdog 可观察输出但不以此替代存活证明 |
| 包内文件漂移 | 嵌套的控制器/协议引用在文件变化后，凭本 run 已提交事件的路径与哈希读取同哈希归档；未提交或外来归档、缺损或被重定向的归档均拒绝；SPEC、源码、环境与顶层输入仍校验当前字节 |
| 真实工具探针 | 在一次性宿主 workspace 用 Gradle 7.6 + JDK 17 + JUnit4 实跑：通过与故意失败的用例分别识别为 Green/Red，JUnit 报告核验无缺口；KMP/native、装机与设备自动化未覆盖 |
| 冻结与理解门禁 | 未冻结编码、代码未接受即测试、批准 hash 不符、源码未决/目标可行性 unknown 均拒绝 |
| 变更 | Fixer 越权改 SPEC 拒绝；边界内任务修订可重新冻结；改变验收不能沿用批准 |
| 结果与复测 | 空/遗漏断言、伪装 Green、篡改原始报告拒绝；非 Green 复测需新 test_run_id/retest_of，代码变化拒收旧结果 |
| 真实闭环 | 子进程 Red → 诊断 → Fixer → 正式复测 → 模块 Green；本地修复一轮未过转 waiting-auditor；`local_fix_rounds` 额外轮次只给仍是 build 的失败，业务失败照常交 Auditor |
| 作者自检与会话 | 实现/修复结果缺 authoring_diagnostics、诊断无日志或版本敏感 API 无固定源码引用均拒收；本地修复游标指向原 Implementer 会话 |
| 静态规格闭合 | build 全绿后同一派发继续 static，再到 automation；passed 场景须给出另一目标文件中的调用位置（reached_from）；审查需覆盖全部冻结需求、引用目标文件中真实存在的符号、逐项判定假实现清单；反模式 present 为 Red 并进入修复；prepared run 必须冻结 static PATH |
| 阅读卡与协议体积 | 每个角色/阶段/操作/UI/复用/埋点组合的卡片引用真实小节、包含四条红线与三条通用总则且不超过 60KB；无触发条件的典型步骤卡片不超过 34KB、本步模板不超过 26KB；审计、GO 规划、MO 各操作取各自小节，技能只带执行规则，专题义务表按触发条件取行，操作矩阵只带当前操作的行；AGENTS.md 专题索引指向的每个“总则”都有卡片可达；协议、命令与模板索引总量不超过 543.2KB、单文件不超过 32KB；共享协议进卡时只带规则小节；游标步骤携带 must_read 与绑定小节正文的 card_sha256；任何角色、操作与触发组合的卡片里，链接只指向小节或模板，不出现整份协议文件；角色定义进卡时不带技能文件清单和只指向通用约定的小节；模块编排者未列出的操作只带状态模板 |
| 提示采纳与流程成本 | assign 回填的会话/阅读卡与建议比对并汇总为 hint_adoption；workflow_cost 按模块统计事件、派发、回执、验收、人工决定与修复轮次并进入收尾报告 |
| 单文件卡与增量交付 | `reading.py render` 以摘要命名写出单个卡片文件且幂等；`show` 只读包内 Markdown 单节并拒绝越界路径；会话已持有的小节不再进入 `must_read_new`，正文变化的小节重新交付；任意模块请求可带 `hint` 报告所用会话与卡片，匹配当前游标步骤才计入，格式不符被拒；流程成本统计每模块完整/实际交付的阅读卡字节；渲染后的卡片不含指向包内文件的链接（整份协议链接变纯文本、小节链接变“文件 § 小节”选择器），卡尾列出本步模板；Test-Runner 的角色定义按测试阶段取块；每步 `templates` 指向真实模板；会话累计持有的协议文本超过阈值时步骤带 `session_rotate` 建议 |
| 精简状态与拒绝提示 | `status --view cursor/module` 不含模块正文、卡片行清单与信号证据，卡片只给字节数与小节数（单模块夹具 13.7KB → 1.8KB）；`--since` 命中当前 sequence 时只返回 unchanged 与信号摘要（约 0.4KB），有新事件即返回完整游标；`--view step` 只给一个模块当前步骤所需：请求信封字段、本阶段预检要求（含必读引用）、分配包、当前 assignment 与待验收提交，规划类步骤和设计派发另带 planning_context，运行中的设计者得到自己阶段的要求，不含其他模块（已冻结叶子的派发步骤小于 module 视图的一半、full 视图的八分之一）；父模块汇总步骤同样带阅读卡与模板；CLI 输出为单行紧凑 JSON；未知模块或视图被拒；拒绝记录带 `read_hint`，每个提示指向真实小节 |
| 闭包提前审计 | 独立同伴运行中时，已交 Auditor 模块的闭包可先 problem-audit，且只锁闭包；消费者的其他依赖仍在运行时拒绝；最终全量审计仍等待全部收尾 |
| 轻量叶子与批量信封 | lean_leaf 登记需 scope/context/不可再拆审阅；本地轮由 Fixer 自诊断（`fixer_self_diagnosis` 对全部模块开启），未开启的普通模块拒绝；批量信封绑定文件 hash 与父的孩子，条目完全匹配且 MO 附 review_ref 才冻结 |
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
| 作者可省略的推导值 | test_design_ref、行为审阅的范围摘要与需求/CASE、任务四维分析的范围摘要与 parent_ref、global-plan 的规范与架构引用、PATH required、冻结与完成的勾选标志省略时由 Ledger 补全或按分配核对，写错被拒；plan 不含 global-contract 定义也能冻结 |
| 包内评审清单 | plan 自带 checklist 定义被拒；接受 plan 时 Ledger 把包内清单按内容哈希存入本 run 并绑定到模块，人工批准的 plan 摘要不变；投影替换模块号并附证据链接与 Ledger 勾选；重新规划时解除绑定 |
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
