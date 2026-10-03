# UI 保真控制道（UI 证据与视觉对齐）

UI 实现需有存量源树、明确 page/state/coverage 和实际可得的运行时基线。角色分工与受限工具见 [受限接入](domain-tools.md)；设备 Capture 由宿主授权的执行者按 [受限视觉执行工具](visual-execution.md) 或既有 adapter 执行，原始产物与转换证据经 Ledger 冻结/验收。

## 结构化 UI 边界（攻克“边界不清晰”）

UI scope 使用可校验载体：

- **capture 目标** `page_id:state_id:coverage`（coverage ∈ `viewport|scroll`），显式列出本切片需视觉验证且可稳定复现的界面态。
- **稳定 id**：原生树保留自己的 screen/node id；SDD 的 `node:<原生节点id>` 引用它。binding/event 是带源码锚点的对象，不能以字符串 ID 代替记录；资源和交互引用随冻结模型互引。
- **显式 exclusions**：范围外界面态/手势/资源逐条声明（如 ForgotPassword 恢复流不呈现）。

### 稳定截图目标与瞬态行为

GO/父 MO 在范围分配时保留全部源状态；子 MO 的 Spec-Designer 与 Test-Runner design 在冻结前区分两类验证义务，并在已有 SPEC/test-design 中逐状态记录源码依据、验证方式和 PATH/ASSERT：

| 状态 | 实现与验证 | 截图要求 |
| --- | --- | --- |
| 可重复到达的 tab/dialog/content/empty/error 等稳定状态 | 保留状态分支与行为路径；存量可预览时冻结 runtime 基线 | 按声明的 page/state/coverage 验证 |
| loading/skeleton/动画过渡等瞬态状态 | 保留源码行为、UI 树动态规则、SPEC 场景和聚焦的状态转换测试 | 不为抢拍而添加 visual PATH，不添加假延时 |
| 明确要求且可稳定复现的 loading 等产品状态 | 记录稳定复现条件与用户需求依据，按稳定目标处理 | 正常执行冻结视觉路径，不能事后降为瞬态免测 |

分类以实际行为与需求为准，不按状态名字猜测。测试可用受控时钟或可控响应验证瞬态转换，不能改生产时序凑截图。无瞬态状态时无需空记录；source-only 的稳定状态沿已有保真限制披露。缺瞬态截图不产生额外 Yellow，也不降低稳定目标的视觉结论；缺其行为测试仍是原 CASE/PATH 的覆盖缺口。父 MO 汇总及 Auditor 沿用冻结分类，不删行为义务、不临时扩大截图清单。样式见 [UI 状态测试表](../../../template/ui-state-test-design.md)。

## UI 证据绑定

`ui-component-spec` 语义模型携带 `ui_evidence`，随冻结经 [semantics.py](../../migration-ledger/scripts/semantics.py) 结构校验：

```jsonc
"semantic_model": {
  "kind": "ui-component-spec",
  "model_ref": {"path": "...", "sha256": "..."},
  "ui_evidence": {
    "capture_manifest_ref": {"path": "...manifest.json", "sha256": "..."},
    "source_index_ref": {"path": "...ui-source-index.json", "sha256": "..."},
    "runtime_index_ref": {"path": "...runtime-ui-index.json", "sha256": "..."}, // source-only 不提供
    "ui_tree_ref": {"path": "...ui-tree.json", "sha256": "..."},   // 合并 source+runtime 的 UI 树
    "coverage": "login:phone:viewport",                            // page:state:coverage
    "legacy_executable": true,                                     // 冻结前判定：存量能否预览
    "visual_mode": "runtime",                                      // runtime ⟺ 可预览（须与树的 runtimeIndex 一致）
    "baseline_refs": [{"path": "...shot.png", "sha256": "..."}]     // 存量截图基线；source-only 时省略
  },
  "interactions": [ ... ],                                          // 可选：Spec 显式声明的手势
  "source": {"origin": "...", "locator": "...", "evidence_refs": []},
  "implementation_location": {"target_path": "/abs", "symbol": "..."}
}
```

