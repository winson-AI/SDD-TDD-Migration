# 埋点上报分析 · {{run-id}} / {{scope-owner}}

## 适用性

- 层级及范围：{{GO 根模块 / 父 MO 子分配 / 子 MO 模块 / TASK}}
- 状态：{{applicable / not-applicable；未查明为 unresolved}}
- 检查过的存量/目标路径、符号、SDK/配置及快照证据：{{refs}}
- 理由与继承：{{无埋点、只消费已有提供方或负责事件/公共能力的依据；父事件、子 owner、消费者}}

N/A 时下表为空并注明不适用；不生成空任务/用例，不申请埋点环境。缺环境或尚未实现不是 N/A。

## 事件、参数及行为对齐（仅 applicable）

| event_id / 功能 | 源事件 → 目标事件 | 触发/禁止触发/次数/顺序 | 参数名/类型/默认/来源/变换 | 初始化/开关/状态 | 重试/缓存/失败语义 | 源行为与差异证据 |
| --- | --- | --- | --- | --- | --- | --- |
| {{event_id / FEATURE}} | {{source → target}} | {{条件及观测窗口}} | {{逐字段；不含密钥}} | {{实际行为}} | {{实际行为或 N/A 依据}} | {{refs}} |

## 实现、复用与测试映射（仅 applicable）

| event_id | owner / TASK | 维度条目 | capability/版本/策略 | 真实接线 | 消费者/影响范围 | CASE/PATH/ASSERT | 验收层级 | adapter/观测入口 | 实际状态 / test_run / 根因 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| {{ID}} | {{唯一 owner / TASK}} | {{UI/Logic/Adhesive/Resource}} | {{reuse/adapt/reference/new}} | {{SDK/DI/桥接/代码}} | {{实际消费者}} | {{已分配 ID}} | {{emitted / sdk-dispatched / server-received}} | {{工具及脚本}} | {{未执行保持未验证；执行后真实引用}} |

## 完整性及待决问题

- 范围内所有已发现埋点均有归属/映射：{{结论与依据}}
- N/A 任务清单及理由：{{TASK 列表}}
- 业务预期/共享边界不明：{{问题、影响范围、人工决策引用}}
- 缺测环境/不可观测层级：{{事件及 PATH、根因、owner、下一步；不能改为 N/A}}
