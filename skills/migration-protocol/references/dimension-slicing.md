# UI → Logic → Adhesive → Resource 完整性协议

## 1. 范围与方法

**先划分范围，再做该范围的四维分析；划分决定负责什么，四维分析直接指导如何实现。** 三层固定顺序：

- GO：全局上下文/完整功能清单 → 划分模块及 scope → 针对每个已划分模块做四维分析 → 模块 SPEC 草案/Testing list/交接包。
- 父 MO：认领模块 → 读取该模块存量/目标已有实现、模块四维分析及全局上下文 → 划分子模块及 scope → 针对每个已划分子模块做四维分析 → 子模块交接包。
- 子 MO：认领子模块 → 读取该子模块存量/目标已有实现、子模块四维分析及全局上下文 → 划分任务及 scope → 针对每个已划分任务做四维分析 → 冻结实现计划 → Coding/Testing。

这里的“实现上下文”是现有源码、目标能力及已批准设计，不要求迁移代码在规划前已生成。每一级的四维分析均按 UI → Logic → Adhesive → Resource 顺序进行；任务执行顺序仍按真实依赖决定。分析发现范围缺口时回到负责该范围的编排层调整，再重做受影响分析；不得用分析结论静默扩大职责或遗漏功能。

逐维度交叉读取四类依据：存量源码及行为、新架构规范、二方库语义/精确版本、目标已有能力。目标已有能力包括真实生产实现与测试/demo/mock 的区别，不能因同名接口或现有库测试通过就假定迁移完成。知识资料与全局分工仍按 planning_context 读取，局部 context pack 不截断全局视野。

此方法参考 android-to-kmp 的 source closure、source-backed UI tree、production chain 与 resource consumer mapping；不导入其专用平台目录、代理架构或 fixture 放宽规则。

## 2. 四维检查内容

| 顺序 | 分析范围（仅列实际存在的内容） | 闭合依据 |
| --- | --- | --- |
| UI | 入口、页面/组件树、列表 renderer、自定义视图、弹窗/菜单、初始/条件可见性、loading/empty/error/content 等状态、事件、导航/返回 | 源码布局与实际绑定/动态修改代码，稳定节点/事件 ID → 状态/行为；UI tree 工件通过 evidence_refs 引用，不能用控件清单代替树与事件关系 |
| Logic | 事件→状态转换→业务规则→repository/API/DAO→可观察结果；解析/映射、持久化、错误/重试/分页、取消及生命周期 | 真实调用链、输入输出/副作用/失败语义；需求与 CASE/PATH/ASSERT 对齐；瞬态行为有源码依据即保留 |
| Adhesive | 生产入口接线、路由参数/返回、DI/工厂、模块接口、共享与平台边界、回调/生命周期、权限、构建依赖、宿主/桥接及打包连接 | UI/事件→状态→领域/数据→真实提供方闭合；明确已有接线复用/修复/新增及唯一 owner，不以接口声明、编译通过或启动成功代替真实绑定 |
| Resource | 字符串/复数/占位符/本地化、图标图片字体、色彩尺寸样式主题/selector、raw/config、qualifier 与资源打包/生成访问器 | 源资源→目标真实文件/访问器→生产消费者。遍历在范围内的传递资源引用和代码动态修改；不无界扫描全部未使用主题 |

Resource 指应用资源；原 Dependencies / Resources 中的文件锁、设备等调度资源仍单独管理。资源迁移保留精确语义/素材、单位/font scaling、locale/theme/density/状态变体，不用无关图标、emoji 或近似样式替代。目标已有等价资源优先复用，差异须记录适配与验证；不覆盖无关现有资产。

## 3. 条件适用与证据

模块/子模块 `dimension-analysis.json.scope` 必须精确绑定已划分的 scope，然后填写严格有序的四行：

- `applicable`：非空 items；每项有稳定 item_id、行为、源定位、requirement_ids/case_ids、target_strategy（reuse/adapt/reference/new）、生产 target_binding、acceptance 和 evidence_refs。
- `not-applicable`：明确 reason + 实际检查证据，items=[]。例如纯解析器可无 UI/Resource；不能因为尚未实现、环境缺失或准备复用就写 N/A。
- 未知/未读到的维度在草稿标 unresolved，并列待回答问题；接受分配/冻结前必须查明。无法由源码确认或跨业务边界时经 Ledger/Escalation 请求人工，明确挂起受影响模块，无关 MO 继续。

