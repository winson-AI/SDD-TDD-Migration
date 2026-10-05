"""Parameters reach the target as a generated file: values are written once by a tool and used by their key.

The sheet says what the legacy UI gives each component and layer. A module's Spec decides only the
exceptions: a parameter that does not apply, a deviation a human approved, the value of a token, what an
expression becomes. Everything else is used as recorded. The file is rendered from the sheet, those
decisions and the project's templates, so its bytes are determined; acceptance regenerates it, compares,
and looks for every key in the submitted code. Nobody retypes a value.
"""
import json
from pathlib import Path
import re

from contracts import check_ref, named, read_json, require
import ui_parameters

TYPES = ('dimension', 'number', 'color', 'string')
LINE_FIELDS = ('key', 'value', 'unit', 'argb', 'quoted', 'id')
MODULE = '{module}'   # each module writes its own file, so two modules never overwrite each other's values
TEXT_LIMIT = 4 * 1024 * 1024


def _template(value, label, allowed):
    require(isinstance(value, str) and value, 'target_resources.parameters.' + label + ' must be a template string')
    names = re.findall(r'\{(\w*)\}', value)
    require(all(name in allowed for name in names) and value.count('{') == value.count('}') == len(names),
            'target_resources.parameters.' + label + ' may use only ' + ', '.join('{' + name + '}' for name in allowed))
    return value


def convention(value, target_root=None):
    """The project's statement of the file parameters are written to, one line per type, and how code names a key."""
    require(isinstance(value, dict) and set(value) <= {'file', 'header', 'footer', 'lines', 'accessor', 'locales', 'string_escapes'},
            'target_resources.parameters takes file, header, footer, lines, accessor, locales and string_escapes')
    def inside(path, label):
        require(isinstance(path, str) and Path(path).is_absolute() and MODULE in path,
                'target_resources.parameters.' + label + ' must be an absolute file path that contains ' + MODULE)
        resolved = Path(path).resolve()
        require(not target_root or resolved.is_relative_to(Path(target_root).resolve()),
                'target_resources.parameters.' + label + ' must lie inside target_root')
        return str(resolved)
    lines = value.get('lines')
    require(isinstance(lines, dict) and all(kind.split(':')[0] in TYPES for kind in lines) and set(TYPES) <= {kind.split(':')[0] for kind in lines},
            'target_resources.parameters.lines needs a line template for dimension, number, color and string')
    locales = value.get('locales', {})
    require(isinstance(locales, dict) and all(isinstance(name, str) and name for name in locales),
            'target_resources.parameters.locales maps a legacy locale qualifier to the file its texts are written to')
    escapes = value.get('string_escapes', {})
    require(isinstance(escapes, dict) and all(isinstance(k, str) and k and isinstance(v, str) for k, v in escapes.items()),
            'target_resources.parameters.string_escapes maps a character to what the target writes for it')
    for label in ('header', 'footer'):
        require(isinstance(value.get(label, ''), str), 'target_resources.parameters.' + label + ' must be text')
    return {'file': inside(value.get('file'), 'file'), 'header': value.get('header', ''), 'footer': value.get('footer', ''),
            'lines': {kind: _template(template, 'lines.' + kind, LINE_FIELDS) for kind, template in sorted(lines.items())},
            'accessor': _template(value.get('accessor'), 'accessor', ('key', 'module')),
            'locales': {name: inside(path, 'locales.' + name) for name, path in sorted(locales.items())},
            'string_escapes': dict(sorted(escapes.items()))}


def _value(value, label):
    require(isinstance(value, dict) and value.get('type') in TYPES and 'value' in value
            and (value['type'] != 'dimension' or isinstance(value.get('unit'), str)), label + ' needs a typed value (dimension with unit, number, color or string)')
    return {name: value[name] for name in ('type', 'value', 'unit') if name in value}


def declarations(analysis):
    """The exceptions a Spec states beside its sheet, structurally checked."""
    for row in analysis.get('dimensions', []):
        if row.get('dimension') == 'UI' and row.get('parameter_fill') is not None:
            fill = row['parameter_fill']
            require(isinstance(fill, dict) and set(fill) <= {'not_applicable', 'deviations', 'tokens', 'settled', 'runtime', 'structural'},
                    'parameter_fill takes not_applicable, deviations, tokens, settled, runtime and structural')
            for name in ('not_applicable', 'deviations', 'tokens', 'settled', 'runtime', 'structural'):
                require(isinstance(fill.get(name, []), list) and all(isinstance(entry, dict) for entry in fill.get(name, [])),
                        'parameter_fill.' + name + ' is a list of records')
            return fill
    return {}


