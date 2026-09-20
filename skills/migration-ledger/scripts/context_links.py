"""Freeze linked Markdown knowledge and relocate OpenSpec links without editing evidence."""
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.parse import quote, unquote, urlsplit

from contracts import check_ref, digest, file_ref, read_json, require

MARKDOWN = {'.md', '.markdown', '.mdx'}
LINK = re.compile(r'(?<!\\)\[[^\]\n]*\]\(\s*(<[^>\n]+>|(?:\\.|[^\\()\s]|\([^()\n]*\))+)(?=\s|\))')
REFERENCE = re.compile(r'^ {0,3}\[[^\]\n]+\]:\s*(<[^>\n]+>|\S+)', re.M)
HTML = re.compile(r'\b(?:href|src)\s*=\s*["\']([^"\']+)["\']', re.I)
AUTOLINK = re.compile(r'<(file://[^>\n]+)>')


def spans(text):
    masked, fence = [], None
    for line in text.splitlines(keepends=True):
        match = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if fence:
            masked.append(''.join('\n' if c == '\n' else ' ' for c in line))
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence): fence = None
        elif match:
            fence = match[1]; masked.append(''.join('\n' if c == '\n' else ' ' for c in line))
        else:
            masked.append(line)
    visible = re.sub(r'(`+)(?!`)(.*?)(?<!`)\1(?!`)', lambda m: ' ' * len(m[0]), ''.join(masked), flags=re.S)
    found = {}
    for pattern in (LINK, REFERENCE, HTML, AUTOLINK):
        for match in pattern.finditer(visible):
            start, end = match.span(1)
            if text[start:end].startswith('<'): start += 1; end -= 1
            found[start, end] = text[start:end]
    return [(start, end, value) for (start, end), value in sorted(found.items())]


def destination(source, value):
    value = re.sub(r'\\([\\`*_{}\[\]()#+.!<> -])', r'\1', value)
    parsed = urlsplit(value)
    if not parsed.path or value.startswith('//') or parsed.scheme not in ('', 'file') or parsed.netloc not in ('', 'localhost'):
        return None
    path = Path(unquote(parsed.path))
    path = (Path(source).parent / path).resolve() if not path.is_absolute() else path.resolve()
    suffix = ('?' + parsed.query if parsed.query else '') + ('#' + parsed.fragment if parsed.fragment else '')
    return str(path), suffix


def rewrite(text, source, mapping):
    warnings, edits = [], []
    for start, end, value in spans(text):
        target = destination(source, value)
        if target:
            path, suffix = target
            if path not in mapping:
                warnings.append({'source': str(source), 'link': value, 'target': path, 'reason': 'target-not-frozen'})
            prefix = 'file://' if value.startswith('file://') else ''
            edits.append((start, end, prefix + quote(str(mapping.get(path, path)), safe='/:@') + suffix))
    for start, end, value in reversed(edits): text = text[:start] + value + text[end:]
    return text, warnings


def freeze(directory, ref, archive, max_files=256, max_bytes=32 * 1024 * 1024):
    source = check_ref(ref).resolve()
    initial = source.read_bytes()
    require(hashlib.sha256(initial).hexdigest() == ref['sha256'], 'source changed during link snapshot')
    content, pending, warnings = {str(source): initial}, [str(source)], []
    size = len(initial)
    while pending:
        origin = pending.pop()
        if Path(origin).suffix.lower() not in MARKDOWN: continue
        text = content[origin].decode('utf-8')
        for _, _, value in spans(text):
            target = destination(origin, value)
            if not target or target[0] in content: continue
            path = Path(target[0])
            reason = None
            if (path.name == '.env' or (path.name.startswith('.env.') and path.name not in ('.env.example', '.env.template'))
                    or '.ssh' in path.parts or path.suffix.lower() in ('.pem', '.key')):
                reason = 'sensitive-link-not-copied'
            elif not path.is_file():
                reason = 'directory-not-frozen' if path.is_dir() else 'missing-local-target'
            elif len(content) >= max_files or size + path.stat().st_size > max_bytes:
                reason = 'link-snapshot-limit'
            if reason:
                warnings.append({'source': origin, 'link': value, 'target': str(path), 'reason': reason}); continue
            data = path.read_bytes(); size += len(data)
            content[str(path)] = data; pending.append(str(path))
    originals = {path: archive(directory, data, '.json.source' if Path(path).suffix == '.json' else Path(path).suffix)
                 for path, data in content.items()}
    markdown = {path for path in content if Path(path).suffix.lower() in MARKDOWN and
                any(destination(path, value) for _, _, value in spans(content[path].decode('utf-8')))}
    if not markdown: return originals[str(source)]
    bundle = directory / 'linked' / digest({'sources': originals, 'warnings': warnings})
    mapping = {path: str(bundle / (digest(path) + '.md')) if path in markdown else original['path']
               for path, original in originals.items()}
    entries = []
    for path, data in content.items():
        if path in markdown:
            data = rewrite(data.decode('utf-8'), path, mapping)[0].encode('utf-8')
            view = Path(mapping[path]); view.parent.mkdir(parents=True, exist_ok=True)
            if view.exists():
                require(view.read_bytes() == data, 'linked context view corrupt')
            else:
                temporary = view.with_suffix('.tmp')
                with temporary.open('wb') as stream:
                    stream.write(data); stream.flush(); os.fsync(stream.fileno())
                os.replace(temporary, view)
        entries.append({'source_path': path, 'original_ref': originals[path], 'readable_ref': file_ref(mapping[path])})
    manifest = {'schema_version': 1, 'entries': entries, 'warnings': warnings}
    manifest_ref = archive(directory, (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2)+'\n').encode(), '.links.json')
    return {**file_ref(mapping[str(source)]), 'link_manifest_ref': manifest_ref}


def verify(ref):
    manifest = read_json(check_ref(ref))
    require(manifest.get('schema_version') == 1, 'invalid context link manifest')
    for entry in manifest['entries']:
        check_ref(entry['original_ref']); check_ref(entry['readable_ref'])
    return manifest


def mapping(value):
    """Use sealed mappings only; never discover new versions while reading a run."""
    targets, warnings = {}, []
    def visit(item):
        if isinstance(item, dict):
            if item.get('path') and item.get('sha256'):
                targets.setdefault(str(Path(item['path']).resolve()), item['path'])
            if item.get('link_manifest_ref'):
                manifest = verify(item['link_manifest_ref']); warnings.extend(manifest['warnings'])
                for entry in manifest['entries']:
                    targets[entry['source_path']] = entry['readable_ref']['path']
                    targets[entry['original_ref']['path']] = entry['readable_ref']['path']
                    targets[entry['readable_ref']['path']] = entry['readable_ref']['path']
            for key, nested in item.items():
                if key != 'link_manifest_ref': visit(nested)
        elif isinstance(item, list):
            for nested in item: visit(nested)
    visit(value)
    if isinstance(value, dict) and value.get('source_paths'):
        for key, original in value['source_paths'].items():
            frozen = value['source_refs'][key]
            pairs = zip(original, frozen) if isinstance(original, list) else [(original, frozen)]
            for source, ref in pairs:
                targets[str(Path(source).resolve())] = ref['path']
                targets[ref['path']] = ref['path']
    return targets, warnings
