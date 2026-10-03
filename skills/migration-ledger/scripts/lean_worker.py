#!/usr/bin/env python3
"""Managed, role-limited deterministic domain tools. Host authenticates the supplied principal.

This entry creates staged evidence, never Ledger events, acceptance, a new approval or a retry loop.
It is not an OS sandbox: host ACLs and process fencing remain mandatory for real workers.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
sys.dont_write_bytecode = True
from types import SimpleNamespace

from contracts import Rejected, baseline, check_ref, file_ref, read_json, require, verify_plan
import lean_adapter
import lean_knowledge
import ledger
import project_context
import run_storage
import runner_storage
import ui_evidence
import parameter_file
import resource_copy
import resource_fidelity
import ui_parameters
import reference_render
from lean_tools import collect_ui_sources, resource_tool, select_runtime_ui, ui_visual_score

ROLES = {
    'analyze-ui': {'global-orchestrator', 'module-orchestrator', 'spec-designer'},
    'validate-ui': {'spec-designer', 'test-runner', 'auditor'},
    'resource-convert': {'implementer', 'fixer'},
    'resource-plan': {'module-orchestrator', 'spec-designer'},
    'screen-checks': {'module-orchestrator', 'spec-designer'},
    'resource-sync': {'implementer', 'fixer'},
    'resource-scan': {'global-orchestrator', 'module-orchestrator', 'spec-designer', 'implementer',
                      'fixer', 'test-runner', 'auditor'},
    'compare-only': {'test-runner', 'auditor'},
    'render-reference': {'spec-designer', 'test-runner', 'auditor'},
    'image-parity': {'test-runner', 'auditor'},
    'visual-install': {'test-runner', 'auditor'},
    'visual-capture': {'test-runner', 'auditor'},
    'semantic-inspect': {'test-runner', 'auditor'},
    'import-evidence': {'spec-designer', 'implementer', 'fixer', 'test-runner', 'auditor'},
    'knowledge-query': {'global-orchestrator', 'module-orchestrator', 'spec-designer', 'implementer',
                        'fixer', 'diagnostician', 'test-runner', 'auditor', 'escalation'},
    'knowledge-diagnose': {'implementer', 'diagnostician', 'fixer', 'test-runner', 'auditor'},
    'foundation-resolve': {'global-orchestrator', 'module-orchestrator', 'spec-designer'},
    'foundation-verify': {'implementer', 'fixer', 'test-runner', 'auditor'},
}


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', value), 'safe actor/request id required')
    return value


def layout_helpers(value):
    """A project's own layout-parameter builders: the call and what each argument is, one entry per arity."""
    require(isinstance(value, list) and all(isinstance(row, dict) and isinstance(row.get('call'), str) and row['call']
            and isinstance(row.get('params'), list) and row['params'] and all(isinstance(name, str) and name for name in row['params'])
            and row.get('unit') in (None, 'dp', 'sp', 'px') for row in value),
            'layout_helpers rows need a call, the parameter each argument gives, and optionally the unit of a bare number')
    return value


def save(path, value):
    run_storage.atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode())
    return file_ref(path)


