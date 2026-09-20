# Test-Runner：编译构建与自动化测试分开执行

## 1. 职责与全局规则

Test-Runner 同一角色承担两个执行环节：**构建验证**和**自动化用例验证**。可由不同实例执行，但身份、assignment 和证据各自绑定。Test-Runner 负责执行、三态和问题报告；源码/构建配置修复仍由 Diagnostician → MO → Fixer 完成，不能自己兼任 Fixer。Auditor 保持独立。

固定流程：

```text
GO 搜索/确认目标构建命令 → 子 SPEC 冻结 build + automation PATH
Coding 接受 → Test-Runner building 预检 → 编译构建
  ├─ Red / 可修复 Yellow → 根因 → 一轮 Fixer → 重新构建
  ├─ 已确认构建依赖/外围阻塞 → 原有记录/审计流程
  └─ Green → Test-Runner testing 预检
       ├─ 环境可用 → Main 执行全部用例路径 → 逐条三态 → 修复/DoD
       └─ 仅自动化环境不可启动 → Yellow / executed=false / automation-not-run
            → MO automation-unavailable → automation-deferred，本轮模块执行收尾
            → 并行任务、依赖当前可构建代码的下游继续 → 父 MO 汇总 → Auditor
```

**调度完成与功能验收通过分开**：automation-deferred 不是 completed/Green。它只表示代码已接受、当前构建通过、自动测试没有执行。本轮可以带缺测记录结束；不能宣称功能已验证、fidelity 已通过或全局 Green。真实用例失败、构建失败、业务契约/提供方缺失不适用此例外。

## 2. 构建命令的来源与固化

项目配置增加可选 `build`，按既有 init/update/prepare 保存并固化，下游通过 planning_context 读取；用户不用手工写 SPEC 或构建 PATH。

```json
{
  "build": {
    "argv": ["/bin/sh", "/work/target/gradlew", ":feature:assembleDebug"],
    "cwd": "/work/target",
    "timeout_seconds": 900,
    "environment_ref": "/work/context/build-environment.md"
  }
}
```

- 用户明确命令优先；没有指定时，GO/Test-Runner 在整个目标项目搜索 Gradle wrapper、Gradle 配置及构建脚本，阅读实际任务和模块/variant，不执行搜索到的所有脚本。
- [discover_build.py](../../migration-test/scripts/discover_build.py) 提供只读候选搜索：项目根 wrapper 优先，其次唯一嵌套 wrapper，否则本机 Gradle。默认候选为 `assemble`；避免使用会顺带运行自动化测试的 `build/check`，确保设备/自动化环境缺失不会使编译阶段失败。
- 多个构建根或不同目标有歧义时由 Agent 结合模块 scope 选择并留依据，无法判断再询问用户。缺少 Gradle、SDK/JDK、必要脚本则记录构建环境 Yellow；不伪造命令、不替换为 `echo success`。
- 历史 `quality_gates.build_argv` 应由宿主转换为 `build.argv`；不再只把构建命令当未执行的说明字段。
- 每个 build PATH 的 `command` 固定绝对 argv、目标内 cwd、timeout_seconds、selection_ref。selection_ref 记录搜索候选、选中理由、目标/variant、必要工具版本及模块范围。building 预检另提供实际环境证据；源码生成前不执行构建。
- 共享构建目录/设备锁由宿主落实，锁等待不能污染其他模块的测试质量。构建只产生授权输出，不授予 Test-Runner 修改业务源码的权限。

## 3. 冻结路径与分阶段证据

新运行要求 `split_testing_required=true`；每个执行叶子的 stage-plan.paths 必须同时包含 `kind=build` 和 `kind=automation`，ID 全局唯一。build 是技术门禁 PATH，关联现有模块 REQ/CASE/TASK，不计作业务测试用例通过。

覆盖门禁同时要求每个已分配 CASE 至少关联一个 automation PATH；不得只给某 CASE 关联 build PATH 来满足整体 CASE 映射。模块边界和 uv 执行方式见 [Harmony sandbox README](../../migration-test/runtime/harmony/README.md)。

MO 派发同一 test-runner 角色时明确 `test_scope=build|automation`。控制器只允许先 build，当前 build 全绿后才 automation；每次 Coding/Fixer 接受新代码，旧构建失效，必须重新 build。

