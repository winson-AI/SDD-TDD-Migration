#!/usr/bin/env python3
"""Deterministic import of external domain-tool evidence under SDD role boundaries.

The managed lean_worker entry stages tool outputs; existing Ledger operations and
execution receipts retain acceptance authority. Whole external skills are not roles.
"""
import argparse
import copy
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True

import ui_evidence as ue
import semantics
from contracts import check_ref, file_ref, nonempty, read_json, require, Rejected
from lean_tools import finalize_alignment, resource_tool
import knowledge_gate
from types import SimpleNamespace


def ui_evidence(capture_entry, ui_tree_ref, *, target=None, capture_ref=None, source_index_ref=None,
                runtime_index_ref=None, resource_scope=None):
    """lean capture manifest entry + extracted ui-tree -> SDD semantic_model.ui_evidence."""
    if 'targets' in capture_entry:
        require(capture_ref and read_json(check_ref(capture_ref)) == capture_entry, 'original capture_ref required')
        require(target, 'native manifest import needs explicit page:state:coverage')
        record = ue.capture_target(capture_ref, target)
        runtime = record['status'] == 'COMPLETE'
        evidence = {'ui_tree_ref': ui_tree_ref, 'source_index_ref': source_index_ref,
                    'capture_manifest_ref': capture_ref, 'coverage': target,
                    'legacy_executable': runtime, 'visual_mode': 'runtime' if runtime else 'source-only'}
        if runtime_index_ref:
            evidence['runtime_index_ref'] = runtime_index_ref
        if resource_scope is not None:
            evidence['resource_scope'] = resource_scope
        if runtime:
            require(runtime_index_ref, 'runtime capture needs runtime_index_ref')
            index = read_json(check_ref(runtime_index_ref))
            evidence['baseline_refs'] = ue.runtime_baselines(ue.runtime_target(index, target))
        ue.validate_native_evidence(evidence)
        evidence['linked_refs'] = capture_evidence(capture_ref, {tuple(target.split(':')[:2])})[0]
        semantics._ui_evidence({'ui_evidence': evidence})
        return evidence
    ue.validate_capture(capture_entry)
    page, state, coverage = capture_entry['page_id'], capture_entry['state_id'], capture_entry['coverage']
    status = capture_entry['status']
    check_ref(ui_tree_ref)
    evidence = {'ui_tree_ref': ui_tree_ref, 'coverage': page + ':' + state + ':' + coverage,
                'visual_mode': 'runtime' if status == 'COMPLETE' else 'source-only'}
    semantics._ui_evidence({'ui_evidence': evidence})  # single source of truth for the gate
    return evidence


VISUAL_QUALITY = {'ALIGNED': 'green-passed', 'ALIGNED_CARRIED': 'green-passed',
                  'NEEDS_UI_FIX': 'red-bug', 'NEEDS_IMPLEMENTATION_FIX': 'red-bug',
                  'CAPTURE_BLOCKED': 'yellow-blocked'}


def overall_alignment(rows, result):
    """A target pixel score cannot clear an unresolved whole-alignment verdict."""
    status = result['status']
    quality = {'FAILED': 'red-bug', 'NEEDS_IMPLEMENTATION_FIX': 'red-bug', 'BLOCKED': 'yellow-blocked'}.get(status)
    for row in rows.values():
        row.update(visual_quality=row['quality'], overall_verdict=status, overall_issues=result.get('issues', []))
        if quality and (row['quality'] == 'green-passed' or quality == 'red-bug' and row['quality'] != 'red-bug'):
            row['quality'] = quality
            row['root_cause'] = {'category': 'implementation' if status == 'NEEDS_IMPLEMENTATION_FIX' else
                                'alignment-failure' if quality == 'red-bug' else 'capture-environment',
                'summary': status + ': ' + str(result.get('issues', [])), 'confidence': 'observed',
                'owner': 'fixer' if quality == 'red-bug' else 'test-runner', 'next_action': 'diagnose'}
    return rows


