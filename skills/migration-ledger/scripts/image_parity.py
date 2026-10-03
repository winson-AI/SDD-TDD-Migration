"""Does a node on the target screen show the reference image? A deterministic answer from bytes.

The reference is a raster rendered from a legacy asset (`reference_render`), the candidate is the crop of
a target screenshot at the node a frozen selector names in the captured view tree. Both are reduced to
the shape of their visible ink, so scale, anti-aliasing, compression and a different tint do not matter,
and a different glyph, a missing or squashed icon, or a wrong colour does. The verdict is a pure function
of the hash-bound inputs and the frozen tolerance: the Ledger recomputes it rather than trusting a report.
Pillow is needed only to measure, never to read tolerances or selectors.
"""
import re
import xml.etree.ElementTree as ET

BOUNDS = re.compile(r'\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]')
SELECTOR_KEYS = ('class', 'resource-id', 'text', 'content-desc')
DEFAULTS = {'shape_iou_min': 0.72, 'aspect_delta_max': 0.20, 'color': None, 'color_delta_max': 48}
LIMITS = {'shape_iou_min': (0.5, 1.0), 'aspect_delta_max': (0.0, 1.0), 'color_delta_max': (0, 255)}
GRID = 48            # both inks are normalised to this many cells per side before they are overlapped
MAX_SIDE = 256       # larger crops are reduced first; icons are small and a whole screen is not an icon
MIN_SIDE = 8         # a node smaller than this shows no recognisable shape
HEX = re.compile(r'#[0-9A-Fa-f]{6}')


class ParityError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ParityError(message)


def thresholds(tolerance=None):
    """The tolerance a check freezes, completed with the defaults and held to hard bounds."""
    tolerance = {} if tolerance is None else tolerance
    require(isinstance(tolerance, dict) and set(tolerance) <= set(DEFAULTS), 'image check tolerance keys: ' + ', '.join(DEFAULTS))
    resolved = {**DEFAULTS, **tolerance}
    for key, (low, high) in LIMITS.items():
        value = resolved[key]
        require(isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high,
                f'image check {key} must be between {low} and {high}')
    color = resolved['color']
    require(color is None or color == 'reference' or (isinstance(color, str) and HEX.fullmatch(color)),
            "image check color is null, 'reference' or #RRGGBB")
    return resolved


def selector_valid(selector):
    return (isinstance(selector, dict) and bool(selector) and set(selector) <= set(SELECTOR_KEYS)
            and all(isinstance(value, str) and value for value in selector.values()))


def locate(view_xml, selector):
    """Bounds (x1, y1, x2, y2) of every node whose attributes equal the selector's, in document order."""
    require(selector_valid(selector), 'image check selector supports non-empty exact class/resource-id/text/content-desc only')
    found = []
    for node in ET.fromstring(view_xml).iter('node'):
        if all(node.get(key) == value for key, value in selector.items()):
            match = BOUNDS.fullmatch(node.get('bounds', ''))
            if match:
                found.append(tuple(int(v) for v in match.groups()))
    return found


def _pillow():
    try:
        from PIL import Image, ImageChops, ImageStat
    except ImportError as exc:
        raise ParityError('Pillow is required to measure image parity') from exc
    return Image, ImageChops, ImageStat


def _reduced(image):
    Image, _, _ = _pillow()
    if max(image.size) > MAX_SIDE:
        image = image.copy()
        image.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    return image


