# UI 保真控制道（吸收 lean 的 UI 证据与视觉对齐）

诊断：真实 Ledger run（demo_sdd_v3/v4/v5）虽走通事务流程，但**全程无 UI 证据/视觉验证**——UI 子模块从散文 scope 凭想象实现，无从存量抽取的 UI 树、无原始截图、无视觉 parity，且无 fail-closed 门禁。这是 UI 还原度差、边界不清的根因。本控制道把 lean 的 UI 管道（capture/ui-tree/aligner）作为**证据与门禁**吸收进 SDD 控制面：设备与截图由映射的 lean skill 提供，SDD 冻结并门禁其产物。

## 结构化 UI 边界（攻克“边界不清晰”）

UI scope 不再用散文墙，改为可校验载体：

- **capture 目标** `page_id:state_id:coverage`（coverage ∈ `viewport|scroll`），显式列出本切片覆盖的界面态。
- **稳定 id**：`screen:` / `node:` / `binding:` / `event:` / `resource:` / `interaction:`，SPEC 与 UI 模型互引。
- **显式 exclusions**：范围外界面态/手势/资源逐条声明（如 ForgotPassword 恢复流不呈现）。

## UI 证据绑定（攻克“UI 还原度”，P1 已实现）

`ui-component-spec` 语义模型可携带 `ui_evidence`，随冻结经 [semantics.py](../../migration-ledger/scripts/semantics.py) 结构校验：

```jsonc
"semantic_model": {
  "kind": "ui-component-spec",
  "model_ref": {"path": "...", "sha256": "..."},
  "ui_evidence": {
    "ui_tree_ref": {"path": "...ui-tree.json", "sha256": "..."},   // 存量源码(+运行时)抽取的 UI 树
    "coverage": "login:phone:viewport",                            // page:state:coverage
    "visual_mode": "runtime | source-only"                         // 有截图证据 / 仅源码(显式限制)
  },
  "source": {"origin": "...", "locator": "...", "evidence_refs": []},
  "implementation_location": {"target_path": "/abs", "symbol": "..."}
}
```

`ui_tree_ref` 归档进 artifacts、hash 冻结；`coverage` 必须匹配 `page:state:(viewport|scroll)`；`visual_mode` 必填。UI 树由映射的 lean skill（`android-to-kmp-lean` 的 collect/select/validate_ui_tree）产出。

## 视觉对齐（攻克“UI 还原度”，P1 已实现）

带 `ui_evidence` 的 UI item，实现接受时其 `dimension_evidence[].semantic_conformance` 必须含 `visual_alignment`：

```jsonc
"semantic_conformance": {
  "model_ref": { ... },
  "evidence_refs": [ ... ],
  "visual_alignment": {"status": "aligned | source-only", "result_ref": {"path": "...", "sha256": "..."}}
}
```

`status=aligned` 需 `result_ref` 指向对齐结果（映射的 `kmp-ui-visual-aligner` 产出 `ALIGNED`）；`source-only` 仅当 `ui_evidence.visual_mode=source-only`（显式无截图证据），须在报告记差异。无 visual_alignment 的 UI 实现被拒——UI 还原不能以散文 fidelity 顶替截图 parity。

## 强制开关（P2，已实现）

`ui_fidelity_required`（init/prepare 开关，默认关、向后兼容；UI 迁移建议开）由 [ui_fidelity.py](../../migration-ledger/scripts/ui_fidelity.py) 强制：

- **冻结门禁**：开启后，模块四维分析中每个 applicable UI item 必须携带绑定 `ui_evidence`（ui_tree_ref + coverage）的 `ui-component-spec` 模型，否则 `freeze` 被拒（`semantics.ui_fidelity_gaps` 列出缺口 item）。这使"UI 从散文凭想象实现、无证据"无法冻结。
- **视觉 parity**：带 `ui_evidence` 的 UI item，实现接受时其 conformance 必须含通过的 `visual_alignment`（P1，`semantics.implementation` 强制）——冻结要证据、实现要 parity，二者合力 fail-closed。
- **覆盖看板**：`status.semantic_index.coverage.missing` 暴露未附模型的 UI item。

进一步的独立视觉对齐游标态（对应 lean `NEED_VISUAL_ALIGNMENT → ALIGNED`，把 parity 移到 build 之后的独立验证道、`NEEDS_UI_FIX` 回 owner ≤3 轮）为可选增强：当前冻结门禁 + 实现 parity 已达成"无证据不能冻结、无 parity 不能接受"的 fail-closed 目标。

## 所有权（吸收 lean ownership，边界清晰）

| 角色 | 拥有 | 映射 lean skill |
|---|---|---|
| Capture | 设备/运行时截图证据与 manifest | mobile-ui-snapshot-capture |
| Implementer(Lean) | 源码分析、UI 树、OpenSpec、代码、消费者接线 | android-to-kmp-lean |
| Resource | 精确资源转换/source-target-consumer 映射 | android-resources-to-cmp |
| Test-Runner/Auditor | 独立编译/构建/HAP/测试裁决 | kmp-spec-build-validator |
| Aligner | 截图对齐比较，向 Resource 报资源缺陷 | kmp-ui-visual-aligner-node |

角色映射与接线契约见 [lean 集成](lean-integration.md)。设备/截图/HAP 不在 SDD 重造；SDD 冻结/门禁其产物。
