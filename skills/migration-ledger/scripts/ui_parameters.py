"""The parameter sheet of a module: every value its legacy UI gives a component or a layer, ready to be used.

The sheet is derived from the source indexes a module's UI evidence names, never authored: layout attributes
(with styles applied and references followed to their values), the layers of drawable XML, what setter calls
give a view, and the values those name. Each parameter has one id, one owner and one class:

  value       a length, number, colour or text: materialised for the target and used there by its key
  linked      names a values resource; that resource is the value, shared by everything that names it
  picture     names a picture file, which travels through the copy plan
  layer       names a drawable described by XML, whose own parameters are in the sheet
  keyword     a structural choice (match_parent, a gravity, a visibility): part of the component's shape
  token       a value the legacy code names (a theme key, a theme attribute): mapped once per module
  expression  computed at run time: a person states what the target does
"""
from pathlib import Path
import re

from contracts import check_ref, digest, read_json, require
import parameter_records as records
import resource_fidelity

PRODUCER = 'sdd-parameter-sheet'
VALUE_TYPES = ('dimension', 'number', 'color', 'string')
VALUE_KINDS = ('dimen', 'color', 'string', 'integer', 'bool', 'fraction')
DEPTH = 6


class Index:
    """Lookups over one source index: its value entries, styles, theme attributes and resource files."""

    def __init__(self, index):
        self.rows = {}
        for row in index.get('resources', []):
            self.rows.setdefault(row['ref'], []).append(row)
        self.themes = {row['ref']: row for row in index.get('themeAttrs', [])}

    def base(self, ref):
        """The declaration that applies without a qualifier, else the only one there is."""
        rows = self.rows.get(ref, [])
        plain = [row for row in rows if row.get('qualifier') in ('default', 'base', None)]
        return plain[0] if plain else rows[0] if len(rows) == 1 else None

    def variants(self, ref):
        return {row['qualifier']: row['value'] for row in self.rows.get(ref, [])
                if 'value' in row and row.get('qualifier') not in ('default', 'base', None)}

    def style(self, ref, depth=0):
        """A style's items with its parents' beneath them; a parent the project does not define ends the chain."""
        row = self.base(ref)
        if not row or not isinstance(row.get('value'), dict) or depth > DEPTH:
            return {}
        parent = row['value'].get('parent')
        name = ref.split('/', 1)[1]
        parent = ('@style/' + parent.split('/')[-1] if parent else '@style/' + name.rsplit('.', 1)[0] if '.' in name and parent is None else None)
        items = dict(self.style(parent, depth + 1)) if parent else {}
        items.update({records.local(key): value for key, value in row['value'].get('items', {}).items()})
        return items


def key(pid):
    """The name target code uses for a parameter: its id as an identifier."""
    return re.sub(r'_+', '_', re.sub(r'[^A-Za-z0-9]', '_', pid)).strip('_')


def _typed(value):
    """The fields of a typed value that belong in the sheet."""
    return {name: value[name] for name in ('type', 'value', 'unit', 'text') if name in value}


