---
description: /sdd-verify <run-id> [--scope global|module|projection|final] [--module-id M001] — 只读核验 Ledger 记录与指定范围的 OpenSpec 投影
---

# /sdd-verify

## 用法与范围

`/sdd-verify <run-id> [--scope global|module|projection|final] [--module-id M001]`

| scope | 检查范围 | 时机 |
| --- | --- | --- |
| `global` | 事件链、prepare 快照、顶层布局与归属 | 初始化/全局调度前 |
| `module` | 指定模块、祖先分配与实际依赖的当前规范/投影（须 module-id） | plan、module 与逐模块派发前 |
| `projection`（默认） | 整个 run 的生成视图与 Ledger 一致 | 巡检、审计前全量阅读 |
| `final` | projection 全量且正式报告为 completed / completed-with-unverified-tests | GO 交付或归档前 |

`verified=true` 只说明该范围记录/投影一致，不证明真实派发、命令/设备实际运行或功能 Green，也不替代冻结、权限、派发与验收门禁；`final` 可接受保留 Yellow 缺测的收尾。module 核验允许模块投影序号早于全局最新但不早于该模块最后一次事实变更；内容与 Ledger 推导结果比较，manifest 存在本身不足以通过。

## 编排步骤

1. 读[判定与红线](../skills/migration-protocol/references/host-integration.md#4-判定与红线)，从 prepare 返回值解析绝对 run_root；按动作选 scope，只读不提交。
2. 执行并读取 `verified`、`scope`、`module_id`、`checked_modules`、`sequence`、`failures`、`next_actions`、`limitations`：

   ```sh
   verify_openspec.py --root <run> --scope module --module-id M001
   ```

3. 未通过按 `failures[].scope/module_id/recovery_action` 处理相应范围；无关模块的投影错误不阻止当前 MO，不把一次失败写成"整轮绕过 Ledger"或重建 run。核验器不修复、不搬迁历史、不改状态。

Python 接口 `inspect(root, scope="projection", module_id=None)`；exit 0 该范围 verified，exit 1 返回失败详情，业务验收看 `next_actions`。运行根须匹配 prepare 固化的 `.sdd-runs/<run_id>`。

```text
✅ verified | run=<run-id> | scope=<scope> | modules=<checked_modules>
⚠️ unverified | run=<run-id> | scope=<scope> | failures=<check 列表> | next=<next_actions>
❌ failed | reason=<实际错误>
```
