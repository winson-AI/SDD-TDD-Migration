# 模板实例化索引

所有 `{{...}}` 均为待填字段，不代表真实运行值。实例化后必须消除占位符；初始 pending/null/untested 保持真实状态，不得为模板完整而改成通过。缺失输入进入澄清，不能随意填入。

| 模板 | 作者及用途 |
| --- | --- |
| [global-input.json](global-input.json) | Global 从固定项目上下文生成本轮输入；宿主保存 input.json，Ledger 绑定引用及快照 |
| [module-input.json](module-input.json) | Global 生成功能切片输入，Ledger 写 modules/Mxxx/_input.json |
| [global-ledger.json](global-ledger.json) | Ledger 维护全局缓存；不得当事实日志直接修改 |
| [assignment.json](assignment.json) | 宿主身份绑定的单次任务；Ledger 创建 |
| [event.json](event.json) | 入站事件信封；Ledger 补服务端事件 ID/sequence/time |
| [proposal.md](proposal.md) | Spec-Designer：六件套 proposal |
| [spec.md](spec.md) | Spec-Designer：实例化为 specs/<capability>/spec.md 的 delta |
| [design.md](design.md) | Spec-Designer：旧→新架构与测试设计 |
| [tasks.md](tasks.md) | Spec-Designer 定义计划；Ledger 投影完成进度 |
| [status.md](status.md) | MO 决策，Ledger 将其中 JSON 同步为 modules/Mxxx.json 与 status.md |
| [checklist.md](checklist.md) | 冻结定义与 DoD 定义；Ledger 更新证据 |
| [freeze.json](freeze.json) | Spec-Designer 提案、Human/MO 审核、Ledger 接受 |
| [test-paths.json](test-paths.json) | Test-Runner：冻结前路径设计；实现后脚本绑定 |
| [test-result.json](test-result.json) | Test-Runner/Auditor 记录实际执行；Fixer 自测标明 producer |
| [implementation.md](implementation.md) | Implementer/Fixer：提交与 tasks 追溯、回归、回滚 |
| [diagnosis.md](diagnosis.md) | Diagnostician：只读根因报告 |
| [change-request.md](change-request.md) | Fixer 提建议；Spec-Designer/MO 审核 |
| [escalation.md](escalation.md) | Escalation：人工问题与超时 |
| [human-decision.json](human-decision.json) | 真实人类反馈引用，Escalation 规范化、Ledger 接受 |
| [audit-report.md](audit-report.md) | Auditor：全局快照、复测与最终裁决 |
| [workflow-verification.md](workflow-verification.md) | 宿主适配后的行为验收矩阵 |

运行根目录与 ACL 见 [runtime.md](../skills/migration-protocol/references/runtime.md)。JSON 字段为 v1 交换契约示例；宿主还须执行身份、版本、状态门禁与非空证据校验，JSON 可解析并不代表业务有效。

## 本地控制器附加模板

- [ledger-request.json](ledger-request.json)：CLI 请求，operation 与 payload 见 local-runtime。
- [stage-plan.json](stage-plan.json)：六件套引用、冻结路径与任务、理解证据、批准边界。
- [stage-result.json](stage-result.json)：阶段 tests 结果；implementation 结构见 local-runtime。
- [test-adapter.json](test-adapter.json)：宿主审核过的实际 argv，不是任意用户文本执行入口。

这些模板字段由 contracts.py 做运行期校验；JSON schema 文件位于 migration-ledger/schemas，描述基本交换形状，不能替代业务守卫。

- [global-plan.json](global-plan.json)：全局需求/用例归属验收输入。
- [fix-note.json](fix-note.json)：Fixer 必填修复记忆；通过阶段结果 fix_note_ref 引用。
- [problem-audit-report.json](problem-audit-report.json)：问题审计报告；可执行模块须提供真实 tests result，此模板展示不可执行的 Yellow。

- [audit-closure-plan.json](audit-closure-plan.json)：Auditor 按 finding_id 路由到一个或多个修复模块，精确绑定各方 SPEC 与测试路径。

## Harmony 测试

- [harmony-test-path.json](harmony-test-path.json)：逐 ASSERT 的冻结谓词、验证类型、匹配和时序。
- [harmony-config.json](harmony-config.json)：设备、模型环境引用、压缩/反思/视频配置。
- [harmony-test-adapter.json](harmony-test-adapter.json)：Main argv 与任务超时；不依赖源项目绝对路径。

- [module-slicing.json](module-slicing.json)：global-input.module_slicing.module_import_ref 指向的可选人工模块方案；字段与优先级见 [切片规约](../skills/migration-global/references/slicing.md)。

