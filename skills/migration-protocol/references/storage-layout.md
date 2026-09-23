# 迁移留存文件系统

## 唯一项目根与三类资产

`workspace_root` 是项目唯一迁移资产根，首次保存在 `.sdd-migration/project-context.json`，默认取该配置目录父级。可以与目标仓位于同一工作区，但不由 target_root 推导；目标仓变化不搬迁配置、证据或规格。新入口不允许配置目录不匹配 workspace_root，也不允许通过运行 overrides 改根目录。

三个目录在 workspace_root 下并列：

- `.sdd-migration`：长期配置入口，跨运行复用；只有 Host 更新。
- `.sdd-runs/<run_id>`：一次迁移的唯一运行根，由 prepare 自动派生；模块用 module_id、每次测试用新 attempt 子目录继续隔离。
- `openspec`：规格、状态机与工作流中枢。`runs/<run_id>/workflow.md` 导航本轮 GO/父子 MO/审计状态；`changes/<run_id>-<module_id小写>` 保存叶子六件套。两者都按 run_id 隔离。

`package_root` 的脚本、模板和 uv 依赖环境属于工具安装资产；legacy/target/reuse_sources 是代码输入或目标。原始业务文档可以位于外部，只读输入通过 context/files 固化。为本轮生成的说明、计划、脚本、报告及录制媒体应在三目录内留存，不能另外建立目标仓 SPEC 副本。除目标源码修改外，全部迁移资产集中管理。构建缓存/APK/测试素材也属于运行资产；默认 Gradle 执行注入本轮缓存与 buildDirectory，自定义构建脚本的输出位置必须在冻结前审核并映射到本轮 runner。工具安装依赖、工作流包自身文档/绘图/回归夹具不属于迁移运行资产。

## 从开始到完成的目录

