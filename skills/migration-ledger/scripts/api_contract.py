"""Scoped API inventory rides the existing dimension -> TASK -> PATH evidence chain."""
from pathlib import Path
from contracts import check_ref, keyed, nonempty, read_json, require

FACETS = ('request_fields', 'response_fields', 'error_outcomes', 'state_effects')
MAPPINGS = ('request_mapping', 'response_mapping', 'error_mapping', 'state_mapping')
METHODS = ('GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS')
# How a call is addressed. A remote procedure or a client library has no method and URL: it is called by an operation name.
ROUTES = {'http': ('method', 'url'), 'rpc': ('operation',), 'sdk': ('operation',)}


def route(row, side):
    transport = row.get('transport', 'http')
    require(transport in ROUTES, 'API transport must be http, rpc or sdk')
    if transport == 'http':
        require(row.get('method') in METHODS and row.get('url'), 'API ' + side + ' method/URL required')
    else:
        require(isinstance(row.get('operation'), str) and row['operation'].strip(), 'API ' + side + ' operation required for ' + transport)
    return (transport, *(row[key] for key in ROUTES[transport]))


def applicability(analysis, required=False):
    review = analysis.get('api_review')
    if review is None:
        require(not required, 'API applicability review required')
        return
    require(review.get('status') in ('applicable', 'not-applicable') and review.get('reason'), 'API applicability status/reason required')
    for ref in nonempty(review.get('evidence_refs'), 'API applicability evidence'): check_ref(ref)
    if review.get('discovery_refs') is not None:
        for ref in nonempty(review['discovery_refs'], 'API discovery scope'): check_ref(ref)
    require((review['status'] == 'applicable') == bool(analysis.get('api_inventory_ref')), 'API applicability and inventory disagree')


def read(analysis, items):
    """The recorded calls and the contracts of an accepted inventory, each contract with the item that owns it."""
    ref = analysis.get('api_inventory_ref')
    if not ref:
        return {}, {}
    inventory = read_json(check_ref(ref))
    owners = {aid: iid for iid, item in items.items() for aid in item.get('api_ids', [])}
    return ({row['api_id']: row for row in inventory.get('calls') or []},
            {row['api_id']: {**row, 'item_id': owners.get(row['api_id'])} for row in inventory.get('contracts') or []})


def load(analysis, items):
    """Judge an inventory the Ledger is asked to register, then read it."""
    applicability(analysis)
    ref = analysis.get('api_inventory_ref')
    if not ref:
        require(not any(item.get('api_ids') for item in items.values()), 'API items need api_inventory_ref')
        return {}, {}
    inventory = read_json(check_ref(ref))
    require(inventory.get('schema_version') == 1 and inventory.get('module_id') == analysis['module_id'], 'API inventory scope/schema mismatch')
    calls = keyed(nonempty(inventory.get('calls'), 'recorded API calls'), 'api_id')
    for source in calls.values():
        route(source, 'source')
        require(source.get('source_symbol'), 'API source production symbol required')
        check_ref(source.get('source_ref'))
        reviewed = (analysis.get('api_review') or {}).get('discovery_refs')
        if reviewed is not None:
            require(any(all(ref[k] == source['source_ref'][k] for k in ('path', 'sha256')) for ref in reviewed),
                    'recorded API source missing from reviewed discovery scope')
        for facet in FACETS:
            require(isinstance(source.get(facet), list) and all(isinstance(field, str) and field for field in source[facet]) and
                    len(set(source[facet])) == len(source[facet]), 'API source facet must list explicit unique obligations')
    for field in ('contracts', 'exclusions'):
        require(isinstance(inventory.get(field), list), 'API ' + field + ' must be an explicit list')
    contracts = keyed(inventory['contracts'], 'api_id') if inventory['contracts'] else {}
    excluded = keyed(inventory['exclusions'], 'api_id') if inventory['exclusions'] else {}
    require(set(contracts).isdisjoint(excluded) and set(contracts) | set(excluded) == set(calls), 'API call closure incomplete or duplicated')
    for row in excluded.values():
        require(row.get('reason'), 'API exclusion needs a source scope rationale')
        for evidence in nonempty(row.get('evidence_refs'), 'API exclusion evidence'): check_ref(evidence)
    owners = {}
    for iid, item in items.items():
        for aid in item.get('api_ids', []):
            require(item['dimension'] in ('Logic', 'Adhesive') and aid in contracts and aid not in owners, 'API needs one Logic/Adhesive owner')
            owners[aid] = iid
    require(set(owners) == set(contracts), 'API contract missing dimension ownership')
    for aid, row in contracts.items():
        source, target = calls[aid], row.get('target', {})
        check_ref(row.get('fixture_contract_ref'))
        addressed = route(target, 'target')
        require(isinstance(target.get('consumer'), str) and '#' in target['consumer'] and
                Path(target['consumer'].split('#', 1)[0]).is_absolute() and target['consumer'].split('#', 1)[1], 'API target needs absolute consumer#symbol')
        for facet, mapping in zip(FACETS, MAPPINGS):
            require(isinstance(target.get(mapping), dict) and set(target[mapping]) == set(source[facet]) and
                    all(isinstance(value, str) and value for value in target[mapping].values()), 'API mapping omits a source obligation: ' + mapping)
        require(row.get('fidelity') in ('exact', 'approved-adaptation'), 'API fidelity must be explicit')
        if row['fidelity'] == 'exact':
            require(route(source, 'source') == addressed, 'API exact route changed')
        else:
            require(row.get('alternative') and row.get('reason'), 'API adaptation needs approved alternative and rationale')
        row = dict(row); row['item_id'] = owners[aid]; contracts[aid] = row
    return calls, contracts


