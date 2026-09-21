# 埋点上报分析 · {{run-id}} / {{scope-owner}}

## 适用性

- 层级及范围：{{GO根模块 / 父MO子分配 / 子MO模块 / TASK；范围内外}}
- 状态：{{applicable / not-applicable；未查明草稿为 unresolved}}
- 检查过的存量/目标路径、符号、SDK/配置及快照证据：{{refs}}
- 理由：{{明确无埋点、只消费已有提供方或负责事件/公共能力的依据}}
- 继承/分配：{{父事件、子owner、消费者；普通无埋点子模块/任务单列N/A}}

确认 N/A 后，以下事件表为空并注明不适用即可；不生成空任务/用例、不申请埋点环境、不改变业务测试状态。缺环境或尚未实现不是 N/A。

## 事件、参数及行为对齐（仅 applicable）

| 追溯 event_id / 功能 | 源事件 → 目标事件 | 触发/禁止触发/次数/顺序 | 参数名/类型/默认/来源/变换 | 初始化/开关/状态 | 实际重试/缓存/失败语义 | 源行为与差异证据 |
| --- | --- | --- | --- | --- | --- | --- |
| {{event_id / FEATURE}} | {{source → target}} | {{条件及观测窗口}} | {{逐字段或详细表链接；不含密钥}} | {{实际行为}} | {{实际行为；不存在写N/A依据}} | {{固化refs}} |

## 实现与复用（仅 applicable）

| event_id | owner / TASK | UI/Logic/Adhesive/Resource条目 | capability/版本/策略 | 真实接线/修改路径 | 消费者/影响范围 | fidelity依据 |
| --- | --- | --- | --- | --- | --- | --- |
| {{ID}} | {{唯一owner / TASK}} | {{涉及维度}} | {{reuse/adapt/reference/new}} | {{SDK/DI/桥接/代码}} | {{实际消费者}} | {{refs}} |

## 测试映射与实际结果（仅 applicable）

| event_id | 模块/CASE/PATH/ASSERT | 冻结验收层级 | adapter/观测入口 | 正常/禁止/边界场景 | 实际状态/executed/stale | test_run/retest_of/基线 | 原始证据/根因/下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| {{ID}} | {{已分配ID}} | {{emitted / sdk-dispatched / server-received}} | {{工具及脚本}} | {{expected及观测窗口}} | {{未执行保持未验证；不编造Green}} | {{冻结时pending；执行后真实引用}} | {{回执/日志refs}} |

## 完整性及待决问题

- 范围内所有已发现埋点均有归属/映射：{{结论与依据}}
- 普通任务 N/A 清单及理由：{{TASK列表}}
- 业务预期/共享边界不明：{{问题、影响范围、人工决策引用；无关任务继续}}
- 缺测环境/不可观测层级：{{事件及PATH、根因、owner、下一步；不能改为N/A}}
- 关联 SPEC/design/tasks、telemetry 索引及 Auditor CHG 清单：{{固化链接}}

规划工件保持不可变；正式结果引用 Ledger，补丁/复测生成新版本并保留原失败证据。
