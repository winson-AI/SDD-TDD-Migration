"""Frozen test inputs shared by module execution and whole-task audit retests."""
from pathlib import Path
import re
from contracts import Rejected, check_ref, digest, keyed, marked, nonempty, read_json, require

KINDS = ('script', 'fixture', 'adapter', 'test-source')


def assets(result):
    rows = result.get('test_assets', [])
    require(isinstance(rows, list), 'test_assets must be a list')
    indexed = keyed(rows, 'asset_id') if rows else {}
    paths = keyed(result.get('paths'), 'path_id')
    directory = check_ref(result['design_ref']).parent
    for asset in indexed.values():
        require(asset.get('kind') in KINDS, 'unknown test asset kind')
        require(check_ref(asset.get('ref')).is_relative_to(directory), 'test asset outside designer staging directory')
        pids = set(nonempty(asset.get('path_ids'), 'test asset PATHs'))
        require(pids <= set(paths), 'test asset references unknown PATH')
        require(not {'actual', 'passed', 'executed', 'quality'}.intersection(asset), 'prepared test asset cannot claim execution')
        if asset['kind'] == 'test-source':
            test_source(asset, {pid: paths[pid] for pid in pids})
        if asset['kind'] == 'script':
            pairs = nonempty(asset.get('assertions'), 'test script assertion mapping')
            require({p.get('path_id') for p in pairs} == pids, 'test script must map each declared PATH')
            for pair in pairs:
                require(pair.get('assertion_id') in {a['assertion_id'] for a in paths[pair['path_id']]['expected_assertions']},
                        'test script references unknown assertion')
    return list(indexed.values())


def test_source(asset, paths):
    """A test written from the SPEC before the code and frozen with it: it defines every required test it names, maps
    each to a scenario, declares the production symbols it calls, lands verbatim at target_path, and the unit PATHs it
    binds require only tests it defines."""
    require(isinstance(asset.get('target_path'), str) and Path(asset['target_path']).is_absolute(), 'test source needs an absolute target_path in the module write scope')
    ids = nonempty(asset.get('required_test_ids'), 'test source required_test_ids')
    require(all(isinstance(i, str) and i.count('#') == 1 and all(i.split('#')) for i in ids) and len(set(ids)) == len(ids),
            'required_test_ids must be unique classname#name values')
    require(not marked(asset['ref']), 'unfilled skeleton field left in ' + Path(asset['ref']['path']).name)
    text = check_ref(asset['ref']).read_text(errors='replace')
    for tid in ids:
        cls, name = tid.split('#')
        require(re.search(r'\bclass\s+' + re.escape(cls.rsplit('.', 1)[-1]) + r'\b', text) and re.search(r'\b' + re.escape(name) + r'\s*\(', text),
                'test source does not define ' + tid)
    rows = asset.get('scenarios')
    require(isinstance(rows, list) and rows and all(isinstance(r, dict) and r.get('scenario_id') and r.get('test_id') in ids for r in rows),
            'test source maps each scenario to one of its required tests')
    for symbol in asset.get('symbols') or []:
        require(isinstance(symbol, str) and symbol and symbol in text, 'declared production symbol not used in the test source: ' + str(symbol))
    for pid, path in paths.items():
        policy = path.get('unit_report') or {}
        require(policy.get('required_test_ids') and set(policy['required_test_ids']) <= set(ids),
                'a test source binds a PATH whose unit_report requires only tests it defines: ' + pid)


def sources_delivered(module, task_ids, code_files):
    """The task that holds a frozen test source's PATH delivers the file verbatim at target_path."""
    design = source(module)
    if not design:
        return
    delivered = {str(Path(r['path']).resolve()): r['sha256'] for r in code_files}
    tasks = {t['task_id']: set(t.get('path_ids', [])) for t in module['plan']['tasks']}
    for asset in assets(read_json(check_ref(design['test_design_ref']))):
        if asset['kind'] == 'test-source' and any(set(asset['path_ids']) & tasks.get(tid, set()) for tid in task_ids):
            require(delivered.get(str(Path(asset['target_path']).resolve())) == asset['ref']['sha256'],
                    'frozen test source missing or changed at ' + asset['target_path'] + '; a test is revised by a change request, not by the implementer')


def frozen_sources(binding):
    """{path, sha256} of the frozen test sources a PATH binds, as the freeze holds them."""
    return [{'path': a['target_path'], 'sha256': a['ref']['sha256']} for a in (binding or {}).get('assets', []) if a['kind'] == 'test-source']


