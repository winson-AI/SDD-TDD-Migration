# UI 保真控制道（UI 证据与视觉对齐）

UI 实现需有存量源树、明确 page/state/coverage 和实际可得的运行时基线。SDD 按现有角色使用领域工具：Spec-Designer 分析、Implementer 精确转换资源并接线、Test-Runner 执行功能与视觉取证、Fixer 修复、Auditor 独立裁决。设备 Capture 由宿主授权的执行者按 [受限视觉执行工具](visual-execution.md) 或既有 adapter 执行，原始产物与转换证据经 Ledger 冻结/验收；不整包加载外部实现或对齐技能来合并权限。见 [受限接入](domain-tools.md)。

## 结构化 UI 边界（攻克“边界不清晰”）

UI scope 不再用散文墙，改为可校验载体：

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

分类以实际行为与需求为准，不根据状态名字猜测。测试可使用受控时钟或可控响应验证瞬态转换，但不能改变生产时序来凑截图。没有瞬态状态时无需空记录；source-only 的稳定状态沿已有保真限制披露。缺少瞬态截图不产生额外 Yellow，也不降低已完成稳定目标的视觉结论；缺少其行为测试仍是原 CASE/PATH 的覆盖缺口。父 MO 汇总及 Auditor 审阅均沿用冻结分类，不能删除行为义务或临时扩大截图清单。输出样式见 [UI 状态测试表](../../../template/ui-state-test-design.md)。

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
- **实现门禁**：conformance 用 `baseline_conformance` 引用真正指导 coding 的基线或中间表征。
- **完成门禁**：`completion_gate` 拒绝仍带 `blocked` 资源的模块完成。
- **覆盖看板**：`status.semantic_index.coverage.missing` 暴露未附模型的 UI item。


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

正式视觉 Green 要求 `record.visual_alignment` 与本次执行回执中的 `captured.visual_alignment` 完全一致：包含冻结 PATH 的 coverage/node_ids/baseline_ref、模块当前 code_baseline、实际可校验 hash 的 hap_ref；HAP 属于当前已接受 build_artifacts。声明 interaction_id 时，execute_test 从冻结 dimension model 提取完整 frozen_interaction（id/action/from/expected，可选 spec_ref）写入 query；GLOBAL 自有 PATH 可冻结自己的 frozen_interaction。proof.required_interaction 必须与冻结声明一致，interaction_checks 提供唯一同 ID 的 PASSED、相同 action、满足冻结 expected 的 observed、同 hap_sha256/代码基线及真实 evidence_ref。只有同名 ID 或 PASSED 文本不够，结果不能另声明一个更容易的动作或目的页面。adapter 与正式 Green 门禁分别核对。Red/Yellow 可保留不完整证据及具体原因，不能为了缺设备而伪造哈希或通过。未完成自动化仍按 Yellow/未执行收尾，独立模块和可用构建下游继续。现有 execute_test 可通过 lean_visual_adapter 接入原始比较结果，最小调用与布尔断言限制见 [接入协议](domain-tools.md)。

automation 手势使用 [interaction-evidence.json](../../../template/interaction-evidence.json) 的条件扩展：正式 Green 同样核对冻结完整动作、起点、预期、当前 HAP/代码及实际观测，record 与原始 report 的 interaction_evidence 必须一致。不要求截图基线，不从 expected 合成 observed。默认 Harmony 未产出该结构化证据时，已执行断言保留并规范化为 Yellow（interaction-evidence-unavailable），可以正式提交；真实 Red 不被覆盖。能力缺失沿现有预检/Yellow 收尾，不新增全局阻塞。

## capture / 构建产物契约

Green 还须带 `alignment_root` 与从原始 alignment 推导的 `comparison_evidence`。逐 round/page/state/reference_capture_index/candidate_capture_index 选取 manifest 中的截图，核对 score 的 reference/candidate 摘要；semantic 必须绑定该 score_sha256 或同一图片对，同时提供两者时全部核验。正式门禁重读 evidence_ref 推导相同结果，不能自填“已经关联”。ALIGNED_CARRIED 保留原 ALIGNED 的完整对齐证据，并用 regression_score 绑定 carried_from_round 与当前 capture_round 的 Harmony 截图（regression_capture_index 默认 0）；仍须明确 ALIGNED 裁决，分数本身不自动通过。

adapter 与正式 submit/accept/Auditor 共用 [visual_evidence.py](../../migration-ledger/scripts/visual_evidence.py)：从所属叶子冻结模型重取完整 Android capture 记录及 baseline_refs，核对每屏、顺序和原始元数据，不能只保持首屏相同后替换其他屏。候选 snapshot 必须关联 capture_execution_ref；重读当前 run 内的装机回执、真实命令日志、截图/树/hash，推导 capture_evidence，绑定实际安装 HAP、设备及代码基线。原生捕获自动生成；外部运行器按 [捕获回执模板](../../../template/visual-capture-execution.json) 留真实 sidecar。仅修改 alignment 标签或增加自述字段不足以通过。carried 历史轮次核对自己的构建/代码，当前轮次严格绑定当前基线。

