---
description: /sdd-verify <run-id> — 只读核验本 run 确经 Ledger 管道产出 OpenSpec 投影
---

# /sdd-verify

## 1. 用法
`/sdd-verify <run-id>`

fail-closed 只读门禁。确认该 run 是真 Ledger-backed（prepare → init → apply），而非手写文件模拟。用于推进前的前置心跳与收尾的强制核验；对真实 run 的任意阶段（含仅规划/冻结、尚无代码）都通过，一旦有人绕过 Ledger 立即失败。它只读，不改状态、不补写投影、不搬迁历史。

## 2. 编排步骤
1. 读取 [AGENTS.md](../AGENTS.md)、[运行协议](../skills/migration-protocol/references/runtime.md)，解析参数为绝对路径及规范 ID。
2. 前置门控：run 根为 `<workspace_root>/.sdd-runs/<run_id>`；只需读权限；不派发、不提交任何业务事件。
3. 运行 `verify_openspec.py --root <run>`，读取 `verified` 与 `failures`。
4. `verified=false` 时按 `failures[].check` 指明缺环（events-journal / events-integrity / storage-layout / workflow-hub / no-fallback-openspec / change-manifest / migration-report），提示回到 prepare → init → apply 重跑；不得据 `ledger/module-registry.json`、散文报告或空 openspec 目录等手写产物宣称已执行。
5. 输出核验结论与证据路径，命令结束。命令不嵌套执行其他 slash command，不修改任何 run 资产。

## 3. 调用契约
目标角色：[Ledger](../Agents/ledger.md)（只读投影核验）。宿主用实际可用的任务工具启动，参数只有 package_root、run_root；不需要 host-context 写身份，也不获取任何锁。定义文件不会自动安装或注册不存在的工具。

## 4. 参数验证
run-id 为 kebab-case；run 根必须是 `.sdd-runs/<run_id>`；禁止路径逃逸与符号链接重定向。旧兼容目录用 `ledger.py history` 只读重放，不经本门禁。

## 5. 硬约束
命令只解析、核验和查询；无业务代码、无状态写入、无事件提交；不代替 status 的路由，也不改变任何门禁结论。核验通过不等于业务验收，仍以 DoD 与 Auditor 裁决为准。

## 6. 期望输出
```text
✅ verified | run=<run-id> | openspec=top-level
⚠️ unverified | run=<run-id> | failures=<check 列表> | next=prepare→init→apply
❌ failed | reason=<实际错误>
```

## 7. 对应规格
[留存布局与投影完整性收尾门禁](../skills/migration-protocol/references/storage-layout.md#openspec-投影完整性收尾门禁)、[本地运行指南](../skills/migration-protocol/references/local-runtime.md)。

## 8. 自查
参数与前置有效；工具实际存在；只读未写入；结论来源为 verify_openspec 实际返回，不臆测通过。

## 本地实现接入

`python3 <package>/skills/migration-ledger/scripts/verify_openspec.py --root <run>`；exit 0 = verified，exit 1 = 未通过并打印 failures。它复用 `ledger.read_events` 做事件链完整性校验，从 prepare 固化的 `storage_layout` 解析顶层 openspec 位置。宿主可在 `/sdd-run`、`/sdd-module`、`/sdd-plan` 推进前及 `/sdd-audit`、`/sdd-archive` 收尾时调用；`status.openspec_binding.location` 提供同源的 top-level / in-run-fallback 快速判读。控制器不自动启动 Agent，不替宿主写目标代码。
