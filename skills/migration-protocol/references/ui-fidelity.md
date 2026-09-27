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

## 强制开关与状态机道（P2，规划）

P1 为 presence-triggered（带 ui_evidence 才强制其后续）。P2 引入 `ui_fidelity_required`（init/prepare 开关，默认关，UI 迁移建议开）：

- 开启后，UI owner 的 case 若无 `ui_evidence`（coverage/ui_tree_ref）**不能冻结**；无通过的 `visual_alignment`（或显式 source-only+记差异）**不能 DoD/Green**。
- 新增视觉对齐游标态（对应 lean `NEED_VISUAL_ALIGNMENT → ALIGNED`）：Test-Runner build/automation Green 后，UI case 进入 alignment，由映射 Aligner 产出结果；`NEEDS_UI_FIX` 路由回 Implementer/Resource owner（≤3 轮，沿用修复预算）。
- `status.semantic_index.coverage.missing` 已暴露未附模型的 UI item，作为覆盖看板。

## 所有权（吸收 lean ownership，边界清晰）

| 角色 | 拥有 | 映射 lean skill |
|---|---|---|
| Capture | 设备/运行时截图证据与 manifest | mobile-ui-snapshot-capture |
| Implementer(Lean) | 源码分析、UI 树、OpenSpec、代码、消费者接线 | android-to-kmp-lean |
| Resource | 精确资源转换/source-target-consumer 映射 | android-resources-to-cmp |
| Test-Runner/Auditor | 独立编译/构建/HAP/测试裁决 | kmp-spec-build-validator |
| Aligner | 截图对齐比较，向 Resource 报资源缺陷 | kmp-ui-visual-aligner-node |

角色映射与接线契约见 [lean 集成](lean-integration.md)。设备/截图/HAP 不在 SDD 重造；SDD 冻结/门禁其产物。