def decisions(parameters, fill, allowed=None):
    """What happens to each parameter: {id: {'status', 'value'?}}; raises when a declaration names nothing or is malformed.

    `allowed` are the plan's approved alternatives; None skips that check (reading an already frozen plan)."""
    by_id = {p['id']: p for p in parameters}
    skipped = {}
    for row in fill.get('not_applicable', []):
        require(isinstance(row.get('reason'), str) and row['reason'].strip() and any(row.get(k) for k in ('ids', 'owner', 'name')),
                'a not_applicable record needs a reason and ids, an owner or a name')
        matched = [p['id'] for p in parameters if (not row.get('ids') or p['id'] in row['ids'])
                   and (not row.get('owner') or p['owner'] == row['owner']) and (not row.get('name') or p['name'] == row['name'])]
        require(matched and set(row.get('ids') or []) <= set(by_id), 'a not_applicable record names no recorded parameter: ' + str(row.get('ids') or row.get('owner') or row.get('name')))
        for ref in row.get('evidence_refs') or []:
            check_ref(ref)
        skipped.update({pid: row['reason'] for pid in matched})
    deviations = {}
    for row in fill.get('deviations', []):
        require(by_id.get(row.get('id'), {}).get('class') == 'value', 'a deviation names a recorded value parameter')
        require(isinstance(row.get('reason'), str) and row['reason'].strip(), row['id'] + ': deviation needs a reason')
        require(allowed is None or row.get('alternative') in allowed,
                row['id'] + ': deviation.alternative must be one of decision_envelope.allowed_alternatives, which a human approves with the plan')
        deviations[row['id']] = _value(row.get('value'), row['id'] + ': deviation')
    settled = {}
    for row in fill.get('settled', []):
        require(by_id.get(row.get('id'), {}).get('class') == 'expression', 'a settled record names a recorded expression')
        settled[row['id']] = _value(row.get('value'), row['id'] + ': settled expression')
    bindings = {}
    for field, kind in (('runtime', 'expression'), ('structural', 'keyword')):
        for row in fill.get(field, []):
            pid = row.get('id')
            require(by_id.get(pid, {}).get('class') == kind and pid not in bindings,
                    field + ' mapping must name one recorded ' + kind)
            require(isinstance(row.get('consumer'), str) and '#' in row['consumer']
                    and Path(row['consumer'].split('#', 1)[0]).is_absolute(), field + ' needs an absolute production consumer#accessor')
            require(row['consumer'].split('#', 1)[1].strip(), field + ' needs a target accessor')
            require(row.get('source_expression') == by_id[pid].get('text', by_id[pid].get('value')),
                    field + ' mapping differs from recorded source expression/keyword')
            require(row.get('reason') and row.get('evidence_refs') and row.get('assertions'), field + ' needs source evidence, rationale and frozen assertions')
            for ref in row['evidence_refs']: check_ref(ref)
            if field == 'runtime':
                require(isinstance(row.get('inputs'), list) and bool(row['inputs']), 'runtime mapping needs variable inputs')
            bindings[pid] = {'status': field, 'binding': row}
    require(not set(bindings) & (set(skipped) | set(settled)), 'parameter mapping cannot also be excluded or made constant')
    tokens = {}
    known = {p['token'] for p in parameters if p['class'] == 'token'}
    for row in fill.get('tokens', []):
        require(row.get('token') in known and row['token'] not in tokens, 'a token record names one token the sheet holds')
        require(('value' in row) != bool(row.get('accessor')), row['token'] + ': a token is given a value or the accessor of an existing target value')
        tokens[row['token']] = {'value': _value(row['value'], row['token'])} if 'value' in row else {'accessor': row['accessor']}
    require(not set(skipped) & (set(deviations) | set(settled)), 'a parameter is not applicable or decided, not both')
    result = {}
    for p in parameters:
        pid, kind = p['id'], p['class']
        if pid in skipped:
            result[pid] = {'status': 'not-applicable', 'reason': skipped[pid]}
        elif kind == 'value':
            result[pid] = ({'status': 'deviation', 'value': deviations[pid]} if pid in deviations else
                           {'status': 'used', 'value': {name: p[name] for name in ('type', 'value', 'unit') if name in p}})
        elif pid in bindings:
            result[pid] = bindings[pid]
        elif kind == 'expression':
            result[pid] = {'status': 'settled', 'value': settled[pid]} if pid in settled else {'status': 'unsettled'}
        elif kind == 'token':
            result[pid] = {'status': 'mapped', 'token': p['token'], **tokens[p['token']]} if p['token'] in tokens else {'status': 'unmapped', 'token': p['token']}
        else:
            result[pid] = {'status': {'keyword': 'structural'}.get(kind, kind)}
    return result


