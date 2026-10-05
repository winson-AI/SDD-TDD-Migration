---
name: migration-global
description: 功能切片、架构差异解析、DAG 与全局三态调度，用于 SDD-TDD-Migration 的 Global-Orchestrator 任务。
---

# migration-global

来源/归属变化时遵守 [来源追加协议](../migration-protocol/references/source-changes.md)：完整来源和影响评审经 source-review 接受，Host 绑定批准后更新当前上下文；所有叶子（包括 new 路线）与父分配都须评审，仅受影响闭包重规划。新 capability 采用显式 owner，写集合不能当作业务归属。

## 1. 定位
服务 Global-Orchestrator；先读取 [共享协议](../migration-protocol/SKILL.md)，再按阅读卡读 [职责协议](../migration-protocol/references/runtime.md) 的相应小节。

## 2. 核心规约
入口默认 project，覆盖完整项目；single-module 按 module_name 选择根功能。GO 划分 scope、context_refs、代码范围与需求/CASE，先验全局覆盖。GO/MO 判断原子性，按需细分或保留当前节点进入叶子 tasks/SPEC；细分接受后重验 registry。叶子规划完备再冻结、实现、独立验收，实际父节点汇总，全体收尾后统一 Auditor。用户无需另交模块资料包。见[切片规约](references/slicing.md#总则)与[父子 MO 协议](../migration-protocol/references/module-decomposition.md#总则)，阅读卡按步骤取节。

所有跨层输入输出通过 Ledger 已提交引用传递；本技能不授予角色之外的写权限。

## 3. 标准模式
推荐：按无环依赖和锁可用性派发 ready 模块；消费 Ledger 完成事件唤醒精确订阅者；blocked 不占用工作线程。

禁止：按目录机械拆模块、漏掉跨模块整体用例、无生产者的 Yellow 永久等待。

## 4. 接口契约
见 [共享协议·通用约定](../migration-protocol/SKILL.md#通用约定)。

## 5. 检查
CASE 覆盖归属与验收角色分开：模块阶段唯一验收 owner 为对应 MO，审计阶段为对应 Auditor；当前范围完整 Green 且已有门禁满足即直接记录。跨模块 paths 保留参与者；锁相交不并行；全局测试未通过不称完成。

## 6. 配套资产
使用 [主要模板](../../template/global-input.json)；其他工件用游标步骤 `templates` 列出的模板。无项目执行器时按 Yellow 处理，不能生成假测试结果。

角色义务、调度/审计规则与专题入口以 [Agent 定义](../../Agents/global-orchestrator.md#专题义务) 和 [状态机](../migration-protocol/references/state-machine.md#模块隔离与全量收尾) 为准；本技能只保留执行规约与检查，不重复专题细则。
