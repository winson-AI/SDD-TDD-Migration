"""Skeletons of a leaf's plan set, written from the allocation the Ledger accepted: the four OpenSpec documents, the
stage plan, the upstream test plan with its design note and, where the run reuses, the reuse plan with its alignment note.

A Spec-Designer starts from the leaf's four-dimension specification, not from an empty template and not from a script of
its own: scope, requirements, cases, every allocated item, one task per feature the leaf holds, one behaviour path per
case, a unit path per Logic item, the build and static paths and the trace from items to tasks and paths are in place;
each part only its author can write is marked. A plan, or a file it cites, that still holds a mark is refused, so a
skeleton is never frozen as a specification. After editing, `contracts.py refs <directory>` gives every file's reference.

  spec_skeleton.py --root <run_root> --module <id> --out <absolute directory in the role's staging>
"""
import argparse
import json
import re
import sys
from pathlib import Path

from contracts import SKELETON_MARK, Rejected, check_ref, file_ref, read_json, require


def todo(what):
    return f'{SKELETON_MARK}：{what}]]'


def documents(s, m):
    """{file name: text} for one leaf: proposal, spec, design and tasks."""
    import dimensions
    mid = m['module_id']
    analysis, items = dimensions.load(m['dimension_analysis_ref'], mid)
    scope = m.get('scope') or {}
    requirements = list(scope.get('requirement_ids') or sorted({rid for item in items.values() for rid in item['requirement_ids']}))
    listed = lambda values: ''.join(f'- {value}\n' for value in values) or '- none\n'
    ids = lambda rows: '、'.join(f'`{iid}`' for iid in rows) or '—'
    ref = lambda value: f"{value['path']} · sha256={value['sha256']}" if isinstance(value, dict) and value.get('path') else '—'
    proposal = (f"# {mid} {(scope.get('in') or [mid])[0]}\n\n## Why\n{todo('业务目标、迁移原因、可观察收益')}\n\n"
                f"## What Changes\n{listed(scope.get('in') or [])}\n不在范围：沿用分配包 scope.out（{len(scope.get('out') or [])} 条），不复写。\n\n"
                f"## Capabilities\n{todo('新增或修改的 capability；没有则写 none')}\n\n"
                f"## Impact\n{todo('旧架构到新架构的影响、上下游契约、数据迁移、安全与性能约束')}\n\n"
                f"## References\n- run_id: {s.get('run_id')}\n- module_id: {mid}\n- global_spec_ref: {ref(s.get('global_spec'))}\n"
                f"- dimension_analysis_ref: {ref(m['dimension_analysis_ref'])}\n- cases: {'、'.join(m.get('case_ids', []))}\n")
    dimensions_text = ''
    for row in analysis.get('dimensions', []):
        dimensions_text += f"### {row['dimension']}（{row.get('status')}：{row.get('reason', '')}）\n"
        for item in row.get('items') or [] if row.get('status') == 'applicable' else []:
            dimensions_text += (f"- `{item['item_id']}`：{item['behavior']}；验收：{item['acceptance']}；CASE：{'、'.join(item['case_ids'])}\n"
                                f"  - {todo('实现要点与接线')}\n")
        dimensions_text += '\n'
    design = (f"# {mid} Design\n\n## Context\n{todo('全局规范、架构、legacy 基线与相关模块接口')}\n\n"
              f"## Goals / Non-Goals\n范围内：\n{listed(scope.get('in') or [])}\n范围外：沿用分配包 scope.out（{len(scope.get('out') or [])} 条），不复写。\n\n"
              f"## Legacy → Target Mapping\n源定位、行为、目标绑定与策略见 dimension_analysis_ref（{len(items)} 个 item），引用为 `path#symbol`/`path:line`，不抄源码。\n\n"
              f"## UI → Logic → Adhesive → Resource\n{dimensions_text}"
              f"## Test Design\n{todo('正常、边界、异常路径与允许 Mock 的外部边界')}\n\n"
              f"## Risks / Rollback\n{todo('风险、回滚条件与操作')}\n")
    spec, number = '## ADDED Requirements\n', 0
    for rid in requirements:
        owned = {iid: item for iid, item in items.items() if rid in item['requirement_ids']}
        spec += (f"\n### Requirement: {todo('需求名称')}\nRequirement-ID: {rid}\n{rid}: The system SHALL {todo('可观察的行为及边界')}.\n"
                 f"Items: {ids(owned)}\n")
        for cid in sorted({cid for item in owned.values() for cid in item['case_ids']}) or ['']:
            number += 1
            spec += (f"\n#### Scenario: {todo('场景名称')}\nScenario-ID: SCN-{mid}-{number:03d}\n" + (f"CASE: {cid}\n" if cid else '') +
                     f"- **GIVEN** {todo('前置条件')}\n- **WHEN** {todo('触发行为')}\n- **THEN** {todo('可断言结果')}\n")
    tasks = (f"# {mid} Tasks\n\n## Implementation\n- [ ] TASK-{mid}-001 {todo('可执行任务名称；按需拆成多个 TASK')}\n"
             f"  - Requirements: {'、'.join(requirements)}\n  - Cases / Paths: {'、'.join(m.get('case_ids', []))} / {todo('PATH-ID')}\n"
             f"  - Items: {ids(items)}\n  - Write scope: {'、'.join(m.get('write_paths', []))}\n"
             f"  - Action: {todo('具体改动')}\n  - Done when: {todo('可核验结果')}\n\n"
             "## Traceability\n| REQ-ID | TASK-ID | CASE-ID | Item |\n| --- | --- | --- | --- |\n" +
             ''.join(f"| {rid} | TASK-{mid}-001 | {'、'.join(sorted({cid for item in items.values() if rid in item['requirement_ids'] for cid in item['case_ids']}))} | "
                     f"{ids({iid: item for iid, item in items.items() if rid in item['requirement_ids']})} |\n" for rid in requirements))
    return {'proposal.md': proposal, 'spec.md': spec, 'design.md': design, 'tasks.md': tasks}


