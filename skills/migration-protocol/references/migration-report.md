# GO 迁移收尾报告

## 必须展示的信号

GO 在本轮成功完成、带自动化缺测结束或需人工处理而停止时，向用户提供完整报告；运行中查询只提供明确标注的进度快照。报告必须包含：

1. run_id、入口范围、Ledger sequence、当前模块代码基线和 Auditor 结论。
2. 父 MO 名称表：`parent-mo-<module_id>`，如 parent-mo-M010。
3. **全部输入 CASE-ID 的状态表**，包括 Green、Red、Yellow，不能只列失败用例或成功模块。一个 CASE 有多个模块/PATH 时，全部参与项共同决定该 CASE 状态；父节点不重复计数。
4. PATH-ID/Name、模块与父 MO、build/automation 类型、状态、executed、stale、test_run_id/retest_of、assertions 与 SPEC 引用。
5. 每条非 Green 的原因、根因置信度（若已有）、owner、next_action 和证据引用；原因未知明确待诊断，不能臆测，也不能以一句“环境问题”代替已有错误证据。
6. 有已接受的实现缺口时，展示 `unimplemented` 清单和“未实现：需要人工决策”：具体目标行为、REQ/CASE/TASK、替代方案核验结论、review_ref、owner 与下一步；对应路径的 `implementation_status=not-implemented` 是实现缺口标记，不新增第四种测试质量。一般复用失败应继续 Coding，自动化缺测仍按缺测展示。入口及恢复见 [复用协议第 8 节](reuse-dependencies.md)。

## 生成与交付节点

- 宿主接受 Ledger 事件或执行 `ledger.py status --root <run_root>` 时，重建 `reports/migration-report.json` 和 `reports/migration-report.md`。
- `status.migration_report` 返回两份文件的绝对路径和 sequence。它们同属该次状态快照，可由事件日志重新生成；GO 不手工修改投影或覆盖模块验收。
- GO 等 MO 收尾、Auditor 处理和父汇总完成后读取报告，在对用户的收尾回复中给出 CASE 状态统计、完整报告链接及非 Green 原因/证据摘要。未解决 Red/Yellow 不得因进入报告阶段而转为 Green。
- 若需保留一次交付版本，宿主按原有工件归档规则保存带 sequence 的报告快照。恢复执行后实时投影会更新，旧 Ledger 事件与原始证据仍保留。

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

JSON 的 `cases` 按 CASE 聚合，`paths` 保留完整明细，`non_green` 单独列出问题与证据，`case_counts` 以 CASE 计数。实际断言保留在 JSON 与原始回执中；Markdown 提供路径与非 Green 摘要。本报告不启动任何测试，不改变 Auditor 的遗留复核范围，也不引入新的验收 owner。

可读格式见 [报告模板](../../../template/migration-report.md)。
