"""Reference rasters rendered from legacy asset files.

A legacy picture can be compared with what the target shows without running the legacy app: the
file in the source tree is the picture. A raster file is decoded; a vector drawable is converted to
SVG (shape only, every fill and stroke is ink) and rasterised by rsvg-convert. Anything else, such
as an animation or a state list, has no single picture and is refused rather than approximated.
"""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

import resource_facts

ANDROID = '{http://schemas.android.com/apk/res/android}'
RASTER = ('.png', '.webp', '.jpg', '.jpeg', '.gif')
PIXELS_PER_DP = 4


class RenderError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise RenderError(message)


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _family(qualifier):
    return 'base' if qualifier in (None, '', 'default') else qualifier


def _attr(element, name):
    return element.get(ANDROID + name)


def _number(value, fallback=0.0):
    try:
        return float(re.sub(r'(dp|dip|px|sp)$', '', (value or '').strip()))
    except ValueError:
        return fallback


def _transparent(color, alpha):
    if color is None:
        return True
    literal = re.fullmatch(r'#([0-9A-Fa-f]{2})?[0-9A-Fa-f]{6}', color.strip())
    return bool(literal and literal.group(1) and int(literal.group(1), 16) == 0) or _number(alpha, 1.0) == 0


def _inline(element, name):
    """Whether a colour is given by a nested `aapt:attr` (a gradient), which is ink like any other colour."""
    return any(resource_facts.local(child.tag) == 'attr' and child.get('name') == 'android:' + name for child in element)


def _path(element):
    data = _attr(element, 'pathData')
    require(data and not data.startswith(('@', '?')), 'a vector path whose data is a resource reference cannot be rendered')
    paint = lambda name: '#000' if _inline(element, name + 'Color') or not _transparent(_attr(element, name + 'Color'), _attr(element, name + 'Alpha')) else 'none'
    fill, stroke = paint('fill'), paint('stroke')
    parts = [f'd="{data}"', f'fill="{fill}"', f'stroke="{stroke}"',
             'fill-rule="' + ('evenodd' if _attr(element, 'fillType') == 'evenOdd' else 'nonzero') + '"']
    if stroke != 'none':
        parts.append(f'stroke-width="{_number(_attr(element, "strokeWidth"), 0.0)}"')
        for name, svg in (('strokeLineCap', 'stroke-linecap'), ('strokeLineJoin', 'stroke-linejoin'), ('strokeMiterLimit', 'stroke-miterlimit')):
            if _attr(element, name):
                parts.append(f'{svg}="{_attr(element, name)}"')
    return '<path ' + ' '.join(parts) + '/>'


def _group(element, ids):
    pivot = (_number(_attr(element, 'pivotX')), _number(_attr(element, 'pivotY')))
    move = (_number(_attr(element, 'translateX')), _number(_attr(element, 'translateY')))
    transform = (f'translate({move[0]},{move[1]}) translate({pivot[0]},{pivot[1]}) rotate({_number(_attr(element, "rotation"))}) '
                 f'scale({_number(_attr(element, "scaleX"), 1.0)},{_number(_attr(element, "scaleY"), 1.0)}) translate({-pivot[0]},{-pivot[1]})')
    return f'<g transform="{transform}">' + _children(element, ids) + '</g>'


def _children(parent, ids):
    """Siblings in order; a clip-path clips every sibling after it within the same parent."""
    out, closers = [], 0
    for element in parent:
        tag = resource_facts.local(element.tag)
        if tag == 'path':
            out.append(_path(element))
        elif tag == 'group':
            out.append(_group(element, ids))
        elif tag == 'clip-path':
            ids.append(len(ids))
            region = f'<path d="{_attr(element, "pathData")}"/>'
            out.append(f'<clipPath id="c{ids[-1]}">{region}</clipPath><g clip-path="url(#c{ids[-1]})">')
            closers += 1
    return ''.join(out) + '</g>' * closers


def vector_svg(root):
    """SVG of a vector drawable and its pixel size; every fill and stroke is ink, colours are not carried."""
    viewport = [_number(_attr(root, 'viewportWidth')), _number(_attr(root, 'viewportHeight'))]
    require(all(v > 0 for v in viewport), 'a vector drawable needs a viewport to be rendered')
    size = [_number(_attr(root, 'width'), viewport[0]) * PIXELS_PER_DP, _number(_attr(root, 'height'), viewport[1]) * PIXELS_PER_DP]
    width, height = (max(1, round(v)) for v in size)
    body = _children(root, [])
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {viewport[0]} {viewport[1]}">'
            f'{body}</svg>'), (width, height)


def _rsvg():
    tool = shutil.which('rsvg-convert')
    require(tool, 'vector rendering needs rsvg-convert on PATH')
    return tool


def render(index, ref, qualifier, out):
    """Render one declaration of a resource to `out/reference.png` and describe it in `out/reference.json`."""
    out = Path(out)
    base = Path(index.get('androidRoot', '')).resolve()
    require(base.is_absolute() and base.is_dir(), 'the source index needs an existing androidRoot')
    rows = [row for row in index.get('resources', []) if row.get('ref') == ref and row.get('path')
            and _family(row.get('qualifier')) == _family(qualifier)]
    require(len(rows) == 1, f'the source index has no single declaration of {ref} / {_family(qualifier)}')
    source = (base / rows[0]['path']).resolve()
    require(source.is_relative_to(base) and source.is_file(), 'the resource file must lie inside the Android root')
    require(_sha256(source) == rows[0]['sha256'], 'the resource file changed after it was indexed')
    suffix = source.suffix.lower()
    png = out / 'reference.png'
    if suffix in RASTER:
        try:
            from PIL import Image
        except ImportError as exc:
            raise RenderError('Pillow is required to render a raster reference') from exc
        with Image.open(source) as image:
            image.seek(0)
            image.convert('RGBA').save(png, format='PNG')
        import PIL
        mode, renderer = 'color', {'name': 'pillow', 'version': PIL.__version__}
    elif suffix == '.xml':
        try:
            root = ET.parse(source).getroot()
        except ET.ParseError as exc:
            raise RenderError('the vector drawable is not valid XML') from exc
        require(resource_facts.local(root.tag) == 'vector', f'{ref} is a {resource_facts.local(root.tag)}, which has no single picture to render')
        svg, (width, height) = vector_svg(root)
        svg_file = out / 'reference.svg'
        svg_file.write_text(svg)
        tool = _rsvg()
        subprocess.run([tool, '-w', str(width), '-h', str(height), str(svg_file), '-o', str(png)],
                       check=True, capture_output=True, timeout=60, cwd=out)
        version = subprocess.run([tool, '--version'], capture_output=True, text=True, timeout=10).stdout.strip()
        mode, renderer = 'mask', {'name': 'rsvg-convert', 'version': version}
    else:
        raise RenderError(f'{source.name}: reference rendering supports raster images and vector drawables only')
    from PIL import Image
    with Image.open(png) as rendered:
        size = list(rendered.size)
        alpha = 'A' in rendered.getbands()
    document = {'schema_version': 1, 'producer': 'sdd-reference-render', 'source_resource': ref, 'qualifier': _family(qualifier),
                'source_ref': {'path': str(source), 'sha256': rows[0]['sha256']}, 'mode': mode, 'width': size[0], 'height': size[1],
                'alpha': alpha, 'png_ref': {'path': str(png.resolve()), 'sha256': _sha256(png)}, 'renderer': renderer}
    (out / 'reference.json').write_text(json.dumps(document, indent=2, ensure_ascii=False) + '\n')
    return document
