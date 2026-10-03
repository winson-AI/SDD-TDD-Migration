"""UI parameters as records: the value a layout attribute, a drawable layer or a setter call gives a component.

A size, a colour, a text or a radius is data. It is read here once, with its unit and where it came from,
so the target is filled from the record instead of from somebody reading the source again. Everything is
deterministic: a literal becomes a typed value, a resource reference stays a reference to be resolved from
the index, a named constant stays a token, and what is computed at run time is kept as an expression that
a person has to settle. Whether a value is used in the target is decided elsewhere.
"""
import re
import xml.etree.ElementTree as ET

import resource_facts
import resource_signals

DIMENSION = re.compile(r'^(-?\d+(?:\.\d+)?)(dp|dip|sp|px|pt|mm|in)$')
COLOR = re.compile(r'^#([0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$')
NUMBER = re.compile(r'^-?\d+(?:\.\d+)?$')
PERCENT = re.compile(r'^(-?\d+(?:\.\d+)?)%p?$')
# Attributes whose literal value is text shown to a person; any other bare word is a keyword such as match_parent.
TEXT_ATTRS = {'text', 'hint', 'contentDescription', 'title', 'subtitle', 'summary', 'label', 'tooltipText', 'textOn', 'textOff', 'queryHint'}
# Attributes that name the node, a handler or another document rather than how the node looks.
SKIPPED_ATTRS = {'id', 'onClick', 'name', 'class', 'layout', 'theme', 'tag', 'labelFor', 'accessibilityTraversalBefore',
                 'accessibilityTraversalAfter', 'nextFocusUp', 'nextFocusDown', 'nextFocusLeft', 'nextFocusRight', 'nextFocusForward'}
LAYER_ROOTS = {'shape', 'selector', 'layer-list', 'inset', 'ripple', 'rotate', 'scale', 'clip', 'level-list', 'transition',
               'bitmap', 'nine-patch', 'color', 'set', 'alpha', 'translate', 'objectAnimator', 'animator'}


def local(name):
    return name.rsplit('}', 1)[-1].split(':')[-1]


def color(text):
    """#AARRGGBB for any Android colour literal."""
    digits = text.lstrip('#')
    if len(digits) in (3, 4):
        digits = ''.join(char * 2 for char in digits)
    return '#' + (digits if len(digits) == 8 else 'FF' + digits).upper()


def number(text):
    value = float(text)
    return int(value) if value == int(value) else value


def literal(text, attr=None):
    """A literal as a typed value, or a reference/token for something the index or a person has to resolve."""
    text = (text or '').strip()
    if text.startswith('?'):
        return {'type': 'token', 'token': text}
    if text.startswith('@'):
        return {'type': 'keyword', 'value': 'null'} if text in ('@null', '@empty') else {'type': 'reference', 'ref': text.replace('@+', '@')}
    match = DIMENSION.match(text)
    if match:
        return {'type': 'dimension', 'value': number(match.group(1)), 'unit': 'dp' if match.group(2) == 'dip' else match.group(2)}
    if COLOR.match(text):
        return {'type': 'color', 'value': color(text)}
    if attr in TEXT_ATTRS:
        return {'type': 'string', 'value': text}
    if NUMBER.match(text):
        return {'type': 'number', 'value': number(text)}
    match = PERCENT.match(text)
    if match:
        return {'type': 'dimension', 'value': number(match.group(1)), 'unit': '%'}
    if text in ('true', 'false'):
        return {'type': 'boolean', 'value': text == 'true'}
    return {'type': 'keyword', 'value': text}


def attributes(attrs):
    """[(name, typed value)] for one XML element's attributes, without what only identifies or wires it."""
    found = []
    for raw, value in sorted(attrs.items()):
        if raw.startswith(('tools:', 'xmlns', '{http://schemas.android.com/tools}')):
            continue
        name = local(raw)
        if name not in SKIPPED_ATTRS and raw != 'style':
            found.append((name, literal(value, name)))
    return found


