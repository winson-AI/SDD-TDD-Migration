# 迁移流程图

按当前三层编排重新整理。先看总览，再按需要展开子 MO、Auditor 或二方库复用；SVG 可放大，PNG 便于分享。

Test-Runner 已拆为编译构建与自动化测试。仅自动化环境缺失时保留 Yellow/未执行，其他可执行任务继续，本轮可以带缺测清单收尾；这不等于功能验收通过。详细门禁见 [双环节协议](../skills/migration-protocol/references/build-automation.md)。

| 图 | 关注点 | SVG | PNG |
| --- | --- | --- | --- |
| 01 · 三层编排总览 | GO 分配模块 scope/context；父 MO 拆子模块；子 MO 拆 tasks；独立并行与全量收尾 | [总览](workflow.svg) | [总览](workflow.png) |
| 02 · 子 MO 执行与首轮修复 | SPEC/测试设计 → 冻结 → Coding → 构建 → 自动化；错误经 Fixer，缺自动化环境单独 Yellow 收尾 | [子 MO](module-execution.svg) | [子 MO](module-execution.png) |
| 03 · Auditor 跨模块处理 | 收集遗留、SPEC/路径与根因路由、Fixer/Testing、失败待人工、最终独立审计 | [Auditor](auditor-closure.svg) | [Auditor](auditor-closure.png) |
| 04 · 二方库语义与复用 | 来源评审 → 语义抽取 → 四类复用决策 → 冻结 → Coding → 真实依赖验证；版本变化后的恢复 | [二方库](reuse-dependencies.svg) | [二方库](reuse-dependencies.png) |
| 05 · Automation 外层闭环 | 输入分层、环境预检、逐 PATH 执行、三层结果、修复与审计；缺测旁路 | [自动化](automation-flow.svg) | [自动化](automation-flow.png) |
| 06 · Harmony 单 PATH 内核 | Planner / Executor / Verify、录制回放、媒体断言、观察落盘与三态汇总 | [内核](automation-engine.svg) | [内核](automation-engine.png) |

自动化输入输出的字段、JSON 示例、调用方法和当前实现边界见 [自动化测试说明](automation-input-output.md)。

## 阅读约定

- 总览以 project 的多个父模块举例；single-module 只保留选定根模块及其父 MO，子功能仍由独立子 MO 执行。
- 功能列表默认从测试用例汇总抽取；没有汇总则先理解存量源码、完整列出功能，再生成需求/测试草案。两种方式都要对照源码查漏，任何疑问立即人工介入；功能清单与逐模块归属通过 global-plan 门禁。
- GO 在目标已有能力与指定外部来源中提取语义目录，结合模块需求形成复用与缺口任务；父/子 MO 逐层细化，验证真实接线与行为等价。
- 先评审来源与接入可行性，再选择 reuse / adapt / reference / new，并将映射与 SPEC 一起冻结。声明来源不可用是阻塞，不能视作“已评审但无匹配”而直接新实现。
- 选中提供方或接入证据变化时，相关计划与旧测试证据失效；受影响消费者经影响分析、CR/重规划、重新冻结和正式复测恢复，无关模块继续。外部源码默认只读，无修改授权的问题走人工路由。
- GO 分配根模块范围和所需上下文，父 MO 在认领范围内继续分配子范围和上下文，子 MO 基于子范围拆 tasks。父子均保留全局代码、架构、知识的读取视野。
- 箭头表示经 Ledger 的交接或控制关系，不表示 Agent 私聊。宿主实际启动/恢复实例、绑定模块、加载 Used Skills；分配包不自行产生执行权限。
- 子 MO 独立运行。父 MO 持续看护范围、覆盖、复用与依赖，并等待全部孩子收尾；一个 Red/Yellow 不结束无关模块。
- 本轮收尾允许基于自身证据明确挂起，但不能将排队、写锁等待或 worker 退出视为已收尾。全部子 MO 收尾、父汇总有效、无在途 worker 与可推进动作后，GO 才统一启动 Auditor。
- 图 03 展开有遗留的问题审计。无遗留且全部 DoD 完成时只做独立证据审阅，不重跑测试；依赖图决定具体修复与验证顺序，不能把图中的角色列表理解为强制先后顺序。
- Green 不需新增人工会签；人工参与澄清冻结、跨模块/不确定边界、失败恢复与交付授权。SPEC 修改、依赖恢复或人工批准均不能直接将测试改成 Green。
- 上下文预检已进入 GO 发现/覆盖规划、父拆分、子 SPEC 冻结、Coding/Testing/Fixer 派发及 Auditor 分析/裁决/最终测试。执行者先只读核对并提交 `context-submit`，原节点验收后推进；缺项或过期阻止相关阶段，不消耗修复预算、不提前收尾。

## 依据与再生成

以 [三层作用域协议](../skills/migration-protocol/references/module-decomposition.md)、[状态机](../skills/migration-protocol/references/state-machine.md)、[上下文就绪协议](../skills/migration-protocol/references/context-readiness.md)、[二方库复用协议](../skills/migration-protocol/references/reuse-dependencies.md)、[本地运行契约](../skills/migration-protocol/references/local-runtime.md) 为准。

源文件为 [generate_workflows.py](generate_workflows.py)。在包目录执行：

```sh
python3 diagrams/generate_workflows.py
```

需要 Python 3 与 `rsvg-convert`；生成四个 SVG 及宽 1920px 的 PNG。修改布局后需重新查看 PNG，核对箭头端点、文字和业务分支。

图 05/06 单独生成，复用同一绘图组件：

```sh
python3 diagrams/generate_automation.py
```

Auditor 遍历所有模块以收集 Red/Yellow，但不会全量重跑测试。global_test_paths 可为空；范围与空清单报告遵守 [审计范围协议](../skills/migration-protocol/references/audit-scope.md)。
