# Watchdog：旁路观察与通知

唯一原则：不影响当前迁移工作流/控制流，只监听状态并提供必要通知。它是可选宿主程序，不是第十一个业务 Agent。不派发/恢复 Agent，不提交 Ledger operation，不 revoke/invalidate，不停止业务进程，不释放业务锁，不重置预算，不修改验收结果。通知中的 next_action 只是供 Host/用户审阅的文字建议。

## 入口与生命周期

先完成正常 prepare/init；watchdog 不成为初始化前置条件，也不会被 sdd-run 自动启动。启动/停止/崩溃/禁用观察器均不影响迁移继续执行。

```sh
# 单次检查；stdout 为 JSON，含 host/workers/findings/notifications
python3 <package_root>/skills/migration-ledger/scripts/watchdog.py check \
  --root <workspace_root>/.sdd-runs/<run_id>

# 持续检查；未确认交付的通知会以相同 notice_id 重放
python3 <package_root>/skills/migration-ledger/scripts/watchdog.py watch \
  --root <workspace_root>/.sdd-runs/<run_id>

# Host 展示/可靠接收通知后确认，可重复传入 --notice-id
python3 <package_root>/skills/migration-ledger/scripts/watchdog.py ack \
  --root <workspace_root>/.sdd-runs/<run_id> --notice-id notice-<实际通知ID中的数字>
```

Host 必须把 notifications 展示给用户，或先可靠写入其通知收件箱再负责展示，然后调用 ack；仅启动后台程序或读取 stdout 不等于用户已收到通知。Host 按 notice_id 去重展示，同一 notice 内的多条通知整体确认；确认只表示通知已接收，不表示问题解决。程序不发送邮件/聊天消息、不执行外部通知 hook。未自动安装系统服务；需要覆盖宿主失联时，由宿主已有可靠监督服务或独立进程承载，不能与主调度循环一起退出。

每个 run 一个观察实例，用 runs/watchdog/.watchdog.lock 互斥；ack 用独立 .ack.lock，可在 watch 运行时确认，忙时重试。只锁观察器自己的文件，不获取 .ledger.lock/.context.lock；忙时退出观察命令，不阻止工作流。watch 在已有有效终态且没有待处理投影异常，或 Host 明确 stopped 后输出尚待交付通知并结束，未确认项仍保留，可用 check 重放；paused 时保持观察，不产生新的业务催促，但仍可重放尚未交付的历史通知。Ctrl-C/终止观察进程也不影响任何业务 worker。

## 配置冻结

长期 project-context.json 的可选 watchdog 字段经既有 update/prepare 保存在本轮 context/snapshot.json.effective_config.watchdog；同 run 不追随长期配置更新。未配置时使用默认值：

| 字段 | 默认 | 含义 |
| --- | --- | --- |
| enabled | true | 允许显式启动观察命令；不是自动启动开关 |
| mode | observe-only | 唯一支持模式，不允许 auto-recover |
| interval_seconds | 60 | 检查间隔 |
| host_stale_seconds | 180 | 宿主导出/心跳过期及持续 ready 提醒阈值 |
| worker_stall_seconds | 900 | 宿主报告的业务进展过期提醒；不判死亡 |
| check_timeout_seconds | 10 | 每轮只读子进程检查时限 |

禁用 watchdog 不停 run。已有 run 无此配置也能使用默认策略，无需修改旧快照或旧 hash。

## 接入真实宿主状态

Host 维护本轮 `runs/watchdog/host-state.json`，格式见 [导出模板](../../../template/watchdog-host-state.json)。Host 应根据实际任务工具/API 的查询结果原子替换该文件，并保护写权限。模板、模型猜测、Ledger assignment 存在都不是存活证明。

支持两种来源：

1. **host-api**：提供实际 provider、execution_id、instance_id、带时区 observed_at，以及 running/exited/unknown。宿主 Agent API 各不相同，本包提供导出适配入口，不假设存在统一 API。宿主负责真实查询与导出；接口未接入、失败或过期时明确 unknown。
2. **local-process**：Host 提供 pid、`process_start`（启动时 `/bin/ps -p PID -o lstart=` 的原始去空白结果）、observed_at。观察器执行同一只读查询核对真实进程；PID 消失为 exited，启动标识变化、无权限、命令不可用为 unknown。不能只用 PID 判断同一 worker，也不等同于业务有进展。

