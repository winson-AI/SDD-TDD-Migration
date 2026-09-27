# UI 保真控制道（吸收 lean 的 UI 证据与视觉对齐）

诊断：真实 Ledger run（demo_sdd_v3/v4/v5）虽走通事务流程，但**全程无 UI 证据/视觉验证**——UI 子模块从散文 scope 凭想象实现，无从存量抽取的 UI 树、无原始截图、无视觉 parity，且无 fail-closed 门禁。这是 UI 还原度差、边界不清的根因。本控制道把 lean 的 UI 管道（capture/ui-tree/aligner）作为**证据与门禁**吸收进 SDD 控制面：设备与截图由映射的 lean skill 提供，SDD 冻结并门禁其产物。

## 结构化 UI 边界（攻克“边界不清晰”）

UI scope 不再用散文墙，改为可校验载体：

- **capture 目标** `page_id:state_id:coverage`（coverage ∈ `viewport|scroll`），显式列出本切片覆盖的界面态。
- **稳定 id**：`screen:` / `node:` / `binding:` / `event:` / `resource:` / `interaction:`，SPEC 与 UI 模型互引。
- **显式 exclusions**：范围外界面态/手势/资源逐条声明（如 ForgotPassword 恢复流不呈现）。

## UI 证据绑定

`ui-component-spec` 语义模型携带 `ui_evidence`，随冻结经 [semantics.py](../../migration-ledger/scripts/semantics.py) 结构校验：