`ui_tree_ref` 与 `baseline_refs` 归档进 artifacts、hash 冻结；`coverage` 必须匹配 `page:state:(viewport|scroll)`。Spec-Designer 通过受限 analyze-ui/validate-ui 使用 collect/select/validate_ui_tree，保留源/运行时索引与原始 manifest 引用；截图来自宿主授权的 Android capture。树结构通过不等于源闭包语义完整，MO 仍核对实际 renderer、分支和范围。

runtime 证据必须有原始 capture_manifest_ref；runtime index 的 manifestSha 绑定它。当前 page/state/coverage 必须唯一匹配 Android COMPLETE 记录，按原生 selector 重算后的 capture 与 runtime index 一致，baseline_refs 恰好是该 capture 的截图集合。共享 manifest/index 的其他目标可以独立处理，其缺失文件不阻塞当前目标。source-only 仍经过同一原生 source/tree 严格校验；纯源码模式可省略 manifest，若提供则当前目标必须是 SOURCE_ONLY，不能带 runtime index、观察或 baseline 伪造运行成功。

## 强制开关

标准 prepare 路径固定 `ui_fidelity_required=true`，prepared init 不能关闭。开启后 [ui_fidelity.py](../../migration-ledger/scripts/ui_fidelity.py) 仅对 applicable UI 强制下列门禁；无 UI/有证据的 N/A 不新增空任务：

- **冻结门禁**：每个 applicable UI item 必须携带绑定 `ui_evidence` 的 `ui-component-spec` 模型（`semantics.ui_fidelity_gaps` 列缺口）；必须已判定存量可执行性；资源闭包不得缩减；`source_closure.ui_renderers` 必填；有基线的目标必须有 visual 路径。


## 基线前移：截图指导实现，而非事后比对

视觉证据的位置决定它是否真的提升还原度。基线**前移到规划/实现阶段**作为输入，冻结前必须判定存量可执行性（[ui_fidelity.baseline_gate](../../migration-ledger/scripts/ui_fidelity.py)）：

| 判定 | `ui_evidence` | 作用 |
|---|---|---|
| **存量可预览** | `legacy_executable: true` + `visual_mode: runtime` + `baseline_refs`（存量截图） | 截图**指导 SPEC 生成与 Implementer coding**；后续作视觉对齐基线 |
| **存量不可预览** | `legacy_executable: false` + `visual_mode: source-only` | 回退保留 UI 源码，但**仍强制走四维 UI 中间表征层**（`ui-component-spec` + `ui_tree`）指导 coding；无基线，不伪造视觉通过 |

未判定可执行性 → 不能冻结。实现接受时，conformance 必须用 `baseline_conformance` 引用**指导 coding 的那份基线或中间表征**（runtime→`baseline_refs`；source-only→`ui_tree_ref`），确保实现确实被证据引导。

## 视觉对齐 = automation 第二层（不是独立阶段）

Test-Runner 在 build Green 后分两层，都是普通测试路径，走既有三态与 Next-STEP：

```text
build → Green
  └─ automation 第一层：功能用例路径走通 → Green
        └─ automation 第二层 visual：对齐存量基线，逐「视觉对齐路径中的节点」assert
```

- `visual` 路径必须绑定 `node_ids`（稳定 `node:` id）与 `baseline_ref`（[test_validation.plan_check](../../migration-ledger/scripts/test_validation.py)）；还须显式 coverage，等于对应 UI item 的 page/state/coverage，baseline_ref 属于该目标 baseline_refs，node_ids 仅引用该目标真实树节点。每个 runtime 目标至少一条对应 visual PATH，不能跨状态充数。
- 阶段顺序由 `tv.next_scope` 强制：**第二层需第一层 Green**（功能没走通时比对渲染无意义）；DoD 要求**全部三层路径 Green**（`tv.all_green`）。
- 视觉不对齐 = **Red + 节点级 root_cause** → 走 ④三态 / ⑤`diagnose` → 一轮 Fixer，**复用既有修复预算**（不另设轮次）。
- 声明的手势（`interaction:<id>`）必须由某条 automation 或 visual 路径承载设备证据（`interaction_id`），静态路由不可替代。source-only 可用 automation 验证行为，无需创建缺少基线的 visual PATH；runtime 目标原有视觉义务仍保留。
- `source-only` 无第二层（无基线可比），按显式缺视觉证据收尾，不允许"没基线就免检"中间表征。
- 仅自动化环境缺失时，`automation-unavailable` 同时挂起 automation 与 visual 两层，沿用既有 Yellow 缺测收尾。

