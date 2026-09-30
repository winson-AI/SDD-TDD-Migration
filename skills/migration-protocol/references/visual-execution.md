# 受限视觉执行工具

本入口补充 Test-Runner/Auditor 的设备与比较取证。GO/父子 MO、冻结、模块阶段验收与独立审计职责沿现有流程执行，工具不提交 Ledger、不修代码、不自行增加比较或修复轮次。源码分析和 Android 基线获取仍按已有宿主能力执行；已有 Harmony Main/adapter 和完整 Capture 导入继续可用。

## 1. 准备与冻结

1. Host/Test-Runner 按项目参考配置（可保存在 `.sdd-migration/harmony/visual.json`）或 [配置模板](../../../template/visual-execution.json)，在本轮 `runs/harmony/sandbox/environment/visual.json` 生成执行配置。该文件与 sandbox prepare 已管理的 config.json 分开；不在执行期间改写已有环境 manifest。只复制本次用户选定的设备/backend/模型配置，不假定本机默认设备或个人 HOME 下配置可用。
2. Spec/Test design 将 `visual_execution` 放到对应 automation/visual PATH：environment_ref 的真实 path/hash、app_id、必要导航 actions、可验证的目标选择器。配置引用随路径冻结并持续验证，变更沿原计划/CR/重新冻结机制。无视觉执行需求时不增加此字段或全局门禁。
3. 设备执行使用显式 HDC backend。模型使用显式启用的 external 配置，API key 仅从指定的进程环境变量读取；配置与请求只保存变量名。Host 可从本 run 的私密环境加载变量，不把 `.env` 或明文 key 当证据归档。
4. 实际执行前 Host 持有设备独占锁，并在认证 host-context 中注入 device_lock 的 device_id、assignment_id、fencing_token、held。模型输出或 Agent 自填锁字段不构成真实锁；工具不是设备锁服务或 OS 沙箱。

## 2. 执行节点

所有操作通过 [lean_worker.py](../../migration-ledger/scripts/lean_worker.py)；请求样式见 [lean-visual-request.json](../../../template/lean-visual-request.json)。每次使用新 request_id：

```sh
python3 <package_root>/skills/migration-ledger/scripts/lean_worker.py \
  --root <run_root> --request <request.json> --host-context <authenticated-host.json>
```

| operation | 所需状态与输入 | 输出意义 |
| --- | --- | --- |
| visual-install | 当前 build 已接受 Green；automation 或 visual assignment；path_id、该 PATH 已接受构建中的 artifact_ref | 校验包身份、实际安装并记录装机元数据和命令；INSTALLED 不是测试通过 |
| visual-capture | 当前功能 Green 后的 visual assignment；冻结目标、artifact_ref、同 assignment/fence 的 install_ref、reference_manifest_ref、正整数 round | 真实截图/XML/meta/manifest，绑定构建、设备、状态及捕获轮次；CAPTURED 不是视觉对齐通过 |
| compare-only | visual assignment；实际 reference_ref/candidate_ref | 确定性 score；不能直接给 ALIGNED |
| semantic-inspect | visual assignment；冻结配置、reference_ref/candidate_ref/score_ref | 有总时限的模型比较，保留图片对和 score hash；INSPECTED 不是最终裁决 |

叶子 PATH 的所有比较原图来自同 coverage 的冻结 UI evidence（baseline_refs/capture_manifest_ref），支持滚动目标的第二屏及后续截图；不能借含首屏的任意 manifest 添加其他基线。Auditor 读取原叶子 SPEC 的证据集合，不能通过构建归属猜测 UI 归属。GLOBAL 自有 PATH 用 visual_evidence 显式冻结 coverage、visual_mode=runtime、capture_manifest_ref 与完整 baseline_refs。缺少完整原始证据时保留局部 Yellow，任何 adapter 都不能将其提升为 v2 正式 Green。

visual-capture 自动将 capture_execution_ref 写入候选 snapshot，关联 [捕获执行回执](../../../template/visual-capture-execution.json)。adapter 与正式验收重读当前 run 内的安装回执、执行日志、截图/树和元数据，推导 capture_evidence，检查 HAP/代码及完整原图集合。外部捕获器可由实际运行器提供同契约 sidecar；需要成功安装命令及实际 capture 命令与图片输出的关联，不能仅自填“当前版本”。已有 meta 中的构建/代码字段必须一致。缺 sidecar 保留 Yellow，不改写原始截图或旧证据。carried 只重验实际引用的历史轮次，并严格检查本轮当前构建。

