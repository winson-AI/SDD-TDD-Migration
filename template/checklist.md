# {{module-id}} Checklist

定义冻结，检查结果由 Ledger 依据批准事件更新；所有 checked 项必须链接证据。freeze 阶段不要求代码/测试已经完成。

## Freeze Gate — R1 / R2
- [ ] F01 范围与整体用例映射完整；证据：{{ref}}
- [ ] F02 需求可验证且覆盖正常/边界/异常；证据：{{ref}}
- [ ] F03 新架构、接口、数据、安全/性能约束与依赖已定义；证据：{{ref}}
- [ ] F04 测试设计独立，Mock 边界与 Main 契约明确；证据：{{ref}}
- [ ] F05 tasks 有 ID、依赖、写范围、完成准则与双向追溯；证据：{{ref}}
- [ ] F06 无未决阻断问题；R1/R2 人类决定绑定当前内容或合法沿用；证据：{{ref}}
- [ ] F07 六件套定义与测试设计摘要已固定，满足 MO 接受冻结的所有前置条件；证据：{{ref}}

- [ ] F08 planning 上下文报告与当前 plan_ref 匹配；全局/父/子、生产链路、接口与复用核对齐备；证据：{{context_ref}}
- [ ] F09 已核对目标实现与二方库冗余；确认可替代部分已规划 reuse/adapt、唯一重构 owner、依赖切换/清理 tasks 和受影响回归；无冗余需提供检查依据；证据：{{reuse-alignment-ref}}

## Execution Context Gates

- [ ] E01 Coding 前实际 Implementer 预检已由 MO 接受，身份/版本/任务/工具/范围齐备；证据：{{context_ref}}
- [ ] E02 Testing 前实际 Test Runner 预检已接受，PATH/代码/真实提供方/环境与数据齐备；证据：{{context_ref}}
- [ ] E03 如触发 Fixer，每轮先核对诊断、历史策略、预算与冻结范围；证据：{{context_ref-or-not-applicable-evidence}}

执行门禁按阶段核对；冻结时不要求 E01–E03 已完成，也不能用这些勾选替代 Ledger 事件。

## DoD Gate — R3 / Delivery Readiness
- [ ] D01 当前 freeze 有效，代码版本可重建；证据：{{ref}}
- [ ] D02 所有必需 tasks 已验收，无无归属代码；证据：{{ref}}
- [ ] D03 当前全部必需 PATH 与验收条目覆盖，Main、构建、静态检查均 Green；证据：{{ref}}
- [ ] D04 断言真实完整、非空、无未经批准核心 Mock；证据：{{ref}}
- [ ] D05 历史非 Green 全有复测链，无遗留 Red/Yellow、skip、stale 或 flaky；证据：{{ref}}
- [ ] D06 依赖版本匹配、CR 闭环、无未决人工阻塞；证据：{{ref}}
- [ ] D07 冻结文档/追溯/实现日志/测试证据可冷读，无孤儿工件；证据：{{ref}}
- [ ] D08 模块独立验收完成，全局上报内容齐全且可在 module_completed 提交时同步记录；证据：{{ref}}
- [ ] D09 冗余目标实现已按冻结方案重构为真实库依赖/必要适配，调用迁移及清理完成，保留兼容入口有依据，fidelity/受影响消费者已正式验证；无冗余引用检查依据；证据：{{implementation-and-test-refs}}

模块 DoD 不代表全局审计或人类合并授权。归档前另核验全局整体测试、Auditor 裁决与具体版本的交付批准。

## 四维覆盖门禁

- [ ] F-OWNER v2 capability 的 baseline/叶子 owner 有证据，消费者依赖与写授权正确；共享实现唯一 owner、写锁范围具体，稳定 provider 与修改目标分离；证据：{{ownership-and-allocation-refs}}
- [ ] F-SOURCE 如发生来源追加，已读取 Ledger 当前快照/影响报告，受影响计划重新冻结；无关计划延续有精确 hash 依据，未借来源变化重置预算或抹掉失败；证据：{{source-change-event-or-not-applicable}}
- [ ] D-PROVIDER 如变更 provider，本轮版本交付、消费者映射和正式复测链完整；旧副本不能代替 live 验证；证据：{{owner-consumer-version-and-retest-refs}}

- [ ] F-DIM UI → Logic → Adhesive → Resource 有序分析，N/A 有依据，未决项为空；父子条目无遗漏；证据：{{dimension_analysis_ref}}
- [ ] F-TRACE design/spec/tasks 的 item ID 与 dimension_trace 一致，TASK/PATH/ASSERT 完整，资源消费者与真实接线明确；证据：{{ref}}
- [ ] D-DIM 全部适用条目实现证据齐全，资源实物及消费者已核验，正式测试/fidelity 通过；证据：{{dimension_evidence-and-test-results}}

- [ ] F-TASK-SCOPE 先定义每项任务 scope，再完成 scope_sha256 绑定的四维分析；逐维 implementation 指导明确，N/A 留证，TASK/PATH/ASSERT 覆盖完整；证据：{{stage-plan}}
- [ ] D-TASK-SCOPE task_trace 文件属于对应任务 write_paths，实现符合冻结任务四维分析；证据：{{implementation-result}}

## 埋点适用性（不新增全局门禁）

- [ ] F-TELEMETRY 已检查范围内埋点；无埋点模块/任务以有据 N/A 满足此检查，无需 SDK/用例/环境；适用事件已映射到任务/业务PATH/ASSERT及验收层级；证据：{{scope-review-or-telemetry-contract}}
- [ ] D-TELEMETRY 无埋点仅核对 N/A；有埋点时当前冻结层级的真实接线与结果可追溯，未验证如实 Yellow，不能用截图/构建或库测试替代；证据：{{N/A-or-real-results}}
