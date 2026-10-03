# 模板索引

`{{...}}` 是待填字段，示例值不是真实运行结果；实例化后消除占位符，初始 pending/null/untested 保持真实状态。模板与 migration-ledger/schemas 只描述形状，业务门禁以 Ledger 校验为准。每一步需要的模板由游标步骤的 `templates` 给出，路径规则见 [资产根与留存](../skills/migration-protocol/references/storage-layout.md#总则)。

| 模板 | 作者 | 用途 |
| --- | --- | --- |
| [project-context.json](project-context.json) | 宿主 | 项目长期配置，无 run/module 状态 |
| [project-context-request.json](project-context-request.json) | 宿主 | 配置 init/update 的 patch、revision、幂等 ID 与来源引用 |
| [run-request.json](run-request.json) | 宿主 | 本次选择、临时覆盖与宿主元数据，prepare 固化后交 GO |
| [single-module-input.json](single-module-input.json) | 宿主 | 单模块入口的两个参数（entry_mode、module_name） |
| [global-input.json](global-input.json) | GO | prepare 返回的本轮输入；GO 补齐规范、需求、CASE 与全局路径后，宿主保存为 input.json 并原样提交 init |
| [module-slicing.json](module-slicing.json) | 人工（可选） | module_slicing.module_import_ref 指向的模块方案 |
| [reuse-source.json](reuse-source.json) | 宿主 | reuse_sources 的外部来源元素；TARGET 自动纳入 |
| [ledger-request.json](ledger-request.json) | 宿主 | Ledger CLI 请求外壳 |
| [feature-inventory.json](feature-inventory.json) | GO | 完整功能清单及源码/用例来源映射 |
| [global-plan.json](global-plan.json) | GO | 全局需求、CASE 与功能归属，global-plan 验收输入 |
| [module-input.json](module-input.json) | GO | register 载荷：根模块的 scope、CASE、写范围、上下文、四维分配与行为审阅 |
| [dimension-analysis.json](dimension-analysis.json) | GO / 父 MO | 四维源闭包、适用性与父子分配 |
| [module-decomposition.json](module-decomposition.json) | 父 MO | 子功能拆分方案，GO 接受后登记子模块 |
| [batch-envelope.json](batch-envelope.json) | 父 MO | 批量冻结信封；一次人类批准覆盖条目完全匹配的孩子 |
| [reuse-catalog.json](reuse-catalog.json) | GO | 功能语义能力目录 |
| [source-impact.json](source-impact.json) | GO | 同 run 来源追加的影响报告 |
| [status.md](status.md) | MO | 模块决策；Ledger 生成 status 投影 |
| [test-design-input.json](test-design-input.json) | MO | 编码前独立测试设计的输入：规格、CASE 与任务范围 |
| [stage-plan.json](stage-plan.json) | Spec-Designer | 规划提交：六件套引用、任务追溯、理解证据与批准边界；PATH、任务范围、spec 与 test_design_ref 由 Ledger 从已接受设计补全 |
| [proposal.md](proposal.md) | Spec-Designer | 六件套 proposal |
| [spec.md](spec.md) | Spec-Designer | specs/<capability>/spec.md 的 delta |
| [design.md](design.md) | Spec-Designer | 旧→新架构与测试设计 |
| [tasks.md](tasks.md) | Spec-Designer | 任务定义；完成勾选由 Ledger 投影 |
| [checklist.md](checklist.md) | 包内固定 | 冻结与 DoD 评审清单；Ledger 接受 plan 时按哈希绑定到模块，投影时附证据链接与运行勾选 |
| [change-impact.json](change-impact.json) | Spec-Designer / MO | within-envelope 再冻结的影响审查，绑定旧 freeze 与新 plan 摘要 |
| [reuse-plan.json](reuse-plan.json) | Spec-Designer | 逐需求的能力选择与接入映射，由 stage-plan.reuse_plan_ref 冻结 |
| [reuse-fidelity.md](reuse-fidelity.md) | Spec-Designer | 存量源码与选中能力的逐行为对齐 |
| [telemetry-contract.json](telemetry-contract.json) | Spec-Designer | 适用埋点的 stage-plan.telemetry 片段，不是独立请求 |
| [telemetry-analysis.md](telemetry-analysis.md) | GO / MO / Spec-Designer / Auditor | 埋点适用性与保真分析 |
| [semantic-model.json](semantic-model.json) | Spec-Designer | 语义模型字段示例（含图像检查、图片信号 item、非精确图形）；实例化后仍须通过 strict 校验，模板不证明源闭包完整 |
| [ui-state-test-design.md](ui-state-test-design.md) | Spec-Designer | 并入模块 test-design 的 UI 状态设计 |
| [domain-worker-request.json](domain-worker-request.json) | Spec-Designer | 受限 UI 源分析请求 |
| [knowledge-request.json](knowledge-request.json) | Spec-Designer / Implementer / Fixer / Diagnostician | 知识主题查询请求，不要求 assignment |
| [test-design-result.json](test-design-result.json) | Test-Runner | 独立测试设计结果；MO 接受后由 Ledger 绑定进 plan |
| [test-paths.json](test-paths.json) | Test-Runner | build/unit/static/automation 各类 PATH 的写法 |
| [harmony-test-path.json](harmony-test-path.json) | Test-Runner | 逐 ASSERT 的冻结谓词、验证类型、匹配与时序 |
| [visual-test-path.json](visual-test-path.json) | Test-Runner | 逐 runtime 目标的视觉路径片段（含仅承载图像检查的变体） |
| [test-adapter.json](test-adapter.json) | 宿主 | 宿主审核过的实际 argv |
| [harmony-test-adapter.json](harmony-test-adapter.json) | Test-Runner | Main argv 与任务超时，不依赖源项目绝对路径 |
| [harmony-config.json](harmony-config.json) | Test-Runner | 设备、模型环境引用与采集配置 |
| [visual-test-adapter.json](visual-test-adapter.json) | Test-Runner | execute_test 的视觉 adapter，只接已独立产出的原始 alignment |
| [visual-execution.json](visual-execution.json) | Test-Runner | 冻结 PATH 配置、run 级设备/模型环境与宿主锁回执样式 |
| [visual-request.json](visual-request.json) | Test-Runner | 受限 worker 的安装、捕获与语义取证请求 |
| [visual-capture-execution.json](visual-capture-execution.json) | 受限 worker / 运行器 | 受管捕获执行回执 |
| [visual-alignment.json](visual-alignment.json) | Test-Runner | 正式视觉结果片段 |
| [interaction-evidence.json](interaction-evidence.json) | Test-Runner | automation 声明手势时的结果扩展 |
| [stage-result.json](stage-result.json) | Test-Runner | 阶段 tests 结果 |
| [test-result.json](test-result.json) | Test-Runner / Auditor / Fixer | 单条 PATH 的实际执行记录 |
| [context-readiness.json](context-readiness.json) | 各执行角色 | 上下文预检报告；检查项与必读引用取自步骤视图 |
| [implementation.md](implementation.md) | Implementer / Fixer | 提交与 tasks 追溯、回归、回滚及 reuse_trace |
| [resource-request.json](resource-request.json) | Implementer / Fixer | 资源执行请求 |
| [implementation-gap.json](implementation-gap.json) | MO | 核验证实无法实现时 suspend(not-implemented) 的依据 |
| [diagnosis.md](diagnosis.md) | Diagnostician | 只读根因报告 |
| [fix-note.json](fix-note.json) | Fixer | 修复记忆，经阶段结果 fix_note_ref 引用 |
| [change-request.md](change-request.md) | Fixer | 变更建议，Spec-Designer/MO 审核 |
| [escalation.md](escalation.md) | Escalation | 人工问题与超时 |
| [human-decision.json](human-decision.json) | Escalation | 真实人类反馈的规范化记录 |
| [audit-code-review.json](audit-code-review.json) | Auditor | 全部 MO 收尾后的整体代码审查 |
| [audit-change-inventory.md](audit-change-inventory.md) | Auditor | 本次代码修改清单，由 audit-code-review.json 引用 |
| [audit-closure-plan.json](audit-closure-plan.json) | Auditor | finding 到修复模块的路由 |
| [audit-review.json](audit-review.json) | Auditor | 待验证清单为空时的独立证据审阅 |
| [problem-audit-report.json](problem-audit-report.json) | Auditor | 问题审计报告；示例为不可执行时的 Yellow，可执行模块须附真实 tests 结果 |
| [audit-report.md](audit-report.md) | Auditor | 全局快照、复测与最终裁决 |
| [migration-report.md](migration-report.md) | GO | 收尾报告展示契约；本地运行优先使用 Ledger 生成的报告 |
| [watchdog-host-state.json](watchdog-host-state.json) | 宿主 | 本 run 的真实状态导出，不是 Ledger 请求 |
| [workflow-verification.md](workflow-verification.md) | 宿主 | 适配后的行为验收矩阵 |