def _ink(rgb, alpha=None):
    """Mask of the visible ink and the reason it cannot be told apart from its background, if any."""
    Image, ImageChops, ImageStat = _pillow()
    if alpha is not None:
        low, high = alpha.getextrema()
        if low < 250 and high > 32:
            return alpha.point(lambda v: 255 if v >= 64 else 0), None
    width, height = rgb.size
    border = [rgb.crop((0, 0, width, 1)), rgb.crop((0, height - 1, width, height)),
              rgb.crop((0, 0, 1, height)), rgb.crop((width - 1, 0, width, height))]
    pixels = [tuple(data[i:i + 3]) for data in (part.tobytes() for part in border) for i in range(0, len(data), 3)]
    background = tuple(sorted(pixel[channel] for pixel in pixels)[len(pixels) // 2] for channel in range(3))
    if max(max(p[c] for p in pixels) - min(p[c] for p in pixels) for c in range(3)) > 40:
        return None, 'the background around the node is not uniform'
    red, green, blue = ImageChops.difference(rgb, Image.new('RGB', rgb.size, background)).split()
    distance = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    peak = distance.getextrema()[1]
    if peak < 32:
        return None, 'no visible ink against the background'
    threshold = max(24, peak * 0.4)
    return distance.point(lambda v: 255 if v >= threshold else 0), None


def _shape(mask):
    Image, _, _ = _pillow()
    box = mask.getbbox()
    cells = mask.crop(box).resize((GRID, GRID), Image.Resampling.BILINEAR).point(lambda v: 255 if v >= 128 else 0)
    return box, cells


def _mean(rgb, mask):
    _, _, ImageStat = _pillow()
    return [round(value, 1) for value in ImageStat.Stat(rgb, mask).mean[:3]]


def _count(mask):
    _, _, ImageStat = _pillow()
    return round(ImageStat.Stat(mask).sum[0] / 255)


def measure(reference, candidate, tolerance=None):
    """(metrics, None) or (None, reason) for a reference image and a candidate crop, both Pillow images."""
    Image, ImageChops, _ = _pillow()
    tolerance = thresholds(tolerance)
    if min(candidate.size) < MIN_SIDE:
        return None, 'the node is too small to show a shape'
    reference, candidate = _reduced(reference.convert('RGBA')), _reduced(candidate.convert('RGB'))
    ref_rgb = reference.convert('RGB')
    ref_mask, why = _ink(ref_rgb, reference.getchannel('A'))
    if ref_mask is None:
        return None, 'reference: ' + why
    cand_mask, why = _ink(candidate)
    if cand_mask is None:
        return None, 'candidate: ' + why
    ref_box, ref_cells = _shape(ref_mask)
    cand_box, cand_cells = _shape(cand_mask)
    inter = _count(ImageChops.darker(ref_cells, cand_cells))
    union = _count(ImageChops.lighter(ref_cells, cand_cells))
    ref_aspect = (ref_box[2] - ref_box[0]) / (ref_box[3] - ref_box[1])
    cand_aspect = (cand_box[2] - cand_box[0]) / (cand_box[3] - cand_box[1])
    metrics = {'shape_iou': round(inter / union, 4), 'aspect_delta': round(abs(ref_aspect - cand_aspect) / max(ref_aspect, cand_aspect), 4),
               'ink_ratio': round(_count(cand_mask) / candidate.size[0] / candidate.size[1], 4)}
    if tolerance['color'] is not None:
        wanted = _mean(ref_rgb, ref_mask) if tolerance['color'] == 'reference' else [int(tolerance['color'][i:i + 2], 16) for i in (1, 3, 5)]
        seen = _mean(candidate, cand_mask)
        metrics.update(expected_color=wanted, candidate_color=seen,
                       color_delta=round(max(abs(a - b) for a, b in zip(wanted, seen)), 1))
    return metrics, None


def verdict(metrics, tolerance=None):
    tolerance = thresholds(tolerance)
    ok = metrics['shape_iou'] >= tolerance['shape_iou_min'] and metrics['aspect_delta'] <= tolerance['aspect_delta_max']
    if tolerance['color'] is not None:
        ok = ok and metrics['color_delta'] <= tolerance['color_delta_max']
    return 'MATCH' if ok else 'MISMATCH'


def evaluate(check, reference_path, screenshot_path, view_xml):
    """One frozen check against one capture: the row a report carries and the Ledger recomputes.

    The crop is returned beside the row so the caller can keep it as evidence."""
    Image, _, _ = _pillow()
    tolerance = thresholds(check.get('tolerance'))
    row = {'id': check['id'], 'node_id': check['node_id'], 'selector': check['target']['selector'], 'tolerance': tolerance,
           'node': None, 'metrics': None}
    nodes = locate(view_xml, check['target']['selector'])
    if len(nodes) != 1:
        return {**row, 'status': 'INCOMPARABLE', 'reason': 'the selector matches ' + str(len(nodes)) + ' nodes; one is required'}, None
    x1, y1, x2, y2 = nodes[0]
    with Image.open(screenshot_path) as shot:
        shot.load()
        box = (max(0, x1), max(0, y1), min(shot.width, x2), min(shot.height, y2))
        if box[2] - box[0] < 1 or box[3] - box[1] < 1:
            return {**row, 'node': {'bounds': list(nodes[0])}, 'status': 'INCOMPARABLE', 'reason': 'the node lies outside the screenshot'}, None
        crop = shot.convert('RGB').crop(box)
    row['node'] = {'bounds': list(nodes[0]), 'crop_box': list(box)}
    with Image.open(reference_path) as reference:
        reference.load()
        metrics, reason = measure(reference, crop, tolerance)
    if metrics is None:
        return {**row, 'status': 'INCOMPARABLE', 'reason': reason}, crop
    return {**row, 'metrics': metrics, 'status': verdict(metrics, tolerance)}, crop