def assignment(state, request, actor):
    mid = request.get('module_id')
    if mid == 'GLOBAL':
        module = ledger.audit_scope(state)
        task = state.get('audit_assignment', {})
        require(task.get('mode') != 'problem' and task.get('scope_policy') == 'non-green-only'
                and task.get('snapshot') == {k: v['code_baseline'] for k, v in state['modules'].items()},
                'current global audit snapshot required')
        # Ephemeral read context only: build ownership does not imply UI baseline ownership.
        # GLOBAL-only paths keep their own explicit baseline; leaf paths retain their SPEC.
        selected = {path['path_id'] for path in module['plan']['paths']}
        module['path_dimension_analysis_refs'] = {
            path['path_id']: owner['plan']['dimension_analysis_ref']
            for owner in state['modules'].values()
            if owner.get('plan', {}).get('dimension_analysis_ref')
            for path in owner['plan']['paths'] if path['path_id'] in selected}
    else:
        require(mid in state.get('modules', {}), 'registered leaf module required')
        module = state['modules'][mid]
        if (state.get('audit_assignment', {}).get('mode') == 'problem'
                and state['audit_assignment'].get('assignment_id') == request.get('assignment_id')):
            import workflow
            task = workflow.problem_assignment(state, mid)
            require(workflow.runnable(state, mid), 'problem path unavailable; record Yellow')
        else:
            task = module.get('assignments', {}).get(request.get('assignment_id'), {})
    require(task and not task.get('closed', True) and task.get('assignment_id') == request.get('assignment_id'),
            'active assignment required')
    require(task.get('role') == actor['role'] and task.get('instance_id') == actor['instance_id'], 'assignment owner mismatch')
    require(task.get('fencing_token') == request.get('fencing_token'), 'stale fencing token')
    require(task.get('freeze_id') == module.get('freeze_id') or mid == 'GLOBAL' or task.get('mode') == 'problem',
            'assignment freeze changed')
    verify_plan(module['plan'], module)
    if actor['role'] in ('test-runner', 'auditor'):
        require(baseline(module['code_files']) == module['code_baseline'], 'current code changed')
    return module, task


