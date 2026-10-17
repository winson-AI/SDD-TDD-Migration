# UI 保真控制道（UI 证据与视觉对齐）

UI 实现需有存量源树、明确 page/state/coverage 和实际可得的运行时基线。角色分工与受限工具见 [受限接入](domain-tools.md)；设备 Capture 由宿主授权的执行者按 [受限视觉执行工具](visual-execution.md) 或既有 adapter 执行，原始产物与转换证据经 Ledger 冻结/验收。

## 结构化 UI 边界（攻克“边界不清晰”）

UI scope 使用可校验载体：

- **capture 目标** `page_id:state_id:coverage`（coverage ∈ `viewport|scroll`）：本切片需视觉验证且可稳定复现的界面态。
- **稳定 id**：原生树保留自己的 screen/node id，SDD 以 `node:<原生节点id>` 引用；binding/event 是带源码锚点的对象，资源和交互引用随冻结模型互引。
- **显式 exclusions**：范围外界面态/手势/资源逐条声明。

### 稳定截图目标与瞬态行为

GO/父 MO 分配时保留全部源状态；Spec-Designer 冻结前区分两类验证义务，在 SPEC/test-design 中逐状态记录源码依据、验证方式和 PATH/ASSERT：

| 状态 | 实现与验证 | 截图要求 |
| --- | --- | --- |
| 可重复到达的 tab/dialog/content/empty/error 等稳定状态 | 保留状态分支与行为路径；存量可预览时冻结 runtime 基线 | 按声明的 page/state/coverage 验证 |
| loading/skeleton/动画过渡等瞬态状态 | 保留源码行为、UI 树动态规则、SPEC 场景和聚焦的状态转换测试 | 不为抢拍而添加 visual PATH，不添加假延时 |
| 明确要求且可稳定复现的 loading 等产品状态 | 记录稳定复现条件与用户需求依据，按稳定目标处理 | 正常执行冻结视觉路径，不能事后降为瞬态免测 |

分类以实际行为与需求为准，不按状态名猜测；测试可用受控时钟或响应验证瞬态转换，不改生产时序凑截图。无瞬态状态时无需空记录。缺瞬态截图不产生额外 Yellow，也不降低稳定目标的视觉结论；缺其行为测试仍是原 CASE/PATH 的覆盖缺口。父 MO 与 Auditor 沿用冻结分类，不删行为义务、不扩大截图清单。样式见 [UI 状态测试表](../../../template/ui-state-test-design.md)。

## UI 证据绑定

`ui-component-spec` 模型携带 `ui_evidence`，随冻结经 [semantics.py](../../migration-ledger/scripts/semantics.py) 结构校验；证据与采集器产物（参数表、UI 树与索引）以引用进入计划，重提只改引用：

`ui_evidence` 字段：`capture_manifest_ref`、`source_index_ref`、`runtime_index_ref`（source-only 无）、`ui_tree_ref`（合并 source+runtime 的树）、`coverage`（page:state:coverage）、`legacy_executable`（冻结前判定存量能否预览）、`visual_mode`（runtime ⟺ 可预览，须与树的 runtimeIndex 一致；user-reference 见下表）、`baseline_refs`（存量截图，source-only 省略）与可选 `resource_scope`；同一模型可带 `interactions`、`image_checks` 与 `image_check_waivers`。示例见 [semantic-model.json](../../../template/semantic-model.json)。

`ui_tree_ref` 与 `baseline_refs` 归档进 artifacts、hash 冻结。Spec-Designer 经受限 analyze-ui/validate-ui 产出树与索引，保留原始 manifest 引用；截图来自宿主授权的 Android capture。树通过不等于源闭包完整，MO 仍核对 renderer、分支和范围。

runtime 证据须有原始 capture_manifest_ref，runtime index 的 manifestSha 绑定它；page/state/coverage 唯一匹配存量 COMPLETE 参考记录，重算 capture 与 index 一致，baseline_refs 恰为该 capture 的截图集合；共享 manifest/index 的其他目标独立处理。source-only 经同一 source/tree 校验，manifest 可省略，提供则该目标须为 SOURCE_ONLY，不得带 runtime index 或 baseline。

