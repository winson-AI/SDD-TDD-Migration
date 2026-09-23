#!/usr/bin/env python3
"""Read-only target-wide build discovery. Never executes discovered scripts."""
import argparse
import json
import os
from pathlib import Path
import shutil

EXCLUDED_DIRECTORIES = ('.git', '.gradle', 'build', 'node_modules', '.idea',
                        '.sdd-migration', '.sdd-runs', 'openspec')


def discover(target, override=None):
    root = Path(target).resolve()
    if not root.is_dir(): raise ValueError('target root missing')
    candidates = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_DIRECTORIES)
        for name in sorted(files):
            p = Path(directory) / name
            resolved = p.resolve()
            if not resolved.is_relative_to(root): continue
            if any(part in EXCLUDED_DIRECTORIES for part in resolved.relative_to(root).parts[:-1]): continue
            if name in ('gradlew', 'gradlew.bat', 'build.gradle', 'build.gradle.kts', 'settings.gradle', 'settings.gradle.kts') or (
                    p.suffix in ('.sh', '.bat', '.ps1') or p.suffix in ('.yml', '.yaml') and
                    ('.github/workflows' in p.as_posix() or any(k in name.lower() for k in ('build', 'compile', 'gradle')))):
                candidates.append(str(p))
    result = {'target_root': str(root), 'candidates': candidates, 'executed': False,
              'excluded_directories': list(EXCLUDED_DIRECTORIES)}
    override = override or {}
    if override.get('argv'):
        argv = list(override['argv'])
        if not all(isinstance(a, str) and a for a in argv): raise ValueError('argv must contain strings')
        if not Path(argv[0]).is_absolute():
            local = root / argv[0]
            argv[0] = str(local.resolve()) if local.is_file() else shutil.which(argv[0]) or argv[0]
        result.update(status='selected' if Path(argv[0]).is_absolute() else 'tool-missing', source='user',
                      argv=argv, cwd=override.get('cwd', str(root)))
    else:
        wrappers = [p for p in candidates if Path(p).name == 'gradlew']
        preferred = str(root / 'gradlew')
        if preferred in wrappers or len(wrappers) == 1:
            wrapper = preferred if preferred in wrappers else wrappers[0]
            result.update(status='selected', source='gradle-wrapper', argv=['/bin/sh', wrapper, 'assemble'], cwd=str(Path(wrapper).parent))
        elif len(wrappers) > 1:
            result.update(status='needs-selection', source='multiple-gradle-roots', argv=[], cwd=str(root))
        else:
            gradle = shutil.which('gradle')
            result.update(status='selected' if gradle else 'tool-missing', source='gradle-default',
                          argv=[gradle, 'assemble'] if gradle else [], cwd=str(root))
    result['timeout_seconds'] = override.get('timeout_seconds', 900)
    result['next_action'] = 'Review module/variant and script behavior, freeze build PATH; do not run automation as part of build'
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--target', required=True)
    p.add_argument('--config', help='JSON object containing optional argv/cwd/timeout_seconds')
    args = p.parse_args()
    print(json.dumps(discover(args.target, json.loads(Path(args.config).read_text()) if args.config else None), ensure_ascii=False, indent=2))
