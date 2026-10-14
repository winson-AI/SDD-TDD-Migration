"""The commit of the workflow package a run is pinned to: a run runs to completion on the package it was prepared with,
and a rule written later binds the next run."""
from functools import lru_cache
import subprocess


@lru_cache(maxsize=None)
def sha(root):
    """The git HEAD commit of `root`, or None when it is not a git checkout."""
    if not root:
        return None
    try:
        out = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    value = out.stdout.strip()
    return value if out.returncode == 0 and len(value) == 40 else None
