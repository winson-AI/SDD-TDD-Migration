# 宿主接入后的行为验收场景

这些是工作流验收案例，不是已执行结果。宿主接入完成后用隔离目标仓与可控测试适配器执行；必须采集事件/文件/进程证据。不能仅匹配提示词文本宣称门禁有效。

| ID | 注入场景 | 必须观察到的结果 |
| --- | --- | --- |
| WF-01 | 无冻结事件请求实现 | 拒绝派发/写入目标；记录缺冻结原因 |
| WF-02 | 已冻结但尚无 implementation_submitted 请求测试 | 不执行 Main；保持前置未完成 |
| WF-03 | Main exit 0 但 assertions 为空 | 非 Green，报告缺失断言 |
| WF-04 | Main 可复现 expected≠actual | Red，根因诊断→Fixer；修复后正式复测方能 Green |
| WF-05 | M001 等待 M002 契约 | M001 Yellow 挂起并释放锁；M002 完成后唤醒、重获锁和复测 |
| WF-06 | 缺设备/凭证且重试耗尽 | Yellow、结构化人工问题；超时不通过 |
| WF-07 | Fixer 请求修改冻结验收 | 权限拒绝；经 CR、设计影响、批准与再冻结才继续 |
| WF-08 | 同一实例兼 Auditor/Fixer 或脚本作者 | 独立性拒绝；换合法实例才审计 |
| WF-09 | 重复 request_id / 过期 revision | 同内容返回原 ACK，不同内容或过期写拒绝；无重复副作用 |
| WF-10 | 两模块写同一目录/子路径 | 不能同时授权，任务等待后串行 |
| WF-11 | 事件已提交、投影前崩溃 | replay 后恢复同一结果，不能重复执行已确认副作用 |
| WF-12 | 代码或消费者依赖版本改变 | 受影响 Green stale，最终报告不混合旧版本 |
| WF-13 | 同基线路径 pass/fail 交替 | flaky Yellow，不能择优记绿；按冻结策略稳定复测 |
| WF-14 | 无模块/漏整体用例/未运行路径 | 全局不能 Green，报告覆盖缺口 |
| WF-15 | 修复达到上限后 resume | 已用预算保留，等待增加预算决策，不能无限循环 |
| WF-16 | 手动编辑 status.md 或删除证据文件 | 不提升质量；从事件重建或 artifact_invalidated |
| WF-17 | 所有模块 Green，但整体集成失败 | Auditor 报 Red 并委派修复，不归档 |
| WF-18 | Auditor 首轮发现缺陷，Fixer 给自测通过 | Auditor 必须自己重跑，不直接采信 |
| WF-19 | 依赖存在环、生产者不存在、所有任务挂起 | 明确全局升级，不能永久等待 |
| WF-20 | 无真实 task/ledger/Main 适配器 | runtime/tooling Yellow；不报告已执行迁移 |
| WF-21 | lease 超时但旧 worker 仍可写 | 禁止重授锁，先停止或隔离旧进程 |
| WF-22 | 已归档候选基线之后又出现代码变化 | 旧审计/批准失效，拒绝本次归档 |
| WF-23 | 初次测试直接通过 | 保留 not-observed RED，不伪造 TDD 失败日志 |
| WF-24 | 提交旧版本人工答案或假身份 | 拒绝恢复；保留问题与当前版本绑定 |
| WF-25 | 无关模块的四维证据漂移 | 本模块仍可派发；实际依赖/父级漂移仍阻塞；global-plan 全量检查拒绝坏证据 |
| WF-26 | invalidate 后旧 plan 证据已失效 | 旧 plan/快照留历史，当前 plan 清空，进入 plan 或 GO 分配审查，不能反复 invalidate |
| WF-27 | 无可执行动作且无 worker，或 worker 超时、连续同原因拒绝三次 | workflow_progress 提供 owner/证据/下一步并提示人工；无关 ready 任务继续，不自动改质量或放锁 |
| WF-28 | 构建通过但 automation 环境缺失 | 模块 Yellow/未执行收尾，下游可继续；Auditor 审查后可 completed-with-unverified-tests，不能伪 Green |
| WF-29 | 拒绝诊断文件损坏 | 状态仍可查询，提示修复诊断，合法派发不受影响；被拒操作不写业务事件 |