VARIANT_CONFLICT = 'runtime-spec-variant-conflict'


def variant_conflict(issues):
    """A runtime page variant contradicting the frozen SPEC is a user scope decision, not a code repair."""
    hits = [i for i in issues or [] if isinstance(i, dict) and i.get('category') == VARIANT_CONFLICT]
    if not hits:
        return None
    return {'category': 'human', 'reason_code': VARIANT_CONFLICT, 'confidence': 'confirmed', 'owner': 'human',
            'summary': '; '.join(str(i.get('message') or i.get('summary') or VARIANT_CONFLICT) for i in hits),
            'next_action': 'ask the user which variant the migration must keep, then re-plan or continue'}


def visual_results(alignment_result, declared_interactions=(), *, target_root=None, result_ref=None):
    rows = _visual_results(alignment_result, declared_interactions, target_root=target_root, result_ref=result_ref)
    conflict = variant_conflict(alignment_result.get('issues'))
    if conflict:
        for row in rows.values():
            if isinstance(row, dict) and row.get('quality') not in (None, 'green-passed'):
                row.update(quality='yellow-blocked', root_cause=conflict)
    return rows


def _visual_results(alignment_result, declared_interactions=(), *, target_root=None, result_ref=None):
    """lean alignment-result -> three-state rows for the visual test stage, keyed page:state:coverage.

    The visual stage is an ordinary test layer, so an unaligned target is a Red with a node-level root
    cause rather than a separate verdict. Declared gestures must carry PASSED device evidence bound to
    the aligned HAP. Nothing here invents a pass.
    """
    if 'rounds' in alignment_result:
        require(target_root and result_ref, 'native alignment needs target_root and original result_ref')
        require(read_json(check_ref(result_ref)) == alignment_result, 'alignment source changed')
        try:
            finalize_alignment.validate(Path(target_root).resolve(), alignment_result)
        except RuntimeError as exc:
            raise Rejected(str(exc)) from exc
        declared = {r['id'] for r in alignment_result.get('required_interactions', [])}
        require(set(declared_interactions) == declared, 'alignment interactions differ from frozen declarations')
        rounds = alignment_result['rounds']
        assets, references = alignment_evidence(alignment_result, target_root)
        if not rounds:
            require(alignment_result['status'] in ('BLOCKED', 'FAILED', 'NEEDS_IMPLEMENTATION_FIX'), 'no comparison round')
            rows = {f"{t['page_id']}:{t['state_id']}:{t['coverage']}": {
                'quality': 'yellow-blocked', 'alignment_status': alignment_result['status'], 'evidence_ref': result_ref,
                'comparison_executed': False, 'linked_refs': assets, 'reference_refs': [],
                'root_cause': {'category': 'capture-environment', 'summary': 'No completed comparison; inspect original issues',
                               'confidence': 'observed', 'owner': 'test-runner', 'next_action': 'diagnose'},
                'issues': alignment_result.get('issues', [])} for t in alignment_result['required_targets']}
            return overall_alignment(rows, alignment_result)
        latest = rounds[-1]
        hap = normalize_ref(latest['hap'], target_root)
        coverage = {(t['page_id'], t['state_id']): t['coverage'] for t in alignment_result['required_targets']}
        checks = [{**c, 'evidence_ref': normalize_ref(c['evidence'], target_root)}
                  for c in alignment_result.get('interaction_checks', [])]
        rows = {}
        for target in latest['target_results']:
            key = f"{target['page_id']}:{target['state_id']}:{coverage[(target['page_id'], target['state_id'])]}"
            row = {'quality': VISUAL_QUALITY[target['status']], 'alignment_status': target['status'],
                   'evidence_ref': result_ref, 'hap_ref': hap, 'interaction_checks': checks,
                   'required_interactions': alignment_result.get('required_interactions', []),
                   'linked_refs': assets, 'reference_refs': references.get((target['page_id'], target['state_id']), []),
                   'comparison_executed': True, 'round': latest['round']}
            if row['quality'] != 'green-passed':
                row['root_cause'] = {'category': 'capture-environment' if target['status'] == 'CAPTURE_BLOCKED' else 'visual-alignment',
                    'summary': str(target.get('reason') or target.get('issues') or target['status']) + ' at ' + key,
                    'confidence': 'observed', 'owner': target.get('owner', 'fixer'), 'next_action': 'diagnose'}
            rows[key] = row
        # A failed declared interaction cannot hide behind visually aligned pixels.
        if any(c['status'] != 'PASSED' for c in checks):
            for row in rows.values():
                if row['quality'] == 'green-passed':
                    row['quality'] = 'red-bug' if any(c['status'] == 'FAILED' for c in checks) else 'yellow-blocked'
                    row['root_cause'] = {'category': 'interaction', 'summary': 'Declared interaction did not pass',
                        'confidence': 'observed', 'owner': 'fixer', 'next_action': 'diagnose'}
        return overall_alignment(rows, alignment_result)
    rows = {}
    for target in nonempty(alignment_result.get('target_results'), 'alignment target_results'):
        status = target.get('status')
        require(status in VISUAL_QUALITY, 'unknown alignment target status: ' + str(status))
        key = '{}:{}:{}'.format(target.get('page_id'), target.get('state_id'), target.get('coverage'))
        check_ref(target.get('evidence_ref'))
        row = {'quality': VISUAL_QUALITY[status], 'alignment_status': status,
               'evidence_ref': target['evidence_ref'], 'nodes': list(target.get('node_ids', []))}
        if row['quality'] != 'green-passed':
            row['root_cause'] = target.get('root_cause') or {
                'category': 'capture-environment' if status == 'CAPTURE_BLOCKED' else 'visual-alignment',
                'summary': status + ' at ' + key, 'confidence': 'confirmed',
                'owner': target.get('owner', 'lean'),
                'next_action': 'repair the named nodes, or restore capture evidence'}
        require(key not in rows, 'duplicate visual target')
        rows[key] = row
    ue.validate_interaction_checks(list(declared_interactions), alignment_result)
    return rows