def gate(s, plan, analysis):
    """Freeze: the sheet is the derived one, every expression is settled, every token mapped, every exception well-formed."""
    document = ui_parameters.load(analysis)
    rules = (s.get('target_resources') or {}).get('parameters')
    if document is None:
        applicable = any(row.get('dimension') == 'UI' and row.get('status') == 'applicable' for row in analysis.get('dimensions', []))
        require(not (rules and applicable), 'the project states target_resources.parameters: a module with UI names its parameter_sheet_ref')
        require(not declarations(analysis), 'parameter_fill needs a parameter_sheet_ref')
        return
    ui_parameters.freeze_check(analysis)
    require(document.get('convention') == rules, 'parameter sheet was derived under another target parameter convention')
    decided = decisions(document['parameters'], declarations(analysis), (plan.get('decision_envelope') or {}).get('allowed_alternatives', []))
    paths = {p['path_id']: p for p in plan.get('paths', [])}
    for pid, row in decided.items():
        if row['status'] not in ('runtime', 'structural') or 'binding' not in row:
            continue
        binding = row['binding']
        require(Path(binding['consumer'].split('#', 1)[0]).resolve().is_relative_to(Path(s['target_root']).resolve()), 'parameter consumer outside target')
        for pair in binding['assertions']:
            path = paths.get(pair.get('path_id'), {})
            require(path.get('kind', 'automation') in ('unit', 'automation', 'visual') and
                    pair.get('assertion_id') in {a['assertion_id'] for a in path.get('expected_assertions', [])},
                    'parameter mapping needs a frozen behavioral assertion; build/static alone is not fidelity')
    if s.get('control_policy_version', 1) >= 2:
        for row in declarations(analysis).get('settled', []):
            require(row.get('constant_reason') and row.get('constant_evidence_refs'), 'runtime expression cannot become a constant without source proof')
            for ref in row['constant_evidence_refs']: check_ref(ref)
        structural_gaps = [pid for pid, row in decided.items() if row['status'] == 'structural' and 'binding' not in row]
        require(not structural_gaps, 'layout keywords need structural mapping: ' + ', '.join(structural_gaps[:8]))
    open_ids = sorted(pid for pid, row in decided.items() if row['status'] == 'unsettled')
    require(not open_ids, 'expressions the Spec must settle or mark not applicable: ' + ', '.join(open_ids[:8])
            + (' and ' + str(len(open_ids) - 8) + ' more' if len(open_ids) > 8 else ''))
    unmapped = sorted({row['token'] for row in decided.values() if row['status'] == 'unmapped'})
    require(not unmapped, 'tokens the Spec must map or mark not applicable: ' + ', '.join(unmapped[:8])
            + (' and ' + str(len(unmapped) - 8) + ' more' if len(unmapped) > 8 else ''))
    require(rules or not entries(document['parameters'], decided), 'writing parameters needs the project to state target_resources.parameters')


def entries(parameters, decided):
    """[(key, typed value, id)] the generated file holds: what is used, deviates or was settled, and tokens given a value."""
    found, tokens = [], {}
    for p in parameters:
        row = decided[p['id']]
        if row['status'] in ('used', 'deviation', 'settled'):
            found.append((ui_parameters.key(p['id']), row['value'], p['id']))
        elif row['status'] == 'mapped' and 'value' in row:
            tokens[row['token']] = row['value']
    found += [(ui_parameters.key('token:' + token), value, 'token:' + token) for token, value in tokens.items()]
    keys = [key for key, _, _ in found]
    require(len(set(keys)) == len(keys), 'two parameters share one key: ' + ', '.join(sorted({k for k in keys if keys.count(k) > 1})[:4]))
    return sorted(found)


def _line(rules, key, value, pid):
    kind = value['type']
    template = rules['lines'].get(kind + ':' + str(value.get('unit'))) or rules['lines'][kind]
    text = value['value']
    quoted = json.dumps(text, ensure_ascii=False) if kind == 'string' else ''
    for char, written in rules['string_escapes'].items():   # what the target's string syntax needs beyond JSON's
        quoted = quoted.replace(char, written)
    return template.format(key=key, id=pid, unit=value.get('unit') or '', value=text,
                           argb=text.lstrip('#') if kind == 'color' else '', quoted=quoted)


