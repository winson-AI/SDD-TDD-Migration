# 功能切片与人工输入

## 项目级与单模块入口

`entry_mode` 默认 `project`；省略时同样执行项目级需求分析与多模块切片。模块数量由业务分析决定，不能为了凑数量人为拆分。

单模块只是同一个项目入口上的选择参数，用户只需指定模式和功能模块名：

```json
{
  "entry_mode": "single-module",
  "module_name": "用户登录"
}
```

[single-module-input.json](../../../template/single-module-input.json) 仅是这两个入口参数的示例片段，与 [已保存的项目配置](../../migration-protocol/references/project-context.md) 合并并经过 prepare 固化；不是一份需要用户另行填写的完整运行输入。默认仍为 `entry_mode=project`，此时 `module_name` 为 null 或省略；single-module 时 module_name 必须为非空功能名称。

- 共享项目规范、目标架构、legacy_root/target_root、测试执行器和运行配置沿用现有项目输入。只缺共享配置时询问具体缺失项，不要求用户再提交模块资料包。
- 用户不需要提供模块 ID、描述、scope、模块代码路径、SPEC、Testing list、需求 ID 或审计路径。这些都是 Global 的分析输出。项目中已有规范和用例作为分析依据，不是新的用户输入要求。
- Global 按模块名定位真实功能入口、相关代码和已有需求，识别业务边界与独立性，分配稳定 module_id，推导 scope、读写路径和依赖；生成模块级 SPEC 草案及 Testing list。SPEC 包含需求 ID、可观察行为和验收语义；列表包含 CASE-ID/Name、关联需求、前置条件、步骤、预期断言及必需性。
- Global 同时生成本轮 Auditor 的运行级验收路径，覆盖选定模块的全部 CASE；不能直接沿用包含无关模块的整项目验收集合，也不构造不存在的跨模块场景。
- 单模块模式采用名称选定的范围，项目级 module_slicing 不触发重新切片。不能静默扩大范围或新增模块。名称不唯一、未找到对应功能、业务预期不明或边界跨模块时，先分析证据和候选项，再提出具体人工决策问题；不能默认要求用户代写 scope、SPEC 或测试列表。

Global 对这两个产物的生成和覆盖完整性负责，然后生成唯一模块 `_input` 和单节点 DAG，接受 global-plan 并启动 Module-Orchestrator。MO 再派发 Spec-Designer 将模块级 SPEC 草案展开为 OpenSpec 六件套、派发 Test-Runner 细化 CASE→PATH/断言，走澄清冻结及实现流程。Global 生成的草案和 Testing list 不是冻结批准，也不是测试执行证据。

本地接入：宿主先读取/初始化/增量更新项目配置并 prepare 固化，然后执行 Global 的初始化分析职责，把冻结上下文整理成非空规范/需求/用例及运行级审计路径；生成工件只处于 staging，不宣称已被 Ledger 接受，也不提前启动模块 worker。宿主再带 `project_context_ref` 提交现有严格 Ledger init，并以 `input_ref`（已整理输入的 path/sha256）在 init payload 中保留完整输入快照；init 对引用归档后，Global register/global-plan、下游派发和所有交接均经过 Ledger。缺信息时停在输入澄清，不能将 null/空用例送入低层 init 或用占位用例绕过守卫。该分析由宿主/Agent 完成，ledger.py 不内置 SPEC 生成器。

完整流程：

```text
入口参数：single-module + 功能模块名（沿用项目上下文）
  → Global 识别 scope/需求/独立性，生成模块级 SPEC 草案 + Testing list
  → 宿主提交整理后的输入 → Global 注册唯一模块、接受 global-plan
  → Module-Orchestrator → Spec-Designer 六件套 + Test-Runner 路径设计 → 澄清冻结
  → Implementer → Main Testing → 诊断/一轮修复 → MO 验收或挂起
  → Global 检查本轮结束门禁
  → 有遗留：Auditor 收集 → 根因分析 → 委派 Fixer → Testing → 审计裁决
  → 无遗留且模块完成：Auditor 最终独立复测 → 审计记录
```

首轮全 Green 时省略空的遗留问题批次，但必须执行最终 Auditor。单模块的“全局 Green”仅说明选定功能及其声明边界通过，不声明整个项目迁移完成。

若指定功能仍依赖本轮其他待迁移模块，Global 必须记录独立性不成立并交人工决定；不能自行新增 module、吞掉依赖或删测试。已经存在且已验证的外部契约可作为冻结上下文；未知或跨模块业务边界沿用人工裁决规则。需要扩大为项目迁移时，以经批准的范围启动新的 project run，保留原运行记录。

## 项目级切片输入

[global-input.json](../../../template/global-input.json) 的 `module_slicing` 为可选项；省略时由 Global Agent 决定粒度。

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

1. 读取整体规范、新架构、完整测试输入、导入方案及代码路径，建立业务能力列表。
2. 默认由 Agent 按“业务触发 → 状态/数据变化 → 可观察结果”确定粒度，以单个 context pack 可评估为尺度。
3. 用户提供完整功能 use case 时，允许按功能模块一级/二级目录建立 module。Agent 核查目录内外的真实业务关系、架构差异与用例覆盖，再明确每个 module 的 `scope.in/out`、需求、测试列表、legacy 读取路径和 target 写范围。人工未指定层级时由 Agent 选择；调整涉及跨模块或不确定业务边界时交人工决定。
4. 为 CASE 建立模块覆盖与 GLOBAL 集成覆盖映射，记录参与模块和契约；公共契约变化明确责任模块。保留全局用例，不重复计算同一验收范围的通过次数。
5. 分配稳定 ID、生成 DAG 与模块 `_input`；分析任何跨模块或不确定的业务边界，记录到 `global-plan.boundary_review.issues`，给出问题、涉及模块和建议方案，由 Escalation 收集人工决定。
6. Global 接受完整覆盖规划后，模块内由 Spec-Designer 根据 scope 和测试列表生成 SPEC 六件套，由 Test-Runner 细化 PATH/断言；依次澄清、冻结，再生成代码。Global 不替 Spec-Designer 编写模块 SPEC，也不以完整用例跳过冻结。

## 边界决策

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