四类 source_reviews 均记录 conclusion 和引用；无二方库/无目标候选也记录实际搜索范围和结果，TARGET 仍需评估。Resource item 另有 source_resource、target_resource、consumer、conversion、qualifiers。定位可带 #symbol，证据引用必须指真实文件及 sha256；文件未生成时规划记录预期定位，实现阶段才验证实物。

证据用本轮不可变快照/分析工件，包含原始文件路径、符号、版本与必要内容；不能对即将修改的目标工作文件直接绑定规划 hash，随后又绕过失效检查。快照只证明分析时基线，正式代码/测试基线仍由现有 Ledger 校验。复用实际接入及源码 fidelity 继续受 reuse_plan_ref 约束。

## 4. 控制节点与交接

1. **GO / register**：全局上下文/完整功能清单 → 划分模块 scope → 对每个模块做四维源闭包/目标映射 → SPEC 草案、Testing list。每个根模块提交 `dimension_analysis_ref`（path+sha256），由 Ledger 接受与归档。GO 草案包含四维行为与边界；正式六件套仍由 Spec-Designer 撰写，GO 不替 MO 冻结。输入源缺项先澄清，不把空模板当完成。
2. **父 MO / decompose → GO / decompose-accept**：认领模块，读取模块实现、根四维分析及全局上下文 → 划分子功能 scope → 为每个已划分子功能生成四维分析，`parent_ref` 精确指向根分析；子 item 的 `parent_item_ids` 关联同维度父 item。所有父 item 必须被子项覆盖，子项需求/用例不得超出对应父项。父项可细分给多个孩子，但子 item_id 全局唯一，`dimension_partition_review_ref` 解释分割依据、职责不重叠及共享提供方/消费者/唯一写 owner；共享修改采用既有依赖、写范围/锁及人工边界决策，不复制实现。新增未分配功能须回 GO，不能偷偷扩 scope。
3. **GO / global-plan**：核验完整 registry 的四维分配和引用仍有效，并结合 feature-inventory、需求/CASE owners 与边界裁决接受全局覆盖。全局 planning_context.dimension_allocations 对父子均可读；权威 assigned_module 包含本模块及父级分析引用。
4. **子 MO + Spec-Designer / plan → freeze**：认领子模块并读取其实现、四维分析与上下文 → 划分具体 tasks.scope → 对每个任务生成 tasks[].dimension_analysis，明确四维如何影响代码/接线/资源与测试；发现上游遗漏先请求父/GO 调整，不能把适用项改 N/A。stage-plan.dimension_analysis_ref 必须等于认领引用，dimension_trace 完整覆盖所有 item，关联 TASK/PATH/ASSERT；每个 task 有维度归属、全部分配 CASE 有行为测试路径，构建不能代替行为断言。跨维度任务允许，避免为四维制造空任务。design/spec/tasks 保留 item ID；MO 在冻结检查审阅文本与机器索引语义一致性。
5. **Implementer/Fixer / submit → MO accept**：按冻结任务 scope 及任务四维 implementation 指导交付；task_trace 的文件必须位于对应 task.scope.write_paths，不能仅凭处于模块范围内就跨任务修改。implementation.dimension_evidence 按 item 列 task_ids、summary、evidence_refs；Resource 再提交真实 target_resource_ref、consumer_ref（文件 hash，可为未修改的复用文件）。这证明实现/接线有依据，不代表测试已通过。已接受的维度证据及资源/消费者引用在后续测试、DoD 和状态读取继续核验；即使复用文件未出现在本模块改动列表，其证据失效也不能沿用 Green。
6. **Test-Runner → MO DoD → 父汇总 → Auditor**：继续先 build、装机、automation，测试执行使用已冻结路径/断言而非从实现临时降低标准。DoD 检查四维追溯的完整实现与正式测试证据；父 MO 汇总全体子 item 覆盖及遗留。Auditor 仍等全体 MO 收尾，仅复核遗留/受影响范围，读取其四维依据定位遗漏、接线或资源缺陷。自动化环境不可用仍 Yellow 缺测，不阻断无关任务，也不宣称 fidelity 通过。

## 5. OpenSpec 与运行兼容