```text
<workspace_root>/
├── .sdd-migration/
│   ├── project-context.json               # 当前配置；revision 与 run 独立
│   ├── history/<sha256>.json              # 每版配置，previous_ref 串联
│   ├── sources/<sha256>.*                 # 用户输入来源快照
│   ├── runs/<run_id>.json                 # run_id → run_root/初始快照索引
│   ├── preparations/<run_id>.json         # preparing/failed/prepared，失败原因与重试入口
│   ├── harmony/                          # config.json、.env、可选 config.native.yaml；凭证不入 Ledger
│   ├── inputs/                           # Host 可选保存原始输入/请求；不是自动生成
│   └── .context.lock
├── .sdd-runs/
│   └── <run_id>/
│       ├── .ledger.lock
│       ├── input.json                    # GO 完成后 Host 保存的本轮高层输入
│       ├── context/
│       │   ├── snapshot.json             # 初始配置/来源/布局；不可原地改写
│       │   ├── files/<sha256>.*           # 架构、知识、来源、sealed snapshot
│       │   ├── files/<sha256>.links.json  # 跨文件链接映射（按输入产生）
│       │   ├── files/linked/<bundle>/...  # 重定位后的可读知识副本
│       │   └── revisions/<sha256>.json    # 同 run 来源追加时产生
│       ├── ledger/
│       │   ├── events.jsonl              # 只追加的唯一状态事实
│       │   ├── global.json               # 全局状态、规划、审计等投影
│       │   ├── modules/<module_id>.json   # 父/子 MO，含分配/assignment/结果
│       │   ├── repair-memory.json        # 修复策略、根因、回归证据
│       │   ├── progress.json             # 查询时生成的宿主进度信号
│       │   └── audit-batch.json           # 有治理/遗留批次时产生
│       ├── artifacts/<sha256>            # 提交前保存的不可变内容寻址工件
│       ├── staging/<agent>/<request>/    # 角色/Host 原始生成件，提交后保留
│       │   └── ...                       # GO 功能清单/分配、SPEC 定义、四维/复用/
│       │                                 # 埋点、测试设计/脚本、诊断/Fixer/CR、
│       │                                 # Auditor 代码清单、人工决策、GO 报告输入
│       ├── runs/
│       │   ├── build/<module-attempt>/    # query/result/receipt/execution.log、cleanup.json
│       │   │   ├── outputs/              # Gradle 工程产物及 APK
│       │   │   ├── cache/                # 构建缓存、Gradle init.d 输出策略
│       │   │   └── temp/                 # 可确认安全结束后清理；退出未确认时留存
│       │   ├── watchdog/                 # 可选旁路监听：自身锁、Host 导出、去重状态
│       │   │   └── acknowledged/         # notice-ID.json 交付确认；不改变业务状态
│       │   └── harmony/
│       │       ├── sandbox/environment/  # 本 run 共享 config.json/.env，由 Test-Runner 从参考复制
│       │       │   ├── manifest.json     # 整套环境完成清单、摘要及 native 缺省记录
│       │       │   └── preparation.json  # 仅准备/恢复期间保留；含私密配置内容，提交后删除
│       │       ├── sandbox/<request>/    # adapter、design、doctor、阶段/历史报告
│       │       │   └── runtime/          # 转换调用的 temp/cache/cleanup（按需）
│       │       └── automation/<module-path-attempt>/
│       │           ├── query.json / result.json / receipt.json / execution.log
│       │           ├── cleanup.json / cache/ / temp/
│       │           └── harmony/
│       │               ├── observations.json / environment.json / engine.log
│       │               ├── reports/ / memory/ / sdk/ / cache/
│       │               └── temp/ / cleanup.json
│       ├── reports/
│       │   ├── migration-report.json
│       │   ├── migration-report.md       # GO 全 CASE/PATH 三态、非 Green 证据
│       │   ├── workflow-attention.md
│       │   ├── rejected-operation.json   # 最新拒绝导航，兼容旧入口
│       │   ├── rejections/<fingerprint>.json # 各作用域独立计数与历史
│       │   ├── projection-recovery/      # 损坏投影原件（按需）
│       │   └── watchdog/                 # 可选 latest.json、notice-<timestamp>.json
│       └── audit-reports/<batch_id>.json/.md # 有人工问题时产生
└── openspec/
    ├── runs/<run_id>/
    │   ├── owner.json                    # 本轮命名空间归属，绑定配置/运行根
    │   ├── projection-owners/<module_id>.json # 写六件套前固化的归属；投影中断恢复
    │   ├── workflow.json                 # 当前 sequence、父子模块、路由、引用
    │   └── workflow.md                   # Host/GO/MO/Auditor 统一阅读入口
    └── changes/<run_id>-<module_id小写>/
        ├── proposal.md
        ├── specs/<capability>/spec.md
        ├── design.md
        ├── tasks.md
        ├── status.md
        ├── checklist.md
        ├── memory.md
        ├── reuse.md                      # 计划包含复用映射时
        ├── dimensions.md                 # 计划包含四维分析时
        └── manifest.json                 # run_root/module/冻结版本/生成文件清单
```

目录树表示全部支持的留存类别，不意味着无条件创建每个文件。没有修复、来源追加、Harmony 执行或人工问题，就不伪造对应记录；父 MO 的分配/汇总在 Ledger 与 staging/artifacts，不能伪装成叶子实现规格。未执行的测试保留 Yellow，不能用空目录当通过证据。

Watchdog 配置随正常项目配置固化，监听产物仅在本 run 的 runs/watchdog 和 reports/watchdog；它不写 Ledger/上下文/OpenSpec、不获取业务锁、不提交恢复动作。OpenSpec 原投影器可链接已有诊断文件；工作流不等待该文件或监听进程。详见 [旁路监听协议](watchdog.md)。

## OpenSpec 与状态机

OpenSpec 中枢展示 Ledger 当前 sequence、全局及父/子状态、global_next_step、next_steps、审计/来源更新路由，并链接模块状态、六件套、全局报告。它是生成的阅读入口，不是第二个可写事件源：

