# 运行与 Ledger 协议

## 总则

默认优先恢复同角色原 session；缺失时按 checkpoint 冷恢复，不要求永久保留一个已失效的宿主会话。角色只在当前阶段需要时创建，9+1 职责不变。所有恢复/修复请求仍经过 Ledger，不能恢复为角色私聊。请求只用[操作矩阵](local-runtime.md#操作矩阵)列出的 operation，未知 operation 拒绝。

## 路径与加载

`workspace_root` 为本项目唯一迁移资产根；`.sdd-migration`、`.sdd-runs`、`openspec` 在其下并列。`package_root` 为工作流包，legacy/target 为业务代码仓，均不是默认资产根。完整目录、二次启动和兼容规则见 [留存文件系统](storage-layout.md)。

```text
<workspace_root>/
  .sdd-migration/                         # 长期配置、版本历史、run_id → 路径索引
  .sdd-runs/<run_id>/                     # run_root
    context/                             # 冻结上下文与来源版本
    input.json                           # Host 保存本轮 GO 输入
    ledger/events.jsonl                  # 唯一事实日志
    ledger/global.json
    ledger/modules/<module_id>.json      # 父/子 MO 状态、分配与结果
    artifacts/<sha256>                   # 不可变提交证据
    staging/<agent>/<request>/           # Host/Agent 生成资产
    runs/build/<attempt>/               # 构建 query、结果、回执、缓存与产物
    runs/harmony/automation/<attempt>/  # 自动化 query、结果、回执及媒体
    runs/harmony/sandbox/<request>/     # 导入、adapter、doctor、汇总
    reports/                             # GO 报告、进度与拒绝信号
    audit-reports/                       # 有人工问题时生成
  openspec/
    runs/<run_id>/owner.json             # 本轮命名空间归属
    runs/<run_id>/workflow.json          # 机器状态/路由导航
    runs/<run_id>/workflow.md            # 工作流中枢入口
    changes/<run_id>-<module_id小写>/    # change_root；本轮六件套与辅助视图
```

新 prepare 自动派生 `run_root = workspace_root/.sdd-runs/run_id`，显式 `--run-root` 只能与之相同；历史快照沿旧位置恢复。项目索引绑定一个 run_id 的唯一位置，不保存模块状态。新测试执行器拒绝把结果写到本轮 `runs/` 外。生成的 SPEC、诊断、修复、审查清单先写自身 staging；Harmony 测试设计/适配器/汇总写 runs/harmony/sandbox；随后提交 Ledger；输入源码/架构可在外部只读，需留存的文档与证据由快照固化。Host 须限制实际 Agent/子进程写权限。

OpenSpec 是规格及状态机的统一阅读入口，状态变更仍经 Ledger；不能编辑 status/workflow 文件替代事件。`assignments` 等信息当前嵌入 Ledger 投影；若宿主另导出 assignment 文件，放本轮 staging 并通过已提交引用交接，不假定脚本自动生成独立文件。顶层已有 `openspec/specs` 的基线发布/归档须单独授权，不由本轮投影覆盖。

run-id/change-name/capability 使用 kebab-case，module_id 匹配 `M[0-9]{3,}`。resolve/realpath 后确认目标写路径在 assignment allowlist 内；拒绝 `..`、符号链接越界和 legacy/target 重叠（除非输入明确批准原地迁移并提供隔离方案）。Legacy 源码默认只读。每次输出记录内容 sha256；引用文件以 path+sha256 固定，不以修改时间为版本。

## 请求与事件

请求见 [ledger-request.json](../../../template/ledger-request.json)：schema_version、request_id、run_id、module_id（全局操作为 null）、expected_revision、operation、payload，可带 hint。调用身份 role/instance_id 由宿主认证后经 host-context 注入，请求体不能自报。Ledger 接受后写入事件：event_id、单调 sequence、UTC timestamp、actor、operation、previous_hash、状态变化与工件快照索引。

同一 request_id + 同一内容 + 同一身份重复提交返回原 ACK，不重复派发；同 ID 不同内容拒绝。expected_revision 是目标模块（module_id 为 null 时为全局）的修订号；过期拒绝后重读重算，不能盲目覆盖。写入只经 Ledger CLI，任何进程不得自行追加 events.jsonl。

## 接受与恢复

1. 校验宿主绑定身份与该 operation 的调用角色、作用域、修订号、活动 assignment 的 fencing token 和工件摘要。
2. 执行该 operation 的守卫；worker 的 submit 不会自动变成模块完成。
3. payload 引用的工件先复制到 artifacts/<sha256>，可读后才追加事件并 fsync。
4. 单写者临界区内分配序号、落盘事件，再重建 global/module/status 等投影（临时文件原子替换，携带 last_sequence）。
5. ACK 仅在事件落盘后返回。投影写失败时日志仍有效，下次 status 或重复请求重建，不重新派发已确认请求；完整事件损坏则停止，不自动截断或删除，由宿主从已校验备份恢复或人工处置。

`events.jsonl` 是唯一事实日志，受进程文件锁保护；投影可重建，不是第二事实源。hash 链可发现意外篡改，但不是抵御重写整本日志的签名链。首个事件记录初始状态，其后每个事件只记录变化（patch 的 set/del）；状态只存报告与结果的哈希引用。事件保留工件原路径与快照引用（更早事件已归档的工件不重复列出）；原路径用于检测工作区变化，快照用于追溯。`status` 的 observed_invalidations 要求宿主随后提交 revoke/invalidate，不把磁盘改动悄悄写成业务完成。缺少对应事件的文件是孤儿；已提交工件缺失或被手改使相关证据失效，须重建，不能凭文件存在推断完成，也不能倒改历史事件来“修复状态”。

## 权限

权限来自宿主身份绑定而非模型声明。每个 operation 允许的调用角色见[操作矩阵](local-runtime.md#操作矩阵)，各角色的禁止事项见其 Agent 定义的硬约束。下游只通过已提交事件引用读取跨角色工件；修复报告、调度信息、人工反馈、环境变化都遵守同一路径。

## 并行、锁与依赖

依赖在 register / decompose 时登记：依赖必须已存在，拒绝环和未知模块。不同模块可并行，活动 assignment 总数受 max_parallel_modules 限制；每个模块同一时刻只有一个活动 assignment，它占用该模块直到 accept 或带真实停止证据的 revoke，不按时间自动重授。写集合重叠（目录与其子路径视为冲突）的两个模块不能同时有活动 worker，后者的 assign 被拒，等前者结束后串行执行；共享文件独立成前置模块或由唯一 owner 处理。宿主仍须在每次真实写操作执行 ACL/fencing。

模块依赖未就绪时以 suspend(kind=dependency) 记录生产者、原因与恢复条件；生产者完成后 Global 提交 dependency-ready，MO resume 回到需重验的阶段，不改 Green。生产者代码或契约变化使消费者旧结果失效。环、缺失模块或无法满足的依赖交人工裁决，不无限轮询；全部模块都在等待且无可推进动作时由 status.workflow_progress 给出阻塞信号。

## 宿主派发

assign（审计为 audit-assign / problem-assign）被接受后，宿主用真实可用的 task/spawn 工具启动该实例，只传 package_root、run_root、module_id 与阅读卡路径；叶子完成只交 Ledger 引用。宿主缺少调度、身份或持久化能力时如实报告不可用，不模拟执行成功。目标 OpenSpec 正式文件物化、原生身份认证、源码写隔离、自动派发及归档由宿主实现，不能通过直接修改投影旁路控制器。

## 项目配置与运行快照

长期配置放在固定 `<workspace_root>/.sdd-migration/project-context.json`，后续显式定位原配置目录，不随 cwd 变化，项目 revision 独立于 run/module revision。配置写入、历史和 prepare 由 [项目上下文协议](project-context.md) 定义；init 绑定本轮 project_context_ref 后，下游只读该固定版本。用户更新只作用于后续运行，不通过修改配置旁路已冻结 SPEC 和测试。