## 强制开关

prepare 固定 `ui_fidelity_required=true`。[ui_fidelity.py](../../migration-ledger/scripts/ui_fidelity.py) 只约束 applicable UI：每个 item 的 `ui-component-spec` 模型与 `ui_evidence` 是冻结前欠项（`semantics.ui_fidelity_gaps` 列缺口，DoD 前结清；无设备的 run 不要求）；资源闭包不得缩减，[复制清单与参数表](resource-transfer.md#总则)与证据重算一致；`source_closure.ui_renderers` 必填；有基线的目标须有 visual 路径，每处静态图片有图像检查或豁免。

## 基线前移：截图指导实现，而非事后比对

基线**前移到规划/实现阶段**作为输入，有 UI 证据的条目冻结前判定存量可执行性（[ui_fidelity.baseline_gate](../../migration-ledger/scripts/ui_fidelity.py)）：

| 判定 | `ui_evidence` | 作用 |
|---|---|---|
| **存量可预览** | `visual_mode: runtime` + `baseline_refs`（存量截图）；`legacy_executable` 随 [存量预览](project-context.md#存量预览) 声明，未捕获界面以 `capture_gap` 披露 | 截图**指导 SPEC 生成与 Implementer coding**；后续作视觉对齐基线 |
| **存量不可预览** | `visual_mode: source-only`（legacy_preview=none） | 回退保留 UI 源码，但**仍强制走四维 UI 中间表征层**（`ui-component-spec` + `ui_tree`）指导 coding；无基线，不伪造视觉通过 |
| **用户参考** | `visual_mode: user-reference` + `baseline_refs`（[用户参考媒体](project-context.md#用户参考媒体)中该 CASE 的截图） | 用户截图指导 SPEC 与 coding，并作对齐基线 |

实现接受时 conformance 用 `baseline_conformance` 引用指导 coding 的基线或中间表征（runtime/user-reference→`baseline_refs`；source-only→`ui_tree_ref`）。

## 视觉对齐 = automation 第二层（不是独立阶段）

Test-Runner 在 build Green 后分两层（第一层：功能用例路径走通；第二层 visual：对齐存量基线，逐视觉对齐路径中的节点 assert），都是普通测试路径，走既有三态与 Next-STEP：

- `visual` 路径须绑定 `node_ids`（稳定 `node:` id）与 `baseline_ref`（[test_validation.plan_check](../../migration-ledger/scripts/test_validation.py)），并显式 coverage = 对应 UI item 的 page/state/coverage；baseline_ref 属于该目标 baseline_refs，node_ids 只引用该目标真实树节点。每个 runtime/user-reference 目标至少一条 visual PATH，不跨状态充数。
- 阶段顺序由 `tv.next_scope` 强制：**第二层需第一层 Green**；DoD 要求**全部三层路径 Green**（`tv.all_green`）。
- 视觉不对齐 = **Red + 节点级 root_cause** → ④三态 / ⑤`diagnose` → 一轮 Fixer，**复用既有修复预算**。
- 声明的手势（`interaction:<id>`）须由 automation 或 visual 路径承载设备证据（`interaction_id`），静态路由不可替代。
- `source-only` 无第二层：行为用 automation 验证，按显式缺视觉证据收尾，不允许"没基线就免检"。
- 仅自动化环境缺失时，`automation-unavailable` 同时挂起 automation 与 visual，沿既有 Yellow 缺测收尾。

正式视觉 Green 要求 `record.visual_alignment` 与回执的 `captured.visual_alignment` 一致：冻结 PATH 的 coverage/node_ids/baseline_ref、当前 code_baseline、本轮已接受且 hash 可校验的 hap_ref。声明 interaction_id 时，execute_test 从冻结 dimension model 取 frozen_interaction 写入 query；proof.required_interaction 须一致，interaction_checks 须有同 ID、PASSED、同 action、observed 满足冻结 expected、同 hap_sha256/代码基线的唯一记录，不得改成更容易的动作或页面。Red/Yellow 可留不完整证据与原因，不得为缺设备伪造哈希或通过；未完成自动化按 Yellow 收尾。execute_test 经 lean_visual_adapter 接入原始比较结果，见[接入协议](domain-tools.md#总则)。

automation 手势使用 [interaction-evidence.json](../../../template/interaction-evidence.json)：正式 Green 同样核对冻结动作、起点、预期、当前 HAP/代码及实际观测，record 与原始 report 的 interaction_evidence 一致；不要求截图基线，不从 expected 合成 observed。Harmony 未产出该结构化证据时，已执行断言保留并规范化为 Yellow（interaction-evidence-unavailable）；真实 Red 不被覆盖，能力缺失不新增全局阻塞。

### 视觉修复聚焦

未解决失败全部是 visual PATH 时，诊断必须给出 1–2 条 `visual_issues`（area、problem、severity=low|medium|high|critical、evidence_ref），多于两条被拒绝：有限的修复轮次只处理最影响还原度的问题。

- 优先：页面/状态不符或固定区域缺失多余 → 顶/底/居中锚点错位 → 遮罩与层级 → 主要区域偏移 → 文本裁切/换行/字号 → 媒体裁切与比例 → 有明确影响的颜色/透明度。
- 忽略：状态栏时间电量、压缩与抗锯齿噪声、轻微等比缩放、槽位正确时的远程图片内容、微小图标偏移。
- 修复面：Fixer 只改布局与修饰、排版/颜色/形状/可见性、已迁移资源的消费者、图片裁切与呈现、比较所需的状态准备；不得为贴近截图伪造数据、重绘资源或换图标。改行为、数据契约、导航或规格走 CR，资源映射错误交资源 owner。

## capture / 构建产物契约

Green 还须带 `alignment_root` 与从原始 alignment 推导的 `comparison_evidence`：逐 round/page/state/capture index 选取 manifest 中的截图，核对 score 的 reference/candidate 摘要，semantic 绑定该 score_sha256 或同一图片对；正式门禁重读 evidence_ref 推导相同结果。ALIGNED_CARRIED 保留原 ALIGNED 的完整证据，并用 regression_score 绑定 carried_from_round 与当前 capture_round 的截图（regression_capture_index 默认 0）；仍须明确 ALIGNED 裁决。

adapter 与正式 submit/accept/Auditor 共用 [visual_evidence.py](../../migration-ledger/scripts/visual_evidence.py)：从所属叶子冻结模型重取完整 capture 记录及 baseline_refs，核对每屏、顺序和元数据；候选 snapshot 的 capture_execution_ref 与安装/捕获回执见 [视觉执行](visual-execution.md#2-执行节点)。

可选 GLOBAL visual PATH 在规划时声明 `build_binding: {module_id, path_id}` 指向冻结的集成 build PATH；Green 只接受该 PATH 在当前模块基线的已接受构建产物。GO/MO 审查该构建命令覆盖此全局用例依赖；缺绑定不借用全局产物池，也不重跑已有 Green。

- **capture manifest** [ui_evidence.validate_capture](../../migration-ledger/scripts/ui_evidence.py):`COMPLETE` 必须有真实 screenshot/view_xml/meta 三元组 + 非空 captures + `observed_variant` + 记录 backend;`scroll` 只有 `scroll-complete` 才算达成(截断的 scroll-partial **永不**推进);`SOURCE_ONLY` 不得携带臆造 captures;缺 coverage 的旧记录不得升级为 viewport。
- **validation → 三态 + HAP** [lean_adapter.validation_summary](../../migration-ledger/scripts/lean_adapter.py):外部验证结果的 compile/test/package 检查映射为三态(任一 failed → Red);`package` 通过必须记录产物,且 artifact 的 sha256 与当前文件**仍需匹配**(HAP 不能被换掉)。

## 精确性纪律

没有走[复制清单与参数表](resource-transfer.md#总则)的资源逐项登记，规则如下。

**① 精确策略与反近似** —— UI 呈现闭包内的 Resource item 必须写 `resource_kind` 与 `resource_strategy`，不能靠省略字段避开校验。源类型决定策略：vector → `exact_vector_xml`（保留 viewport/path/group/clip/stroke/fill/alpha/mirroring；**不是** ImageVector）；bitmap/font/raw → `byte_copy`；string/plurals/array → `value_xml_exact`（保留文本、占位符、转义、quantity/数组结构、限定符；显示值以存量平台解析结果为准，由持有该资源的切片提供唯一取值入口，消费方不各自还原转义）；color/dimen/已证 attr → `design_token_exact`；selector/layer-list/shape/有状态绘制 → `compose_semantic_exact`。

**没有 `approximate` 策略**：禁止 Material 图标替代、手绘近似、语义近似、自动栅格化、位图兜底。逃生口仅 `manual_exact`（须 `adaptation_evidence_ref`；图片另受[图片与图标对齐](#图片与图标对齐)闸门约束）与 `blocked`（须 `blocked_reason`，`completion_gate` 拒绝仍带 blocked 资源的模块完成）。`.9.png` 的 stretch/content 区域**永不** `byte_copy`；`sp` 尺寸被间距消费时必须 `scales_with_font`。

**② 闭包不得缩减** —— UI 树声明的每个呈现引用（含 `dynamicRules` 的运行时覆盖）与代码里的[使用点](resource-transfer.md#使用点与闭包)都要被覆盖，否则拒绝冻结；参数表携带的取值（文案、尺寸、颜色）连同变体即算覆盖。item 逐 `source_resource + qualifier` 给真实源文件的 path/sha256、策略、目标与消费者，kind、qualifier、.9.png、sp 单位与源文件一致且 SHA 与 collector 相同；裸 `covered_resource_ids` 不计覆盖，别名与附加资源各带源事实。night、语言等变体各有 item，不属当前切片的在 `ui_evidence.resource_scope.exclusions` 逐项给 source_resource/qualifier/path、reason 与 evidence_refs，不能排除配置中启用的 qualifier。索引缺 hash 或过期时重新抽取；`res/color*` 状态选择器按 selector 处理。转换与配置映射见[资源接入](domain-tools.md#资源执行与事实绑定)。

**③ 节点 ID、数组与平台资源** —— `R.id` 是节点定位事实，不按资源文件查找；`@array` 以 array 精确迁移，不丢元素结构。平台引用（`@android:` / `?android:`）须声明 platform_resource.api_level 与指向真实 SDK source.properties 的 sdk_metadata_ref，source_resource_ref 位于同 SDK 的 data/res 并含匹配定义；缺定义可显式 blocked，不伪造。示例见 [semantic-model.json](../../../template/semantic-model.json)。

**④ UI 树白盒（按原生采集器真实契约）** —— Ledger 校验 `ui_tree_ref` 内容：`schemaVersion:1`、`scope`、合并溯源 `generatedFrom`（runtime 两字段同有或同无）、`screens[]`（递归 source-backed `root` 与 `attachments[]`，重复行只记一次）、完整映射源布局的 `layoutClosure`，以及显式的 `criticalLayoutContracts`/`unresolved`（冲突不得丢弃）。节点字段、attachment kind 与 binding/event/dynamic rule 必填项见模板 `ui_tree_contract`，各记录都带 sourcePath 与 line 或 selector；runtimeObservations 只记实际运行观察，source-only 树不得携带，visual_mode 须与 runtimeIndex 是否存在一致。

**⑤ 源闭包证据面** —— UI 适用时 `source_closure` 必填 `ui_renderers`（真正改变可见状态的 Activity/Fragment/Adapter/ViewHolder/自定义 View，只有 layout 不算）、`ui_topology`（布局/对话框/菜单/标签/浮层及初始可见性）、`states`（实际存在的 loading/content/empty/error/disabled/transient/refresh/retry/pagination）、`navigation`（目标身份/参数/返回/范围外副作用）、`platform_lifecycle`（权限/存储/网络/回调/后台/取消/宿主窗口）；散文控件清单不算闭包。**listener 只证事件绑定，类型声明只证 API 形状，都不证生产调用路径**；基础工作在被用户可见行为消费前不算已交付切片。

**⑥ 消费者接线纪律（anti-guess，协议）** —— 改任何源声明的 dimension/margin/padding/typography/color 前，须经 UI 树 + 资源映射追溯消费者：存在精确映射而消费者硬编码/猜测 → 必须改为接线映射值；映射缺失/错误 → 路由 Resource owner。**只有所有源值与运行时覆盖都接线后**，截图证据才可用于证明残余跨平台文本布局校正。Resource 的 `consumer` 支持单值或列表；实现证据以 `consumer_refs` 逐文件覆盖冻结消费者（同文件多个符号只需一个 hash）。出现引用只证明用到了它，接线语义仍由角色审阅及正式测试验证。

## 图片与图标对齐

图片的记录、闭包与复制见 [搬运](resource-transfer.md#使用点与闭包)；本节是目标屏幕上的核对。

**① 检查。** `ui-component-spec` 的 `image_checks[]` 冻结对屏幕节点的要求，各带 `id`、`node_id`、`target.selector`（目标 view tree 节点的精确 class/resource-id/text/content-desc）与可选 `capture_index`，`kind` 取：`image`（默认，节点显示这张存量图片：`source_resource`+`qualifier`、`reference.render_ref` 为 `render-reference` 离线渲染并绑定源文件 SHA 的参考、可选 `tolerance`）、`text`（节点文本等于存量字符串：`@string` 的 source_resource、qualifier 与索引中的 `expect.text`）、`node`（节点存在）。

**② 每处图片都上屏核对。** 树上节点声明的每张静态图片（位图/矢量，不含 `.9.png`、动画与 XML 图层）必须有同节点同资源的 image 检查，或在 `image_check_waivers` 以 reason 与 evidence_refs 豁免（可限定 node_id / source_resource）。`screen-checks` 为模块派生全部缺少的检查并渲染参考，节点以自身 id（去掉 `node:`）作 `resource-id` 定位，目标只需给这些节点同名 key；另给出文本检查建议，由 Spec 按状态取用。

**③ 执行。** visual PATH 以 `image_check_ids` 承载检查，已声明的都要被承载：Test-Runner 抓取目标屏幕并运行 `image-parity`，Ledger 用哈希绑定的同一批输入重算。图标比形状（IoU ≥ 0.72、宽高比偏差 ≤ 0.20，可选颜色），铺满画面的图片比内容（相似度 ≥ 0.80）；MATCH → Green，MISMATCH（含文本不同、找不到节点）→ Red 并给节点级根因，无法比较 → Yellow。不依赖存量可运行：无 `baseline_ref` 的 PATH 只抓目标，coverage 须是冻结的 UI 目标，node_ids 属于其树并含每个检查的节点；runtime 目标仍须另有基线 PATH，带基线的 PATH 承载检查时节点须是基线观察到的。

**④ 非精确图形闸门。** 静态位图/矢量（bitmap、vector，或 raw/assets 中的静态图）用 `manual_exact` 代替精确复制时，item 恰有其一：`image_check`（已声明、被 visual PATH 承载、属于同一 source_resource+qualifier）或 `deviation` `{alternative, kind: redraw|degrade|absent, reason, evidence_refs?}`。`alternative` 必须是计划 `decision_envelope.allowed_alternatives` 的一项，由人类随计划 hash 批准。动画与 `.9.png` 无法离线测量，手工替换只能带 `deviation`；绘制代码按代码移植，保留经评审的 `manual_exact`；三者均不可挂 `image_check`。

## 最终报告的保真披露

GO migration-report 增加 visual_coverage 与 fidelity_limitations：逐模块/目标列 runtime 已验证、未验证、source-only、显式无 UI 或证据未知；只有当前基线已执行且 Green 的视觉路径可列 verified，source-only 业务 CASE 可 Green 但须说明未验证视觉保真；capture-fixture 另列"样本未证明在线服务/provider 等价"。`picture_fidelity` 逐项列非精确复制的图片：verified（图像检查所在 PATH 已执行且 Green）、not-verified、approved-deviation、reviewed（绘制代码/手工映射，仅评审）、blocked、unknown，未验证者同入 fidelity_limitations；另给 copied（按路径复制的文件数）、checks（各模块已检查/已豁免使用点数）和 parameters（[参数填充率](resource-transfer.md#参数填充)）。这些是证据覆盖说明，不新增阻塞门、不重染业务 CASE、不扩大 Auditor 复测范围；缺测 Yellow 仍按原控制流收尾。