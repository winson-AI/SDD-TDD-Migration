# 迁移留存文件系统

## 总则

所有角色遵守本协议。资产固定在 workspace_root 下并列的 .sdd-migration、.sdd-runs、openspec；读 prepare 返回的 run_root/storage_layout 与 status.openspec_hub，不按 cwd 猜目录，不在目标仓另建 SPEC。生成工件放当前 run staging，Harmony 辅助产物放 runs/harmony/sandbox，正式自动化放 runs/harmony/automation，构建放 runs/build；临时目录归当前 runner，结束清理或留 cleanup 原因；状态变更经 Ledger。草稿、探针脚本与日志放 staging/<agent>/<request>/scratch/，Ledger 不读、不归档、不作证据；staging 其余产出应被事件引用，收尾报告给未引用占比。包内规则与脚本不是证据，按卡片小节引用。

## 唯一项目根与三类资产

`workspace_root` 的确定与配置目录身份见[项目上下文](project-context.md#固定位置与身份)；三个目录在其下并列：

- `.sdd-migration`：长期配置入口，跨运行复用；只有 Host 更新。
- `.sdd-runs/<run_id>`：一次迁移的唯一运行根，由 prepare 自动派生；模块用 module_id、每次测试用新 attempt 子目录继续隔离。
- `openspec`：规格、状态机与工作流中枢。`runs/<run_id>/workflow.md` 导航本轮 GO/父子 MO/审计状态；`changes/<run_id>-<module_id小写>` 保存叶子六件套。两者都按 run_id 隔离。

`package_root` 的脚本、模板和 uv 依赖环境是工具安装资产；legacy/target/reuse_sources 是代码输入或目标。原始业务文档可在外部，只读输入经 context/files 固化。构建缓存/APK/测试素材也是运行资产（[构建资产位置](build-automation.md#构建资产位置)）。工具安装依赖、工作流包自身文档/绘图/回归夹具不属于迁移运行资产。

## 从开始到完成的目录

```text
<workspace_root>/
├── .sdd-migration/                      # 项目配置、history/、sources/、runs/、preparations/、harmony/（凭证不入 Ledger）、inputs/
├── .sdd-runs/<run_id>/
│   ├── input.json                       # 本轮高层输入
│   ├── context/                         # snapshot.json（不可改写）、files/<sha256>.*、files/<sha256>.links.json、files/linked/、revisions/
│   ├── ledger/                          # events.jsonl（唯一事实）、global.json（plan 只以 plan_ref 引用）、modules/<id>.json、repair-memory.json、progress.json、audit-batch.json
│   ├── artifacts/<sha256>               # 不可变内容寻址工件
│   ├── staging/<agent>/<request>/       # 被事件引用的生成件；scratch/ 放草稿、探针、日志，Ledger 不读不归档、拒绝引用
│   ├── runs/
│   │   ├── build/<module-attempt>/      # query/result/receipt、stdout/stderr、execution-state.json（I/O 观察）、outputs/、cache/、temp/
│   │   ├── watchdog/                    # 旁路监听状态与 acknowledged/ 回执
│   │   └── harmony/                     # sandbox/environment/（共享 config/.env 与 manifest）、sandbox/<request>/、automation/<module-path-attempt>/
│   ├── reports/                         # migration-report.json/.md、workflow-attention.md、rejected-operation.json、rejections/、projection-recovery/、watchdog/
│   └── audit-reports/<batch_id>.json/.md  # 有人工问题时产生
└── openspec/
    ├── runs/<run_id>/                   # owner.json、projection-owners/<module_id>.json、workflow.json、workflow.md
    └── changes/<run_id>-<module_id小写>/  # 六件套与 status/checklist/memory；reuse.md、dimensions.md、scenarios.md 按计划产生；manifest.json 记冻结版本与清单
```

目录树是全部支持的留存类别，不无条件创建；没有修复、来源追加、Harmony 执行或人工问题就不伪造对应记录，未执行的测试保留 Yellow，不能用空目录当通过证据。

Watchdog 的留存与边界见[旁路监听协议](watchdog.md#留存与权限边界)；工作流不等待其文件或进程。

## OpenSpec 与状态机

OpenSpec 中枢展示 Ledger 当前 sequence、全局及父/子状态、global_next_step、next_steps、审计/来源更新路由，并链接模块状态、六件套、全局报告。它是生成的阅读入口，不是第二个可写事件源：

1. SPEC 定义由 Spec-Designer 在 staging 生成，plan 提交后归档；freeze 仍须原批准门禁。
2. 实现/测试/验收/失效请求通过 Ledger；正式六件套与状态由 Ledger 投影。
3. 事件提交刷新中枢状态并标记 routing_refresh_required；宿主调用 `ledger.py status` 得到当前派发门禁，更新精确路由，再采取动作。
4. 编辑/删除 workflow 或 status 不能改变事实；status 可重建视图。不能删除 owner.json、context 或 artifacts 后仍声称可恢复。
5. 中枢与六件套链接使用实际顶层路径；知识跳转继续指向本轮 context/files 固化版本，不改历史证据 hash。
6. 在写模块投影前先保存 projection-owners 归属；事件已提交但 manifest 尚未生成就中断时，`ledger.py status` 可依据该归属从 Ledger 重建，不重复提交业务事件。已有合法 manifest 可补登记归属；无 manifest 且无归属的外来目录仍拒绝覆盖。深层目录、目标文件与清理路径均拒绝符号链接重定向。

当前控制器不自动发布/归档顶层 `openspec/specs` 基线、不覆盖其他 run 或未声明归属的 change；manifest 的 structural-only 不表示已执行 OpenSpec CLI 验证。

## OpenSpec 投影完整性收尾门禁

顶层 `<workspace_root>/openspec/` 是 Ledger 生成投影，不手写为状态源。位置由 [workflow_hub.location](../../migration-ledger/scripts/workflow_hub.py) 与 [run_storage.change_root](../../migration-ledger/scripts/run_storage.py) 从 prepare 固化的 storage_layout 解析；未绑定布局的旧入口可能使用 run 内回退目录。缺失 `ledger/events.jsonl` 时无法验证该 run 的事件依据，但不能仅凭文件缺失断言控制器从未运行；也可能是证据损坏或位置错误。散文报告、空目录或自造 registry 不能补足缺失的事件证据。

只读 [verify_openspec.py](../../migration-ledger/scripts/verify_openspec.py) 按 scope 核验：global 检查公共事件链、prepare 快照和顶层布局归属；module 检查指定模块、祖先与实际依赖的当前规范/投影；projection 比较整个 run 的生成视图与 Ledger 内容；final 在 projection 之上要求正式 report_stage 为 completed 或 completed-with-unverified-tests。默认 projection 可在仅规划阶段通过，不表示已实现。manifest 的引擎标记和摘要用于一致性检查，不是宿主真实执行的认证签名。

```sh
python3 <package>/skills/migration-ledger/scripts/verify_openspec.py --root <workspace_root>/.sdd-runs/<run_id> --scope module --module-id M001
python3 <package>/skills/migration-ledger/scripts/verify_openspec.py --root <workspace_root>/.sdd-runs/<run_id> --scope final
```

`verified=false` 表示所选范围存在具体核验失败，读取 failures 的 check/scope/module_id/recovery_action 和 next_actions。仅相关模块错误不得停止无关 MO；公共事件链/快照损坏才影响整轮。生成视图缺失按投影恢复协议重建，冻结源损坏恢复有效证据或正常失效/重规划，不一律重建 run。门禁只读，不改状态、不补写投影、不搬迁历史；它无法单独证明真实 Agent 派发、命令执行或全部功能 Green。最终 Yellow 缺测仍在正式报告保留。

回退显式暴露：`ledger.py status --view full` 返回 `openspec_binding`，`location=top-level` 表示绑定了 prepare 固化的 `storage_layout`、投影落在顶层 `workspace/openspec`；`location=in-run-fallback`（未 prepare/未绑定 `project_context_ref`）说明本 run 的 OpenSpec 落在 `.sdd-runs/<run_id>/openspec`，宿主据此立即感知需要走预备管道，而非事后才发现顶层目录缺失。

## 启动与二次启动

请求内含 project_id、run_id、request_id、source_ref；之后使用返回的 run_root，不自选运行目录：

```sh
python3 <package>/skills/migration-ledger/scripts/project_context.py prepare --root <workspace_root>/.sdd-migration --request <request.json> --host-context <host.json>
python3 <package>/skills/migration-ledger/scripts/ledger.py status --view full --root <workspace_root>/.sdd-runs/<run_id>
```

prepare 核验目录、文档及摘要；缺输入不创建 run/OpenSpec。固化前 Host 写 preparations=preparing；失败写 failed、原因/重试入口，中断保留 preparing。同 run_id 重试验证归属，成功登记索引并写 prepared，保留失败历史；不替代 Ledger，不自动删除或改业务状态，完成的同请求不重写。

工作流测试辅助命令显式传 --root：Harmony design/adapter/doctor/历史报告与阶段汇总写入本轮 runs/harmony/sandbox；正式自动化写 runs/harmony/automation/<新 attempt>。独立模式使用同样的 `.sdd-runs/<run_id>/runs/harmony` 路径，可由显式输出推导根目录，不要求已有 Ledger；doctor 必须指定 --root。独立执行不自动得到冻结、assignment 或验收资格。

Ledger 在查询、变更和拒绝诊断写入前核对快照绑定的 run_root/run_id；索引或准备记录缺失时同样核对 project_id/run_id/run_root 与请求及实际恢复目录一致再登记索引。复制或移动已有 run 目录不能直接作为新 run 继续写入，仍绑定原路径的快照被拒绝；恢复回到原登记位置，新迁移使用新 run_id。受管文件写入统一使用路径检查和随机临时文件，拒绝符号链接重定向；事件追加与工件保存也检查实际路径。

| 场景 | 文件变化 | 状态处理 |
| --- | --- | --- |
| 首次 init/prepare | 新配置、历史、来源、run 索引、context 快照、OpenSpec owner | Ledger init 后才进入运行 |
| 同请求重复 prepare | 返回原快照；不新建另一目录，不更新配置/预算 | duplicate=true；不重新切片/实现 |
| 同 run 再次启动 | 读取位置索引与 Ledger；status 可重建视图 | 保留 revision、失败、预算、assignment；失效 worker 按原 revoke/recover 流程 |
| 完成后再次查询同 run | 不增加事件或测试；可重建报告/中枢 | 不从 completed 重置到 init |
| 明确更新项目输入 | 当前配置和历史增加版本 | 旧 run 仍读其冻结快照 |
| 新 run_id 启动 | 新索引、新 `.sdd-runs/<id>`、新 `openspec/runs/<id>`；规划后新增该 run changes | 重新 GO 规划；不直接继承旧 Green |

历史不搬迁/改 hash。嵌套旧控制器/协议引用须有本 run 已提交事件的路径/哈希证明，读受管 artifacts 同哈希归档，新事件记 historical-snapshot/accepted_event；缺损拒绝。其他输入及 SPEC/代码/环境仍严格校验；历史不作当前指令。`trace.py evidence --root <run_root> --sha256 <hash>` 返回引用、归档路径/事件证明，不写状态。

无 storage_layout 的旧根目录 `ledger.py history --root <目录>` 仅重放，不刷新投影/写锁/诊断；继续执行须按当前存储约束恢复并在同 Run 补齐证据；调整布局需迁移评审，不伪装同路径恢复或用新任务替代原任务。

## 写入与测试边界

新 prepare 固化布局并绑定 OpenSpec owner；执行器校验测试 output 位于当前 `.sdd-runs/<run_id>/runs/`，拒绝其他 run 或经符号链接逃逸。原始输入、代码位置与外部只读依赖可被引用；证据按原归档机制固化。

不同 run 的目录隔离不等于目标源码的跨 run 写锁；共享同一 target_root 的并发迁移仍由宿主协调或串行执行。

Python 路径校验不构成操作系统权限沙箱；实际 Agent、Gradle、设备/LLM 工具的任意文件写入仍需宿主限制。OpenSpec CLI、真实业务构建/设备和语义完备性验证与文件布局测试分开报告。

## 执行临时目录与外部工具

- 执行器向子进程传递本轮 TMPDIR/TMP/TEMP、XDG/uv/pip/Gradle 缓存目录，禁用 Python 字节码。Harmony 在 SDK 导入前绑定 Python tempfile、SDK output/working_dir 与当前工作目录；覆盖外部 HYPIUM_MCP 路径变量，扩展 skill 用 runner 工作目录读写，源码仍用绝对路径读取。
- 正常结束/异常返回清除本执行的 temp，保留 cleanup.json；termination.host_stop_required=true 时外层与 Harmony temp 都不删，记 retained-in-run/process-stop-unconfirmed，交 Host 停止或隔离后清理（[异常回执](build-automation.md#构建和自动化异常回执)）；清理失败留原因，不另建系统临时文件；强制中断的残留在该 run 内，恢复时先确认 worker 已停止，不清理仍活跃的兄弟 attempt。
- 设备互斥用本机 loopback 端口租约，不建系统临时锁文件；按 device/ip/port 稳定映射，进程退出自动释放；端口冲突或不允许绑定时返回不可执行信号，绝不绕过互斥或称测试通过；租约不收发网络数据。
- 默认 Gradle 的 GRADLE_USER_HOME、project cache、buildDirectory 指向构建 attempt，init.d 策略留证；启动只追加确定的 project-cache-dir/gradle-user-home 参数，回执保留 requested_argv 与实际 argv，验收重算校验；工程自行覆盖 buildDirectory 到外部会失败并走诊断/Fixer。环境变量与路径校验不是 OS 沙箱，不承诺任意命令都无法越界。
- 设备端 /data/local/tmp 录屏与相册 fixture 是设备 I/O，不是宿主资产：正常结束清理录屏临时副本并拉回本轮 reports；断连/强杀后的设备清理在下次使用前核验。

## 原位置与治理映射

SDK 的 reports/dumps、截图/视频与临时文件写入本 runner 的 sdk、temp，环境覆盖不能改位置；工具安装与维护资产留在原位置，运行期新增的缓存、配置、证据不写回包目录。

Harmony 写入器的路径约束见 [Harmony 运行协议](../../migration-test/references/harmony-runtime.md#底层直接调用的留存路径约束)。

模板里的 absolute-run-root 必须展开为 workspace_root/.sdd-runs/run_id；asset-name/evidence-path 等文件名占位符不得再次携带绝对根或 ..。Host 身份输入示例放 .sdd-migration/inputs，角色输出放指定 staging 或 Harmony sandbox。运行未确定 project/workspace/run_id 时先定位配置，不自行把本工作流包认作业务运行根。

Gradle 启动参数与 init.d 机制参考 [官方 init script 文档](https://docs.gradle.org/current/userguide/init_scripts.html)；实际工程插件/Gradle 版本仍需在目标项目验证，Python wrapper 夹具不等于真实 Gradle 构建通过。

本 run 的 Harmony 环境由 Test-Runner 用 sandbox.py prepare 初始化；配置源优先显式输入、长期项目参考、包内 default。共享 environment 加锁幂等、私密权限，不跟随参考源更新；同任务配置变化经 run-review/revise-run 批准后使用 environment-<context摘要> 新目录，旧版本留存；不重建 Run。子模块仅复用配置，各 attempt 独立写结果；不将凭证目录整体归档为 Ledger 工件。

初始化先在 environment/preparation.json 原子保存整套配置内容及摘要，再写成员文件，最后提交 manifest.json（status=ready），调用方经 prepare 验证后才获得配置路径；中途失败保留 preparing，重试读同一准备内容，不混用后来更改的参考源；提交后每次复用校验全部摘要及 config.native.yaml 当时不存在，提交后删除 preparation.json，中断则下次校验后清理。准备文件含 .env 的可恢复内容，属私密凭证：目录 700、文件 600，不入 Ledger/artifacts 或 Git；失败原因留在调用方原有错误/Yellow 回执。

无 manifest 的环境不推断历史版本一致性，也不补入当前参考文件；无可靠准备记录时交 Host 核验，在原 Run 内按受控版本修订恢复。完成清单或成员被修改时拒绝静默覆盖，按原环境异常出口处理相关测试；独立任务继续。

## 投影异常与视觉工具留存

`reports/projection-recovery/<module_id>/<sha256>.manifest` 保存已验证所有权的损坏 manifest 原件，长期留在本 run，当前 manifest 和视图从事件重建；恢复规则见[进度恢复协议](progress-recovery.md#授权改码投影恢复与文件锁等待)。

业务已完成但仍有 projection-pending 时，watchdog 保持 completed-with-pending-diagnostics 观察状态，通知只写既有 runs/watchdog 与 reports/watchdog。此状态不新增目录、不改变业务验收，正常 status 恢复投影后监听收尾。

受限视觉工具的留存与清理见[视觉执行](visual-execution.md#3-失败留存与恢复)：统一位于 `runs/harmony/sandbox/<actor>/<request_id>/`，冻结执行配置在 `sandbox/environment/visual.json`；正式验收仍走 automation runner 与 Ledger。
