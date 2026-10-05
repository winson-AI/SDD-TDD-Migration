# OpenSpec 中间表示与冻结

## 六件套映射

| 用户要求 | 实例路径 | 内容作者 / 正式写入者 |
| --- | --- | --- |
| proposal | `change_root/proposal.md` | Spec-Designer / Ledger |
| spec | `change_root/specs/<capability>/spec.md`，每能力一份 | Spec-Designer / Ledger |
| design | `change_root/design.md` | Spec-Designer / Ledger |
| tasks | `change_root/tasks.md` | Spec-Designer / Ledger |
| status | `change_root/status.md` | MO 决策 / Ledger 投影 |
| checklist | `change_root/checklist.md` | 包内评审清单，Ledger 随 plan 绑定并投影；MO 审核 |

测试设计另以 test-design 工件绑定冻结，为 TDD 提供 CASE/PATH/ASSERT；status/checklist 属运行与治理视图。

不另外维护重复 `spec.md`、`plan.md` 状态源。spec 部分可含多能力 delta 文件；tasks 即可执行计划；status 记录阶段、循环、next_action；追溯及测试报告存不可变 artifacts，由 Ledger 索引。

## 基线与 Delta

目标已有行为在 `openspec/specs/<capability>/spec.md`，使用 `## Requirements`；变更目录使用 `## ADDED Requirements`、`## MODIFIED Requirements`、`## REMOVED Requirements`，重命名按安装版本支持的 `RENAMED` 格式。每需求用 `### Requirement:`，每情景用 `#### Scenario:`，可验证 SHALL/MUST 与 WHEN/THEN。MODIFIED 必须给出修改后的完整 requirement 与全部保留情景；REMOVED 说明理由和替代/迁移策略。

先判断目标基线：目标新增能力用 ADDED；已有能力改变用 MODIFIED；保持不变的需求引用现有基线，不能为了凑 delta 虚构变化。迁移到新的目标架构时也需区分“代码变化”与“行为变化”。Legacy 的观察证据记录在 design 映射中；不能未经批准把 legacy bug 当作目标验收规范。

proposal 说明 Why/What/Capabilities/Impact；design 说明旧→新架构映射、接口、数据、依赖/锁范围、风险与回滚；tasks 使用 `- [ ]` 项，每任务带 TASK-ID、前置任务、REQ-ID/CASE-ID、目标写范围与完成证据。

## 冻结算法

行为契约由运行状态开启，Ledger 在 plan 中写入 `behavior_contract_required=true`，作者不必声明；source_closure 同时是叶子的行为审阅，另含 boundary_rationale、shared_capabilities；它覆盖的范围、需求与 CASE 就是分配包，不再抄写。SPEC 每个需求/场景分别写独立行 `Requirement-ID: <id>`、`Scenario-ID: <run内唯一id>`。Ledger 接受 plan 时从 SPEC 派生 scenario_index，plan 不携带；`behavior_contract.py --plan <staged-plan.json>` 可预览。SPEC 修改即改变 plan 摘要：编码前重新规划，编码后走 CR；均重新审核冻结。

scenario_trace 每行写 scenario_id 与 task_ids，assertions 由 Ledger 按设计断言的 scenario_ids 补全（写了须与之相同）；每个场景至少被一条行为断言验证、每条行为断言至少验证一个场景、全部任务有归属，允许多对多，build/static 不充当行为断言。scenarios.md 为只读投影。