class Sheet:
    def __init__(self, index):
        self.index, self.lookup, self.found = index, Index(index), {}

    def add(self, pid, owner, name, value, origin, **extra):
        row = {'id': pid, 'owner': owner, 'name': name, **self.classify(value), 'origin': origin, **extra}
        self.found[pid] = row
        return row

    def classify(self, value, depth=0):
        kind = value['type']
        if kind == 'dimension' and value['value'] == 0:
            return {'class': 'keyword', **_typed(value)}   # no gap, no inset: the absence is structure, not a value to carry
        if kind in VALUE_TYPES:
            return {'class': 'value', **_typed(value)}
        if kind in ('keyword', 'boolean'):
            return {'class': 'keyword', **_typed(value)}
        if kind == 'expression':
            return {'class': 'expression', 'text': value['text']}
        if kind == 'token':
            return self.theme(value, depth) if value['token'].startswith('?') else {'class': 'token', 'token': value['token'], 'text': value.get('text', value['token'])}
        return self.reference(value['ref'], depth)

    def theme(self, value, depth):
        """A theme attribute every project style gives the same value is that value; otherwise it stays a token."""
        ref = '?attr/' + value['token'].split('/', 1)[-1]
        definitions = {d['value'] for d in (self.lookup.themes.get(ref) or {}).get('definitions', []) if d.get('qualifier') in ('default', 'base', None)}
        if len(definitions) == 1 and depth < DEPTH:
            return {**self.classify(records.literal(definitions.pop()), depth + 1), 'via': [value['token']]}
        return {'class': 'token', 'token': value['token'], 'text': value['token']}

    def reference(self, ref, depth):
        kind = ref.lstrip('@').split('/')[0].split(':')[-1]
        if ref.startswith('@android:'):
            return {'class': 'token', 'token': ref, 'text': ref}
        row = self.lookup.base(ref)
        if kind in VALUE_KINDS and row is not None and 'value' in row:
            return {'class': 'linked', 'uses': self.resource(ref, depth)}
        if kind in ('drawable', 'mipmap', 'color', 'anim', 'animator') and any(r.get('parameters') for r in self.lookup.rows.get(ref, [])):
            return {'class': 'layer', 'uses': ref}
        if kind in resource_fidelity.FILE_KINDS:
            return {'class': 'picture', 'uses': ref}
        return {'class': 'keyword', 'type': 'keyword', 'value': ref}

    def resource(self, ref, depth=0):
        """A values entry as a parameter of its own: `values:dimen/gap`; what names it is linked to it."""
        kind, name = ref.lstrip('@').split('/', 1)
        pid = 'values:' + kind + '/' + name
        if pid not in self.found:
            row = self.lookup.base(ref)
            text = row['value']
            # A text is text whatever it looks like; only an alias (`@string/other`) is followed.
            value = {'type': 'string', 'value': text} if kind == 'string' and not text.startswith(('@', '?')) else records.literal(text)
            extra = {'variants': self.lookup.variants(ref)} if self.lookup.variants(ref) else {}
            self.found[pid] = None   # a reference that reaches itself stops here
            resolved = self.classify(value, depth + 1) if depth < DEPTH else {'class': 'expression', 'text': row['value']}
            self.found[pid] = {'id': pid, 'owner': 'values', 'name': kind + '/' + name, **resolved,
                               'origin': {'path': row['path']}, **extra}
        return pid

    # ------------------------------------------------------------------ where parameters come from

    def layouts(self):
        for document in self.index.get('layouts', []):
            label = document['name'] + ('' if document.get('qualifier') in ('default', 'base', None) else '@' + document['qualifier'])
            taken = {}
            def walk(node, trail):
                android_id = (node.get('androidId') or '').split('/')[-1]
                segment = re.sub(r'\[(\d+)\]|\[@.*\]', lambda m: m.group(1) or '', node['selector'].rsplit('/', 1)[-1])
                name = android_id or '.'.join(trail + [segment])
                taken[name] = taken.get(name, 0) + 1
                owner = 'layout:' + label + '/' + name + ('' if taken[name] == 1 else '~' + str(taken[name]))
                origin = {'path': document['path'], 'selector': node['selector']}
                attrs = dict(node.get('rawAttrs', {}))
                style = attrs.pop('style', None)
                explicit = {records.local(raw) for raw in attrs}
                if style and style.startswith('@'):
                    for item, value in sorted(self.lookup.style(style.replace('@+', '@')).items()):
                        if item not in explicit and item not in records.SKIPPED_ATTRS:
                            self.add(owner + '.' + item, owner, item, records.literal(value, item), origin, via=[style])
                for attr, value in records.attributes(attrs):
                    self.add(owner + '.' + attr, owner, attr, value, origin)
                for child in node.get('children', []):
                    walk(child, trail + ([] if android_id else [segment]))
            walk(document['root'], [])

    def layers(self, refs):
        for ref in sorted(refs):
            for row in self.lookup.rows.get(ref, []):
                if not row.get('parameters'):
                    continue
                qualifier = '' if row.get('qualifier') in ('default', 'base', None) else '@' + row['qualifier']
                owner = 'layer:' + ref.lstrip('@') + qualifier
                for parameter in row['parameters']:
                    self.add(owner + '/' + parameter['path'] + '.' + parameter['name'], owner, parameter['name'],
                             parameter, {'path': row['path'], 'element': parameter['path']})

    def code(self, excluded):
        counts = {}
        for source in self.index.get('sourceFiles', []):
            for parameter in source.get('parameters', []):
                site = {'ref': '', 'symbol': parameter.get('symbol')}
                if resource_fidelity._scoped_out(site, [row for row in excluded if row.get('symbol') and not row.get('ref')]):
                    continue
                owner = 'code:' + component(parameter.get('symbol')) + '/' + parameter['receiver']
                base = owner + '.' + parameter['name']
                counts[base] = counts.get(base, 0) + 1
                self.add(base + ('' if counts[base] == 1 else '#' + str(counts[base])), owner, parameter['name'], parameter,
                         {'path': source['path'], 'line': parameter['line']}, raw=parameter['raw'])

    def strings(self, excluded):
        """Texts the scoped code names anywhere, a setter or not, are values the target shows."""
        for source in self.index.get('sourceFiles', []):
            for site in source.get('resourceUsages', []):
                if site['ref'].startswith('@string/') and self.lookup.base(site['ref']) and not resource_fidelity._scoped_out(site, excluded):
                    self.resource(site['ref'])


