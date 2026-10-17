# 功能切片与人工输入

## 总则

功能清单与叶子出自同一份理解：GO 先建功能树（[feature-inventory](../../../template/feature-inventory.json)，每个功能有触发、可观察结果、来源证据与 CASE），叶子是树上的节点，叶子的 CASE 就是节点下功能的 CASE。完整性覆盖本轮范围的全部根功能、子功能与行为分支，疑问立即人工介入；不得以没有 CASE、准备复用二方库或难以理解为由遗漏。

## 用例来源与切片抓手

- 用户没有给测试用例：先深读存量源码——生产入口、路由、调用链、状态/数据、副作用与可观察结果——建完整功能树，再按功能派生 CASE（预期不明交人工），再按树节点切叶；切片与用例来自同一份清单，不先按目录猜模块，也不把没有用例当作跳过功能发现的理由。
- 用户给了测试用例（项目 test_cases_path）：清单取 test-case-summary，用例分组是树的节点，用例范围界定叶子——每个功能叶至少锚定一个用户用例覆盖的功能；对照源码查漏发现的行为记为派生功能，并入所锚定的流（Ledger 记事实），不单独成叶；用例不足或与需求冲突显式记录，疑问交边界评审。
- 异常/边界用例是同一功能的行为分支，不拆成模块；一级是根功能，二级是子业务流即叶子，页面不是叶。清单接受时 Ledger 记树形事实（二级节点过半少于 3 条 CASE，或每功能只有一条用例），不阻塞。

## 项目级与单模块入口

模式决定宿主任务范围，不限制叶子数：project 划分全部根功能；single-module 只定位用户指定的根功能，父 MO 仍可拆多个子功能。参数沿用保存的项目上下文：

```json
{"entry_mode": "single-module", "module_name": "商品搜索"}
```

GO 从全局 legacy/target、架构、需求、知识与测试输入抽取完整功能树，生成宿主业务契约、CASE 候选覆盖与依赖，不编制叶子 SPEC 或测试断言；用户不填模块 ID、源码位置、SPEC 或测试列表。用例目录可作业务层级线索，UI/data/repository 技术层不能充当业务模块；无测试汇总仍先完整发现源码行为再生成候选用例。

