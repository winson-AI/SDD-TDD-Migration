# Watchdog：旁路观察与通知

可选宿主程序；next_action 仅供 Host/用户审阅，不执行恢复。

## 总则

watchdog 仅观察和通知；不派发/恢复 Agent、不写 Ledger、不改门禁/结果/预算、不停进程/释放业务锁。Host 存活无法核实时为 unknown。不自动启动，缺失或失败不阻塞模块。

## 入口与生命周期

正常 prepare/init 后可显式启动；观察器启停不影响迁移。

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

Host 按 notice_id 去重展示或可靠存入通知收件箱后 ack，同 notice 整体确认；读取 stdout 不等于交付，ack 不等于解决。程序不发邮件/聊天、不执行通知 hook、不安装服务。覆盖宿主失联需独立监督进程。

每 run 一个实例，仅锁 runs/watchdog/.watchdog.lock；ack 使用独立 .ack.lock，忙时重试，不获取业务锁。有效终态无投影异常或 Host stopped 时，watch 输出未交付通知后结束，check 可重放。paused 保持观察、不催执行，仍重放历史待确认通知。

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

Host 按真实工具/API 查询原子更新 runs/watchdog/host-state.json 并保护写权限，见 [模板](../../../template/watchdog-host-state.json)；模板、模型猜测、assignment 均非存活证明。

支持两种来源：

1. **host-api**：真实 provider/execution_id/instance_id、带时区 observed_at、running/exited/unknown。接口缺失、失败或过期为 unknown，本包无统一 Agent API。
2. **local-process**：pid、process_start（启动时 `/bin/ps -p PID -o lstart=` 去空白结果）、observed_at；观察器同查询核对。PID 消失为 exited，启动标识变化/无权限/命令缺失为 unknown；PID 或存活不证明业务进展。

worker 匹配 module_id/assignment_id/instance_id，全局审计 module_id=null，不借用其他任务状态。GO/父 MO/Spec/预检可仅有 execution_id；其已退出且 expected_active=true 时才提醒。

heartbeat_at 为宿主心跳，last_progress_at 为业务进展；检查时间、日志或投影刷新不能替代。缺进展接口为 progress=unknown。

worker 可选 execution_state_path 指向本 run/attempt 的 execution-state.json；匹配 run/module/assignment/instance 后附 execution_output。输出字节和 last_output_at 仅是 I/O 观察，不证明存活或业务进展。真实宿主报告 exited 且输出未完整时通知 execution-output-incomplete；路径/身份/读取错误仅通知 execution-output-unreadable。

## 检查与通知

限时只读子进程核对 prepare 布局/快照、Ledger、progress 和宿主导出；不调用 ledger.status。progress sequence 落后报 routing-observation-stale，不把旧 ready 当可执行命令。

- 宿主/worker unknown、心跳/业务进展过期、assignment 未关闭但进程退出：提醒 Host 核查。
- 长期 ready 且无运行 worker：提醒核查认领，不断言漏派发。
- Ledger 人工信号：去重通知，不扩大影响。
- 查询超时/读取错误：observation-unavailable，保留旧告警，不修日志/偷锁。
- 暂停/停止、有效交付等待或 completed-with-unverified-tests：不催执行、不改 Green。

终态有 projection-pending 时显示 completed-with-pending-diagnostics 并继续监听，不催业务。ack 只停止重放；Host 按原 status 入口重建，信号消失后通知 closed 并收尾。仍遵守 paused/stopped，不改 Ledger 终态。

告警按 run/scope/code 去重，开启/关闭产生 notice；持续问题不重复生成。未 ack 的 pending_notices 每次重放且 notify_user=true；确认后静默，再次开启产生新 ID。

先原子保存 notice/active 检查点，再写 state/latest，最后 stdout；写失败/输出丢失可从 notice 恢复。ack 绑定本 run notice 摘要、幂等且保留历史；旧版 notice 亦需确认。Host 负责去重展示，不保证 stdout 恰好一次交付。

closed 仅表示监测条件消失，不是业务通过。写诊断失败向 stderr 返回 observer-error，Host 展示故障，迁移继续。

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

无系统临时文件/凭证/第四资产根。OpenSpec 仅链接诊断，不接入质量或门禁；业务 Agent 仍走 Ledger，Host 消费健康通知。同 run 重启继续去重，新 run 隔离。
