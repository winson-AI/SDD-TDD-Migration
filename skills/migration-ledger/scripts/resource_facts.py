"""Intrinsic facts of Android resource files and the references inside XML drawables.

Everything is read from file headers or the XML itself with the standard library, so the
collector records sizes, density families, vector viewports and animation metadata beside each
file's hash and planning never depends on a role reading them by hand. Facts describe a file;
they never decide how it is migrated.
"""
import json
from pathlib import Path
import re
import struct
import xml.etree.ElementTree as ET

DENSITY = {'ldpi': 0.75, 'mdpi': 1.0, 'tvdpi': 1.33, 'hdpi': 1.5, 'xhdpi': 2.0, 'xxhdpi': 3.0, 'xxxhdpi': 4.0}
RASTER_SUFFIXES = ('.png', '.webp', '.jpg', '.jpeg', '.gif')
RESOURCE_REF = re.compile(r'[@?](?:android:)?[A-Za-z_][\w.-]*/[A-Za-z_][\w.-]*')
NODE_ID_REF = ('@id/', '@android:id/')
HEADER_BYTES = 65536
JSON_LIMIT = 8 * 1024 * 1024


def local(name):
    return name.rsplit('}', 1)[-1]


def density_scale(qualifier):
    """The dpi multiplier a qualifier names, or None for nodpi/anydpi/default."""
    for token in str(qualifier or '').split('-'):
        if token in DENSITY:
            return DENSITY[token]
    return None


def variant(qualifier):
    """(what a file is for, which rendition of it): the qualifier without its density and platform level, and the density it names.

    `night-xxhdpi` is the night picture at one density; `xxhdpi`, `mdpi` and `anydpi-v24` are the same picture,
    drawn for another screen or another platform version."""
    tokens = [token for token in str(qualifier or '').split('-') if token and token not in ('default', 'base')]
    density = [token for token in tokens if token in DENSITY or token in ('nodpi', 'anydpi') or re.fullmatch(r'\d+dpi', token)]
    rendition = density + [token for token in tokens if re.fullmatch(r'v\d+', token)]
    return '-'.join(token for token in tokens if token not in rendition) or 'base', (density[0] if density else None)


def format_of(path):
    """What a file is, in the words a project uses for what its target loads: png, webp, jpg, gif, vector-xml,
    animation-json, nine-patch, or the bare suffix; other XML and JSON keep their own names and are never pictures."""
    path = Path(path)
    suffix = path.suffix.lower()
    if path.name.lower().endswith('.9.png'):
        return 'nine-patch'
    if suffix in ('.jpg', '.jpeg'):
        return 'jpg'
    if suffix == '.xml':
        try:
            return 'vector-xml' if local(ET.parse(path).getroot().tag) == 'vector' else 'xml'
        except (ET.ParseError, OSError):
            return 'xml'
    if suffix == '.json':
        try:
            text = path.read_text(encoding='utf-8', errors='replace') if path.stat().st_size <= JSON_LIMIT else ''
        except OSError:
            text = ''
        return 'animation-json' if animation_facts(text) else 'json'
    return suffix.lstrip('.') or 'file'


def _png(data):
    if len(data) < 33 or data[12:16] != b'IHDR':
        return None
    width, height = struct.unpack('>II', data[16:24])
    alpha, animated, position = data[25] in (4, 6), False, 8
    while position + 8 <= len(data):
        length, kind = struct.unpack('>I4s', data[position:position + 8])
        alpha = alpha or kind == b'tRNS'
        animated = animated or kind == b'acTL'
        if kind == b'IDAT':
            break
        position += 12 + length
    return {'format': 'png', 'width': width, 'height': height, 'alpha': alpha, 'animated': animated}


def _jpeg(data):
    position = 2
    while position + 4 <= len(data):
        if data[position] != 0xFF:
            position += 1
            continue
        marker = data[position + 1]
        if marker == 0xFF:
            position += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            position += 2
            continue
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            height, width = struct.unpack('>HH', data[position + 5:position + 9])
            return {'format': 'jpeg', 'width': width, 'height': height, 'alpha': False, 'animated': False}
        position += 2 + struct.unpack('>H', data[position + 2:position + 4])[0]
    return None


def _webp(data):
    if len(data) < 30 or data[:4] != b'RIFF' or data[8:12] != b'WEBP':
        return None
    kind = data[12:16]
    if kind == b'VP8X':
        return {'format': 'webp', 'width': 1 + int.from_bytes(data[24:27], 'little'),
                'height': 1 + int.from_bytes(data[27:30], 'little'),
                'alpha': bool(data[20] & 0x10), 'animated': bool(data[20] & 0x02)}
    if kind == b'VP8L' and data[20] == 0x2F:
        bits = int.from_bytes(data[21:25], 'little')
        return {'format': 'webp', 'width': 1 + (bits & 0x3FFF), 'height': 1 + ((bits >> 14) & 0x3FFF),
                'alpha': bool((bits >> 28) & 1), 'animated': False}
    if kind == b'VP8 ' and data[23:26] == b'\x9d\x01\x2a':
        return {'format': 'webp', 'width': struct.unpack('<H', data[26:28])[0] & 0x3FFF,
                'height': struct.unpack('<H', data[28:30])[0] & 0x3FFF, 'alpha': False, 'animated': False}
    return None


