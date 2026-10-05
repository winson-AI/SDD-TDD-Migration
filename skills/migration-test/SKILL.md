---
name: migration-test
description: SDD-TDD-Migration 的测试设计、构建与自动化执行；支持项目 Main 及 Android/Harmony test 模式、截图/视频断言、回放、证据和三态归档。
---

# migration-test

## 1. 定位
服务 Test-Runner；先读取 [共享协议](../migration-protocol/SKILL.md)，再按阅读卡读 [职责协议](../migration-protocol/references/testing.md) 的相应小节。

## 2. 核心规约
设计/执行模式分离；每条参数化路径有 ID/Name/query 和非空预期断言；Main 采用项目真实执行器。

设计 UI 测试时使用 [状态测试表](../../template/ui-state-test-design.md)：稳定视觉目标与瞬态行为分别验证。loading/skeleton 保留状态转换测试，未声明为可稳定复现的视觉目标时不要求抢拍，不通过假延时改变生产行为。该分类写入已有 test-design，随 SPEC 冻结。

所有跨层输入输出通过 Ledger 已提交引用传递；本技能不授予角色之外的写权限。

需要当前 HAP 装机、视觉捕获或模型语义比较时按 [受限视觉执行](../migration-protocol/references/visual-execution.md#2-执行节点)。在现有测试 assignment 下使用 visual-install/visual-capture/semantic-inspect/image-parity，读取冻结配置、保存原始证据；正式结果仍通过 execute_test/adapter 提交，不在工具中修代码或直接验收。

## 3. 标准模式
design 沿 `assign(mode=design) → submit（附 test-design 预检）→ MO accept(review_ref)` 提交预期路径，再由 Ledger 补进 Spec plan、MO 冻结；见 [编码前交接](../migration-protocol/references/testing.md#编码前设计交接)。code accepted 后依次 build → unit（本轮 JUnit）→ static（逐 Scenario）→ automation → 适用时 visual。错误交 Fixer；仅 automation 环境缺失记 Yellow/未执行，其他任务继续。

禁止：自然语言 query 当 shell；以构建 exit 0 代替业务用例通过；无断言或 skip 当通过；重跑只保留最好一次。

## 4. 接口契约
见 [共享协议·通用约定](../migration-protocol/SKILL.md#通用约定)。

## 5. 检查
用例路径全覆盖；assert 完整；结果版本匹配；未知/环境失败 Yellow；失败根因可追溯。

## 6. 配套资产
使用 [主要模板](../../template/test-paths.json)；其他工件用游标步骤 `templates` 列出的模板。无项目执行器时按 Yellow 处理，不能生成假测试结果。

## 7. Android/Harmony 自动化测试

两端 UI/端到端 PATH 按 [移动端运行协议](references/harmony-runtime.md#3-execute一条-path-到-main)。使用 MobileAgenticOperator 的 test 流程：Planner → Executor → Verify；保留验证、回放、重规划和报告。冻结 platform=android|harmony、task_type=test；不支持 iOS 或以 snapshot/recording 验收。

- design：用 [harmony_design.py](scripts/harmony_design.py) 导入 MD/XMind，审核完整用例并补齐冻结 ASSERT 描述、类型、匹配规则与 after_step。
- execute：通过 host execute_test 调用 [harmony_adapter.py](scripts/harmony_adapter.py)，再用 [harmony_stage.py](scripts/harmony_stage.py) 组装全路径结果，按 Ledger submit/accept。
- 固定 ASSERT ID 绑定冻结谓词；零断言、最终通过文本、旧回放结果不能代替本次验证。原生 memory 是候选执行素材，复用与修复裁决仍受 Ledger 控制。
- 内核组件只执行当前 Test-Runner 任务，不承担 Spec/Fixer/Auditor 权限；历史 harmony 文件名/存储路径兼容保留。

复用 fidelity、视觉、手势、埋点、运行环境与留存等角色义务以 [Test-Runner 定义](../../Agents/test-runner.md#专题义务) 为准；本技能只保留执行规约。

输出位置：构建 `.sdd-runs/<run_id>/runs/build/<new-attempt>`，自动化 `runs/harmony/automation/<new-attempt>`，Harmony 设计/适配/汇总 `runs/harmony/sandbox/<request>`；本 run 共享环境 `runs/harmony/sandbox/environment` 由 `sandbox.py prepare --root <run_root>` 生成。见 [留存布局](../migration-protocol/references/storage-layout.md#总则)。
