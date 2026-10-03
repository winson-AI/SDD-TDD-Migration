---
description: /sdd-audit <run-id> — 整体代码审查、代码治理与独立遗留复核
---

# /sdd-audit

## 1. 用法
`/sdd-audit <run-id>`

## 2. 编排步骤
1. 按[命令通用约定](../skills/migration-protocol/references/host-integration.md#命令通用约定)读取入口、解析参数并检查现有工件。
2. 前置门控：完整 registry 中所有 MO 本轮独立完成或基于自身证据明确挂起，无活动 worker、无可推进动作；手工调用本命令也不得跳过等待，不得为审计强制结束其他 MO。模块 registry 和整体用例完整；实例与实现/修复/脚本作者分离；可冻结候选版本；未生成的代码不能测试，只报告 Yellow。
3. 按 `status` 的 global_next_step 派发对应角色。先按 [代码治理协议](../skills/migration-protocol/references/audit-code-review.md#顺序与职责) 执行 audit-code-review，遍历全部模块的代码改动、冗余、二方库和公共能力；治理发现先委派修正及受影响回归并刷新审查。随后收集剩余 Red/Yellow 遗留；读取对应 SPEC/CASE/PATH，分析根因并安排复核、必要的一轮 Fixer 与修复后 Testing。仍失败输出根因待人工；无关有效 Green 不重跑，不追加全项目全量测试。

整体代码审查必须提交 [本次代码修改清单](../template/audit-change-inventory.md)，由 audit-code-review.json.change_inventory_ref 绑定同版工件；清单列功能点、逐文件修改/路径、影响范围、CASE/PATH/测试脚本及结果证据。GO 收尾展示该链接，修复后刷新版本；不能只返回审查结论而省略清单。

## 3. 调用契约
目标角色：[Auditor](../Agents/auditor.md)。宿主用实际可用的任务工具启动，只传 package_root、run_root、module_id 与阅读卡路径；Ledger 按协议串行服务。定义文件不会自动安装或注册不存在的工具。

## 4. 对应规格
[审计范围](../skills/migration-protocol/references/audit-scope.md#总则)、[Auditor 与全局完成](../skills/migration-protocol/references/state-machine.md#auditor-与全局完成)。

## 上下文就绪门禁

全部 MO 收尾后，Auditor 的 audit-analysis、audit-verdict 预检随 audit-plan、audit-verdict 提交；audit-assign 有待测路径时先 context-submit audit-testing，空清单时为 audit-verdict；Fixer/Testing 仍独立预检。预检不替代独立复测与裁决。详见 [阶段协议](../skills/migration-protocol/references/context-readiness.md#2-精确插入节点)。

global_test_paths 可为空，不是 Auditor 触发条件。完整规则与恢复方式见 [审计范围协议](../skills/migration-protocol/references/audit-scope.md#总则)。

## 本地实现接入

Global audit-assign → 对 assignment.path_ids 执行 Auditor execute_test --module GLOBAL → audit；path_ids=[] 时仅提交独立 audit-review。

本地审计失败后的下一步为 audit-route / repair-accept，不能立即循环 audit-assign。模块修复复测完成后才开启下一轮，报告需关联上一轮非 Green 的 test_run_id。

当前入口必须等全部模块本轮结束/明确挂起，且无活动或可推进工作，才先 audit-code-review 及治理闭环，再统一扫描所有并行遗留：audit-collect → Auditor audit-plan → Global audit-route-batch → 负责模块 MO audit-work → Fixer → Test-Runner → 原发现模块 audit-retest → audit-verdict。按 finding 与依赖顺序执行，失败关联分支待人工，独立分支继续；汇总后须批准 audit-release 才能进入常规恢复，不再循环 problem-assign。问题闭环完成后做 audit-assign/audit 收尾审阅；仅剩未验证路径才执行测试，绝不再次执行所有用例。

纯自动化环境缺测不作为必须修复的代码缺陷，也不强制进入人工审批。等待全量收尾后汇总缺测 PATH；最终环境仍不可用，独立预检后 audit-unavailable 留 Yellow 报告结束本轮；不能宣称 Green。见 [双环节协议](../skills/migration-protocol/references/build-automation.md#5-auditor-与恢复)。

审计全量阅读前使用 `verify_openspec.py --root <run> --scope projection`；GO 交付收尾报告前改用 `--scope final`，要求正式报告已 completed 或 completed-with-unverified-tests。失败按返回范围与恢复动作处理，不从投影错误推断整轮从未执行。核验通过不证明真实派发或全部功能 Green；Yellow 缺测须继续披露。见 [核验范围](sdd-verify.md)。
