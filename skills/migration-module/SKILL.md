---
name: migration-module
description: 模块状态机门禁、DoD、子任务验收与循环控制，用于 SDD-TDD-Migration 的 Module-Orchestrator 任务。
---

# migration-module

## 1. 定位
服务 Module-Orchestrator；先读取 [共享协议](../migration-protocol/SKILL.md)，再读 [职责协议](../migration-protocol/references/state-machine.md)。

## 2. 核心规约
每个迁移事件验证前置 phase、版本、产物与批准者；仅 MO 决定模块状态，Ledger 验证写入。

所有跨层输入输出通过 Ledger 已提交引用传递；本技能不授予角色之外的写权限。

## 3. 标准模式
推荐：收到 worker submission → 独立核验 → 接受/驳回事件 → 下一合法阶段；失败按预算分流。

禁止：看到文件已存在就标 done；先更新 Green 再补复测；恢复时清空计数。

## 4. 接口契约
输入 assignment_ref + event_ref + absolute artifact refs；输出角色权限矩阵许可的事件及模板工件。文件已生成不等于已接受，必须收到 Ledger ACK。

## 5. 检查
所有转移符合状态表；冻结与完成清单分离；未解决问题都有 next_action；已用预算不会回退。

## 6. 配套资产
使用 [主要模板](../../template/module-input.json)；其他工件由 [模板索引](../../template/INDEX.md) 定位。无项目执行器时按 Yellow 处理，不能生成假测试结果。

控制补充：使用 Ledger 的 assign→submit→accept 接受阶段结果；只允许单模块一个活动 worker。session 原地恢复优先；替换需停止旧 worker 与 checkpoint 事件。recover 只在预算/停滞上限后经具体新增轮数批准，普通 resume 不清零。

本地诊断需 diagnosis-accept；审计修复需 repair-accept。DoD 挂起后恢复 testing 并复测；阻塞中需重规划时 invalidate，旧边界不再复用。详见 [控制流闭环](../migration-protocol/references/local-runtime.md#控制流闭环修订)。

模块执行顺序：Implementer Coding → MO 接受代码 → Test-Runner Testing。可修复 Red/Yellow 均优先 Diagnostician 诊断 → MO 接受 → 自动派发一轮 Fixer → MO 接受补丁 → Test-Runner 正式复测；不因 Yellow 颜色直接跳过可修复问题，也不等待 Auditor 才进行首次本地修复。确认依赖/外围问题直接 audit-defer，一轮复测不通过也交接。waiting-auditor 不占 worker；audit-resume 只接受独立 Auditor 裁决，不能直接完成模块。

Auditor 跨模块收尾使用 audit-work/audit-retest；守住负责模块与发现模块各自的 SPEC 和测试基线。awaiting-human 时禁止继续派修复。

审计批次按 finding 和依赖推进，audit-retest 也可用于受影响的原 Green 中间模块。失败只停关联分支；证据受阻用 audit-block，人工摘要批准后的 audit-release 由 Global 执行，再恢复通常的 plan/freeze/resume/recover 守卫。

模块范围的 CASE/PATH 由本模块 MO 唯一验收；正式测试完整 Green 且 DoD 满足即直接记录，无额外会签。审计中的模块守卫不代替 Auditor 验收。新增跨模块或不确定业务边界须人工决策，批准后才走相应 CR/冻结/恢复。

各 MO 独立运行：只依据本模块的测试证据和已确认依赖判断状态，禁止复制其他模块的失败或全局聚合颜色。并行同伴失败时继续自身合法动作；真实依赖等待保留本模块既有结果并记录 Yellow 阻塞原因。模块本轮结束以自身 DoD 或明确挂起记录和 worker 收尾为准，见 [模块隔离规则](../migration-protocol/references/state-machine.md#模块隔离与全量收尾)。

父子分工：GO 划分模块 scope/所需上下文；父 MO 读取全局规划上下文、认领 status.module_inputs 分配包，在获分配范围内拆子模块 scope/context 并 decompose；GO decompose-accept 后启动独立子 MO。父 MO 管理范围、覆盖与依赖，逐个等候子 MO，并 module-summary 汇总；子 MO 基于子 scope/context 拆 tasks，不再创建 MO，各自冻结、编码、测试与验收。规划须绑定 assigned_module，不能自行扩大范围。父子均需读取全局存量/目标代码、架构、知识及最新分工，优先复用目标已有能力，写权限仍按本模块 scope/锁。必读 [父子 MO 与规划上下文](../migration-protocol/references/module-decomposition.md)。

父 MO 将能力目录映射到模块需求，统一共享适配并分发子上下文；子 MO 冻结逐需求的 reuse/adapt/reference/new 决策及 task/PATH 映射，验收实际接线和完整测试。详见 [二方库复用协议](../migration-protocol/references/reuse-dependencies.md)。

Test-Runner 按 test_scope 先 build 后 automation；环境缺测通过 automation-unavailable 明确本轮收尾，下游代码调度与 Green 验收分开。读取 [双环节协议](../migration-protocol/references/build-automation.md)。
