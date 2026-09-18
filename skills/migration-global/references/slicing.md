# 功能切片与人工输入

## 项目级与单模块入口

模式决定本轮迁移范围，不决定执行 MO 的数量。

| 模式 | 用户指定范围 | GO 规划 | MO 规划与执行 |
| --- | --- | --- | --- |
| `project`（默认） | 一个完整项目，包含各功能及其子功能 | 划分全部根模块及 scope，生成所需上下文、SPEC 草稿、Testing list 与依赖 | 每个父 MO 拆分自己的子功能；独立子 MO 执行，父 MO 汇总 |
| `single-module` | 项目中的一个特定功能模块 | 定位该根功能及 scope，生成所需上下文、SPEC 草稿、Testing list 与依赖 | 选定功能的父 MO 仍须拆分子功能；独立子 MO 执行，父 MO 汇总 |

用户的单功能入口仍只有两个选择参数，沿用已保存项目上下文：

```json
{"entry_mode": "single-module", "module_name": "商品搜索"}
```

- 用户不需要填写模块 ID、scope、模块代码位置、SPEC 或 Testing list。GO 根据全局存量代码、目标代码、架构/需求/知识及测试输入识别根功能并生成初稿。
- GO 划分根功能 scope 及完成它所需的上下文；父 MO 认领后在范围内拆子功能，为每个子 MO 分配 scope 和上下文。子 MO 基于分配拆 tasks，不再递归创建 MO；粒度不合适则经 Ledger 请求父 MO 调整，涉及跨模块或不确定边界交人工。
- single-module 可在选定功能内部生成多个子模块及依赖；禁止静默扩大到该功能之外的其他根功能。没有测试用例汇总时先从源码抽取完整功能，再生成用例草案；名称歧义、行为疑问、跨根功能或不确定业务边界立即交人工决策。
- 一级用例目录可作为根功能边界，二级及后代作为父 MO 拆分依据；实际粒度取决于完整业务行为，不能把 UI/data/repository 技术层机械分成业务模块。
- GO 的草稿不是冻结批准。子 MO 组织 Spec Designer 展开 OpenSpec 六件套、Test Runner 细化 CASE→PATH/断言，经澄清冻结后编码。
- 父/子 MO 规划时均读取相同全局代码、架构规范、知识资料及最新全项目分工；模块局部路径用于聚焦分析，不限制全局只读视野。先检查目标已实现能力和兄弟模块职责，明确复用关系与唯一实现 owner，避免重复实现和交叉写入。

```text
project：完整项目 → GO 识别多个根功能 → 各父 MO 分别拆分
single-module：选定根功能 → GO 识别该功能 → 该父 MO 拆分
    ↓
MO decompose → GO decompose-accept → 子模块登记 / 全局覆盖规划
    ↓
独立子 MO：全局 + 父级 + 子级上下文读取 → 子功能拆 tasks → SPEC / 测试设计 → 冻结 → Coding → Testing / Fixer → DoD 或明确挂起
    ↓
父 MO：持续看护模块 → 等待所有子 MO 结束 → module-summary
    ↓
GO：全部根功能及子模块本轮收尾 → Auditor 遗留处理 / 最终独立审计
```

`single_module_id` 是低层选定根功能 ID，不能用来限制叶子子模块数量。父节点与执行叶子在 Ledger 中分开记录；父节点不另跑一份相同代码/测试。父汇总不覆盖子模块结论；一个子模块失败不停止无关兄弟。全部叶子与父汇总均结束后才进入 Auditor；单功能 Green 只覆盖选定功能及声明契约。

首次仍由宿主保存项目配置、prepare 固化上下文、GO 生成非空规范/用例/审计路径，再严格 Ledger init、登记根功能。MO 的正式拆分发生在初始化后，通过 Ledger 提交与交接。控制器不内置业务识别或 Agent 调度器。操作契约见 [父子 MO 与全局规划上下文](../../migration-protocol/references/module-decomposition.md)。

## 项目级切片输入

[global-input.json](../../../template/global-input.json) 的 `module_slicing` 为可选项；省略时采用“测试用例汇总优先、缺失则先理解源码”的功能清单抽取方式，Global Agent 决定切片粒度。功能清单来源与切片粒度分别决策。

| 字段 | 含义 |
| --- | --- |
| `module_import_ref` | 可选的人工模块方案 JSON 的绝对 path/sha256，结构见 [module-slicing.json](../../../template/module-slicing.json)；null 表示没有导入 |
| `functional_use_cases_complete` | 用户声明已提供完整功能测试用例；默认 false，Global 仍须检查覆盖与断言是否充分 |
| `functional_directory_level` | null 由 Agent 选择；1 或 2 表示采用功能目录的一级或二级层级作为初始划分 |

