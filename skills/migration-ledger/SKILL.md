---
name: migration-ledger
description: Ledger 单写者、版本、权限、事件追溯与状态投影，用于 SDD-TDD-Migration 的 Ledger 任务。
---

# migration-ledger

## 1. 定位
服务 Ledger；先读取 [共享协议](../migration-protocol/SKILL.md)，再按阅读卡读 [职责协议](../migration-protocol/references/runtime.md) 的相应小节。

## 2. 核心规约
宿主绑定身份、revision CAS、request 幂等；产物先落盘再提交事实事件，投影可从日志重建。

所有跨层输入输出通过 Ledger 已提交引用传递；本技能不授予角色之外的写权限。

## 3. 标准模式
推荐：模块守卫提交的请求经校验落盘，再更新 status/global/module 投影返回 ACK。

禁止：多个 Agent append 同一文件；用户改 status 当事实；以请求自报 actor 验证权限。

## 4. 接口契约
见 [共享协议·通用约定](../migration-protocol/SKILL.md#通用约定)。

## 5. 检查
重复提交不重复生效；失效锁拒绝；越权拒绝；空测试非 Green；重放不丢失败。

## 6. 配套资产
请求用 [ledger-request.json](../../template/ledger-request.json)；其他工件用游标步骤 `templates` 列出的模板。无项目执行器时按 Yellow 处理，不能生成假测试结果。

## 本地工具

[source_changes.py](scripts/source_changes.py) 接入 GO source-review 和 Host reconfigure-sources，追加只读来源、固化新快照并局部重新规划；status.source_change_next_step 给出审批/过期/协调信号。所有事务走 ledger.py，不直接调用 helper 修改生产状态。字段与三层职责见 [来源变更协议](../migration-protocol/references/source-changes.md)。

读取 [local-runtime.md](../migration-protocol/references/local-runtime.md) 后使用 [ledger.py](scripts/ledger.py)（init/apply/status/resume/recover）。[contracts.py](scripts/contracts.py) 校验阶段结构/证据，[workflow.py](scripts/workflow.py) 校验全局覆盖与问题审计，[openspec_projection.py](scripts/openspec_projection.py) 重建六件套与修复记忆；[execute_test.py](scripts/execute_test.py) 供宿主执行已授权测试。

编排状态查询还会派生 next_steps/ready_modules/global_next_step；它们不是第二套状态源。阶段接收、精确恢复、审计关闭/撤销和根因停滞摘要均在 ledger.py 内验证。

[progress_signals.py](scripts/progress_signals.py) 派生 workflow_progress、停滞/worker 超时/重复拒绝信号及人工提醒，不改变业务状态。invalidate 保留 planning_history，解除当前旧 plan 阻塞；宿主必须消费这些信号，见 [进度恢复协议](../migration-protocol/references/progress-recovery.md)。

[audit_closure.py](scripts/audit_closure.py) 实现全模块本轮收尾门禁、finding/多 owner 路由、按依赖交错修复与完整测试、关联分支挂起，以及人工批准的 audit-release；这是默认 Auditor 收尾入口。

[project_context.py](scripts/project_context.py) 提供宿主项目配置 init/update/show/history/prepare；配置 revision 与 run revision 分离。Ledger init 验证并保存 project_context_ref，后续操作验证冻结证据。协议及 CLI 见 [项目上下文](../migration-protocol/references/project-context.md)。

[context_links.py](scripts/context_links.py) 将 context/files 中 Markdown 的本地链接目标一起固化，保留原始证据、生成重定位后的阅读副本及链接 manifest；OpenSpec 用同一映射更新知识链接和六件套内部跳转。宿主检查 document_link_warnings / change manifest.link_warnings，不能直接修改旧快照的正文/hash 来修链接。

[decomposition.py](scripts/decomposition.py) 提供父 MO decompose、GO decompose-accept、父 MO module-summary；modules 保存叶子，module_groups 保存父节点。planning_context 提供父子共享全局代码/架构/知识/分工；拆分提案与子 plan 不抄写它，Ledger 接受时绑定当前上下文与分配的摘要并在冻结、派发时复核；详见 [父子 MO 协议](../migration-protocol/references/module-decomposition.md)。

复用契约纳入项目快照、plan 冻结、实现 trace 和当前证据校验；OpenSpec reuse.md 投影冻结映射。所选 provider 或接入证据变更阻止旧 Green 复用。结构校验不证明语义等价，详见 [二方库协议](../migration-protocol/references/reuse-dependencies.md)。

## 上下文就绪

[design_stage.py](scripts/design_stage.py) 处理 mode=design 的派发/提交/接受及 plan/freeze 绑定，不改测试质量，见 [设计交接](../migration-protocol/references/testing.md#编码前设计交接)。

新运行启用 context-submit 与各原节点的 context_ref 验收，维护 context_receipts/context_acceptances；步骤视图的 `context` 给出本阶段要求；不把预检失败自动扩散或标作模块收尾。按 [阶段协议](../migration-protocol/references/context-readiness.md) 校验身份、必读输入摘要、草稿与版本，保留失败与恢复证据。

Auditor 收尾先接受 `audit-code-review` 的独立全模块代码审查；`audit-collect` 优先代码治理批次，再处理剩余 Red/Yellow；最终 audit-assign/audit-unavailable 均校验当前审查及无待治理发现。接口、证据和恢复见 [代码治理协议](../migration-protocol/references/audit-code-review.md)。

[run_storage.py](scripts/run_storage.py) 统一派生三个顶层目录，校验 run_id/路径归属及测试输出范围；[workflow_hub.py](scripts/workflow_hub.py) 生成顶层 OpenSpec 的本轮导航与状态视图。新入口遵守 [留存布局](../migration-protocol/references/storage-layout.md)，不自动搬迁历史快照。

[trace.py](scripts/trace.py) 按 Scenario/TASK/PATH/ASSERT/测试 ID 只读查询已提交证据；恢复先取摘要，完整日志按需分页。实时执行观察仅供 Host，见 [日志与按需追溯](../migration-protocol/references/testing.md#日志与按需追溯)。