正式视觉 Green 要求 `record.visual_alignment` 与本次执行回执中的 `captured.visual_alignment` 完全一致：冻结 PATH 的 coverage/node_ids/baseline_ref、模块当前 code_baseline、可校验 hash 且属于当前已接受 build_artifacts 的 hap_ref。声明 interaction_id 时，execute_test 从冻结 dimension model 取完整 frozen_interaction（id/action/from/expected，可选 spec_ref）写入 query（GLOBAL 自有 PATH 冻结自己的）；proof.required_interaction 须与之一致，interaction_checks 需有同 ID、PASSED、同 action、observed 满足冻结 expected、同 hap_sha256/代码基线且证据真实的唯一记录，不能另声明更容易的动作或目的页面。adapter 与正式门禁分别核对。Red/Yellow 可保留不完整证据及原因，不能为缺设备伪造哈希或通过；未完成自动化按 Yellow/未执行收尾，其他模块与可用构建下游继续。execute_test 经 lean_visual_adapter 接入原始比较结果，见 [接入协议](domain-tools.md#总则)。

automation 手势使用 [interaction-evidence.json](../../../template/interaction-evidence.json) 的条件扩展：正式 Green 同样核对冻结完整动作、起点、预期、当前 HAP/代码及实际观测，record 与原始 report 的 interaction_evidence 必须一致。不要求截图基线，不从 expected 合成 observed。默认 Harmony 未产出该结构化证据时，已执行断言保留并规范化为 Yellow（interaction-evidence-unavailable），可以正式提交；真实 Red 不被覆盖。能力缺失沿现有预检/Yellow 收尾，不新增全局阻塞。

### 视觉修复聚焦

未解决失败全部是 visual PATH 时，诊断必须给出 1–2 条 `visual_issues`（area、problem、severity=low|medium|high|critical、evidence_ref），多于两条被拒绝：有限的修复轮次只处理最影响还原度的问题。

- 优先：页面/状态不符或固定区域缺失多余 → 顶/底/居中锚点错位 → 遮罩与层级 → 主要区域偏移 → 文本裁切/换行/字号 → 媒体裁切与比例 → 有明确影响的颜色/透明度。
- 忽略：状态栏时间电量、压缩与抗锯齿噪声、轻微等比缩放、槽位正确时的远程图片内容差异、微小图标偏移。
- 修复面：Fixer 只改布局与修饰、排版/颜色/形状/可见性、已迁移资源的消费者、图片裁切与呈现、比较所需的确定性状态准备；不得为贴近截图或通过图像检查伪造数据、重绘资源或换用别的图标。需要改行为、数据契约、导航或规格时走 CR，资源映射本身的错误交资源 owner。

## capture / 构建产物契约

Green 还须带 `alignment_root` 与从原始 alignment 推导的 `comparison_evidence`。逐 round/page/state/reference_capture_index/candidate_capture_index 选取 manifest 中的截图，核对 score 的 reference/candidate 摘要；semantic 必须绑定该 score_sha256 或同一图片对，同时提供两者时全部核验。正式门禁重读 evidence_ref 推导相同结果，不能自填“已经关联”。ALIGNED_CARRIED 保留原 ALIGNED 的完整对齐证据，并用 regression_score 绑定 carried_from_round 与当前 capture_round 的 Harmony 截图（regression_capture_index 默认 0）；仍须明确 ALIGNED 裁决，分数本身不自动通过。

adapter 与正式 submit/accept/Auditor 共用 [visual_evidence.py](../../migration-ledger/scripts/visual_evidence.py)：从所属叶子冻结模型重取完整 Android capture 记录及 baseline_refs，核对每屏、顺序和原始元数据，不能只保持首屏相同后替换其他屏；候选 snapshot 的 capture_execution_ref 与安装/捕获回执见 [视觉执行](visual-execution.md#2-执行节点)。

可选 GLOBAL visual PATH 在规划时声明 `build_binding: {module_id, path_id}`，指向负责项目集成构建的冻结 build PATH；实际 Green 只接受该 PATH 在当前模块基线的已接受构建产物。GO/MO 审查该构建命令是否覆盖此全局用例依赖；缺少绑定不会借用全局产物池，也不要求重跑已有 Green。

- **capture manifest** [ui_evidence.validate_capture](../../migration-ledger/scripts/ui_evidence.py):`COMPLETE` 必须有真实 screenshot/view_xml/meta 三元组 + 非空 captures + `observed_variant` + 记录 backend;`scroll` 只有 `scroll-complete` 才算达成(截断的 scroll-partial **永不**推进);`SOURCE_ONLY` 不得携带臆造 captures;缺 coverage 的旧记录不得升级为 viewport。
- **validation → 三态 + HAP** [lean_adapter.validation_summary](../../migration-ledger/scripts/lean_adapter.py):外部验证结果的 compile/test/package 检查映射为三态(任一 failed → Red);`package` 通过必须记录产物,且 artifact 的 sha256 与当前文件**仍需匹配**(HAP 不能被换掉)。

## 精确性纪律

还原度差的根因不是验证不足，而是**允许了近似**。以下规则把"近似"从源头排除：

**① 资源精确策略 + 反近似禁令** —— [resource_fidelity.py](../../migration-ledger/scripts/resource_fidelity.py) 为 Resource 维 item 提供 `resource_strategy` 枚举。UI 呈现闭包内 Resource item 必须显式填写 `resource_kind` 与 `resource_strategy`，不能通过省略字段避开精确性校验：

| Android 源类型 (`resource_kind`) | 必须策略 |
|---|---|
| vector | `exact_vector_xml`（保留 viewport/path/group/clip/stroke/fill/alpha/mirroring；**不是** ImageVector） |
| bitmap / font / raw | `byte_copy`（字节级） |
| string / plurals / array | `value_xml_exact`（保留文本、占位符、转义、quantity/数组结构、限定符） |
| color / dimen / 已证 attr | `design_token_exact` |
| selector / layer-list / shape / 有状态绘制 | `compose_semantic_exact` |

**没有 `approximate` 策略**：禁止 Material 图标替代、手绘近似、语义近似、自动栅格化、位图兜底。逃生口仅 `manual_exact`（须 `adaptation_evidence_ref` 实证；静态图另受[图片与图标对齐](#图片与图标对齐)闸门约束）与 `blocked`（须 `blocked_reason`）。专项规则：`.9.png` 的 stretch/content 区域**永不** `byte_copy`；`sp` 尺寸被间距消费时必须 `scales_with_font`（不得静默变固定 Dp）。

**② 闭包不得缩减** —— `ui_fidelity_required` 开启时，UI 树声明的每个呈现引用（含 `dynamicRules` 的代码态运行时覆盖）必须被实际 Resource item 覆盖，否则冻结被拒。逐 `source_resource + qualifier` 留真实源、策略、目标及消费者证据；裸 `covered_resource_ids` 不计入覆盖。资源分组使用现有 TASK/dimension_trace；附加资源及别名分别登记源事实，不能用一个主资源代证其余资源。

声明的 resource_kind 必须与 source_resource_ref 指向的真实文件/values 条目一致。冻结与受限资源转换读取源事实，校验 qualifier、.9.png、sp 单位；byte_copy 导入校验源目标字节相等。资源扫描、任务授权、单项 values 转换与变体映射见 [资源接入](domain-tools.md#资源执行与事实绑定)。

进一步从本 UI 树实际引用到的源索引逐 `source_resource + qualifier + path` 核验闭包：每个适用变体恰有一个 Resource item，并与 collector 保存的源文件 SHA、实际文件及 Resource source_resource_ref 一致。base 覆盖不能代替 night/语言等变体。明确不属于当前切片的候选通过 ui_evidence.resource_scope.exclusions 逐项说明 source_resource/qualifier/path、reason 与 evidence_refs；排除证据持续校验，不能排除配置范围中明确启用的 qualifier。未被本树引用的资源不扩大门禁。旧索引缺少资源 hash 或已过期时重新抽取、审查与冻结，不给旧提取值补上当前 hash。res/color* 的状态选择器按 selector/compose_semantic_exact 处理，不能伪装为固定 color token。

**③ blocked 不得计入 Green** —— `completion_gate` 拒绝仍带 `blocked` 资源的模块完成。

代码中的 `R.id` / `android.R.id` 保留为节点定位事实，不按独立资源文件查找。`@array` 能发现 string-array 与 integer-array，并以 array 精确迁移；不丢失元素结构。Android 平台引用（`@android:` / `?android:`）须在 Resource item 声明 platform_resource.api_level 与 sdk_metadata_ref，后者指向真实 SDK source.properties；source_resource_ref 必须位于同 SDK 的 data/res 且包含匹配定义。冻结与后续计划读取持续核验 API、摘要、kind/qualifier/配置路由。SDK 文件为只读来源，分析资产仍留在当前 run。缺 SDK 定义可显式 blocked 留缺口，不伪造源码或一律拒绝所有平台资源。示例见 [semantic-model.json](../../../template/semantic-model.json)。

**④ UI 树白盒（按原生采集器真实契约）** —— [ui_evidence.validate_tree](../../migration-ledger/scripts/ui_evidence.py) 校验 `ui_tree_ref` 内容：`schemaVersion:1`、`scope`、合并溯源 `generatedFrom`（runtime 两字段同有或同无）、`screens[]`（递归 source-backed `root` 与 `attachments[]`，重复行只记一次）、完整映射源布局的 `layoutClosure`，以及显式的 `criticalLayoutContracts`/`unresolved`（冲突不得丢弃）。节点字段、attachment kind 与 binding/event/dynamic rule 必填项见模板 `ui_tree_contract`，各记录都带 sourcePath 与 line 或 selector；runtimeObservations 只记实际运行观察，source-only 树不得携带，visual_mode 须与 runtimeIndex 是否存在一致。完整模板见 [semantic-model.json](../../../template/semantic-model.json)，测试用真实 collector 产物实例化该模板后调用原生严格 validator；不能只检查 JSON 语法或替换模板树后再声称模板通过。

**⑤ 源闭包证据面** —— UI 适用时 `source_closure` 必填 `ui_renderers`（仅有 layout 不完整，必须点名真正改变可见状态的 Activity/Fragment/Adapter/ViewHolder/自定义 View 渲染者），以及 `ui_topology`（布局/对话框/菜单/标签/浮层及初始可见性）、`states`（实际存在的 loading/content/empty/error/disabled/transient/refresh/retry/pagination）、`navigation`（目标身份/参数/返回行为/范围外副作用）、`platform_lifecycle`（权限/存储/网络/回调/后台/取消/宿主窗口）。散文控件清单不算闭包。证据质量纪律：**listener 只证事件绑定，不证 UI 层级；类型声明只证 API 形状，不证生产调用路径**；基础工作在被用户可见行为消费前不算已交付切片。

**⑥ 消费者接线纪律（anti-guess，协议）** —— 改任何源声明的 dimension/margin/padding/typography/color 前，须经 UI 树 + 资源映射追溯消费者：存在精确映射而消费者硬编码/猜测 → 必须改为接线映射值；映射缺失/错误 → 路由 Resource owner。**只有所有源值与运行时覆盖都接线后**，截图证据才可用于证明残余跨平台文本布局校正。Resource 的 `consumer` 支持单值或列表；实现证据以 `consumer_refs` 逐文件覆盖冻结消费者（同文件多个符号只需一个 hash），并持续校验 hash。文件引用正确只证明读取对象一致，生产接线语义仍由角色审阅及正式测试验证。

## 图片与图标对齐

图标与图片最先漂移，所以它们的来源、迁移策略和屏幕结果都有可校验记录。

**① 信号记录。** collector 除布局引用外还记录：逐层嵌套的 drawable、menu/navigation/xml/manifest 中的图标、主题属性及取值、assets 图片；每个资源文件带从文件头读到的 `facts`（格式、像素或 viewport、alpha、是否动画、density/dp）。没有资源文件的图片来源记入 `imageSources`（稳定 id `src:<kind>:<hash>`）：`remote-image`（URL 或 API 字段及 JSON key，含加载器 placeholder/error/fallback 与变换）、`dynamic-resource`（运行时拼出的资源名及候选）、`data-binding`、`code-drawn`（绘制代码）。`analyze-ui` 可带 `manifests` 与 `image_sinks`（项目自有的加载入口）。

**② 闭包以记录为准。** 树触达的每个资源文件（含嵌套及随主题属性跟随到的取值）逐 `source_resource+qualifier+path` 一个 Resource item；每条 `imageSources` 一个 `source_signal` item（`resource_kind` 取信号 kind），或在 `resource_scope.signal_exclusions` 带证据排除。`remote-image` 可用 `source_equivalent`：`target_source` 指明目标取同一来源，`loader_mapping` 把 placeholder/error/fallback 指到 item id（或 `{absent: 原因}`），变换逐条 `{legacy, target}`；其余信号用 `manual_exact`/`blocked`。`resource-scan` 按记录预填 `skeletons`，作者只补策略、目标与消费者。

**③ 图像检查。** `ui-component-spec` 的 `image_checks[]` 冻结“此节点必须显示这张存量图片”：`id`、`node_id`、`source_resource`+`qualifier`、`reference.render_ref`（`render-reference` 从存量文件离线渲染的参考栅格，绑定源索引中该文件的 SHA）、`target.selector`（目标 view tree 里节点的精确 class/resource-id/text/content-desc）、可选 `capture_index` 与 `tolerance`。visual PATH 以 `image_check_ids` 承载检查：Test-Runner 抓取目标屏幕并运行 `image-parity`，Ledger 用哈希绑定的同一批输入重算——节点图像与参考的形状 IoU ≥ 0.72、宽高比偏差 ≤ 0.20（可选颜色）为 MATCH → Green；MISMATCH → Red 并给节点级根因；找不到节点或截图（INCOMPARABLE）→ Yellow。**不依赖存量可运行**：无 `baseline_ref`、有 `image_check_ids` 的 PATH 只抓取目标，coverage 须是冻结的 UI 目标，node_ids 属于其树并含每个检查的节点；runtime 目标仍须另有基线 PATH，已声明的检查必须被某条 visual PATH 承载。带基线的 PATH 也可同时承载检查，其节点须是基线观察到的节点。

**④ 非精确图形闸门。** 静态位图/矢量（bitmap、vector，或 raw/assets 中的静态图）用 `manual_exact` 代替精确复制时，item 恰有其一：`image_check`（已声明、被 visual PATH 承载、属于同一 source_resource+qualifier）或 `deviation` `{alternative, kind: redraw|degrade|absent, reason, evidence_refs?}`。`alternative` 必须是计划 `decision_envelope.allowed_alternatives` 的一项，由人类随计划 hash 批准，Implementer 不能自行认定“足够近似”。动画与绘制代码无法离线测量：保留经评审的 `manual_exact`（也可带 `deviation`），不可挂 `image_check`。

## 最终报告的保真披露

GO migration-report 增加 visual_coverage 与 fidelity_limitations：逐模块/目标列出 runtime 已验证、未验证、source-only、显式无 UI 或证据未知。只有当前基线已执行并 Green 的视觉路径可列 verified；source-only 业务 CASE 可以 Green，但报告必须说明未验证视觉保真。capture-fixture 另列“样本未证明在线服务/provider 等价”。`picture_fidelity` 逐项列出非精确复制的图片：verified（其图像检查所在 PATH 当前已执行并 Green）、not-verified、approved-deviation、reviewed（动画/绘制代码/手工加载映射，仅评审未测量）、blocked、unknown；未验证者同入 fidelity_limitations。这些是证据覆盖说明，不新增阻塞门、不重染业务 CASE、不扩展 Auditor 复测范围。缺测 Yellow 仍按原控制流收尾。