1. SPEC 定义由 Spec-Designer 在 staging 生成，plan 提交后归档；freeze 仍须原批准门禁。
2. 实现/测试/验收/失效请求通过 Ledger；正式六件套与状态由 Ledger 投影。
3. 事件提交刷新中枢状态并标记 routing_refresh_required；宿主调用 `ledger.py status` 得到当前派发门禁，更新精确路由，再采取动作。
4. 编辑/删除 workflow 或 status 不能改变事实；status 可重建视图。不能删除 owner.json、context 或 artifacts 后仍声称可恢复。
5. 中枢与六件套链接使用实际顶层路径；知识跳转继续指向本轮 context/files 固化版本，不改历史证据 hash。
6. 在写模块投影前先保存 projection-owners 归属；事件已提交但 manifest 尚未生成就中断时，`ledger.py status` 可依据该归属从 Ledger 重建，不重复提交业务事件。已有合法 manifest 可补登记归属；无 manifest 且无归属的外来目录仍拒绝覆盖。深层目录、目标文件与清理路径均拒绝符号链接重定向。

已有顶层 `openspec/specs` 的正式基线与 archive 属于单独的发布动作。当前控制器不自动发布/归档、不覆盖其他 run 或未声明归属的 change。manifest 的 structural-only 不表示已执行 OpenSpec CLI 验证。

## OpenSpec 投影完整性收尾门禁

顶层 `<workspace_root>/openspec/` 是投影,不能手写:它仅在 prepare → `ledger init`（绑定 `project_context_ref`）→ `apply` 真正跑通、且状态绑定 prepare 固化的 `storage_layout` 时产生（位置由 [workflow_hub.location](../../migration-ledger/scripts/workflow_hub.py) 与 [run_storage.change_root](../../migration-ledger/scripts/run_storage.py) 从 `for_state` 解析）。缺 `storage_layout` 会静默回退到 `.sdd-runs/<run_id>/openspec`；整条管道未跑时，即使回退目录也只是手搓骨架。**唯一判据：run 内没有 `ledger/events.jsonl`（唯一事实源），就说明 Ledger 控制器从未运行**——`ledger/module-registry.json`（本包从不产生此文件名）、散文报告或空 `openspec` 目录都是手写产物，不代表迁移已执行。

收尾（GO 交付报告、`/sdd-audit`、`/sdd-archive`）必须通过只读门禁 [verify_openspec.py](../../migration-ledger/scripts/verify_openspec.py)，它 fail-closed 校验：`events.jsonl` 非空且事件链完整、`context/snapshot.json` 存在、状态绑定 `project_context_ref`、顶层 `openspec/runs/<run_id>/workflow.{json,md}` 存在、无 in-run 回退目录、每个已规划叶子的 `openspec/changes/<run-id>-<mid>` 有归属正确的 `manifest.json`（投影引擎签名，手写目录没有），以及 `reports/migration-report.json` 为结构化投影（`schema_version/run_id/report_stage/cases/paths`；投影每次同时写 `.json` 与 `.md`，手写 case 只有散文 `.md`）。

```sh
python3 <package>/skills/migration-ledger/scripts/verify_openspec.py --root <workspace_root>/.sdd-runs/<run_id>
```

`verified=false` 表示该 run 绕过了 Ledger，GO/Auditor 不得据其自述报告宣称完成，须回到 prepare → init → apply 重跑。门禁只读，不改状态、不补写投影、不搬迁历史。

回退不再静默：`ledger.py status` 返回 `openspec_binding`，`location=top-level` 表示绑定了 prepare 固化的 `storage_layout`、投影落在顶层 `workspace/openspec`；`location=in-run-fallback`（未 prepare/未绑定 `project_context_ref`）说明本 run 的 OpenSpec 落在 `.sdd-runs/<run_id>/openspec`，宿主据此立即感知需要走预备管道，而非事后才发现顶层目录缺失。旧兼容 run 只读重放不受影响。

## 启动与二次启动

