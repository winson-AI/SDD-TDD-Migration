"""A UI tree for a legacy web application, derived from the runtime index of its browser captures alone: there is no source
index, every node id is the element id the DOM declares (or the element's path on that screen), each node carries the runtime
observation placing it on its page and state, and the image sources the DOM names are recorded, never carried."""
from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET


def _element_id(attrs: dict, page_id: str, state_id: str, path: str) -> str:
    rid = (attrs.get('resource-id') or '').strip()
    return 'node:' + rid if rid and all(ch.isalnum() or ch in '/_.-' for ch in rid) and rid[0].isalnum() else f'node:{page_id}.{state_id}/{path}'


def _node(element: ET.Element, page_id: str, state_id: str, path: str, seen: set, images: list) -> dict:
    attrs = element.attrib
    nid = _element_id(attrs, page_id, state_id, path)
    if nid in seen:  # two elements with one DOM id: the second is addressed by its path
        nid = f'node:{page_id}.{state_id}/{path}'
    seen.add(nid)
    children = [_node(child, page_id, state_id, f'{path}.{i}', seen, images) for i, child in enumerate(element) if child.tag == 'node']
    presentation = {'resourceRefs': []}
    if attrs.get('image-src'):
        presentation['imageSource'] = attrs['image-src']
        images.append({'nodeId': nid, 'src': attrs['image-src'], 'pageId': page_id, 'stateId': state_id})
    observation = {'pageId': page_id, 'stateId': state_id, 'class': attrs.get('class', ''), 'text': attrs.get('text', ''),
                   'contentDesc': attrs.get('content-desc', ''), 'bounds': attrs.get('bounds', ''), 'scrollable': attrs.get('scrollable') == 'true'}
    return {'id': nid, 'kind': 'container' if children else 'view', 'presentation': presentation, 'bindings': [], 'events': [],
            'dynamicRules': [], 'capabilities': [], 'runtimeObservations': [observation], 'children': children}


def build(index: dict, index_ref: dict, scope: str, platform: str = 'web') -> dict:
    """One screen per captured page:state, built from the first viewport's view tree of that capture: the document body of a
    web page, the application node of a Harmony layout."""
    screens, images = [], []
    for capture in index.get('captures', []):
        page_id, state_id = capture['pageId'], capture['stateId']
        view = (capture.get('viewports') or [{}])[0].get('viewTree') or capture.get('viewTree')
        root = ET.fromstring(Path(view['path']).read_text(encoding='utf-8', errors='replace'))
        body = root if platform == 'harmony' else next(iter(root), None)
        if body is None:
            raise RuntimeError(f'{page_id}:{state_id} view tree has no element')
        screens.append({'id': f'screen:{page_id}.{state_id}', 'root': _node(body, page_id, state_id, 'body', set(), images), 'attachments': {}})
    if not screens:
        raise RuntimeError('a runtime-derived UI tree needs at least one captured page:state')
    return {'schemaVersion': 1, 'scope': scope,
            'generatedFrom': {'platform': platform, 'sourceIndex': None, 'sourceIndexSha256': None,
                              'runtimeIndex': index_ref['path'], 'runtimeIndexSha256': index_ref['sha256'],
                              'manifest': index.get('manifest'), 'manifestSha256': index.get('manifestSha256')},
            'screens': screens, 'layoutClosure': [], 'criticalLayoutContracts': [], 'unresolved': [], 'imageSources': images}