def validation_summary(validation_result, *, target_root=None, result_ref=None):
    """Import a verdict as an evidence hint; formal SDD receipts still decide acceptance."""
    native = validation_result.get('schemaVersion') is not None
    checks = validation_result.get('checks')
    verdict = validation_result.get('verdict')
    extra_refs = []
    if native:
        require(validation_result.get('schemaVersion') == 1, 'unsupported native validation schema')
        require(target_root and result_ref and read_json(check_ref(result_ref)) == validation_result,
                'native validation needs target_root and original result_ref')
        allowed = {'PRE_VISUAL': {'BUILD_READY', 'NEEDS_IMPLEMENTATION_FIX', 'BLOCKED', 'FAILED'},
                   'FINAL': {'PASSED', 'RUNNABLE_PARTIAL', 'NEEDS_IMPLEMENTATION_FIX', 'BLOCKED', 'FAILED'}}
        require(verdict in allowed.get(validation_result.get('stage'), set()), 'validation verdict invalid for stage')
        require(isinstance(checks, list), 'validation checks must be an array')
        require(isinstance(validation_result.get('issues', []), list), 'validation issues must be an array')
        kinds_seen = set()
        for item in checks:
            require(isinstance(item, dict) and item.get('kind'), 'validation check needs a kind')
            require(item['kind'] not in kinds_seen, 'duplicate/conflicting validation check kind')
            kinds_seen.add(item['kind'])
            require(item.get('status') in ('passed', 'failed', 'blocked', 'not-run'), 'invalid validation check status')
            if item['status'] in ('passed', 'failed'):
                require(item.get('command') and type(item.get('exit_code')) is int, 'command and exit_code required')
                normalize_ref(item.get('log_path'), target_root)
                require(item['status'] != 'passed' or item['exit_code'] == 0, 'passed check has failed exit')
        required = {'test', 'compile', 'package'}
        if 'ui' in validation_result.get('scope_kinds', []): required.add('ui-contract')
        if verdict in ('BUILD_READY', 'PASSED', 'RUNNABLE_PARTIAL'):
            require(required <= kinds_seen, 'missing required test/compile/package checks')
            require(all(c.get('status') == 'passed' for c in checks), 'success contradicts incomplete/failed checks')
            require(all(isinstance(c, dict) and c.get('status') == 'passed' and c.get('scenario') and c.get('evidence')
                        for c in nonempty(validation_result.get('spec_checks'), 'spec checks')), 'spec review incomplete')
            nonempty(validation_result.get('artifacts'), 'current HAP/HSP artifacts')
        if verdict == 'NEEDS_IMPLEMENTATION_FIX':
            require(all(isinstance(issue, dict) and issue.get('owner') in ('lean', 'resource')
                        for issue in nonempty(validation_result.get('issues'), 'actionable implementation issues')),
                    'implementation issues require lean/resource owner')
        validation_result = copy.deepcopy(validation_result)
        validation_result['artifacts'] = [normalize_ref(r, target_root) for r in validation_result.get('artifacts', [])]
        require(all(Path(r['path']).suffix.lower() in ('.hap', '.hsp') for r in validation_result['artifacts']),
                'native build artifact must be HAP/HSP')
        if verdict == 'RUNNABLE_PARTIAL':
            visual = validation_result.get('visual_evidence') or {}
            require(visual.get('mode') == 'source-only' and validation_result.get('issues'),
                    'partial verdict must disclose missing visual proof')
            manifest_ref = normalize_ref(visual.get('manifest'), target_root)
            manifest = read_json(check_ref(manifest_ref))
            extra_refs.extend(capture_evidence(manifest_ref, {(t.get('page_id'), t.get('state_id'))
                for t in visual.get('targets', []) if isinstance(t, dict)})[0])
            for target in nonempty(visual.get('targets'), 'source-only targets'):
                require(isinstance(target, dict) and target.get('page_id') and target.get('state_id'), 'source-only target invalid')
                require(any(r.get('phase') == 'android-reference' and r.get('platform') == 'android'
                            and r.get('page_id') == target['page_id'] and r.get('state_id') == target['state_id']
                            and r.get('status') == 'SOURCE_ONLY' and r.get('snapshot') is None
                            for r in manifest.get('targets', [])), 'partial verdict has no matching SOURCE_ONLY capture')
        if verdict == 'PASSED' and 'ui' in validation_result.get('scope_kinds', []):
            require((validation_result.get('visual_evidence') or {}).get('mode') == 'runtime', 'UI PASSED requires runtime visual evidence')
            alignment_ref = normalize_ref(validation_result.get('alignment_result'), target_root)
            alignment = read_json(check_ref(alignment_ref))
            require(alignment.get('status') == 'ALIGNED', 'UI PASSED requires ALIGNED result')
            visual_results(alignment, [r['id'] for r in alignment.get('required_interactions', [])],
                           target_root=target_root, result_ref=alignment_ref)
            extra_refs.extend([alignment_ref, *alignment_evidence(alignment, target_root)[0]])
    else:
        nonempty(checks, 'validation checks')
        for check in checks:
            require(isinstance(check, dict) and check.get('kind'), 'validation check needs a kind')
            require(check.get('status') in ('passed', 'failed'), 'validation check status must be passed/failed')
    artifacts = [str(check_ref(ref)) for ref in validation_result.get('artifacts', [])]
    require(not any(c['kind'] == 'package' and c.get('status') == 'passed' for c in checks) or artifacts,
            'a package check must record its built artifact (HAP)')
    failed = sorted({check['kind'] for check in checks if check['status'] == 'failed'})
    quality = ('red-bug' if failed or (native and verdict in ('FAILED', 'NEEDS_IMPLEMENTATION_FIX')) else
               'yellow-blocked' if native and verdict in ('BLOCKED', 'RUNNABLE_PARTIAL') else 'green-passed')
    result = {'quality': quality, 'failed_checks': failed, 'artifacts': artifacts, 'verdict': verdict,
              'source_ref': result_ref, 'acceptance': 'requires-sdd-execution-receipt',
              'issues': validation_result.get('issues', []),
              'linked_refs': list({r['path']: r for r in [*linked_refs(validation_result, Path(target_root)), *extra_refs]}.values()) if native else []}
    if quality != 'green-passed':
        result['root_cause'] = {'category': 'validation-failure' if quality == 'red-bug' else 'validation-incomplete',
            'summary': verdict or 'failed checks', 'confidence': 'observed',
            'owner': 'fixer' if quality == 'red-bug' else 'test-runner', 'next_action': 'diagnose'}
    conflict = variant_conflict(result['issues'])
    if conflict:
        result.update(quality='yellow-blocked', root_cause=conflict)
    return result


