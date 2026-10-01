#!/usr/bin/env python3
"""Normalize a completed, independently reviewed comparison through execute_test.

This adapter revalidates original comparison evidence. It does not capture, repair, or invent a
visual verdict. Host must supply the current result and frozen interaction declarations.
"""
import argparse
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True

from contracts import check_ref, digest, file_ref, read_json, require
import lean_adapter
import ui_evidence
import runner_storage
import run_storage
import visual_evidence


def report(query, result_ref, target_root, interactions=()):
    require(query.get('kind') == 'visual', 'visual PATH required')
    require(query.get('coverage') and query.get('node_ids'), 'frozen visual target/nodes required')
    check_ref(query.get('baseline_ref'))
    expected = query.get('expected_assertions', [])
    require(expected and all(a.get('expected') is True for a in expected),
            'this adapter supports explicit boolean alignment assertions only')
    rows = lean_adapter.visual_results(read_json(check_ref(result_ref)), interactions,
                                       target_root=target_root, result_ref=result_ref)
    require(query['coverage'] in rows, 'alignment omitted frozen target')
    row = rows[query['coverage']]
    quality = row['quality']
    requirement = None
    if quality == 'green-passed':
        require(any(ref['sha256'] == query['baseline_ref']['sha256'] for ref in row.get('reference_refs', [])),
                'alignment reference must match the frozen baseline screenshot')
        if query.get('interaction_id'):
            frozen = query.get('frozen_interaction')
            require(isinstance(frozen, dict) and frozen.get('id') == query['interaction_id'],
                    'visual query requires its complete frozen interaction')
            declared = [item for item in row.get('required_interactions', []) if item.get('id') == frozen['id']]
            require(len(declared) == 1, 'alignment omitted frozen interaction requirement')
            requirement = ui_evidence.match_interaction(declared[0], frozen)
            checks = [item for item in row.get('interaction_checks', []) if item.get('id') == frozen['id']]
            require(len(checks) == 1, 'alignment omitted frozen interaction observation')
            ui_evidence.match_interaction_observation(checks[0], frozen)
    proof = {'coverage': query['coverage'], 'node_ids': query['node_ids'], 'baseline_ref': query['baseline_ref'],
             'code_baseline': query['code_baseline'], 'hap_ref': row.get('hap_ref'),
             'evidence_ref': result_ref, 'linked_refs': row.get('linked_refs', []),
             'interaction_checks': [{**c, 'code_baseline': query['code_baseline']} for c in row.get('interaction_checks', [])]}
    if requirement:
        proof['required_interaction'] = requirement
    if quality == 'green-passed':
        proof['alignment_root'] = str(Path(target_root).resolve())
        proof['comparison_evidence'] = lean_adapter.comparison_evidence(read_json(check_ref(result_ref)),
                                                                      target_root, query['coverage'])
        proof['capture_evidence'] = visual_evidence.validate_alignment(read_json(check_ref(result_ref)),
            target_root, query['coverage'], frozen_evidence=query.get('frozen_visual_evidence'),
            code_baseline=query['code_baseline'], run_root=query.get('run_root'),
            assignment=query.get('execution_assignment'))
        proof['linked_refs'] += lean_adapter.linked_refs(proof['capture_evidence'], target_root)
    cause = row.get('root_cause')
    if cause:
        cause = {**cause, 'evidence_refs': [result_ref]}
    return {'schema_version': 1, 'producer': 'lean-visual-adapter', 'query_sha256': digest(query),
            **{k: query[k] for k in ('run_id', 'module_id', 'path_id', 'freeze_id', 'code_baseline')},
            'quality': quality, 'visual_alignment': proof, 'root_cause': cause,
            'assertions': [{'assertion_id': a['assertion_id'], 'expected': True,
                            'actual': True if quality == 'green-passed' else False if quality == 'red-bug' else None,
                            'passed': quality == 'green-passed', 'evidence_ref': result_ref} for a in expected]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('alignment', 'target-root', 'query-file', 'result-file'): p.add_argument('--' + key, required=True)
    p.add_argument('--interaction', action='append', default=[])
    args = p.parse_args()
    try:
        query = read_json(args.query_file)
        out = runner_storage.harmony_output(None, args.result_file, 'automation')
        require(not out.exists(), 'result attempt must not overwrite prior evidence')
        result = report(query, file_ref(args.alignment), args.target_root, args.interaction)
        run_storage.atomic_bytes(out, (json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode())
        print(json.dumps({'quality': result['quality'], 'result_ref': file_ref(out)}))
        return {'green-passed': 0, 'red-bug': 1, 'yellow-blocked': 2}[result['quality']]
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'rejected', 'reason': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