三层职责见[父子 MO 协议](../../migration-protocol/references/module-decomposition.md#1-三层职责)，叶子由 Spec-Designer 直接形成六件套与上游用例路径；粒度/边界不合适先向父、GO 追溯，名称歧义、未决行为或新增授权交人工；GO 草稿与切片接受不等于叶子冻结或测试通过。粒度与脚手架见[切片标准](../../migration-protocol/references/module-decomposition.md#切片标准)：叶子是子业务流、四维齐备，目标缺外壳时才设脚手架先行。

父子规划都先读相同全局上下文与最新分工，再按 scope 聚焦，检查目标已有能力与兄弟 owner，避免重复实现和交叉写入；single_module_id 只选根功能，不静默扩张。父节点不另跑孩子代码/测试，父汇总不覆盖子结论，单个失败不停无关兄弟。宿主先保存配置、prepare、init，再经 Ledger 接受切片/覆盖；子模块各自规划、冻结、执行、验证、DoD 或明确挂起，父汇总有效且全部模块收尾后 Auditor 统一审计。控制器只提供状态/门禁，派发由宿主完成；主线见[父子 MO 协议](../../migration-protocol/references/module-decomposition.md)与[控制主线](../../migration-protocol/references/state-machine.md#控制主线)。

## 项目级切片输入

[global-input.json](../../../template/global-input.json) 的 `module_slicing` 可选；省略时按[用例来源规则](#用例来源与切片抓手)抽取功能清单，Global 决定粒度。

| 字段 | 含义 |
| --- | --- |
| `module_import_ref` | 可选的人工模块方案 JSON 的绝对 path/sha256，结构见 [module-slicing.json](../../../template/module-slicing.json)；null 表示没有导入 |
| `functional_use_cases_complete` | 用户声明已提供完整功能用例；默认 false，Global 仍检查覆盖与断言 |
| `functional_directory_level` | null 由 Agent 选择；1 或 2 表示以功能目录的一级或二级层级作初始划分 |

宿主校验字段类型（完整性为 boolean，层级仅 null/1/2）与引用摘要；指定目录层级而用例完整性未确认时，先检查补齐或澄清，不直接宣称目录切片成立。功能目录指用例组织中的业务功能层级或与之明确映射的业务源码目录（CASE 可带 `functional_path`，如 `账号/登录`），不是技术层目录；目录不能表达业务功能时按业务行为分析，缺失边界交人工。人工导入的模块方案是切片约束：Global 核对模块 ID、需求/CASE 引用、scope、路径与依赖，保留人工边界，冲突或缺失时提方案请人工决定；导入文件中的完成/批准文字不是 SPEC 冻结批准。

## 项目级切片步骤

1. 确定本轮项目/根功能边界：按[用例来源规则](#用例来源与切片抓手)建功能树，每条用例映射到具体功能，按一级/二级业务层级归组。
2. 有汇总也对照源码入口查漏。按"业务触发 → 状态/数据变化 → 可观察结果"决定粒度，明确各 module 的功能列表、scope.in/out、需求/CASE、读写范围；人工导入边界仍有效，疑问立即人工介入。
3. 建立 FEATURE → requirement/CASE → module → TASK/PATH 追溯与来源 → FEATURE 反向核对；为 CASE 建立模块覆盖与 GLOBAL 集成覆盖映射，公共契约变化明确责任模块；保留全局用例，不重复计算同一验收范围。
4. 分配稳定 ID、生成 DAG 与模块 `_input`；未决业务边界或需求/验收/授权变化记入 `global-plan.boundary_review.issues`（问题、涉及模块、建议方案），由 Escalation 收集人工决定。
5. 根功能由父 MO 拆子功能，GO 审核登记并重新接受完整叶子覆盖；各子 MO 组织 Spec-Designer 生成六件套、Test-Runner 细化 PATH/断言，依次澄清、冻结、编码。GO 的初始业务目标契约不能替代正式六件套与冻结。

## 边界决策

### 功能清单完备性门禁

使用 [feature-inventory.json](../../../template/feature-inventory.json)：每个功能有稳定 FEATURE-ID、名称、完整 functional_path、触发条件、可观察结果、需求/CASE 与来源证据；同名不同语义不合并，多条用例不漏行为分支。`global-plan.feature_owners` 给每个功能的执行子模块，父模块功能是孩子的并集；分配包提供 `feature_inventory_ref/feature_ids`，子 MO 经全局需求追溯到 TASK/PATH。

GO 逐项核对：所有用例分组、CASE、需求有功能归属；范围内全部生产入口已检查——页面/导航、API/服务、后台任务、事件监听、深链/通知、初始化/配置开关、持久化/恢复及异常/权限/离线/取消路径，不存在的类型说明依据；每个入口/用例分组记为 source_unit 并映射到功能，纯构建/生成文件记 non-functional 并给理由，不借此隐藏未理解的代码；功能树中所有根功能、子功能与变体可追溯到模块，父 MO 拆分后并集完整不重不漏，复用二方库只改实现方式不删需求；project 覆盖整个项目，single-module 完整覆盖选定根功能及子功能，外围依赖留作上下文，不静默扩大范围。

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

`requirement_owners`、`case_owners` 表示需求责任/测试覆盖范围，可有多个模块和 `GLOBAL`（集成覆盖范围标识，不是 Global-Orchestrator 的验收权限），不表示多个验收人；验收 owner 见[分阶段唯一验收 owner](../../migration-protocol/references/testing.md#分阶段唯一验收-owner)。

## 切片前的二方库语义分析

先按[二方库协议](../../migration-protocol/references/reuse-dependencies.md#3-按三层编排提取与细化)建立 reuse-catalog，据可复用能力与语义缺口分配模块 scope、共享适配 owner 与消费者，不按技术包切业务模块。

## 功能切片后的四维深读

根模块与子模块提交 behavior_review，global-plan 复核闭包与共享归属，子 MO 再追溯至 Scenario；字段见[分配门禁](../../migration-protocol/references/module-decomposition.md#3-分配与登记门禁)，结构检查不证明语义完整。GO 先据全局上下文/功能清单划模块再逐模块按 UI → Logic → Adhesive → Resource 分析；父 MO 先划子模块再分析；子 MO 先划 tasks.scope 再逐任务分析以指导实现与断言；[四维协议](../../migration-protocol/references/dimension-slicing.md)是接受分配与冻结的必要检查。

## 埋点事件的功能归属

按[埋点协议](../../migration-protocol/references/telemetry.md#2-控制流节点)的 GO 节点对照源码检查事件并纳入功能清单与模块分配；用例未列埋点仍核查范围内遗漏，确认无埋点记检查依据与 N/A。