def plans(s, m, out, documents):
    """{file name: JSON or text} for the leaf's plan set, citing the documents already written under `out`: the stage plan
    (definitions, tasks, trace, test and reuse plan references), the upstream test plan with its design note and, when the
    run reuses, the reuse plan with its alignment note. The Ledger completes the rest of a plan from the analysis."""
    import dimensions
    import design_stage
    import decomposition
    mid = m['module_id']
    analysis, items = dimensions.load(m['dimension_analysis_ref'], mid)
    cases = list(m.get('case_ids') or [])
    scope = m.get('scope') or {}
    requirements = list(scope.get('requirement_ids') or sorted({rid for item in items.values() for rid in item['requirement_ids']}))
    holders = {cid: [iid for iid, item in items.items() if cid in item['case_ids']] for cid in cases}
    requirement_of = lambda cid: next((rid for iid in holders[cid] for rid in items[iid]['requirement_ids']), requirements[0] if requirements else todo('REQ-ID'))
    # one task per feature the leaf holds; the cases no feature holds, or every case when there is no inventory, make one more
    features = []
    allocation = decomposition.assigned_module(s, m)
    if allocation.get('feature_inventory_ref'):
        try:
            held = set(allocation.get('feature_ids') or [])
            features = [f for f in read_json(check_ref(allocation['feature_inventory_ref'])).get('features') or []
                        if (f.get('feature_id') in held if held else set(f.get('case_ids') or []) & set(cases))]
        except (Rejected, OSError, KeyError, TypeError):
            features = []
    groups = [(f.get('name') or f['feature_id'], [c for c in cases if c in set(f.get('case_ids') or [])]) for f in features]
    groups = [g for g in groups if g[1]]
    rest = [c for c in cases if not any(c in g[1] for g in groups)]
    if rest or not groups:
        groups.append((todo('任务名称：按行为切，每个任务有自己可跑的 PATH'), rest or cases))
    path_of = {cid: f'PATH-{mid}-{n:03d}' for n, cid in enumerate(cases, 1)}
    logic = [iid for iid, item in items.items() if item['dimension'] == 'Logic']
    unit_of = {iid: f'UNIT-{mid}-{n:03d}' for n, iid in enumerate(logic, 1)}
    build, static = f'BUILD-{mid}-001', (f'STATIC-{mid}-001' if s.get('spec_closure_required') else None)
    first = cases[0] if cases else None

    def path(pid, kind, cid, name, expected=None, **extra):
        return {'path_id': pid, 'kind': kind, 'name': name, 'case_id': cid, 'requirement_id': requirement_of(cid) if cid else requirements[0],
                'required': True, 'preconditions': [todo('源码定义的前置状态')], 'steps': [todo('源码定义的动作')], 'parameters': {},
                'dependency_refs': [], 'priority': 'P0', 'scope': 'module',
                'expected_assertions': [{'assertion_id': 'ASSERT-' + pid, 'expected': todo('上游预期') if expected is None else expected, 'scenario_ids': []}],
                'preparation': {'status': 'existing', 'reason': todo('已批准的测试方式'), 'evidence_refs': [], 'asset_ids': []}, **extra}
    paths = [path(build, 'build', first, todo('构建命令名'), expected=0,
                  command={'argv': [todo('绝对 argv')], 'cwd': s.get('target_root'), 'timeout_seconds': 600, 'selection_ref': todo('选择依据引用')})]
    if static:
        paths.append(path(static, 'static', first, '静态规格闭合审查', expected=True))
    sources, test_assets = {}, []
    for iid in logic:  # one frozen test source per Logic item: written from the SPEC, delivered verbatim, required by its unit PATH
        pid = unit_of[iid]
        cls = ''.join(part.capitalize() for part in re.split(r'[^A-Za-z0-9]+', iid) if part) + 'Test'
        held = items[iid]['case_ids'] or ([first] if first else [])
        methods = [('case_' + re.sub(r'[^A-Za-z0-9]+', '_', cid).strip('_').lower(), cid) for cid in held] or [('scenario_001', None)]
        ids = [f'{cls}#{name}' for name, _ in methods]
        name = f'test-sources/{cls}.' + language(s)
        sources[name] = test_source(cls, pid, iid, methods)
        test_assets.append({'asset_id': 'TEST-' + pid, 'kind': 'test-source', 'ref': name, 'path_ids': [pid],
                            'target_path': todo('目标测试源集中的绝对路径'), 'required_test_ids': ids,
                            'scenarios': [{'scenario_id': todo('Scenario-ID'), 'test_id': tid} for tid in ids],
                            'symbols': [todo('测试调用的生产符号')]})
        paths.append(path(pid, 'unit', held[0] if held else first, todo(f'{iid} 的单测名'), expected=True,
                          command={'argv': [todo('绝对 argv')], 'cwd': s.get('target_root'), 'timeout_seconds': 600, 'selection_ref': todo('选择依据引用')},
                          unit_report={'format': 'junit', 'patterns': [todo('runner 相对的 JUnit 报告 glob')], 'required_test_ids': ids},
                          preparation={'status': 'prepared', 'reason': '从 SPEC 写出并随计划冻结的测试源', 'evidence_refs': [], 'asset_ids': ['TEST-' + pid]}))
    paths += [path(path_of[cid], 'automation', cid, todo(f'{cid} 的上游用例路径名')) for cid in cases]
    tasks = []
    for n, (name, held) in enumerate(groups, 1):
        reqs = sorted({rid for cid in held for iid in holders[cid] for rid in items[iid]['requirement_ids']}) or requirements
        units = [unit_of[iid] for iid in logic if set(items[iid]['case_ids']) & set(held)]
        tasks.append({'task_id': f'TASK-{mid}-{n:03d}', 'scope': {'in': [name], 'out': list(scope.get('out') or []), 'write_paths': list(m.get('write_paths') or [])},
                      'requirement_ids': reqs, 'path_ids': [build] + ([static] if static else []) + units + [path_of[cid] for cid in held]})
    trace = []
    for iid, item in items.items():
        owned = [t['task_id'] for t in tasks if set(item['case_ids']) & {c for c in cases if path_of[c] in t['path_ids']}] or [tasks[0]['task_id']]
        pids = [path_of[cid] for cid in item['case_ids'] if cid in path_of] + ([unit_of[iid]] if iid in unit_of else [])
        trace.append({'item_id': iid, 'task_ids': owned, 'path_ids': pids, 'assertions': [{'path_id': pid, 'assertion_id': 'ASSERT-' + pid} for pid in pids]})
    test_note = (f"# {mid} 测试计划\n\n上游用例：{'、'.join(cases)}\n\n" + ''.join(f"- {p['path_id']}（{p['kind']}）：{p['name']}；CASE {p['case_id']}\n" for p in paths)
                 + f"\n{todo('每条路径的前置、步骤、断言与准备方式')}\n")
    upstream = {'schema_version': 1, 'kind': 'upstream-test-plan', 'module_id': mid, 'subject_sha256': design_stage.subject(s, m),
                'case_refs': design_stage.upstream_refs(s), 'design_ref': None, 'paths': paths, 'test_assets': test_assets}
    plan = {'schema_version': 1, 'module_id': mid,
            'definitions': [{'kind': kind, **documents[kind + '.md']} for kind in ('proposal', 'spec', 'design', 'tasks')],
            'test_design_ref': None, 'tasks': tasks, 'dimension_trace': trace}
    out_files = {'test-plan.md': test_note, 'upstream-test-plan.json': upstream, 'stage-plan.json': plan, **sources}
    if m.get('parent_module_id') or s.get('reuse_required'):
        catalog = None
        for ref in m.get('context_refs') or []:
            try:
                if isinstance(read_json(check_ref(ref)), dict) and 'capabilities' in read_json(check_ref(ref)):
                    catalog = ref
            except (Rejected, OSError, ValueError, TypeError):
                continue
        mappings = [{'mapping_id': f'REUSE-{mid}-{n:03d}', 'requirement_ids': [rid], 'capability_id': todo('能力 ID；new 时为 null'),
                     'decision': todo('reuse / adapt / reference / new'), 'rationale': todo('语义匹配与选择理由'), 'behavior_delta': todo('匹配点、缺口与适配'),
                     'binding_plan': todo('生产入口、DI、适配器与消费者'), 'task_ids': [t['task_id'] for t in tasks if rid in t['requirement_ids']] or [tasks[0]['task_id']],
                     'path_ids': [path_of[cid] for cid in cases if requirement_of(cid) == rid] or [path_of[first]] if first else [],
                     'verification': todo('业务契约、边界、错误与真实提供方断言'),
                     'fidelity': {'legacy_root': s.get('legacy_root'), 'legacy_source_refs': [], 'alignment_ref': None, 'scenarios': []},
                     'integration': {'mode': todo('existing-target / package / source-module / reference-only'), 'locator': todo('目标模块、API 或包坐标'), 'version': todo('解析版本')}}
                    for n, rid in enumerate(requirements, 1)]
        out_files['reuse-fidelity.md'] = f"# {mid} 复用与存量功能保真对齐\n\n{todo('逐行为对齐：场景、源码定位、前置/输入、存量预期、提供方语义、差异与 PATH/ASSERT')}\n"
        out_files['reuse-plan.json'] = {'schema_version': 1, 'module_id': mid, 'catalog_ref': catalog or todo('能力目录引用'), 'mappings': mappings}
    return out_files


