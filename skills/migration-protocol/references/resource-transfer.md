# 资源与参数的搬运

## 总则

存量 UI 用到的文件和取值是数据，按“记录 → 派生 → 工具写入 → 核对引用”到达目标，不由角色重新实现：图片、动画、字体按路径复制；尺寸、颜色、文案等参数生成到目标文件、按键取用。清单与参数表由 Ledger 从冻结证据重算，Spec 只写例外，验收比对字节并在提交的代码里找引用。登记 UI/Resource 适用的分配前，`target_resources` 的 copy 与（UI 适用时）parameters 须已定论：GO 依目标工程的资源目录与取用写法给出约定，经 run-review 的 context_patch 写入，推不出才问人；目标不接收的部分记入 `declined` 并写原因，按 [精确性纪律](ui-fidelity.md#精确性纪律) 逐项登记。

## 使用点与闭包

collector 记录范围内代码每处资源引用的使用点（行号、所在类/方法、接收它的调用）、资源文件的文件头事实 `facts`（格式、像素或 viewport、alpha、是否动画）、嵌套 drawable、menu/navigation/xml/manifest 图标、主题属性取值、assets，以及没有资源文件的图片来源 `imageSources`（id `src:<kind>:<hash>`：`remote-image` 含 URL 或 API 字段与加载器占位/变换，`dynamic-resource`，`data-binding`，`code-drawn`）。`analyze-ui` 可带 `manifests`、`image_sinks`（项目自有加载入口）与 `layout_helpers`（项目自有布局参数构造方法，逐元数声明各实参含义）；名字像图片加载却未被解释的调用列在 `imageSinkCandidates`。

- **用到即入账**：代码用到的文件资源（drawable/mipmap/raw/font），不论传给哪个方法，都要由 UI 树某节点声明，或在 `resource_scope.usage_exclusions` 以 `symbol`（类或方法）和/或 `ref` 加 reason、evidence_refs 排除；加载器的占位图随其图片来源入账。
- **闭包**：树触达的每个资源（含嵌套与主题取值）有一个 Resource item 或复制清单的一行；每条 `imageSources` 有一个 `source_signal` item 或 `signal_exclusions`。`remote-image` 可用 `source_equivalent`（`target_source` 取同一来源，`loader_mapping` 把占位图指到 item id 或 `{absent: 原因}`，变换逐条 `{legacy, target}`），其余信号用 `manual_exact`/`blocked`。
- **同图多档**：drawable 的密度与平台版本（`xxhdpi`、`anydpi-v24`）是同一张图的副本，一个条目指明迁移哪一档。

## 文件资源按路径复制

项目在 `target_resources.copy` 声明一次目标目录、路径与 accessor 模板、目标可原样加载的格式和密度取用顺序（字段见 [target-resources.json](../../../template/target-resources.json)）。

1. `resource-plan` 从分析里的 UI 证据派生**复制清单**：每个可原样加载的文件资源一行（存量路径与哈希、目标路径、accessor、使用它的节点），并列出清单之外须登记的资源及原因。Resource 维以 `copy_plan_ref` 引用它；资源全在清单内时 `items` 可为空。
2. 冻结时 Ledger 按证据与约定重算清单，逐行相同才通过；一个资源只由清单或 item 之一覆盖。
3. Implementer 以 `resource-sync`（给出拥有目标目录的 task_id）一次复制全部行：字节相同则保留，不同则拒绝覆盖。
4. 验收逐行核对副本哈希等于存量哈希，且提交的代码完整出现每行的 accessor；副本自身不算引用。

约定已声明时可原样加载的文件必须走清单；手工替换存量图片的 item 以 `copy_blocker` 写明不能复制的原因，随报告披露。

清单之外的 item 同样被核对：非 blocked 的 `target_resource` 与 consumer 必须是目标工程内的文件，产出资源的策略须写 `#accessor`；验收时 `byte_copy` 比对哈希，`value_xml_exact` 比对条目，`exact_vector_xml` 比对确定性转换结果，每个 consumer 文件须出现该 accessor。

## 参数表

`resource-plan` 同时派生模块的**参数表**（UI 维以 `parameter_sheet_ref` 引用，冻结时重算）：布局 XML 属性（style 展开，`@dimen`/`@color`/`@string`/主题属性跟随到取值）、drawable XML 各层（shape 的填充/圆角/描边/渐变、selector 各状态、layer-list 各层）、代码里 setter、属性赋值与布局参数的实参。每个参数有 id、所属组件或图层、名称、带单位的值和出处，并归为一类：

| 类 | 含义 | 目标的义务 |
| --- | --- | --- |
| value | 长度、数值、颜色、文案 | 生成到目标并按键取用 |
| linked | 指向 values 条目 | 由该条目的键满足 |
| picture / layer | 指向图片文件 / XML 图层 | 走复制清单 / 图层自身的参数 |
| keyword | 结构性取值（match_parent、gravity、为 0 的间距） | 属于组件结构，不计入填充 |
| token | 存量代码命名的值（主题键、无唯一取值的主题属性） | 模块内映射一次 |
| expression | 运行时计算 | 保留计算，定值须源证据 |

## 参数填充

项目在 `target_resources.parameters` 声明每模块一个的参数文件、各类型的行模板与 accessor（字段见同一模板）；声明后，有 UI 的模块必须引用参数表。

Spec 在 UI parameter_fill 写例外及动态/结构映射（见[四维模板](../../../template/dimension-analysis.json)）：not_applicable 附原因，deviations 给取值和批准的 alternative，tokens 给值/已有 accessor；settled、runtime、structural 见下节。其余 value 按源记录取用；冻结拒绝未处理的 expression/token。

`resource-sync` 按参数表、例外与模板写出文件，字节由三者决定；验收重新生成并比对，且提交的代码须按键出现每个参数（生成文件自身不算）。生成文件不得手改，取值有误走 CR 修订例外。填充率 = 按记录取用与已映射 ÷ 需要决定的参数，随收尾报告披露。

## 动态参数与布局结构

parameter_fill.runtime/structural 每条记录 id、原 source_expression、consumer（绝对生产文件#accessor）、reason、源 evidence_refs 与冻结 assertions（path_id/assertion_id）；runtime 还记录 inputs。定值须 constant_reason/constant_evidence_refs；布局 keyword 须映射或有证据排除。冻结拒绝缺变量或行为断言，build/static 不证明语义。实现核对提交的消费者/accessor，正式测试验证变量变化、单位/字体缩放、约束、可见性和运行时覆盖。填充率只量化搬运，fidelity_proven 不由它推导。

四维 item.fidelity_conditions 记录 condition_id/condition、status、reason/evidence_refs。父条件须承接；applicable 条件由叶子计划在该 item 的 dimension_trace.condition_assertions={condition_id:[{path_id,assertion_id}]} 绑定本 item 的行为断言（分析里已写 assertions 的以分析为准），N/A 用 assertions=[]。报告 verified 须当前基线真实执行、断言通过且未 stale。

planning_coverage_required 下，仅 applicable UI/Resource 维度需 condition_review：UI 核 theme/density/font-scale/loading-error/visibility-layout，Resource 核 theme/density/loading-error。每项 reason/evidence_refs 说明源依据，condition_refs=[{item_id,condition_id}] 覆盖本维度全部 applicable 条件；空列表表示有证据排除。不适用维度免填。源条件发现与布局语义由规划/Auditor 核验，复制率不证明完备性。

## API 与 URL 契约

业务 API 属 Logic/Adhesive。四维 api_review 记录适用性、reason/evidence_refs；适用须 api_inventory_ref 绑定[清单](../../../template/api-inventory.json)。calls 记录源符号/hash、路由（`transport`：http 记 method/URL，rpc/sdk 记调用名 `operation`）、请求/响应、错误及副作用；contracts 记录消费者、fixture 与映射，item 用 api_ids 唯一认领。范围外调用须 exclusions 证据。planning_coverage_required 下 api_review.discovery_refs 必填（含不适用判定），绑定检索范围并包含已登记调用的 source_ref。GO/父 MO/Auditor 核对调用入口及排除依据；门禁不自动发现全部 API。

imageSources/Resource 的 API 图片 item 写 api_binding（api_id/response_field）；字段匹配 model field/JSON key，target_source 等于 API response_mapping。非 API 模型来源须 image_source_review(kind=non-api)、reason/evidence_refs。URL 字面值不变，加载器占位/变换另映射；仍须接线与正式图片断言。

dimension_trace.assertions.api_obligations 覆盖 `api_id/route` 和 `api_id/<facet>:<field>`，facet 为 request_fields/response_fields/error_outcomes/state_effects；对应 PATH 绑定 fixture_contract_ref 且为 unit/automation。exact 保持源 transport 与路由；approved-adaptation 须理由、信封 alternative 及人工决定：该计划的精确决定、父批量信封，或逐契约命名 alternative 的 run 级决定（kind=api-adaptation，一次覆盖持有这些契约的所有叶子）。实现 dimension_evidence.consumer_refs 核对目标文件/符号，正式断言证明语义；出现名字不等于 API 等价。源变化沿同 Run 回溯重冻、接线和复测。