1. 先生成完整六件套草稿（SPEC 带 Requirement-ID/Scenario-ID）；冻结前 Test-Runner design 模式以该 SPEC 为输入独立补齐测试用例与路径大纲，不运行代码。
2. Spec-Designer 把明确的问题、备选项和推荐值经 Ledger 交 Escalation；Human 的答复须绑定 question_id、spec_revision、内容摘要。既有明确答复可复用，若绑定内容已变则重新裁决。
3. 冻结 manifest 列出 proposal、所有 delta specs、design、tasks 定义、test design 与已准备测试资产的实际 path+sha256；checklist 是包内评审清单，与全局上下文一样不进 manifest，由 Ledger 绑定。保留不可变副本，生成 freeze_id/spec_revision。
4. `status`、tasks 完成勾选、checklist 证据等运行字段不纳入语义冻结 hash；冻结的原始定义始终存在不可变 artifacts。动态视图可按已固化映射重定位文档链接及更新运行勾选，不得改变需求、设计和断言语义。验证时比较定义快照，不以可变文件整体 hash 误判失效。
5. MO 独立核验完整规划与 checklist，以当前内容摘要绑定的 plan-review 冻结；仅未决问题、需求/验收/授权变化需要 Human 精确决定。Spec-Designer 不能自批。
6. 每次编码/修复验证当前冻结引用与 assignment 输入一致。缺失/摘要不符停止，不得自行补成“已冻结”。

## 变更控制

Fixer 只提交 change-request 模板，包含原因、证据、受影响需求/任务/路径/模块、行为差异、回归和回滚建议。MO 判断：纯实现补丁不改变契约可授权直接修；需改 design/tasks 定义则 Spec-Designer 出新 revision，由 MO 审核；需求/验收、架构原则、外部接口、数据安全底线变化必须 Human 批准。

修改冻结定义一律重新冻结；MO 可对仅实现规划调整沿用仍有效的人类需求/设计决定，但必须附“不改变既有决定”的影响分析与新 manifest 接受记录。不能把原人类批准假写成新 hash 的批准。受影响代码任务及测试结果标 stale，经新的实现提交和复测才恢复。

## 验证、同步与归档

若项目已有 OpenSpec CLI，先读该版本 `openspec --version` 和 `openspec --help`，保存版本；按其实际可用命令验证各 change（常见为 `openspec validate <change-name> --strict`），保存 stdout/stderr/exit code。无 CLI 可做结构核查，但必须记录 `structural-only`，不能伪称 CLI 已通过；若项目把 CLI 验证设为必需门禁则 Yellow。

在 Global 全局审计通过、人类交付授权绑定最终代码与 spec manifest 后，申请 capability 与归档目录写锁。先在隔离副本预演各 delta 合并，检查同能力多模块冲突，由 Spec-Designer 提交解决方案；不静默选择其中一个。Ledger 记录预演和授权，宿主按已核对 CLI 的同步/归档能力执行；这不替代代码合并授权。操作记录到 archive 事件，保留 change→artifact→event 链，失败可从快照恢复。不得通过“归档”绕开 Red/Yellow。

