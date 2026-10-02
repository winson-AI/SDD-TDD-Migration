# 宿主接入后的行为验收场景

这些是工作流验收案例，不是已执行结果。宿主接入完成后用隔离目标仓与可控测试适配器执行；必须采集事件/文件/进程证据。不能仅匹配提示词文本宣称门禁有效。

| ID | 注入场景 | 必须观察到的结果 |
| --- | --- | --- |
| WF-01 | 无冻结事件请求实现 | 拒绝派发/写入目标；记录缺冻结原因 |
| WF-02 | 已冻结但实现结果尚未 submit/accept 就请求测试 | 不执行 Main；保持前置未完成 |
| WF-03 | Main exit 0 但 assertions 为空 | 非 Green，报告缺失断言 |
| WF-04 | Main 可复现 expected≠actual | Red，根因诊断→Fixer；修复后正式复测方能 Green |
| WF-05 | M001 等待 M002 契约 | M001 Yellow 挂起并释放锁；M002 完成后唤醒、重获锁和复测 |
| WF-06 | 缺设备/凭证且重试耗尽 | 保留 Yellow；纯自动化环境缺失按 automation-unavailable 缺测收尾，独立任务继续；其他需用户决策的问题按原升级协议，超时不通过 |
| WF-07 | Fixer 请求修改冻结验收 | 权限拒绝；经 CR、设计影响、批准与再冻结才继续 |
| WF-08 | 同一实例兼 Auditor/Fixer 或脚本作者 | 独立性拒绝；换合法实例才审计 |
| WF-09 | 重复 request_id / 过期 revision | 同内容返回原 ACK，不同内容或过期写拒绝；无重复副作用 |
| WF-10 | 两模块写同一目录/子路径 | 不能同时授权，任务等待后串行 |
| WF-11 | 事件已提交、投影前崩溃 | replay 后恢复同一结果，不能重复执行已确认副作用 |
| WF-12 | 代码或消费者依赖版本改变 | 受影响 Green stale，最终报告不混合旧版本 |
| WF-13 | 同基线路径 pass/fail 交替 | flaky Yellow，不能择优记绿；按冻结策略稳定复测 |
| WF-14 | 无模块/漏整体用例/未运行路径 | 全局不能 Green，报告覆盖缺口 |
| WF-15 | 修复达到上限后 resume | 已用预算保留，等待增加预算决策，不能无限循环 |
| WF-16 | 手动编辑 status.md 或删除证据文件 | 不提升质量；从事件重建或按 observed_invalidations 失效 |
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
| WF-30 | 二方库无可用候选，但可自主实现 | new 映射经过冻结后正常 Coding/Testing，不生成未实现提醒 |
| WF-31 | 适配/参考/自主实现经核验均不可行 | MO 接受带范围/revision/证据的未实现记录；status 和 GO 报告提醒人工，独立模块继续 |
| WF-32 | 无核验材料、仍有可行路线或报告范围/版本错误 | 拒绝未实现声明；原状态和事件保持不变 |
| WF-33 | 架构/知识文档固化到 context/files 后存在相对链接、循环引用或代码/图片链接 | 关联文件一起固化，阅读文档跳转至对应版本，原字节与重写内容分别校验；删除原文件后仍可读 |
| WF-34 | OpenSpec 六件套移到不同目录并引用已固化架构 | 内部跳转指向正确 SPEC/design 位置，外部知识跳转至本轮 context；重建不读取最新源文件 |
| WF-35 | 关联代码更新、固化目标被篡改或链接目标缺失 | 更新仅影响新 run，篡改拒绝使用；缺失链接明确 warning，不伪造完整知识链 |
| WF-36 | 目标已有实现与二方库语义冗余且可接入 | 规划唯一 owner，直接按冻结任务重构依赖/调用并清理重复逻辑；保留必要适配和完整回归，不重复造轮子 |
| WF-37 | 只加二方库依赖却仍走旧实现，或无依据保留两套业务逻辑 | MO 不接受为重构完成；补齐真实接线/清理及正式保真验证，不能靠编译通过验收 |
| WF-38 | 稳定 provider 位于多个 MO 的宽写范围 | null owner 不产生虚假依赖；写锁仍互斥；非空 owner 需合法叶子/权限/实际依赖 |
| WF-39 | 同 run 新增只读来源，部分模块不受影响 | GO 全范围评审、Host 精确批准、创建新快照；受影响闭包重规划，无关冻结/Green 保留并用新上下文继续 |
| WF-40 | 缺来源导致阻塞，另一个模块有不同业务阻塞或 Red | 明确批准可让相关 blocker 回到规划；其他 blocker/失败/预算/修复 memory 保留，新增来源不算通过 |
| WF-41 | 来源评审过期、旧来源被修改/删除、worker/审计活动中 | 拒绝事务并显示具体动作；不得取消其他 MO、覆盖配置或重置审计 |
| WF-42 | 来源切换后投影失败或同请求重试 | 事件为唯一提交点；重试恢复投影、只切换一次；旧 snapshot/链接/事件仍可校验 |
| WF-43 | 稳定 provider 必须修改本体 | owner 先获授权任务/版本方案，消费者失效并重规划；新版本交付后正式复测；adapt 不绕过 live hash |
| WF-46 | M002 投影损坏，但 M001 及其祖先/实际依赖有效 | module M001 核验可通过，projection 报 M002 故障；不能把全量失败回写全部 MO |
| WF-47 | planning 中全量投影一致但未正式收尾 | projection 可通过，final 必须拒绝；verified 不宣称真实派发或功能通过 |
| WF-48 | UI 多个 page/state，只给一条 visual PATH 或引用另一目标的节点/基线 | 冻结拒绝；每个 runtime 目标单独绑定 coverage、node_ids、baseline_ref |
| WF-49 | 视觉 Green 使用旧 HAP/旧 code_baseline，或 record 与实际 captured 不一致 | 正式结果拒绝；不能用旧 ALIGNED 覆盖当前版本 |
| WF-50 | Test-Runner 请求资源改写/自动修 UI，或 Spec-Designer 请求实现 | 受限工具拒绝跨角色操作；通过 Ledger 派给有权限的 Implementer/Fixer |
| WF-51 | reuse-catalog 缺少显式 provider owner 或使用旧结构 | 冻结拒绝；按当前目录结构重新生成并评审 owner，不推断归属 |
| WF-52 | Auditor 为 M001 的 PATH 提交 M002 构建的 HAP | 拒绝跨模块借用产物；GLOBAL visual 使用冻结 build_binding 的当前已接受构建 |
| WF-53 | score/semantic 使用无关图片，或 carried 没有当前截图回归 | Green 拒绝；重读原始 alignment 按 round/target/capture index 核对图片摘要 |
| WF-54 | Foundation 解析省略 producer、虚构依赖，或冻结后解析文件变化 | 冻结时按随包 catalog 重算；缺失门禁不显示 freeze ready；冻结引用变化拒绝继续派发 |
| WF-55 | 用旧 CR 审查冻结另一份计划，或 invalidate 后重用旧 impact | impact 绑定 from_freeze_id + to_plan_hash；消费/失效后转历史，当前计划须重新审查 |
| WF-56 | 资源目的地属于模块但超出 task.scope，或映射不属于该 task | 写入前拒绝，目标文件不变；保留失败 receipt，不增加其他模块阻塞 |
| WF-57 | 资源自报类型与源码不符、byte_copy 字节不同，或多个配置变体 | 核对源文件/条目/单位/nine-patch；以 sourceId+qualifier 区分合法变体，拒绝伪造精确映射 |
| WF-58 | source-only/capture-fixture 下业务 CASE 已 Green | 原 CASE 三态保持；GO 报告单列未验证视觉/在线 provider 的证据覆盖限制，无新增流程门禁 |
| WF-59 | 一个资源被多个消费者使用 | 逐消费者引用验收；缺项、路径不匹配或后续 hash 变化拒绝，不以 AttributeError 退出 |
| WF-60 | 裸附加资源 ID、不支持自动转换的真实源类型、night→base 路由 | 裸 ID 不填平闭包；未知类型能诚实记录 blocked/manual_exact；跨配置须冻结范围/条件证据 |
| WF-61 | Foundation 无匹配、知识提供上游控制概念 | external 返回受限候选和完整 hash 引用，probe 未执行；sdd_adaptation 映射现有 SPEC/任务/PATH 及三根目录 |
| WF-62 | loading→content，只有 content 可稳定截图，自动化设备缺失 | 瞬态保留行为测试，不强制截图；缺设备逐 automation/visual Yellow，保留 build Green，父汇总与 Auditor 正常收尾 |
| WF-63 | 装机/捕获/语义工具执行，或设备/模型无法使用 | 校验 assignment/当前构建/配置/设备锁及当前审计快照；证据受管留存，缺条件不伪 Green、不提交 Ledger 或重置预算 |
| WF-64 | alignment 改为新 HAP/代码，但仍用旧截图或仅标签 sidecar | adapter 与正式 Green 共用安装/捕获日志、逐屏截图树及当前基线校验；跨 run、伪造关联拒绝 |
| WF-65 | 首屏不变但替换冻结 Android 第二屏，或 GLOBAL 缺原始集合 | 校验完整冻结目标记录；GLOBAL 显式 visual_evidence，缺证据局部 Yellow，不猜测 UI 归属 |
| WF-66 | source-only UI 声明手势，或默认 Harmony 缺手势结构化证据 | automation 可冻结并传递完整动作；真实 proof 才 Green，缺 proof 保留断言并接受已执行 Yellow，Red 保留 |
| WF-67 | 仅覆盖 base、collector 源 hash 过期，或 UI/Resource 使用不同源版本 | 冻结和 verify_plan 按当前 UI 的 ID/qualifier/path/hash 核验；有证据范围排除不阻塞无关变体，排除证据变化拒绝 |
| WF-68 | 颜色来自 res/color-night 的 selector XML | collector 与 scan 都发现候选，按真实 selector 使用 compose_semantic_exact，不能冒充固定 token |
| WF-69 | 提高修复预算时仍有人工作业/工具/依赖阻塞 | recover 只解除预算限制，保留独立 blocker、phase/resume_phase；无独立 blocker 才恢复原修复/测试路由，兄弟模块不变 |
| WF-70 | adapter 退出成功但 skipped/xfail 为真 | 规范化保留限制与真实断言，Green 转 Yellow 并记录 incomplete-test-execution；正式门禁拒绝绕过，Red 不降级 |
| WF-71 | 新 Auditor/测试 assignment 重读同构建旧截图 | 最新 capture 必须匹配当前 assignment/fence；adapter 与正式门禁均校验，carried 历史轮次可保留旧授权 |
| WF-72 | 代码 R.id、两类 @array、Android 平台资源 | 节点 ID 不报缺资源文件；两类数组可发现/冻结/精确迁移；平台资源通过 SDK API/元数据/定义摘要，缺来源显式 blocked |
| WF-73 | global_paths 仅覆盖部分已登记 CASE | init 接受合法子集；未知 CASE 拒绝；global-plan 仍要求全量 requirement/case owner |
| WF-74 | 仅 GLOBAL 缺环境，之后提交 ready audit-testing | 新有效预检提示 audit-assign 并携带 owner/context；旧、blocked、篡改或已消费预检不触发，其他模块不重跑 |
| WF-75 | 已执行 Yellow 后 automation-unavailable/audit-unavailable | 保留同基线最近真实断言/回执为 last_execution；当前尝试未执行、质量仍 Yellow；重复缺测不产生递归历史 |
| WF-76 | semantic 仍有 issues 或不可比，却被标 ALIGNED | Green 必须逐项绑定原结果/原 finding 的有据 resolved/dismissed 裁决；原件/佐证变化、漏项、重复或无证据拒绝 |
| WF-77 | GO/父 MO/子 MO 行为闭包不完整或共享能力有多个 owner | register/decompose/plan/global-plan 按 scope、REQ/CASE、证据和归属拒绝；运行期无关兄弟证据不影响本模块，实际依赖仍核验 |
| WF-78 | 同一 Requirement 的错误/空态 Scenario 未映射或索引过期 | plan/freeze 从 SPEC 重算索引，要求逐 Scenario→TASK/PATH/ASSERT；缺场景/构建代替行为断言拒绝，static 明确缺实现记 Red |
| WF-79 | 单测退出 0，但零执行/全跳过/错选/缺损报告 | 当前 runner JUnit 实际 testcase 和冻结 required_test_ids 不满足时 Yellow，不能 Green；观察到失败为 Red，走既有修复 |
| WF-80 | 重用旧单测报告、路径越界、重复 test ID、篡改计数或回执基线 | attempt 范围/时间、hash、实际计数及 run/module/PATH/assignment/test_run/freeze/code 绑定校验；无有效证据不能通过 |
| WF-81 | 恢复 run 或更新来源 | 行为契约与设计门禁由 prepare 固定、不能关闭；Red/Fixer/回归、OpenSpec 投影与二次启动仍完整 |
| WF-82 | 长任务、双流大输出、取消/硬终止 | 退出前日志可见；原字节/时间/位置留存；异常不完整、超时有界，原终止门禁与独立任务不受观察器影响 |
| WF-83 | 按 Scenario/PATH/测试 ID 查询及历史复查 | 只读已提交证据，不刷新投影或拿业务锁；历史结果明确标注，分页/字节上限有效，损坏归档可定位 |
| WF-84 | watchdog 读取执行输出 | 绑定身份/本 run 路径；输出不冒充心跳；真实退出且输出不完整才提示，缺宿主接口仍 unknown |
| WF-85 | 实时观察、审计 trace 与业务验收 | live 明确未验收，不作为跨层结果；GLOBAL 审计独立查询；缺实现/零测试不能通过 |

## WF-44：整体代码治理前置

- 全 Green 仍需 audit-code-review；未审查/证据过期不能 audit-assign 或 audit-unavailable。
- CR-* 先于剩余 Red/Yellow 收集，不能伪造测试 Red；治理不能 verify 旧 Green 后直接关闭。
- 合法 owner 的一轮 Fixer → 完整 Testing → 受影响消费者回归 → Auditor 裁决；新增任务/边界走 CR。
- 变更后重新审查，失败保留根因待人工；无关 Green 与模块结果保留；自动化缺失不阻止代码审查。

## WF-45：埋点有则覆盖，无则继续

- 无 telemetry 索引的旧计划不新增全局门禁；新 N/A 模块正常冻结/编码/业务测试/DoD，无空事件用例或额外修复。
- 适用模块允许普通任务 N/A；存在事件须映射合法 TASK/业务 PATH/ASSERT，构建断言不能代替。
- 事件名称/参数/触发及禁止条件、真实接线与验收层级可追溯；截图不作为服务端接收证据。
- 某模块埋点证据过期只约束本模块/真实依赖，无关兄弟继续；观测缺口记录 Yellow，不伪装 N/A。
