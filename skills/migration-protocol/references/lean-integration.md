# lean 技能集成：作为 SDD 角色的领域 worker

SDD 是治理/控制面（事务化 Ledger、并行 MO、独立审计、四维/语义/模型路由、fail-closed 留存），lean bundle 是 Android→KMP 领域执行（UI 树抽取、视觉对齐、Foundation 知识、依赖解析、Git 纪律）。二者互补：**不重造 lean 的领域能力，而让 SDD 的角色把 lean 的 skill 当作真实派发的 worker**，由 Ledger 冻结/审计/并行治理，lean 输出经转换成 Ledger 事件与冻结证据。这同时吸收 lean 全部优势并解决“宿主未接线”缺口。

## 角色映射

| SDD 角色 / 操作 | lean skill（worker） | 产出 → Ledger |
|---|---|---|
| Implementer（frozen→implementing→submit） | `android-to-kmp-lean`（IMPLEMENT/REMEDIATE） | implementation-result → `submit`（code_files/task_trace/dimension_evidence，含 UI 树 ref、visual_alignment、semantic_conformance） |
| Resource（子任务/资源维） | `android-resources-to-cmp` | resource-result.resourceMappings → dimension Resource item 的 target/consumer 证据 |
| Test-Runner / Auditor（build/automation/audit） | `kmp-spec-build-validator` | validation-result（compile/test/package/HAP checks）→ tests 结果三态 + audit 复核 |
| Aligner（P2 视觉对齐道） | `kmp-ui-visual-aligner-node` | alignment_result(ALIGNED) → UI item 的 `visual_alignment.result_ref` |
| Capture（UI 证据前置） | `mobile-ui-snapshot-capture` | capture manifest(page:state:coverage) → UI 模型 `ui_evidence.ui_tree_ref/coverage` |

宿主按 [宿主接入契约](host-integration.md) 派发对应 skill，把其 result 文件经 `submit`/`accept`/`audit` 提交 Ledger；lean 的 session 复用与 handoff-minimization 与 SDD 的 session/checkpoint 对齐。`/sdd-verify` 与四维/语义门禁照常校验。

## 产物转换（lean → SDD 证据）

[lean_adapter.py](../../migration-ledger/scripts/lean_adapter.py) 把 lean 的 UI 保真产物转成 SDD 证据形状（结构校验、绝不伪造 ALIGNED）：

| lean 产物 | 适配器 | → SDD 证据 |
|---|---|---|
| capture manifest 条目 `{page_id,state_id,coverage,status}` + 抽取的 ui-tree | `ui-evidence` | `semantic_model.ui_evidence{ui_tree_ref, coverage=page:state:coverage, visual_mode}`（COMPLETE→runtime、SOURCE_ONLY→source-only） |
| alignment-result `{status}` | `visual-alignment` | `semantic_conformance.visual_alignment{status, result_ref}`（ALIGNED→aligned、RUNNABLE_PARTIAL→source-only、其余拒绝并 NEEDS_UI_FIX 回 owner） |

```sh
python3 <pkg>/skills/migration-ledger/scripts/lean_adapter.py ui-evidence --capture <entry.json> --ui-tree <ui-tree.json>
python3 <pkg>/skills/migration-ledger/scripts/lean_adapter.py visual-alignment --alignment <alignment-result.json>
```

其余映射（implementation-result → dimension_evidence/code_files/task_trace；validation-result checks → tests 三态；resource-result → Resource 维证据）字段较多、含 SDD 专属元数据（freeze_id/assignment_id/断言集合），由宿主按上表所有权对照组装 SDD payload，适配器只固化最清晰、直接服务 UI 保真的两项转换。

## Wave-1 吸收（协议 + 轻量脚本，规划）

从 lean 吸收、融入 SDD 冻结/修复门禁：

1. **Foundation/迁移知识 gate**：引入策展 `knowledge-index` + `query_knowledge`（按切片触发主题、按稳定错误 diagnose→cookbook）+ `foundation_gate resolve`（冻结前解析 target 敏感依赖的确切版本与 API 子闭包）。融入 [reuse.py](../../migration-ledger/scripts/reuse.py)，作为 `dependency_resolution_ref` 冻结前置。
2. **依赖决策阶梯**：在 reuse 的 `reuse/adapt/reference/new` 之外补 `subclosure-port`（按 pin 版查 SCM 源做最小隔离子闭包）与 `capture-fixture`（capture 派生 fixture 置于可替换 Repository/DataSource 边界，OpenSpec/结果/裁决须披露）。
3. **Grill 纪律**：澄清门只问不可逆的用户产品决策，不问可从源码/目标/SDK/capture 查得的事实——降低人工门噪音，融入上下文就绪与 boundary_review。
4. **Git 纪律**：pre-migration baseline commit、`a2c/<change-id>` 分支、`generatedTrackedPaths` 处理、单一迁移 commit、不 stage 既有脏文件——作为宿主归档/合并纪律（SDD 不自动合并）。

## 边界（诚实）

设备/HDC/截图/HAP/视觉模型由 lean skill 执行，SDD 不重造；SDD 只冻结/门禁其产物并做跨模块治理。lean 的扁平单切片被 SDD 的 GO/父/子并行分解与独立审计取代；lean 的“游标即控制态、子工件为真相”被 SDD 的事务化 events.jsonl 取代（避免绕过）。UI 保真具体门禁见 [UI 保真控制道](ui-fidelity.md)。