- building 预检只检查冻结方案、代码、构建命令、构建环境和权限，不检查设备/UI/自动化账号。
- `execute_test.py` 对 build PATH 直接执行冻结命令，**不追加 query-file/result-file 参数**；宿主保存 stdout/stderr、退出码和 receipt，并生成唯一构建断言（expected=0，actual=真实退出码）。编译错误按 Red、环境/工具或未知原因按 Yellow，均保留根因及日志，由角色核实分类；127/124 默认 Yellow。
- build 结果提交覆盖全部 build PATH；automation 结果提交覆盖全部 automation PATH。Ledger 合并两部分，保留构建状态及每条用例结果；DoD 必须全部冻结路径有效 Green。
- [harmony_stage.py](../../migration-test/scripts/harmony_stage.py) 可组装构建回执及 Harmony 自动化回执，按 assignment scope 校验覆盖；其他自动化框架继续使用通用 tests stage 契约。
- 首轮修复和后续审计修复沿既有预算执行。Fixer 自测不是正式复测；修复 memory 只有完整验证后才能 reusable，缺自动化验证时标 unverified。

## 4. 自动化环境缺失：直接记 Yellow 并继续

Test-Runner 经 `context-submit` 提交 testing 报告，仅 `test-environment=blocked`，填写 missing/owner/next_action/evidence；其余检查就绪。MO 接受 `automation-unavailable`（payload.context_ref 指向报告）。控制器要求当前构建已通过、代码未漂移、没有活动 worker，且不能遮蔽当前基线已观察到的 Red。

接受后逐 automation PATH 记录 `quality=yellow-blocked`、`executed=false`、`reason_code=automation-not-run`、结构化根因、版本关联及旧结果的 retest_of；保留 build Green。模块进入 `automation-deferred`，不耗 Fixer 轮次，不需要人工批准，不反复尝试启动不可用环境。游标会提示该操作，不停留在无动作的 blocked 预检。

若已启动后才发现无法运行，先保存启动日志/原始回执，结束或 revoke 活动 assignment，再提交上述报告，引用已有失败证据。已经观察到真实断言失败时，不能以环境缺失覆盖成“未执行”。

下游仍需真实代码和依赖接口可用。仅自动化缺测的上游可作为代码依赖继续编译/实现/验证，质量 Yellow 不向消费者传播；消费者自己缺环境则独立记录。上游代码或 SPEC 变更仍使相关下游失效，不能利用缺测绕过版本/边界校验。

父 MO 可汇总 automation-deferred 子节点。全部叶子逐个结束且父汇总有效后才统一启动 Auditor；仍不得因一个子模块缺环境提前结束其他 MO。

## 5. Auditor 与恢复

纯自动化环境缺测不进入 Fixer 缺陷队列，最终 Auditor 仍读取全部模块结果和缺测 PATH。实际 Red/其他 Yellow 按原 audit-collect 闭环处理，不能被环境例外吞掉。

审计修复或复核期间再次缺自动化环境，MO 同样提交 automation-unavailable；该分支记录到批次 automation_deferred，其他分支继续。Auditor 裁决保留 unverified_findings，不能写入 resolved_findings；仅因缺测不进入 awaiting-human，批次可完成为 completed-with-unverified-tests。

最终独立自动化环境也不可用时，Auditor 提交当前 blocked audit-testing 报告，并执行 **audit-unavailable**。门禁仍要求全量收尾、独立实例、无其他待处理缺陷/审计批次。Ledger 保存未执行路径清单与 Yellow 最终报告，global_next_step.reason=completed-with-unverified-tests，停止空转；已有模块构建证据保留，但不得称独立审计通过。环境可用则 audit-assign/audit 仅复核尚未验证的路径，保留有效构建 Green；清单为空只做独立 audit-review。

环境恢复时，新 testing ready 报告 → MO **automation-resume** → 新 assignment → Main 逐路径复测；不额外请求人工恢复批准。旧 Yellow 和缺测证据保留，新结果链接 retest_of。代码/构建已变化则先走正常重建，不直接恢复自动测试。所有完整路径真实 Green 后才完成 DoD；全局 Green 仍需最终独立审计。

## 6. 实现边界

