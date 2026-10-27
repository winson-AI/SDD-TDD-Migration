# Test-Runner：编译构建、功能自动化与基线视觉对齐分段执行

## 总则

Coding 接受后先构建，同一派发内跑逻辑单测（命令全冻结，由 `ledger.py advance` 代跑），两者通过后另派 Test-Runner 做静态规格闭合审查（逐需求核对生产符号与假实现，见[静态规格闭合](testing.md#静态规格闭合)），然后自动化：PATH 的平台有声明的适配器或内置 Main 时同样由 advance 代跑，否则由 Test-Runner 执行。任务分批时游标先给已接受任务的构建与单测（不强制）；静态闭合待全部任务写完且需要本模块代码的切片已有代码，此前为 awaiting-assembly。构建命令相同的模块同时只一个在写；命令优先用户指定，否则搜索构建脚本并默认评估 Gradle assemble。构建/用例错误记三态与根因，修复由 Fixer。仅自动化环境不可启动时保留构建 Green，逐用例记 Yellow/未执行，经 automation-unavailable 进入 automation-deferred，独立任务与依赖当前构建产物的下游继续，不传播 Yellow、不强制人工恢复；全量收尾后 Auditor 保留缺测清单，本轮可 completed-with-unverified-tests，不称功能/fidelity 验证通过；不跳过构建、不吞已观察到的 Red。

## 1. 职责与全局规则

Test-Runner 一个角色承担构建验证、功能用例自动化和（存量可预览时）基线视觉对齐，顺序由 `test_validation.next_scope` 强制：build → automation → visual；visual 的路径绑定、修复与缺测规则见 [UI 保真控制道](ui-fidelity.md#视觉对齐--automation-第二层不是独立阶段)。可由不同实例执行，身份、assignment 与证据各自绑定；Test-Runner 只执行、定三态和报告，修复由 Diagnostician → MO → Fixer，Auditor 独立。

固定流程：

```text
GO 搜索/确认目标构建命令 → 子 SPEC 冻结 build + automation PATH，适用时加 visual PATH
Coding 接受 → Test-Runner building 预检 → 编译构建
  ├─ Red / 可修复 Yellow → 根因 → Fixer → 重新构建
  ├─ 已确认构建依赖/外围阻塞 → 原有记录/审计流程
  └─ Green → Test-Runner testing 预检
       ├─ 环境可用 → Main 执行 automation 用例路径 → 逐条三态
       │    └─ 功能 Green → 有 visual 时另派只读对齐 → 全部冻结路径 Green 才 DoD
       └─ 仅自动化环境不可启动 → Yellow / executed=false / automation-not-run
            → MO automation-unavailable → automation-deferred，本轮模块执行收尾
            → 并行任务、依赖当前可构建代码的下游继续 → 父 MO 汇总 → Auditor
```

**调度完成与功能验收通过分开**：automation-deferred 不是 completed/Green。它只表示代码已接受、当前构建通过、自动测试没有执行。真实用例失败、构建失败、业务契约/提供方缺失不适用此例外。

## 2. 构建命令的来源与固化

项目配置增加可选 `build`，按既有 init/update/prepare 保存并固化，下游通过 planning_context 读取；用户不用手工写 SPEC 或构建 PATH。

自动发现排除 `.sdd-migration`、`.sdd-runs`、`openspec` 及指向其内部脚本的文件链接，防止目标工程内的迁移记录被当作当前构建入口。候选选择不替代后续冻结和执行预检。

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

- 没有指定命令时 [discover_build.py](../../migration-test/scripts/discover_build.py) 只读搜索候选：项目根 wrapper 优先，其次唯一嵌套 wrapper，否则本机 Gradle；默认候选 `assemble`，避免顺带跑自动化测试的 `build/check`；GO/Test-Runner 阅读实际任务和模块/variant，不执行搜索到的脚本。
- 多个构建根或目标有歧义时由 Agent 结合模块 scope 选择并留依据，无法判断再问用户。缺 Gradle、SDK/JDK、必要脚本记构建环境 Yellow；不伪造命令、不换成 `echo success`。
- 每个 build PATH 的 `command` 固定绝对 argv、目标内 cwd、timeout_seconds、selection_ref（搜索候选、选中理由、目标/variant、工具版本与模块范围）；building 预检另给实际环境证据；源码生成前不构建。
- 共享构建目录/设备锁由宿主落实，锁等待不污染其他模块的测试质量；构建只产生授权输出，不授予 Test-Runner 改业务源码的权限。

## 3. 冻结路径与分阶段证据

构建/自动化拆分是必选门禁：每个执行叶子的 stage-plan.paths 必须同时包含 `kind=build` 和 `kind=automation`，ID 全局唯一。build 是技术门禁 PATH，关联现有模块 REQ/CASE/TASK，不计作业务测试用例通过。

覆盖门禁同时要求每个已分配 CASE 至少关联一个 automation PATH；不得只给某 CASE 关联 build PATH 来满足整体 CASE 映射。模块边界和 uv 执行方式见 [Harmony sandbox README](../../migration-test/runtime/harmony/README.md#1-测试覆盖与模块边界)。

MO 派发 test-runner 时明确 `test_scope=build|automation|visual`，顺序同上；每次接受新代码，旧构建失效，须重新 build。

- building 预检只检查冻结方案、代码、构建命令、构建环境和权限，不检查设备/UI/自动化账号。
- `execute_test.py` 对 build PATH 直接执行冻结命令，**不追加 query-file/result-file 参数**；宿主保存 stdout/stderr、退出码和 receipt，生成唯一构建断言（expected=0，actual=真实退出码）。编译错误 Red，环境/工具或未知原因 Yellow（127/124 默认 Yellow），均留根因与日志，由角色核实分类。
- 每次结果提交覆盖 assignment scope 下全部 PATH；build、automation、visual 分别提交/接受，Ledger 合并并保留每条路径结果。
- visual 用正式 `execute_test.py` adapter 回执；`compare-only` 的 score 不算正式通过。逐目标绑定、HAP 与手势要求见[UI 保真](ui-fidelity.md#视觉对齐--automation-第二层不是独立阶段)。
- [harmony_stage.py](../../migration-test/scripts/harmony_stage.py) 组装构建与 Harmony 自动化回执并按 assignment scope 校验覆盖；其他自动化框架用通用 tests stage 契约。

## 4. 自动化环境缺失：直接记 Yellow 并继续

Test-Runner 经 `context-submit` 提交 testing 报告，仅 `test-environment=blocked`，填写 missing/owner/next_action/evidence；其余检查就绪。MO 接受 `automation-unavailable`（payload.context_ref 指向报告）。控制器要求当前构建已通过、代码未漂移、没有活动 worker，且不能遮蔽当前基线已观察到的 Red。

接受后对尚未验证的 automation/visual PATH 记录 `quality=yellow-blocked`、`executed=false`、`reason_code=automation-not-run`、结构化根因、版本关联及旧结果的 retest_of；保留当前基线已有 Green。模块进入 `automation-deferred`，不耗 Fixer 轮次，不需要人工批准，不反复尝试启动不可用环境。

同一代码基线上此前真实执行过的，缺测行的 `last_execution` 保留最近一次已接受的真实执行（状态、断言、execution_receipt、test_run_id）；本次仍是 `executed=false/assertions=[]`。GO 报告分别输出 `executed`（曾执行）、`attempt_executed`（本次执行）、`last_execution` 与 `last_execution_stale`；历史观测不能代替本次复核。

已启动后才发现无法运行，先保存启动日志/原始回执，结束或 revoke 活动 assignment，再提交上述报告。已观察到真实断言失败时不能以环境缺失覆盖成"未执行"，"先断言失败、后环境中断"的 Yellow 保留失败断言与环境原因，继续原诊断/审计路径；缺失观测的 actual=null 不等于已观察到业务失败。

仅自动化缺测的上游可作为代码依赖继续编译/实现/验证，质量 Yellow 不向消费者传播，消费者自己缺环境则独立记录；上游代码或 SPEC 变更仍使相关下游失效。父 MO 可汇总 automation-deferred 子节点，不得因一个子模块缺环境提前结束其他 MO。

## 5. Auditor 与恢复

审计修复或复核期间再次缺自动化环境，MO 同样提交 automation-unavailable；该分支记录到批次 automation_deferred，其他分支继续。Auditor 裁决保留 unverified_findings，不能写入 resolved_findings；仅因缺测不进入 awaiting-human，批次可完成为 completed-with-unverified-tests。

最终独立自动化环境也不可用时，Auditor 提交 blocked audit-testing 报告并执行 **audit-unavailable**：门禁仍要求全量收尾、独立实例、无其他待处理缺陷/审计批次；Ledger 保存未执行路径清单与 Yellow 最终报告，global_next_step.reason=completed-with-unverified-tests，不得称独立审计通过。环境可用则 audit-assign/audit 只复核尚未验证的路径；清单为空只做独立 audit-review。

环境恢复时，新 testing ready 报告 → MO **automation-resume** → 新 assignment → Main 逐路径复测；不额外请求人工恢复批准。旧 Yellow 和缺测证据保留，新结果链接 retest_of。代码/构建已变化则先走正常重建，不直接恢复自动测试。所有完整路径真实 Green 后才完成 DoD；全局 Green 仍需最终独立审计。同一份代码最多恢复 `max_yellow_retries` 次（默认 2）；环境反复失效用尽后游标不再建议恢复，模块保留缺测 Yellow 收尾；计数按代码基线，代码变化后重新计数。

只有 GLOBAL 路径缺测、模块均已结束时，由原独立 Auditor 提交新的 `audit-testing` ready 报告。报告必须匹配当前主体/快照、通过引用校验，且未在上次 audit-unavailable 时被记录为已有预检。`global_next_step` 提示 `audit-assign`，payload 带该 context_ref 与 auditor instance；宿主按提示实际派发。旧 ready、blocked、过期或被修改的报告不会触发恢复，读取状态本身不启动进程、不增加审计预算。

## 6. 实现边界

脚本不自动安装 SDK、创建设备、发放账号或证明命令确实覆盖了目标模块；Agent/宿主必须审核范围、环境和真实日志。

若最终 Auditor 环境可用且对原缺测模块的 Yellow 自动化路径真实复测 Green（当前已通过构建证据保留），Ledger 将审计结果关联回模块并进入 dod，由 MO 完成管理性 DoD/父汇总；测试验收 owner 仍是 Auditor，不要求再跑同一轮测试或再次会签。原 Yellow 通过 retest_of/module_retest_of 保留追溯。

## 7. 宿主如何推进 build → unit → static → automation → visual

责任分工：Test-Runner 执行并取证，MO 接受结果和请求派发，Ledger 决定合法下一步，宿主真正启动进程/Agent；`next_steps` 返回动作不代表命令已执行，也不是 Test-Runner 私自串联第二阶段的授权。

| 节点 | Ledger 状态 / 游标 | 宿主及角色动作 |
| --- | --- | --- |
| Coding/Fixer 代码已接受 | `phase=testing`，`stale=true`，`build_baseline=null`；下一 scope 为 build | 实际 Test-Runner 提交 building 报告；MO assign build，宿主启动 |
| 构建进程已退出，但结果未接受 | 当前 assignment 仍未关闭；不能开启 automation | 保存 receipt，同一 assignment 继续 unit、static 到第一个非 Green（见[静态规格闭合](testing.md#静态规格闭合)），一次 submit / accept |
| build 非 Green 已接受 | 留在 testing；游标 diagnose 或 audit-defer | Diagnostician → MO diagnosis-accept → fixing 预检 → Fixer；依赖/环境/目标工程自身缺陷（target-baseline）或预算用完则留证待 Auditor，不等人不回 GO |
| Fixer 补丁已接受 | 新 code_baseline；旧结果 stale，旧构建失效 | 再次 build 派发（派发内 building 预检）；不得直接沿用旧 Green 或启动 automation |
| build、unit、static 全部 Green 已接受 | `build_baseline=code_baseline`；仍在 testing；下一 scope 为 automation | 派发 automation，Test-Runner 在派发内提交 testing 报告，核对设备/安装包/fixture/模型/工具 |
| automation 结果接受且完整 Green，存在 visual PATH | 仍在 testing；下一 scope 为 visual | MO 另派 visual assignment；Test-Runner 只读比较并留正式回执 |
| 全部适用的 build/automation/visual 路径有效 Green | `phase=dod` | MO 完成 DoD；父汇总，全量收尾后统一 Auditor |

切换 scope 时按当前游标重新提交该阶段报告，不沿用旧 assignment、scope 或 context_ref。

模块派发和实际执行均检查 build_ready；结果 submit/accept 再检查覆盖、版本和证据。构建 CLI 外层退出码 0 仅表示已写回执，读取 receipt/result 并等待接受，不能凭它转阶段。

### 本地一轮的预算单位

`local_fix_used` 是模块级计数，build、automation 与 visual 共用；每次补丁接受后都需完整正式回归，全部通过才将修复 memory 标为可复用。按总预算局部收敛，见[有限循环](state-machine.md#有限循环)。宿主不能重置计数。

Harmony Main 不隐式安装 App：装机证据来自 visual-install（[视觉执行](visual-execution.md#2-执行节点)）或宿主提供的已安装包与当前构建/代码基线的关联证据；旧安装包上的测试不算当前代码通过。

## 构建资产位置

冻结 build PATH 时审核构建输出位置，遵守[留存文件系统](storage-layout.md)：正式输出为 runs/build/<新 attempt>；执行器绑定临时目录与工具缓存，在该次 Gradle home 放 init.d 把各工程 buildDirectory 与项目缓存定向到 runner，脚本内的构建同样继承。自查用 `execute_test.py selfcheck --cwd <树> --output <新目录> -- <命令>`，同一定向，不留回执、不算结果。各次执行默认以宿主 `~/.gradle` 链接 wrapper 与依赖缓存（`SDD_GRADLE_CACHE_SEED` 改指或置空关闭）。build/unit 只跑 PATH 所验平台的任务，无 PATH 验原生目标时用 allTests 等汇总任务记欠项。APK、构建报告、测试脚本不留在目标源码旁；硬编码输出先调整冻结任务/构建配置，工程不支持则如实记录。安装步骤读本轮实际 APK 路径。

## 构建和自动化异常回执

可捕获的执行器中断与启动后的运行异常先停止本 attempt、限时回收并保存 execution.log、cleanup.json、receipt.json，再向宿主重新抛出（SIGTERM 转 SystemExit(143)、SIGINT 转 KeyboardInterrupt，不改宿主信号处理器）。回执 termination.executor_aborted=true 并保留异常类型与退出码（中断 130/143，运行异常 125），不能作为完成结果接受；Host 核验停止/隔离并留证后走 revoke/audit-revoke。用户取消不自动重启或派 Fixer；退出未确认时保留 temp；SIGKILL/断电等由 Host 据运行记录核验恢复。

执行超时后 Host executor 向本 attempt 的进程组发送 SIGKILL，输出回收另限 2 秒，不因脱离进程组的子进程持有 stdout/stderr 无限等待。回执 termination 记录信号结果、direct_process_exited、output_drained、descendants_status 和 host_stop_required；发出信号或管道 EOF 不代表外部子进程已停止。

回收超时、直接进程未确认退出或信号失败时保存已捕获日志、exit_code=124 与诊断回执，host_stop_required=true，attempt 与嵌套 Harmony temp 保留，cleanup.json 记 process-stop-unconfirmed；Host 核验/停止或隔离进程、保留回执与 stopped_worker_ref 后按 revoke（审计用 audit-revoke）恢复，该回执不能经 submit/accept 关闭 assignment，也不算普通自动化缺测；已有失败观测保留，不自动重授资源锁或删仍在用的临时目录，无关模块继续，确认后 Host 清理该 attempt，后续测试用新 attempt。正常回收的超时仍按下述三态提交。

Auditor 批次中的构建 Red/Yellow 也是验证失败：接受时记录 build-verification-failed、结果引用及编译/超时根因，关联分支待人工审核，独立分支继续。批次内禁止 audit-defer；构建 Green 只开放 Automation，不写入自动化通过证明。纯自动化环境缺失仍走原缺测出口，不能用于跳过失败构建。

Automation 执行器在进程退出后保留原始 result.json 与已落盘 observations.json（receipt.partial_observations_ref）；汇总与验收共用 host_completion_version=1 的确定性判定：失败报告随后超时/异常仍保留失败断言与根因，不改写为"未执行"；报告未完成但有有效部分观测时逐冻结 ASSERT 恢复有证据的观测，整体 Yellow，混合 pass/fail 保留失败与 flaky；JSON 截断或格式错误保留原件，生成带解析原因的 Yellow；没有有效观测才 executed=false，submit/accept 后关闭 assignment。引用 hash、身份、冻结 query 或媒体证据不匹配仍拒绝；原始报告、观测和 hash 不被重写。
