"""Capture manifest contract (schema 2), absorbed from mobile-ui-snapshot-capture.

A COMPLETE record must carry a real screenshot/view.xml/meta triple whose achieved coverage
satisfies the request; a `scroll` request is COMPLETE only when scrolling actually completed, so a
truncated (scroll-partial) record never advances UI evidence. SOURCE_ONLY is an explicit
no-runtime-evidence handoff and must not carry invented captures. A legacy record without coverage
is never silently upgraded to viewport.
"""
from contracts import nonempty, require

COVERAGE = ('viewport', 'scroll')
STATUS = ('COMPLETE', 'SOURCE_ONLY')


def validate_entry(entry):
    require(isinstance(entry, dict), 'capture entry must be an object')
    require(entry.get('schema_version') == 2, 'capture manifest schema_version 2 required')
    for key in ('page_id', 'state_id'):
        require(isinstance(entry.get(key), str) and entry[key], 'capture entry needs ' + key)
    require(entry.get('coverage') in COVERAGE, 'capture coverage must be viewport/scroll')
    status = entry.get('status')
    require(status in STATUS, 'capture status must be COMPLETE/SOURCE_ONLY')
    if status == 'SOURCE_ONLY':
        require(not entry.get('snapshot'), 'SOURCE_ONLY must not carry invented runtime captures')
        return entry
    snapshot = entry.get('snapshot') or {}
    require(isinstance(snapshot, dict), 'COMPLETE needs a snapshot object')
    for key in ('screenshot', 'view_xml', 'meta'):
        require(isinstance(snapshot.get(key), str) and snapshot[key], 'COMPLETE snapshot needs ' + key)
    nonempty(snapshot.get('captures'), 'COMPLETE snapshot captures')
    expected = 'scroll-complete' if entry['coverage'] == 'scroll' else 'viewport'
    require(entry.get('achieved_coverage') == expected,
            'achieved coverage must be ' + expected + '; partial evidence never advances the cursor')
    require(entry.get('observed_variant'), 'COMPLETE needs observed_variant (selected tab/dialog/page identity)')
    require(entry.get('backend'), 'COMPLETE needs the recording device backend')
    return entry
