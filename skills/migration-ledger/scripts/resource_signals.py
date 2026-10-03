"""Display-bearing resource signals for the UI source collector.

A UI slice shows pixels that come from many places besides a layout attribute: drawables nested in
drawables, menu and preference icons, theme attributes, images fetched by URL or API field, names
built at run time, assets and code that draws. This module reads them deterministically from the
Android source root and describes each one with the facts a migration needs, so no role has to find
them by hand. It records signals; whether a replacement is acceptable is decided elsewhere.
"""
import hashlib
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import resource_facts as facts

VALUE_KINDS = {'string', 'color', 'dimen', 'integer', 'bool', 'style', 'array', 'plurals'}
FILE_EXCLUDED = VALUE_KINDS - {'color'}
XML_KINDS = ('menu', 'xml', 'navigation')
DOCUMENT_KINDS = {'layout', *XML_KINDS}
SOURCE_SUFFIXES = ('.kt', '.java')
SKIPPED_PARTS = {'build', '.git', '.gradle', 'node_modules', 'test', 'tests', 'androidTest'}
IMAGE_ASSETS = ('.png', '.webp', '.jpg', '.jpeg', '.gif', '.svg', '.json', '.xml')
CODE_REF = re.compile(r'(?<![\w.])(?P<platform>android\.)?R\.(?P<kind>[A-Za-z_]\w*)\.(?P<name>[A-Za-z_]\w*)')
IMAGE_HINT = re.compile(r'src|image|icon|url|avatar|photo|thumb|picture|cover|logo|background|foreground|drawable', re.I)
DESIGN_ATTRS = {'src', 'srcCompat', 'background', 'foreground', 'icon', 'drawableStart', 'drawableEnd',
                'drawableLeft', 'drawableRight', 'drawableTop', 'drawableBottom'}
LOADER_CHAINS = (('Glide', re.compile(r'\bGlide\s*\.\s*with\s*\(')),
                 ('Picasso', re.compile(r'\bPicasso\s*\.\s*(?:get|with)\s*\(')))
COMPOSE_LOADERS = re.compile(r'\b(?:AsyncImage|SubcomposeAsyncImage|GlideImage)\s*\(')
PLACEHOLDERS = ('placeholder', 'error', 'fallback')
TRANSFORMS = {'circleCrop', 'centerCrop', 'fitCenter', 'centerInside', 'transform', 'transforms', 'transformations',
              'roundedCorners', 'resize', 'override', 'size', 'scale', 'crossfade', 'fade', 'noFade', 'dontAnimate',
              'thumbnail', 'rotate', 'format', 'diskCacheStrategy', 'skipMemoryCache', 'contentScale'}
SERIAL_NAME = re.compile(r'@(?:\w+:)?(?:SerializedName|SerialName|JsonProperty|Json|Field|ColumnInfo)\s*\(\s*'
                         r'(?:value\s*=\s*|name\s*=\s*)?"([^"]+)"')
# A draw override or a canvas call, and a drawable built in code; a type that is only named (an import, a field, a cast) draws nothing.
DRAWN = re.compile(r'\b(onDraw|dispatchDraw)\s*\(|\.\s*(drawBitmap|drawRoundRect|drawCircle|drawPath|drawArc|drawOval|drawLine)\s*\(|'
                   r'(?:\bnew\s+|(?<![\w.]))(GradientDrawable|ShapeDrawable|PaintDrawable|LayerDrawable|StateListDrawable|BitmapDrawable|'
                   r'VectorDrawable|RippleDrawable|ClipDrawable)\s*\(')
