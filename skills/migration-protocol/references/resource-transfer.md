# 资源与参数的搬运

## 总则

存量 UI 用到的文件和取值是数据，按“记录 → 派生 → 工具写入 → 核对引用”到达目标，不由角色重新实现：图片、动画、字体按路径复制；尺寸、颜色、文案等参数生成到目标文件、按键取用。清单与参数表由 Ledger 从冻结证据重算，Spec 只写例外，验收比对字节并在提交的代码里找引用。项目未声明约定的部分按 [精确性纪律](ui-fidelity.md#精确性纪律) 逐项登记。

## 使用点与闭包

collector 记录范围内代码每处资源引用的使用点（行号、所在类/方法、接收它的调用）、资源文件的文件头事实 `facts`（格式、像素或 viewport、alpha、是否动画）、嵌套 drawable、menu/navigation/xml/manifest 图标、主题属性取值、assets，以及没有资源文件的图片来源 `imageSources`（id `src:<kind>:<hash>`：`remote-image` 含 URL 或 API 字段与加载器占位/变换，`dynamic-resource`，`data-binding`，`code-drawn`）。`analyze-ui` 可带 `manifests`、`image_sinks`（项目自有加载入口）与 `layout_helpers`（项目自有布局参数构造方法，逐元数声明各实参含义）；名字像图片加载却未被解释的调用列在 `imageSinkCandidates`。

- **用到即入账**：代码用到的文件资源（drawable/mipmap/raw/font），不论传给哪个方法，都要由 UI 树某节点声明，或在 `resource_scope.usage_exclusions` 以 `symbol`（类或方法）和/或 `ref` 加 reason、evidence_refs 排除；加载器的占位图随其图片来源入账。
- **闭包**：树触达的每个资源（含嵌套与主题取值）有一个 Resource item 或复制清单的一行；每条 `imageSources` 有一个 `source_signal` item 或 `signal_exclusions`。`remote-image` 可用 `source_equivalent`（`target_source` 取同一来源，`loader_mapping` 把占位图指到 item id 或 `{absent: 原因}`，变换逐条 `{legacy, target}`），其余信号用 `manual_exact`/`blocked`。
- **同图多档**：drawable 的密度与平台版本（`xxhdpi`、`anydpi-v24`）是同一张图的副本，一个条目指明迁移哪一档；night、语言等限定符内容不同，各自登记。

## 文件资源按路径复制

项目在 `target_resources.copy` 声明一次目标目录、路径与 accessor 模板、目标可原样加载的格式和密度取用顺序（字段见 [target-resources.json](../../../template/target-resources.json)）。

1. `resource-plan` 从分析里的 UI 证据派生**复制清单**：每个可原样加载的文件资源一行（存量路径与哈希、目标路径、accessor、使用它的节点），并列出清单之外须登记的资源及原因。Resource 维以 `copy_plan_ref` 引用它；资源全在清单内时 `items` 可为空。
2. 冻结时 Ledger 按证据与约定重算清单，逐行相同才通过；一个资源只由清单或 item 之一覆盖。
3. Implementer 以 `resource-sync`（给出拥有目标目录的 task_id）一次复制全部行：字节相同则保留，不同则拒绝覆盖。
4. 验收逐行核对副本哈希等于存量哈希，且提交的代码完整出现每行的 accessor；副本自身不算引用。

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
| expression | 运行时计算 | 由 Spec 给出目标取值或说明不适用 |

## 参数填充

项目在 `target_resources.parameters` 声明每模块一个的参数文件、各类型的行模板与 accessor（字段见同一模板）；声明后，有 UI 的模块必须引用参数表。

Spec 只在 UI 维的 `parameter_fill` 写例外（见 [dimension-analysis.json](../../../template/dimension-analysis.json)）：`not_applicable`（附 reason）、`deviations`（另给取值，`alternative` 属于计划已批准的 allowed_alternatives）、`tokens`（给值，或指向目标已有的 accessor）、`settled`（给 expression 定值）。其余 value 一律按记录取用；冻结拒绝未定值的 expression 与未映射的 token。

`resource-sync` 按参数表、例外与模板写出文件，字节由三者决定；验收重新生成并比对，且提交的代码须按键出现每个参数（生成文件自身不算）。生成文件不得手改，取值有误走 CR 修订例外。填充率 = 按记录取用与已映射 ÷ 需要决定的参数，随收尾报告披露。