assignment worker 必须匹配 module_id/assignment_id/instance_id；全局审计使用 module_id=null。不匹配不借用其他任务的存活结果。GO、父 MO、Spec、预检等无 assignment 的执行可提供 execution_id；只有明确 expected_active=true 的已退出编排执行才提示 Host 核查，正常结束不能被自动当故障。

heartbeat_at 代表宿主调度循环心跳，last_progress_at 代表实际业务进展，两者不能用检查时间、日志刷新或投影 mtime 代替。未提供业务进展接口时显示 progress=unknown，不猜测死亡或自动取消。

## 检查与通知

程序在有时限的只读子进程中核对 prepare 布局/快照、重放 Ledger 事件、读取最近 progress 投影和宿主导出。不调用会写投影的 ledger.status，不修改 OpenSpec 或业务状态。进度投影 sequence 落后时报告 routing-observation-stale，不把旧 ready 当当前可执行命令。

- 宿主/worker unknown、宿主心跳过期、已结束但 assignment 尚活动：留证提醒，由 Host 决定后续处理。
- 实际运行 worker 的业务进展过期：提醒核查，不杀进程。
- 相同 ready 动作长期存在且未观察到运行 worker：提示 Host 核查是否已认领，不宣称已证明漏派发。
- 现有 Ledger 人工信号：转成去重通知，不扩大阻塞范围。
- 查询超时、日志不完整或读取错误：observation-unavailable；不修日志、不偷锁、不把旧告警当已解决。
- 暂停/停止、有效 Green 交付等待或 completed-with-unverified-tests：不反复催执行，不把 Yellow 改 Green。

业务终态仍存在 `projection-pending` 时，观察状态为 `completed-with-pending-diagnostics`，保留该异常通知并继续监听，不再催促业务执行。该值只属于 watchdog，不改变 Ledger 的业务终态、质量或验收。ack 后停止重放已交付通知，但异常仍保持开启；Host 使用原 status 入口重建投影，当前 progress 中该信号消失后，观察器产生 closed 通知并按 completed 收尾。显式 paused/stopped 仍遵守宿主控制。

告警状态按 run/scope/code 去重，首次出现及关闭产生 notice 文件；持续同一问题不反复生成新 notice。通知交付使用独立的 pending_notices：未 ack 的 notice 在每次 check/watch 输出中重放，notify_user=true；确认后不再重放，直到出现新的开启/关闭事件。同一告警关闭后再次出现具有新的 notice_id。

先原子保存 notice（含 active 检查点），再更新 state/latest，最后输出 stdout。state/latest 写入失败或 stdout 丢失后，重启从 notice 恢复并重放，不把“已经写文件”误当“已交付”。ack 绑定本 run 已存在 notice 的内容摘要，幂等且不删除历史；旧版 notice 也会作为未确认记录重放一次，确认后静默。此机制保证可重试交付，Host 仍必须负责去重展示与确认；不宣称 stdout 提供恰好一次交付。

closed 只表示该监测条件不再展示，不代表代码已修复或测试验收通过。真正业务结果仍以 Ledger 为准。无法写诊断时 CLI 返回 observer-error 到 stderr，Host 应展示该监听故障，不能因此停止迁移。

## 留存与权限边界

```text
.sdd-runs/<run_id>/
├── runs/watchdog/
│   ├── .watchdog.lock          # 仅观察器互斥
│   ├── .ack.lock               # 仅通知确认互斥
│   ├── host-state.json         # Host 原子导出的真实状态，观察器只读
│   ├── state.json              # 去重、上次检查和 ready 观察计时
│   └── acknowledged/notice-<timestamp>.json # Host 交付确认，绑定 notice 摘要
└── reports/watchdog/
    ├── latest.json             # 最新诊断，包括 unknown/通知
    └── notice-<timestamp>.json # 持久通知与 active 检查点；未确认时重放
```

不创建系统临时文件，不保存环境变量或凭证，不生成第四顶层目录。OpenSpec 原投影器只提供诊断文件链接，不将监听结果并入模块质量或调度门禁。业务 Agent 仍通过原 Ledger 获得跨层信息；Host 可以直接消费自己的运行健康通知。

诊断是可重建旁路记录。原 run 重启继续去重，新 run 隔离；watchdog 永不代替 GO/MO/Auditor 的恢复操作与验收。
