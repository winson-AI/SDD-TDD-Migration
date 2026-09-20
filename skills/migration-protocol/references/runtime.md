# 运行与 Ledger 协议 v1

## 路径与加载

`package_root` 为本包绝对路径；`target_root` 为目标仓；`run_root = <target_root>/openspec/migrations/<run-id>`；`change_root = <target_root>/openspec/changes/<change-name>`。

```text
openspec/
  specs/<capability>/spec.md                    # 已接受行为基线
  changes/<run-id>-m001-<slug>/
    proposal.md
    specs/<capability>/spec.md                 # 六件套的 spec 部分
    design.md
    tasks.md
    status.md                                 # Ledger 投影
    checklist.md                              # 定义冻结，完成值由 Ledger 投影
  migrations/<run-id>/
    input.json
    ledger/events.jsonl                       # 唯一事实日志，只追加
    ledger/global.json                        # 可重建投影
    ledger/modules/M001.json                   # 可重建投影
    reports/migration-report.json             # GO 全 CASE/PATH 状态及非 Green 证据投影
    reports/migration-report.md               # 同一 sequence 的可读报告
    assignments/<assignment-id>.json
    modules/M001/_input.json
    artifacts/<artifact-id>/...                # 提交后的不可变快照、报告、冻结内容
    staging/<agent-instance>/<request-id>/...  # 本角色临时产物
    runs/<test-run-id>/...                     # 实际日志、断言、环境快照
```

表中运行目录均由 Ledger/宿主按事件生成。业务 Agent 只能写自身 staging、获锁的目标源码或指定 test-run 目录；不得自行改六件套正式路径。Spec-Designer 设计六件套，但只提交内容/状态建议；Ledger 投影实际 status，Module-Orchestrator 审核状态变化。Ledger 不创作业务需求。

run-id/change-name/capability 使用 kebab-case，module_id 匹配 `M[0-9]{3,}`。resolve/realpath 后确认目标写路径在 assignment allowlist 内；拒绝 `..`、符号链接越界和 legacy/target 重叠（除非输入明确批准原地迁移并提供隔离方案）。Legacy 源码默认只读。每次输出记录内容 sha256；引用文件以 path+sha256 固定，不以修改时间为版本。

## 事件信封

见 [event.json](../../../template/event.json)。所有请求包含 schema_version、run_id、request_id、actor(role/instance)、assignment_id、module_id（全局为 null）、expected_revision、causation_event_id、event_type、payload 和 artifacts。Ledger 接受后补 event_id、单调 sequence、UTC timestamp、new_revision 和 previous_event_id；客户端不能自填可信 actor 或服务端序号。

宿主提供已绑定实例身份的 `submit(request)` 与 `read(after_sequence, scope)`。无 RPC 时可由主宿主持有单一 Ledger 实例，串行代理提交；不能允许多个进程自行 append events.jsonl。请求队列仅是 Ledger 入站通道，不是角色间共享邮箱。

同一 request_id + 同一内容重复提交返回原 ACK，不重复派发；同 ID 不同内容拒绝。expected_revision 是目标 module/global aggregate 修订号；过期拒绝后重读重算，不能盲目覆盖。跨模块事务须校验涉及的全部 aggregate revisions。

## 引导事务

首次 `run_requested` 是唯一无已有 assignment 的请求，由宿主认证用户命令身份，expected_revision=0，run-id 尚不存在。Ledger 原子创建 run 事实与 Global 初始化 assignment；run_initialized 只能由该 assignment 提交。其后所有角色请求必须有合法 assignment。status 查询不用创建 assignment；不得借引导例外提交测试、冻结或完成事件。

模块初始投影及 `_input` 来自 module_registered 事务；global-ledger 模板的 modules 列表只是结构示例，必须用实际拆分结果替换。任何能力不可用都记录 bootstrap/tooling 阻塞，不能为了初始化跳过宿主身份验证。

## 接受与恢复

1. 验证宿主绑定身份、assignment、作用域、父因果事件、版本、锁 fencing token 和产物摘要。
2. 检查请求类型权限与守卫批准；不把 worker 的“成功”自动变成 module completed。
3. 将 staged 工件放到不可变 artifact-id 地址并验证完整。只有工件可读取后才 append 事件，fsync；未被事件引用的孤儿工件可稍后清理。
4. 在单写者串行临界区内分配序号、持久化事件；按事件生成 global/module/status/checklist 投影，写临时文件后原子替换。投影携带 last_sequence。
5. ACK 仅在事件落盘后返回。若投影写失败，日志仍有效，恢复时 replay。尾部不完整记录隔离为故障证据，不能当作合法事件；中部损坏停止并升级。

重启从快照 sequence + 后续事件重建；重新校验工件 hash、当前 code baseline 与锁持有人。文件存在但缺少已接受事件时是 orphan；文件缺失/被手改则 artifact_invalidated，挂起相关阶段并重建，不能凭文件存在推断 done。所有投影是缓存，事件是事实；不能倒改历史事件来“修复状态”。

## 权限矩阵

