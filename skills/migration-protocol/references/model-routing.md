# 两层模型路由

弱推理任务（执行命令、采集与比对观察结果）走**低成本模型**；强推理任务（切片/四维/语义设计、根因、裁决）走**配置的强模型**。控制器不派发 Agent、不调模型，因此它只**建议档位（tier）并在游标上暴露**、**禁止把强推理步骤降级到低成本模型**、并**留存宿主实际调用的模型**供排查；宿主解析 tier→model 并 dispatch。策略见 [model_routing.py](../../migration-ledger/scripts/model_routing.py)。

## 配置（project-context 的 `runtime.model_routing`）

```jsonc
"runtime": { "model_routing": {
  "strong":   {"model": "<强模型 id>", "endpoint": "...", "api_key": {"env": "SDD_STRONG_MODEL_KEY"}},
  "low_cost": {"model": "<低成本模型 id>", "endpoint": "...", "api_key": {"env": "SDD_LOW_COST_MODEL_KEY"}},
  "default_tier": "strong",
  "overrides": { "<role|operation>": "low_cost|strong" }
}}
```

密钥走 env 引用，不入 Ledger。[project_context.py](../../migration-ledger/scripts/project_context.py) 在 prepare/update 时结构校验（strong/low_cost 的 model 非空、tier 合法、override 不得把强推理步骤降级）。

## 档位策略

| tier | 步骤 | 说明 |
| --- | --- | --- |
| **low_cost** | Test-Runner execute（跑 build/automation、采断言）、`accept`/`submit`/`dependency-ready`/`audit-retest`/`automation-resume` 等机械步、Harmony Executor | 执行 + 确定性判定 |
| **strong**（默认） | GO、Spec-Designer、父 MO decompose、Implementer、Fixer、Diagnostician、Auditor、Harmony Planner/Verify | 设计/迁移/分析/根因/裁决 |

- **不可降级（strong-only）**：`spec-designer`/`diagnostician`/`auditor` 角色，`plan`/`freeze`/`diagnose`/`audit-plan`/`audit-verdict`/`audit`/`problem-audit` 操作——`enforce` 拒绝其使用 low_cost。
- **升级信号**：模块存在未确认根因的失败、`no_progress_rounds>0` 或有 `repair_findings` 时，`reasoning_escalated` 让该步强制 strong（“判断观察结果”不确定时用强推理）。确定性断言比对本由 [execute_test.py](../../migration-ledger/scripts/execute_test.py) 完成，非模型任务。
- Implementer 默认 strong（迁移常需理解语义），可经 override 调整；strong-only 步骤不可 override 降级。

## 游标建议（status.next_steps[].model_tier）

`status` 的每个 `next_steps`（及 `global_next_step`）附 `model_tier`，由角色/操作查策略表并叠加升级信号得出。宿主读它，用 `runtime.model_routing` 解析出的模型 dispatch。该字段为纯建议、始终存在、向后兼容。

## 实际模型留存（辅助排查）

宿主 dispatch 时把实际调用的模型回填进 `assign`/`session`/`audit-assign` 的 payload：

```jsonc
{"operation": "assign", "payload": {"role": "test-runner", ..., "model": "<实际模型 id>", "model_tier": "low_cost"}}
```

- presence-triggered：不带 `model`/`model_tier` 则不记录、不影响既有流程；带则 `enforce` 校验不违反 strong-only，并存入 assignment/session（不可变落 `events.jsonl`）。
- 投影 `ledger/model-usage.json`（可重建）逐条列 `{scope, kind, role, assignment_id/session_id, model, model_tier}`；`status.model_usage` 返回同一视图，并写入人读的 `reports/workflow-attention.md`（Model usage 段）。排查时对照“建议 tier（next_steps.model_tier）↔ 实际模型（model_usage）”定位错配。

## 边界

控制器只声明 tier、禁止降级、留存实际模型；真正用哪个模型由宿主 dispatch 决定（同 Agent 派发边界）。不做成本核算或用量统计。

Harmony 在 sandbox 内自带 Planner/Executor/Verify 三档模型配置：**Planner 与 Verify（观察结果判断）使用其各自配置的强档模型（strong）**，Executor（执行命令）对应 low_cost。SDD 的 tier 路由治理宿主派发的角色（test-runner 的命令执行/采集属 low_cost），Harmony 内部模型由 harmony-config 独立提供、不经 tier 解析；二者命名对齐，无需改 Harmony 代码。
