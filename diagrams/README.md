# 迁移流程图

图集与当前控制器及角色契约一致：GO/父 MO 切 scope/全量 CASE，子 MO 拆 TASK，SPEC 明确后冻结执行；执行反馈按实现错误、规划缺口、范围不足分流。同一 Run 仅执行当前冻结 SPEC，规划调整保留 history。先看总览，再展开模块执行、统一 Auditor、复用或自动化；SVG 入库，可放大，PNG 仅在本地生成。

Test-Runner 的预检与静态审查从 Ledger 骨架起笔，冻结同一命令的 unit PATH 一次执行、逐 PATH 归因；按顺序执行：build → unit → static（同一派发）→ 功能自动化（设备 PATH 由内置 Harmony Main、web PATH 由内置 web Main 执行，适配器随 PATH 平台选取，预检命令由 Ledger 预填）→ 基线视觉对齐（存量在声明的设备 / 浏览器上被包内捕获、或用户给了截图 / 目标预期时；逐节点对齐，不对齐即 Red + 节点级根因走既有诊断/修复）。存量基线来源随 legacy_preview 声明，冻结前前移为 SPEC/coding 的输入。仅自动化环境缺失时保留 Yellow/未执行，其他可执行任务继续，本轮可以带缺测清单收尾；这不等于功能验收通过。详细门禁见 [构建与自动化协议](../skills/migration-protocol/references/build-automation.md)。

| 图 | 关注点 | SVG |
| --- | --- | --- |
| 01 · 三层编排总览 | 用户输入含参考截图 / 录屏，init 前一次问完五条声明（存量怎样跑、目标在哪预览、资源怎样进目标、迁移范围、依赖授权），prepare 固化快照与存量提交；GO 先记目标画像（无 / 壳 / 部分 / 已有，target-scan 给候选），再按功能树切 scope/全量 CASE；叶子是子业务流（`split_draft.py` 从功能清单起草切分，不足 6 条 CASE 不拆，横切功能随主流程叶子；子四维分析与行为评审由 Ledger 切出；首次切分可不全覆盖，漏掉的记为父的欠项、孩子首版收尾后补齐）；与 Ledger 起草一致的拆分当场接受，全局覆盖交给孩子并重验沿用，手改的拆分才由 GO 审核；子 MO 拆 TASK，依赖方与提供方并行规划；Ledger 代填已有事实、被拒列全问题；worker 只读阅读卡，机械步骤由 advance 提交；宿主停了由 handover 接手，run revision 可改钉新版本包；并行执行与统一宿主审计 | [总览](workflow.svg) |
| 02 · 子 MO 执行与反馈调整 | TASK/四维 → 存量可跑先按 capture_due 捕获、按 media_due 引用用户媒体 → SPEC、测试源与用户截图的 visual PATH 从骨架起笔（每条 CASE 一个预填场景，可后补项记 debt，首版限时 45 分钟，拿不准的库写成 spike 任务）、起步门禁冻结（门禁全过且无人提问时 Ledger 记评审即冻结，MO 只在被要求时评审；完整性缺口记欠项、DoD 前结清；测试源须能失败；目标已有代码须复用或说明，未捕获 / 未引用是欠项）→ Implementer（冻结测试原样交付、可在写范围外，自查红→绿留证，编译通过即机械接受）/Testing（构建只跑 PATH 平台；命令全冻结或适配器已声明的派发由 advance 代跑，静态审查在 build/unit 通过后单独派发，Green 或确定 Red 机械验收）；命令只交回退出码与报错定位，写范围内的构建失败与本模块断言失败由 Ledger 诊断并直派 Fixer 自行定位；Fixer/CR（测试源缺陷与只改测试写法均走 CR）/上溯三分流，环境与目标基线缺陷审计延期；DoD 守卫通过即机械完成；独立性证明与默认全模块重验 | [子 MO](module-execution.svg) |
| 03 · 统一 Auditor 宿主审计 | 全宿主目标/代码治理（清单与审查从骨架起笔，预列 debt）、遗留路由、影响模块完整回归、独立 Test-Runner 与 Auditor 裁决；波次集成已跑的路径只在 owner 代码变动时重跑；空清单由 Ledger 预检 | [Auditor](auditor-closure.svg) |
| 04 · 二方库语义与复用 | 来源评审 → 语义抽取 → 四类复用决策 → API 与数据契约 → 冻结 → Coding → 真实依赖验证；提供方证据变化后的恢复 | [二方库](reuse-dependencies.svg) |
| 05 · Automation 外层闭环 | 冻结用例与测试源（须能失败）、构建只跑 PATH 平台、派发后预检（骨架起笔）、声明平台未写适配器即用内置 Main、进程内 JUnit 或设备 / 脚本逐 PATH 证据、三类反馈及成功/复用统计；缺测旁路；global path 在持有叶子完成时即执行（波次集成）；PATH 可录屏，媒体随结果入 Ledger | [自动化](automation-flow.svg) |
| 06 · Android/Harmony 单 PATH 内核 | Planner / Executor / Verify、录制回放、媒体断言、观察落盘与三态汇总；snapshot / recording 媒体任务只留媒体不判定 | [内核](automation-engine.svg) |

