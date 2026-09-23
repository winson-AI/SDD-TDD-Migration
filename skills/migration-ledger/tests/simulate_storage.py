"""Isolated Python lifecycle fixture, not a real mobile migration or host dispatcher.

Run with --output <new-directory>; retain the tree and content-hash manifests.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import test_context_readiness
import test_dimensions
import test_source_changes
import test_audit_scope
import ledger
import project_context as pc
import decomposition
from contracts import file_ref


def inventory(base):
    return {str(p.relative_to(base)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(base.rglob('*')) if p.is_file()}


def difference(before, after):
    return {'added': sorted(after.keys() - before.keys()), 'removed': sorted(before.keys() - after.keys()),
            'modified': sorted(k for k in before.keys() & after.keys() if before[k] != after[k])}


class ManagedFlow(test_context_readiness.ContextReadinessTests):
    run_id = 'demo'

    def raw(self, op, payload=None, role='module-orchestrator', module='M001', instance=None, request=None):
        if request is None:
            state = ledger.read_events(self.root)[0]
            if op == 'init': module = None
            revision = (state['modules'][module]['revision'] if module else state['revision']) if state else 0
            request = {'schema_version': 1, 'request_id': str(self.n + 1), 'run_id': self.run_id,
                       'module_id': module, 'expected_revision': revision, 'operation': op, 'payload': payload or {}}
        return super().raw(op, payload, role=role, module=module, instance=instance, request=request)

    def ref(self, name, content):
        path = self.root / 'staging/fixture-host' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content if isinstance(content, str) else json.dumps(content))
        return file_ref(path)


def plan_modules(f):
    fixture = test_source_changes.SourceChangeTests(); fixture.f = f
    d = test_dimensions.DimensionTests(); d.f = f; fixture.d = d
    analysis = d.analysis(); d.root_ref = f.ref('root-dimensions.json', analysis)
    f.call('register', {'module_id': 'M010', 'case_ids': ['C1'], 'write_paths': [str(f.target)],
        'scope': analysis['scope'], 'context_refs': [f.ref('root-context.md', 'Parent scope')],
        'dimension_analysis_ref': d.root_ref, 'decomposition_required': True}, role='global-orchestrator', module=None)
    f.split(d.proposal(ids=('M001', 'M002'))); f.global_plan()
    fixture.freeze('M001'); fixture.freeze('M002')
    f.state()  # Host refreshes current routing after the last accepted freeze.
    return fixture


def simulate(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    workspace = output / 'workspace'; workspace.mkdir()
    f = ManagedFlow(); f.base = workspace; f.n = 0; f.auto_context = True
    f.legacy = output / 'legacy'; f.legacy.mkdir()
    f.target = output / 'target'; f.target.mkdir()
    f.root = workspace / '.sdd-runs/demo'
    context = workspace / '.sdd-migration'
    source = context / 'inputs/user.md'; source.parent.mkdir(parents=True)
    source.write_text('Fixture user: migrate R1 and approve the generated fixture scope.')
    arch = context / 'inputs/architecture.md'; arch.write_text('Python fixture architecture v1')
    actor = {'role': 'host', 'instance_id': 'host'}
    config = {'legacy_root': str(f.legacy), 'target_root': str(f.target), 'architecture_path': str(arch)}
    pc.update(context, {'schema_version': 1, 'project_id': 'demo-project', 'request_id': 'config',
        'expected_revision': 0, 'patch': config, 'source_ref': file_ref(source)}, actor, True)
    request = {'schema_version': 1, 'project_id': 'demo-project', 'request_id': 'prepare-demo',
               'run_id': 'demo', 'source_ref': file_ref(source)}
    prepared = pc.prepare(context, None, request, actor)
    checkpoints = {'prepared': inventory(workspace)}
    spec_ref = f.ref('global-spec.md', 'R1: observable result must equal 2')
    (f.root / 'input.json').write_text(json.dumps({**prepared['input'], 'global_spec': spec_ref,
        'requirement_ids': ['R1'], 'global_test_cases': [{'case_id': 'C1', 'name': 'result equals 2'}]}, indent=2))
    f.call('init', {'target_root': str(f.target), 'legacy_root': str(f.legacy),
        'new_architecture': prepared['input']['new_architecture'], 'project_context_ref': prepared['project_context_ref'],
        'case_ids': ['C1'], 'requirement_ids': ['R1'], 'global_paths': [],
        'global_spec': spec_ref}, role='host')
    fixture = plan_modules(f)
    checkpoints['frozen'] = inventory(workspace)
    fixture.implement_and_test('M001', value=9)
    f.call('diagnose', {'diagnosis_ref': f.ref('diagnosis.md', 'Wrong fixture calculation'),
        'owner': 'fixer', 'root_cause': 'code'}, role='diagnostician')
    f.call('diagnosis-accept')
    fixture.implement_and_test('M001', role='fixer')
    fixture.implement_and_test('M002')
    s = f.state()
    ledger.apply(f.root, {'schema_version': 1, 'run_id': 'demo', 'request_id': 'parent-summary',
        'module_id': 'M010', 'expected_revision': s['module_groups']['M010']['revision'], 'operation': 'module-summary',
        'payload': {'summary_ref': f.ref('parent-summary.md', 'Both leaves completed and evidence reviewed'),
                    'subject_sha256': decomposition.summary_subject(s, s['module_groups']['M010'])}},
        {'role': 'module-orchestrator', 'instance_id': 'parent-mo-M010'})
    report = test_audit_scope.AuditScopeTests().review(f)
    f.raw('audit', {'report_ref': f.ref('audit.json', report)}, role='auditor', module=None)
    finished = f.state()
    assert finished['quality'] == 'green-passed'
    assert finished['modules']['M001']['fix_memory'][0]['reusable']
    checkpoints['completed'] = inventory(workspace)
    old_sequence = finished['last_sequence']
    retry = pc.prepare(context, None, request, actor)
    restored = ledger.status(retry['run_root'])
    assert retry['duplicate'] and restored['last_sequence'] == old_sequence
    checkpoints['same_run_restart'] = inventory(workspace)
    # Explicit new user input updates only project configuration and the next run.
    arch.write_text('Python fixture architecture v2')
    source.write_text('Fixture user: use revised architecture for a new migration.')
    pc.update(context, {'schema_version': 1, 'project_id': 'demo-project', 'request_id': 'update',
        'expected_revision': 1, 'patch': {'human_owner': 'fixture-owner'}, 'source_ref': file_ref(source)}, actor)
    next_request = {**request, 'run_id': 'demo-next', 'request_id': 'prepare-demo-next', 'source_ref': file_ref(source)}
    second = pc.prepare(context, None, next_request, actor)
    next_root = Path(second['run_root'])
    spec = next_root / 'staging/go/global-spec.md'; spec.parent.mkdir(parents=True); spec.write_text('Next run R1')
    (next_root / 'input.json').write_text(json.dumps({**second['input'], 'global_spec': file_ref(spec),
        'requirement_ids': ['R1'], 'global_test_cases': [{'case_id': 'C1', 'name': 'result equals 2'}]}, indent=2))
    ledger.apply(next_root, {'schema_version': 1, 'run_id': 'demo-next', 'request_id': 'init',
        'module_id': None, 'expected_revision': 0, 'operation': 'init', 'payload': {
            'target_root': str(f.target), 'legacy_root': str(f.legacy), 'global_spec': file_ref(spec),
            'new_architecture': second['input']['new_architecture'], 'project_context_ref': second['project_context_ref'],
            'case_ids': ['C1'], 'requirement_ids': ['R1'], 'global_paths': []}}, actor)
    ledger.status(next_root)
    f.root = next_root; f.run_id = 'demo-next'
    plan_modules(f)
    checkpoints['new_run_started'] = inventory(workspace)
    diffs = {name: difference(checkpoints[a], checkpoints[b]) for name, a, b in [
        ('prepare_to_freeze', 'prepared', 'frozen'), ('freeze_to_complete', 'frozen', 'completed'),
        ('same_run_restart', 'completed', 'same_run_restart'), ('new_run_start', 'same_run_restart', 'new_run_started')]}
    protected = ('.sdd-runs/demo/', 'openspec/changes/demo-', 'openspec/runs/demo/')
    assert not any(p.startswith(protected) for p in diffs['new_run_start']['modified'] + diffs['new_run_start']['removed'])
    summary = {'fixture': 'Python, two leaf MOs, one Red/Fixer/regression, independent Auditor review',
        'workspace': str(workspace), 'first_run_quality': finished['quality'], 'first_run_sequence': old_sequence,
        'second_run_stage': 'GO/parent/leaf planning accepted; two leaves frozen; no code/test yet', 'changes': diffs,
        'manifests': {k: len(v) for k, v in checkpoints.items()}}
    evidence = output / 'evidence'; evidence.mkdir()
    for name, snapshot in checkpoints.items():
        (evidence / (name + '.json')).write_text(json.dumps(snapshot, indent=2))
    (evidence / 'summary.json').write_text(json.dumps(summary, indent=2))
    (evidence / 'completed-files.txt').write_text('\n'.join(checkpoints['completed']) + '\n')
    (evidence / 'second-start-files.txt').write_text('\n'.join(checkpoints['new_run_started']) + '\n')
    lines = ['# 留存文件系统模拟结果', '',
        '隔离 Python 夹具：两个叶子 MO、一次 Red→Fixer→复测、父 MO 汇总、独立 Auditor 收尾。', '',
        f'首轮：{finished["quality"]}，Ledger sequence={old_sequence}。第二轮仅完成规划/冻结，没有沿用旧 Green。', '',
        '| 阶段 | 新增 | 修改 | 删除 |', '| --- | ---: | ---: | ---: |']
    for name, delta in diffs.items():
        lines.append(f'| {name} | {len(delta["added"])} | {len(delta["modified"])} | {len(delta["removed"])} |')
    lines += ['', '[首轮完整文件清单](completed-files.txt) · [二次启动后完整文件清单](second-start-files.txt) · [逐文件增删改](summary.json)', '',
        '[首轮 OpenSpec 中枢](../workspace/openspec/runs/demo/workflow.md) · [第二轮 OpenSpec 中枢](../workspace/openspec/runs/demo-next/workflow.md)', '',
        '首次运行内容 hash 见 completed.json；恢复后见 same_run_restart.json；新 run 规划后见 new_run_started.json。', '',
        '修改仅涉及本次主动更新的输入 architecture.md、user.md 及 project-context.json；首轮运行与 OpenSpec 文件未被覆盖。', '',
        '未使用真实业务 Gradle、移动设备、LLM 或宿主 subagent；测试中的角色身份与审批为受控夹具。', '']
    (evidence / 'report.md').write_text('\n'.join(lines))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--output', required=True)
    print(json.dumps(simulate(parser.parse_args().output), indent=2))