def component(symbol):
    """The class a view belongs to: the leading capitalised names of a symbol, a constructor counted once."""
    names = []
    for name in (symbol or 'file').split('.'):
        if not name[:1].isupper() or (names and names[-1] == name):
            break
        names.append(name)
    return '.'.join(names) or (symbol or 'file').split('.')[0]


def sheet(index, tree=None, scope=None):
    """The parameters of one UI target, from its source index."""
    excluded = resource_fidelity.usage_exclusions(index, scope)
    built = Sheet(index)
    built.layouts()
    built.code(excluded)
    built.strings(excluded)
    seen = set()
    while True:   # layers named by parameters bring their own parameters, which may name further layers
        wanted = {row['uses'] for row in built.found.values() if row and row['class'] == 'layer'} - seen
        if tree is not None:
            wanted |= {ref for ref in resource_fidelity.obligations(index, tree, scope)['refs']
                       if any(r.get('parameters') for r in built.lookup.rows.get(ref, []))} - seen
        if not wanted:
            break
        seen |= wanted
        built.layers(wanted)
    return [row for _, row in sorted(built.found.items()) if row]


def derive(analysis, rules=None):
    """The sheet of a module: the parameters of all its UI targets, each once, with the convention they will be written under."""
    merged = {}
    for row in analysis.get('dimensions', []):
        if row.get('dimension') != 'UI' or row.get('status') != 'applicable':
            continue
        for item in row.get('items', []):
            evidence = (item.get('semantic_model') or {}).get('ui_evidence')
            if not evidence or not evidence.get('source_index_ref'):
                continue
            index = read_json(check_ref(evidence['source_index_ref']))
            tree = read_json(check_ref(evidence['ui_tree_ref'])) if evidence.get('ui_tree_ref') else None
            for parameter in sheet(index, tree, evidence.get('resource_scope')):
                known = merged.setdefault(parameter['id'], parameter)
                require(known == parameter, 'UI targets of one module give different values to parameter ' + parameter['id'])
    return {'schema_version': 1, 'producer': PRODUCER, 'module_id': analysis.get('module_id'), 'convention': rules,
            'parameters': [merged[pid] for pid in sorted(merged)]}


def outline(parameters):
    """What a Spec still has to decide after deriving a sheet: its size by class, the tokens to map, the expressions to settle."""
    counts = {}
    for row in parameters:
        counts[row['class']] = counts.get(row['class'], 0) + 1
    return {'counts': dict(sorted(counts.items())), 'tokens': sorted({row['token'] for row in parameters if row['class'] == 'token'}),
            'expressions': [{'id': row['id'], 'text': row['text']} for row in parameters if row['class'] == 'expression']}


def sheet_ref(analysis):
    for row in analysis.get('dimensions', []):
        if row.get('dimension') == 'UI' and row.get('parameter_sheet_ref'):
            return row['parameter_sheet_ref']
    return None


def load(analysis, resolve=check_ref):
    """The parameter sheet a dimension analysis names; None when it names none."""
    ref = sheet_ref(analysis)
    if ref is None:
        return None
    document = read_json(resolve(ref))
    require(document.get('schema_version') == 1 and document.get('producer') == PRODUCER and isinstance(document.get('parameters'), list),
            'parameter_sheet_ref must name a derived parameter sheet')
    return document


def parameters(analysis, resolve=check_ref):
    document = load(analysis, resolve)
    return document['parameters'] if document else []


def freeze_check(analysis):
    """The sheet a Spec names is the one its UI evidence gives, parameter for parameter."""
    document = load(analysis)
    if document is not None:
        require(document.get('module_id') == analysis.get('module_id')
                and digest(document['parameters']) == digest(derive(analysis)['parameters']),
                'parameter sheet differs from the one its UI evidence gives; derive it again with resource-plan')
