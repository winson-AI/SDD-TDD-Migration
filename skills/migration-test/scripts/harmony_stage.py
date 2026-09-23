#!/usr/bin/env python3
"""Build (do not submit) a Test-Runner stage from host receipts, including blocked paths."""
import argparse
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'migration-ledger/scripts'))
from contracts import check_ref, file_ref, read_json, require
from ledger import status, audit_scope
from runner_storage import harmony_output
from test_completion import interpret


def build(root, module_id, assignment_id, receipts):
    s = status(root)
    m = audit_scope(s) if module_id == 'GLOBAL' else s['modules'][module_id]
    a = s['audit_assignment'] if module_id == 'GLOBAL' else m['assignments'][assignment_id]
    require(not a['closed'] and a['assignment_id'] == assignment_id, 'active assignment required')
    import test_validation as tv
    selected = tv.paths(m, a['test_scope']) if module_id != 'GLOBAL' and tv.split(m) else m['plan']['paths']
    paths = {p['path_id']:p for p in selected}
    rows = {}
    for receipt_ref in receipts:
        r = read_json(check_ref(receipt_ref))
        for key, value in {'run_id':s['run_id'], 'module_id':module_id, 'assignment_id':assignment_id,
                           'actor_instance_id':a['instance_id'], 'freeze_id':m['freeze_id'], 'code_baseline':m['code_baseline']}.items():
            require(r.get(key) == value, f'receipt {key} mismatch')
        pid = r['path_id']
        require(pid in paths and pid not in rows, 'unknown/duplicate receipt path; do not pick the best attempt')
        row = {'path_id':pid, 'test_run_id':r['test_run_id'], 'execution_receipt':receipt_ref}
        row.update(interpret(r, paths[pid]))
        previous = m.get('results',{}).get(pid)
        if previous: row['retest_of'] = previous['test_run_id']
        rows[pid] = row
    require(set(rows) == set(paths), 'provide one host receipt for every frozen path; do not shrink coverage')
    result = {'schema_version':1, 'kind':'tests', 'run_id':s['run_id'], 'module_id':module_id,
              'assignment_id':assignment_id, 'actor_instance_id':a['instance_id'],
              'freeze_id':m['freeze_id'], 'code_baseline':m['code_baseline'], 'paths':list(rows.values())}
    if module_id == 'GLOBAL': result['snapshot'] = a['snapshot']
    return result


def save(root, output, result):
    path = harmony_output(root, output, 'sandbox')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as f: json.dump(result, f, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('root','module','assignment','output'): p.add_argument('--'+key, required=True)
    p.add_argument('--receipt', action='append', required=True)
    args = p.parse_args()
    result = build(args.root, args.module, args.assignment, [file_ref(p) for p in args.receipt])
    save(args.root, args.output, result)