```sh
# 请求内含 project_id、run_id、request_id、source_ref
python3 <package>/skills/migration-ledger/scripts/project_context.py prepare \
  --root <workspace_root>/.sdd-migration --request <request.json> --host-context <host.json>
# 使用返回的 run_root；无需再自选运行目录
python3 <package>/skills/migration-ledger/scripts/ledger.py status \
  --root <workspace_root>/.sdd-runs/<run_id>
```

显式传入 --run-root 时，新 run 必须与派生路径一致；目录符号链接重定向会被拒绝。`.sdd-migration/runs/<run_id>.json` 在项目锁内绑定唯一位置，不包含业务状态，不另起总线。

prepare 先核验必需目录、文档和引用摘要；输入缺失时不创建 run/OpenSpec。进入实际固化前，Host 在 preparations 写 preparing；固化/登记失败记录 failed、原因和重试动作，突然中断则保留 preparing。修正条件后重试同 run_id，验证归属并继续固化；成功写位置索引并改为 prepared，保留失败历史。该记录仅用于初始化恢复，不取代 Ledger；不自动删除失败目录或改业务状态。同请求恢复完成的 run 不重写这些文件。

工作流测试辅助命令显式传 --root：Harmony design/adapter/doctor/历史报告与阶段汇总写入本轮 runs/harmony/sandbox；正式自动化写 runs/harmony/automation/<新 attempt>。独立模式使用同样的 `.sdd-runs/<run_id>/runs/harmony` 路径，可由显式输出推导根目录，不要求已有 Ledger；doctor 必须指定 --root。独立执行不自动得到冻结、assignment 或验收资格。旧任意输出目录不再接受；兼容入口保留读取历史输入，所有新输出遵循新位置。

Ledger 在查询、变更和拒绝诊断写入前核对快照绑定的 run_root/run_id。复制或移动已有 run 目录不能直接作为新 run 继续写入；恢复应使用原登记位置，新迁移使用新 run_id。Ledger/上下文/OpenSpec 的受管文件写入统一使用路径检查和随机临时文件，拒绝符号链接重定向；事件追加与工件保存也检查实际路径。

workspace_root 位于目标工程内时，自动构建发现排除 `.sdd-migration`、`.sdd-runs`、`openspec`，包括指向其内部脚本的文件链接，避免选择历史脚本。用户显式配置的构建命令仍按原优先级处理，并经过冻结和执行预检。

| 场景 | 文件变化 | 状态处理 |
| --- | --- | --- |
| 首次 init/prepare | 新配置、历史、来源、run 索引、context 快照、OpenSpec owner | Ledger init 后才进入运行 |
| 同请求重复 prepare | 返回原快照；不新建另一目录，不更新配置/预算 | duplicate=true；不重新切片/实现 |
| 同 run 再次启动 | 读取位置索引与 Ledger；status 可重建视图 | 保留 revision、失败、预算、assignment；失效 worker 按原 revoke/recover 流程 |
| 完成后再次查询同 run | 不增加事件或测试；可重建报告/中枢 | 不从 completed 重置到 init |
| 明确更新项目输入 | 当前配置和历史增加版本 | 旧 run 仍读其冻结快照 |
| 新 run_id 启动 | 新索引、新 `.sdd-runs/<id>`、新 `openspec/runs/<id>`；规划后新增该 run changes | 重新 GO 规划；不直接继承旧 Green |

同一 run_id 改请求内容会拒绝，不可借此替换冻结上下文。恢复一般直接读索引→status；若重试 prepare 必须重用原请求。同 run 来源追加仍走 source-review/reconfigure-sources，另增 context/revisions，不以普通配置 update 代替。