def normalize_ref(value, base):
    raw = value.get('path') if isinstance(value, dict) else value
    require(isinstance(raw, str) and raw, 'evidence file path required')
    p = Path(raw)
    ref = file_ref(p if p.is_absolute() else Path(base) / p)
    if isinstance(value, dict) and value.get('sha256'):
        require(ref['sha256'] == value['sha256'], 'evidence hash mismatch')
    return ref


def capture_evidence(manifest_ref, selected=None):
    """Resolve only declared capture paths relative to the owning manifest."""
    path = check_ref(manifest_ref)
    manifest = read_json(path)
    require(isinstance(manifest, dict) and isinstance(manifest.get('targets'), list), 'capture manifest targets required')
    refs, references = {manifest_ref['path']: manifest_ref}, {}
    for target in manifest['targets']:
        if not isinstance(target, dict) or (selected is not None and (target.get('page_id'), target.get('state_id')) not in selected):
            continue
        snapshot = target.get('snapshot') or {}
        require(isinstance(snapshot, dict) and isinstance(snapshot.get('captures', []), list), 'capture snapshot must contain a captures array')
        shots = {}
        for record in [snapshot, *snapshot.get('captures', [])]:
            require(isinstance(record, dict), 'capture record must be an object')
            for field in ('screenshot', 'view_tree', 'view_xml', 'meta', 'video', 'recording'):
                if record.get(field):
                    ref = normalize_ref(record[field], path.parent)
                    refs[ref['path']] = ref
                    if field == 'screenshot': shots[ref['path']] = ref
        if target.get('phase') == 'android-reference' and target.get('platform') == 'android' and target.get('status') == 'COMPLETE':
            key = (target['page_id'], target['state_id'])
            require(key not in references, 'ambiguous Android reference capture')
            references[key] = list(shots.values())
    return list(refs.values()), references