自动化输入输出的字段、JSON 示例、调用方法和当前实现边界见 [自动化测试说明](automation-input-output.md)。

## 阅读约定

- 总览以 project 的多个父模块举例；single-module 只保留选定根模块及其父 MO，原子能力可直接作叶子，其余子功能由独立子 MO 执行。
- 用户给了测试用例时，用例分组是功能树的节点、用例范围界定叶子；没给时先深读存量源码建完整功能树，再按功能派生 CASE，切片与用例来自同一份清单。叶子是功能树上的子业务流（页面是 TASK，3–30 条 CASE），自带四维分析与实现 SPEC；两种方式都要对照源码查漏，任何疑问立即人工介入；功能清单与逐模块归属通过 global-plan 门禁。
- GO 在目标已有能力与指定外部来源中提取语义目录，结合模块需求形成复用与缺口任务；父/子 MO 逐层细化，验证真实接线与行为等价。
- 先评审来源与接入可行性，再选择 reuse / adapt / reference / new，并将映射与 SPEC 一起冻结。声明来源不可用是阻塞，不能视作“已评审但无匹配”而直接新实现。
- 选中提供方或接入证据变化时，相关计划与旧测试证据失效；受影响消费者经影响分析、CR/重规划、重新冻结和正式复测恢复，无关模块继续。外部源码默认只读，无修改授权的问题走人工路由。
- GO 分配根模块范围和所需上下文，父 MO 在认领范围内继续分配子范围和上下文，子 MO 基于子范围拆 tasks。上游全量 CASE 在冻结前按 scope 分配，SPEC 明确即可执行；独立 design 按需。automation 发现规划遗漏/fidelity 规划不足时局部更新 SPEC、再冻结并更新已有代码及正式复测。父子均保留全局代码、架构、知识的读取视野。
- 非 Green 在派修复前按现有诊断分流：实现错误 → Fixer；scope 内规划/功能/依赖契约缺口 → CR → Spec-Designer 修订 → MO 重冻 → Implementer 更新代码；超 scope → 父 MO/GO 修正分配，再 top-down 更新。已有提供方暂不可用沿等待/恢复，不混作契约缺失。
- CR 默认全模块重验；可选 MO TASK 独立性证明通过才保留未影响 TASK/Green。新代码始终重跑 build/unit/static，automation/visual 重跑受影响及非 Green 路径。保留成功证据记录 validation_reuse，原回执不变、单列统计，不计作本次新执行；独立性证明不免除统一审计。
- 箭头表示经 Ledger 的交接或控制关系，不表示 Agent 私聊。宿主实际启动/恢复实例、绑定模块、加载 Used Skills；分配包不自行产生执行权限。
- 子 MO 独立运行。父 MO 持续看护范围、覆盖、复用与依赖，并等待全部孩子收尾；一个 Red/Yellow 不结束无关模块。
- 本轮收尾允许基于自身证据明确挂起，但不能将排队、写锁等待或 worker 退出视为已收尾。全部子 MO 收尾、父汇总有效、无在途 worker 与可推进动作后，GO 才统一启动 Auditor。
- 图 03 是统一宿主审计：全部模块（含 Green）先做代码治理；实际复测按遗留/影响范围选择，清单为空只做独立证据审阅，不启动测试；依赖图决定具体修复与验证顺序，不能把图中的角色列表理解为强制先后顺序。
- 清晰且可执行的规划由 MO 审核冻结，独立 design 按需；Green 不需新增人工会签。真实未决或需求/验收/授权变化、适用的人工恢复与交付授权才交 Human。SPEC 修改、依赖恢复或人工批准均不能直接将测试改成 Green。
- 上下文预检已进入 GO 发现/覆盖规划、父拆分、子 SPEC 冻结、Coding/Testing/Fixer 派发及 Auditor 分析/裁决/最终测试。规划与审计者的报告由原节点验收；worker 接到派发后提交 `context-submit`，ready 报告授权开工、blocked 报告退回派发；coding 与无待复测的审计由 Ledger 机械预检，building/testing 从 Ledger 骨架起笔；缺项或过期阻止相关阶段，不消耗修复预算、不提前收尾。
- run 固定 prepare 时的包提交；运行产物不设体量上限，棘轮只约束包自身；automation 统计里 TASK 行的缺路径只计模块整体缺的 CASE。
- 正式目标代码测试在代码被接受之后派发；作者对任务的 unit PATH 自查两次（实现前失败、实现后通过），两份记录是该任务的 red 证据，报告按任务计数、不设门禁；已知技术债登 kind=debt 的 issue，审计骨架预列。
- 波次集成：持有某条 global path 用例的叶子全部完成、别的叶子还在做时，GO 派独立 Test-Runner 执行它；结果绑定各 owner 的代码基线，统一审计只重跑 owner 代码变动的路径，Red 路由给 owner 叶子修复。
- 项目理解：GO 在全局发现记目标画像（absent / shell-only / partial / existing，只读 target-scan 给候选证据），脚手架只在缺外壳处，持有代码的叶子冻结时欠复用说明；项目知识文档（文件或 wiki 目录）可按 project 模式检索，缺的专业 / 接口知识登 knowledge-need，由人以 kind=knowledge 决定补充并写成本 run 文档，答复随经验库沉淀到下次 run；用户给的存量截图 / 录屏随项目上下文固化、按 CASE 下发到持有叶子：截图作 user-reference 视觉基线（存量不可预览也有基线）、录屏作功能 PATH 的交互预期、规划步骤列尚未引用的媒体（media_due）、未被 PATH 引用即欠项，诊断/修复并列预期与实际媒体；目标预期（target-expectation）取代存量基线，design 须引用，报告披露。
- 存量预览与媒体取证：项目声明存量怎样跑（设备 / 模拟器 / 虚拟机 / 浏览器 / 不能跑），可执行性随声明，存量可跑却未捕获的界面写 capture_gap；legacy-capture 在包内装机、走冻结动作把界面写成参考记录（adb 或 Playwright，走不成确定性动作的界面由声明的 navigator 以 snapshot 任务走到后再按选择器捕获），浏览器按同一滚动契约捕获（整页滚动以 body 为区域，shadow DOM 与同源 iframe 并入树，点击/滚动后等页面稳定，声明可带 viewport）、web / 鸿蒙存量的 UI 树从运行时索引派生且无源索引，Android 目标装 APK 走同一视觉对齐；hdc / adb / 浏览器共用一个屏幕观察器（前台核对、选择器、滚动契约、稳定树），Harmony 候选也经它捕获；目标在浏览器里预览时不装机，宿主部署已接受构建并让页面声明其哈希，候选记为 web-candidate 进入同一对齐链路；存量怎样跑、目标在哪验证是只有用户能给的声明，init / update / prepare 返回待问的 open_statements，status 持续提示到声明为止；规划步骤带 capture_due，未捕获的界面是首版携带的欠项；内置运行时的 snapshot / recording 只留媒体不判定；测试结果带截图 / 录屏引用，报告逐 PATH 列出，diagnose/Fixer 带非 Green 路径的媒体。
- 照抄的判断交给 Ledger：登记已说明的全局覆盖由 Ledger 起草；没有复测项且代码审查无发现时审计结论取自该审查；drive.py 的派发行带实例与可接续会话，接续时只给未读小节。
- 判断只留给需要判断的地方：无人提问的计划由 Ledger 评审并冻结；`drive.py` 推进全部机械步，宿主只读待派 / 运行中 / 待人工各一行；Auditor 派发与适配器驱动的波次集成机械完成；计划卡只带作者要写的内容；全流程演练按角色报告模型轮次。
- 模型只做需要判断的事：命令经 run_command 执行，只交回退出码与从日志 grep 出的报错定位，日志按需 grep；写范围内的构建失败由 Ledger 写诊断、直派 Fixer，定位是 Fixer 的输入；确认的诊断转 Fixer、依赖放行与恢复、审计延期、缺测收尾机械提交；声明了适配器的自动化由 advance 代跑；限制的是加载进模型的内容而非协议文件体量。
- 叶子少走模型轮次：作者编译通过的实现、Green 或确定 Red 的测试结果由 advance 机械接受，确定 Red 直接进诊断；build、unit 与进程内功能测试的命令在冻结时已定，这类派发由 Ledger 机械预检、advance 以 worker 名义执行并提交；静态审查、设备与视觉仍由 Test-Runner 执行；演练测试把每叶模型轮次卡成棘轮。
- 父层只确认切在哪里，首版先跑：父 MO 只确认切分边界，子模块材料由 Ledger 切出；首次切分漏掉的用例、需求、四维工作和功能不阻塞孩子，在孩子首版收尾、父汇总前补齐；规划期的完整性类检查（缺 PATH 的已分配 CASE、契约与资源的理由和证据、行为评审文字等）记欠项，结构、身份、越界和事实不符仍拒绝。
- 让 run 动起来、停了能接上：首版计划限时，超时 planning-overdue 并列出规划期建的工程；`watchdog.py schedule` 给出由人安装的定时检查，宿主停了能被发现，`ledger.py handover` 写出新宿主接手说明；run revision 带 package_sha 经人工决定改钉，正在跑的 run 用上新规则而不重开。
- 减少拒绝与往返：手续问题（hint 不全、提交者预检、issue 地址、过期修订号）不拒绝请求；分配范围、排除项、用例摘要、叶子功能行由 Ledger 代填；被拒响应带 `further` 列出同一请求其余问题，任意请求可先 `preview --request`；存量按 prepare 时的提交冻结，run 内存量变化不再逐个哈希拒绝，而是发信号提示走 run-review；watchdog 在 Ledger 久无事件时区分 staging 仍在动（ledger-quiet-staging-moving）与宿主空闲（host-idle）。
- 测试代码是冻结资产：Logic 条目的单测与无设备 CASE 的进程内功能测试（<Case>FlowTest，按冻结命令跑 JUnit、逐断言归因）由 Ledger 起稿骨架、Spec-Designer 从 SPEC 写出、随计划冻结；Implementer 原样交付，改测试走 CR。有设备且绑定 UI 树的 CASE 起稿设备脚本（选择器取节点 id），报告分列脚本驱动的设备路径及其 flaky。

## 依据与再生成

以 [三层作用域协议](../skills/migration-protocol/references/module-decomposition.md)、[状态机](../skills/migration-protocol/references/state-machine.md)、[上下文就绪协议](../skills/migration-protocol/references/context-readiness.md)、[项目上下文](../skills/migration-protocol/references/project-context.md)、[视觉执行](../skills/migration-protocol/references/visual-execution.md)、[二方库复用协议](../skills/migration-protocol/references/reuse-dependencies.md)、[本地运行契约](../skills/migration-protocol/references/local-runtime.md) 为准。

源文件为 [generate_workflows.py](generate_workflows.py)。在包目录执行：

```sh
python3 diagrams/generate_workflows.py
```

需要 Python 3 与 `rsvg-convert`；生成四个 SVG，并在本地渲染宽 1920px 的 PNG（不入库）。修改布局后查看 PNG，核对箭头端点、文字和业务分支。

图 05/06 单独生成，复用同一绘图组件：

```sh
python3 diagrams/generate_automation.py
```

Auditor 遍历所有模块以收集 Red/Yellow，但不会全量重跑测试。global_paths 可为空；范围与空清单报告遵守 [审计范围协议](../skills/migration-protocol/references/audit-scope.md)。
