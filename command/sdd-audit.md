---
description: /sdd-audit <run-id> — 独立全局复测与修复委派
---

# /sdd-audit

## 1. 用法
`/sdd-audit <run-id>`

## 2. 编排步骤
1. 读取 [AGENTS.md](../AGENTS.md)、[运行协议](../skills/migration-protocol/references/runtime.md)，解析参数为绝对路径及规范 ID。
2. 前置门控：完整 registry 中所有 MO 本轮独立完成或基于自身证据明确挂起，无活动 worker、无可推进动作；手工调用本命令也不得跳过等待，不得为审计强制结束其他 MO。模块 registry 和整体用例完整；实例与实现/修复/脚本作者分离；可冻结候选版本；未生成的代码不能测试，只报告 Yellow。
3. 检查现有工件与版本；同请求幂等恢复，不删除、不静默覆盖。普通命令不直接写业务工件或投影。
4. 由宿主向 Ledger 提交 audit_requested；收到 ACK 后派发对应角色。聚合所有模块，重跑非 Green/过期/未运行，再跑整体测试与受影响回归；失败经 MO 委派修复，Auditor 复测并按上限输出报告。
5. 输出已提交事件/当前状态/产物路径和下一动作，命令结束。角色内部按授权预算运行；命令不嵌套执行其他 slash command。

## 3. 调用契约
目标角色：[Auditor](../Agents/auditor.md)。宿主用实际可用的任务工具启动，参数只有 package_root、assignment_ref、event_ref；Ledger 按协议串行服务。定义文件不会自动安装或注册不存在的工具。

## 4. 参数验证
run-id/change-name 为 kebab-case，module-id 为 `M[0-9]{3,}`；禁止路径逃逸。JSON 中占位符、未决必填值、零必需用例不能作为有效运行输入。status 可读取尚未完成的输入状态。

## 5. 硬约束
命令只解析、门控、提交/查询和派发；无业务代码、无状态双写；叶子不能私传结果；无有效批准不推断已冻结；所有门禁由对应守卫/权限校验再次验证。

## 6. 期望输出
```text
✅ accepted | event=<id> | run=<run-id> | next=<账本动作>
⚠️ blocked | reason=<门禁/依赖/人工> | evidence=<绝对路径或事件>
❌ failed | reason=<实际错误> | recorded=<event-id或transport-unavailable>
```
status 使用 `snapshot sequence=<n>` 及当前三态摘要，不伪造事件接受回执。

## 7. 对应规格
[状态机](../skills/migration-protocol/references/state-machine.md)、[OpenSpec 契约](../skills/migration-protocol/references/openspec.md)。

## 上下文就绪门禁

全部 MO 收尾后，Auditor audit-plan 前提交 audit-analysis，audit-verdict 前提交当前证据的 audit-verdict，最终 audit-assign 前提交 audit-testing；Fixer/Testing 仍独立预检。预检不替代独立复测与裁决。详见 [阶段协议](../skills/migration-protocol/references/context-readiness.md)。

## 8. 自查
参数与前置有效；工具实际存在；没有越权写入；回执来源可信；恢复指令与 phase 一致。

## 本地实现接入

Global audit-assign → Auditor execute_test --module GLOBAL → audit。具体 payload/命令用法见 [local-runtime.md](../skills/migration-protocol/references/local-runtime.md)。宿主必须把已授权身份绑定到 host-context；不能让请求内自报 role 直接获得权限。控制器不自动启动 Agent，不替宿主写目标代码。

本地审计失败后的下一步为 audit-route / repair-accept，不能立即循环 audit-assign。模块修复复测完成后才开启下一轮，报告需关联上一轮非 Green 的 test_run_id。

当前入口必须等全部模块本轮结束/明确挂起，且无活动或可推进工作，才统一扫描所有并行遗留：audit-collect → Auditor audit-plan → Global audit-route-batch → 负责模块 MO audit-work → Fixer → Test-Runner → 原发现模块 audit-retest → audit-verdict。按 finding 与依赖顺序执行，失败关联分支待人工，独立分支继续；汇总后须批准 audit-release 才能进入常规恢复，不再循环 problem-assign。全部完成后做最终 audit-assign/audit。