历史证据不得就地搬迁/修改 hash。旧运行没有 storage_layout 时，底层 Ledger 兼容解析仍识别原 run_root 与内部 openspec 位置；显式指向旧快照的重复 prepare 可登记位置索引。此兼容路径不自动移动/重写旧 hash，不允许新入口借它随意创建外部目录。无快照的旧低层 Ledger API 为回归兼容保留；正式 CLI 的 init/apply/status/resume/recover 必须绑定 prepare 布局，新 init 必须绑定 project_context_ref。旧目录通过 `ledger.py history --root <旧目录>` 只读重放，既不刷新投影也不写锁/诊断；宿主不得调用底层兼容 API 绕过新的存储门禁。旧布局需要继续迁移时，先在三目录内 prepare 新 run，以只读历史引用记录来源，重新规划/冻结，不能伪装成旧 run 的同路径恢复。

索引或准备记录缺失时，也必须核对快照的 project_id/run_id/run_root 与请求及实际恢复目录一致，再登记索引。复制出来但仍绑定原路径的快照会被拒绝，不写入错误位置索引；应回到原绑定目录恢复。此校验不改变合法旧运行的存储位置或快照摘要。

## 写入与测试边界

新 prepare 固化布局并绑定 OpenSpec owner；执行器校验测试 output 位于当前 `.sdd-runs/<run_id>/runs/`，拒绝其他 run 或经符号链接逃逸。GO/Spec/Fixer/Auditor 等工件和请求由宿主安排到本轮 staging；Harmony 配置生成、用例导入、阶段汇总归 runs/harmony/sandbox，其他测试脚本可放 staging。原始输入、代码位置与外部只读依赖可被引用；证据按原归档机制固化。

不同 run 的目录隔离不等于目标源码的跨 run 写锁；共享同一 target_root 的并发迁移仍由宿主协调或串行执行。

Python 路径校验不构成操作系统权限沙箱；实际 Agent、Gradle、设备/LLM 工具的任意文件写入仍需宿主限制。OpenSpec CLI、真实业务构建/设备和语义完备性验证与文件布局测试分开报告。

## 可重跑的生命周期模拟

```sh
PYTHONDONTWRITEBYTECODE=1 python3 <package>/skills/migration-ledger/tests/simulate_storage.py \
  --output <全新模拟目录>
```

模拟调用真实项目配置/prepare/Ledger/执行器，使用两个叶子 MO 和一个父 MO，执行 Python 构建及业务断言，M001 Red→Fixer→正式复测、M002 Green、父汇总、独立 Auditor 审查收尾；随后恢复同 run，再更新配置并启动新 run，完成 GO/父子 MO 规划与叶子冻结；新 run 不执行代码/测试，不继承旧 Green。输出 workspace 实际文件树和 evidence 下五个阶段的内容 hash 清单、增删改 summary.json。模拟中的审批、语义分析和角色是测试夹具，不代表真实用户授权、宿主派发或移动设备测试。


## 执行临时目录与外部工具

- 执行器向子进程传递本轮 TMPDIR/TMP/TEMP、XDG/uv/pip/Gradle 缓存目录，禁用 Python 字节码。Harmony 在 SDK 导入前同时绑定 Python tempfile、SDK output/working_dir 和当前工作目录；覆盖外部 HYPIUM_MCP 路径变量，扩展 skill 使用 runner 工作目录读写，源码仍用绝对路径读取。
- 正常结束/异常返回清除本执行的 temp，保留 cleanup.json；执行器超时向 attempt 进程组发停止信号，并限时回收输出。若 termination.host_stop_required=true，外层及 Harmony temp 均不删除，记录 retained-in-run/process-stop-unconfirmed，交 Host 停止或隔离后清理；否则沿原规则清理。清理失败同样留存原因，不另建系统临时文件。宿主/机器强制中断可能使 finally 无法执行，残留已位于该 run，恢复时先确认 worker 已停止再检查该 temp；禁止清理仍活跃的兄弟 attempt。
- 设备互斥使用本机 loopback 端口租约，不再创建系统临时锁文件。按 device/ip/port 稳定映射，进程退出自动释放；端口冲突或宿主不允许绑定时返回不可执行信号，绝不绕过互斥或称测试通过。该租约不监听/发送网络数据。
- 默认 Gradle 的 GRADLE_USER_HOME、project cache、buildDirectory 指向构建 attempt，init.d 策略留证；启动时只追加确定的 project-cache-dir/gradle-user-home 参数，回执保留 requested_argv 与实际 argv，验收重新计算并校验；工程自行覆盖 buildDirectory 到外部会失败并走既有诊断/Fixer。自定义 Gradle 插件、shell、其他构建工具的绝对输出必须由宿主在冻结前审核/配置，必要时由宿主文件权限约束。环境变量和路径校验不等于 OS 沙箱，不能承诺任意命令都无法越界。
- 设备端 /data/local/tmp 录屏与相册 fixture 是设备 I/O，不是宿主资产目录：正常结束清理录屏临时副本，拉回本轮 reports；断连/强杀后的设备清理须在下次使用设备前核验。不得把系统文件或用户相册当作可批量迁移/清除的宿主资产。

