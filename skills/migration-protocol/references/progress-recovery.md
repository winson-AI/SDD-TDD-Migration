# 进度信号、局部阻塞与重新规划

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
| `operation-rejected` | 最近一次被拒操作及原因。同一作用域 revision/操作/原因连续拒绝 3 次升级人工信号，禁止原样重试空转 |
| `not-implemented` / `label=未实现` | MO 核验替代实现均不可行后接受的具体功能缺口；立即展示范围、核验证据及所需人工决策。无可复用库本身不构成该信号，详见 [复用协议第 8 节](reuse-dependencies.md) |

拒绝请求仍返回非零退出码；在日志可读、诊断可写时持久化 `reports/rejected-operation.json`，不提交业务事件、不改变质量。作用域 revision 前进后，旧拒绝不再作为当前阻塞提示。诊断是可重建/可替换的提示，不是第二条业务总线。

若真实 worker 已退出但 assignment 仍活动，宿主保存退出日志并走 revoke，再根据恢复点续作或记录有证据的挂起；仍运行时先核实/停止，禁止超时后直接重授锁。父 MO/GO 不得为满足 Auditor 收尾门禁批量挂起无关模块。

这里只增强控制器信号与宿主响应契约，没有后台 watchdog。无人调用 status、宿主停止或必须的人工决定未到时，控制器不能自行推进；宿主必须明确告知用户等待原因。门禁/权限/预算不会因为超时被绕过。

## 4. 自动化缺测出口

当前代码已接受且 build Green，仅自动化环境无法启动时：Test-Runner 提交仅 `test-environment=blocked` 的 testing 报告 → MO `automation-unavailable` → `automation-deferred`。逐 PATH Yellow/未执行、有缺测证据；独立模块和可消费当前构建代码的真实下游继续。若已派发，先保存启动失败证据并结束/revoke worker。

等待全部模块本轮结束、父汇总有效后，Auditor 继续审查对应 SPEC/CASE/PATH 和缺测证据；其他 Red/Yellow 仍按修复/复核闭环处理。最终仍仅缺环境时，独立 Auditor 的 blocked audit-testing 报告 → `audit-unavailable` → `completed-with-unverified-tests`。本轮结束但质量 Yellow；不因该缺测强制等待人工，也不声称功能验证通过。

环境恢复后重新预检和正式复测，不能把“环境恢复”直接写成 Green。具体守卫见 [构建与自动化协议](build-automation.md)。