def alignment_evidence(result, target_root):
    """Archive manifests and their capture closure, keeping each document's own base."""
    refs, references = {}, {}
    def add(value, base=target_root):
        ref = normalize_ref(value, base); refs[ref['path']] = ref
        return ref
    for item in result.get('rounds', []):
        add(item['hap'])
        manifest_ref = add(item['capture_manifest'])
        captures, candidates = capture_evidence(manifest_ref, {(t['page_id'], t['state_id']) for t in result['required_targets']})
        refs.update({r['path']: r for r in captures})
        for target in item['target_results']:
            key = (target['page_id'], target['state_id'])
            if target['status'] in ('ALIGNED', 'NEEDS_UI_FIX'):
                references[key] = candidates.get(key, [])
            if target.get('regression_score'): add(target['regression_score'])
        for comparison in item.get('comparisons', []):
            for disposition in comparison.get('semantic_dispositions', []):
                if disposition.get('semantic_ref'):
                    add(disposition['semantic_ref'])
                for evidence in disposition.get('evidence_refs', []):
                    add(evidence)
            for field in ('score', 'semantic'):
                if comparison.get(field):
                    proof = add(comparison[field])
                    if field == 'score':
                        score = read_json(check_ref(proof))
                        for key in ('reference', 'candidate'):
                            if score.get(key): add(score[key], Path(proof['path']).parent)
                        for key in ('heatmap', 'side_by_side', 'reference_normalized', 'candidate_normalized'):
                            value = score.get('artifacts', {}).get(key)
                            if value: add(value, Path(proof['path']).parent)
    for interaction in result.get('interaction_checks', []):
        if interaction.get('evidence'): add(interaction['evidence'])
    return list(refs.values()), references