## 原位置与治理映射

| 原位置/内容 | 新位置/处理 |
| --- | --- |
| harmony/.env、项目模型配置 | 长期参考为 .sdd-migration/harmony；Test-Runner 首次 prepare 复制到本 run runs/harmony/sandbox/environment/.env、config.json。旧文件仅作显式复制来源，密钥不入证据 |
| harmony/adapter.local.json | .sdd-runs/<run_id>/runs/harmony/sandbox/<request>/adapter.json，按新 run 重新生成 |
| cwd reports/memory、独立任意输出 | runs/harmony/automation/<attempt>/harmony/reports、memory；CLI 拒绝旧任意输出路径 |
| 原 XMind 旁的转换 Markdown | runs/harmony/sandbox/<request>/converted.md；原生兼容 CLI 转换落入该自动化 attempt/design |
| SDK reports/dumps、系统截图/视频/concat临时文件 | 本 runner 的 sdk、temp；SDK 环境覆盖不能改变位置 |
| context/spec/诊断/缺口/审查等生成记录 | run staging → artifacts；六件套与导航在顶层 openspec |
| 外部需求/源码/二方库/测试历史 | 原文件只读，文档经 context/files 固化，证据按 artifacts 归档；不搬迁业务源码 |
| 既有外部运行结果 | 保留只读历史；新输出创建受管 run，不改历史 hash、不自动删除原件 |
| .venv、wheel、公开默认配置、包源码/文档/diagrams、包自身测试日志 | 工具安装/维护资产保持原位置；运行期间新增的缓存、配置、证据不写回包目录 |

模板里的 absolute-run-root 必须展开为 workspace_root/.sdd-runs/run_id；asset-name/evidence-path 等文件名占位符不得再次携带绝对根或 ..。Host 身份输入示例放 .sdd-migration/inputs，角色输出放指定 staging 或 Harmony sandbox。运行未确定 project/workspace/run_id 时先定位配置，不自行把本工作流包认作业务运行根。