def run(root, request, actor):
    root = Path(root).resolve()
    require(root.parent.name == '.sdd-runs', 'managed .sdd-runs/<run_id> required')
    state, _ = ledger.read_events(root) if (root / 'ledger/events.jsonl').exists() else (None, [])
    context_ref = state.get('project_context_ref') if state else None
    snapshot = project_context.verify_snapshot(context_ref or file_ref(root / 'context/snapshot.json'))
    require(snapshot['run_root'] == str(root), 'snapshot belongs to another run')
    operation = request.get('operation')
    require(operation in ROLES and actor.get('role') in ROLES[operation], 'operation outside role capability')
    rid, aid = identifier(request.get('request_id')), identifier(actor.get('instance_id'))
    config = snapshot['effective_config']
    args = request.get('args', {})
    require(isinstance(args, dict), 'args must be an object')
    module = task = None
    visual_operations = ('visual-install', 'visual-capture', 'semantic-inspect')
    if operation in ('resource-convert', 'resource-sync', 'compare-only', 'image-parity') + visual_operations:
        require(state, 'Ledger initialization required before execution')
        module, task = assignment(state, request, actor)
        if operation in ('resource-convert', 'resource-sync'):
            require(module['phase'] in ('implementing', 'fixing'), 'code generation phase required')
        else:
            scopes = ('automation', 'visual') if operation == 'visual-install' else ('visual',)
            require(task['role'] == 'auditor' or task.get('test_scope') in scopes, 'visual testing assignment required')
            if task['role'] == 'test-runner':
                import test_validation
                require(module.get('phase') == 'testing', 'test execution phase required')
                if operation == 'visual-install':
                    require(test_validation.build_ready(module), 'build must pass before installation')
                else:
                    require(test_validation.functional_ready(module), 'functional layer must pass before visual comparison')
    area = 'runs/harmony/sandbox' if operation in ('compare-only', 'image-parity') + visual_operations else 'staging'
    out = run_storage.checked_path(root / area / aid / rid, root / area)
    require(not out.exists(), 'worker output must be a new attempt; preserve prior evidence')
    out.mkdir(parents=True)
    request_ref = save(out / 'request.json', request)
    started = datetime.now(timezone.utc).isoformat()
    receipt = {'schema_version': 1, 'producer': 'lean-worker', 'run_id': snapshot['run_id'],
               'operation': operation, 'actor': actor, 'module_id': request.get('module_id'),
               'assignment_id': request.get('assignment_id'), 'request_ref': request_ref, 'started_at': started,
               'tools_ref': file_ref(Path(__file__).parent / 'lean_tools/UPSTREAM.json')}
    try:
        with runner_storage.scope(out):
            if operation == 'analyze-ui':
                require(args.get('entry') or args.get('source_files') or args.get('layouts'), 'source entry required')
                result = collect_ui_sources.collect(SimpleNamespace(android_root=config['legacy_root'],
                    scope=args.get('scope') or request.get('module_id') or rid, entry=args.get('entry', []),
                    source_file=args.get('source_files', []), layout=args.get('layouts', []),
                    manifest=args.get('manifests', []), image_sinks=args.get('image_sinks', []),
                    layout_helpers=layout_helpers(args.get('layout_helpers', []))))
                result = {'source_index_ref': save(out / 'ui-source-index.json', result)}
                if args.get('capture_ref'):
                    capture = check_ref(args['capture_ref'])
                    runtime = select_runtime_ui.select(capture, args.get('targets', []))
                    result['runtime_index_ref'] = save(out / 'runtime-ui-index.json', runtime)
            elif operation == 'validate-ui':
                ui_evidence.validate_tree_ref(args.get('ui_tree_ref'),
                    source_index_ref=args.get('source_index_ref'), runtime_index_ref=args.get('runtime_index_ref'),
                    resource_scope=args.get('resource_scope'))
                result = {'status': 'source-contract-valid', **args}
            elif operation == 'resource-convert':
                require(args.get('consumer') and args.get('source_id') and args.get('target_ref'), 'resource consumer mapping required')
                require(isinstance(args['consumer'], list) and all(isinstance(c, str) and c.strip() for c in args['consumer']),
                        'resource consumer must be a nonempty list of strings')
                require(len(args['consumer']) == len(set(args['consumer'])), 'duplicate resource consumer')
                destination = run_storage.checked_path(Path(config['target_root']) / args['destination'], config['target_root'])
                require(any(destination.is_relative_to(Path(p).resolve()) for p in module['write_paths']), 'resource outside assigned write scope')
                tasks = [t for t in module['plan'].get('tasks', []) if t['task_id'] == args.get('task_id')]
                require(len(tasks) == 1, 'resource-convert requires a frozen task_id')
                writes = tasks[0].get('scope', {}).get('write_paths', [])
                require(any(destination.is_relative_to(Path(p).resolve()) for p in writes), 'resource outside assigned task write scope')
                analysis = read_json(check_ref(module['plan'].get('dimension_analysis_ref')))
                items = [i for d in analysis['dimensions'] if d['dimension'] == 'Resource'
                         for i in d.get('items', []) if i['item_id'] == args.get('resource_item_id')]
                require(len(items) == 1, 'resource-convert requires a frozen resource_item_id')
                item = items[0]
                require(any(t['item_id'] == item['item_id'] and args['task_id'] in t['task_ids']
                            for t in module['plan'].get('dimension_trace', [])), 'task does not own resource item')
                facts = resource_fidelity.validate_facts(item, config['legacy_root'], check_configuration=True)
                source = run_storage.checked_path(Path(config['legacy_root']) / args['source'], config['legacy_root'])
                consumers = resource_fidelity.consumers(item)
                target_path, _, accessor = item['target_resource'].partition('#')
                require(file_ref(source) == item['source_resource_ref'] and args['source_id'] == item['source_resource']
                        and destination == Path(target_path).resolve() and args['target_ref'] == accessor
                        and set(args['consumer']) == set(consumers), 'resource request differs from frozen mapping')
                strategy = item['resource_strategy']
                require(args.get('strategy', strategy) == strategy, 'resource strategy differs from frozen mapping')
                if strategy == 'exact_vector_xml':
                    require(args.get('resolve_ref', []) == item.get('resolve_ref', []) and
                            args.get('consumer_tint') == item.get('consumer_tint'), 'vector substitutions differ from frozen mapping')
                    result = resource_tool.prepare_vector(SimpleNamespace(android_root=config['legacy_root'],
                        target_root=config['target_root'], source=str(source), destination=str(destination),
                        source_id=args['source_id'], target_ref=args['target_ref'], consumer=args['consumer'],
                        resolve_ref=args.get('resolve_ref', []), consumer_tint=args.get('consumer_tint')))
                    payload = result.pop('content').encode()
                else:
                    payload = resource_fidelity.prepare_exact(source, destination, args['source_id'], strategy)
                    result = {'status': 'RESOURCE_READY', 'mapping': {'sourceId': args['source_id'],
                        'sourcePath': args['source'], 'targetPath': args['destination'], 'targetRef': args['target_ref'],
                        'consumers': args['consumer'], 'strategy': strategy}}
                result['mapping']['qualifier'] = facts['qualifier']
                if item.get('configuration_mapping'):
                    result['mapping']['configurationMapping'] = item['configuration_mapping']
                result.update(task_id=args['task_id'], resource_item_id=item['item_id'], source_facts=facts)
                run_storage.atomic_bytes(destination, payload)
                result['target_ref'] = file_ref(destination)
            elif operation == 'resource-plan':
                rules = config.get('target_resources') or {}
                analysis = read_json(check_ref(args.get('dimension_analysis_ref')))
                sheet = ui_parameters.derive(analysis, rules.get('parameters'))
                result = {'status': 'PLANNED', 'undeclared': resource_copy.undeclared(analysis),
                          'parameter_sheet_ref': save(out / 'parameter-sheet.json', sheet), 'parameters': ui_parameters.outline(sheet['parameters']),
                          'next_action': 'name parameter_sheet_ref on the UI dimension and copy_plan_ref on the Resource dimension; '
                                         'author only what they leave open'}
                if rules.get('copy'):
                    plan, authored = resource_copy.derive(analysis, rules['copy'])
                    result.update(copy_plan_ref=save(out / 'copy-plan.json', plan), rows=len(plan['rows']), authored=authored)
            elif operation == 'screen-checks':
                import ui_fidelity
                derived = ui_fidelity.derive_checks(read_json(check_ref(args.get('dimension_analysis_ref'))), out,
                                                    (config.get('target_resources') or {}).get('copy'))
                result = {'status': 'DERIVED', 'screen_checks_ref': save(out / 'screen-checks.json', derived),
                          'checks': sum(len(rows) for rows in derived['checks'].values()), 'unrendered': derived['unrendered'],
                          'next_action': 'add each UI item\'s checks to its image_checks and carry them on a visual PATH; '
                                         'waive with evidence only what the screen cannot show'}
            elif operation == 'resource-sync':
                analysis = read_json(check_ref(module['plan'].get('dimension_analysis_ref')))
                tasks = [t for t in module['plan'].get('tasks', []) if t['task_id'] == args.get('task_id')]
                require(len(tasks) == 1, 'resource-sync requires a frozen task_id')
                scopes = [[Path(p).resolve() for p in paths] for paths in (module['write_paths'], tasks[0].get('scope', {}).get('write_paths', []))]
                allowed = lambda path: all(any(path.resolve().is_relative_to(p) for p in scope) for scope in scopes)
                copies = resource_copy.sync(analysis, allowed)
                document = ui_parameters.load(analysis)
                files, accessors = parameter_file.render(document, parameter_file.declarations(analysis)) if document and document.get('convention') else ({}, [])
                require(copies or files, 'the frozen plan names neither a copy plan nor parameters to write')
                rows = []
                for row, target, payload, action in copies:
                    if action == 'copied':
                        run_storage.atomic_bytes(target, payload)
                    rows.append({'source_resource': row['source_resource'], 'variant': row['variant'], 'accessor': row['accessor'],
                                 'action': action, 'target_ref': file_ref(target)})
                written = []
                for path, text in sorted(files.items()):
                    require(allowed(Path(path)), 'generated parameter file outside the assigned write scope: ' + path)
                    run_storage.atomic_bytes(Path(path), text.encode('utf-8'))
                    written.append(file_ref(path))
                result = {'status': 'SYNCED', 'task_id': args['task_id'], 'rows': rows, 'parameter_files': written, 'keys': len(accessors),
                          'acceptance': 'copies-and-generated-files-are-checked-against-the-frozen-plan-when-the-result-is-accepted'}
            elif operation == 'resource-scan':
                result = resource_tool.scan(SimpleNamespace(android_root=config['legacy_root'],
                    ui_tree=str(check_ref(args['ui_tree_ref'])) if args.get('ui_tree_ref') else None,
                    source_index=str(check_ref(args['source_index_ref'])) if args.get('source_index_ref') else None,
                    extra_ref=args.get('extra_refs', [])))
                for row in result['resources']:
                    row['source_refs'] = [file_ref(run_storage.checked_path(Path(config['legacy_root']) / p,
                                                                          config['legacy_root'])) for p in row['candidates']]
                if args.get('ui_tree_ref') and args.get('source_index_ref'):
                    result['skeletons'] = resource_fidelity.skeletons(
                        read_json(check_ref(args['source_index_ref'])), read_json(check_ref(args['ui_tree_ref'])),
                        args.get('resource_scope'))
            elif operation == 'render-reference':
                index = read_json(check_ref(args['source_index_ref']))
                require(Path(index.get('androidRoot', '')).resolve() == Path(config['legacy_root']).resolve(),
                        'the source index belongs to another legacy root')
                try:
                    document = reference_render.render(index, args.get('source_resource'), args.get('qualifier', 'base'), out)
                except reference_render.RenderError as exc:
                    raise Rejected(str(exc)) from exc
                result = {'status': 'RENDERED', 'reference_ref': file_ref(out / 'reference.json'), 'png_ref': document['png_ref'],
                          'acceptance': 'a-reference-is-frozen-by-the-spec-that-declares-the-check'}
            elif operation == 'image-parity':
                import lean_visual_worker
                result = lean_visual_worker.parity(args, out, module, task, snapshot['run_id'])
            elif operation == 'compare-only':
                ref = check_ref(args.get('reference_ref')); candidate = check_ref(args.get('candidate_ref'))
                old = sys.argv
                try:
                    sys.argv = ['ui_visual_score', '--reference', str(ref), '--candidate', str(candidate), '--out', str(out / 'score')]
                    code = ui_visual_score.main()
                finally:
                    sys.argv = old
                result = {'status': 'scored' if code == 0 else 'comparison-unavailable',
                          'score_ref': file_ref(out / 'score/score.json'),
                          'reference_ref': args['reference_ref'], 'candidate_ref': args['candidate_ref'],
                          'acceptance': 'score-is-evidence-not-a-visual-verdict'}
            elif operation in visual_operations:
                import lean_visual_worker
                result = lean_visual_worker.run(operation, args, root=root, out=out, module=module,
                                                task=task, actor=actor, config=config)
            elif operation.startswith(('knowledge-', 'foundation-')):
                result = lean_knowledge.run(operation, args, config, root)
            else:
                kind = args.get('kind')
                original = args.get('source_ref'); data = read_json(check_ref(original))
                if kind == 'ui':
                    result = lean_adapter.ui_evidence(data, args['ui_tree_ref'], target=args['target'], capture_ref=original,
                        source_index_ref=args.get('source_index_ref'), runtime_index_ref=args.get('runtime_index_ref'),
                        resource_scope=args.get('resource_scope'))
                elif kind == 'alignment':
                    result = lean_adapter.visual_results(data, args.get('interactions', []),
                        target_root=config['target_root'], result_ref=original)
                elif kind == 'validation':
                    result = lean_adapter.validation_summary(data, target_root=config['target_root'], result_ref=original)
                elif kind == 'foundation':
                    result = {'source_ref': original, 'resolution': lean_adapter.knowledge_gate.validate_resolution(original)}
                elif kind == 'resource':
                    result = lean_adapter.resource_summary(original, target_root=config['target_root'],
                        legacy_root=config['legacy_root'], approved_spec_hash=args['approved_spec_hash'])
                else:
                    raise Rejected('unsupported evidence kind')
            receipt.update(status='produced', result_ref=save(out / 'result.json', result))
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        receipt.update(status='rejected', reason=str(exc))
        raise Rejected(str(exc)) from exc
    finally:
        receipt['finished_at'] = datetime.now(timezone.utc).isoformat()
        save(out / 'receipt.json', receipt)
    return {'receipt_ref': file_ref(out / 'receipt.json'), 'result_ref': receipt['result_ref'],
            'next_action': 'submit the staged references through the existing Ledger operation'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'request', 'host-context'): p.add_argument('--' + name, required=True)
    args = p.parse_args()
    try:
        print(json.dumps(run(args.root, read_json(args.request), read_json(args.host_context)), ensure_ascii=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'rejected', 'reason': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