LEXEME = re.compile(r'//[^\n]*|/\*.*?\*/|"""[\s\S]*?"""|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'|[{};]', re.S)
TYPE_HEAD = re.compile(r'\b(?:class|interface|object|enum|record)\s+([A-Za-z_]\w*)')
KOTLIN_FUN = re.compile(r'\bfun\s+(?:<[^>]*>\s*)?(?:[\w<>?,. ]+\.)?([A-Za-z_]\w*)\s*\(')
JAVA_METHOD = re.compile(r'([A-Za-z_]\w*)\s*\((?:[^()]|\([^()]*\))*\)\s*(?:throws\s+[\w.,\s]+)?$')
KEYWORDS = {'if', 'else', 'for', 'while', 'do', 'switch', 'try', 'catch', 'finally', 'synchronized', 'when', 'return', 'throw', 'new'}
# A call named like an image loader that the built-in loaders do not explain; listed so a project can declare it as an image sink.
SINK_NAME = re.compile(r'\.\s*((?:set|load|display|show)\w*(?:Image|Avatar|Photo|Thumb|Picture)\w*)\s*\(')
KNOWN_SETTERS = {'setImageResource', 'setImageDrawable', 'setImageBitmap', 'setImageURI', 'setImageTintList', 'setImageLevel',
                 'setImageAlpha', 'setImageMatrix', 'setImageState', 'displayImage'}
CANDIDATE_LIMIT = 64


def local(tag):
    return tag.rsplit('}', 1)[-1]


def normalize(text, limit=400):
    value = ' '.join(str(text).split())
    return value if len(value) <= limit else value[:limit] + '…'


def line_of(text, offset):
    return text.count('\n', 0, offset) + 1


def code_refs(value):
    refs = set()
    for match in CODE_REF.finditer(value or ''):
        refs.add(('@android:' if match.group('platform') else '@') + match.group('kind') + '/' + match.group('name'))
    return sorted(refs)


def balanced(text, open_index, opener='(', closer=')', limit=4000):
    """Index just past the bracket closing the one at open_index, skipping string literals; None when unbalanced."""
    depth, quote, index = 0, None, open_index
    end = min(len(text), open_index + limit)
    while index < end:
        char = text[index]
        if quote:
            if char == '\\':
                index += 1
            elif char == quote:
                quote = None
        elif char in '"\'':
            quote = char
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return None


def split_args(text):
    """Top-level comma-separated arguments of a call, with nesting and string literals respected."""
    parts, depth, quote, start = [], 0, None, 0
    for index, char in enumerate(text):
        if quote:
            if char == quote and text[index - 1] != '\\':
                quote = None
        elif char in '"\'':
            quote = char
        elif char in '([{':
            depth += 1
        elif char in ')]}':
            depth -= 1
        elif char == ',' and depth == 0:
            parts.append(text[start:index].strip())
            start = index + 1
    tail = text[start:].strip()
    return parts + ([tail] if tail else [])


SEGMENT = re.compile(r'\s*(?:\?\.|!!\.|\.)\s*([A-Za-z_]\w*)\s*(?=[(<{])')


def chain(text, position, limit=3000):
    """The `.name(args) { block }` segments that follow a call, and where the statement ends."""
    segments, end = [], position
    while len(segments) < 40 and end - position < limit:
        match = SEGMENT.match(text, end)
        if not match:
            break
        name, cursor = match.group(1), match.end()
        if text[cursor] == '<':
            close = text.find('>', cursor)
            if close < 0:
                break
            cursor = close + 1
        args, block = '', ''
        if text[cursor:cursor + 1] == '(':
            close = balanced(text, cursor)
            if close is None:
                break
            args, cursor = text[cursor + 1:close - 1], close
        brace = re.match(r'\s*\{', text[cursor:cursor + 40])
        if brace:
            close = balanced(text, cursor + brace.end() - 1, '{', '}')
            if close is not None:
                block, cursor = text[cursor + brace.end():close - 1], close
        segments.append({'name': name, 'args': args, 'block': block})
        end = cursor
    return segments, end


class Catalog:
    """One walk of the Android root shared by every lookup, so a reference never re-reads the project."""

    def __init__(self, root):
        self.root = Path(root)
        self._values = self._files = self._assets = self._sources = None
        self._hashes = {}

    def relative(self, path):
        return Path(path).resolve().relative_to(self.root).as_posix()

    def sha256(self, path):
        if path not in self._hashes:
            digest = hashlib.sha256()
            with Path(path).open('rb') as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                    digest.update(chunk)
            self._hashes[path] = digest.hexdigest()
        return self._hashes[path]

    def values(self):
        if self._values is None:
            self._values = []
            for path in sorted(self.root.rglob('*.xml')):
                if not path.is_file() or not path.parent.name.startswith('values') or 'res' not in path.parts:
                    continue
                try:
                    document = ET.parse(path)
                except ET.ParseError:
                    continue
                entries = []
                for element in document.getroot():
                    declared = element.attrib.get('type', local(element.tag))
                    entries.append(('array' if declared in ('string-array', 'integer-array') else declared,
                                    element.attrib.get('name'), element))
                self._values.append((path, path.parent.name[len('values'):].lstrip('-') or 'default', entries))
        return self._values

    def files(self):
        if self._files is None:
            self._files = {}
            for path in sorted(self.root.rglob('*')):
                if not path.is_file() or 'res' not in path.parts:
                    continue
                kind = path.parent.name.split('-', 1)[0]
                qualifier = path.parent.name[len(kind):].lstrip('-') or 'default'
                self._files.setdefault((kind, path.name.split('.', 1)[0]), []).append((qualifier, path))
        return self._files

    def assets(self):
        if self._assets is None:
            self._assets = {}
            for path in sorted(self.root.rglob('*')):
                parts = path.relative_to(self.root).parts
                if path.is_file() and 'assets' in parts and not SKIPPED_PARTS & set(parts):
                    self._assets.setdefault('/'.join(parts[parts.index('assets') + 1:]), path)
        return self._assets

    def sources(self):
        if self._sources is None:
            self._sources = []
            for path in sorted(self.root.rglob('*')):
                parts = path.relative_to(self.root).parts
                if (path.suffix in SOURCE_SUFFIXES and path.is_file() and not SKIPPED_PARTS & set(parts)
                        and path.stat().st_size <= 1024 * 1024):
                    self._sources.append((self.relative(path), path.read_text(encoding='utf-8', errors='replace')))
        return self._sources

    def value_rows(self, ref, kind, name):
        rows = []
        for path, qualifier, entries in self.values():
            for declared, entry_name, element in entries:
                if entry_name != name or declared != kind:
                    continue
                if kind == 'style':
                    value = {'parent': element.attrib.get('parent'),
                             'items': {item.attrib.get('name', ''): ''.join(item.itertext()).strip() for item in element}}
                else:
                    value = ''.join(element.itertext()).strip()
                rows.append({'ref': ref, 'kind': kind, 'qualifier': qualifier, 'path': self.relative(path),
                             'sha256': self.sha256(path), 'value': value})
        return rows

    def file_rows(self, ref, kind, name):
        return [{'ref': ref, 'kind': kind, 'qualifier': qualifier, 'path': self.relative(path), 'sha256': self.sha256(path)}
                for qualifier, path in self.files().get((kind, name), [])]

    def rows(self, ref):
        """Every declaration of a resource reference: values entries and res/ files, one row per qualifier."""
        clean = ref.lstrip('@?')
        if clean.startswith('android:'):
            return [{'ref': ref, 'kind': 'platform', 'status': 'platform'}]
        if '/' not in clean:
            return []
        kind, name = clean.split('/', 1)
        found = self.value_rows(ref, kind, name) if kind in VALUE_KINDS else []
        if kind not in FILE_EXCLUDED:
            found += self.file_rows(ref, kind, name)
        return found

    def describe(self, row):
        """Add the intrinsic facts and nested references of a file or style row; value rows keep their value."""
        if row.get('path') and 'value' not in row:
            path = self.root / row['path']
            row['facts'] = facts.file_facts(path, row['qualifier'])
            if path.suffix.lower() == '.xml' and row['kind'] not in DOCUMENT_KINDS:
                try:
                    nested = facts.xml_references(ET.parse(path).getroot())
                except ET.ParseError:
                    nested = []
                if nested:
                    row['references'] = nested
                import parameter_records
                layers = parameter_records.layer_parameters(path)
                if layers:
                    row['parameters'] = layers
        elif row.get('kind') == 'style' and isinstance(row.get('value'), dict):
            nested = [{'ref': ref, 'via': 'style/item:' + name}
                      for name, value in sorted(row['value']['items'].items()) for ref in facts.references(value)]
            nested += [{'ref': ref, 'via': 'style/parent'} for ref in facts.references(row['value'].get('parent'))]
            if nested:
                row['references'] = nested
        return row

    def xml_files(self, kind, name):
        return [(qualifier, path) for qualifier, path in self.files().get((kind, name), []) if path.suffix == '.xml']

    def theme_definitions(self, name):
        found = []
        for path, qualifier, entries in self.values():
            for declared, style, element in entries:
                if declared != 'style':
                    continue
                for item in element:
                    if item.attrib.get('name') == name:
                        found.append({'style': style, 'qualifier': qualifier, 'value': ''.join(item.itertext()).strip(),
                                      'path': self.relative(path), 'sha256': self.sha256(path)})
        return found

    def asset_row(self, relative):
        path = self.assets().get(relative)
        if path is None:
            return None
        return {'ref': 'asset:' + relative, 'kind': 'asset', 'qualifier': 'base', 'path': self.relative(path),
                'sha256': self.sha256(path), 'facts': facts.file_facts(path, 'base')}

    def resource_names(self, kinds, prefix):
        stems = sorted({kind + '/' + stem for (kind, stem) in self.files() if kind in kinds and stem.startswith(prefix)})
        return ['@' + stem for stem in stems]

    def model_fields(self, names):
        """Declarations of a model field in the sources, with the serialized key a serializer annotation names."""
        found = []
        for relative, text in self.sources():
            pattern = (r'\b(?:val|var)\s+(%s)\s*[:=]' if relative.endswith('.kt') else
                       r'\b[A-Za-z_][\w<>\[\],.?]*\s+(%s)\s*(?:=[^;{]*)?;') % '|'.join(map(re.escape, sorted(names)))
            for match in re.finditer(pattern, text):
                serial = SERIAL_NAME.findall(text[max(0, match.start() - 200):match.start()])
                found.append({'declaredIn': relative + ':' + str(line_of(text, match.start())),
                              'jsonKey': serial[-1] if serial else None})
                if len(found) >= 5:
                    return found
        return found


def layout_hint(hints, selector, name, value, attributes):
    """Image sources a layout element declares outside plain resource references: bindings and design-time samples."""
    attr = name.rsplit(':', 1)[-1]
    if '@{' in value and IMAGE_HINT.search(attr):
        hints.append({'kind': 'data-binding', 'selector': selector, 'attr': name, 'value': normalize(value, 200)})
    elif name.startswith('tools:') and attr in DESIGN_ATTRS:
        real = {'android:' + attr, 'app:' + attr, 'app:srcCompat' if attr == 'src' else 'app:' + attr}
        hints.append({'kind': 'design-sample', 'selector': selector, 'attr': name, 'value': normalize(value, 200),
                      'hasRuntimeSource': bool(real & attributes)})


def source_kind(argument):
    literal = re.fullmatch(r'\s*"(https?://[^"]*)"\s*', argument)
    if literal:
        return {'kind': 'url-literal', 'value': literal.group(1)}
    embedded = re.search(r'"(https?://[^"]*)"', argument)
    if embedded:
        return {'kind': 'url-template', 'value': normalize(argument, 200), 'literal': embedded.group(1)}
    return {'kind': 'expression', 'value': normalize(argument, 200)}


def api_field(catalog, expression):
    """The model field an image expression reads, with where it is declared and the key it is serialized under."""
    names = re.findall(r'[A-Za-z_]\w*', re.sub(r'\([^)]*\)|\?|!!', '', expression))
    if not names:
        return None
    leaf = names[-1]
    field = leaf[3].lower() + leaf[4:] if leaf.startswith('get') and len(leaf) > 3 else leaf
    return {'field': field, 'candidates': catalog.model_fields({leaf, field})}


def loader_details(calls, library, sink):
    loader = {'library': library, 'sink': sink}
    transforms = []
    for name, args in calls:
        if name in PLACEHOLDERS:
            refs = code_refs(args)
            loader[name] = refs if refs else []
            if not refs and args.strip():
                loader[name + 'Expression'] = normalize(args, 120)
        elif name in TRANSFORMS:
            transforms.append(name + '(' + normalize(args, 60) + ')')
        elif name == 'into' and args.strip():
            loader['target'] = split_args(args)[0]
    if transforms:
        loader['transforms'] = transforms
    return loader


def block_calls(block):
    calls = []
    for match in re.finditer(r'\b(' + '|'.join(sorted(PLACEHOLDERS + tuple(TRANSFORMS))) + r')\s*\(', block):
        close = balanced(block, match.end() - 1)
        if close is not None:
            calls.append((match.group(1), block[match.end():close - 1]))
    return calls


def remote_rows(catalog, text, relative, sinks):
    rows, found = [], []   # found: (start, end, library, sink, source expression, calls, target)
    for library, pattern in LOADER_CHAINS:
        for match in pattern.finditer(text):
            close = balanced(text, match.end() - 1)
            if close is None:
                continue
            segments, end = chain(text, close)
            load = next((s for s in segments if s['name'] == 'load'), None)
            if load:
                calls = [(s['name'], s['args']) for s in segments] + [c for s in segments for c in block_calls(s['block'])]
                found.append((match.start(), end, library, 'load', split_args(load['args'])[0] if load['args'].strip() else '', calls, None))
    if re.search(r'\bimport\s+coil3?\.', text):
        for match in re.finditer(r'\b(?P<target>[A-Za-z_][\w.]*)\s*\.\s*load\s*\(', text):
            close = balanced(text, match.end() - 1)
            if close is None:
                continue
            end, block, brace = close, '', re.match(r'\s*\{', text[close:close + 40])
            if brace:
                stop = balanced(text, close + brace.end() - 1, '{', '}')
                if stop is not None:
                    block, end = text[close + brace.end():stop - 1], stop
            args = split_args(text[match.end():close - 1])
            found.append((match.start(), end, 'Coil', 'load', args[0] if args else '', block_calls(block), match.group('target')))
    for match in COMPOSE_LOADERS.finditer(text):
        close = balanced(text, match.end() - 1)
        if close is None:
            continue
        named = {}
        for position, argument in enumerate(split_args(text[match.end():close - 1])):
            key, _, value = argument.partition('=')
            named[key.strip() if value and re.fullmatch(r'\s*\w+\s*', key) else ('model' if position == 0 else '')] = (value or argument).strip()
        calls = [(key, value) for key, value in named.items() if key in PLACEHOLDERS or key == 'contentScale']
        found.append((match.start(), close, 'Compose', match.group(0).split('(')[0].strip(), named.get('model', ''), calls, None))
    for sink, library, pattern in (('setImageURI', 'ImageView', r'\.\s*setImageURI\s*\('), ('displayImage', 'ImageLoader', r'\.\s*displayImage\s*\('),
                                   *(((name, 'custom', r'\.\s*' + re.escape(name) + r'\s*\(') for name in sinks))):
        for match in re.finditer(pattern, text):
            close = balanced(text, match.end() - 1)
            if close is not None:
                args = split_args(text[match.end():close - 1])
                found.append((match.start(), close, library, sink, args[0] if args else '', [], None))
    taken = set()
    for start, end, library, sink, argument, calls, target in sorted(found, key=lambda item: item[:5]):
        expression = normalize(text[start:end])
        if (start, sink) in taken or not argument:
            continue
        taken.add((start, sink))
        if re.search(r'android_asset|asset:///', argument):
            continue  # an asset is a file resource; it is recorded with the other files
        row = {'kind': 'remote-image', 'sourcePath': relative, 'line': line_of(text, start), 'expression': expression,
               'source': source_kind(argument), 'loader': loader_details(calls, library, sink)}
        if target and 'target' not in row['loader']:
            row['loader']['target'] = target
        if row['source']['kind'] != 'url-literal':
            api = api_field(catalog, argument)
            if api:
                row['api'] = api
        rows.append(row)
    return rows


def name_prefix(expression):
    """(prefix, None) for a name built from a literal start, (None, name) for a literal, else (None, None)."""
    exact = re.fullmatch(r'\s*"([^"$]+)"\s*', expression)
    if exact:
        return None, exact.group(1)
    for match in (re.match(r'\s*"([^"$]*)"\s*\+', expression), re.match(r'\s*"([^"$]*)\$', expression),
                  re.search(r'format\s*\(\s*"([^"%]*)%', expression)):
        if match and match.group(1):
            return match.group(1), None
    return None, None


def identifier_rows(catalog, text, relative):
    rows = []
    for match in re.finditer(r'\.\s*getIdentifier\s*\(', text):
        close = balanced(text, match.end() - 1)
        args = split_args(text[match.end():close - 1]) if close else []
        if len(args) < 2:
            continue
        typed = re.fullmatch(r'\s*"(\w+)"\s*', args[1])
        kinds = (typed.group(1),) if typed else ('drawable', 'mipmap')
        prefix, exact = name_prefix(args[0])
        row = {'kind': 'dynamic-resource', 'sourcePath': relative, 'line': line_of(text, match.start()),
               'expression': normalize(text[match.start():close]), 'nameExpression': normalize(args[0], 200),
               'resourceType': kinds[0] if typed else None, 'prefix': prefix}
        if exact:
            row['candidates'] = [ref for ref in (f'@{kind}/{exact}' for kind in kinds) if catalog.files().get((ref[1:].split('/')[0], exact))]
        elif prefix:
            names = catalog.resource_names(kinds, prefix)
            row['candidates'] = names[:CANDIDATE_LIMIT]
            if len(names) > CANDIDATE_LIMIT:
                row['truncated'] = True
        else:
            row['candidates'] = None
        rows.append(row)
    return rows


def asset_paths(text):
    found = set(re.findall(r'(?:file:///android_asset/|asset:///)([^"\'\s)]+)', text))
    found.update(a or b for a, b in re.findall(r'\bassets?\s*\.\s*open\s*\(\s*"([^"]+)"|\bgetAssets\(\)\s*\.\s*open\s*\(\s*"([^"]+)"', text))
    return sorted(path for path in found if path.lower().endswith(IMAGE_ASSETS))


class Symbols:
    """Which class and function hold a position of a Java or Kotlin source, read from its braces.

    Comments and string literals are skipped; a block that declares nothing (a branch, a lambda, an
    anonymous class) keeps the names of the blocks around it."""

    def __init__(self, text, kotlin=False):
        self.spans, self.code = [], []
        stack, boundary = [], 0   # stack: (open offset, names of the enclosing declarations)
        for match in LEXEME.finditer(text):
            token = match.group(0)
            if token not in '{};':
                self.code.append((match.start(), match.end()))   # not code: a comment or a literal
                continue
            if token == '{':
                names = stack[-1][1] if stack else ()
                name = self._declared(text[boundary:match.start()], kotlin)
                stack.append((match.start(), names + (name,) if name else names))
            elif token == '}' and stack:
                start, names = stack.pop()
                self.spans.append((start, match.end(), names))
            boundary = match.end()
        self.spans.extend((start, len(text), names) for start, names in stack)
        self.spans.sort()

    @staticmethod
    def _declared(header, kotlin):
        types = TYPE_HEAD.findall(header)
        if kotlin:
            functions = KOTLIN_FUN.findall(header)
            last_type, last_fun = header.rfind(types[-1]) if types else -1, header.rfind('fun ') if functions else -1
            return (functions[-1] if last_fun > last_type else types[-1]) if (types or functions) else None
        if types:
            return types[-1]
        method = JAVA_METHOD.search(header.strip())
        if not method or method.group(1) in KEYWORDS or re.search(r'\bnew\s+[\w.<>\[\], ]*$', header.strip()[:method.start(1)]):
            return None
        return method.group(1)

    def outside_code(self, offset):
        return any(start <= offset < end for start, end in self.code)

    def at(self, offset):
        """`Class.Inner.method` for the innermost named blocks around a position, or None at file level."""
        names = ()
        for start, end, held in self.spans:
            if start > offset:
                break
            if offset < end:
                names = held
        return '.'.join(names) or None


def receiving_call(text, offset, limit=400):
    """The name of the call a position is an argument of, or None when it is not inside a call's parentheses."""
    depth = 0
    for index in range(offset - 1, max(-1, offset - limit - 1), -1):
        char = text[index]
        if char in ';{}':
            return None
        if char == ')':
            depth += 1
        elif char == '(':
            if depth:
                depth -= 1
                continue
            name = re.search(r'([A-Za-z_]\w*)\s*$', text[max(0, index - 120):index])
            return name.group(1) if name and name.group(1) not in KEYWORDS else None
    return None


def usages(text, kotlin=False, symbols=None):
    """Every place a source file names a resource: the reference, its line, the class and function, and the call it is passed to."""
    symbols = symbols or Symbols(text, kotlin)
    rows = []
    for match in CODE_REF.finditer(text):
        if symbols.outside_code(match.start()):
            continue
        row = {'ref': ('@android:' if match.group('platform') else '@') + match.group('kind') + '/' + match.group('name'),
               'line': line_of(text, match.start())}
        symbol, call = symbols.at(match.start()), receiving_call(text, match.start())
        if symbol:
            row['symbol'] = symbol
        if call:
            row['call'] = call
        rows.append(row)
    return rows


def drawn_rows(text, relative, symbols=None):
    """Drawing code, grouped by the function that holds it: one signal per `Class.function`."""
    symbols = symbols or Symbols(text, relative.endswith('.kt'))
    groups = {}
    for match in DRAWN.finditer(text):
        if symbols.outside_code(match.start()):
            continue
        position = match.start()
        if match.group(1):  # a draw override named where it is declared belongs to the function it declares
            close = balanced(text, match.end() - 1)
            body = re.match(r'\s*(?::\s*[\w.<>?]+\s*)?(?:throws\s+[\w.,\s]+)?\{', text[close:close + 200]) if close else None
            if body:
                position = close + body.end()
        owner = symbols.at(position) or relative
        group = groups.setdefault(owner, {'kind': 'code-drawn', 'sourcePath': relative, 'line': line_of(text, match.start()),
                                         'owner': owner, 'constructs': set()})
        group['constructs'].add(next(name for name in match.groups() if name))
    return [{**group, 'constructs': sorted(group['constructs']),
             'expression': normalize(text.splitlines()[group['line'] - 1].strip(), 200)} for group in groups.values()]


def sink_candidates(text, relative, sinks, symbols):
    """Calls named like an image loader that no recognised loader explains, so nothing about them was recorded."""
    rows = []
    for match in SINK_NAME.finditer(text):
        name = match.group(1)
        if name in KNOWN_SETTERS or name in sinks or symbols.outside_code(match.start()):
            continue
        close = balanced(text, match.end() - 1)
        rows.append({'call': name, 'sourcePath': relative, 'line': line_of(text, match.start()),
                     'expression': normalize(text[match.start():close or match.end()], 200)})
    return rows


def code_sources(catalog, text, relative, sinks=(), helpers=()):
    """What one source file shows beyond its setters: image sources, assets, every resource use, and unexplained loader calls."""
    symbols = Symbols(text, relative.endswith('.kt'))
    import parameter_records
    return {'imageSources': remote_rows(catalog, text, relative, tuple(sinks)) + identifier_rows(catalog, text, relative)
            + drawn_rows(text, relative, symbols), 'assets': asset_paths(text),
            'usages': usages(text, symbols=symbols), 'sinkCandidates': sink_candidates(text, relative, tuple(sinks), symbols),
            'parameters': parameter_records.code_parameters(text, relative, symbols, helpers)}


def source_id(row, occurrence):
    key = '|'.join([row['kind'], row.get('sourcePath', ''), row.get('selector', ''), str(row.get('attr', '')),
                    row.get('expression') or row.get('value') or row.get('owner', ''), str(occurrence)])
    return 'src:' + row['kind'] + ':' + hashlib.sha256(key.encode()).hexdigest()[:12]


def identify(rows):
    """Stable ids: the same source keeps its id when other lines move, and repeated identical sources stay distinct."""
    seen, ordered = {}, sorted(rows, key=lambda r: (r.get('sourcePath', ''), r.get('line') or 0, r.get('selector', ''), r['kind']))
    for row in ordered:
        base = (row['kind'], row.get('sourcePath', ''), row.get('selector', ''), str(row.get('attr', '')),
                row.get('expression') or row.get('value') or row.get('owner', ''))
        seen[base] = seen.get(base, 0) + 1
        row['id'] = source_id(row, seen[base])
    return ordered


def source_refs(row):
    """Resource references an image source itself names: loader placeholders and run-time name candidates."""
    refs = set(row.get('candidates') or [])
    loader = row.get('loader') or {}
    for key in PLACEHOLDERS:
        refs.update(loader.get(key) or [])
    return sorted(refs)
