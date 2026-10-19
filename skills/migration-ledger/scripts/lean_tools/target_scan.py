"""A read-only scan of the target project for the orchestrator's target profile: where the target already holds modules,
entry points and symbols that match the features being migrated. It returns candidates with their files' hashes; whether a
feature is absent, a shell or an existing implementation is still the orchestrator's judgement over this evidence."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

BUILD_FILES = ('build.gradle', 'build.gradle.kts', 'oh-package.json5', 'package.json', 'Package.swift', 'pubspec.yaml', 'CMakeLists.txt')  # module.json5 is an entry file
SOURCE_SUFFIXES = ('.kt', '.java', '.ets', '.ts', '.js', '.swift', '.dart', '.py', '.cpp', '.cc', '.h', '.m', '.mm')
SKIP_DIRS = {'.git', '.gradle', '.idea', 'build', 'node_modules', 'oh_modules', 'openspec', '.sdd-migration', '.sdd-runs', '.kotlin', 'DerivedData', '__pycache__'}
TEST_DIRS = ('test', 'tests', 'androidTest', 'ohosTest', 'unitTest', '__tests__', 'Tests')
DECLARATION = re.compile(r'^\s*(?:export\s+)?(?:(?:public|private|protected|internal|open|abstract|data|sealed|final|static|async|suspend|default)\s+)*'
                         r'(?:class|interface|object|enum class|enum|struct|protocol|fun|function|def|@Component|@Entry|@ComponentV2)\s+(?:struct\s+)?([A-Za-z_][A-Za-z0-9_]*)')
MANIFEST_NAME = re.compile(r'android:name="([^"]+)"')
ABILITY_NAME = re.compile(r'"name"\s*:\s*"([A-Za-z_][A-Za-z0-9_]*)"')
FILE_LIMIT, SYMBOL_LIMIT = 5000, 400


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _walk(root: Path, roots):
    starts = [root / r for r in roots] if roots else [root]
    seen = 0
    for start in starts:
        for path in sorted(start.rglob('*')):
            if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
                continue
            if path.is_file():
                seen += 1
                if seen > FILE_LIMIT:
                    return
                yield path


def scan(target_root: str, keywords, roots=None) -> dict:
    """Modules (folders with a build file), entry points (manifest activities, module abilities) and declared symbols whose
    name or path mentions a keyword, each with the file's hash as evidence for a target profile row."""
    root = Path(target_root).resolve()
    needles = [k.lower() for k in keywords]
    modules, entries, symbols, truncated = {}, [], [], False
    for path in _walk(root, roots or []):
        rel = path.relative_to(root)
        if path.name in BUILD_FILES:
            folder = modules.setdefault(str(rel.parent), {'path': str(path.parent), 'build_files': [], 'has_tests': False})
            folder['build_files'].append(path.name)
            folder['has_tests'] = folder['has_tests'] or any((path.parent / sub).is_dir() or (path.parent / 'src' / sub).is_dir() for sub in TEST_DIRS)
            continue
        text = None
        if path.name == 'AndroidManifest.xml' or path.name == 'module.json5':
            text = path.read_text(encoding='utf-8', errors='replace')
            names = MANIFEST_NAME.findall(text) if path.suffix == '.xml' else ABILITY_NAME.findall(text)
            if names:
                entries.append({'path': str(path), 'kind': 'android-manifest' if path.suffix == '.xml' else 'harmony-module', 'names': sorted(set(names)), 'sha256': sha256(path)})
            continue
        if path.suffix not in SOURCE_SUFFIXES:
            continue
        path_hit = next((k for k in needles if k in str(rel).lower()), None)
        text = path.read_text(encoding='utf-8', errors='replace')
        digest = None
        for number, line in enumerate(text.splitlines(), 1):
            match = DECLARATION.match(line)
            if not match:
                continue
            name = match.group(1)
            hit = next((k for k in needles if k in name.lower()), None) or path_hit
            if not hit:
                continue
            if len(symbols) >= SYMBOL_LIMIT:
                truncated = True
                break
            digest = digest or sha256(path)
            symbols.append({'symbol': str(path) + '#' + name, 'line': number, 'keyword': hit, 'sha256': digest,
                            'in_tests': any(part in TEST_DIRS for part in rel.parts)})
        if truncated:
            break
    return {'producer': 'sdd-target-scan', 'target_root': str(root), 'keywords': list(keywords), 'roots': list(roots or []),
            'modules': sorted(modules.values(), key=lambda m: m['path']), 'entries': entries, 'symbols': symbols, 'truncated': truncated,
            'acceptance': 'candidates-for-the-target-profile-not-a-state-verdict'}
