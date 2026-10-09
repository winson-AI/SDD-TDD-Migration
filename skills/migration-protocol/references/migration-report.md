# GO 迁移收尾报告

## 总则

父 MO 统一命名 `parent-mo-<module_id>`，例如 parent-mo-M010；宿主读取父步骤的 agent_name，并在创建/恢复时保持可见名称一致。GO 收尾必须向用户提供全部测试 CASE 状态，非 Green 汇总原因与证据；读取 Ledger 生成的 `<run_root>/reports/migration-report.md` 与 `.json`，不省略缺测、不用构建 Green 代替功能验证。

## 必须展示的信号

GO 在本轮成功完成、带自动化缺测结束或需人工处理而停止时，向用户提供完整报告；运行中查询只提供明确标注的进度快照。报告必须包含：

1. run_id、入口范围、Ledger sequence、当前模块代码基线和 Auditor 结论。
2. 父 MO 名称表：`parent-mo-<module_id>`，如 parent-mo-M010。
3. **全部输入 CASE-ID 的状态表**，包括 Green、Red、Yellow，不能只列失败用例或成功模块。一个 CASE 有多个模块/PATH 时，全部参与项共同决定该 CASE 状态；父节点不重复计数。
4. PATH-ID/Name、模块/父 MO/TASK、类型、平台/参数、executed/stale、test_run_id/retest_of、断言与证据；`automation` 按宿主任务、模块、TASK 列应测/已尝试/完整执行/部分执行/完整性未知/有效成功/Red/Yellow及成功集合。只计 automation，build/unit/static/visual 单列，并分列设备/进程内/视觉路径的成功与应测及设备缺口 CASE；共享 TASK 的 PATH 总计一次，重试不加分母。缺路径 CASE 保留覆盖缺口，旧 Green 失效退出成功集合；Yellow 细分未执行/受阻/过期/flaky，已观察失败断言单列且不重复计数。
5. 每条非 Green 的原因、根因置信度（若已有）、owner、next_action 和证据引用；原因未知明确待诊断，不能臆测，也不能以一句“环境问题”代替已有错误证据。
6. 有已接受的实现缺口时，展示 `unimplemented` 清单和“未实现：需要人工决策”：具体目标行为、REQ/CASE/TASK、替代方案核验结论、review_ref、owner 与下一步；对应路径的 `implementation_status=not-implemented` 是实现缺口标记，不新增第四种测试质量。一般复用失败应继续 Coding，自动化缺测仍按缺测展示。入口及恢复见 [复用协议第 8 节](reuse-dependencies.md)。

## 生成与交付节点

- 宿主接受 Ledger 事件或执行 `ledger.py status --root <run_root>` 时，重建 `reports/migration-report.json` 和 `reports/migration-report.md`。
- full 视图的 `migration_report` 给出两份文件的绝对路径和 sequence。它们同属该次状态快照，可由事件日志重新生成；GO 不手工修改投影或覆盖模块验收。
- GO 等 MO 收尾、Auditor 处理和父汇总完成后读取报告，在对用户的收尾回复中给出 CASE 状态统计、完整报告链接及非 Green 原因/证据摘要。未解决 Red/Yellow 不得因进入报告阶段而转为 Green。
- 若需保留一次交付版本，宿主按原有工件归档规则保存带 sequence 的报告快照。

## 状态与证据规则

| 情况 | 报告处理 |
| --- | --- |
| CASE 全部路径有效 Green | CASE 为 Green；是否完成迁移另看 DoD/父汇总/Auditor 与 report_stage |
| 任一路径 Red | CASE 为 Red，同时保留其他 Yellow 明细 |
| 未分配、未生成路径、未执行、缺测 | 明确 Yellow；不从统计分母删除 |
| 旧 Green 的代码/定义/依赖证据失效 | 有效状态 Yellow，保留 recorded_quality、原 test_run 和过期原因 |
| 构建 Green、自动化未执行 | 构建单列 Green，业务 CASE 仍为 Yellow |
| Auditor 补验或修复后复核 | 使用当前已接受结果，保留 retest_of；空 audit-review 不制造新测试记录 |
| 尚未到收尾门禁 | report_stage=in-progress，不称迁移成功 |
| 带缺测结束 | completed-with-unverified-tests，质量保持 Yellow |
| 修复失败待人工 | awaiting-human，列出非 Green 及人工根因报告 |

证据优先使用已接受 stage-result 引用、execution_receipt、根因引用的日志/环境报告/截图录屏工件（均保留 path/sha256）。每个非 Green 条目另附 events.jsonl 路径、sequence、CASE/module/PATH，作为该次状态的可重放依据。未执行时没有截图/运行回执，必须指向真实的环境预检/阻塞记录；仅有状态事实时如实说明缺少诊断证据。

JSON 的 cases/case_counts 按 CASE 聚合，paths/non_green 保留明细与证据，automation 从同一批已接受结果派生，不维护第二份计数账本。成功覆盖率=有效成功/应测 PATH；分母为零不报 100%，存在任何模块/CASE 路径缺口不称全量覆盖。attempt_coverage 与 completion_coverage 分开；definition_coverage_complete 仅指路径定义齐全，validation_complete 指全路径完整执行。旧 execution_coverage/current_executed_paths 保留已尝试口径，coverage_complete 保留定义覆盖口径；历史非 Green 无完整性字段记未知。contract_retirements 披露批准、替代及原失败，不算成功；Yellow 中的真实失败不被环境原因遮蔽。报告不启动测试、不改变审计复测范围或验收 owner。

保真披露（视觉覆盖、图片、复制与参数填充）见 [UI 保真](ui-fidelity.md#最终报告的保真披露)，不改变 CASE 状态。可读格式见 [报告模板](../../../template/migration-report.md)。

## 流程成本

报告与 `status.workflow_cost` 从已提交事件统计每个模块的事件数、worker 派发数（build 继续进入 static 只算一次）、上下文回执、验收、人工决定（含父级批量信封的使用）、修复轮次与是否轻量叶子，另给全局事件和审计派发合计；并列出各叶子的规划体量（为计划撰写的与只被引用的文件分列，对照 CASE/TASK 数）和每个人工决定的用途（取自日志，解除阻塞的带原因）。这些数字用于发现流程冗余，不是门禁，也不代表质量。