```jsonc
"semantic_model": {
  "kind": "ui-component-spec",
  "model_ref": {"path": "...", "sha256": "..."},
  "ui_evidence": {
    "ui_tree_ref": {"path": "...ui-tree.json", "sha256": "..."},   // lean 产出的合并 source+runtime UI 树
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

`ui_tree_ref` 与 `baseline_refs` 归档进 artifacts、hash 冻结；`coverage` 必须匹配 `page:state:(viewport|scroll)`。UI 树由映射的 lean skill（`android-to-kmp-lean` 的 collect/select/validate_ui_tree）产出，截图由 `mobile-ui-snapshot-capture` 的 `android-reference` 阶段产出。

## 强制开关

`ui_fidelity_required`（init/prepare 开关，默认关、向后兼容；UI 迁移建议开）由 [ui_fidelity.py](../../migration-ledger/scripts/ui_fidelity.py) 强制：

- **冻结门禁**：每个 applicable UI item 必须携带绑定 `ui_evidence` 的 `ui-component-spec` 模型（`semantics.ui_fidelity_gaps` 列缺口）；必须已判定存量可执行性；资源闭包不得缩减；`source_closure.ui_renderers` 必填；有基线的目标必须有 visual 路径。
- **实现门禁**：conformance 用 `baseline_conformance` 引用真正指导 coding 的基线或中间表征。
- **完成门禁**：`completion_gate` 拒绝仍带 `blocked` 资源的模块完成。
- **覆盖看板**：`status.semantic_index.coverage.missing` 暴露未附模型的 UI item。

## 基线前移：截图指导实现，而非事后比对（已实现）

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

- `visual` 路径必须绑定 `node_ids`（稳定 `node:` id）与 `baseline_ref`（[test_validation.plan_check](../../migration-ledger/scripts/test_validation.py)）；有 runtime 基线的 UI 目标必须有 visual 路径。
- 阶段顺序由 `tv.next_scope` 强制：**第二层需第一层 Green**（功能没走通时比对渲染无意义）；DoD 要求**全部三层路径 Green**（`tv.all_green`）。
- 视觉不对齐 = **Red + 节点级 root_cause** → 走 ④三态 / ⑤`diagnose` → 一轮 Fixer，**复用既有修复预算**（不另设轮次）。
- 声明的手势（`interaction:<id>`）必须由某条 visual 路径承载设备证据（`interaction_id`），静态路由不可替代。
- `source-only` 无第二层（无基线可比），按显式缺视觉证据收尾，不允许"没基线就免检"中间表征。
- 仅自动化环境缺失时，`automation-unavailable` 同时挂起 automation 与 visual 两层，沿用既有 Yellow 缺测收尾。

## capture / 构建产物契约（Wave B，已实现）

- **capture manifest（schema 2）** [capture_manifest.py](../../migration-ledger/scripts/capture_manifest.py):`COMPLETE` 必须有真实 screenshot/view_xml/meta 三元组 + 非空 captures + `observed_variant` + 记录 backend;`scroll` 只有 `scroll-complete` 才算达成(截断的 scroll-partial **永不**推进);`SOURCE_ONLY` 不得携带臆造 captures;缺 coverage 的旧记录不得升级为 viewport。
- **validation → 三态 + HAP** [lean_adapter.validation_summary](../../migration-ledger/scripts/lean_adapter.py):lean validator 的 compile/test/package 检查映射为三态(任一 failed → Red);`package` 通过必须记录产物,且 artifact 的 sha256 与当前文件**仍需匹配**(HAP 不能被换掉)。

## 精确性纪律（Wave A，已实现）

还原度差的根因不是验证不足，而是**允许了近似**。以下规则把"近似"从源头排除：

**① 资源精确策略 + 反近似禁令** —— [resource_fidelity.py](../../migration-ledger/scripts/resource_fidelity.py) 为 Resource 维 item 提供 `resource_strategy` 枚举（presence-triggered）：

| Android 源类型 (`resource_kind`) | 必须策略 |
|---|---|
| vector | `exact_vector_xml`（保留 viewport/path/group/clip/stroke/fill/alpha/mirroring；**不是** ImageVector） |
| bitmap / font / raw | `byte_copy`（字节级） |
| string / plurals / array | `value_xml_exact`（保留文本、占位符、转义、quantity/数组结构、限定符） |
| color / dimen / 已证 attr | `design_token_exact` |
| selector / layer-list / shape / 有状态绘制 | `compose_semantic_exact` |

**没有 `approximate` 策略**：禁止 Material 图标替代、手绘近似、语义近似、自动栅格化、位图兜底。逃生口仅 `manual_exact`（须 `adaptation_evidence_ref` 实证）与 `blocked`（须 `blocked_reason`）。专项规则：`.9.png` 的 stretch/content 区域**永不** `byte_copy`；`sp` 尺寸被间距消费时必须 `scales_with_font`（不得静默变固定 Dp）。

**② 闭包不得缩减** —— `ui_fidelity_required` 开启时，UI 树声明的每个呈现引用（含 `dynamicRules` 的代码态运行时覆盖）必须被某个 Resource item 覆盖（`source_resource`/`covered_resource_ids`），否则冻结被拒。不得只迁"方便转换的子集"。

**③ blocked 不得计入 Green** —— `completion_gate` 拒绝仍带 `blocked` 资源的模块完成。

**④ UI 树白盒（按 lean 真实契约）** —— [ui_tree.py](../../migration-ledger/scripts/ui_tree.py) 校验 `ui_tree_ref` 内容：`schemaVersion:1` + `scope`；`generatedFrom{sourceIndex,sourceIndexSha256,runtimeIndex,runtimeIndexSha256}` 合并溯源（runtime 两字段同有或同无）；`screens[]` 每屏一个递归 source-backed `root` + 分类 `attachments`（drawers/dialogs/menus/overlays/pagerPages/listItems/headers/footers，重复行只记一次）；节点含稳定 `node:` id、`presentation.resourceRefs`、`bindings`/`events`（稳定 id）、`dynamicRules{condition,resourceRefs}`、`capabilities`、`children`、可选 `runtimeObservations{pageId,stateId,…}`；`layoutClosure`/`criticalLayoutContracts`/`unresolved` 均为显式列表（冲突保留不得丢弃）。**source-only 树不得携带 runtimeObservations**；`visual_mode` 必须与 `generatedFrom.runtimeIndex` 是否存在一致——这保证 SDD 能直接消费 lean `validate_ui_tree.py` 的产物，稳定 id 也正是 visual 路径 `node_ids` 的来源。

**⑤ 源闭包含 mutating renderer** —— UI 适用时 `source_closure.ui_renderers` 必填：仅有 layout 不完整，必须点名真正改变可见状态的 Activity/Fragment/Adapter/ViewHolder/自定义 View 渲染者。

**⑥ 消费者接线纪律（anti-guess，协议）** —— 改任何源声明的 dimension/margin/padding/typography/color 前，须经 UI 树 + 资源映射追溯消费者：存在精确映射而消费者硬编码/猜测 → 必须改为接线映射值；映射缺失/错误 → 路由 Resource owner。**只有所有源值与运行时覆盖都接线后**，截图证据才可用于证明残余跨平台文本布局校正。机械面由 `dimensions.implementation` 的 Resource `target_resource_ref`/`consumer_ref` 必须匹配冻结值保障。

## 所有权（吸收 lean ownership，边界清晰）

| 角色 | 拥有 | 映射 lean skill |
|---|---|---|
| Capture | 设备/运行时截图证据与 manifest | mobile-ui-snapshot-capture |
| Implementer(Lean) | 源码分析、UI 树、OpenSpec、代码、消费者接线 | android-to-kmp-lean |
| Resource | 精确资源转换/source-target-consumer 映射 | android-resources-to-cmp |
| Test-Runner/Auditor | 独立编译/构建/HAP/测试裁决 | kmp-spec-build-validator |
| Aligner | 截图对齐比较，向 Resource 报资源缺陷 | kmp-ui-visual-aligner-node |

角色映射与接线契约见 [lean 集成](lean-integration.md)。设备/截图/HAP 不在 SDD 重造；SDD 冻结/门禁其产物。
