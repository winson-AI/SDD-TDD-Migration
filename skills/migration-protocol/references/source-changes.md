# 同 run 追加只读来源：三层影响评审与局部恢复

使用场景：运行中用户补充新的二方库/其他项目模块，需要沿用本 run 的记录。普通项目配置更新仍仅影响新运行；本入口只追加 source_id，不修改 target/legacy、架构、验收、预算、测试配置、registry、scope、write_paths 或依赖。不能覆盖旧 snapshot 或重跑 prepare 来伪造新输入。

## 1. GO：评估来源、归属与影响范围

1. 读取当前 Ledger 的 project_context_ref、全局分配及已知问题。来源标准化后保留全部旧条目原值，仅追加用户提供的新 source_id；只读模块必须与 target 分离。
2. 扫描新来源，生成覆盖完整来源集合的 v2 reuse-catalog；显式 owner 的定义见 [复用协议](reuse-dependencies.md#10-显式-provider-归属与合法版本变更)。不能把写权限覆盖当作交付责任。
3. 填写 [source-impact.json](../../../template/source-impact.json)。逐叶子评估 reuse/adapt/reference/new，包括先前无候选而准备自主实现的模块；父 MO 提供现有分配、共享能力、调用方和写锁评审，经 Ledger 引用交 GO 接受。
4. 每个叶子 action 为 `replan` 或 `unchanged`，必须附理由及证据。未冻结模块必须 replan；unchanged 仅允许已有冻结且证据仍有效的计划。所有实际依赖 replan 模块的消费者也须 replan；语义影响超出登记依赖时 GO 主动纳入。
   影响证据按 UI → Logic → Adhesive → Resource 对照既有条目，记录新来源如何改变实现策略、适配/资源接线及 TASK/PATH 验证指导，不能只写“增加库路径”。原维度分配继续保存 scope/条目和历史分析，新策略以本次接受的影响依据和重新冻结 tasks 明确承接；若需改变 scope、条目分配或公共契约，则按下一条处理，不用来源事务隐藏范围变化。
5. parent_reviews 覆盖全部父节点。若新来源要求修改分工/DAG/写权限，本事务不能暗改：先做具体分配方案，按现有分配流程或新 run 处理，再规划；跨模块/不确定业务边界须人工决定。当前版本没有原位重写已登记 registry 的通用操作。

GO 提交 global-planning 的 context-submit（draft_ref 绑定影响报告），随后提交全局 `source-review`，payload 为 `report_ref`、`context_ref`。Ledger 接受后提供 `source_change_review.subject_sha256`；这是具体来源、全体模块/父节点当前状态、原快照、全局计划及审计状态的审批摘要。模块推进后旧评审可能过期，须重新核对，不能重用旧批准。

## 2. Host：版本事务与明确恢复

用户明确同意该具体来源与影响后，由 Host 使用现有 `decision` 保存真实用户来源，module_id=null、subject_sha256 为上一步摘要；不得根据模板自动批准。原话已充分授权具体效果时直接记录，无需重复询问。不能把“加入库”自动理解成解除另一个业务阻塞。

Host 提交全局 `reconfigure-sources`：

```json
{"decision_id": "D-SOURCES-001", "subject_sha256": "<GO source-review 返回的实际摘要>"}
```

上述是 payload；外层照常提供 schema_version/run_id/request_id/expected_revision/operation，使用可信 Host 身份。只接受这两个字段，来源集合来自已经提交的 GO 报告。

- 切换必须在 worker 都结束的协调点进行；不能自动终止无关 MO。停止工作须真实停止证据和 revoke，结束后重新评审过期摘要。
- 活动独立审计或收尾审计批次不能被配置事务打断；按原 audit-revoke 或 Auditor 人工审核/audit-release 流程退出后再评审。已经排队的遗留问题和普通模块阻塞不一律禁止来源追加。
- 模块已有 blocker 时，默认原样保留原因和等待状态，仅把受影响计划的恢复目标改成 specifying。确实与来源补充相关、需要恢复的 blocker，在对应行填写当前 blocker 的 digest 作为 `resume_blocker_sha256`，由本次绑定批准明确授权进入重新规划。旧 blocker 留在历史，解除不代表测试通过。
- Red/Yellow results、repair findings、审计队列、已耗修复预算及作者/assignment 历史不删除。已有真实失败不能因为新增来源变成 Green；正式复测继续携带 retest_of。

事务生成 `context/revisions/<sha256>.json` 和 `context/files/<sha256>.snapshot`，保留原 source_refs/source_paths/link_manifest_ref，previous_context_ref 指向上一版本。原 context/snapshot.json、项目 defaults 和旧事件链不修改。事务沿用 Ledger 锁/CAS/幂等；文件先写后提交事件，孤儿文件不算生效，事件已提交后的投影失败可通过同 request_id 重试重建。

## 3. 父 MO：共享分工与局部恢复

GO 已在 source-review 接受完整影响评审；registry 不变时保留原 global-plan 覆盖关系，并附 source_review_ref，无需阻止无关模块等待第二次全局覆盖批准。若要改变覆盖/业务边界，仍执行原 global-plan 门禁。

- replan 叶子及其依赖闭包清除活动 plan、freeze、代码验收基线和旧上下文 acceptance；历史计划与结果保留，父 MO 重新组织这些子模块规划。
- unchanged 叶子保留冻结计划、代码和测试结果，Ledger 记录精确 plan_hash 的上下文延续依据。只允许这次已评审的来源/快照字段更新，不能借此改变其他冻结内容；下一次派发仍须新的阶段上下文 receipt。
- 全局只读视野保持完整。父 MO 对新增共享适配指定唯一子 MO owner，细化写范围；重叠写集合仍互斥，显式 owner 不会放开资源锁。
- 父摘要绑定孩子 revision，版本变化后由父 MO 重新汇总；Host 不伪造父 MO 验收。无关子模块 Green 保留，无须仅为重新汇总重跑测试。

## 4. 子 MO：规划、编码与验证

读取 status.planning_context.source_change_ref 中的新 catalog 和影响依据；按当前上下文、scope、四维分析重新生成 SPEC/tasks。replan 模块重新澄清/冻结，不能沿用已失效批准；unchanged 模块读取新上下文预检后继续原任务。

编码继续执行真实依赖接线、必要适配及重复代码清理，随后 Build → Automation → MO 验收。自动化环境不可用仍按 Yellow/缺测分流，不扩散给其他模块。OpenSpec 的失效显示复用既有 invalidate 投影机制，不另建完成状态。

## 5. 信号与 Auditor

Host 每次状态轮询同时读取 `source_change_next_step` 与 `workflow_progress.signals`：待具体批准、评审过期、等待 worker/审计均有明确下一步；它们不会替换独立模块的 runnable actions。不要读取旧 input.json 或 prepare 返回值作为当前运行上下文，当前事实以 Ledger 绑定的新引用为准。

Auditor 仍等所有 MO 收尾，收集原有及新增 Red/Yellow，结合提供方版本变化核对受影响消费者，再委派 Fixer/正式复核；无关有效 Green 不全量重跑。来源事务不替代 Auditor 裁决，也不重置审计预算。

此能力验证的是来源/范围/版本/事件契约；全量功能语义、归属和影响是否判定正确，仍由实际 GO/父子 MO 审查并留证。