def semantic_dispositions(semantic, semantic_ref, dispositions):
    """Require an evidence-backed judgment for contradictions, never score an automatic pass."""
    issues = semantic.get('issues', [])
    require(isinstance(issues, list) and all(isinstance(issue, dict) for issue in issues),
            'semantic issues must be an array of findings')
    findings = [{'kind': 'issue', 'index': index, 'issue': issue} for index, issue in enumerate(issues)]
    comparability = semantic.get('comparability')
    if comparability is not None:
        require(isinstance(comparability, (int, float)) and not isinstance(comparability, bool)
                and 0 <= comparability <= 1, 'semantic comparability must be a finite 0..1 value')
        # Lean's existing interpretation labels <0.40 as different route/state. The
        # reviewer may rebut that judgment with evidence; it is not an acceptance score.
        if comparability < 0.4:
            findings.append({'kind': 'comparability', 'value': comparability})
    if semantic.get('comparable') is False:
        findings.append({'kind': 'comparable', 'value': False})
    require(isinstance(dispositions, list) and len(dispositions) == len(findings),
            'semantic contradictions require one explicit disposition per finding')
    remaining = list(findings)
    for disposition in dispositions:
        require(isinstance(disposition, dict) and disposition.get('semantic_ref') == semantic_ref,
                'semantic disposition must bind the original semantic file/hash')
        finding = disposition.get('finding')
        require(finding in remaining, 'semantic disposition finding differs from original issue or is duplicated')
        remaining.remove(finding)
        require(disposition.get('decision') in ('resolved', 'dismissed')
                and isinstance(disposition.get('reason'), str) and disposition['reason'].strip(),
                'semantic disposition requires resolved/dismissed and a nonempty reason')
        refs = nonempty(disposition.get('evidence_refs'), 'semantic disposition evidence')
        for ref in refs:
            check_ref(ref)
        require(any(ref['sha256'] != semantic_ref['sha256'] for ref in refs),
                'semantic disposition needs supporting evidence beyond the contradicted semantic result')
    return dispositions