例如，在高层输入中启用二级功能目录划分并导入人工模块方案：

```json
{
  "module_slicing": {
    "module_import_ref": {
      "path": "/workspace/inputs/module-slicing.json",
      "sha256": "<实际文件摘要>"
    },
    "functional_use_cases_complete": true,
    "functional_directory_level": 2
  }
}
```

示例路径需要替换；不导入时 `module_import_ref=null`。宿主校验字段类型（完整性为 boolean，层级仅 null/1/2）和引用摘要。指定目录层级但用例完整性尚未确认时，先由 Agent 检查并补齐输入或提交澄清，不直接宣称目录切片成立。

功能目录指用例组织中的业务功能层级，或与这些用例明确映射的业务源码目录。提供目录时，各 CASE 可增加 `functional_path`，如 `账号/登录`。这不是 UI/data/repository 技术层目录。未提供目录映射、用例不完整或目录不能表达业务功能时，不凭目录名猜 scope；Agent 按业务行为分析，缺失的业务边界交人工。

人工导入的模块方案优先作为切片约束。Global 检查模块 ID、需求/CASE 引用、scope、路径和依赖；保留人工指定边界，不能静默拆并或重新分配责任。发现冲突、缺失或需要修改人工边界时提出方案并请求人工决策。导入文件中的完成/批准文字不是 SPEC 冻结批准。

## 项目级切片步骤

1. 先确定本轮项目/指定根功能的边界。默认从已提供的测试用例汇总提取完整功能树，每条用例映射到具体功能，按一级/二级业务层级归组；异常/边界用例保留为同一功能的行为分支，不机械拆成独立模块。
2. 没有测试用例汇总时，必须先理解待迁移存量源码，从生产入口、路由、调用链、状态/数据、副作用与可观察结果抽取完整功能清单，再生成需求与 Testing list 草案。不得先按目录猜模块再补功能，也不得把没有用户用例当作跳过功能发现的理由。
3. 有用例汇总时也要对照源码入口做遗漏核查；用例不足、源码新增行为或与需求冲突均显式记录。按“业务触发 → 状态/数据变化 → 可观察结果”决定粒度，明确各 module 的功能列表、scope.in/out、需求/CASE、读取和写入范围。完整 use case 默认可按一级/二级业务层级起分，Agent 决定层级；人工导入边界仍有效。任何疑问立即人工介入，不自作假设继续划定相关范围。
4. 建立 FEATURE → requirement/CASE → module → TASK/PATH 追溯，以及源码/用例来源 → FEATURE 的反向核对。为 CASE 建立模块覆盖与 GLOBAL 集成覆盖映射，记录参与模块和契约；公共契约变化明确责任模块。保留全局用例，不重复计算同一验收范围的通过次数。
5. 分配稳定 ID、生成 DAG 与模块 `_input`；分析任何跨模块或不确定的业务边界，记录到 `global-plan.boundary_review.issues`，给出问题、涉及模块和建议方案，由 Escalation 收集人工决定。
6. 根功能由父 MO 继续拆分子功能，GO 审核并登记子模块、重新接受完整叶子覆盖规划；各子 MO 组织 Spec-Designer 生成正式六件套、Test-Runner 细化 PATH/断言，依次澄清、冻结、编码。GO 的初始 SPEC 草稿不能替代正式六件套与冻结。

## 边界决策

### 功能清单完备性门禁

使用 [feature-inventory.json](../../../template/feature-inventory.json)。每个功能有稳定 FEATURE-ID、名称、完整 functional_path、触发条件、可观察结果、需求/CASE 与来源证据；同名不同语义不能合并，同一功能多条用例不能漏掉行为分支。`global-plan.feature_owners` 明确每个功能对应的执行子模块；父模块功能列表为孩子的并集。状态分配包提供 `feature_inventory_ref/feature_ids`，子 MO 通过全局需求追溯到 TASK/PATH。

GO 必须逐项核对：

- 所有用例分组、CASE、业务需求有功能归属；无用例时根据源码生成可审核的 CASE 草案，业务预期不明确时交人工。
- 全部在范围内的生产入口已检查：页面/导航、API/服务、后台任务、事件监听、深链/通知、初始化/配置开关、持久化/恢复，以及异常/权限/离线/取消等路径；项目不存在的类型说明依据。
- 每个入口/用例分组记录为 source_unit，映射到功能；纯构建/生成文件/无业务行为的单元可记录 non-functional 与理由，不能用该标签隐藏不理解的代码。
- 功能树中的所有根功能、子功能和变体均可追溯到模块；父 MO 拆分后并集完整、不重不漏。复用二方库只改变实现方式，不能从功能清单删除需求。
- project 覆盖整个指定项目；single-module 完整覆盖选定根功能及子功能，外围依赖保留为上下文，不静默扩大迁移范围。范围外业务必须有明确既有范围依据；不确定是否应迁移则问人工。