def render(document, fill):
    """{path: text} of every file the parameters are written to, determined by the sheet, the decisions and the templates."""
    rules, module = document.get('convention'), document.get('module_id') or ''
    require(rules, 'the parameter sheet carries no target convention')
    decided = decisions(document['parameters'], fill)
    rows = entries(document['parameters'], decided)
    place = lambda text: text.replace(MODULE, module)
    files = {place(rules['file']): place(rules['header']) + ''.join(_line(rules, key, value, pid) + '\n' for key, value, pid in rows)
             + place(rules['footer'])}
    texts = {p['id']: p for p in document['parameters'] if p['id'].startswith('values:string/')}
    for locale, path in rules['locales'].items():
        lines = [_line(rules, key, {'type': 'string', 'value': texts[pid]['variants'][locale]}, pid) + '\n'
                 for key, value, pid in rows if pid in texts and locale in texts[pid].get('variants', {})]
        files[place(path)] = place(rules['header']) + ''.join(lines) + place(rules['footer'])
    return files, [rules['accessor'].format(key=key, module=module) for key, _, _ in rows] + sorted(
        {row['accessor'] for row in decided.values() if row['status'] == 'mapped' and row.get('accessor')})


def verify_files(analysis):
    """Each generated file is in the target with exactly the bytes its sheet and decisions give."""
    document = ui_parameters.load(analysis)
    if document is None or not document.get('convention'):
        return [], []
    files, accessors = render(document, declarations(analysis))
    for path, text in files.items():
        target = Path(path)
        require(target.is_file() and target.read_text(encoding='utf-8') == text,
                'generated parameter file is missing or was edited: ' + path + '; write it again with resource-sync')
    return list(files), accessors


def verify(analysis, code_files):
    """Acceptance: the generated files are untouched and the submitted code names every key."""
    files, accessors = verify_files(analysis)
    document = ui_parameters.load(analysis)
    bindings = [row['binding'] for row in decisions(document['parameters'], declarations(analysis)).values() if 'binding' in row] if document else []
    submitted = {str(check_ref(ref).resolve()): ref for ref in code_files or []}
    for binding in bindings:
        path, accessor = binding['consumer'].split('#', 1)
        require(str(Path(path).resolve()) in submitted and named(Path(path).read_text(), accessor),
                'runtime/layout binding is missing from submitted production consumer')
    if not accessors:
        return
    skip = {str(Path(path).resolve()) for path in files}
    text = ''
    for ref in code_files or []:
        path = Path(ref['path'])
        if str(path.resolve()) not in skip and path.is_file() and path.stat().st_size <= TEXT_LIMIT:
            data = path.read_bytes()
            if b'\0' not in data[:4096]:
                text += data.decode('utf-8', errors='replace') + '\n'
    unused = [accessor for accessor in accessors if not named(text, accessor)]
    require(not unused, str(len(unused)) + ' recorded parameters are not used by the submitted code: ' + ', '.join(unused[:12])
            + (' …' if len(unused) > 12 else '') + '; use each by its key, or state in parameter_fill why it does not apply')


def summary(analysis, resolve=check_ref):
    """How a module's parameters are filled: counts by what was decided, and the share of values used as recorded."""
    document = ui_parameters.load(analysis, resolve)
    if document is None:
        return None
    decided = decisions(document['parameters'], declarations(analysis))
    counts = {}
    for row in decided.values():
        counts[row['status']] = counts.get(row['status'], 0) + 1
    owed = sum(counts.get(name, 0) for name in ('used', 'deviation', 'settled', 'mapped', 'not-applicable', 'unsettled', 'unmapped', 'runtime'))
    return {'parameters': len(decided), 'counts': dict(sorted(counts.items())),
            'components': len({p['owner'] for p in document['parameters'] if p['owner'].startswith(('layout:', 'code:'))}),
            'layers': len({p['owner'] for p in document['parameters'] if p['owner'].startswith('layer:')}),
            'runtime_mapped': counts.get('runtime', 0),
            'structural_mapped': sum(row.get('status') == 'structural' and 'binding' in row for row in decided.values()),
            'fidelity_proven': False,  # only real behavioral/visual results can establish fidelity
            'fill_rate': round((counts.get('used', 0) + counts.get('mapped', 0)) / owed, 4) if owed else None}
