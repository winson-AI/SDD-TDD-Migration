"""The frozen query a web PATH runs in the built-in web Main: deterministic steps on a served page, and after a step
the predicates the DOM must satisfy, or the screen the user showed. Nothing here is inferred from the implementation."""
import re

ACTIONS = {'goto': ('url',), 'click': ('selector',), 'fill': ('selector', 'text'), 'press': ('key',), 'wait': ('ms',)}
PREDICATES = {'text': True, 'value': True, 'visible': True, 'count': True, 'url': False, 'title': False}  # needs a selector
COMPARISONS = ('equals', 'contains', 'matches')
DEFAULT_TOLERANCE = 80  # the visual score (0..100) a candidate screen must reach against the user's screenshot


def _fail(message):
    raise ValueError(message)


def validate_step(step, number):
    if not isinstance(step, dict) or step.get('action') not in ACTIONS:
        _fail(f'step {number}: a web step is an object whose action is one of ' + ', '.join(ACTIONS))
    fields = ACTIONS[step['action']]
    extra = set(step) - {'action', *fields}
    if extra:
        _fail(f'step {number}: unknown fields ' + ', '.join(sorted(extra)))
    for field in fields:
        value = step.get(field)
        if field == 'ms':
            if type(value) is not int or not 0 < value <= 30_000: _fail(f'step {number}: ms is an integer of at most 30000')
        elif not isinstance(value, str) or not value.strip():
            _fail(f'step {number}: {field} is a non-empty string')
    if step['action'] == 'goto' and not step['url'].startswith(('http://', 'https://')):
        _fail(f'step {number}: goto takes an absolute http(s) url')


def validate_predicate(aid, predicate):
    if not isinstance(predicate, dict) or predicate.get('kind') not in PREDICATES:
        _fail(f'{aid}: predicate.kind is one of ' + ', '.join(PREDICATES))
    if PREDICATES[predicate['kind']] and not (isinstance(predicate.get('selector'), str) and predicate['selector'].strip()):
        _fail(f'{aid}: a {predicate["kind"]} predicate names its selector')
    given = [c for c in COMPARISONS if c in predicate]
    if predicate['kind'] == 'visible':
        if given or set(predicate) - {'kind', 'selector'}: _fail(f'{aid}: a visible predicate takes only its selector')
        return
    if len(given) != 1:
        _fail(f'{aid}: one of ' + ', '.join(COMPARISONS) + ' states the expected ' + predicate['kind'])
    value = predicate[given[0]]
    if predicate['kind'] == 'count':
        if given[0] != 'equals' or type(value) is not int or value < 0: _fail(f'{aid}: count equals a non-negative integer')
    elif not isinstance(value, str):
        _fail(f'{aid}: {given[0]} takes a string')
    if given[0] == 'matches':
        try: re.compile(value)
        except re.error: _fail(f'{aid}: matches takes a valid regular expression')


def validate_query(q):
    if q.get('platform') != 'web' or q.get('task_type', 'test') != 'test':
        _fail('web platform and task_type test required')
    for key in ('run_id', 'module_id', 'path_id', 'name', 'freeze_id', 'code_baseline'):
        if not q.get(key): _fail(f'missing frozen query {key}')
    steps, assertions = q.get('steps'), q.get('expected_assertions', [])
    if not isinstance(steps, list) or not steps or not assertions:
        _fail('steps and nonempty assertions required')
    for number, step in enumerate(steps, 1):
        validate_step(step, number)
    if steps[0]['action'] != 'goto':
        _fail('the first step opens the page: goto')
    ids = set()
    for a in assertions:
        aid = a.get('assertion_id', '')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', aid) or aid in ids: _fail('unique assertion IDs required')
        ids.add(aid)
        if a.get('expected') is not True or not a.get('description'):
            _fail(f'{aid}: a web predicate is frozen with expected=true and a description; request a SPEC change for other observations')
        if a.get('matcher') != 'exact': _fail(f'{aid}: the web Main matches exactly (matcher=exact)')
        if type(a.get('after_step')) is not int or not 1 <= a['after_step'] <= len(steps):
            _fail(f'{aid}: after_step must reference a frozen step')
        verification, picture = a.get('verification'), a.get('reference_media_ref')
        if verification == 'dom':
            validate_predicate(aid, a.get('predicate'))
        elif verification == 'refer_image_assert':
            if not (isinstance(picture, dict) and isinstance(picture.get('path'), str) and picture['path']
                    and isinstance(picture.get('sha256'), str) and re.fullmatch(r'[0-9a-f]{64}', picture['sha256'])):
                _fail(f'{aid}: refer_image_assert needs reference_media_ref {{path, sha256}}, the user screenshot the Ledger bound')
            tolerance = a.get('tolerance', DEFAULT_TOLERANCE)
            if type(tolerance) not in (int, float) or not 0 <= tolerance <= 100: _fail(f'{aid}: tolerance is a score in 0..100')
        else:
            _fail(f'{aid}: verification is dom (a predicate on the page) or refer_image_assert (the user screenshot)')
    return q
