# 进度信号、局部阻塞与重新规划

测试异常的确定出口见 [构建和自动化异常回执](build-automation.md#构建和自动化异常回执)：Auditor 构建失败进入相关分支人工问题；自动化超时保留失败观测；截断报告转结构化 Yellow 并通过原 submit/accept 关闭 assignment。宿主已退出但无可接受回执时仍按下文 revoke 流程处理，不能假设所有进程退出均已被 Ledger 接受。

## 1. 校验范围

GO 接受 `global-plan` 时检查完整功能清单、来源证据、全部模块/父级四维分配与覆盖。运行派发仍检查已接受的全局契约及 registry，但仅递归检查**当前模块、其实际依赖链及这些模块的父级分配**；不遍历无关兄弟的分析/源码证据。父 MO 的分配与审核记录仍是本模块的约束。

本模块定义、实现证据及真实依赖变化仍需失效处理；全局规范或已接受全局规划本身损坏仍需 GO 处理。局部异常不得改写无关模块颜色、取消 worker 或阻止其合法派发。

## 2. invalidate 后必须有明确出口

`status` 发现旧计划/代码证据失效，返回可处理的 `invalidate`；仍有活动 worker 时先提示宿主 `revoke`。宿主必须实际停止 worker 并提供停止证据，不能凭游标推断进程已退出。

MO 接受 `invalidate` 后：

1. 将旧 plan/ref/hash、freeze、代码基线、测试结果及四维实现证据保存到 `planning_history`；事件和 `artifacts` 快照保留。
2. 清除当前 plan/freeze/代码及构建基线、任务完成记录和旧上下文接受记录，进入 `specifying`。旧结果保留但 stale，不能参与新验收；修复预算不重置。
3. 已认领分配仍有效 → 下一步 `plan`，Spec-Designer 重新提交计划，按正常澄清/批准/冻结门禁推进。
4. 当前模块、父级或实际依赖的分配证据无效 → `allocation-review-required`，交 GO 恢复已批准的原始证据，或保留旧 run 后重新规划新 run。不能就地改已登记的 scope/hash 来掩盖变化。

OpenSpec 当前视图撤下旧受管定义，显示“Replanning required”；旧定义仍可从历史事件及快照恢复。不删除用户自有文件，不自动接受新 SPEC，不复用过期 Green。

## 3. 宿主必须消费的进度信号

每次事件 ACK、命令拒绝、worker 返回或异常退出后，宿主重新读取 `ledger.py status`。等待 worker 期间至少每 60 秒检查其真实状态并刷新 status；不用重复派发来探测进度。

`status.workflow_progress` 同步写入 `<run_root>/ledger/progress.json` 和 `reports/workflow-attention.md`：

| 字段/信号 | 含义与处理 |
| --- | --- |
| `runnable_actions` | 继续无冲突、独立的 ready 动作；提交时仍须通过真实门禁 |
| `signals` | 阻塞原因、owner、next_action、sequence 和证据；按模块处理 |
| `notify_user=true` | 宿主必须向用户展示需决策/介入事项、受影响范围、原因、证据和下一步；不能只写日志后静默退出 |
| `no-runnable-action-and-no-worker` / `state=stalled` | 当前没有可推进动作且没有活动 worker；立即交 GO 排查并反馈。它是停滞快照，不等于已证明死锁 |
| `worker_watches` | 活动 assignment 最近一次同作用域事件后的无进展时长；宿主核实进程是否仍存活 |
| `worker-progress-overdue` | 默认 900 秒无同作用域事件，提醒人工/宿主核实；init 可设置正整数 `worker_stall_timeout_seconds`。不是自动取消或释放锁 |
| `operation-rejected` | 各作用域当前 revision 下被拒操作及原因分别计数；相同操作/原因累计拒绝 3 次升级人工信号，其他模块的拒绝不清零，禁止原样重试空转 |
| `not-implemented` / `label=未实现` | MO 核验替代实现均不可行后接受的具体功能缺口；立即展示范围、核验证据及所需人工决策。无可复用库本身不构成该信号，详见 [复用协议第 8 节](reuse-dependencies.md) |

拒绝请求仍返回非零退出码；在日志可读、诊断可写时持久化 `reports/rejected-operation.json`，不提交业务事件、不改变质量。作用域 revision 前进后，旧拒绝不再作为当前阻塞提示。诊断是可重建/可替换的提示，不是第二条业务总线。

若真实 worker 已退出但 assignment 仍活动，宿主保存退出日志并走 revoke，再根据恢复点续作或记录有证据的挂起；仍运行时先核实/停止，禁止超时后直接重授锁。父 MO/GO 不得为满足 Auditor 收尾门禁批量挂起无关模块。

上述信号在 status 被调用时生成，不会自行推进工作流。可选 [watchdog](watchdog.md) 独立只读监听、留存诊断并通知；不调用 status、派发 Agent 或提交恢复操作。宿主停止或必须的人工决定未到时仍不能自行推进，门禁/权限/预算不会因为超时被绕过。

## 4. 自动化缺测出口

当前代码已接受且 build Green，仅自动化环境无法启动时：Test-Runner 提交仅 `test-environment=blocked` 的 testing 报告 → MO `automation-unavailable` → `automation-deferred`。逐 PATH Yellow/未执行、有缺测证据；独立模块和可消费当前构建代码的真实下游继续。若已派发，先保存启动失败证据并结束/revoke worker。

等待全部模块本轮结束、父汇总有效后，Auditor 继续审查对应 SPEC/CASE/PATH 和缺测证据；其他 Red/Yellow 仍按修复/复核闭环处理。最终仍仅缺环境时，独立 Auditor 的 blocked audit-testing 报告 → `audit-unavailable` → `completed-with-unverified-tests`。本轮结束但质量 Yellow；不因该缺测强制等待人工，也不声称功能验证通过。

环境恢复后重新预检和正式复测，不能把“环境恢复”直接写成 Green。具体守卫见 [构建与自动化协议](build-automation.md)。


## 授权改码、投影恢复与文件锁等待

### 授权 worker 的工作副本

status 仍校验冻结 SPEC、复用依据及不可变证据。有效且未挂起的 Implementer/Fixer 在当前 assignment 的 write_paths 内正常修改工作副本时，不因旧代码 hash 改变而推荐 revoke；等待 submit → MO accept 校验完整新代码清单、范围、任务追溯与维度证据。测试、依赖消费和 DoD 仍要求已接受的当前基线。SPEC 漂移、外部证据漂移、路径重定向及 worker 已撤销后的未接受改动仍走原失效门禁。Host 继续落实写权限与 fencing，轮询不能作为放宽权限的依据。

### 事件提交与投影结果分开

Ledger apply 的成功回执含 `committed: true`、event_id、sequence 和 `projection`。后者包含本次投影 sequence、`status: current|pending`、errors（stage/module_id/reason/next_action）。`pending` 表示事实事件已持久化，不能把同一业务操作当作未提交后换 request_id 重做；原 request_id 重试仍返回原事件，并尝试重建当前投影。

status 从事件恢复状态，单模块 OpenSpec 或报告写入失败返回 projection.errors，并通过 workflow_progress 的 projection-pending 信号通知 Host；有效的无关动作继续。投影更新失败时磁盘文件可能落后，须以返回的 Ledger sequence/状态及有效工件引用为准。即使进度报告自身不能写入，命令返回仍带诊断。日志完整性损坏、run 身份/快照校验失败仍保护性停止，不纳入可忽略的投影故障。

status 先尝试写 workflow-attention.md，再将包含末端写入错误的进度保存到 ledger/progress.json，供旁路监听读取。progress 写入失败时仅补写一次，并带入首次失败的诊断；再次失败就返回全部错误，不递归重试、不追加业务事件。两个诊断出口均不可写时，旧磁盘投影可能仍存在，Host 必须展示本次返回的 projection.errors，不能只依赖 watchdog。补写成功仍保留本次故障，下一次正常 status 完整重建后才撤下信号。

对于 JSON 损坏的 OpenSpec manifest，只有本 run 的 projection-owners 记录已验证时才自动恢复：先将原字节保存到 `run_root/reports/projection-recovery/<module_id>/<sha256>.manifest`，再按 Ledger 重建。损坏内容不能用作删除清单；有效但属于其他 owner 的 manifest、符号链接或无法验证归属的文件保留原状并提示处理。恢复不改业务事件或质量。

### 有时限的锁获取

`.ledger.lock`、`.context.lock` 和 Harmony `.prepare.lock` 统一使用非阻塞重试；默认最多等待 10 秒。Host 可通过 `SDD_LOCK_TIMEOUT_SECONDS` 设置正的有限秒数（允许小数）。该值仅控制获取锁的等待，不限制已持锁事务执行时间。

超时抛出 LockTimeout；Ledger/项目上下文 CLI 返回 `status: lock-timeout`、lock_path、timeout_seconds、owner=host 和 next_action。Host 保存命令回执到对应 run staging，检查持锁进程，再重试；不会自动偷锁、撤销 assignment、重置预算或改测试结果。超时后的拒绝处理不再次争用同一把锁。旁路 watchdog 不获取业务锁，也不会代替 Host 执行恢复。

## 并行拒绝与审计撤销顺序

拒绝计数按 module/global、revision、operation、reason 的 fingerprint 独立保存在 reports/rejections/<fingerprint>.json。reports/rejected-operation.json 只保留最新导航兼容。并行交错拒绝不会互相清零；status 聚合所有当前作用域计数，revision 更新后撤下旧提示但保留历史文件。

活动全局审计期间不推荐模块 invalidate 等被审计锁禁止的操作；快照失效时全局优先提示 Host audit-revoke 并立即通知。Host 实际确认审计 worker 已停止、提供 stopped_worker_ref 后才可撤销；其后模块重新获得 invalidate/规划入口。watchdog 只转达该提示，不执行停止、撤销或重新规划。