def obligations(aid, source):
    return {aid + '/' + facet + ':' + field for facet in FACETS for field in source[facet]} | {aid + '/route'}


def plan(analysis, items, plan):
    calls, contracts = read(analysis, items)
    traces = {row['item_id']: row for row in plan.get('dimension_trace', [])}
    paths = {row['path_id']: row for row in plan['paths']}
    for aid, contract in contracts.items():
        covered = set()
        for pair in traces[contract['item_id']]['assertions']:
            declared = pair.get('api_obligations', [])
            if not declared:
                continue
            path = paths[pair['path_id']]
            require(path.get('kind', 'automation') in ('unit', 'automation'), 'API fidelity requires actual behavior tests')
            require(path.get('fixture_contract_ref') == contract['fixture_contract_ref'], 'API tests must bind the frozen fixture contract')
            covered.update(declared)
        require(obligations(aid, calls[aid]) <= covered, 'API behavior assertion coverage incomplete: ' + aid)
        require(contract['fidelity'] == 'exact' or contract['alternative'] in plan['decision_envelope']['allowed_alternatives'], 'API adaptation outside decision envelope')


def adaptations(module):
    """{api_id: alternative} of the contracts a registered allocation adapts instead of keeping exact."""
    ref = (module.get('plan') or {}).get('dimension_analysis_ref') or module.get('dimension_analysis_ref')
    if not ref:
        return {}
    import dimensions
    _, contracts = read(*dimensions.load(ref, module['module_id']))
    return {aid: row['alternative'] for aid, row in contracts.items() if row['fidelity'] != 'exact'}


def undecided(s, wanted):
    """The adaptations among `wanted` that no human decision of the run names with the same alternative. A human decides
    an adaptation once, for the contract: every leaf that holds the contract then freezes without asking again."""
    held = {aid: alternative for d in s['decisions'].values() if d.get('kind') == 'api-adaptation'
            for aid, alternative in d['adaptations'].items()}
    return {aid: alternative for aid, alternative in wanted.items() if held.get(aid) != alternative}


def registered(s):
    """Every adaptation the run's root allocations hold; a child's contracts are its parent's."""
    found = {}
    for module in (m for m in {**s.get('module_groups', {}), **s['modules']}.values() if not m.get('parent_module_id')):
        found.update(adaptations(module))
    return found


def decision(s, payload):
    """A human decision of kind api-adaptation: it names registered contracts and the alternative of each."""
    named = payload.get('adaptations')
    require(isinstance(named, dict) and named and payload.get('module_id') is None, 'api-adaptation decision names contracts for the run')
    held = registered(s)
    require(all(held.get(aid) == alternative for aid, alternative in named.items()),
            'api-adaptation decision names a contract or alternative the run has not registered')
    from contracts import digest
    require(payload['subject_sha256'] == digest(named), 'api-adaptation decision must hash the adaptations it names')


def freeze(s, m, payload):
    pending = undecided(s, adaptations(m))
    if not pending:
        return
    decision = s['decisions'].get(payload.get('decision_id'), {})
    exact = decision.get('module_id') == m['module_id'] and decision.get('subject_sha256') == m['plan_hash'] and not decision.get('consumed')
    enveloped = decision.get('kind') == 'batch-envelope' and decision.get('module_id') == m.get('parent_module_id') and \
        read_json(check_ref(decision['envelope_ref']))['children'].get(m['module_id']) == m['plan']['decision_envelope']
    require(exact or enveloped, 'API adaptation requires exact Human decision, the parent\'s batch envelope, or a run '
            'decision of kind api-adaptation naming: ' + ', '.join(sorted(pending)))


def implementation(analysis, items, result):
    _, contracts = read(analysis, items)
    evidence = {row['item_id']: row for row in result.get('dimension_evidence', [])}
    code = {check_ref(ref).resolve() for ref in result.get('code_files', [])}
    from contracts import named
    for row in contracts.values():
        path, symbol = row['target']['consumer'].split('#', 1)
        target = Path(path).resolve()
        refs = evidence[row['item_id']].get('consumer_refs', [])
        require(target in code and target in {check_ref(ref).resolve() for ref in refs}, 'API binding lacks submitted production consumer evidence')
        require(named(target.read_text(), symbol), 'API target consumer does not name frozen production symbol')
