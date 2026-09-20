# GO 迁移报告：{{run-id}}

- 范围：{{project 或 single-module 及功能范围}}
- Ledger sequence / snapshot：{{sequence 与模块基线}}
- 阶段：{{in-progress | completed | completed-with-unverified-tests | awaiting-human}}
- 全局质量 / Auditor 结论：{{状态、裁决及证据}}
- 父 MO：{{M010 → parent-mo-M010}}

## 全部测试用例

| CASE-ID | 参与模块 / PATH | 状态 | executed / stale | 结果证据 |
| --- | --- | --- | --- | --- |
| {{逐项列全，不省略未运行}} | {{模块和路径}} | {{green-passed / red-bug / yellow-blocked}} | {{实际事实}} | {{引用}} |

## 非 Green 原因与证据

| CASE / PATH | 根因与置信度 | owner / next_action | 证据 |
| --- | --- | --- | --- |
| {{ID / Name}} | {{真实原因，未知明确待诊断}} | {{责任方与后续动作}} | {{日志/断言/环境/媒体的绝对路径及 hash；Ledger sequence}} |

完整路径/断言和复测链：{{migration-report.json 链接}}。

## 未实现：需要人工决策

{{存在 implementation-gap 时逐项列出模块、目标行为、REQ/CASE/TASK、替代实现核验结论、报告引用、owner 和 next_action。读取 Ledger unimplemented 清单；不可直接复用但已转 Coding 的功能不列入，自动化缺测不列入。}}

构建通过不代表功能通过；未运行保持 Yellow；历史 Green 失效须标注。无非 Green 时明确写“无”，但不替代 DoD 和 Auditor 的完成门禁。本地运行使用 Ledger 生成的同名 Markdown/JSON 投影，不由 GO 手写新的验收事实。
