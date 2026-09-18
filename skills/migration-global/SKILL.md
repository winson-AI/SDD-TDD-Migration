---
name: migration-global
description: 功能切片、架构差异解析、DAG 与全局三态调度，用于 SDD-TDD-Migration 的 Global-Orchestrator 任务。
---

# migration-global

## 1. 定位
服务 Global-Orchestrator；先读取 [共享协议](../migration-protocol/SKILL.md)，再读 [职责协议](../migration-protocol/references/runtime.md)。

## 2. 核心规约
入口默认 project，按项目需求划分多个 modules；single-module 仅增加模式与 module_name 两个入口参数，沿用项目上下文；Global 按名称定位功能，自主识别 scope/代码路径、分配模块 ID、生成模块级 SPEC 草案与 Testing list，再注册单节点 DAG、验收全局规划并启动 MO 及后续 Auditor。不得要求用户提供模块描述、scope、代码路径、SPEC 或测试列表作为入口前提。MO 组织正式六件套和路径设计、澄清冻结，不再拆成多个 modules。项目模式切片粒度由 Agent 决定，按业务触发→状态/数据变化→对外结果分析；支持 global-input 的可选人工模块导入。用户提供完整功能 use case 时，可按一级/二级功能目录划分 module，再分析 scope、测试列表并交模块生成 SPEC。具体输入、优先级和边界审核必须读取 [切片规约](references/slicing.md)。

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

实现前必须 global-plan：所有需求/用例都有 owner、模块 registry 匹配、整体测试可追溯。audit_queue 非空时安排问题审计，保留最终全局审计门禁。

## Auditor 启动门禁

必须等所有模块本轮完成或明确挂起、无在途 worker 与可推进动作，再统一拉起 Auditor。dependency-ready/resume 优先；audit-collect 会重复校验。宿主实际启动/恢复各 subagent 及 Used Skills。finding 路由、依赖复测与人工释放见 [当前运行契约](../migration-protocol/references/local-runtime.md)。

跨模块或不确定的业务边界必须交人工决策，记录 boundary_review 及批准后再接受 global-plan；Global 只执行已批准的边界、依赖和路由。已批准范围内的常规调度无需重复询问。

启动时读取宿主 prepare 的 project_context_ref 和固定项目版本，按 [项目上下文协议](../migration-protocol/references/project-context.md) 生成完整 SPEC/Testing list/input.json，再初始化 Ledger 并派发。Global 不写 mutable 项目配置，更新由宿主依据真实用户输入提交；下游始终使用运行快照。
