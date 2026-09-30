# UI 状态测试设计（并入模块已有 test-design）

本表是填写示例，不能充当源码事实、批准或测试通过。实例化在 `<run_root>/staging/<spec-or-test-agent>/<request-id>/`，随 plan.definitions 的 test-design 提交，经 Ledger 引用投影到本次 OpenSpec。无需创建另一套测试状态机。

| 状态 ID | 源码/需求证据 | 状态分类与依据 | 验证方式 | 冻结 PATH / ASSERT | Capture 目标 |
| --- | --- | --- | --- | --- | --- |
| state:settings/content | {{source-ref + scenario}} | 稳定，可重复进入 | 行为 + 视觉 | {{automation-path/assert}}；{{visual-path/assert}} | settings:content:viewport |
| state:settings/loading | {{source-ref + scenario}} | 瞬态，请求结束后退出 | 状态转换、取消/成功/错误分支 | {{automation-path/assert}} | 不要求截图；保留生产分支和 UI 树动态规则 |
| {{explicit-stable-state}} | {{source-ref + user-requirement}} | 明确要求且可稳定复现，条件：{{condition}} | 行为 + 视觉 | {{automation-path/assert}}；{{visual-path/assert}} | {{page:state:coverage}} |

按实际范围删除不适用示例。每个状态的行为测试与 CASE 对应；不能因为不截图而省略 loading/skeleton 行为，不能为了截图改变生产时序。无运行时基线的稳定状态沿 source-only 留存及披露，不制造截图或 Green。