Gradle 启动参数与 init.d 机制参考 [官方 init script 文档](https://docs.gradle.org/current/userguide/init_scripts.html)；实际工程插件/Gradle 版本仍需在目标项目验证，Python wrapper 夹具不等于真实 Gradle 构建通过。

本 run 的 Harmony 环境由 Test-Runner 用 sandbox.py prepare 初始化；配置源优先显式输入、长期项目参考、包内 default。共享 environment 加锁幂等、私密权限，不跟随参考源更新；不同配置使用新 run。子模块仅复用配置，各 attempt 独立写结果；不将凭证目录整体归档为 Ledger 工件。

初始化先在 environment/preparation.json 原子保存整套配置内容及摘要，再写成员文件，最后提交 manifest.json（status=ready）。所有调用方经过 prepare 验证后才获得配置路径；中途失败保留 preparing，重试读取同一准备内容，即使参考源后来更改/删除也不混用版本。已写成员必须与准备内容一致；提交后的每次复用校验全部摘要，以及 config.native.yaml 当时是否不存在。提交后删除 preparation.json；若在提交与删除之间中断，下次校验完成后清理。准备文件含 .env 的可恢复内容，属于私密凭证资产：目录 700、文件 600，不加入 Ledger/artifacts 或 Git。失败原因保留在调用方原有错误/Yellow 回执中。

无 manifest 的完整旧环境以现有 config.json/.env/可选 native 建立兼容基线，不补入新的参考文件，也不推断历史版本一致性；不完整旧环境无可靠准备记录时交 Host 核验或使用新 run，禁止拿当前参考补齐。完成清单或成员被修改时拒绝静默覆盖，按原环境异常出口处理相关测试；独立任务继续。

## 底层直接调用同样遵守留存规则

路径约束必须落在实际写入/清理函数中，不能只依靠 CLI 或技能说明。Harmony 原生写入器统一调用 AutoTest/storage.py：

| 产物 | 缺省处理 | 无运行上下文时 |
| --- | --- | --- |
| XMind 转换 Markdown | 当前 runner/design/<源文件名>.md | 必须显式传入本轮 sandbox/automation 下的绝对输出目录；禁止写回源文件旁 |
| HTML/JSON/Markdown 报告、截图布局 | runner/reports 或显式受管位置 | 缺省相对路径拒绝；显式位置仍检查三目录归属 |
| 录制记忆 | runner/memory | 可只读加载外部旧记忆；新录制必须受管 |
| 图片/视频/时间映射、结果 JSON、日志 | 当前 runner 或显式受管位置 | 不能退回 cwd、包目录或来源旁 |
| 截图、裁剪、拼接临时文件 | runner/temp；独立媒体处理可用显式受管输出旁的 temp | 无 runner 且无可判定的受管输出时拒绝，不使用系统 temp |
| SDK/设备报告 | 本轮 sdk 或已校验报告目录 | SDK 执行需进入 runner scope，禁止退回第三方默认 dumps/reports |
| shell/扩展 skill | runner cwd；子进程固定存储环境变量 | 缺 runner 拒绝，不能覆盖 TMPDIR/SDK/cache 等受管变量 |

显式输出不能跨当前 run、不能经符号链接或 .. 跳转；报告文件名生成后也重新检查。外部源码、原始用例、历史报告/视频保持只读；裁剪证据在本轮保存，自动清理不能删除外部输入。直接调用如果不进入 scope，受管 temp 残留仍在该 run；宿主确认 worker 结束后处理，不做系统目录清理。

Test-Runner 对非法路径返回的错误保留执行日志并按现有 Yellow/环境预检失败提交；不得为了继续执行而改用任意目录或取消无关模块。生成资产经既有 Ledger 提交/验收，存储校验本身不构成测试通过。

这些检查约束本包的写入器与子进程启动参数。任意 shell 命令、扩展 Python 或构建插件仍可自行使用绝对路径/修改 cwd；Host 必须按冻结命令与文件权限约束实际写入，不能把路径校验声明成 OS 沙箱。工具安装、开发验证夹具和设备端路径遵循此前列明的例外。


### 投影异常的留存与恢复

`reports/projection-recovery/<module_id>/<sha256>.manifest` 保存已验证所有权的损坏 manifest 原件，长期留在本 run；当前 manifest 和视图从事件重建。投影失败详情进入 status.projection、workflow_progress 和可写时的 workflow-attention.md。事件已提交而投影待恢复时，原 event_id/sequence 仍有效，不追加重复业务事件。其他 owner/符号链接不自动替换；日志与快照损坏仍需恢复有效证据。完整规则见 [进度恢复协议](progress-recovery.md#授权改码投影恢复与文件锁等待)。

progress.json 在尝试输出 workflow-attention.md 后写入，以保留该报告的写入失败；机器诊断失败最多补写一次，其余错误由 Host 消费命令返回值。业务已完成但仍有 projection-pending 时，watchdog 保持 completed-with-pending-diagnostics 观察状态，通知只写既有 runs/watchdog 与 reports/watchdog。此状态不新增目录、不改变业务验收，正常 status 恢复投影后监听收尾。