def comparison_evidence(result, target_root, coverage):
    """Re-derive a selected target's score/semantic inputs from round capture indices."""
    page, state, _ = coverage.split(':')
    proofs = []
    rounds = {r['round']: r for r in result.get('rounds', [])}
    require(rounds, 'visual Green requires original comparison rounds')

    def shot(r, phase, index):
        manifest = normalize_ref(r['capture_manifest'], target_root)
        targets = read_json(check_ref(manifest))['targets']
        matches = [t for t in targets if t.get('page_id') == page and t.get('state_id') == state
                   and t.get('phase') == phase and t.get('status') == 'COMPLETE'
                   and t.get('platform') == ('android' if phase == 'android-reference' else 'harmony')
                   and (phase == 'android-reference' or t.get('round') == r.get('capture_round', r['round']))]
        require(len(matches) == 1 and matches[0].get('observed_variant') == state,
                'comparison capture must identify one matching observed target/round')
        captures = [c for c in matches[0].get('snapshot', {}).get('captures', []) if c.get('index') == index]
        require(len(captures) == 1, 'comparison capture index must select one screenshot')
        return normalize_ref(captures[0]['screenshot'], Path(manifest['path']).parent)

    def score_binding(value, reference, candidate):
        ref = normalize_ref(value, target_root)
        score = read_json(check_ref(ref))
        for key, expected in (('reference', reference), ('candidate', candidate)):
            actual = normalize_ref(score.get(key), Path(ref['path']).parent)
            require(actual['sha256'] == expected['sha256'], 'score ' + key + ' differs from selected capture')
        return ref

    def visit(r):
        target = next((t for t in r['target_results'] if (t['page_id'], t['state_id']) == (page, state)), None)
        require(target and target['status'] in ('ALIGNED', 'ALIGNED_CARRIED'), 'visual Green needs aligned target')
        if target['status'] == 'ALIGNED_CARRIED':
            previous = rounds.get(target.get('carried_from_round'))
            require(previous and previous['round'] < r['round'], 'carried alignment needs prior aligned round')
            visit(previous)
            index = target.get('regression_capture_index', 0)
            reference, candidate = shot(previous, 'harmony-candidate', index), shot(r, 'harmony-candidate', index)
            score = score_binding(target.get('regression_score'), reference, candidate)
            proofs.append({'round': r['round'], 'coverage': coverage, 'kind': 'carried-regression',
                           'reference_capture_index': index, 'candidate_capture_index': index,
                           'reference_ref': reference, 'candidate_ref': candidate, 'score_ref': score})
            return
        comparisons = [c for c in r.get('comparisons', []) if (c['page_id'], c['state_id']) == (page, state)]
        require(comparisons, 'aligned target needs comparison evidence')
        for c in comparisons:
            ri, ci = c.get('reference_capture_index', c.get('capture_index', 0)), c.get('candidate_capture_index', c.get('capture_index', 0))
            reference, candidate = shot(r, 'android-reference', ri), shot(r, 'harmony-candidate', ci)
            score = score_binding(c.get('score'), reference, candidate)
            proof = {'round': r['round'], 'coverage': coverage, 'kind': 'comparison',
                     'reference_capture_index': ri, 'candidate_capture_index': ci,
                     'reference_ref': reference, 'candidate_ref': candidate, 'score_ref': score}
            if c.get('semantic'):
                semantic_ref = normalize_ref(c['semantic'], target_root)
                semantic = read_json(check_ref(semantic_ref))
                require(semantic.get('score_sha256') or (semantic.get('reference') and semantic.get('candidate')),
                        'semantic inspection must bind its score hash or screenshot pair')
                if semantic.get('score_sha256'):
                    require(semantic['score_sha256'] == score['sha256'], 'semantic score hash differs from comparison')
                if semantic.get('reference') or semantic.get('candidate'):
                    for key, expected in (('reference', reference), ('candidate', candidate)):
                        actual = normalize_ref(semantic.get(key), Path(semantic_ref['path']).parent)
                        require(actual['sha256'] == expected['sha256'], 'semantic image differs from selected capture')
                proof['semantic_ref'] = semantic_ref
                dispositions = semantic_dispositions(semantic, semantic_ref, c.get('semantic_dispositions', []))
                if dispositions:
                    proof['semantic_dispositions'] = dispositions
            proofs.append(proof)
    visit(result['rounds'][-1])
    return proofs


def linked_refs(value, base):
    """Retain actual file references hidden inside native path-based documents."""
    refs = {}
    def walk(item):
        if isinstance(item, dict):
            if isinstance(item.get('path'), str) and item.get('sha256'):
                ref = normalize_ref(item, base); refs[ref['path']] = ref
            else:
                for v in item.values(): walk(v)
        elif isinstance(item, list):
            for v in item: walk(v)
        elif isinstance(item, str) and '\n' not in item and len(item) < 1000:
            p = Path(item)
            if not p.is_absolute(): p = Path(base) / p
            try:
                if p.is_file():
                    ref = file_ref(p); refs[ref['path']] = ref
            except OSError:
                pass
    walk(value)
    return list(refs.values())