def xml_parameters(root):
    """Every parameter a drawable, colour list or animation XML states, named by its place in the file.

    `selector/item[2]/shape/corners.radius`: the element path, an index only among siblings of one tag, then the attribute."""
    rows = []
    def walk(element, path):
        for name, value in attributes(element.attrib):
            rows.append({'path': path, 'name': name, **value})
        counts, totals = {}, {}
        for child in element:
            totals[local(child.tag)] = totals.get(local(child.tag), 0) + 1
        for child in element:
            tag = local(child.tag)
            counts[tag] = counts.get(tag, 0) + 1
            walk(child, path + '/' + tag + ('[%d]' % counts[tag] if totals[tag] > 1 else ''))
    walk(root, local(root.tag))
    return rows


def layer_parameters(path):
    """Parameters of a resource file that is a layer description rather than a picture; None for anything else."""
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return None
    return xml_parameters(root) if local(root.tag) in LAYER_ROOTS else None


# ----------------------------------------------------------------------------- setter calls in code

# method -> (parameter names by position, unit of a bare number). A unit of None means the number is not a length.
SETTERS = {
    'setTextSize': (('textSize',), 'sp'), 'setPadding': (('paddingLeft', 'paddingTop', 'paddingRight', 'paddingBottom'), 'px'),
    'setPaddingRelative': (('paddingStart', 'paddingTop', 'paddingEnd', 'paddingBottom'), 'px'),
    'setTextColor': (('textColor',), None), 'setHintTextColor': (('hintTextColor',), None), 'setLinkTextColor': (('linkTextColor',), None),
    'setHighlightColor': (('highlightColor',), None), 'setBackgroundColor': (('backgroundColor',), None),
    'setBackgroundResource': (('background',), None), 'setBackground': (('background',), None), 'setBackgroundDrawable': (('background',), None),
    'setForeground': (('foreground',), None), 'setImageResource': (('image',), None), 'setImageDrawable': (('image',), None),
    'setText': (('text',), None), 'setHint': (('hint',), None), 'setContentDescription': (('contentDescription',), None),
    'setTitle': (('title',), None), 'setSubtitle': (('subtitle',), None),
    'setGravity': (('gravity',), None), 'setMaxLines': (('maxLines',), None), 'setMinLines': (('minLines',), None), 'setLines': (('lines',), None),
    'setSingleLine': (('singleLine',), None), 'setEllipsize': (('ellipsize',), None), 'setAlpha': (('alpha',), None),
    'setVisibility': (('visibility',), None), 'setLineSpacing': (('lineSpacingExtra', 'lineSpacingMultiplier'), 'px'),
    'setLetterSpacing': (('letterSpacing',), None), 'setTypeface': (('typeface', 'textStyle'), None),
    'setMinWidth': (('minWidth',), 'px'), 'setMinHeight': (('minHeight',), 'px'), 'setMinimumWidth': (('minWidth',), 'px'),
    'setMinimumHeight': (('minHeight',), 'px'), 'setMaxWidth': (('maxWidth',), 'px'), 'setMaxHeight': (('maxHeight',), 'px'),
    'setElevation': (('elevation',), 'px'), 'setScaleType': (('scaleType',), None), 'setColorFilter': (('tint', 'tintMode'), None),
    'setCompoundDrawablePadding': (('drawablePadding',), 'px'), 'setTranslationX': (('translationX',), 'px'),
    'setTranslationY': (('translationY',), 'px'), 'setScaleX': (('scaleX',), None), 'setScaleY': (('scaleY',), None),
    'setRotation': (('rotation',), None), 'setTextAlignment': (('textAlignment',), None), 'setIncludeFontPadding': (('includeFontPadding',), None),
    'setOrientation': (('orientation',), None), 'setHorizontalGravity': (('horizontalGravity',), None), 'setVerticalGravity': (('verticalGravity',), None),
}
PROPERTIES = {'textSize': 'sp', 'alpha': None, 'text': None, 'hint': None, 'contentDescription': None, 'visibility': None, 'gravity': None,
              'maxLines': None, 'minLines': None, 'elevation': 'px', 'translationX': 'px', 'translationY': 'px', 'scaleX': None, 'scaleY': None,
              'rotation': None, 'letterSpacing': None, 'orientation': None}