def preparation(result, required=False, freezing=False):
    prepared = assets(result)
    for path in result['paths']:
        review = path.get('preparation')
        require(review is not None or not required, 'test PATH preparation review required')
        if review is None: continue
        require(review.get('status') in ('existing', 'prepared', 'deferred') and review.get('reason'), 'test preparation status/reason required')
        for ref in nonempty(review.get('evidence_refs'), 'test preparation evidence'): check_ref(ref)
        ids = {a['asset_id'] for a in prepared if path['path_id'] in a['path_ids']}
        require(set(review.get('asset_ids', [])) == ids, 'test preparation asset coverage mismatch')
        require(review['status'] != 'prepared' or ids, 'prepared PATH needs test assets')
        if review['status'] == 'deferred':
            require(review.get('owner') and review.get('next_action'), 'deferred preparation needs owner/next_action')
            require(not freezing, 'resolve deferred test preparation before freeze')


def source(module):
    ref = (module.get('plan') or {}).get('test_design_ref')
    return {'module_id': module['module_id'], 'freeze_id': module['freeze_id'], 'test_design_ref': ref,
            'contract_version': module['plan'].get('test_asset_contract_version', 0)} if ref else None


def binding(module, path):
    owner = (module.get('path_test_sources') or {}).get(path['path_id']) if 'path_test_sources' in module else source(module)
    if not owner: return None
    result = read_json(check_ref(owner['test_design_ref']))
    require(result.get('module_id') == owner['module_id'], 'test asset design belongs to another module')
    if owner['module_id'] == 'GLOBAL':
        require(result.get('actor_instance_id'), 'GLOBAL test design author required')
    designed = next((p for p in result['paths'] if p['path_id'] == path['path_id']), None)
    require(designed and designed['expected_assertions'] == path['expected_assertions'], 'test assets bound to different PATH/assertions')
    return {**owner, 'assets': [a for a in assets(result) if path['path_id'] in a['path_ids']]}


def usage(binding, argv, usage_file):
    """Direct entrypoints are host-observed; other consumption is executor-reported, hash-bound evidence."""
    selected = (binding or {}).get('assets', [])
    direct = [a['asset_id'] for a in selected if a['kind'] in ('script', 'adapter') and a['ref']['path'] in argv]
    try:
        reported = read_json(usage_file) if usage_file.is_file() else []
        require(isinstance(reported, list), 'test asset usage must be a list of asset_id/ref')
        for row in reported:
            require(any(row == {'asset_id': a['asset_id'], 'ref': a['ref']} for a in selected), 'test asset usage outside frozen inputs')
            check_ref(row['ref'])
    except (Rejected, OSError, ValueError, KeyError, TypeError) as exc:
        return {'entrypoint_ids': direct, 'reported_ids': [], 'error': str(exc)}
    return {'entrypoint_ids': direct, 'reported_ids': [r['asset_id'] for r in reported]}


def validate_receipt(module, path, receipt, quality):
    expected = binding(module, path)
    if not expected: return
    query = read_json(check_ref(receipt['query_ref']))
    require(query.get('frozen_test_assets', []) == expected['assets'], 'execution omitted/changed frozen test assets')
    if not expected['contract_version']: return  # Historical freezes retain their original receipt contract.
    require(receipt.get('test_asset_binding') == expected and query.get('test_asset_binding') == expected,
            'test asset source/freeze binding mismatch')
    usage_ref = receipt.get('test_asset_usage_ref')
    usage_file = check_ref(usage_ref) if usage_ref else Path(receipt['query_ref']['path']).parent / 'test-assets-used.json'
    require(usage_file.resolve() == (Path(receipt['query_ref']['path']).parent / 'test-assets-used.json').absolute(),
            'test asset usage outside execution directory')
    require(bool(usage_ref) == usage_file.is_file(), 'test asset usage receipt missing')
    observed = usage(expected, receipt.get('requested_argv', receipt['argv']), usage_file)
    require(receipt.get('test_asset_usage') == observed, 'test asset usage changed')
    if quality == 'green-passed':
        require(not observed.get('error'), 'Green requires valid test asset usage evidence')
        require({a['asset_id'] for a in expected['assets'] if a['kind'] != 'test-source'} <= set(observed['entrypoint_ids'] + observed['reported_ids']),
                'Green requires evidence of frozen test asset consumption')
    require(receipt.get('frozen_test_sources', []) == frozen_sources(expected), 'frozen test sources differ from the freeze')


def global_authors(state):
    return {read_json(check_ref(p['test_design_ref']))['actor_instance_id'] for p in state.get('global_paths', [])
            if p.get('test_design_ref')}