GLOBAL 自有 visual PATH 必须显式冻结 visual_evidence（coverage、visual_mode=runtime、capture_manifest_ref、完整 baseline_refs）；build_binding 仅确定构建归属，不能代替 UI 原始证据。缺原始记录/执行回执只保留局部 Yellow，不能正式 Green；不影响其他模块及 Auditor 缺测收尾。

Auditor 按 PATH 保留所属模块的 build_artifacts，不能借用其他模块的 HAP。可选 GLOBAL visual PATH 在规划时声明 `build_binding: {module_id, path_id}`，指向负责项目集成构建的冻结 build PATH；实际 Green 只接受该 PATH 在当前模块基线的已接受构建产物。GO/MO 审查该构建命令是否覆盖此全局用例依赖；缺少绑定不会借用全局产物池，也不要求重跑已有 Green。普通模块 PATH 不需要新增全局字段。

- **capture manifest（schema 2）** [ui_evidence.validate_capture](../../migration-ledger/scripts/ui_evidence.py):`COMPLETE` 必须有真实 screenshot/view_xml/meta 三元组 + 非空 captures + `observed_variant` + 记录 backend;`scroll` 只有 `scroll-complete` 才算达成(截断的 scroll-partial **永不**推进);`SOURCE_ONLY` 不得携带臆造 captures;缺 coverage 的旧记录不得升级为 viewport。
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

**没有 `approximate` 策略**：禁止 Material 图标替代、手绘近似、语义近似、自动栅格化、位图兜底。逃生口仅 `manual_exact`（须 `adaptation_evidence_ref` 实证）与 `blocked`（须 `blocked_reason`）。专项规则：`.9.png` 的 stretch/content 区域**永不** `byte_copy`；`sp` 尺寸被间距消费时必须 `scales_with_font`（不得静默变固定 Dp）。

**② 闭包不得缩减** —— `ui_fidelity_required` 开启时，UI 树声明的每个呈现引用（含 `dynamicRules` 的代码态运行时覆盖）必须被实际 Resource item 覆盖，否则冻结被拒。逐 `source_resource + qualifier` 留真实源、策略、目标及消费者证据；裸 `covered_resource_ids` 不计入覆盖。资源分组使用现有 TASK/dimension_trace；附加资源及别名分别登记源事实，不能用一个主资源代证其余资源。