- [single-module-input.json](single-module-input.json)：单模块入口的两个参数示例（entry_mode/module_name），合并已有项目上下文；根功能 ID、scope、SPEC/Testing list 由 Global 生成，父 MO 继续拆子功能，独立子 MO 执行，父汇总后统一 Auditor。

- [project-context.json](project-context.json)：项目长期 config 内容模板，宿主根据用户输入整理，无 run/module 状态。
- [project-context-request.json](project-context-request.json)：init/update 的 patch、CAS revision、幂等 ID 和用户来源引用。
- [run-request.json](run-request.json)：本次选择、临时覆盖与宿主元数据，prepare 固化后交 Global；用户单模块选择仍只有模式和名称。

- [module-decomposition.json](module-decomposition.json)：父 MO 的子功能拆分方案，绑定全局 planning_context 和认领的 assigned_module，逐子分配 scope/context_refs；GO 接受后登记独立子模块。
- module-input 的 parent_module_id/decomposition_required、scope/context_refs 与子 stage-plan.planning_context/assigned_module 由宿主/角色填充；不增加用户入口参数。project-context.knowledge_paths 用于固化父子共享知识文档。

- [reuse-source.json](reuse-source.json)：project-context/global-input.reuse_sources 的可选外部来源元素；TARGET 自动包含。
- [reuse-catalog.json](reuse-catalog.json)：GO 的功能语义抽取目录，父/子 MO 按需求进一步核验细化。
- [source-impact.json](source-impact.json)：GO 的同 run 来源追加影响报告，完整来源集合、v2 catalog、全部叶子 replan/unchanged 与父分配评审；与 source-review/reconfigure-sources 配套。
- [reuse-plan.json](reuse-plan.json)：子模块逐需求的能力选择、差异、task/PATH 和接入映射；由 stage-plan.reuse_plan_ref 冻结，Ledger 投影到 change/reuse.md。
- [reuse-fidelity.md](reuse-fidelity.md)：存量源码与选中能力逐行为对齐；reuse-plan.fidelity 绑定源码、报告和复现 PATH/ASSERT，正式结果沿 Main/Ledger 留档。
- [implementation-gap.json](implementation-gap.json)：适配/参考/自主实现均经核验证实不可行时，MO 通过 suspend(reason_code=not-implemented) 接受，生成“未实现”人工提醒；没有可复用库本身不能作为结论。
- implementation.md 说明新增 reuse_trace；控制器检查选中映射的实际版本、task 文件和生产绑定证据。

## 上下文预检工件

[context-readiness.json](context-readiness.json) 是 Coding 的 blocked 起始模板；其他 stage 根据 status.context_requirements 生成完整检查项。经 context-submit 提交，原操作 context_ref 接受；assignment 保留同一报告引用。见 [阶段协议](../skills/migration-protocol/references/context-readiness.md)。

## 功能清单来源与完备性

[feature-inventory.json](feature-inventory.json)：GO 抽取的完整功能清单及源码/用例来源映射；默认用例汇总优先，缺失则源码抽取。global-plan.feature_inventory_ref/feature_owners 接受清单并分配叶子，疑问通过 boundary_review 人工决策。

## 构建与自动化

project-context/global-input 的 build 为可选配置，空对象表示由 GO 发现命令。stage-plan/test-paths 示例含 kind=build 和 kind=automation；build.command.selection_ref 冻结选择依据。assign 增加 test_scope。automation-unavailable / automation-resume / audit-unavailable 的 payload.context_ref 引用实际角色提交的报告。详见 [双环节协议](../skills/migration-protocol/references/build-automation.md)。

- [audit-review.json](audit-review.json)：Auditor 待验证清单为空时的独立证据审阅；不能用于跳过 Red/Yellow。

- [migration-report.md](migration-report.md)：GO 收尾展示契约，包含完整 CASE 状态、父 MO 名称及非 Green 原因/证据；本地运行优先使用 Ledger 自动生成的报告。

- [dimension-analysis.json](dimension-analysis.json)：GO/父 MO 四维源闭包、条件适用、目标映射与父子分配；先绑定模块/子模块 scope；下游 stage-plan 先划 tasks.scope，再生成任务四维分析并关联 PATH/ASSERT。

- [audit-code-review.json](audit-code-review.json)：全部 MO 收尾后的独立整体代码审查，含全模块改动/冗余/复用/公共能力/fidelity；CR-* 治理发现先于剩余 Red/Yellow 进入闭环。
- [audit-change-inventory.md](audit-change-inventory.md)：Auditor 必交的本次代码修改清单；模块/功能点、逐文件修改路径及前后快照、代码影响范围、CASE/PATH/query/脚本/断言映射与缺口。由 audit-code-review.json.change_inventory_ref 引用，GO 报告提供同版链接。
