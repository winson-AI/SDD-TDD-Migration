---
description: /sdd-verify <run-id> [--scope global|module|projection|final] [--module-id M001] — 只读核验 Ledger 记录与指定范围的 OpenSpec 投影
---

# /sdd-verify

## 用法与范围

`/sdd-verify <run-id> [--scope global|module|projection|final] [--module-id M001]`

| scope | 检查范围 | 调用时机 |
| --- | --- | --- |
| `global` | 事件链、prepare 快照、顶层布局与归属 | 初始化/全局调度前，检查公共基础；不扫描无关模块视图 |
| `module` | 指定模块、祖先分配与实际依赖的当前规范/投影 | `/sdd-plan`、`/sdd-module` 和逐模块派发前；必须传 module-id |
| `projection`（默认） | 整个 run 的生成视图与 Ledger 内容一致 | 投影巡检、审计前的全量阅读；规划中也可通过 |
| `final` | projection 全量检查，且正式报告处于 `completed` 或 `completed-with-unverified-tests` | GO 最终交付或归档前 |

`verified=true` 仅说明该范围的记录/投影一致性检查通过；它不证明宿主真的派发了 Agent、命令/设备实际运行、所有功能 Green，也不替代 Ledger 的冻结、权限、派发与验收门禁。`final` 可接受保留 Yellow 缺测的正式收尾，不能把它宣传成功能全部验证通过。

module 核验允许模块投影序号早于全局最新序号，但不得早于该模块最后一次事实变更，且 revision/freeze/定义/内容仍须一致；兄弟事件不强迫无关模块重写。projection/final 则核对全局最新投影。文档内容会与 Ledger 推导结果比较，manifest 存在本身不足以通过。

## 编排步骤

1. 读取 [AGENTS.md](../AGENTS.md) 与 [运行协议](../skills/migration-protocol/references/runtime.md)，从 prepare 返回值解析绝对 run_root。
2. 根据实际动作选择 scope；只读，不派发、不提交业务事件、不获取写锁。
3. 执行并读取 `verified`、`scope`、`module_id`、`checked_modules`、`sequence`、`failures`、`next_actions` 与 `limitations`：

   ```sh
   python3 <package>/skills/migration-ledger/scripts/verify_openspec.py --root <run> --scope module --module-id M001
   ```

4. 未通过时按 `failures[].scope/module_id/recovery_action` 处理相应范围。全局事件链/快照基础损坏影响整轮；无关模块的投影错误不阻止当前合法 MO。不得把一次全量 projection 失败写成“整轮绕过 Ledger”，或要求不分原因重建 run。
5. 输出核验范围、失败项与下一步。生成视图损坏按既有投影恢复协议处理；冻结源/事件证据问题恢复有效证据或按 Ledger 正常失效/重规划。核验器自身不修复、不搬迁历史、不修改状态。

## 调用与返回

工具为 [verify_openspec.py](../skills/migration-ledger/scripts/verify_openspec.py)，只需读权限；`--scope` 默认 projection。Python 接口为 `inspect(root, scope="projection", module_id=None)`；exit 0 表示该范围 verified，exit 1 返回失败详情。使用结果里的 `next_actions`，不从进程退出码推导业务验收。

```text
✅ verified | run=<run-id> | scope=<scope> | modules=<checked_modules>
⚠️ unverified | run=<run-id> | scope=<scope> | failures=<check 列表> | next=<next_actions>
❌ failed | reason=<实际错误>
```

运行根须匹配 prepare 固化的 `.sdd-runs/<run_id>`，禁止路径逃逸。旧兼容 run 的只读重放与恢复按 [留存布局](../skills/migration-protocol/references/storage-layout.md#openspec-投影完整性收尾门禁) 执行，不改写已有证据。
