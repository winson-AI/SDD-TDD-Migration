"""Shared frozen-reference and executed-capture checks for visual acceptance.

Managed execution receipts bind bytes and the installed build, not visual verdicts. Host
authentication and device locking remain the executor's responsibility, as for other receipts.
"""
from pathlib import Path

from contracts import check_ref, file_ref, read_json, require
import runner_storage
import ui_evidence


def reference(value, base):
    raw = value.get('path') if isinstance(value, dict) else value
    require(isinstance(raw, str) and raw, 'visual evidence file path required')
    path = Path(raw)
    ref = file_ref(path if path.is_absolute() else Path(base) / path)
    if isinstance(value, dict):
        require(value.get('sha256') == ref['sha256'], 'visual evidence hash mismatch')
    return ref


def source_record(evidence, coverage):
    require(isinstance(evidence, dict) and evidence.get('visual_mode') == 'runtime'
            and evidence.get('coverage') == coverage,
            'complete frozen visual evidence required; do not infer an owner from build binding')
    baselines = evidence.get('baseline_refs')
    require(isinstance(baselines, list) and baselines, 'frozen baseline screenshot set required')
    for ref in baselines:
        check_ref(ref)
    record = ui_evidence.capture_target(evidence.get('capture_manifest_ref'), coverage)
    require(record.get('status') == 'COMPLETE', 'frozen source capture must be complete')
    recorded = [file_ref(c['screenshot'])['sha256'] for c in record['snapshot']['captures']]
    require(set(recorded) == {ref['sha256'] for ref in baselines},
            'frozen baseline set must match all original target screenshots')
    return record


def frozen_evidence(module, path):
    """Use the PATH's UI owner, or an explicitly frozen GLOBAL-own evidence contract."""
    ref = (module.get('path_dimension_analysis_refs', {}).get(path['path_id']) or
           module.get('plan', {}).get('dimension_analysis_ref'))
    if ref:
        analysis = read_json(check_ref(ref))
        require(isinstance(analysis, dict), 'frozen UI dimension analysis must be an object')
        matches = [evidence for dimension in analysis.get('dimensions', [])
                   if dimension.get('dimension') == 'UI' and dimension.get('status') == 'applicable'
                   for item in dimension.get('items', [])
                   for evidence in [(item.get('semantic_model') or {}).get('ui_evidence') or {}]
                   if evidence.get('coverage') == path.get('coverage') and evidence.get('visual_mode') == 'runtime'
                   and path.get('baseline_ref') in evidence.get('baseline_refs', [])]
        if not matches:
            return None
        evidence = matches[0]
        require(all(item.get('capture_manifest_ref') == evidence.get('capture_manifest_ref') and
                    item.get('baseline_refs') == evidence.get('baseline_refs') for item in matches),
                'PATH has conflicting frozen runtime screenshot sets')
    else:
        evidence = path.get('visual_evidence')
        if not evidence:
            return None
    source_record(evidence, path['coverage'])
    require(path.get('baseline_ref') in evidence['baseline_refs'], 'PATH baseline outside frozen screenshot set')
    return evidence


def match_source(manifest_ref, evidence, coverage):
    original = source_record(evidence, coverage)
    current = ui_evidence.capture_target(manifest_ref, coverage)
    require(current == original, 'reference manifest changed this coverage original frozen Android record')
    return current


def observations(record, base):
    return [{'index': capture['index'], 'screenshot_ref': reference(capture['screenshot'], base),
             'view_ref': reference(capture.get('view_tree') or capture.get('view_xml'), base)}
            for capture in record['snapshot']['captures']]


def managed_ref(ref, run_root):
    path = check_ref(ref)
    runner_storage.harmony_output(run_root, path)
    return path


def command_log(ref, run_root):
    rows = read_json(managed_ref(ref, run_root))
    require(isinstance(rows, list) and rows, 'capture execution needs its actual command log')
    require(all(isinstance(row, dict) and isinstance(row.get('argv'), list)
                and all(isinstance(arg, str) for arg in row['argv']) for row in rows),
            'capture command log rows must contain command argv')
    require(any(isinstance(row, dict) and isinstance(row.get('argv'), list) and row['argv']
                and row.get('exit_code') == 0 for row in rows),
            'capture execution needs successful command evidence')
    return rows


def installation(ref, *, artifact_ref, code_baseline, device_id, app_id,
                 assignment_id, fencing_token, run_root):
    data = read_json(managed_ref(ref, run_root))
    require(data.get('producer') == 'lean-visual-worker' and data.get('operation') == 'visual-install'
            and data.get('status') == 'INSTALLED', 'managed successful installation receipt required')
    for key, expected in (('artifact_ref', artifact_ref), ('code_baseline', code_baseline),
                          ('device_id', device_id), ('app_id', app_id),
                          ('assignment_id', assignment_id), ('fencing_token', fencing_token)):
        require((expected or key == 'fencing_token' and expected is None) and key in data
                and data[key] == expected, 'installation receipt differs from capture ' + key)
    check_ref(data['artifact_ref'])
    rows = command_log(data.get('command_log_ref'), run_root)
    require(any(row.get('exit_code') == 0 and 'install' in row.get('argv', [])
                and artifact_ref['path'] in row['argv'] for row in rows),
            'installation command must name the captured HAP')
    return data