声明的 resource_kind 必须与 source_resource_ref 指向的真实文件/values 条目一致。冻结与受限资源转换读取源事实，校验 qualifier、.9.png、sp 单位；byte_copy 导入校验源目标字节相等。资源扫描、任务授权、单项 values 转换与变体映射见 [资源接入](domain-tools.md#资源执行与事实绑定)。

进一步从本 UI 树实际引用到的源索引逐 `source_resource + qualifier + path` 核验闭包：每个适用变体恰有一个 Resource item，并与 collector 保存的源文件 SHA、实际文件及 Resource source_resource_ref 一致。base 覆盖不能代替 night/语言等变体。明确不属于当前切片的候选通过 ui_evidence.resource_scope.exclusions 逐项说明 source_resource/qualifier/path、reason 与 evidence_refs；排除证据持续校验，不能排除配置范围中明确启用的 qualifier。未被本树引用的资源不扩大门禁。旧索引缺少资源 hash 或已过期时重新抽取、审查与冻结，不给旧提取值补上当前 hash。res/color* 的状态选择器按 selector/compose_semantic_exact 处理，不能伪装为固定 color token。

**③ blocked 不得计入 Green** —— `completion_gate` 拒绝仍带 `blocked` 资源的模块完成。

代码中的 `R.id` / `android.R.id` 保留为节点定位事实，不按独立资源文件查找。`@array` 能发现 string-array 与 integer-array，并以 array 精确迁移；不丢失元素结构。Android 平台引用（`@android:` / `?android:`）须在 Resource item 声明 platform_resource.api_level 与 sdk_metadata_ref，后者指向真实 SDK source.properties；source_resource_ref 必须位于同 SDK 的 data/res 且包含匹配定义。冻结与后续计划读取持续核验 API、摘要、kind/qualifier/配置路由。SDK 文件为只读来源，分析资产仍留在当前 run。缺 SDK 定义可显式 blocked 留缺口，不伪造源码或一律拒绝所有平台资源。示例见 [semantic-model.json](../../../template/semantic-model.json)。

视觉复测要求最新 capture 属于当前 assignment/fence；semantic 中仍有问题或不可比判断时需逐项有据裁决，详见 [视觉执行](visual-execution.md)。

**④ UI 树白盒（按原生采集器真实契约）** —— [ui_evidence.validate_tree](../../migration-ledger/scripts/ui_evidence.py) 校验 `ui_tree_ref` 内容：`schemaVersion:1` + `scope`；`generatedFrom{sourceIndex,sourceIndexSha256,runtimeIndex,runtimeIndexSha256}` 合并溯源（runtime 两字段同有或同无）。`screens[]` 每屏包含 id/name/kind、递归 source-backed `root` 与 `attachments[]`；attachment 是带 id/kind/anchorNodeId/root 的对象，kind 使用 drawer/dialog/menu/overlay/pager_page/list_item/header/footer，重复行只记一次。节点包含 id/name/nodeKind/viewClass/analysisStatus、source{path,selector,origin,line}、initialVisibility、layout{kind,scrollable,rawAttrs,resolvedAttrs}、presentation.resourceRefs、bindings[]、events[]、dynamicRules[]、capabilities 对象与 children[]。binding 需 target/source，event 需 trigger/handler，dynamic rule 需 when/property/result；各记录都带 sourcePath 与 line 或 selector。可选 runtimeObservations{pageId,stateId,…} 只记录实际运行观察。`layoutClosure` 完整映射源布局和 XML selector；criticalLayoutContracts/unresolved 是显式列表，冲突不得丢弃。source-only 树不得携带 runtimeObservations，visual_mode 须与 runtimeIndex 是否存在一致。完整模板见 [semantic-model.json](../../../template/semantic-model.json)，测试用真实 collector 产物实例化该模板后调用原生严格 validator；不能只检查 JSON 语法或替换模板树后再声称模板通过。

**⑤ 源闭包证据面** —— UI 适用时 `source_closure` 必填 `ui_renderers`（仅有 layout 不完整，必须点名真正改变可见状态的 Activity/Fragment/Adapter/ViewHolder/自定义 View 渲染者），以及 `ui_topology`（布局/对话框/菜单/标签/浮层及初始可见性）、`states`（实际存在的 loading/content/empty/error/disabled/transient/refresh/retry/pagination）、`navigation`（目标身份/参数/返回行为/范围外副作用）、`platform_lifecycle`（权限/存储/网络/回调/后台/取消/宿主窗口）。散文控件清单不算闭包。证据质量纪律：**listener 只证事件绑定，不证 UI 层级；类型声明只证 API 形状，不证生产调用路径**；基础工作在被用户可见行为消费前不算已交付切片。资源面由上面的②闭包不得缩减更强地保障，不在此重复要求。

**⑥ 消费者接线纪律（anti-guess，协议）** —— 改任何源声明的 dimension/margin/padding/typography/color 前，须经 UI 树 + 资源映射追溯消费者：存在精确映射而消费者硬编码/猜测 → 必须改为接线映射值；映射缺失/错误 → 路由 Resource owner。**只有所有源值与运行时覆盖都接线后**，截图证据才可用于证明残余跨平台文本布局校正。Resource 的 `consumer` 支持单值或列表；实现证据以 `consumer_refs` 逐文件覆盖冻结消费者，兼容旧单值 `consumer_ref`，并持续校验 hash。文件引用正确只证明读取对象一致，生产接线语义仍由角色审阅及正式测试验证。

## 所有权

| 角色 | 拥有 | 受限工具边界 |
|---|---|---|
| Spec-Designer | 源码分析、UI 树、OpenSpec 与冻结基线 | analyze-ui/validate-ui，不改目标源码 |
| Implementer | 冻结任务内代码、精确资源与消费者接线 | resource-convert 支持 vector/byte_copy/单项 values，先校验任务 scope 与冻结映射；不接管设计/验收 |
| Test-Runner | 正式构建、功能测试、设备取证与视觉比较 | execute_test + visual-install/capture + compare-only/semantic-inspect；工具完成或评分不能单独给 ALIGNED |
| Fixer | 授权范围内实现/资源补丁 | 原预算，修复后正式复测；不能改冻结验收 |
| Auditor | 独立代码审查与验收 | 在选定审计 PATH 上独立取证/比较/复测，不兼代码或脚本作者 |
| Host | 按声明目标与权限执行 Capture、派发角色 | 保留实际设备与传输证据，不以结果文件自述替代 |

角色与接线契约见 [领域工具受限接入](domain-tools.md)。不完整加载外部实现或对齐技能，不另设资源/对齐编排循环；所有结果仍由 SDD 当前 owner 经 Ledger 接受。

## 最终报告的保真披露

GO migration-report 增加 visual_coverage 与 fidelity_limitations：逐模块/目标列出 runtime 已验证、未验证、source-only、显式无 UI 或证据未知。只有当前基线已执行并 Green 的视觉路径可列 verified；source-only 业务 CASE 可以 Green，但报告必须说明未验证视觉保真。capture-fixture 另列“样本未证明在线服务/provider 等价”。这些是证据覆盖说明，不新增阻塞门、不重染业务 CASE、不扩展 Auditor 复测范围。缺测 Yellow 仍按原控制流收尾。