`coverage.status=complete` 仅在逐项核查结束、`unclassified=[]`、`unresolved_questions=[]` 时填写。已发现疑问保留在 `questions`，必须同步到 global-plan.boundary_review.issues，并通过现有真实人工批准绑定整份规划；不得删除疑问以绕过审核。未解决时停止受影响规划并提交 Escalation，独立明确的分析可以继续；不得生成代码。

GO 在根登记前的 global-discovery 预检中核对功能草案；父 MO decomposition 和子 planning 预检核对各自功能清单；全部孩子登记后的 global-plan 是完整功能清单/叶子归属的正式接受点。新运行缺少清单、来源映射、需求/用例覆盖或功能 owner 时拒绝接受；后续执行/审计再次检查清单及证据摘要。脚本只能证明已登记清单的结构与追溯完整，真实源码功能是否穷尽由 Agent 审核，存在疑问必须人工裁决。

各 Agent 在自身职责与已批准 scope 内自主工作。新出现的跨模块业务归属、共享契约责任、scope 重划，或不确定的业务预期，必须交人工决定。Global 负责汇总与落实，不能自行代决；Diagnostician/Auditor 可以分析并提出建议，Fixer 不得据此扩大范围。

已有人工决策覆盖且内容、模块责任、契约均未变化的跨模块依赖调度、缺陷路由和复测，按既有决策执行。发现新边界问题时暂停受影响动作；独立模块继续，批准后经过原有 CR/重新冻结门禁。

全局规划中的 `boundary_review.issues=[]` 表示 Agent 已审查且没有需要人工决定的边界问题，不能用空数组掩盖未知项。问题格式示例：

```json
{
  "question_id": "BOUNDARY-001",
  "kind": "cross-module",
  "module_ids": ["M001", "M002"],
  "question": "价格计算由商品模块还是订单模块负责？",
  "proposed_resolution": "商品模块提供价格契约，订单模块消费；各自测试并保留全局下单路径。"
}
```

`kind` 为 `cross-module` 或 `uncertain`。列表非空时，宿主记录真实人类对完整方案的批准，Global 提交 `global-plan` 时附 `boundary_decision_id`；精确摘要绑定见 [本地运行指南](../../migration-protocol/references/local-runtime.md#功能切片输入与边界批准)。未决问题不得作为已接受规划进入实现。脚本只校验声明及批准，业务语义完整性仍由角色审核。

## 覆盖与验收的区别

`requirement_owners`、`case_owners` 保留现有字段名，表示需求责任/测试覆盖范围，可有多个模块和 `GLOBAL`，不表示多个验收人。`GLOBAL` 是集成覆盖范围标识，不是 Global-Orchestrator 的验收权限。

模块阶段以 `(module_id, CASE/PATH, freeze_id, code_baseline)` 为验收范围，唯一验收 owner 是该模块的 Module-Orchestrator；审计阶段以 `(audit assignment/batch, CASE/PATH, snapshot)` 为范围，唯一验收 owner 是对应 Auditor。Test-Runner 执行并提交证据，Ledger 持久化。当前范围测试完整且 Green、证据有效并满足已有 DoD 后，对应 owner 直接验收记录，无需额外人工批准或另一个角色会签。

审计修复期间 MO 仍执行本模块 worker 接收和 DoD 守卫；它们是模块执行记录，不替代或批准 Auditor 的审计结论。模块 Green 不豁免最终全局审计。失败、边界决策、SPEC 冻结及最终交付授权保留各自门禁。

## 切片前的二方库语义分析

先将整体需求与 TARGET/用户指定外部模块的业务能力对齐，建立 reuse-catalog；功能相同不等于 API 同名。依据可复用能力及语义缺口分配模块 scope、共享适配 owner 和消费者，避免按技术包直接切业务模块。父 MO 继续细化需求映射，子 MO 将复用/适配/参考/新实现决策落为 tasks 与 PATH。复用提供方若也在迁移，应登记真实模块依赖；现存稳定库使用版本/接线约束，不虚构待执行 MO。详见 [二方库协议](../../migration-protocol/references/reuse-dependencies.md)。