def capture_execution(record, manifest_ref, hap_ref, code_baseline, run_root, coverage, capture_round):
    snapshot = record['snapshot']
    execution_ref = snapshot.get('capture_execution_ref')
    receipt = read_json(managed_ref(execution_ref, run_root))
    require(receipt.get('schema_version') == 1 and receipt.get('producer') == 'sdd-visual-capture'
            and receipt.get('status') == 'CAPTURED' and receipt.get('executed') is True,
            'managed capture execution receipt required, not an alignment label')
    require(receipt.get('coverage') == coverage and receipt.get('capture_round') == capture_round,
            'capture execution target/round differs from selected capture')
    require(receipt.get('artifact_ref') == hap_ref, 'capture execution HAP differs from alignment HAP')
    require(receipt.get('code_baseline') and (code_baseline is None or receipt['code_baseline'] == code_baseline),
            'capture execution code baseline is stale')
    actual = observations(record, Path(manifest_ref['path']).parent)
    require(receipt.get('observations') == actual, 'capture execution screenshot/tree set differs from selected capture')
    backend = snapshot.get('device_backend') or {}
    require(receipt.get('device_id') == backend.get('device'), 'capture execution device differs from snapshot')
    installed = installation(receipt.get('install_ref'), artifact_ref=hap_ref, code_baseline=receipt['code_baseline'],
                 device_id=receipt.get('device_id'), app_id=receipt.get('app_id'),
                 assignment_id=receipt.get('assignment_id'), fencing_token=receipt.get('fencing_token'),
                 run_root=run_root)
    rows = command_log(receipt.get('command_log_ref'), run_root)
    # Native HDC logs expose each downloaded image. External runners may retain a
    # structured capture command result naming the same observations and installed build.
    downloads = {str(row['argv'][-1]) for row in rows if row.get('exit_code') == 0
                 and isinstance(row.get('argv'), list) and 'recv' in row['argv']}
    native = (any(row.get('exit_code') == 0 and 'snapshot_display' in row.get('argv', []) for row in rows)
              and all(item['screenshot_ref']['path'] in downloads for item in actual))
    external = any(row.get('exit_code') == 0 and row.get('operation') == 'capture'
                   and row.get('artifact_ref') == hap_ref and row.get('code_baseline') == receipt['code_baseline']
                   and row.get('install_ref') == receipt['install_ref'] and row.get('observations') == actual
                   for row in rows)
    require(native or external, 'capture command evidence must bind the observed screenshots and installed build')
    meta_ref = reference(snapshot['meta'], Path(manifest_ref['path']).parent)
    meta = read_json(check_ref(meta_ref))
    # Native metadata may lack bindings; its managed sidecar supplies them. If native
    # bindings exist they must agree, so a sidecar cannot relabel an older capture.
    for key in ('artifact_ref', 'code_baseline', 'assignment_id', 'fencing_token', 'app_id'):
        if key in meta:
            require(meta[key] == receipt.get(key), 'capture metadata differs from execution ' + key)
    return {'capture_round': capture_round, 'coverage': coverage, 'manifest_ref': manifest_ref,
            'capture_execution_ref': execution_ref, 'install_ref': receipt['install_ref'],
            'install_command_log_ref': installed['command_log_ref'],
            'command_log_ref': receipt['command_log_ref'], 'meta_ref': meta_ref,
            'artifact_ref': hap_ref, 'code_baseline': receipt['code_baseline'], 'observations': actual}


def validate_alignment(result, target_root, coverage, *, frozen_evidence, code_baseline, run_root, assignment):
    """Recheck only the chosen target's used rounds, including carried regression capture."""
    source_record(frozen_evidence, coverage)
    require(isinstance(run_root, (str, Path)) and Path(run_root).is_absolute(), 'visual execution run_root required')
    require(isinstance(assignment, dict) and assignment.get('assignment_id'),
            'current visual execution assignment required')
    page, state, _ = coverage.split(':')
    rounds = {r['round']: r for r in result.get('rounds', [])}
    require(rounds, 'visual Green requires original comparison rounds')
    latest = result['rounds'][-1]['round']
    proofs = []

    def visit(round_id):
        row = rounds[round_id]
        target = next((t for t in row['target_results'] if (t['page_id'], t['state_id']) == (page, state)), None)
        require(target and target['status'] in ('ALIGNED', 'ALIGNED_CARRIED'), 'visual Green needs aligned target')
        if target['status'] == 'ALIGNED_CARRIED':
            previous = target.get('carried_from_round')
            require(previous in rounds and previous < round_id, 'carried alignment needs prior aligned round')
            visit(previous)
        manifest_ref = reference(row['capture_manifest'], target_root)
        match_source(manifest_ref, frozen_evidence, coverage)
        manifest = read_json(check_ref(manifest_ref))
        capture_round = row.get('capture_round', round_id)
        candidates = [r for r in manifest['targets'] if r.get('phase') == 'harmony-candidate'
                      and r.get('platform') == 'harmony' and r.get('page_id') == page and r.get('state_id') == state
                      and r.get('round') == capture_round and r.get('status') == 'COMPLETE']
        require(len(candidates) == 1, 'one executed candidate capture required per selected round')
        hap_ref = reference(row['hap'], target_root)
        proof = capture_execution(candidates[0], manifest_ref, hap_ref,
                                  code_baseline if round_id == latest else None, run_root, coverage, capture_round)
        if round_id == latest:
            executed = read_json(check_ref(proof['capture_execution_ref']))
            require(executed.get('assignment_id') == assignment['assignment_id']
                    and executed.get('fencing_token') == assignment.get('fencing_token'),
                    'latest capture must belong to the current test/audit assignment and fence; '
                    'reading previous capture evidence is review, not a new test')
        proofs.append({'round': round_id, **proof})

    visit(latest)
    return proofs
