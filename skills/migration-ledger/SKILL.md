---
name: migration-ledger
description: Ledger 单写者、版本、权限、事件追溯与状态投影，用于 SDD-TDD-Migration 的 Ledger 任务。
---

# migration-ledger

## 1. 定位
服务 Ledger；先读取 [共享协议](../migration-protocol/SKILL.md)，再读 [职责协议](../migration-protocol/references/runtime.md)。

## 2. 核心规约
宿主绑定身份、revision CAS、request 幂等；产物先落盘再提交事实事件，投影可从日志重建。

所有跨层输入输出通过 Ledger 已提交引用传递；本技能不授予角色之外的写权限。

## 3. 标准模式
推荐：模块守卫批准的 transition 请求经校验落盘，再更新 status/global/module 投影返回 ACK。

禁止：多个 Agent append 同一文件；用户改 status 当事实；以请求自报 actor 验证权限。

## 4. 接口契约
输入 assignment_ref + event_ref + absolute artifact refs；输出角色权限矩阵许可的事件及模板工件。文件已生成不等于已接受，必须收到 Ledger ACK。

## 5. 检查
重复提交不重复生效；失效锁拒绝；越权拒绝；空测试非 Green；重放不丢失败。

## 6. 配套资产
使用 [主要模板](../../template/event.json)；其他工件由 [模板索引](../../template/INDEX.md) 定位。无项目执行器时按 Yellow 处理，不能生成假测试结果。

## 本地工具

读取 [local-runtime.md](../migration-protocol/references/local-runtime.md) 后使用 [ledger.py](scripts/ledger.py)（init/apply/status/resume/recover）。[contracts.py](scripts/contracts.py) 校验阶段结构/证据，[workflow.py](scripts/workflow.py) 校验全局覆盖与问题审计，[openspec_projection.py](scripts/openspec_projection.py) 重建六件套与修复记忆；[execute_test.py](scripts/execute_test.py) 供宿主执行已授权测试。

行为测试：`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s <package_root>/skills/migration-ledger/tests -v`。只在临时目录运行样例适配器，不依赖真实迁移项目。

编排状态查询还会派生 next_steps/ready_modules/global_next_step；它们不是第二套状态源。阶段接收、精确恢复、审计关闭/撤销和根因停滞摘要均在 ledger.py 内验证，详细语义见本地运行指南的 2026-09-17 补充。

[progress_signals.py](scripts/progress_signals.py) 派生 workflow_progress、停滞/worker 超时/重复拒绝信号及人工提醒，不改变业务状态。invalidate 保留 planning_history，解除当前旧 plan 阻塞；宿主必须消费这些信号，见 [进度恢复协议](../migration-protocol/references/progress-recovery.md)。

[audit_closure.py](scripts/audit_closure.py) 实现全模块本轮收尾门禁、finding/多 owner 路由、按依赖交错修复与完整测试、关联分支挂起，以及人工批准的 audit-release；这是默认 Auditor 收尾入口。

[project_context.py](scripts/project_context.py) 提供宿主项目配置 init/update/show/history/prepare；配置 revision 与 run revision 分离。Ledger init 验证并保存 project_context_ref，后续操作验证冻结证据。协议及 CLI 见 [项目上下文](../migration-protocol/references/project-context.md)。

[decomposition.py](scripts/decomposition.py) 提供父 MO decompose、GO decompose-accept、父 MO module-summary；modules 保存叶子，module_groups 保存父节点。status.planning_context 提供父子共享全局代码/架构/知识/分工，拆分与子 plan 校验当前上下文；详见 [父子 MO 协议](../migration-protocol/references/module-decomposition.md)。

复用契约纳入项目快照、plan 冻结、实现 trace 和当前证据校验；OpenSpec reuse.md 投影冻结映射。所选 provider 或接入证据变更阻止旧 Green 复用。结构校验不证明语义等价，详见 [二方库协议](../migration-protocol/references/reuse-dependencies.md)。

## 上下文就绪

新运行启用 context-submit 与各原节点的 context_ref 验收，维护 context_receipts/context_acceptances 和 status.context_requirements；不把预检失败自动扩散或标作模块收尾。按 [阶段协议](../migration-protocol/references/context-readiness.md) 校验身份、必读引用、草稿与版本，保留失败与恢复证据。