安装可在功能自动化前执行；切换 assignment 后需要当前授权下的装机证据，不能沿用旧 assignment 的权限。最终 Auditor 仅处理已选取的审计 PATH，设备工具校验当前审计快照和 PATH 所属的构建产物，不能借用其他模块 HAP。

`execute_test` 将真实活动 assignment_id/fencing_token 写入 visual query 的 `execution_assignment`。v2 最新 capture_execution 必须属于该授权；正式 submit/accept/Auditor 使用 Ledger 的 assignment 再核验，不能用 adapter 自报身份替代。即使 HAP 与代码没有变化，新审计任务也必须实际重新捕获；重新读取旧截图只是审阅。ALIGNED_CARRIED 引用的历史轮次可保留旧授权，本轮捕获仍需当前授权。

viewport 捕获要求实际前台 App、冻结目标选择器以及截图前后稳定的页面树。scroll 除起点外还需冻结有源码依据的终点选择器 `scroll_end_match`，指定唯一可验证的 `scroll_region`；连续保存每屏证据并有界滚动，实际观察终点才能声明 scroll-complete。多滚动区域应拆 PATH 或使用既有完整 adapter。无可信滚动区域、未到终点、状态变化、截断或仅重复画面均不足以证明完整覆盖，保留 partial/Yellow；不得把缺少 scrollable 节点当成“无须滚动”。模糊导航/未支持 backend 使用已有正式运行器或如实留缺口，不静默切换。

Test-Runner 将原始截图、score、semantic 与交互证据组装为现有 alignment 结构，再通过 `execute_test.py → lean_visual_adapter.py → tests submit/accept` 走正式复核。脚本不从分数自动推导 ALIGNED；冻结手势仍需实际 action/observation 证据。本入口不自动执行未声明手势，也不代替功能自动化 Main。

semantic 原文件的所有 issues，以及 `comparability < 0.4` 或 `comparable=false`，都必须在对应 comparison 的 `semantic_dispositions` 中逐项裁决，才可声明 v2 Green。0.4 沿用 Lean 对不同路线/状态的解释，只标记待解释矛盾，不是自动通过阈值。每项包含原 semantic_ref（path/hash）、原 finding（issue 含 index 和完整内容；comparability/comparable 含原值）、`resolved|dismissed`、非空 reason 和实际 evidence_refs，至少一份佐证不同于原 semantic。无问题时不制造裁决。正式门禁重新读取原件；漏项、重复、旧 hash 或只有结论没有证据均拒绝。字段示例见 [visual-alignment.json](../../../template/visual-alignment.json)。裁决由当前测试/审计职责内的 Agent 作出，工具不替 Agent 判断是否真的修复。

## 3. 失败、留存与恢复

每个请求的 request/result/receipt、设备命令、装机结果、截图/树/meta/manifest、比较结果放 `runs/harmony/sandbox/<actor>/<request_id>/`；正式测试回执与报告仍在 `runs/harmony/automation/<attempt>/`。配置归同 run 的 sandbox/environment；正常临时文件清理，无法清理时保留原因。设备临时截图/树仅删除本次生成的文件，失败留清理记录。

工具 BLOCKED/quality_candidate 只是待提交证据，不能直接改 Ledger。缺少工具、设备、模型或观测条件时，Test-Runner 留原因/日志，MO 按实际情况使用既有 Yellow/未执行与 automation-unavailable 通道。已经观察到的失败断言不能覆盖成缺环境；设备错误或页面不符也不自动断言为实现缺陷，先走现有根因判断。Auditor 可继续代码审查及缺测收尾；其他模块与可用构建依赖继续。

工具执行取消后由宿主核实停止，按已有 revoke/audit-revoke 处理，不重启或释放业务锁。配置/hash/assignment/权限不匹配属于受控拒绝，返回原因供相关 owner 修订，不转换为测试 Green。真实设备与模型能力须在项目环境验证，本包的隔离测试仅证明控制与证据契约。
