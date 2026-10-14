---
description: /sdd-archive <run-id> <decision.json绝对路径> — 核验交付批准并归档规格
---

# /sdd-archive

## 1. 用法
`/sdd-archive <run-id> <decision.json绝对路径>`

## 2. 编排步骤
1. 按[命令通用约定](../skills/migration-protocol/references/host-integration.md#命令通用约定)读取入口、解析参数并检查现有工件。
2. 前置门控：全部模块 DoD Green、最终审计 Green、批准绑定当前代码与 SPEC、无 stale、OpenSpec 工具与写锁可用；先 `verify_openspec.py --scope final`，失败按 recovery_action 恢复，不直接重建整轮；final 不把 Yellow 改 Green，见[核验范围](sdd-verify.md)。
3. 归档不产生 Ledger 事件：审核决策后做 delta 合并预演与冲突审阅，按核对过的 OpenSpec CLI 同步/归档并保留追溯；代码合并须另有授权。成功后运行 experience.py harvest 采集经验，补充抽象教训走 /sdd-retrospect。

## 3. 契约与规格
目标角色 [Global-Orchestrator](../Agents/global-orchestrator.md)；[验证、同步与归档](../skills/migration-protocol/references/openspec.md#验证同步与归档)、[投影完整性收尾门禁](../skills/migration-protocol/references/storage-layout.md#openspec-投影完整性收尾门禁)。