新 init 默认启用拆分，prepare 强制启用；历史没有该字段的 run、显式低层 split_testing_required=false 保留旧契约，不能据此宣称完成新流程。脚本不自动安装 SDK、创建设备、发放账号或证明命令确实覆盖了目标模块；Agent/宿主必须审核范围、环境和真实日志。构建成功只证明该命令通过，不等于业务自动化或复用保真通过。

若最终 Auditor 环境可用且对原缺测模块的 Yellow 自动化路径真实复测 Green（当前已通过构建证据保留），Ledger 将审计结果关联回模块并进入 dod，由 MO 完成管理性 DoD/父汇总；测试验收 owner 仍是 Auditor，不要求再跑同一轮测试或再次会签。原 Yellow 通过 retest_of/module_retest_of 保留追溯。

## 7. 宿主如何从 build 推进到 automation

责任分工：Test-Runner 执行并取证；MO 接受结果和请求派发；Ledger 决定合法下一步；宿主真正启动进程/Agent。`next_steps` 返回动作不代表命令已经执行，也不是 Test-Runner 私自串联第二阶段的授权。

| 节点 | Ledger 状态 / 游标 | 宿主及角色动作 |
| --- | --- | --- |
| Coding/Fixer 代码已接受 | `phase=testing`，`stale=true`，`build_baseline=null`；下一 scope 为 build | 实际 Test-Runner 提交 building 报告；MO assign build，宿主启动 |
| 构建进程已退出，但结果未接受 | 当前 assignment 仍未关闭；不能开启 automation | 保存 receipt，汇总全部 build PATH，submit；MO accept |
| build 非 Green 已接受 | 留在 testing；游标 diagnose 或 audit-defer | Diagnostician → MO diagnosis-accept → fixing 预检 → Fixer；依赖/外围或已用完本地一轮则留证待 Auditor |
| Fixer 补丁已接受 | 新 code_baseline；旧结果 stale，旧构建失效 | 再次 building 预检及 build assignment；不得直接沿用旧 Green 或启动 automation |
| 当前 build 全部 Green 已接受 | `build_baseline=code_baseline`；仍在 testing；下一 scope 为 automation | 提交单独 testing 报告，核对设备/安装包/fixture/模型/工具；MO assign automation |
| automation 结果接受且完整 Green | `phase=dod`；修复 memory 有完整回归后才 verified/reusable | MO 完成 DoD；父汇总，全量收尾后统一 Auditor |
| 仅自动化环境缺失 | `automation-unavailable → automation-deferred`，逐 PATH Yellow/未执行 | 保存缺测证据，其他任务继续；环境恢复后再预检和正式复测 |

宿主每次事件 ACK 后重新查询状态，不缓存旧 assignment、scope 或 context_ref。若 `context_gate` 尚未 ready，先由实际执行实例只读预检并 context-submit；派发时携带该阶段的当前报告。`building` 报告不能授权 `automation`，即使由同一个 Test-Runner 实例完成，也要重新派发并绑定独立 assignment。

构建使用 `execute_test.py` 直接运行冻结 argv；automation 使用同一宿主包装器传递完整 query 到 Main。模块派发和实际执行均检查 build_ready；结果 submit/accept 再检查覆盖、版本和证据。构建 CLI 外层退出码 0 仅表示已写回执，应读取 receipt/result 并等待接受，不能凭这一个退出码转阶段。

### 本地一轮的预算单位

`local_fix_used` 是模块级计数，build 与 automation 共用；不是每种失败或每个阶段各有一轮。构建已使用 Fixer 后，必须允许重新构建和正式 automation 完成这一轮的验证；若其中仍有问题，再交 Auditor。只有完整正式回归通过才允许将该修复 memory 标为可复用。增加轮次或改成两个独立预算须显式修改策略，不能由宿主自行重置计数。

### 构建产物与设备安装

构建 Green 只证明所选命令通过。当前没有自动安装/部署步骤，Harmony adapter 也不安装 App；宿主在 testing 预检里提供已安装包与当前构建/代码基线的关联证据及 fixture。uv sandbox 只准备 Python 执行环境，不替代部署。安装/设备等仅自动化环境条件缺失时沿缺测分流；不得把旧安装包上的测试当作当前代码的通过证据。
