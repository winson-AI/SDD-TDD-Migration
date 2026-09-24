# 宿主接入契约:如何真实走完控制流

本文件回答一个问题:**怎样才算"宿主真实执行了本控制流",而不是手写文件模拟。** 它把散落在各 reference 里的"宿主负责……"整合成逐阶段、可执行、可自证的清单。

前提认知:进入 Ledger 后阶段顺序 = 事件顺序 = hash 链,无法跳步(见 [状态机](state-machine.md));所以"真实走控制流"等价于两条——(1) **每一步都由 `ledger.py`/`project_context.py` 提交真实事件**,不是手写 `global.json`/`module-registry.json`/openspec;(2) **每个角色由宿主真实派发的 Agent 执行真实工作**(写码、跑测试),不是编排器自述完成。缺任一条,[verify_openspec.py](../../migration-ledger/scripts/verify_openspec.py) 会判 `verified=false`。

## 1. 宿主必须提供、控制器不代劳的三件事

1. **身份认证与 host-context 注入**:每次 `apply`/`init` 传入认证过的 `{"role":..,"instance_id":..}`;绝不能让请求体自报 role 获得权限,也不能让 worker 自选 host-context。
2. **真实派发 Agent**:控制器只记录 dispatch 请求并在 `status.next_steps` 给出游标;宿主必须用自己的 task/spawn 工具,按 [Agents/*.md](../../../Agents/) 定义启动隔离实例,并把结果经 Ledger 回传。控制器不 spawn、不嵌套 slash command。
3. **真实工作落地**:Implementer/Fixer 真写 `target_root` 源码;Test-Runner 经 [execute_test.py](../../migration-ledger/scripts/execute_test.py) 调项目真实构建/测试命令;Auditor 独立实例真实重跑。`code_files`/`checks_passed`/断言都由宿主真实产生,不能自填冒充。

这三件事无法从控制器内部强制(CLI 非安全边界);它们是本契约要求宿主自证的核心。

## 2. 逐阶段接入清单

每行:命令 → 必须提交的 Ledger op → 宿主必须做的真实工作 → 如何自证。所有 op 语义见 [本地运行指南](local-runtime.md) 操作矩阵。

| 命令 | 必须提交的 Ledger op(顺序) | 宿主真实工作 | 自证 |
| --- | --- | --- | --- |
| `/sdd-init` | `project_context.py prepare` → `ledger.py init`(payload 带 `project_context_ref`)→ `register`(拓扑序)→ `global-plan` | 认证 host;GO 生成功能清单/切片/覆盖;真实规范/架构/用例引用 | `status.openspec_binding.location==top-level`;`events.jsonl` 逐条增长;顶层 `openspec/runs/<run_id>/workflow.md` 出现 |
| `/sdd-plan` | (树形先 `decompose`→`decompose-accept`)→ `plan`(Spec-Designer)→ `freeze`(MO,绑定真实 `decision_id` 或 within-envelope) | 派发 Spec-Designer 真实产出六件套;人工澄清冻结决定 | `changes/<run-id>-<mid>/` 六件套 + `manifest.json` 由投影生成;freeze 事件绑定真实 `human_source_ref` |
| `/sdd-run`、`/sdd-module` | `assign`/`submit`/`accept`(implementer)→ `assign`/`submit`/`accept`(test-runner:先 build 后 automation)→ 需要则 `diagnose`/`diagnosis-accept`/`assign(fixer)` → `complete`;父节点 `module-summary` | 派发各角色隔离实例;真写 target 代码;execute_test 跑真实命令;真实 diff/DoD 审查 | 每 assignment 有 submit+accept;`code_baseline` 与磁盘一致(否则 `observed_invalidations` 报警);`complete` 前全 PATH Green |
| `/sdd-audit` | `audit-code-review` → `audit-collect` → `audit-plan` → `audit-route-batch` → `audit-work`/`audit-retest` → `audit-verdict`(→`audit-release`) | **独立** Auditor 实例(≠ 任何 implementer/fixer/test 作者)真实重跑;Fixer 按路由修复 | `authors` 独立性校验通过;audit 报告绑定当前 snapshot;`audit-reports/<batch>.md` 生成 |
| `/sdd-archive` | 宿主 OpenSpec CLI 同步/归档(无 Ledger `archive` op) | 人工交付授权;代码合并另行授权 | `verify_openspec` 通过 + 最终 audit Green;归档不等于合并 |
| `/sdd-status`、`/sdd-verify` | 只读,不提交事件 | —— | `/sdd-verify` 全程可用,推进前后都应 `verified=true` |

## 3. 接入自检(部署一次,证明编排器真接了 Ledger)

在一次性 throwaway workspace 上执行,确认产生的是**真实事件**而非手写文件:

```sh
# 1. 最小管道:确认控制器被真实调用、投影落顶层
python3 <pkg>/skills/migration-ledger/scripts/project_context.py prepare --root <ws>/.sdd-migration --request <req.json> --host-context <host.json>
python3 <pkg>/skills/migration-ledger/scripts/ledger.py init   --root <ws>/.sdd-runs/<run> --request <init.json> --host-context <host.json>
python3 <pkg>/skills/migration-ledger/scripts/ledger.py status  --root <ws>/.sdd-runs/<run>   # 断言 openspec_binding.location==top-level
python3 <pkg>/skills/migration-ledger/scripts/verify_openspec.py --root <ws>/.sdd-runs/<run>  # 断言 verified=true
```

- **管道自证**:上面四步后,`ledger/events.jsonl` 必须存在且逐条增长;若你的编排器"跑完"却没有 events.jsonl,或只有 `module-registry.json`/散文报告,就是**没接 Ledger**,必须修接线。
- **派发自证**:让编排器真实执行一次 `/sdd-plan <run> <mid>`,检查新出现的 `plan` 事件 `actor` 是被派发的 spec-designer 实例、`plan_ref` 指向该 Agent 产出的工件——而不是编排器自己写的。同理 implement 阶段检查 `code_files` 确由 Implementer 写入 `target_root`。
- **黄金参照**:[simulate_storage.py](../../migration-ledger/tests/simulate_storage.py) 是 prepare→init→register→plan→freeze→implement→test→audit 的**完整真实调用序列**,可作为接线对照与冒烟脚本骨架(它调真实脚本,不手写状态)。

## 4. 判定与红线

- 每个推进命令(`/sdd-plan`、`/sdd-run`、`/sdd-module`)与收尾命令(`/sdd-audit`、`/sdd-archive`)前置运行 `/sdd-verify`;`verified=false` 一律拒绝推进,回到 prepare→init→apply。
- `status.openspec_binding.location==in-run-fallback` 表示未绑定预备布局,OpenSpec 落在 run 内——按未接入处理。
- 控制器无法拦截"喂给 Ledger 的假证据"(stub 代码、假适配器返回 Green、空过 checks_passed);对冲手段是**独立 Auditor 真实重跑 + 宿主 git diff 审查**,不是再加控制器代码。
- `observed_invalidations` 非空说明目标代码被 out-of-band 修改,须 revoke→invalidate 重走,不得无视继续。

完整存储不变量与门禁细节见 [留存布局](storage-layout.md#openspec-投影完整性收尾门禁);操作矩阵见 [本地运行指南](local-runtime.md);阶段守卫见 [状态机](state-machine.md)。