SETTER = re.compile(r'\b(?P<receiver>[A-Za-z_][\w.]*?)\s*\.\s*(?P<method>' + '|'.join(sorted(SETTERS, key=len, reverse=True)) + r')\s*\(')
PROPERTY = re.compile(r'\b(?P<receiver>[A-Za-z_][\w.]*?)\s*\.\s*(?P<name>' + '|'.join(sorted(PROPERTIES, key=len, reverse=True)) + r')\s*=(?!=)\s*(?P<value>[^\n;]+)')
ADD_VIEW = re.compile(r'\.\s*addView\s*\(')
LAYOUT_PARAMS = re.compile(r'^(?:new\s+)?[\w.]*LayoutParams$')
LENGTH = re.compile(r'^(?:[\w.]+\.)?(?P<unit>dp|sp)(?:ToPx|Float|f)?\s*\(\s*(?P<number>-?\d+(?:\.\d+)?)[fFdL]?\s*\)$')
POSTFIX = re.compile(r'^(?P<number>-?\d+(?:\.\d+)?)[fF]?\s*\.\s*(?P<unit>dp|sp)$')
BARE = re.compile(r'^-?\d+(?:\.\d+)?[fFdL]?$')
HEX = re.compile(r'^0[xX]([0-9a-fA-F]{6}|[0-9a-fA-F]{8})$')
PARSED_COLOR = re.compile(r'^Color\.parseColor\(\s*"(#[0-9a-fA-F]{3,8})"\s*\)$')
TEXT = re.compile(r'^"((?:\\.|[^"\\])*)"$')
RESOURCE = re.compile(r'(?<![\w.])(android\.)?R\.(\w+)\.(\w+)')
CONSTANT = re.compile(r'^(?:[\w.]+\.)?[A-Z][A-Z0-9_]*(?:\s*\|\s*(?:[\w.]+\.)?[A-Z][A-Z0-9_]*)*$')
COMPLEX_UNIT = re.compile(r'^TypedValue\.COMPLEX_UNIT_(DIP|SP|PX|PT)$')
NAMED = re.compile(r'(?:[A-Za-z_]\w*\.)+[A-Za-z_]\w*')
COLOR_PARAMS = ('Color', 'tint', 'background')


def expression(text, unit=None, colour=False):
    """One argument of a setter as a typed value."""
    text = ' '.join(text.split())
    match = LENGTH.match(text) or POSTFIX.match(text)
    if match:
        return {'type': 'dimension', 'value': number(match.group('number')), 'unit': match.group('unit')}
    match = HEX.match(text)
    if match and (colour or len(match.group(1)) == 8):
        return {'type': 'color', 'value': color('#' + match.group(1))}
    match = PARSED_COLOR.match(text)
    if match:
        return {'type': 'color', 'value': color(match.group(1))}
    if BARE.match(text):
        value = number(text.rstrip('fFdL'))
        return {'type': 'dimension', 'value': value, 'unit': unit} if unit else {'type': 'number', 'value': value}
    if text in ('true', 'false'):
        return {'type': 'boolean', 'value': text == 'true'}
    if text == 'null':
        return {'type': 'keyword', 'value': 'null'}
    match = TEXT.match(text)
    if match:
        return {'type': 'string', 'value': match.group(1)}
    refs = RESOURCE.findall(text)
    if len(refs) == 1 and not re.search(r'[?:+]|\bif\b', RESOURCE.sub('', text)):
        platform, kind, name = refs[0]
        return {'type': 'reference', 'ref': ('@android:' if platform else '@') + kind + '/' + name}
    if CONSTANT.match(text):
        return {'type': 'keyword', 'value': text}
    # A value named in code (a theme key, a typeface helper) is the same token wherever it is used: one named field
    # among the arguments, or a call without arguments that is the whole value. Anything else is computed at run time.
    if re.fullmatch(r'(?:[A-Za-z_]\w*\.)+[A-Za-z_]\w*\(\s*\)', text):
        return {'type': 'token', 'token': text[:text.index('(')], 'text': text}
    if not re.search(r'[?+\-*/<>\[]|\bif\b', NAMED.sub('', text)):
        fields = {match.group(0) for match in NAMED.finditer(text) if not re.match(r'\s*\(', text[match.end():])}
        if len(fields) == 1:
            return {'type': 'token', 'token': fields.pop(), 'text': text}
    return {'type': 'expression', 'text': text}


