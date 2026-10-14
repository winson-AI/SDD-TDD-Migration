# 功能切片与人工输入

## 总则

功能列表默认从测试用例汇总总结/拆分；没有汇总则先理解存量源码完整抽取，再生成测试草案。完整性覆盖本轮范围的全部根功能、子功能与行为分支，疑问立即人工介入；不得以没有 CASE、准备复用二方库或难以理解为由遗漏。

## 项目级与单模块入口

模式决定宿主任务范围，不限制叶子数：project 划分全部根功能；single-module 只定位用户指定的根功能，父 MO 仍可拆多个子功能。参数沿用保存的项目上下文：

```json
{"entry_mode": "single-module", "module_name": "商品搜索"}
```

GO 从全局 legacy/target、架构、需求、知识与测试输入抽取完整功能树，生成宿主业务契约、CASE 候选覆盖与依赖，不编制叶子 SPEC 或测试断言；用户不填模块 ID、源码位置、SPEC 或测试列表。用例目录可作业务层级线索，UI/data/repository 技术层不能充当业务模块；无测试汇总仍先完整发现源码行为再生成候选用例。

三层职责见[父子 MO 协议](../../migration-protocol/references/module-decomposition.md#1-三层职责)，叶子由 Spec-Designer 直接形成六件套与上游用例路径；粒度/边界不合适先向父、GO 追溯，名称歧义、未决行为或新增授权交人工；GO 草稿与切片接受不等于叶子冻结或测试通过。粒度与脚手架见[切片标准](../../migration-protocol/references/module-decomposition.md#切片标准)：叶子是子业务流、四维齐备，目标缺外壳时才设脚手架先行。

父子规划都先读相同全局上下文与最新分工，再按 scope 聚焦，检查目标已有能力与兄弟 owner，避免重复实现和交叉写入；single_module_id 只选根功能，不静默扩张。父节点不另跑孩子代码/测试，父汇总不覆盖子结论，单个失败不停无关兄弟。宿主先保存配置、prepare、init，再经 Ledger 接受切片/覆盖；子模块各自规划、冻结、执行、验证、DoD 或明确挂起，父汇总有效且全部模块收尾后 Auditor 统一审计。控制器只提供状态/门禁，派发由宿主完成；主线见[父子 MO 协议](../../migration-protocol/references/module-decomposition.md)与[控制主线](../../migration-protocol/references/state-machine.md#控制主线)。

## 项目级切片输入

[global-input.json](../../../template/global-input.json) 的 `module_slicing` 可选；省略时按"用例汇总优先、缺失则先理解源码"抽取功能清单，Global 决定粒度。

| 字段 | 含义 |
| --- | --- |
| `module_import_ref` | 可选的人工模块方案 JSON 的绝对 path/sha256，结构见 [module-slicing.json](../../../template/module-slicing.json)；null 表示没有导入 |
| `functional_use_cases_complete` | 用户声明已提供完整功能用例；默认 false，Global 仍检查覆盖与断言 |
| `functional_directory_level` | null 由 Agent 选择；1 或 2 表示以功能目录的一级或二级层级作初始划分 |

宿主校验字段类型（完整性为 boolean，层级仅 null/1/2）与引用摘要；指定目录层级而用例完整性未确认时，先检查补齐或澄清，不直接宣称目录切片成立。功能目录指用例组织中的业务功能层级或与之明确映射的业务源码目录（CASE 可带 `functional_path`，如 `账号/登录`），不是技术层目录；目录不能表达业务功能时按业务行为分析，缺失边界交人工。人工导入的模块方案是切片约束：Global 核对模块 ID、需求/CASE 引用、scope、路径与依赖，保留人工边界，冲突或缺失时提方案请人工决定；导入文件中的完成/批准文字不是 SPEC 冻结批准。

## 项目级切片步骤

1. 确定本轮项目/根功能边界：从测试用例汇总提取完整功能树，每条用例映射到具体功能，按一级/二级业务层级归组；异常/边界用例是同一功能的行为分支，不拆成模块。
2. 没有汇总时先理解存量源码，从生产入口、路由、调用链、状态/数据、副作用与可观察结果抽取完整功能清单，再生成需求与 Testing list 草案；不先按目录猜模块，不把没有用例当作跳过功能发现的理由。
3. 有汇总也对照源码入口查漏，用例不足、源码新增行为或与需求冲突均显式记录。按"业务触发 → 状态/数据变化 → 可观察结果"决定粒度，明确各 module 的功能列表、scope.in/out、需求/CASE、读写范围；一级是根功能，二级是子业务流即叶子，页面不是叶；人工导入边界仍有效，疑问立即人工介入。
4. 建立 FEATURE → requirement/CASE → module → TASK/PATH 追溯与来源 → FEATURE 反向核对；为 CASE 建立模块覆盖与 GLOBAL 集成覆盖映射，公共契约变化明确责任模块；保留全局用例，不重复计算同一验收范围。
5. 分配稳定 ID、生成 DAG 与模块 `_input`；未决业务边界或需求/验收/授权变化记入 `global-plan.boundary_review.issues`（问题、涉及模块、建议方案），由 Escalation 收集人工决定。
6. 根功能由父 MO 拆子功能，GO 审核登记并重新接受完整叶子覆盖；各子 MO 组织 Spec-Designer 生成六件套、Test-Runner 细化 PATH/断言，依次澄清、冻结、编码。GO 的初始业务目标契约不能替代正式六件套与冻结。

## 边界决策

### 功能清单完备性门禁

使用 [feature-inventory.json](../../../template/feature-inventory.json)：每个功能有稳定 FEATURE-ID、名称、完整 functional_path、触发条件、可观察结果、需求/CASE 与来源证据；同名不同语义不合并，多条用例不漏行为分支。`global-plan.feature_owners` 给每个功能的执行子模块，父模块功能是孩子的并集；分配包提供 `feature_inventory_ref/feature_ids`，子 MO 经全局需求追溯到 TASK/PATH。

GO 逐项核对：所有用例分组、CASE、需求有功能归属（无用例时按源码生成可审核的 CASE 草案，预期不明交人工）；范围内全部生产入口已检查——页面/导航、API/服务、后台任务、事件监听、深链/通知、初始化/配置开关、持久化/恢复及异常/权限/离线/取消路径，不存在的类型说明依据；每个入口/用例分组记为 source_unit 并映射到功能，纯构建/生成文件记 non-functional 并给理由，不借此隐藏未理解的代码；功能树中所有根功能、子功能与变体可追溯到模块，父 MO 拆分后并集完整不重不漏，复用二方库只改实现方式不删需求；project 覆盖整个项目，single-module 完整覆盖选定根功能及子功能，外围依赖留作上下文，不静默扩大范围。

`coverage.status=complete` 仅在逐项核查结束、`unclassified=[]`、`unresolved_questions=[]` 时填写；疑问保留在 `questions` 并同步到 boundary_review.issues，经真实人工批准绑定整份规划，不得删疑问绕审。未解决时停止受影响规划并提交 Escalation，独立明确的分析继续，不得生成代码。GO 在 global-discovery 预检核对功能草案，父 MO decomposition 与子 planning 预检核对各自清单，全部孩子登记后的 global-plan 是正式接受点；缺清单、来源映射、覆盖或 owner 则拒绝；脚本只证结构与追溯完整，源码功能是否穷尽由 Agent 审核。

各 Agent 在职责与已批准 scope 内自主工作；新出现的跨模块归属、共享契约责任、scope 重划或不确定的业务预期交人工，Global 汇总落实不代决，Diagnostician/Auditor 可建议，Fixer 不得扩范围。已有人工决策覆盖且内容、责任、契约未变的依赖调度、缺陷路由与复测按既有决策执行；新边界问题暂停受影响动作，独立模块继续，批准后经原 CR/重冻结门禁。`boundary_review.issues=[]` 表示已审查且无需人工决定，不能掩盖未知项。问题格式：

```json
{
  "question_id": "BOUNDARY-001",
  "kind": "cross-module",
  "module_ids": ["M001", "M002"],
  "question": "价格计算由商品模块还是订单模块负责？",
  "proposed_resolution": "商品模块提供价格契约，订单模块消费；各自测试并保留全局下单路径。"
}
```

`kind` 为 `cross-module` 或 `uncertain`。列表非空时宿主记录真实人类对完整方案的批准，Global 提交 `global-plan` 时附 `boundary_decision_id`，精确摘要见[本地运行指南](../../migration-protocol/references/local-runtime.md#功能切片输入与边界批准)；未决问题不进实现，脚本只校验声明与批准。

## 覆盖与验收的区别

`requirement_owners`、`case_owners` 表示需求责任/测试覆盖范围，可有多个模块和 `GLOBAL`（集成覆盖范围标识，不是 Global-Orchestrator 的验收权限），不表示多个验收人。模块阶段以 `(module_id, CASE/PATH, freeze_id, code_baseline)` 为验收范围，唯一 owner 是该模块的 MO；审计阶段以 `(audit assignment/batch, CASE/PATH, snapshot)` 为范围，唯一 owner 是对应 Auditor。Test-Runner 执行并提交证据，Ledger 持久化；范围内测试完整 Green、证据有效并满足 DoD 后 owner 直接验收，无额外人工批准或会签。审计修复期间 MO 仍执行本模块 worker 接收与 DoD 守卫，不替代审计结论；模块 Green 不豁免最终审计。

## 切片前的二方库语义分析

先将整体需求与 TARGET/用户指定外部模块的业务能力对齐，建立 reuse-catalog（功能相同不等于 API 同名），据可复用能力与语义缺口分配模块 scope、共享适配 owner 与消费者，不按技术包切业务模块；父 MO 细化需求映射，子 MO 把复用/适配/参考/新实现落为 tasks 与 PATH。复用提供方若也在迁移则登记真实模块依赖，稳定库用版本/接线约束，不虚构待执行 MO。详见[二方库协议](../../migration-protocol/references/reuse-dependencies.md)。

## 功能切片后的四维深读

根模块与子模块提交 behavior_review，global-plan 复核闭包与共享归属，子 MO 再追溯至 Scenario；字段见[分配门禁](../../migration-protocol/references/module-decomposition.md#3-分配与登记门禁)，结构检查不证明语义完整。GO 先据全局上下文/功能清单划模块再逐模块按 UI → Logic → Adhesive → Resource 分析；父 MO 先划子模块再分析；子 MO 先划 tasks.scope 再逐任务分析以指导实现与断言；[四维协议](../../migration-protocol/references/dimension-slicing.md)是接受分配与冻结的必要检查。

## 埋点事件的功能归属

对照源码检查页面曝光/点击、业务成功失败、生命周期、后台事件及公共 SDK/包装/拦截/配置接线；用例未列埋点仍核查范围内遗漏，把存在的事件与可观察副作用纳入功能清单与模块分配。公共提供方唯一 owner，业务模块各自保留触发/消费职责，不机械创建埋点模块；确认无埋点记检查依据与 N/A，不增加功能或阻塞，不确定时只澄清相关范围。遵守[埋点协议](../../migration-protocol/references/telemetry.md)。
