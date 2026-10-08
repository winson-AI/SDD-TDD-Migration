# 迁移流程图

图集与当前控制器及角色契约一致：GO/父 MO 切 scope/全量 CASE，子 MO 拆 TASK，SPEC 明确后冻结执行；执行反馈按实现错误、规划缺口、范围不足分流。同一 Run 仅执行当前冻结 SPEC，规划调整保留 history。先看总览，再展开模块执行、统一 Auditor、复用或自动化；SVG 入库，可放大，PNG 仅在本地生成。

Test-Runner 按顺序执行：build → unit → static（同一派发）→ 功能自动化 → 基线视觉对齐（存量可预览时；逐节点对齐，不对齐即 Red + 节点级根因走既有诊断/修复）。存量基线在冻结前判定并前移为 SPEC/coding 的输入。仅自动化环境缺失时保留 Yellow/未执行，其他可执行任务继续，本轮可以带缺测清单收尾；这不等于功能验收通过。详细门禁见 [构建与自动化协议](../skills/migration-protocol/references/build-automation.md)。

| 图 | 关注点 | SVG |
| --- | --- | --- |
| 01 · 三层编排总览 | GO/父 MO 切 scope/全量 CASE；原子能力作叶子；子 MO 拆 TASK；并行执行与统一宿主审计 | [总览](workflow.svg) |
| 02 · 子 MO 执行与反馈调整 | TASK/四维 → SPEC 冻结 → Implementer/Testing；Fixer/CR/上溯三分流；独立性证明与默认全模块重验 | [子 MO](module-execution.svg) |
| 03 · 统一 Auditor 宿主审计 | 全宿主目标/代码治理、遗留路由、影响模块完整回归、独立 Test-Runner 与 Auditor 裁决 | [Auditor](auditor-closure.svg) |
| 04 · 二方库语义与复用 | 来源评审 → 语义抽取 → 四类复用决策 → 冻结 → Coding → 真实依赖验证；提供方证据变化后的恢复 | [二方库](reuse-dependencies.svg) |
| 05 · Automation 外层闭环 | 冻结用例、派发后预检、逐 PATH 证据、三类反馈及成功/复用统计；缺测旁路 | [自动化](automation-flow.svg) |
| 06 · Android/Harmony 单 PATH 内核 | Planner / Executor / Verify、录制回放、媒体断言、观察落盘与三态汇总 | [内核](automation-engine.svg) |

自动化输入输出的字段、JSON 示例、调用方法和当前实现边界见 [自动化测试说明](automation-input-output.md)。

## 阅读约定

- 总览以 project 的多个父模块举例；single-module 只保留选定根模块及其父 MO，原子能力可直接作叶子，其余子功能由独立子 MO 执行。
- 功能列表默认从测试用例汇总抽取；没有汇总则先理解存量源码、完整列出功能，再生成需求/测试草案。两种方式都要对照源码查漏，任何疑问立即人工介入；功能清单与逐模块归属通过 global-plan 门禁。
- GO 在目标已有能力与指定外部来源中提取语义目录，结合模块需求形成复用与缺口任务；父/子 MO 逐层细化，验证真实接线与行为等价。
- 先评审来源与接入可行性，再选择 reuse / adapt / reference / new，并将映射与 SPEC 一起冻结。声明来源不可用是阻塞，不能视作“已评审但无匹配”而直接新实现。
- 选中提供方或接入证据变化时，相关计划与旧测试证据失效；受影响消费者经影响分析、CR/重规划、重新冻结和正式复测恢复，无关模块继续。外部源码默认只读，无修改授权的问题走人工路由。
- GO 分配根模块范围和所需上下文，父 MO 在认领范围内继续分配子范围和上下文，子 MO 基于子范围拆 tasks。上游全量 CASE 在冻结前按 scope 分配，SPEC 明确即可执行；独立 design 按需。automation 发现规划遗漏/fidelity 规划不足时局部更新 SPEC、再冻结并更新已有代码及正式复测。父子均保留全局代码、架构、知识的读取视野。
- 非 Green 在派修复前按现有诊断分流：实现错误 → Fixer；scope 内规划/功能/依赖契约缺口 → CR → Spec-Designer 修订 → MO 重冻 → Implementer 更新代码；超 scope → 父 MO/GO 修正分配，再 top-down 更新。已有提供方暂不可用沿等待/恢复，不混作契约缺失。
- CR 默认全模块重验；可选 MO TASK 独立性证明通过才保留未影响 TASK/Green。新代码始终重跑 build/unit/static，automation/visual 重跑受影响及非 Green 路径。保留成功证据记录 validation_reuse，原回执不变、单列统计，不计作本次新执行；独立性证明不免除统一审计。
- 箭头表示经 Ledger 的交接或控制关系，不表示 Agent 私聊。宿主实际启动/恢复实例、绑定模块、加载 Used Skills；分配包不自行产生执行权限。
- 子 MO 独立运行。父 MO 持续看护范围、覆盖、复用与依赖，并等待全部孩子收尾；一个 Red/Yellow 不结束无关模块。
- 本轮收尾允许基于自身证据明确挂起，但不能将排队、写锁等待或 worker 退出视为已收尾。全部子 MO 收尾、父汇总有效、无在途 worker 与可推进动作后，GO 才统一启动 Auditor。
- 图 03 是统一宿主审计：全部模块（含 Green）先做代码治理；实际复测按遗留/影响范围选择，清单为空只做独立证据审阅，不启动测试；依赖图决定具体修复与验证顺序，不能把图中的角色列表理解为强制先后顺序。
- 清晰且可执行的规划由 MO 审核冻结，独立 design 按需；Green 不需新增人工会签。真实未决或需求/验收/授权变化、适用的人工恢复与交付授权才交 Human。SPEC 修改、依赖恢复或人工批准均不能直接将测试改成 Green。
- 上下文预检已进入 GO 发现/覆盖规划、父拆分、子 SPEC 冻结、Coding/Testing/Fixer 派发及 Auditor 分析/裁决/最终测试。规划与审计者的报告由原节点验收；worker 接到派发后提交 `context-submit`，ready 报告授权开工、blocked 报告退回派发；缺项或过期阻止相关阶段，不消耗修复预算、不提前收尾。

## 依据与再生成

以 [三层作用域协议](../skills/migration-protocol/references/module-decomposition.md)、[状态机](../skills/migration-protocol/references/state-machine.md)、[上下文就绪协议](../skills/migration-protocol/references/context-readiness.md)、[二方库复用协议](../skills/migration-protocol/references/reuse-dependencies.md)、[本地运行契约](../skills/migration-protocol/references/local-runtime.md) 为准。

源文件为 [generate_workflows.py](generate_workflows.py)。在包目录执行：

```sh
python3 diagrams/generate_workflows.py
```

需要 Python 3 与 `rsvg-convert`；生成四个 SVG，并在本地渲染宽 1920px 的 PNG（不入库）。修改布局后查看 PNG，核对箭头端点、文字和业务分支。

图 05/06 单独生成，复用同一绘图组件：

```sh
python3 diagrams/generate_automation.py
```

Auditor 遍历所有模块以收集 Red/Yellow，但不会全量重跑测试。global_paths 可为空；范围与空清单报告遵守 [审计范围协议](../skills/migration-protocol/references/audit-scope.md)。
