# Bundled knowledge in SDD

This is an adapter to the current SDD workflow. Bundled knowledge is advisory source material, not a second controller. `knowledge-query` and `knowledge-diagnose` only read the bundle and write their result/receipt in the current run's assigned staging directory. They do not install dependencies, run probes, modify the target, submit Ledger events or change acceptance.

## Ownership and retained evidence

Use the absolute `run_root`, `change_root` and `storage_layout` provided by prepare/Ledger. Never infer these paths from the working directory.

| Knowledge concept | SDD owner and artifact |
| --- | --- |
| Active slice/work packet | Current GO/MO allocation or frozen TASK scope and its Ledger assignment |
| Platform capability decision / UI contract | Spec-Designer records source evidence and chosen route in the applicable UI/Logic/Adhesive/Resource analysis and frozen OpenSpec design/tasks; map CASE/PATH/ASSERT explicitly |
| Layout/node/platform implementation mapping | Implementer/Fixer supplies task_trace and dimension_evidence with target file/symbol, source node/attribute/resource mappings and production bindings in the submitted implementation; detailed evidence is hash-referenced from the assigned staging directory |
| Capability, package or runtime validation result | Test-Runner's current frozen PATH/ASSERT result, execution receipt and evidence; MO or Auditor owns acceptance for its phase |
| Dependency/version guidance | Hash-bound knowledge_refs and dependency_resolution_ref; verify installed SDK, target TOML, build and runtime separately |
| Consistency analysis/report | Current role's `.sdd-runs/<run_id>/staging/<instance_id>/<request_id>/`; real build evidence uses the existing `runs/build` runner, Harmony evidence uses `runs/harmony` |

Long-lived user configuration stays in `.sdd-migration`. Per-run evidence stays in `.sdd-runs/<run_id>`. Frozen SPEC and status projections stay in the parallel top-level `openspec` hub under its run-specific paths. Target source edits are the only exception. Do not create an upstream `.a2c` tree, independent migration contract, implementation ledger or validation state machine. Use the actual controller-provided paths; examples are not permission to write another role's directory.

## Evidence and execution limits

Catalog versions, upstream `verified` flags, device/API observations and recipes describe the bundled snapshot, not this target. Record the snapshot/hash, then verify the actual target. External-capability search returns candidates with both record and cookbook references; the upstream standalone probe is explicitly unsupported and not imported. Spec-Designer may design equivalent target-local checks in the existing frozen test plan. Execution still requires coding/build/assignment gates and the current Test-Runner flow.

No catalog match does not prove a capability impossible. Continue through source/target/SDK analysis and the existing reuse, adapt, reference or new implementation routes. Do not weaken fidelity to fit a catalog.

Fix actions described in recipes belong to Implementer/Fixer within the frozen task and existing repair budget. Test-Runner records failures; Auditor reviews and delegates, without writing code. Automatic test environment failures remain Yellow/unexecuted for the relevant paths and follow `automation-unavailable`; they do not block unrelated work or claim Green. New scope or acceptance changes follow the existing CR/human decision rules.

UI capture, numeric scoring and semantic checks remain evidence producers. Stable screenshot targets and transient behavior checks are planned separately; final acceptance uses the formal SDD paths and role boundaries. No knowledge document grants another repair loop or independent visual controller.
