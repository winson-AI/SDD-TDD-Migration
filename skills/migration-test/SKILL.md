---
name: migration-test
description: SDD-TDD-Migration 的测试设计与执行；支持项目 Main 及 Harmony 分层 UI 自动测试、截图/视频断言、录制回放、证据和三态归档。
---

# migration-test

## 1. 定位
服务 Test-Runner；先读取 [共享协议](../migration-protocol/SKILL.md)，再读 [职责协议](../migration-protocol/references/testing.md)。

## 2. 核心规约
设计/执行模式分离；每条参数化路径有 ID/Name/query 和非空预期断言；Main 采用项目真实执行器。

所有跨层输入输出通过 Ledger 已提交引用传递；本技能不授予角色之外的写权限。

## 3. 标准模式
推荐：先 design 定义可验证期望，code accepted 后 execute 记录 path 级结果；失败保留实际值与原因。

禁止：自然语言 query 当 shell；只看 exit 0；无断言或 skip 当通过；重跑只保留最好一次。

## 4. 接口契约
输入 assignment_ref + event_ref + absolute artifact refs；输出角色权限矩阵许可的事件及模板工件。文件已生成不等于已接受，必须收到 Ledger ACK。

## 5. 检查
用例路径全覆盖；assert 完整；结果版本匹配；未知/环境失败 Yellow；失败根因可追溯。

## 6. 配套资产
使用 [主要模板](../../template/test-paths.json)；其他工件由 [模板索引](../../template/INDEX.md) 定位。无项目执行器时按 Yellow 处理，不能生成假测试结果。

## 7. Harmony 自动化测试

HarmonyOS UI/端到端测试读取 [Harmony 运行协议](references/harmony-runtime.md)。使用迁入的 Planner → Executor → Verify 内核，保留五类媒体验证、录制回放、失败重规划、记忆压缩、XPath 与原报告。

- design：用 [harmony_design.py](scripts/harmony_design.py) 导入 MD/XMind，审核完整用例并补齐冻结 ASSERT 描述、类型、匹配规则与 after_step。
- execute：通过 host execute_test 调用 [harmony_adapter.py](scripts/harmony_adapter.py)，再用 [harmony_stage.py](scripts/harmony_stage.py) 组装全路径结果，按 Ledger submit/accept。
- 固定 ASSERT ID 绑定冻结谓词；零断言、最终通过文本、旧回放结果不能代替本次验证。原生 memory 是候选执行素材，复用与修复裁决仍受 Ledger 控制。
- 内核的 Planner/Executor/Verify 仅是当前 Test-Runner 内部组件；不能承担外层 Spec/Fixer/Auditor 权限。其他平台继续使用原 Main 适配器。

测试设计增加二方库接线、版本配置、语义差异及真实提供方集成路径；Coding 后正式 Main 执行，完整业务验收不得因复用而缩减。见 [二方库复用协议](../migration-protocol/references/reuse-dependencies.md)。