def resource_summary(result_ref, *, target_root, legacy_root, approved_spec_hash):
    path = check_ref(result_ref)
    try:
        resource_tool.validate_result(SimpleNamespace(android_root=legacy_root, target_root=target_root,
            result=str(path), approved_spec_hash=approved_spec_hash))
    except RuntimeError as exc:
        raise Rejected(str(exc)) from exc
    result = read_json(path)
    refs = {}
    for mapping in result['resourceMappings']:
        import resource_fidelity
        source = normalize_ref(mapping['sourcePath'], legacy_root)
        facts = resource_fidelity.source_facts(check_ref(source), mapping['sourceId'])
        resource_fidelity.validate_item({'resource_kind': facts['kind'], 'resource_strategy': mapping['strategy'],
            'nine_patch': facts['nine_patch'], 'source_unit': facts.get('source_unit'),
            'scales_with_font': mapping.get('scalesWithFont'),
            'adaptation_evidence_ref': mapping.get('adaptationEvidenceRef'), 'blocked_reason': mapping.get('blockedReason')})
        resource_fidelity.validate_configuration({'resource_strategy': mapping['strategy'],
            'target_resource': str(Path(target_root) / mapping.get('targetPath', '')),
            'consumer': mapping['consumers'], 'configuration_mapping': mapping.get('configurationMapping')}, facts['qualifier'])
        proof_refs = list((mapping.get('configurationMapping') or {}).get('evidence_refs', []))
        if mapping.get('adaptationEvidenceRef'):
            proof_refs.append(mapping['adaptationEvidenceRef'])
        for ref in proof_refs:
            verified = check_ref(ref); refs[str(verified)] = ref
        for field, checksum, base in (('sourcePath', 'sourceSha256', legacy_root), ('targetPath', 'targetSha256', target_root)):
            if mapping.get(field):
                if field == 'targetPath' and mapping['strategy'] == 'blocked':
                    continue  # A blocked mapping may name a proposed, uncreated destination.
                value = {'path': mapping[field], **({'sha256': mapping[checksum]} if mapping.get(checksum) else {})}
                ref = normalize_ref(value, base); refs[ref['path']] = ref
        for consumer in mapping.get('consumers', []):
            # Native consumers may be symbolic names. File consumers use target-root paths.
            candidate = Path(target_root) / consumer.split('#', 1)[0]
            if candidate.is_file():
                ref = file_ref(candidate); refs[ref['path']] = ref
    for changed in result.get('filesChanged', []):
        ref = normalize_ref(changed, target_root); refs[ref['path']] = ref
    return {'source_ref': result_ref, 'status': result['status'],
            'resource_mappings': result['resourceMappings'],
            'linked_refs': list(refs.values()),
            'acceptance': 'requires-frozen-resource-trace-and-production-consumers'}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p_ui = sub.add_parser('ui-evidence', help='capture entry + ui-tree file -> ui_evidence')
    p_ui.add_argument('--capture', required=True, help='JSON file with page_id/state_id/coverage/status')
    p_ui.add_argument('--ui-tree', required=True, help='extracted ui-tree.json (file_ref computed here)')
    p_ui.add_argument('--target', help='native page:state:coverage')
    p_ui.add_argument('--source-index')
    p_ui.add_argument('--runtime-index')
    p_visual = sub.add_parser('visual-results', help='alignment-result file -> visual-stage three-state rows')
    p_visual.add_argument('--target-root', help='base for native alignment paths')
    p_visual.add_argument('--alignment', required=True, help='lean alignment-result.json')
    p_visual.add_argument('--interaction', action='append', default=[], help='declared interaction id (repeatable)')
    args = parser.parse_args()
    try:
        if args.command == 'ui-evidence':
            out = ui_evidence(read_json(args.capture), file_ref(Path(args.ui_tree).resolve()),
                target=args.target, capture_ref=file_ref(args.capture),
                source_index_ref=file_ref(args.source_index) if args.source_index else None,
                runtime_index_ref=file_ref(args.runtime_index) if args.runtime_index else None)
        else:
            out = visual_results(read_json(args.alignment), args.interaction, target_root=args.target_root,
                                 result_ref=file_ref(args.alignment))
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'rejected', 'reason': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
