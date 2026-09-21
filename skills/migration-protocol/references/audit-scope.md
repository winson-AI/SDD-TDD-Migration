# Auditor：整体代码治理、遗留复核与一轮修复

## 入口与范围

Auditor 在所有父/子 MO 的本轮实现、编译构建、自动化测试及本地修复收尾后统一启动。完成 DoD 或有本模块证据的明确挂起/automation-deferred，父汇总有效、无活动 worker、无可推进动作，才满足门禁；不要求所有模块已经 Green。单模块失败不能提前启动 Auditor 或结束其他 MO。

**遍历全部模块，收集 Red/Yellow；绝不默认重跑全部测试用例。** `global_test_paths`（Ledger 中为 `global_paths`）是可选的额外运行级用例，不是启动开关，缺省或 `[]` 均合法。复核的主要依据来自模块自己的冻结 SPEC、Testing list、PATH/ASSERT 和 Ledger 结果。

## 代码治理前置

先执行 [audit-code-review](audit-code-review.md)：审查所有模块改动、重构、冗余、二方库复用与公共能力。即使测试全 Green，也不能跳过。治理批次先委派 Fixer（需新任务/边界则 CR/人工重规划）、完整回归实际影响范围；刷新当前基线审查后，再收集剩余 Red/Yellow。Auditor 自己不写代码。

## 问题处理

1. GO `audit-collect` 固定当前遗留 finding、来源模块、SPEC/测试路径及基线；纯自动化环境缺测汇入收尾待验证清单，不强制当成代码缺陷。
2. Auditor 逐 finding 读取 SPEC/tasks/CASE/PATH、断言和根因证据，提交 `audit-plan`。可直接复核的用 `verify`；已有根因需要补丁的用 `fix`；业务边界不明/不可修复的用 `human`。
3. GO 审核路由，负责模块 MO `audit-work`，委派**一轮 Fixer**。同 owner 的相关问题合并处理；Auditor 自己不修代码、不修改验收标准。
4. 修复后的正式 Testing 复核和必要的受影响回归必须留新执行回执、assert、基线与 `retest_of`。一轮仍 Red/Yellow，则记录根因及证据待人工，不自动重复修复。环境仍不可启动则明确 Yellow/未测试。
5. Auditor `audit-verdict` 验收，Ledger 记录结果与修复 memory；独立分支继续，失败只影响有依赖关系的分支。父 MO 刷新汇总后，独立审阅收尾。

当前 `audit_batch.work_modules` 包括发现模块、根因 owner 和依赖图中的受影响下游。由于代码基线按模块管理，这些模块采用保守的完整模块回归，代码改变后重新构建。范围扩展必须能追溯到 finding、owner 与依赖边；**不能把无关 Green 模块加入回归，也不能在问题闭环后再跑一遍全项目**。完整测试定义仍保留用于理解与覆盖核对，不等于全部加入最终执行清单。

## 收尾的实际执行契约

`audit-assign` 不检查 global_paths 非空。Ledger 的 `audit_scope(state)` 生成本轮执行集合，并固定到 assignment：

- `scope_policy: non-green-only`。
- `path_ids`：当前模块结果为 Red/Yellow 的 PATH；已由问题闭环复核通过的不再加入。
- 若用户另外声明了运行级 global_paths，仅加入其中非 Green、从未验证或代码基线已失效的路径。未验证不能隐式算 Green；已有效 Green 的额外路径同样不重复执行。没有额外运行级用例时无需补造它们。
- 有效构建 Green 不因自动化缺测被重跑或覆盖。对原 automation-deferred 模块补验时合并 PATH 结果，保留原构建证据。

| 清单 | 上下文门禁 | 动作与报告 |
| --- | --- | --- |
| 非空 | audit-testing | 独立执行 assignment.path_ids；`kind=tests`，完整提交本清单结果和 snapshot |
| 空 | audit-verdict | 核验已接受模块/问题闭环证据；`kind=audit-review`、`paths=[]`、`execution_status=no-retest-needed`、`review_ref` 和 snapshot；不启动测试、不要求自动化环境 |
| 非空、仅自动化环境不可用 | blocked audit-testing | `audit-unavailable` 记录选中路径 Yellow/未执行并收尾，保留已有 Green；不宣称功能通过 |

空清单仍需独立 Auditor 审阅，不能自动生成通过结论。`audit-review` 不能关闭尚有待复核路径的 assignment；正常 `tests` 报告不能用空 paths 冒充测试。模板见 [audit-review.json](../../../template/audit-review.json)。审计结果的 quality 表示证据裁决，execution_status 区分是否实际执行；不要把 no-retest-needed 写成“全部独立复测通过”。

## 已有空配置 run 的恢复

升级本包后，直接对原 run 查询：

```sh
python3 <package_root>/skills/migration-ledger/scripts/ledger.py status --root <run_root>
```

读取 `module_rounds`、`global_next_step`、`context_gate` 后，宿主按下一动作提交事件及实际启动对应 Agent。无需重新 init、无需修改 input/snapshot/global.json、无需给 global_paths 补假用例：

- 尚有模块工作：继续对应 MO，等待全部收尾。
- 有代码/依赖等遗留：audit-collect → 根因路由 → 一轮 Fixer/Testing → 裁决。
- 仅缺测或模块均 Green：audit-assign，按 Ledger 的路径清单选择复核或独立审阅。
- 若旧版全量 audit assignment 仍活动：status 提示 audit-revoke；宿主确认旧 worker 已停止并留证后撤销，再创建新 assignment。不得边运行旧审计边替换范围。撤销不返还既有预算。

宿主仍负责启动 subagent、加载对应 skills、执行脚本及绑定真实身份；Ledger 只治理状态、范围、证据与门禁。
