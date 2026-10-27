"""Scoped data inventory rides the same dimension -> TASK -> PATH evidence chain as the API inventory: where each field
of an entity comes from, under what conditions it is fetched, how a derived field is computed and when it goes stale are
explicit obligations; the leaf's target binds each one and its tests prove each one under the shared fixture."""
from pathlib import Path
from contracts import check_ref, keyed, nonempty, owed, read_json, require

FACETS = ('sources', 'fetch_conditions', 'derived_fields', 'invalidation')
MAPPINGS = ('source_mapping', 'fetch_mapping', 'compute_mapping', 'invalidation_mapping')
DECISIONS = ('refactor', 'adapt')  # what a leaf does with a target that already fetches or computes the same data another way


def applicability(analysis, required=False):
    review = analysis.get('data_review')
    if review is None:
        require(not required, 'data applicability review required')
        return
    require(review.get('status') in ('applicable', 'not-applicable') and review.get('reason'), 'data applicability status/reason required')
    for ref in nonempty(review.get('evidence_refs'), 'data applicability evidence'): check_ref(ref)
    require((review['status'] == 'applicable') == bool(analysis.get('data_inventory_ref')), 'data applicability and inventory disagree')


def read(analysis, items):
    """The recorded entities and the contracts of an accepted inventory, each contract with the item that owns it."""
    ref = analysis.get('data_inventory_ref')
    if not ref:
        return {}, {}
    inventory = read_json(check_ref(ref))
    owners = {did: iid for iid, item in items.items() for did in item.get('data_ids', [])}
    return ({row['data_id']: row for row in inventory.get('entities') or []},
            {row['data_id']: {**row, 'item_id': owners.get(row['data_id'])} for row in inventory.get('contracts') or []})


def entity_row(source):
    """A recorded entity: its production symbol and source, and explicit unique obligations per facet; its fields come from somewhere."""
    require(source.get('source_symbol'), 'data source production symbol required')
    check_ref(source.get('source_ref'))
    for facet in FACETS:
        require(isinstance(source.get(facet), list) and all(isinstance(x, str) and x for x in source[facet])
                and len(set(source[facet])) == len(source[facet]), 'data source facet must list explicit unique obligations: ' + facet)
    require(source['sources'], 'a data entity names where its fields come from: sources')


def load(analysis, items):
    """Judge an inventory the Ledger is asked to register, then read it."""
    applicability(analysis)
    ref = analysis.get('data_inventory_ref')
    if not ref:
        require(not any(item.get('data_ids') for item in items.values()), 'data items need data_inventory_ref')
        return {}, {}
    inventory = read_json(check_ref(ref))
    require(inventory.get('schema_version') == 1 and inventory.get('module_id') == analysis['module_id'], 'data inventory scope/schema mismatch')
    entities = keyed(nonempty(inventory.get('entities'), 'recorded data entities'), 'data_id')
    for source in entities.values():
        entity_row(source)
    for field in ('contracts', 'exclusions'):
        require(isinstance(inventory.get(field), list), 'data ' + field + ' must be an explicit list')
    contracts = keyed(inventory['contracts'], 'data_id') if inventory['contracts'] else {}
    excluded = keyed(inventory['exclusions'], 'data_id') if inventory['exclusions'] else {}
    require(set(contracts).isdisjoint(excluded) and set(contracts) | set(excluded) == set(entities), 'data entity closure incomplete or duplicated')
    for row in excluded.values():
        owed(row.get('reason'), 'data exclusion needs a source scope rationale')
        for evidence in nonempty(row.get('evidence_refs'), 'data exclusion evidence'): check_ref(evidence)
    owners = {}
    for iid, item in items.items():
        for did in item.get('data_ids', []):
            require(item['dimension'] in ('Logic', 'Adhesive') and did in contracts and did not in owners, 'data needs one Logic/Adhesive owner')
            owners[did] = iid
    require(set(owners) == set(contracts), 'data contract missing dimension ownership')
    for did, row in contracts.items():
        source, target = entities[did], row.get('target')
        if row.get('fixture_contract_ref') is not None:
            check_ref(row['fixture_contract_ref'])
        # How the target holds the data and what it is tested against are the leaf's: an allocation may leave both open.
        if target is not None:
            repository = target.get('repository')
            require(isinstance(repository, str) and '#' in repository and Path(repository.split('#', 1)[0]).is_absolute()
                    and repository.split('#', 1)[1], 'data target needs absolute repository#symbol')
            for facet, mapping in zip(FACETS, MAPPINGS):
                owed(isinstance(target.get(mapping), dict) and set(target[mapping]) == set(source[facet]) and
                     all(isinstance(value, str) and value for value in target[mapping].values()), 'data mapping omits a source obligation: ' + mapping)
        owed(row.get('fidelity') in ('exact', 'approved-adaptation'), 'data fidelity must be explicit')
        if row.get('fidelity') != 'exact':
            owed(row.get('alternative') and row.get('reason'), 'data adaptation needs approved alternative and rationale')
        existing = row.get('existing_target')
        if existing is not None:  # the target already fetches or computes this data: one way survives, by decision
            owed(isinstance(existing, dict) and existing.get('symbol') and existing.get('divergence') and existing.get('decision') in DECISIONS
                 and existing.get('reason'), 'a target that already holds this data needs its symbol, the divergence and a refactor/adapt decision with a reason')
        row = dict(row); row['item_id'] = owners[did]; contracts[did] = row
    return entities, contracts