def _gif(data):
    if data[:6] not in (b'GIF87a', b'GIF89a'):
        return None
    width, height = struct.unpack('<HH', data[6:10])
    return {'format': 'gif', 'width': width, 'height': height, 'alpha': None, 'animated': None}


def raster_facts(data):
    """Format and pixel size of a PNG, JPEG, WebP or GIF from its first bytes; None when unrecognised."""
    for parse in (_png, _webp, _gif):
        facts = parse(data)
        if facts:
            return facts
    return _jpeg(data) if data[:2] == b'\xff\xd8' else None


def _dp(value):
    match = re.fullmatch(r'\s*(-?[0-9.]+)\s*(dp|dip)\s*', value or '')
    return float(match.group(1)) if match else None


def vector_facts(root):
    attr = lambda name: root.get('{http://schemas.android.com/apk/res/android}' + name)
    facts = {'format': 'vector-xml', 'paths': sum(1 for e in root.iter() if local(e.tag) == 'path')}
    viewport = [attr('viewportWidth'), attr('viewportHeight')]
    if all(viewport):
        facts['viewport'] = [float(v) for v in viewport]
    size = [_dp(attr('width')), _dp(attr('height'))]
    if None not in size:
        facts['size_dp'] = size
    for key, name in (('tint', 'tint'), ('alpha', 'alpha'), ('auto_mirrored', 'autoMirrored')):
        if attr(name) is not None:
            facts[key] = attr(name)
    return facts


def animation_facts(text):
    """Metadata of a Lottie-style animation document; None for any other JSON."""
    try:
        document = json.loads(text)
    except ValueError:
        return None
    if not isinstance(document, dict) or not {'fr', 'ip', 'op', 'layers'} <= set(document):
        return None
    numbers = [document.get(key) for key in ('w', 'h', 'fr', 'ip', 'op')]
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in numbers) or not document['fr']:
        return None
    width, height, rate, start, end = numbers
    return {'format': 'animation-json', 'width': width, 'height': height, 'frame_rate': rate,
            'in_point': start, 'out_point': end, 'duration_s': round((end - start) / rate, 3),
            'layers': len(document['layers']) if isinstance(document['layers'], list) else None}


def file_facts(path, qualifier='base'):
    """Facts of one resource file: bytes always, then format/size/alpha/dp, vector or animation metadata."""
    path = Path(path)
    facts = {'bytes': path.stat().st_size}
    suffix = path.suffix.lower()
    if suffix in RASTER_SUFFIXES:
        with path.open('rb') as handle:
            parsed = raster_facts(handle.read(HEADER_BYTES))
        facts.update(parsed or {'format': suffix.lstrip('.')})
        scale = density_scale(qualifier)
        if parsed and scale:
            facts.update(density=scale, dp=[round(parsed['width'] / scale, 2), round(parsed['height'] / scale, 2)])
    elif suffix == '.xml':
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            return {**facts, 'format': 'xml', 'invalid': True}
        facts.update(vector_facts(root) if local(root.tag) == 'vector' else {'format': 'xml', 'root': local(root.tag)})
    elif suffix == '.json' and facts['bytes'] <= JSON_LIMIT:
        facts.update(animation_facts(path.read_text(encoding='utf-8', errors='replace')) or {'format': 'json'})
    return facts


def references(text):
    """Resource references named inside one attribute or style value, node ids excluded."""
    return sorted({ref for ref in RESOURCE_REF.findall(text or '') if not ref.startswith(NODE_ID_REF)})


def xml_references(root):
    """Every resource reference an XML drawable or state list makes, with where it sits and the state it applies to.

    `via` is the element/attribute that holds the reference; `when` carries the item's state flags
    (state_selected, state_pressed, ...), so a selector's icon per state is a recorded fact."""
    found = {}
    for element in root.iter():
        tag = local(element.tag)
        when = {local(name): value for name, value in element.attrib.items() if local(name).startswith('state_')}
        for name, value in element.attrib.items():
            for ref in references(value):
                via = tag + '/' + local(name)
                found[(ref, via, json.dumps(when, sort_keys=True))] = {'ref': ref, 'via': via, **({'when': when} if when else {})}
    return [found[key] for key in sorted(found)]
