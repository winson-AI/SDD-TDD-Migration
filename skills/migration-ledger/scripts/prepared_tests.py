"""Frozen test inputs shared by module execution and whole-task audit retests."""
from pathlib import Path
from contracts import Rejected, check_ref, keyed, nonempty, read_json, require


def assets(result):
    rows = result.get('test_assets', [])
    require(isinstance(rows, list), 'test_assets must be a list')
    indexed = keyed(rows, 'asset_id') if rows else {}
    paths = keyed(result.get('paths'), 'path_id')
    directory = check_ref(result['design_ref']).parent
    for asset in indexed.values():
        require(asset.get('kind') in ('script', 'fixture', 'adapter'), 'unknown test asset kind')
        require(check_ref(asset.get('ref')).is_relative_to(directory), 'test asset outside designer staging directory')
        pids = set(nonempty(asset.get('path_ids'), 'test asset PATHs'))
        require(pids <= set(paths), 'test asset references unknown PATH')
        require(not {'actual', 'passed', 'executed', 'quality'}.intersection(asset), 'prepared test asset cannot claim execution')
        if asset['kind'] == 'script':
            pairs = nonempty(asset.get('assertions'), 'test script assertion mapping')
            require({p.get('path_id') for p in pairs} == pids, 'test script must map each declared PATH')
            for pair in pairs:
                require(pair.get('assertion_id') in {a['assertion_id'] for a in paths[pair['path_id']]['expected_assertions']},
                        'test script references unknown assertion')
    return list(indexed.values())


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
        require({a['asset_id'] for a in expected['assets']} <= set(observed['entrypoint_ids'] + observed['reported_ids']),
                'Green requires evidence of frozen test asset consumption')


def global_authors(state):
    return {read_json(check_ref(p['test_design_ref']))['actor_instance_id'] for p in state.get('global_paths', [])
            if p.get('test_design_ref')}