格式依据：[OpenSpec Concepts](https://github.com/Fission-AI/OpenSpec/blob/main/docs/concepts.md)、[CLI](https://github.com/Fission-AI/OpenSpec/blob/main/docs/cli.md)。六件套后两项、冻结算法与 Ledger 为本包扩展，未注册 OpenSpec 自定义 schema；CLI 不会替本包执行门禁。

## 决策边界与执行基线

`decision_envelope` 记录并经 MO 比对宿主目标：scope、acceptance、allowed_alternatives、forbidden_changes。默认禁止未经批准更换数据提供方、缩减范围、降低验收或引入重大排除。判断是否越界由 Spec-Designer 提交证据、MO 审查；hash 不能证明语义合规。

MO 审核或所需 Human 决定绑定 Ledger 补全后的 stage-plan digest，执行绑定 freeze_id。证据/状态更新不改定义；编码前任务细化走 planning-reopen，编码后走 CR。within-envelope 保留原 envelope 及完整 PATH/预期断言集合；命令/显示名属技术规划，变更仍需 CR/新冻结和执行证据，MO 审阅后发布新执行基线，不伪造新人工批准。

快速通道使用 [change-impact.json](../../../template/change-impact.json)，绑定 from_freeze_id、to_plan_hash。只有当前 CR 的同一 impact_ref 能冻结该计划；再次修改需重审，散文记录不授权再冻结。成功后 CR 进入 change_request_history；invalidate 随 planning_history 留存并清除当前 CR。初始清晰规划允许 MO 审核冻结；边界外变化仍需真实人工决定。

改变需求、验收或授权必须有新的人类决定；纯技术规划调整由 MO 提交不改变既有决定的证据。脚本核对结构与版本，不自动证明文本语义等价。Spec-Designer/Implementer/Fixer 的写权限不合并。第一次 SPEC 冻结前的 legacy 观察属于理解输入，不等于允许提前执行目标测试。

原有六件套是可读定义；新 stage-plan 是它们的引用与机器验收索引，不额外创作第二份需求规范。两者一致性由 MO 冻结审查，独立审计再次核对。

## Ledger 物化与修复记忆

change_root 为 `<workspace_root>/openspec/changes/<run-id>-<module-id小写>`。接受 plan 后物化定义快照及运行状态，manifest 标记 structural-only；CLI 结果须真实执行，视图不作为新定义。

生成视图同时更新跳转：六件套内部引用指向对应的实际生成位置（特别是 specs/<capability>/spec.md）；架构、知识及其中的框架/代码链接，按本轮 context 的 source_paths/link_manifest_ref 指向固化后的文件位置。锚点与标题保留，不能把链接留在旧目录或换成最新工作文件。原始定义及 hash 不修改，重建只使用既有快照。未收录目标记录在 change/manifest.json 的 link_warnings，不能默认当作有效知识链。context/files 的关联文件固化见 [项目上下文协议](project-context.md#contextfiles-的跨文件链接)。

invalidate 后旧 plan 进入 planning_history，当前 plan/freeze 清空；Ledger 撤下 manifest 管理的旧定义视图并生成重新规划 status，保留事件及 artifacts 历史快照。旧计划不能继续阻塞新计划提交，也不能冒充当前冻结定义；新计划仍须正常审核/冻结。分配依据失效交 GO，具体出口见 [恢复协议](progress-recovery.md)。


## 二方库语义与需求映射

reuse_plan_ref 冻结库选择、语义差异、接线、版本及 fidelity（源码基线、对齐报告、复现 PATH/ASSERT），生成辅助 reuse.md；spec 保持用户行为要求。proposal/design/tasks 记录适配与验证，status 记录实际结果。规划对齐不代表运行通过，源码与需求冲突交人工；换能力/接入契约走影响分析、CR/重新冻结，详见 [复用协议](reuse-dependencies.md)。

build 与 automation PATH 分别冻结命令/断言；自动化环境缺失保留 SPEC 和未执行 Yellow，恢复后补测，见 [双环节协议](build-automation.md)。

## 四维完整性索引

按 [四维协议](dimension-slicing.md#7-任务级四维分析契约) 冻结 dimension_analysis_ref、dimension_trace 及先划定的 tasks.scope / 随后生成的任务 dimension_analysis；design/spec/tasks 都保留适用 item ID，N/A 的源码依据写入设计。Ledger 从不可变分析生成 dimensions.md。它是辅助索引，不替代六件套或正式验证。

## OpenSpec 自动物化

事件提交/status 重放由 Ledger 生成六件套、memory.md、manifest.json及适用的复用/四维/场景索引。spec 按 capability 分文件，默认小写模块 ID；定义作者仍为 Spec-Designer。tasks 必须含每个 TASK-ID 的 checkbox，按已接受 task_trace 勾选；checklist 追加证据，status 记录阶段/三态/next_step。重建不改定义快照、freeze_id 或验收；manifest 清理旧生成文件，变更走 plan/CR。

## 修复 memory

Fixer 的 implementation 必须带 fix_note_ref，内容见 [fix-note 模板](../../../template/fix-note.json)：root_cause、strategy、applicability、risks。Ledger 保存 diagnosis、问题快照、冻结版本、前后代码基线、任务/补丁引用和正式回归证据，生成模块 memory.md 与全局 ledger/repair-memory.json。

pending / interrupted / awaiting-regression / failed / verified 区分修复事实；只有正式回归全 Green 的记录 reusable=true。复用前按根因、适用条件和当前 SPEC 比较，引用 memory 所属事件/工件；memory 不授予写权限，不替代本轮测试，也不允许降低验收。失败记录仍可用于避免重复无效方案。
