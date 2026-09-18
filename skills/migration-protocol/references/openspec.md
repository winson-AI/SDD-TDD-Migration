# OpenSpec 中间表示与冻结

## 六件套映射

| 用户要求 | 实例路径 | 内容作者 / 正式写入者 |
| --- | --- | --- |
| proposal | `change_root/proposal.md` | Spec-Designer / Ledger |
| spec | `change_root/specs/<capability>/spec.md`，每能力一份 | Spec-Designer / Ledger |
| design | `change_root/design.md` | Spec-Designer / Ledger |
| tasks | `change_root/tasks.md` | Spec-Designer / Ledger |
| status | `change_root/status.md` | MO 决策 / Ledger 投影 |
| checklist | `change_root/checklist.md` | Spec-Designer 定义、MO 审核 / Ledger 投影 |

不另外维护重复 `spec.md`、`plan.md` 状态源。spec 部分可含多能力 delta 文件；tasks 即可执行计划；status 记录阶段、循环、next_action；追溯及测试报告存不可变 artifacts，由 Ledger 索引。

## 基线与 Delta

目标已有行为在 `openspec/specs/<capability>/spec.md`，使用 `## Requirements`；变更目录使用 `## ADDED Requirements`、`## MODIFIED Requirements`、`## REMOVED Requirements`，重命名按安装版本支持的 `RENAMED` 格式。每需求用 `### Requirement:`，每情景用 `#### Scenario:`，可验证 SHALL/MUST 与 WHEN/THEN。MODIFIED 必须给出修改后的完整 requirement 与全部保留情景；REMOVED 说明理由和替代/迁移策略。

先判断目标基线：目标新增能力用 ADDED；已有能力改变用 MODIFIED；保持不变的需求引用现有基线，不能为了凑 delta 虚构变化。迁移到新的目标架构时也需区分“代码变化”与“行为变化”。Legacy 的观察证据记录在 design 映射中；不能未经批准把 legacy bug 当作目标验收规范。

proposal 说明 Why/What/Capabilities/Impact；design 说明旧→新架构映射、接口、数据、依赖/锁范围、风险与回滚；tasks 使用 `- [ ]` 项，每任务带 TASK-ID、前置任务、REQ-ID/CASE-ID、目标写范围与完成证据。

## 冻结算法

1. 生成完整六件套草稿；冻结前 Test-Runner design 模式独立补齐测试用例与路径大纲，不运行代码。
2. Spec-Designer 把明确的问题、备选项和推荐值经 Ledger 交 Escalation；Human 的答复须绑定 question_id、spec_revision、内容摘要。既有明确答复可复用，若绑定内容已变则重新裁决。
3. 冻结 manifest 列出 proposal、所有 delta specs、design、tasks 定义、checklist 定义、test design 与全局输入契约的实际 path+sha256。保留不可变副本，生成 freeze_id/spec_revision。
4. `status`、tasks 完成勾选、checklist 证据等运行字段不纳入语义冻结 hash；冻结的原始定义始终存在不可变 artifacts，动态视图不得更改定义文本。验证时比较定义快照，不以可变文件整体 hash 误判失效。
5. Human R1/R2 批准具体 manifest；MO 独立核验 checklist 后接受 freeze；Ledger 提交 freeze_accepted 并物化状态。Spec-Designer 不能自批。
6. 每次编码/修复验证当前冻结引用与 assignment 输入一致。缺失/摘要不符停止，不得自行补成“已冻结”。

## 变更控制

Fixer 只提交 change-request 模板，包含原因、证据、受影响需求/任务/路径/模块、行为差异、回归和回滚建议。MO 判断：纯实现补丁不改变契约可授权直接修；需改 design/tasks 定义则 Spec-Designer 出新 revision，由 MO 审核；需求/验收、架构原则、外部接口、数据安全底线变化必须 Human 批准。

修改冻结定义一律重新冻结；MO 可对仅实现规划调整沿用仍有效的人类需求/设计决定，但必须附“不改变既有决定”的影响分析与新 manifest 接受记录。不能把原人类批准假写成新 hash 的批准。受影响代码任务及测试结果标 stale，经新的实现提交和复测才恢复。

## 验证、同步与归档

若项目已有 OpenSpec CLI，先读该版本 `openspec --version` 和 `openspec --help`，保存版本；按其实际可用命令验证各 change（常见为 `openspec validate <change-name> --strict`），保存 stdout/stderr/exit code。无 CLI 可做结构核查，但必须记录 `structural-only`，不能伪称 CLI 已通过；若项目把 CLI 验证设为必需门禁则 Yellow。

在 Global 全局审计通过、人类交付授权绑定最终代码与 spec manifest 后，申请 capability 与归档目录写锁。先在隔离副本预演各 delta 合并，检查同能力多模块冲突，由 Spec-Designer 提交解决方案；不静默选择其中一个。Ledger 记录预演和授权，宿主按已核对 CLI 的同步/归档能力执行；这不替代代码合并授权。操作记录到 archive 事件，保留 change→artifact→event 链，失败可从快照恢复。不得通过“归档”绕开 Red/Yellow。

格式依据：[OpenSpec Concepts](https://github.com/Fission-AI/OpenSpec/blob/main/docs/concepts.md)、[CLI](https://github.com/Fission-AI/OpenSpec/blob/main/docs/cli.md)。六件套后两项、冻结算法与 Ledger 为本包扩展，未注册 OpenSpec 自定义 schema；CLI 不会替本包执行门禁。

## 决策边界与执行基线（P1）

人类批准 `decision_envelope`：scope、acceptance、allowed_alternatives、forbidden_changes。默认禁止未经批准更换数据提供方、缩减范围、降低验收或引入重大排除。判断是否越界由 Spec-Designer 提交证据、MO 审查；hash 不能证明语义合规。

初始批准绑定完整 stage-plan 的内容摘要；该计划包含六件套文件引用、测试 PATH/断言、任务、source_closure、target_feasibility 与 envelope。当前执行仍绑定具体 freeze_id。后续只增加证据/状态不改变定义；任务细化须 CR/影响分析与新 freeze。`within-envelope` 快速通道只允许保留原 envelope 和完整测试路径/预期断言集合，不放开 tasks 任意变化；MO 审查实施计划后发布新执行基线，不伪造新的人工批准。

改变范围、验收、替代方案或路径集合必须有新的人类决定；脚本不能自动裁定两段文本语义等价。Spec-Designer/Implementer/Fixer 的写权限不合并。第一次 SPEC 冻结前的 legacy 观察属于理解输入，不等于允许提前执行目标测试。

原有六件套是可读定义；新 stage-plan 是它们的引用与机器验收索引，不额外创作第二份需求规范。两者一致性由 MO 冻结审查，独立审计再次核对。

## Ledger 物化与修复记忆

本地默认 change_root 为 `<run_root>/openspec/changes/<run-id>-<module-id小写>`。每个已接受 plan 的定义快照会自动生成 proposal/spec/design/tasks/checklist，status 从状态机生成；tasks 勾选绑定 accepted task trace，checklist 保留定义并附机器证据。manifest 标记 structural-only，正式 CLI 验证结果不得伪造。删除视图后 status 可重建，视图修改不能更改冻结内容。

memory.md 与 ledger/repair-memory.json 保存 Red/Yellow 修复的根因、策略、适用条件、风险、前后基线和正式回归证据；这是定义之外的运行记忆，不能覆盖需求。只有 verified/reusable=true 条目可作为已验证方案参考；依然必须符合本轮冻结任务与验收并重新测试。