def obligations(did, source):
    return {did + '/' + facet + ':' + field for facet in FACETS for field in source[facet]}


def plan(analysis, items, plan):
    entities, contracts = read(analysis, items)
    traces = {row['item_id']: row for row in plan.get('dimension_trace', [])}
    paths = {row['path_id']: row for row in plan['paths']}
    for did, contract in contracts.items():
        covered = set()
        trace = traces.get(contract['item_id'])  # an item the plan does not trace yet owes its coverage
        for pair in (trace or {}).get('assertions', []):
            declared = pair.get('data_obligations', [])
            if not declared:
                continue
            path = paths[pair['path_id']]
            if path.get('kind', 'automation') not in ('unit', 'automation'):
                owed(False, 'data fidelity requires actual behavior tests'); continue
            require(contract.get('fixture_contract_ref') is None or path.get('fixture_contract_ref') == contract['fixture_contract_ref'],
                    'data tests must bind the frozen fixture contract')
            covered.update(declared)
        owed(obligations(did, entities[did]) <= covered, 'data behavior assertion coverage incomplete: ' + did)
        require(contract['fidelity'] == 'exact' or contract['alternative'] in plan['decision_envelope']['allowed_alternatives'], 'data adaptation outside decision envelope')


def consumer_files(module):
    """A data contract's target side is a named production repository or model file the module writes or the target
    already holds, settled with its fixture before freeze."""
    ref = (module.get('plan') or {}).get('dimension_analysis_ref') or module.get('dimension_analysis_ref')
    if not ref:
        return
    import dimensions
    _, contracts = read(*dimensions.load(ref, module['module_id']))
    scope = [Path(path).resolve() for path in module.get('write_paths') or []]
    for did, row in contracts.items():
        require(row.get('target') and row.get('fixture_contract_ref'),
                did + ": the plan settles a data contract's target side and fixture before freeze; its allocation left that to the leaf")
        repository = row['target']['repository']
        path = Path(repository.split('#', 1)[0])
        require(path.suffix and not path.is_dir(), did + ': a data repository is a production file, not a directory: ' + repository)
        require(not scope or path.is_file() or any(path.resolve().is_relative_to(base) for base in scope),
                did + ': a data repository is a file this module writes or the target already holds: ' + repository)


def freeze(s, m):
    consumer_files(m)


def implementation(analysis, items, result):
    _, contracts = read(analysis, items)
    evidence = {row['item_id']: row for row in result.get('dimension_evidence', [])}
    code = {check_ref(ref).resolve() for ref in result.get('code_files', [])}
    from contracts import named
    for row in contracts.values():
        path, symbol = row['target']['repository'].split('#', 1)
        target = Path(path).resolve()
        refs = evidence.get(row['item_id'], {}).get('consumer_refs', [])
        require(target in code and target in {check_ref(ref).resolve() for ref in refs}, 'data binding lacks submitted production repository evidence')
        require(named(target.read_text(), symbol), 'data target repository does not name frozen production symbol')
