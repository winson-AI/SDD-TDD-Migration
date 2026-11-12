"""Frozen device conditions and the observed configuration of a visual capture."""
import re
from pathlib import Path

from contracts import require

DPI = dict(zip(('ldpi', 'mdpi', 'tvdpi', 'hdpi', 'xhdpi', 'xxhdpi', 'xxxhdpi'),
               (120, 160, 213, 240, 320, 480, 640)))
PROBE = ('shell', 'am', 'get-config')
LOCALE = r'(?:[a-z]{2,3}(?:-r[A-Z]{2})?|b\+[A-Za-z0-9+]+)'
FIELDS = ('density_dpi', 'night', 'smallest_width_dp', 'api_level', 'locale')
OTHER = {'car', 'desk', 'land', 'port', 'long', 'round', 'watch', 'vrheadset', 'television', 'widecg', 'highdr'}


def validate(value):
    require(isinstance(value, dict) and value and set(value) <= set(FIELDS), 'invalid visual device_configuration fields')
    for key, item in value.items():
        valid = (type(item) is bool if key == 'night' else
                 isinstance(item, str) and re.fullmatch(LOCALE, item) if key == 'locale' else
                 type(item) is int and item > 0)
        require(valid, 'invalid visual device_configuration ' + key)
    return value


def matches(actual, expected):
    return all(actual.get(key) == value for key, value in expected.items())


def tokens(value):
    # Keep the first locale in a device locale list and keep its region together.
    value = re.sub(r',[^-\s]+(?:-r[A-Z]{2})?', '', value)
    return re.findall(r'[a-z]{2,3}-r[A-Z]{2}|[^-]+', value)


def condition(token):
    if token in DPI:
        return 'density_dpi', DPI[token]
    if token in ('night', 'notnight'):
        return 'night', token == 'night'
    for key, pattern in (('density_dpi', r'(\d+)dpi'), ('smallest_width_dp', r'sw(\d+)dp'), ('api_level', r'v(\d+)')):
        match = re.fullmatch(pattern, token)
        if match:
            return key, int(match[1])
    if token not in OTHER and re.fullmatch(LOCALE, token):
        return 'locale', token
    return None


def parse(stdout):
    line = re.search(r'^config:\s*(\S+)', stdout, re.MULTILINE)
    return dict(pair for token in tokens(line[1]) if (pair := condition(token))) if line else {}


def from_log(rows, device_id, external):
    probes = [(i, parse(row.get('stdout') or '')) for i, row in enumerate(rows)
              if row.get('exit_code') == 0 and isinstance(argv := row.get('argv'), list) and len(argv) == 6
              and Path(argv[0]).name == 'adb' and argv[1:3] == ['-s', device_id] and tuple(argv[3:]) == PROBE]
    screenshots = [i for i, row in enumerate(rows) if row.get('exit_code') == 0
                   and (argv := row.get('argv') or [])[1:3] == ['-s', device_id] and 'screencap' in argv]
    if probes and screenshots and probes[0][0] < screenshots[0] <= screenshots[-1] < probes[-1][0]:
        return probes[0][1] if all(config == probes[0][1] for _, config in probes) else {}
    observed = [row['device_configuration'] for row in external if row.get('device_id') == device_id
                and row.get('device_configuration')]
    return validate(observed[0]) if observed and all(config == observed[0] for config in observed) else {}


def applicable(actual, qualifier):
    if qualifier in ('base', 'default', None):
        return True
    if not actual:
        return False
    for token in tokens(qualifier):
        if token in ('anydpi', 'nodpi'):
            if 'density_dpi' not in actual:
                return False
            continue
        pair = condition(token)
        if not pair:
            return False
        key, value = pair
        found = actual.get(key)
        if key in ('api_level', 'smallest_width_dp'):
            if found is None or found < value:
                return False
        elif key == 'locale' and found and '-r' not in value and not value.startswith('b+'):
            if found.split('-r')[0] != value:
                return False
        elif found != value:
            return False
    return True


def qualifier_rank(qualifier):
    """Order the supported conditions from locale to API level."""
    parts = tokens(qualifier)
    values = dict(pair for token in parts if (pair := condition(token)))
    locale = values.get('locale')
    locale_rank = 0 if not locale else 1 if re.fullmatch(r'[a-z]{2,3}', locale) else 2
    density_rank = 3 if 'anydpi' in parts else 2 if 'density_dpi' in values else 1 if 'nodpi' in parts else 0
    return (locale_rank, values.get('smallest_width_dp', 0), 'night' in values, density_rank,
            values.get('api_level', 0))


def distinguishes(actual, qualifier, alternatives):
    """Report a rendition only if a stronger matching source qualifier cannot shadow it."""
    if not applicable(actual, qualifier):
        return False
    base = (None, 'base', 'default')
    rank = qualifier_rank(qualifier) if qualifier not in base else (0, 0, False, 0, 0)
    return not any(qualifier_rank(other) >= rank for other in alternatives
                   if other not in (*base, qualifier) and applicable(actual, other))