| 提交者 | 允许请求 | 禁止事项 |
| --- | --- | --- |
| Command/Host | run_requested、plan_requested、resume_requested、audit_requested、archive_requested，传输提交/查询 | 自行写状态、批准 SPEC、改代码 |
| Global-Orchestrator | run_initialized、module_registered、dag_updated、lock_grant/release、dependency_resolved、dispatch_request、global_escalated、archive_plan | 直接 module completed、改测试结论 |
| Module-Orchestrator | transition_requested、assignment_accepted/rejected、freeze_accepted、change_reviewed、dependency_requested、module_completed、dispatch_request | 代写实现或独立审计通过 |
| Spec-Designer | spec_proposed、clarification_requested、freeze_requested、spec_revision_proposed、impact_analyzed | 修改代码、自批准冻结 |
| Implementer | implementation_submitted、task_trace_submitted | 改 SPEC、状态、验收标准 |
| Test-Runner | test_design_submitted、test_run_recorded | 给模块盖 DoD、删失败记录 |
| Diagnostician | diagnosis_submitted | 修复任何源码 |
| Fixer | patch_submitted、regression_submitted、change_requested | 改冻结工件、直接宣告正式测试 Green |
| Auditor | audit_snapshot_requested、audit_run_recorded、audit_verdict、repair_requested | 写代码、修测试脚本、绕过模块守卫改状态 |
| Escalation | escalation_opened、human_decision_recorded、escalation_expired | 代答问题、超时默许 |
| Ledger | committed/rejected ACK、snapshot_rebuilt、artifact_invalidated | 自创业务批准、代替人类或审计者裁决 |

权限来自宿主身份绑定而非模型声明。事件 payload 必须包含对应工件、原因、目标与证据；未知事件类型拒绝。下游通过已提交事件引用读取跨角色工件。修复报告、调度信息、人工反馈、环境变化都遵守同一路径。

## 并行、锁与依赖

Global 维护 DAG；边明确 `depends_on module + required_contract_version + readiness=completed`。默认由 Agent 按端到端业务能力决定粒度，支持人工模块导入；完整功能 use case 可按一级/二级功能目录初分，再核对 scope 和测试列表。不能机械按 UI/data/repository 技术层拆分。整体用例覆盖跨模块时保留 GLOBAL 集成覆盖范围和参与模块；GLOBAL 不代表验收角色。跨模块或不确定的业务边界交人工决定；已批准契约内的调度按 DAG 执行。详见 [切片规约](../../migration-global/references/slicing.md)。

资源锁对真实源码路径/公共接口/OpenSpec capability/测试环境建模。默认单一目标工作树，只有写集合不重叠且无依赖的模块可并行。目录与子路径视为冲突；读写冲突也需阻止。共享文件独立成前置模块或串行授权。所有锁按规范路径排序，一次申请全部，失败不持有部分锁，避免死锁。

每个锁记录 owner assignment、resource、lease_expires_at、fencing_token。仅 Global 决策授权，Ledger 原子提交；宿主每次写/接收补丁须检查 fencing token。租约过期先停止/隔离旧进程、确认其不能再写，之后才重授予，不能只看时间就允许两者同时写。依赖/人工等待时 checkpoint 后释放可释放锁；恢复重获锁并校验版本，旧 worker 结果拒收。

Module 遇跨模块 Yellow 提交 dependency_requested（producer、contract、paths、复现、唤醒条件），Global 验证依赖存在且无环，再登记订阅。依赖满足只唤醒到需重验证阶段，不改 Green；生产者版本变化使受影响消费者旧结果 stale。若 DAG 环/缺模块/无法达到契约版本，则进入人工裁决，不能无限轮询。所有活动模块都在等待且无可调度生产者时生成全局阻塞报告。

## 宿主派发

dispatch_request 接受后产生 assignment（见模板）；宿主以真实可用 task/spawn 工具启动新实例并带入 package_root、assignment_ref、event_ref。叶子完成只交 Ledger 引用。编排器可以继续消费事件，Auditor 修复请求由所属 Module-Orchestrator 审核并派发 Fixer，Global 协调跨模块写锁。未提供调度/身份/持久化能力时记录 runtime-unavailable，不模拟执行成功。

## 本地实现状态

本包已提供 [local-runtime.md](local-runtime.md) 对应的本地控制器、契约校验器和真实子进程测试适配器。此前描述的完整宿主协议仍是集成边界；本地实现的确切操作、权限、限制以该操作矩阵为准。

`events.jsonl` 是唯一事实日志，受进程文件锁保护；投影可重建。接受请求前保存输入证据的内容寻址副本，事件保留原路径与快照引用；原路径用于检测工作区变化，快照用于追溯。损坏日志采取 fail-closed，不自动截断或删除尾部。该脚本的 `status` 输出包含 observed_invalidations，要求宿主随后提交 invalidate/revoke，不把磁盘改动悄悄写成业务完成。

原协议事件信封供宿主接口使用；本地 CLI 使用 `operation` 请求，由宿主根据下表文档映射，而非声称所有抽象事件名已实现。目标 OpenSpec 正式文件物化、原生身份认证、源码写隔离、自动派发及归档仍由宿主实现；不能通过直接修改投影旁路控制器。

## 项目配置与运行快照

长期配置放在工作目录 `.sdd-migration/project-context.json`，项目 revision 独立于 run/module revision。配置写入、历史和 prepare 由 [项目上下文协议](project-context.md) 定义；init 绑定本轮 project_context_ref 后，下游只读该固定版本。用户更新只作用于后续运行，不通过修改配置旁路已冻结 SPEC 和测试。
