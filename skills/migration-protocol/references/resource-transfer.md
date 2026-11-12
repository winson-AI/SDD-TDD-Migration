# 资源与参数的搬运

## 总则

存量 UI 用到的文件和取值是数据，按"记录 → 派生 → 工具写入 → 核对引用"到达目标，不由角色重新实现：图片、动画、字体按路径复制，尺寸、颜色、文案等参数生成到目标文件按键取用。清单与参数表由 Ledger 从冻结证据重算，Spec 只写例外，验收比对字节并在提交的代码里找引用。登记 UI/Resource 适用的分配前，`target_resources` 的 copy 与（UI 适用时）parameters 须已定论：GO 依目标工程的资源目录与取用写法给出约定，经 run-review 的 context_patch 写入，推不出才问人；目标不接收的记入 `declined` 并写原因，按 [精确性纪律](ui-fidelity.md#精确性纪律) 逐项登记。

## 使用点与闭包

collector 记录范围内每处资源引用的使用点（行号、类/方法、接收它的调用）、文件头事实 `facts`（格式、像素或 viewport、alpha、是否动画）、嵌套 drawable、menu/navigation/xml/manifest 图标、主题属性取值、assets，以及无资源文件的图片来源 `imageSources`（`src:<kind>:<hash>`：`remote-image` 含 URL 或 API 字段与加载器占位/变换、`dynamic-resource`、`data-binding`、`code-drawn`）；`analyze-ui` 可带 `manifests`、`image_sinks`（项目自有加载入口）与 `layout_helpers`（项目自有布局参数构造方法，逐元数声明实参含义，未声明的元数整条记 `layout_params` 表达式），像图片加载却未被解释的调用列在 `imageSinkCandidates`。

- **用到即入账**：代码用到的文件资源（drawable/mipmap/raw/font），不论传给哪个方法，都要由 UI 树某节点声明，或在 `resource_scope.usage_exclusions` 以 `symbol`（类或方法）和/或 `ref` 加 reason、evidence_refs 排除；加载器的占位图随其图片来源入账。
- **闭包**：树触达的每个资源（含嵌套与主题取值）由 Resource item 或复制清单覆盖；每条 `imageSources` 有一个 `source_signal` item 或 `signal_exclusions`。`remote-image` 可用 `source_equivalent`（`target_source` 取同一来源，`loader_mapping` 把占位图指到 item id 或 `{absent: 原因}`，变换逐条 `{legacy, target}`），其余信号用 `manual_exact`/`blocked`。
- **同图多档**：drawable 按配置归组，复制清单的 renditions 记录源限定符、源路径、哈希、选用状态和原因。主题、语言等配置按各自资源组核对。

## 文件资源按路径复制

项目声明目标目录、路径与 accessor 模板、可加载格式和密度顺序。见 [资源约定模板](../../../template/target-resources.json)。

- `resource-plan` 从 UI 证据派生 `copy_plan_ref`，登记存量路径与哈希、目标路径、accessor 和使用节点。清单之外的资源另立 item。Ledger 绑定并在冻结时重算，拒绝复制文件和生成参数共用落点。
- 宿主按派发的 TASK 范围预检并同步。相同字节直接保留，CR 只更新仍匹配旧验收哈希的文件。遇独立修改时保留原文件，`drive` 报当前派发与回执。
- `preserve_density: true` 允许按 `{density}` 或 `{qualifier}` 保留多档。用完整限定符区分同密度多版本，如 `anydpi-v21` 与 `anydpi-v24`。报告披露折叠档位。设备检查见 [限定配置的设备验证](#限定配置的设备验证)。
- 验收核对存量字节与代码 accessor。清单外图片手工替换要写 `copy_blocker`。非 blocked 项绑定目标文件和 consumer，`byte_copy` 验哈希，`value_xml_exact` 验条目，`exact_vector_xml` 验转换结果。

## 参数表

`resource-plan` 同时派生模块的**参数表**（UI 维以 `parameter_sheet_ref` 引用，冻结时重算）：布局 XML 属性（style 展开，`@dimen`/`@color`/`@string`/主题属性跟随到取值）、drawable XML 各层（shape 的填充/圆角/描边/渐变、selector 各状态、layer-list 各层）、代码里 setter、属性赋值、布局参数的实参，以及绘制代码交给 Paint、Canvas、Rect、Path 的长度与颜色。每个参数有 id、所属组件或图层、名称、带单位的值和出处，并归为一类：

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

Spec 在 UI parameter_fill 写例外及动态/结构映射（见[四维模板](../../../template/dimension-analysis.json)）：not_applicable 附原因，deviations 给取值和批准的 alternative，tokens 给值/已有 accessor；settled、runtime、structural 见下节；未决表达式与未映射 token 记欠项。其余 value 按源记录取用；冻结拒绝未处理的 expression/token。

`resource-sync` 按参数表、例外与模板写出文件，字节由三者决定；验收重新生成并比对，且提交的代码须按键出现每个参数（生成文件自身不算）。生成文件不得手改，取值有误走 CR 修订例外。报告披露填充率。多配置值见 [限定配置的设备验证](#限定配置的设备验证)。

`target_resources.parameters.configurations` 将完整 Android 限定符映射到独立的绝对目标文件，文件模板含 `{module}`。例如 `night` 与 `sw600dp-night` 可以分别生成同一键的尺寸、颜色、整数或文案，`locales` 可继续映射纯语言文案。报告保留源字面值与落点，缺映射或尚未解析的别名记为未搬运。

## 限定配置的设备验证

在 visual PATH 的 `device_configuration` 填该路径要观察到的配置，可用 `density_dpi`、`night`、`smallest_width_dp`、`api_level` 和 Android 格式的 `locale`。用 `image_check_ids` 绑定对应的 `source_resource` 与完整 `qualifier`。图片用原档位的渲染参考。XML 值可用文本检查、`bounds`（`expect.metric` 为 `width`、`height`、`gap-x` 或 `gap-y`，并声明 `value` 与 `unit`，间距需 `target.anchor_selector`）、或 `color`（`expect.color` 为不透明 `#FFRRGGBB`，可用 `target.sample` 指定裁剪内的采样坐标）。

Android 内置采集在截图前后读取同一设备配置。Ledger 复核命令日志和测量证据。报告按平台、限定符和 PATH 分别保留证据，配置缺失或不匹配时保留未验证。XML 数值、别名、复杂绘制等须建立可重算断言。

### Harmony

冻结 `platform: harmony`、`device_configuration` 和 `harmony_resource_probe`。探针填 `node_id` 和 `selections`，每个检查 ID 映射到 `{resource_id, target_qualifier}`。把选档策略写在目标实际消费者中。用测试 HAP 内的可访问节点暴露小型 JSON，采集生产取值所用的同一 resolver。节点包含 `schema_version: 1`、`configuration` 和以 `resource_id` 为键的 `resources`。配置采集 `vp_scale`（当前 UIContext 的 `vp2px(1)`）、`window_width_vp`，并按本 PATH 需要采集 `density_dpi`、`night`、`locale` 和 `harmony_api_level`。检查值使用原始图片字节的 SHA-256、`{unit, value}` 尺寸、`#FFRRGGBB` 或字符串。屏幕颜色默认精确，设备出现可测的色彩量化时可冻结 `target.channel_tolerance`。探针返回的原始颜色值仍精确比对。

Test-Runner 在同一 HAP、设备锁和 fence 下保留 HDC PNG 和前后原始视图树。Ledger 从原始树复算选档证据和屏幕断言，Harmony 尺寸用实测逻辑缩放。映射可声明目标目录或应用自己的配置分支。Android `vNN` 和 `swNNNdp` 应绑定 Harmony 实际能力或窗口条件。相同内容指纹只能证明内容一致，资源目录身份须有能区分候选的证据。

### Harmony 模拟器与真机

在 `test_adapter.device.harmony.profiles` 声明独立设备配置。例如 `{"emulator":{"serial":"<HDC emulator>"},"physical":{}}` 会预留真机覆盖。接入指定真机时，以同 Run 的设备 `reverify` 补 `physical.serial` 和 `physical.model`。两个设备不能共享 serial。叶子 SPEC 为每个需要验证的设备与限定配置冻结独立 PATH，设置 `harmony_device_profile` 为设备配置名，引用对应的 `target_preview.environments.harmony-<profile>`。保留原有 `emulator` 与 `physical` 名称，也可用 `physical-high-dpi`、`physical-default` 等独立配置。已冻结的配置换绑只影响对应 PATH，其他真机覆盖仍可用。旧的不带 profile 的 PATH 继续使用原 Harmony 环境。既有冻结漏了必需真机配置时，用同 scope 的 CR 补 PATH。设备不可用时记录缺口，同一 CASE 的模拟器和真机分开统计。

真机首轮使用 API 20+ 的主显示（display 0）和单一应用窗口。用同一已验收的签名 HAP 验证浅色和深色。需要区分密度时补实际配置跨档的设备。构建把每次唯一的 由 64 个小写十六进制字符组成的构建标识打包到 `resources/rawfile/sdd-build-id.txt`。正式消费者旁的测试探针读回已安装应用内的标识，使用 `schema_version: 2`，沿用 `configuration` 并带 `build_id`、`viewport: {display_id, window_id, window_bounds_px, orientation}`。每个 `resources[resource_id]` 回报 `{value, resolved_qualifier}`，限定符取正式消费者实际选择的可区分目录或分支。确有获审图片转换时，可冻结 `selections.<check_id>.target_sha256` 校验目标已打包图片的原始字节，PNG 屏幕比对仍以存量渲染参考为准。

Ledger 重读 HDC 型号和系统版本，核对部署的 HAP 引用、应用读回标识、配置、截图及前后 UI 树。真机前后用 WindowManager 获取主屏焦点窗口，再以 `dumpLayout -w` 取该窗口的树。回执重核前树采集及下载、PNG 采集及下载、后树采集及下载的顺序和窗口一致性。原生整窗与 UI 树内容边界分别记账，状态栏等内边距可以存在。内容区须落在整窗内，整窗须可直接对应主屏截图坐标。真机型号来自宿主配置和设备读回，证据范围限于当前接入的设备。未取得实际选档证据时只能确认值一致，真机档位仍未通过。错误档位或值在正式观测中为 Red，设备、安装标识、窗口或取证能力缺失时保留 Yellow。构建和设备检查只在对应 PATH 执行时加载。

对需要区分系统选档与窗口覆盖的 PATH，在 `harmony_resource_probe.configuration_scope` 冻结 `system` 或 `window`。新版 `schema_version: 3` 保留 `configuration` 作为正式消费者的有效配置，并用 `system_configuration` 从系统配置来源读取密度、夜间或语言。可在 PATH 探针契约中同时冻结预期系统值。系统覆盖要求参与判定的系统字段和有效字段都符合预期。窗口覆盖可记录两套不同的值。

资源探针从正式消费者的实际选档读回 `identity`。图片可在映射冻结 `target_entry`，Ledger 从已验收 HAP 重新读取该成员的字节哈希，与消费者取到的哈希对照。XML 可冻结 `target_branch`，同时核对分支标识、类型和值。无法区分候选时允许探针返回空的 `resolved_qualifier` 或 `identity`，已冻结的选档要求保持待验证。

## 动态参数与布局结构

parameter_fill.runtime/structural 每条记录 id、原 source_expression、consumer（绝对生产文件#accessor）、reason、源 evidence_refs 与冻结 assertions（path_id/assertion_id）；runtime 还记录 inputs。定值须 constant_reason/constant_evidence_refs；布局 keyword 须映射或有证据排除。冻结拒绝缺变量或行为断言，build/static 不证明语义。实现核对提交的消费者/accessor，正式测试验证变量变化、单位/字体缩放、约束、可见性和运行时覆盖。填充率只量化搬运，fidelity_proven 不由它推导。

四维 item.fidelity_conditions 记录 condition_id/condition、status、reason/evidence_refs。父条件须承接；applicable 条件由叶子计划在该 item 的 dimension_trace.condition_assertions={condition_id:[{path_id,assertion_id}]} 绑定本 item 的行为断言（分析里已写 assertions 的以分析为准），N/A 用 assertions=[]。报告 verified 须当前基线真实执行、断言通过且未 stale。

planning_coverage_required 下，仅 applicable UI/Resource 维度需 condition_review：UI 核 theme/density/font-scale/loading-error/visibility-layout，Resource 核 theme/density/loading-error。每项 reason/evidence_refs 说明源依据，condition_refs=[{item_id,condition_id}] 覆盖本维度全部 applicable 条件；空列表表示有证据排除。不适用维度免填。源条件发现与布局语义由规划/Auditor 核验，复制率不证明完备性。

## API 与 URL 契约

业务 API 属 Logic/Adhesive：api_review 记适用性与 reason/evidence_refs（planning_coverage_required 下 discovery_refs 必填，含不适用判定与已登记调用的 source_ref），适用须 api_inventory_ref 绑定[清单](../../../template/api-inventory.json)：calls 记源符号/hash、路由（`transport`：http 记 method/URL，rpc/sdk 记 `operation`）、请求/响应、错误及副作用，contracts 记消费者（冻结前须是本模块写或目标已有的文件）、fixture 与映射，item 用 api_ids 唯一认领，范围外调用须 exclusions 证据；门禁不自动发现全部 API，GO/父 MO/Auditor 核对入口与排除依据；分配后在本叶发现的调用以 `api-register` 登记到本叶及其 owner item，下次 plan 带上即可。

imageSources/Resource 的 API 图片 item 写 api_binding（api_id/response_field）；字段匹配 model field/JSON key，target_source 等于 API response_mapping。非 API 模型来源须 image_source_review(kind=non-api)、reason/evidence_refs。URL 字面值不变，加载器占位/变换另映射；仍须接线与正式图片断言。

dimension_trace.assertions.api_obligations 覆盖 `api_id/route` 和 `api_id/<facet>:<field>`，facet 为 request_fields/response_fields/error_outcomes/state_effects；对应 PATH 绑定 fixture_contract_ref 且为 unit/automation。exact 保持源 transport 与路由；approved-adaptation 须理由、信封 alternative 及人工决定：该计划的精确决定、父批量信封，或逐契约命名 alternative 的 run 级决定（kind=api-adaptation，一次覆盖持有这些契约的所有叶子）。实现 dimension_evidence.consumer_refs 核对目标文件/符号，正式断言证明语义；出现名字不等于 API 等价。源变化沿同 Run 回溯重冻、接线和复测。

## 数据契约

数据属 Logic。四维 `data_review` 记适用性与依据，适用须 data_inventory_ref 绑定[清单](../../../template/data-inventory.json)：entities 逐实体记源符号/hash 与四类义务——sources（字段来源）、fetch_conditions（取数条件）、derived_fields（派生字段的计算与单位/精度/时区）、invalidation（失效）；contracts 记目标 repository/model 符号与四个映射，逐义务覆盖；item 用 data_ids 认领，范围外实体入 exclusions。fidelity exact 保持取数与计算语义，approved-adaptation 须理由与信封 alternative。目标已有 repository/model 另一套取数或计算时，existing_target 记符号、差异与 refactor/adapt 决定，不留两套。dimension_trace.assertions.data_obligations 覆盖 `data_id/<facet>:<义务>`，PATH 为 unit/automation 并绑定 fixture_contract_ref：同一 fixture 下逐字段 expected/actual，分页/排序、空值/默认值、缓存失效各至少一条场景；实现 consumer_refs 核对目标 repository 文件与符号。字段同名不等于取数与计算等价。