def language(s):
    """The test language the skeleton is written in: Kotlin when the target holds Kotlin sources, else a neutral text."""
    target = Path(s.get('target_root') or '')
    return 'kt' if target.is_dir() and next(target.rglob('*.kt'), None) else 'txt'


def test_source(cls, pid, iid, methods):
    """A test class from the SPEC: one test per case the Logic item holds, Given / When / Then left to the author."""
    body = ''.join(f"    // CASE {cid or todo('CASE')}\n    @Test\n    fun {name}() {{\n        // Given {todo('前置状态（Scenario-ID）')}\n"
                   f"        // When {todo('调用冻结的生产符号')}\n        // Then {todo('断言上游预期')}\n        TODO(\"{todo('实现断言后删除')}\")\n    }}\n\n"
                   for name, cid in methods)
    return (f"import kotlin.test.Test\n\n// {pid} · {iid}：从 SPEC 写出、随计划冻结；Implementer 原样落到 target_path，不改动\n"
            f"class {cls} {{\n{body}}}\n")


def write(root, module_id, out):
    import ledger
    s, _ = ledger.read_events(root)
    m = (s or {}).get('modules', {}).get(module_id)
    require(m and m.get('dimension_analysis_ref') and not m.get('decomposition_required'),
            'skeletons are written for a leaf that has its four-dimension analysis')
    out = Path(out)
    require(out.is_absolute(), 'absolute output directory required')
    texts = documents(s, m)
    require(not any((out / name).exists() for name in texts), 'refusing to overwrite documents in ' + str(out))
    out.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, text in texts.items():
        (out / name).write_text(text)
        files[name] = file_ref(out / name)
    rest = plans(s, m, out, files)
    require(not any((out / name).exists() for name in rest), 'refusing to overwrite plan files in ' + str(out))
    for name in ('test-plan.md', 'reuse-fidelity.md', *[n for n in rest if n.startswith('test-sources/')]):  # the notes and sources first: the JSON files cite them
        if name in rest:
            (out / name).parent.mkdir(parents=True, exist_ok=True)
            (out / name).write_text(rest[name]); files[name] = file_ref(out / name)
    for asset in rest['upstream-test-plan.json']['test_assets']:
        asset['ref'] = files[asset['ref']]
    rest['upstream-test-plan.json']['design_ref'] = files['test-plan.md']
    if 'reuse-plan.json' in rest:
        for row in rest['reuse-plan.json']['mappings']:
            row['fidelity']['alignment_ref'] = files['reuse-fidelity.md']
    (out / 'upstream-test-plan.json').write_text(json.dumps(rest['upstream-test-plan.json'], ensure_ascii=False, indent=2) + '\n')
    files['upstream-test-plan.json'] = file_ref(out / 'upstream-test-plan.json')
    rest['stage-plan.json']['test_design_ref'] = files['upstream-test-plan.json']
    if 'reuse-plan.json' in rest:
        (out / 'reuse-plan.json').write_text(json.dumps(rest['reuse-plan.json'], ensure_ascii=False, indent=2) + '\n')
        files['reuse-plan.json'] = file_ref(out / 'reuse-plan.json')
        rest['stage-plan.json']['reuse_plan_ref'] = files['reuse-plan.json']
    (out / 'stage-plan.json').write_text(json.dumps(rest['stage-plan.json'], ensure_ascii=False, indent=2) + '\n')
    files['stage-plan.json'] = file_ref(out / 'stage-plan.json')
    unfilled = sum((out / name).read_text().count(SKELETON_MARK) for name in files)
    return {'module_id': module_id, 'files': files, 'unfilled': unfilled,
            'next_action': 'write every marked part, then `contracts.py refs ' + str(out) + '` for the references the plan cites; '
                           'a plan, or a file it cites, that still holds a mark is refused'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--root', required=True); parser.add_argument('--module', required=True); parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(write(args.root, args.module, args.out), ensure_ascii=False, indent=2))
        return 0
    except (Rejected, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'rejected', 'reason': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
