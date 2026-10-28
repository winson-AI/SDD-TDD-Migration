#!/usr/bin/env python3
"""Skeletons of the reports an executing role files, written by the Ledger from what it holds.

A Test-Runner's building/testing preflight and static spec review, and the Auditor's change inventory and code
review: every field the Ledger can state is filled, every judgement only the role can make is a marked part.
Nothing written here is a result, a verdict or an accepted report; a report that still holds a mark is refused.
"""
import argparse
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True

from contracts import SKELETON_MARK, Rejected, check_ref, file_ref, read_json, require
import context_readiness as cr
from spec_skeleton import todo


def dump(out, name, data):
    path = out / name
    require(not path.exists(), 'refusing to overwrite ' + str(path))
    path.write_text(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    return file_ref(path)


def preflight(root, s, mid, assignment):
    """The report the Test-Runner submits before it runs: inputs, code and PATHs checked by the Ledger; commands copied
    from the frozen plan; environment, providers and permissions left to the worker."""
    m = s['modules'][mid]
    stage = 'building' if assignment.get('test_scope') == 'build' else 'testing'
    paths = [p for p in m['plan']['paths'] if p['path_id'] in assignment['execution_contract']['path_ids']]
    commands = {p['path_id']: {'argv': list(p['command']['argv']), 'cwd': p['command']['cwd']} for p in paths if p.get('command')}
    import execute_test
    for p in paths:
        if p.get('kind') == 'static':
            commands[p['path_id']] = {'argv': [todo('absolute spec_closure.py command: --review <static-review.json> --target-root <target>')], 'cwd': todo('target root')}
        elif p['path_id'] not in commands and p.get('kind') in ('automation', 'visual'):  # the adapter the run resolves for this platform, so the preflight and the executor agree
            try:
                chosen = execute_test.adapter_for(s, p, root)
                commands[p['path_id']] = {'argv': chosen['argv'], 'cwd': chosen['cwd']}
            except Rejected:
                commands[p['path_id']] = {'argv': [todo('absolute adapter command: state test_adapter.adapters.' + str(p.get('platform')) + ' in the project context, or write it here')], 'cwd': todo('target root')}
    try:
        cr.verify_inputs(s, mid, stage, deep=True, run_root=root)
        held = 'checked by the Ledger: the %d inputs of this stage exist and match their hashes; ' % len(cr.input_refs(s, mid, stage))
    except (Rejected, OSError, KeyError):
        held = None
    def ledger(text):
        return ({'status': 'ready', 'evidence_refs': [m['plan_ref']], 'summary': held + text} if held else
                own('an input of this stage is not as referenced: report what is missing'))
    def own(what):
        return {'status': todo('ready|blocked'), 'evidence_refs': [todo('{path, sha256} of what was read')], 'summary': todo(what)}
    facts = {'frozen-spec': ledger('freeze ' + str(m.get('freeze_id'))[:12]),
             'accepted-code': ledger('%d code files at baseline %s' % (len(m.get('code_files', [])), str(m.get('code_baseline'))[:12])),
             'test-paths': ledger('%d PATHs in this dispatch: %s' % (len(paths), ', '.join(p['path_id'] for p in paths))),
             'build-command': ledger('frozen or adapter argv/cwd of %d PATHs copied into execution.commands' % len(commands)),
             'build-environment': own('toolchain, SDK and caches this host runs the frozen commands with; probed, not assumed'),
             'test-environment': own('device/emulator, adapter and data the automation PATHs need'),
             'provider-binding': own('the real providers and fixtures the frozen PATHs bind'),
             'permissions-tools': own('identity of this dispatch and the tools it may run')}
    first = next((c for c in commands.values() if SKELETON_MARK not in str(c)), None)
    execution = {'argv': first['argv'] if first else [todo('absolute adapter command')], 'cwd': first['cwd'] if first else todo('target root'),
                 'environment_ref': todo('{path, sha256} of the environment note'), **({'commands': commands} if commands else {})}
    return {'schema_version': 1, 'run_id': s['run_id'], 'module_id': mid, 'stage': stage,
            'producer': {'role': 'test-runner', 'instance_id': assignment['instance_id']},
            'subject_sha256': cr.subject(s, mid, stage), 'checks': {name: facts[name] for name in cr.CHECKS[stage]},
            'verdict': todo('ready; blocked when any check is'), 'execution': execution}


def static_review(s, mid, assignment, path):
    """The review the static PATH's command checks: one row per frozen scenario, every anti-pattern listed."""
    m = s['modules'][mid]
    symbol = lambda what: {'path': todo('absolute target file'), 'symbol': todo(what)}
    rows = m.get('scenario_index') or [{'requirement_id': rid} for rid in sorted({r for t in m['plan']['tasks'] for r in t['requirement_ids']})]
    units = any(p.get('kind') == 'unit' for p in m['plan']['paths'])
    scenarios = [{**({'scenario_id': row['scenario_id']} if 'scenario_id' in row else {}), 'requirement_id': row['requirement_id'],
                  'status': todo('passed|failed'), 'summary': todo('what the production code does for this scenario, with lines'),
                  'production_symbols': [symbol('real symbol defined in it')],
                  'reached_from': symbol('the cited symbol, from another file: caller, DI, navigation or manifest'),
                  **({'test_refs': [symbol('test symbol that exercises it')]} if units else {}),
                  'evidence_refs': [todo('{path, sha256} of the review notes')]} for row in rows]
    import spec_closure
    return {'schema_version': 1, 'run_id': s['run_id'], 'module_id': mid, 'path_id': path['path_id'],
            'freeze_id': m['freeze_id'], 'code_baseline': m['code_baseline'],
            'reviewer': {'role': 'test-runner', 'instance_id': assignment['instance_id']},
            'independence': todo('why the reviewer wrote none of the code under review'), 'scenarios': scenarios,
            'anti_patterns': {name: {'status': todo('absent|present'), 'note': todo('where it was looked for'),
                                     'evidence_refs': [todo('{path, sha256}')]} for name in spec_closure.ANTI_PATTERNS}}


def inventory(s, sequence):
    """The change inventory: modules, features, files, impact and test mapping as the Ledger holds them."""
    import decomposition
    names = decomposition.parent_mo_names(s)
    plan = (s.get('global_plan') or {}).get('content', {})
    features = {row['feature_id']: row for row in read_json(check_ref(plan['feature_inventory_ref']))['features']} if plan.get('feature_inventory_ref') else {}
    owners = plan.get('feature_owners', {})
    cell = lambda values: ', '.join(str(v) for v in values) if values else '无'
    same = lambda path: str(Path(path).resolve())
    lines = ['# 本次迁移代码修改清单 · %s / review-revision %d（Ledger sequence %s）' % (s['run_id'], len(s.get('audit_code_review_history', [])) + (1 if s.get('audit_code_review') else 0) + 1, sequence), '',
             '> Ledger 写出其持有的事实；Auditor 写标记处的判断。测试状态只读取 Ledger，不因代码审查通过改成 Green。', '',
             '## 1. 范围与基线', '',
             '- Auditor instance：' + todo('独立审计者 ID'),
             '- 迁移入口与范围：%s；模块 %s' % (s.get('entry_mode', 'project'), cell(sorted(s['modules']))),
             '- 存量项目 / 目标项目：`%s` / `%s`' % (s['legacy_root'], s['target_root']),
             '- 起点：' + todo('commit/tree 或非 Git 快照；本轮开始时已有的工作区修改及证据'),
             '- 当前候选：' + todo('commit/tree、暂存/未暂存/未跟踪文件快照'),
             '- 完整 diff / 文件清单：' + todo('固化证据链接及 sha256'),
             '- 功能清单 / 全局规格：%s / %s' % (plan.get('feature_inventory_ref', {}).get('path', '无'), s['global_spec']['path']),
             '- 完备性：' + todo('complete 或 incomplete；缺项列入第 8 节'), '',
             '## 2. 模块汇总', '', '| 根模块 / 父 MO | 子模块 / owner | 功能点 | CHG-ID | 修改路径数 | 直接 / 下游影响 | 无修改时的依据 |', '| --- | --- | --- | --- | --- | --- | --- |']
    change_ids, rows3, rows4, rows5, rows6 = {}, [], [], [], []
    for mid, m in s['modules'].items():
        tasks = (m.get('plan') or {}).get('tasks', [])
        task_files = m.get('task_files', {})
        for ref in m.get('code_files', []):
            change_ids[(mid, same(ref['path']))] = 'CHG-%03d' % (len(change_ids) + 1)
        held = sorted(fid for fid, who in owners.items() if mid in who)
        dependents = sorted(other for other, x in s['modules'].items() if mid in x.get('dependencies', []))
        lines.append('| %s | %s / %s | %s | %s | %d | 依赖本模块：%s | %s |' % (
            names.get(m.get('parent_module_id')) or '无', mid, cell(m.get('authors', [])), cell(held),
            cell([change_ids[(mid, same(r['path']))] for r in m.get('code_files', [])]), len(m.get('code_files', [])), cell(dependents),
            todo('复用既有实现、未实现等真实原因') if not m.get('code_files') else '不适用'))
        for fid in held:
            feature = features.get(fid, {})
            tids = [t['task_id'] for t in tasks if fid in (t.get('feature_ids') or []) or set(t['requirement_ids']) & set(feature.get('requirement_ids', []))]
            files = sorted({same(f) for tid in tids for f in task_files.get(tid, [])})
            rows3.append('| %s %s | %s | %s / %s | %s | %s | %s | %s | %s |' % (
                fid, feature.get('name', ''), mid, cell(feature.get('requirement_ids')), cell(tids), todo('行为变化与迁移结果'),
                cell([row['item_id'] for row in (m.get('plan') or {}).get('dimension_trace', []) if set(row['task_ids']) & set(tids)]),
                cell([change_ids[(mid, f)] for f in files if (mid, f) in change_ids]),
                cell(['%s / %s' % (p['case_id'], p['path_id']) for p in (m.get('plan') or {}).get('paths', []) if p.get('case_id') in feature.get('case_ids', [])]),
                todo('SPEC / fidelity 依据')))
        for ref in m.get('code_files', []):
            tids = [tid for tid, files in task_files.items() if same(ref['path']) in {same(f) for f in files}]
            rows4.append('| %s | %s / %s | %s | %s | `%s` | %s | %s | %s → %s | %s |' % (
                change_ids[(mid, same(ref['path']))], mid, cell(tids), todo('add|modify|delete|rename'), todo('修改前路径；新增为不适用'),
                ref['path'], todo('符号 / 行段'), todo('修改内容与原因'), todo('before-sha 或不适用'), ref['sha256'][:12], todo('diff / 快照证据')))
        for trace in latest_implementation(m).get('reuse_trace', []):
            rows5.append('| %s / %s | %s | %s / %s | %s | %s | %s | %s |' % (
                cell([change_ids[(mid, same(f))] for f in trace.get('files', []) if (mid, same(f)) in change_ids]), trace.get('capability_id'),
                todo('直接影响'), todo('provider owner'), trace.get('resolved_version'), cell(dependents), todo('reuse/adapt/reference 及理由'),
                todo('生产接线证据'), todo('影响分析依据')))
        for p in (m.get('plan') or {}).get('paths', []):
            r = m.get('results', {}).get(p['path_id'], {})
            rows6.append('| %s / %s | %s / %s / %s | %s | %s | %s | %s | %s / %s / %s | %s / %s / %s | %s |' % (
                mid, p.get('case_id'), p['path_id'], p.get('name', ''), p.get('kind', 'automation'),
                cell([t['task_id'] for t in tasks if p['path_id'] in t.get('path_ids', [])]), todo('脚本 / 配置 / 数据证据路径'),
                cell([a['assertion_id'] for a in p.get('expected_assertions', [])]), todo('回归选择及依据'),
                r.get('quality', '未执行'), r.get('executed', False), r.get('stale', False),
                r.get('test_run_id', '无'), r.get('retest_of', '无'), str(r.get('code_baseline', '无'))[:12], todo('根因 / 结果证据')))
    lines += ['', '## 3. 功能点与实现追溯', '', '| 功能点 | 子模块 | REQ / TASK | 行为变化与迁移结果 | 四维条目 | CHG-ID | CASE / PATH | SPEC / fidelity 依据 |', '| --- | --- | --- | --- | --- | --- | --- | --- |', *(rows3 or ['| ' + todo('功能点') + ' | | | | | | | |']),
              '', '## 4. 逐文件代码修改清单', '', '| CHG-ID | owner / TASK | 修改类型 | 修改前路径 | 修改后路径 | 符号 / 行段 | 修改内容与原因 | 前 → 后摘要 | 证据 |', '| --- | --- | --- | --- | --- | --- | --- | --- | --- |', *(rows4 or ['| 无 | | | | | | | | |']),
              '', '**本轮已有工作区修改、未纳入迁移的改动及归属不明项**：' + todo('逐路径列出来源/排除理由/证据，或明确无'),
              '', '## 5. 影响范围与复用 / 公共能力', '', '| CHG-ID / 能力 | 直接影响 | provider owner / 版本 | 实际消费者 | 复用决策 | 生产接线 / 冗余清理证据 | 影响分析依据 |', '| --- | --- | --- | --- | --- | --- | --- |', *(rows5 or ['| 不适用 | ' + todo('无复用映射时的依据') + ' | | | | | |']),
              '', '## 6. 测试用例与测试路径映射', '', '| 模块 / CASE | PATH / Name / kind | TASK | 脚本 / 配置 / 数据证据 | ASSERT | 回归选择 | 状态 / executed / stale | test_run / retest_of / 基线 | 根因 / 结果证据 |', '| --- | --- | --- | --- | --- | --- | --- | --- | --- |', *rows6,
              '', '## 7. 清单核对与统计', '',
              '- 功能点数 / 已关联修改数：%d / %d' % (len(owners), len({fid for fid, who in owners.items() for mid in who for t in (s['modules'][mid].get('plan') or {}).get('tasks', []) if fid in (t.get('feature_ids') or []) and s['modules'][mid].get('task_files', {}).get(t['task_id'])})),
              '- 修改文件数（Ledger code_files）：%d；修改类型按第 4 节' % len(change_ids),
              '- 路径数 / 当前 Green：%d / %d' % (sum(len((m.get('plan') or {}).get('paths', [])) for m in s['modules'].values()),
                                            sum(1 for m in s['modules'].values() for r in m.get('results', {}).values() if r.get('quality') == 'green-passed' and not r.get('stale'))),
              '- diff → CHG → 功能/REQ/TASK → CASE/PATH/ASSERT 双向追溯：' + todo('结论与缺口'),
              '', '## 8. 治理发现及后续动作', '', '| CR-ID / 缺口 | 功能 / CHG / CASE / PATH | 根因与证据 | owner / 影响范围 | 下一步 | Ledger 记录 |', '| --- | --- | --- | --- | --- | --- |',
              *[('| %s | %s | %s | %s | %s | issue %s |' % (todo('CR-ID 或“不立案”'), cell(issue['applies_to']), issue['summary'], todo('owner / 影响范围'), todo('下一步'), iid))
                for iid, issue in debts(s)],
              '| ' + todo('稳定 CR-ID，或“无”') + ' | | | | | |', '']
    return '\n'.join(lines)


def debts(s):
    """The debts the implementers recorded (issue kind debt): the audit starts its governance from them."""
    return sorted((iid, issue) for iid, issue in s.get('issues', {}).items() if issue.get('kind') == 'debt')


def latest_implementation(m):
    refs = [(a.get('fencing_token', 0), m['submissions'][aid]['ref']) for aid, a in m.get('assignments', {}).items()
            if a.get('closed') and aid in m.get('submissions', {}) and m['submissions'][aid].get('kind') == 'implementation']
    try:
        return read_json(check_ref(max(refs)[1])) if refs else {}
    except (Rejected, OSError, ValueError):
        return {}


def code_review(s, inventory_ref):
    """The review report with every derived field in place; conclusions, reasons and diffs are the Auditor's."""
    import audit_code_review
    import run_changes
    plan = (s.get('global_plan') or {}).get('content', {})
    features = [row['feature_id'] for row in read_json(check_ref(plan['feature_inventory_ref']))['features']] if plan.get('feature_inventory_ref') else []
    tasks = lambda rid: [{'module_id': mid, 'task_id': t['task_id']} for mid, m in s['modules'].items()
                         for t in (m.get('plan') or {}).get('tasks', []) if rid in t.get('global_requirement_ids', t['requirement_ids'])]
    paths = lambda rid: sorted({pid for mid, m in s['modules'].items() for t in (m.get('plan') or {}).get('tasks', [])
                                if rid in t.get('global_requirement_ids', t['requirement_ids']) for pid in t['path_ids']}
                               | {p['path_id'] for p in s.get('global_paths', []) if rid in p.get('requirement_ids', [p.get('requirement_id')])})
    origin = s.get('host_task_contract', {}).get('global_spec') or next(iter(s.get('run_change_history', [])), {}).get('previous_global_spec', s['global_spec'])
    return {'schema_version': 1, 'run_id': s['run_id'], 'auditor_instance_id': todo('independent auditor instance'),
            'snapshot': audit_code_review.snapshot(s), 'change_inventory_ref': inventory_ref,
            'modules': [{'module_id': mid, 'diff_refs': [todo('{path, sha256} of the before/after evidence')],
                         'checks': {name: {'conclusion': todo('satisfied|finding|not-applicable'), 'reason': todo('what was compared'),
                                           'evidence_refs': [inventory_ref]} for name in audit_code_review.CHECKS}}
                        for mid in s['modules'] if mid not in audit_code_review.carried(s)],  # after a repair: what it changed
            'findings': [], 'recovery_resolutions': [], 'debts': [iid for iid, _ in debts(s)],
            'goal_review': {'global_spec_ref': s['global_spec'], 'origin_spec_ref': origin, 'feature_ids': features,
                            'requirements': [{'requirement_id': rid, 'conclusion': todo('satisfied|finding|blocked'), 'reason': todo('original goal against the delivered code and its verification'),
                                              'tasks': tasks(rid), 'path_ids': paths(rid), 'evidence_refs': [inventory_ref]} for rid in s['requirement_ids']],
                            'retirement_reviews': [{'kind': r['kind'], 'id': r['id'], 'revision_ref': r['revision_ref'], 'decision_id': r['decision_id'],
                                                    'conclusion': todo('confirmed|finding|blocked'), 'reason': todo('reason'), 'evidence_refs': [todo('{path, sha256}')]}
                                                   for r in run_changes.retirements(s)]}}


def write(root, out, module_id=None, assignment_id=None):
    import ledger
    root = Path(root).resolve()
    s = ledger.status(root)
    out = Path(out)
    require(out.is_absolute(), 'absolute output directory required')
    out.mkdir(parents=True, exist_ok=True)
    files = {}
    if module_id:
        m = s['modules'].get(module_id) or {}
        a = (m.get('assignments') or {}).get(assignment_id) or {}
        require(a.get('role') == 'test-runner' and not a.get('closed', True), 'an open Test-Runner assignment is needed')
        report = preflight(root, s, module_id, a)
        files['preflight-' + report['stage'] + '.json'] = dump(out, 'preflight-' + report['stage'] + '.json', report)
        static = next((p for p in m['plan']['paths'] if p.get('kind') == 'static' and p['path_id'] in a['execution_contract']['path_ids']), None)
        if static:
            files['static-review.json'] = dump(out, 'static-review.json', static_review(s, module_id, a, static))
    else:
        require(s.get('modules') and all((x.get('plan') or {}).get('paths') for x in s['modules'].values()), 'every module needs a frozen plan to be inventoried')
        files['audit-change-inventory.md'] = dump(out, 'audit-change-inventory.md', inventory(s, s.get('last_sequence')))
        files['audit-code-review.json'] = dump(out, 'audit-code-review.json', code_review(s, files['audit-change-inventory.md']))
    unfilled = sum((out / name).read_text().count(SKELETON_MARK) for name in files)
    return {'files': files, 'unfilled': unfilled,
            'next_action': 'write every marked part; a report, review or inventory that still holds a mark is refused'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--root', required=True); parser.add_argument('--out', required=True)
    parser.add_argument('--module'); parser.add_argument('--assignment'); parser.add_argument('--global', dest='whole', action='store_true')
    args = parser.parse_args(argv)
    try:
        require(args.whole != bool(args.module and args.assignment), '--module with --assignment, or --global')
        print(json.dumps(write(args.root, args.out, args.module, args.assignment), ensure_ascii=False, indent=2))
        return 0
    except (Rejected, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'rejected', 'reason': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
