---
name: migration-global
description: 功能切片、架构差异解析、DAG 与全局三态调度，用于 SDD-TDD-Migration 的 Global-Orchestrator 任务。
---

# migration-global

来源/归属变化时遵守 [来源追加协议](../migration-protocol/references/source-changes.md)：完整来源和影响评审经 source-review 接受，Host 绑定批准后版本切换；所有叶子（包括 new 路线）与父分配都须评审，仅受影响闭包重规划。新 capability 采用 v2 显式 owner，写集合不能当作业务归属。

## 1. 定位
服务 Global-Orchestrator；先读取 [共享协议](../migration-protocol/SKILL.md)，再读 [职责协议](../migration-protocol/references/runtime.md)。

## 2. 核心规约
入口默认 project，用户直接指定一个完整项目，GO 识别项目内各功能及子功能。single-module 仅通过 module_name 选择其中一个特定功能；其子功能仍由父 MO 拆分并交独立子 MO 执行。GO 划分根模块 scope（in/out/全局需求 ID）、所需 context_refs、代码范围和 SPEC 草稿/Testing list，根功能登记 decomposition_required=true；父 MO 认领后在范围内拆子模块及其上下文，子 MO 再拆 tasks；接受 MO 的 decompose 后，以 decompose-accept 登记子模块并重新 global-plan。用户无需另交模块资料包。两种入口都保留全局只读上下文、子模块独立验收、父 MO 汇总和统一 Auditor 门禁。细则必读 [切片规约](references/slicing.md) 与 [父子 MO 协议](../migration-protocol/references/module-decomposition.md)。

所有跨层输入输出通过 Ledger 已提交引用传递；本技能不授予角色之外的写权限。

## 3. 标准模式
推荐：按无环依赖和锁可用性派发 ready 模块；消费 Ledger 完成事件唤醒精确订阅者；blocked 不占用工作线程。

禁止：按目录机械拆模块、漏掉跨模块整体用例、无生产者的 Yellow 永久等待。

## 4. 接口契约
输入 assignment_ref + event_ref + absolute artifact refs；输出角色权限矩阵许可的事件及模板工件。文件已生成不等于已接受，必须收到 Ledger ACK。

## 5. 检查
CASE 覆盖归属与验收角色分开：模块阶段唯一验收 owner 为对应 MO，审计阶段为对应 Auditor；当前范围完整 Green 且已有门禁满足即直接记录。跨模块 paths 保留参与者；锁相交不并行；全局测试未通过不称完成。

## 6. 配套资产
使用 [主要模板](../../template/global-input.json)；其他工件由 [模板索引](../../template/INDEX.md) 定位。无项目执行器时按 Yellow 处理，不能生成假测试结果。

实现前必须 global-plan：所有需求/用例都有 owner、模块 registry 匹配、整体测试可追溯。audit_queue 仅登记遗留；须先满足全部模块本轮收尾门禁才安排问题审计，保留最终全局审计门禁。

## Auditor 启动门禁

必须等所有模块本轮完成或明确挂起、无在途 worker 与可推进动作，再统一拉起 Auditor。dependency-ready/resume 优先；audit-collect 会重复校验。宿主实际启动/恢复各 subagent 及 Used Skills。finding 路由、依赖复测与人工释放见 [当前运行契约](../migration-protocol/references/local-runtime.md)。

跨模块或不确定的业务边界必须交人工决策，记录 boundary_review 及批准后再接受 global-plan；Global 只执行已批准的边界、依赖和路由。已批准范围内的常规调度无需重复询问。

启动时读取宿主 prepare 的 project_context_ref 和固定项目版本，按 [项目上下文协议](../migration-protocol/references/project-context.md) 生成完整 SPEC/Testing list/input.json，再初始化 Ledger 并派发。Global 不写 mutable 项目配置，更新由宿主依据真实用户输入提交；下游始终使用运行快照。

按完整 registry 独立维护每个 MO 的进度；单模块失败不触发其他 MO 的取消、失败标记或统一挂起。全局 quality 仅是聚合展示；继续 status.ready_modules 并等待 module_rounds.active_modules，直到全量收尾。具体遵守 [模块隔离与全量收尾](../migration-protocol/references/state-machine.md#模块隔离与全量收尾)。

切片前评估目标已有能力与用户指定的外部模块，完成语义抽取和全局复用目录，再分配模块 scope/context、提供方/消费者与共享适配 owner。必读 [二方库复用协议](../migration-protocol/references/reuse-dependencies.md)；目录是下游规划输入，不是对业务验收的替代。

## 功能清单来源与完备性

默认从测试用例汇总提取模块功能列表；没有汇总时，先完整理解存量源码并抽取功能，之后生成需求/CASE。逐项核对源码入口、功能与用例的双向覆盖；任何疑问立即人工介入。新运行 global-plan 必填 feature_inventory_ref 和 feature_owners，完备性与处理流程见 [切片规范](references/slicing.md#功能清单完备性门禁)。

## 父 MO 名称与最终报告

父 MO 一律显示为 `parent-mo-<module_id>`（如 parent-mo-M010），派发/恢复使用 `status.parent_mo_names`，技术实例 ID 与显示名分开。GO 在本轮收尾后必须向用户提供完整 CASE 状态清单，非 Green 逐项汇总根因、责任方、下一步及证据；无测试环境不能仅称“迁移成功”。按 [GO 报告协议](../migration-protocol/references/migration-report.md) 读取 status.migration_report，不重复验收或触发全量测试。

## 切片完整性

GO 的 register、decompose-accept、global-plan 执行 [四维协议](../migration-protocol/references/dimension-slicing.md)；先据上下文/功能清单划模块 scope，再逐模块分析 UI → Logic → Adhesive → Resource，既有目标能力/二方库须对齐源码功能。