def _row(text, offset, symbols, receiver, name, value, raw):
    row = {'receiver': receiver, 'name': name, 'line': resource_signals.line_of(text, offset), 'raw': resource_signals.normalize(raw, 240), **value}
    symbol = symbols.at(offset)
    if symbol:
        row['symbol'] = symbol
    return row


def code_parameters(text, relative, symbols=None, helpers=()):
    """What setter calls, property assignments and layout parameters give the views of one source file.

    `helpers` are a project's own layout-parameter builders: {call, params[, unit]} per arity, declared once."""
    symbols = symbols or resource_signals.Symbols(text, relative.endswith('.kt'))
    rows = []
    for match in SETTER.finditer(text):
        close = resource_signals.balanced(text, match.end() - 1)
        if close is None or symbols.outside_code(match.start()):
            continue
        names, unit = SETTERS[match.group('method')]
        args = resource_signals.split_args(text[match.end():close - 1])
        if match.group('method') == 'setTextSize' and len(args) == 2:
            declared = COMPLEX_UNIT.match(args[0].strip())
            unit, args = ({'DIP': 'dp', 'SP': 'sp', 'PX': 'px', 'PT': 'pt'}[declared.group(1)] if declared else unit), args[1:]
        for name, argument in zip(names, args):
            value = expression(argument, unit, any(part in name for part in COLOR_PARAMS))
            rows.append(_row(text, match.start(), symbols, match.group('receiver'), name, value, text[match.start():close]))
    for match in PROPERTY.finditer(text) if relative.endswith('.kt') else ():   # in Java such an assignment is a field, not a view property
        if symbols.outside_code(match.start()) or match.group('receiver') in ('this', 'it'):
            continue
        name = match.group('name')
        value = expression(match.group('value'), PROPERTIES[name], 'Color' in name)
        rows.append(_row(text, match.start(), symbols, match.group('receiver'), name, value, match.group(0)))
    signatures = {}
    for helper in helpers:
        signatures[(helper['call'].rsplit('.', 1)[-1], len(helper['params']))] = helper
    for match in ADD_VIEW.finditer(text):
        close = resource_signals.balanced(text, match.end() - 1)
        args = resource_signals.split_args(text[match.end():close - 1]) if close else []
        if len(args) < 2 or symbols.outside_code(match.start()):
            continue
        call = re.match(r'^(?P<name>(?:new\s+)?[\w.]+)\s*\((?P<args>.*)\)$', ' '.join(args[-1].split()), re.S)
        if not call:
            continue
        inner = resource_signals.split_args(call.group('args'))
        helper = signatures.get((call.group('name').rsplit('.', 1)[-1], len(inner)))
        if helper:
            names, unit = helper['params'], helper.get('unit')
        elif LAYOUT_PARAMS.match(call.group('name')) and len(inner) >= 2:
            names, unit = ('layout_width', 'layout_height', 'layout_weight')[:len(inner)], 'px'
        else:
            continue
        for name, argument in zip(names, inner):
            rows.append(_row(text, match.start(), symbols, args[0].strip(), name,
                             expression(argument, None if name in ('layout_weight', 'layout_gravity', 'gravity') else unit), text[match.start():close]))
    rows.sort(key=lambda row: (row['line'], row['receiver'], row['name']))
    return rows
