# 复用与存量功能保真对齐记录

> 规划工件，不是已执行或已通过的证明。由 reuse-plan 的 fidelity.alignment_ref 引用并冻结；正式结果通过 Ledger 的 PATH/ASSERT 和 execution_receipt 关联，不回写此冻结文件。

## 基线与范围

- run / module / mapping / capability：{{IDs}}
- 存量源码：{{legacy_root、commit（如有）、实际源码 path/sha256、入口与调用链}}
- 复用提供方：{{TARGET 或外部 source_id、version、provider_refs}}
- 功能需求 / CASE / TASK：{{IDs 与批准范围}}
- 基线依据：{{源码分析 / 已有真实执行记录；分别标注，不能互相冒充}}
- 已有执行记录：{{如有，填写命令、环境、输入/状态、输出/副作用及证据 path/sha256；如无，说明未执行及限制}}

## 逐行为对齐

按适用的正常、边界、错误/取消/重试、权限、默认值/空值、顺序/分页、状态/生命周期、持久化/恢复、并发及副作用展开；不适用项说明依据。

| scenario_id | 源码定位与需求 | 相同前置/输入/状态 | 存量预期结果与副作用 | 提供方实际语义及依据 | 差异与适配 TASK | PATH / ASSERT |
| --- | --- | --- | --- | --- | --- | --- |
| {{FID}} | {{source locator / REQ / CASE}} | {{fixtures/actions/reset/seed}} | {{expected}} | {{reviewed behavior}} | {{none with reason / adaptation}} | {{PATH / ASSERT}} |

## 复现方案与未决项

### 目标已有实现与冗余处理

{{存在目标已有功能时必填；无重复也记录检查范围/依据。对照实际库内容，确认可复用的重复逻辑必须安排目标重构，不以“已实现”跳过。}}

| 目标文件/符号 | 二方库 source/capability/version | 等价行为及差异依据 | 消费者/唯一 owner | 删除或替换范围 / 必要适配及保留理由 | TASK / 回归 PATH/ASSERT |
| --- | --- | --- | --- | --- | --- |
| {{target}} | {{provider}} | {{semantic alignment}} | {{callers / owner}} | {{refactor / cleanup / compatibility}} | {{trace}} |

### 生产复现与限制

- 目标生产链路：{{入口 → 真实提供方 → 适配 → 结果}}
- 验证方法：{{同场景回放或对应源码基线的明确断言、命令/环境方案；规划时不执行目标测试}}
- 保真限制：{{无法确认的行为、缺环境/数据/证据、owner、next_action；无则明确 none}}
- 需求与存量行为冲突：{{差异及 Ledger 人工决策/CR 引用；未解决不得冻结，不能用库默认值作决定}}
- 规划结论：{{可直接复用 / 需适配 / 仅参考 / 拒绝候选；不是 Green}}

## 后续记录位置

Main 的每条 PATH 结果保存 frozen expected/actual、assertion_id、test_run_id、freeze_id、code_baseline、环境、日志与 execution_receipt；按 reuse-plan.scenarios 关联本记录。Red/Yellow 保存根因和恢复动作，Fixer memory 引用 mapping/scenario/失败与复测记录；Auditor 按同一基线独立裁决。新的提供方、基线或行为差异生成新记录版本，保留历史。
