# 运行与 Ledger 协议

## 总则

默认优先恢复同角色原 session；缺失时按 checkpoint 冷恢复，不要求永久保留一个已失效的宿主会话。角色只在当前阶段需要时创建，9+1 职责不变。所有恢复/修复请求仍经过 Ledger，不能恢复为角色私聊。请求只用[操作矩阵](local-runtime.md#操作矩阵)列出的 operation，未知 operation 拒绝。

## 路径与加载

`workspace_root` 为本项目唯一迁移资产根；`.sdd-migration`、`.sdd-runs`、`openspec` 在其下并列。`package_root` 为工作流包，legacy/target 为业务代码仓，均不是默认资产根。各目录的用途、二次启动和兼容规则见[留存文件系统](storage-layout.md#从开始到完成的目录)。

新 prepare 自动派生 `run_root = workspace_root/.sdd-runs/run_id`，显式 `--run-root` 只能与之相同；历史快照沿旧位置恢复。项目索引绑定一个 run_id 的唯一位置，不保存模块状态。新测试执行器拒绝把结果写到本轮 `runs/` 外。生成的 SPEC、诊断、修复、审查清单先写自身 staging；Harmony 测试设计/适配器/汇总写 runs/harmony/sandbox；随后提交 Ledger；输入源码/架构可在外部只读，需留存的文档与证据由快照固化。Host 须限制实际 Agent/子进程写权限。

OpenSpec 是规格及状态机的统一阅读入口，状态变更仍经 Ledger；不能编辑 status/workflow 文件替代事件。`assignments` 等信息当前嵌入 Ledger 投影；若宿主另导出 assignment 文件，放本轮 staging 并通过已提交引用交接，不假定脚本自动生成独立文件。顶层已有 `openspec/specs` 的基线发布/归档须单独授权，不由本轮投影覆盖。

run-id/change-name/capability 使用 kebab-case，module_id 匹配 `M[0-9]{3,}`。resolve/realpath 后确认目标写路径在 assignment allowlist 内；拒绝 `..`、符号链接越界和 legacy/target 重叠（除非输入明确批准原地迁移并提供隔离方案）。Legacy 源码默认只读。每次输出记录内容 sha256；引用文件以 path+sha256 固定，不以修改时间为版本。

## 请求与事件

请求见 [ledger-request.json](../../../template/ledger-request.json)：schema_version、request_id、run_id、module_id（全局操作为 null）、expected_revision、operation、payload，可带 hint。调用身份 role/instance_id 由宿主认证后经 host-context 注入，请求体不能自报。Ledger 接受后写入事件：event_id、单调 sequence、UTC timestamp、actor、operation、previous_hash、状态变化与工件快照索引。

同一 request_id + 同一内容 + 同一身份重复提交返回原 ACK，不重复派发；同 ID 不同内容拒绝。expected_revision 是目标模块（module_id 为 null 时为全局）的修订号；过期拒绝后重读重算，不能盲目覆盖。文件引用 `{path, sha256}` 的摘要须是该文件当前的摘要（`contracts.py ref`）；hash 不符的拒绝给出文件与实际摘要，改用它，工件改动后重新取。写入只经 Ledger CLI，任何进程不得自行追加 events.jsonl。

## 接受与恢复

校验宿主身份、操作角色/作用域/修订号、活动 assignment 的 fencing token 及工件 hash，再执行守卫。submit 不等于完成。工件先归档 artifacts/<sha256>，可读后才在单写者文件锁内分配序号、追加 events.jsonl 并 fsync；之后原子重建带 last_sequence 的投影，ACK 仅在事件落盘后返回。

事件日志是唯一事实源：首条存初始状态，其后存 set/del 变化；状态存报告/结果引用。工件原路径检测漂移，快照供追溯，已归档文件不重复列出。投影失败用 status/同请求重建，不重复派发；完整事件损坏停止，由 Host 从校验备份恢复或人工处置，禁止自动截断/倒改历史。hash 链检测意外篡改，不能抵御整本重写。observed_invalidations 要求 Host 提交 revoke/invalidate，不把磁盘变化记为完成。无事件文件是孤儿，已提交文件缺失/手改使相关证据失效，须重建。

## 权限

身份由宿主绑定；operation 权限见[操作矩阵](local-runtime.md#操作矩阵)，禁止事项见角色硬约束。跨角色工件、修复报告、调度、人工反馈及环境变化均经 Ledger 已提交引用交接。

## 并行、锁与依赖

依赖在 register / decompose 时登记：依赖必须已存在，拒绝环和未知模块。不同模块可并行，活动 assignment 总数受 max_parallel_modules 限制；每个模块同一时刻只有一个活动 assignment，它占用该模块直到 accept 或带真实停止证据的 revoke，不按时间自动重授。写集合重叠（目录与其子路径视为冲突）的两个模块不能同时有活动 worker，后者的 assign 被拒，等前者结束后串行执行；共享文件独立成前置模块或由唯一 owner 处理。宿主仍须在每次真实写操作执行 ACL/fencing。

模块依赖未就绪时以 suspend(kind=dependency) 记录生产者、原因与恢复条件；生产者完成后 Global 提交 dependency-ready，MO resume 回到需重验的阶段，不改 Green。生产者代码或契约变化使消费者旧结果失效。环、缺失模块或无法满足的依赖交人工裁决，不无限轮询；全部模块都在等待且无可推进动作时由 status.workflow_progress 给出阻塞信号。

## 宿主派发

assign（审计为 audit-assign / problem-assign）被接受后，宿主用真实可用的 task/spawn 工具启动该实例，只传 package_root、run_root、module_id 与阅读卡路径；叶子完成只交 Ledger 引用。宿主缺少调度、身份或持久化能力时如实报告不可用，不模拟执行成功。目标 OpenSpec 正式文件物化、原生身份认证、源码写隔离、自动派发及归档由宿主实现，不能通过直接修改投影旁路控制器。

## 项目配置与运行快照

长期配置固定为 `<workspace_root>/.sdd-migration/project-context.json`，不随 cwd 变化；项目 revision 独立于 run/module。写入、历史及 prepare 见[项目上下文](project-context.md#总则)。init 绑定 project_context_ref，下游只读该版本；更新配置仅作用于后续运行，不能旁路本轮冻结 SPEC/测试。

## 显式执行任务

v2 `assign` 使用 [执行分配模板](../../../template/execution-assignment.json)：Implementer 选 TASK，Test-Runner execute 选 TASK/PATH，Fixer 选 FINDING 与受影响 TASK/PATH。Ledger 固化 plan_ref/hash、freeze_id、基线、写范围、权限及证据要求，提交结果不得含未分配工作；目标执行器也限制 PATH。Test-Runner design 是 MO 指派的规划任务，读取 SPEC/测试输入产出用例，不运行目标代码。

同一模块可分批执行 TASK，复用合规实例；代码 manifest 累积包含已接受文件，未分配任务的文件不可修改或省略。全部 TASK 完成并补齐整体四维/复用证据后才进入正式测试；部分完成不能宣称模块 DoD。build 分配包含 build/unit/static 全阶段 PATH，可在首个非 Green 前置停止；其他测试批次完整核对所选 PATH，DoD 核对模块全部 PATH。

## 渐进加载

常驻红线、权限、assignment、版本/提交门禁；实现必读冻结规范与验收。卡片按 TASK/PATH 取事实，规划/最终审计保留完整范围。新事实/read_hint 按需追加单节；未加载不关闭门禁。

未确认根因/重复失败才加载增强小节。lesson_candidates 最多 5 条，同分优先失败经验；模块按范围/四维/根因检索，GO 切片及上游修订按当前目标/功能检索。核适用后读正文；规划历史默认最近 5 条和总数，完整记录沿 history_refs 读取。

hint.context_inputs=[{kind,ref}] 仅报实际交付的 spec/source/log/history/tool/fixture；核 hash 后按内容去重为 input_bytes，重复交付另计 input_delivered_bytes/input_delivery_count。context_load/session_rotate 统计已报材料，非 token 或宿主完整上下文；不授权读取。日志/工具输出先存工件，按需交付。

render --resumed 不清除旧上下文；Host 按[会话交接](host-integration.md#会话交接)创建同 Run 独立会话并恢复。轮换不改任务、冻结、质量或预算。