`dimension_analysis_ref`、`dimension_trace`、`tasks[].scope` 和 `tasks[].dimension_analysis` 一起纳入 stage-plan 摘要和冻结；design 解释逐维差异、复用与接线，spec 给出应保留的可观察行为，tasks 给出实现/验证责任，checklist 验收覆盖。Ledger 将模块分析、任务 scope/四维分析及追溯物化为 `change/dimensions.md`，它是六件套的辅助索引，不是第二份可修改需求或状态源。登记后分配引用不可就地覆盖；范围/分配发现错误须保留旧运行证据并重新规划新 run，既有叶子 tasks 调整按 CR 与重新冻结。

新 Ledger init 默认 `dimension_slicing_required=true`；project-context prepare 固化开启且不允许关闭。历史 run 缺少该字段保持原合同；直接 init 显式 false 仅用于旧格式兼容/隔离测试，不能用于宣称满足本协议的新迁移。即使旧 run 提交了分析引用，该引用及相关门禁仍会校验。

脚本验证顺序、N/A 证据、hash、父子覆盖、TASK/PATH/ASSERT 追溯及实现证据；**无法自动证明 Agent 已读完源码或每项业务语义完整**。GO、父 MO、Spec-Designer/子 MO 的源码审阅和正式 Main 测试必须真实执行，不能用结构通过代替语义验收。

## 6. 简例：搜索子功能

GO 先从功能清单划定“搜索”模块 scope，再在 UI 记录搜索框/结果与错误态，Logic 记录过滤/分页/重试，Adhesive 记录路由/DI/repository 接线，Resource 记录文案/图标/主题。父 MO 认领后基于搜索实现与四维上下文，先拆成“提交查询”“结果分页”等子模块，再分别分析它们的四维实现要求，公共 SearchRepository 只有一个实现 owner，其余声明消费者依赖。

若另一个子功能只是无界面的查询参数解析器，UI 可 N/A，Logic 记录解析/失败语义，Adhesive 按是否负责接入决定，Resource 按实际使用决定。每个 N/A 均需源码证据；其 Logic item 仍映射到实现任务、参数化 CASE/PATH/ASSERT，不能因为无 UI 而漏测。

## 7. 任务级四维分析契约

子 MO 先为每个 task 定义 `scope.in/out/write_paths`：具体负责的行为、排除内容、允许写入的目标路径。保留子模块排除项，写范围不得超出认领子模块。随后填写 `dimension_analysis`：

- `scope_sha256`：使用 Ledger contracts.digest 对完整 task.scope 计算摘要，绑定先确定的范围；范围变化必须重新分析并重新冻结。
- `parent_ref`：精确指向认领子模块的 dimension_analysis_ref；继承其源码/架构/二方库/目标能力证据，再补任务针对性分析。
- `dimensions`：UI/Logic/Adhesive/Resource 四行，分别填写 status、reason、evidence_refs、item_ids。item_ids 与 dimension_trace 分配到该任务且同维度的条目一致。
- applicable 行必须填写 `implementation`：具体改哪些行为/节点/接口、如何复用或适配、怎样接线、怎样保留源语义；Resource 引用源资源→目标访问器→消费者，不得只写“完成本维度”。验证沿用该任务已冻结的 PATH/ASSERT。
- not-applicable 行 item_ids=[]，给出本任务范围内的理由及证据。子模块适用某维度不代表每个任务都适用，但所有适用条目必须被任务集合完整承接；不能用 N/A 删除已分配给该任务的条目。
- `unresolved=[]` 才可冻结。任务间共享修改先明确单一写 owner/前置依赖；实施中发现需越过 task scope，先走 CR/影响分析，不能用全模块写权限绕过。

例如“提交查询”子模块先拆出“参数校验”和“按钮事件接线”任务，再分别四维分析。前者 Logic 指导校验规则、错误类型与边界值测试，UI/Resource 可有依据地 N/A；后者按实际职责分析 UI 状态/事件及 Adhesive 的处理器接线。任务分析描述实际实现决策，模块级条目映射仅作为继承与覆盖索引。

当前运行若已有早期四维 plan、尚无任务级分析，须通过正常 plan/CR 补齐并重新冻结；不改写旧事件或伪造旧批准。历史无四维合同的 run 仍按原兼容规则处理。结构校验能绑定范围和证据，真实阅读/决策的先后顺序仍需编排角色遵守。
