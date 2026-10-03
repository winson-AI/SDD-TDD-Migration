"""Reference rasters from legacy assets, and the shape-and-colour comparison of a target node with them."""
import io
import json
import math
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from PIL import Image, ImageDraw

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import image_parity as ip
import reference_render as rr
from contracts import file_ref


def glyph(kind, size, color=(0, 0, 0, 255), mirror=False, stretch=(1, 1), thin=False):
    """A transparent icon drawn at 4x and reduced, as an exported asset would be."""
    s = size * 4
    image = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    width = max(2, int(s * (0.07 if thin else 0.12)))
    point = lambda x, y: (x * s, y * s)
    if kind == 'back':
        draw.line([point(.8, .5), point(.2, .5)], fill=color, width=width)
        draw.line([point(.45, .25), point(.2, .5), point(.45, .75)], fill=color, width=width, joint='curve')
    elif kind == 'chevron':
        draw.line([point(.35, .2), point(.65, .5), point(.35, .8)], fill=color, width=width, joint='curve')
    elif kind == 'plus':
        draw.line([point(.5, .2), point(.5, .8)], fill=color, width=width)
        draw.line([point(.2, .5), point(.8, .5)], fill=color, width=width)
    elif kind == 'ring':
        draw.ellipse([point(.2, .2), point(.8, .8)], outline=color, width=width)
    elif kind == 'star':
        points = [(0.5 + (0.38 if i % 2 == 0 else 0.16) * math.sin(i * math.pi / 5),
                   0.52 - (0.38 if i % 2 == 0 else 0.16) * math.cos(i * math.pi / 5)) for i in range(10)]
        draw.polygon([point(*p) for p in points], fill=color)
    image = image.resize((size, size), Image.Resampling.LANCZOS)
    if mirror:
        image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if stretch != (1, 1):
        image = image.resize((int(size * stretch[0]), int(size * stretch[1])), Image.Resampling.LANCZOS)
    return image


def on_screen(icon, background=(255, 255, 255), padding=10, jpeg=75, tint=None):
    """The icon as a device would show it: tinted, on a background, compressed."""
    if tint:
        icon = Image.merge('RGBA', (*(Image.new('L', icon.size, c) for c in tint), icon.getchannel('A')))
    canvas = Image.new('RGB', (icon.width + 2 * padding, icon.height + 2 * padding), background)
    canvas.paste(icon, (padding, padding), icon)
    if jpeg:
        out = io.BytesIO()
        canvas.save(out, 'JPEG', quality=jpeg)
        out.seek(0)
        canvas = Image.open(out)
        canvas.load()
    return canvas


class ToleranceTests(unittest.TestCase):
    def test_defaults_are_completed_and_bounds_are_hard(self):
        self.assertEqual(ip.thresholds(), ip.DEFAULTS)
        self.assertEqual(ip.thresholds({'shape_iou_min': 0.9})['aspect_delta_max'], 0.2)
        for bad in ({'shape_iou_min': 0.2}, {'shape_iou_min': 1.5}, {'aspect_delta_max': -1}, {'color_delta_max': 300},
                    {'color': 'red'}, {'color': '#12345'}, {'unknown': 1}, {'shape_iou_min': True}, 'tight'):
            with self.subTest(bad=bad), self.assertRaises(ip.ParityError):
                ip.thresholds(bad)
        self.assertEqual(ip.thresholds({'color': '#6200EE'})['color'], '#6200EE')
        self.assertEqual(ip.thresholds({'color': 'reference'})['color'], 'reference')

    def test_selectors_are_exact_attribute_matches(self):
        view = ('<hierarchy><node class="Image" resource-id="back" bounds="[10,20][58,68]"/>'
                '<node class="Image" resource-id="more" bounds="[100,20][148,68]"/>'
                '<node class="Image" resource-id="more" bounds="[100,80][148,128]"/></hierarchy>')
        self.assertEqual(ip.locate(view, {'resource-id': 'back'}), [(10, 20, 58, 68)])
        self.assertEqual(len(ip.locate(view, {'resource-id': 'more'})), 2)
        self.assertEqual(ip.locate(view, {'resource-id': 'back', 'class': 'Other'}), [])
        for bad in ({}, {'bounds': '[0,0][1,1]'}, {'text': ''}, 'back'):
            with self.subTest(bad=bad), self.assertRaises(ip.ParityError):
                ip.locate(view, bad)


class ShapeParityTests(unittest.TestCase):
    reference = glyph('back', 72)

    def verdict(self, candidate, tolerance=None):
        metrics, why = ip.measure(self.reference, candidate, tolerance)
        return (ip.verdict(metrics, tolerance) if metrics else 'INCOMPARABLE'), metrics, why

    def test_the_same_icon_matches_whatever_the_scale_compression_or_tint(self):
        for size in (36, 48, 72, 96, 144):
            for jpeg in (None, 90, 60):
                with self.subTest(size=size, jpeg=jpeg):
                    self.assertEqual(self.verdict(on_screen(glyph('back', size), jpeg=jpeg))[0], 'MATCH')
        self.assertEqual(self.verdict(on_screen(glyph('back', 24)))[0], 'MATCH')  # a small icon with thin strokes still passes
        self.assertEqual(self.verdict(on_screen(glyph('back', 60), background=(240, 240, 240), tint=(98, 0, 238)))[0], 'MATCH')
        self.assertEqual(self.verdict(on_screen(glyph('back', 60, color=(255, 255, 255, 255)), background=(30, 30, 40)))[0], 'MATCH')
        self.assertEqual(self.verdict(on_screen(glyph('back', 60), padding=40))[0], 'MATCH')  # a node larger than its icon

    def test_a_different_glyph_or_weight_does_not(self):
        for label, candidate in (('mirrored', glyph('back', 60, mirror=True)), ('chevron', glyph('chevron', 60)),
                                 ('plus', glyph('plus', 60)), ('ring', glyph('ring', 60)), ('star', glyph('star', 60)),
                                 ('thin stroke', glyph('back', 60, thin=True))):
            with self.subTest(label=label):
                verdict, metrics, _ = self.verdict(on_screen(candidate))
                self.assertEqual(verdict, 'MISMATCH')
                self.assertLess(metrics['shape_iou'], 0.7)

    def test_a_squashed_icon_fails_on_its_aspect_even_when_its_shape_overlaps(self):
        verdict, metrics, _ = self.verdict(on_screen(glyph('back', 60, stretch=(0.6, 1))))
        self.assertEqual(verdict, 'MISMATCH')
        self.assertGreater(metrics['shape_iou'], 0.72)
        self.assertGreater(metrics['aspect_delta'], 0.2)

    def test_what_cannot_be_compared_is_said_not_guessed(self):
        self.assertIn('no visible ink', self.verdict(Image.new('RGB', (80, 80), (255, 255, 255)))[2])
        self.assertIn('too small', self.verdict(on_screen(glyph('back', 4), padding=1))[2])
        gradient = Image.linear_gradient('L').convert('RGB').resize((80, 80))
        self.assertIn('not uniform', self.verdict(gradient)[2])
        opaque = Image.new('RGBA', (40, 40), (255, 255, 255, 255))
        self.assertIn('reference', ip.measure(opaque, on_screen(glyph('back', 60)))[1])

    def test_a_tolerance_the_check_freezes_changes_the_verdict(self):
        candidate = on_screen(glyph('back', 60, thin=True))
        self.assertEqual(self.verdict(candidate)[0], 'MISMATCH')
        self.assertEqual(self.verdict(candidate, {'shape_iou_min': 0.5})[0], 'MATCH')
        self.assertEqual(self.verdict(on_screen(glyph('back', 60)), {'shape_iou_min': 1.0})[0], 'MISMATCH')

    def test_colour_is_compared_only_when_the_check_asks(self):
        purple = on_screen(glyph('back', 60), tint=(98, 0, 238))
        self.assertEqual(self.verdict(purple)[0], 'MATCH')  # shape only by default: a tint is not a defect
        verdict, metrics, _ = self.verdict(purple, {'color': 'reference'})
        self.assertEqual(verdict, 'MISMATCH')
        self.assertGreater(metrics['color_delta'], 48)
        self.assertEqual(self.verdict(purple, {'color': '#6200EE'})[0], 'MATCH')
        self.assertEqual(self.verdict(on_screen(glyph('back', 60), tint=(0, 0, 0)), {'color': 'reference'})[0], 'MATCH')

    def test_the_verdict_follows_from_the_metrics_and_the_tolerance(self):
        metrics = {'shape_iou': 0.9, 'aspect_delta': 0.05}
        self.assertEqual(ip.verdict(metrics), 'MATCH')
        self.assertEqual(ip.verdict({**metrics, 'shape_iou': 0.5}), 'MISMATCH')
        self.assertEqual(ip.verdict({**metrics, 'aspect_delta': 0.5}), 'MISMATCH')
        self.assertEqual(ip.verdict({**metrics, 'color_delta': 90.0}, {'color': 'reference'}), 'MISMATCH')


class NodeEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        glyph('back', 72).save(self.root / 'reference.png')
        self.check = {'id': 'back-arrow', 'node_id': 'node:screen.back', 'target': {'selector': {'resource-id': 'back'}}}

    def screen(self, icon, at=(60, 80)):
        canvas = Image.new('RGB', (360, 640), (250, 250, 250))
        canvas.paste(icon, at, icon)
        canvas.save(self.root / 'shot.jpeg', quality=80)
        x, y = at
        view = ('<hierarchy><node class="Image" resource-id="back" bounds="[%d,%d][%d,%d]"/>'
                '<node class="Text" text="Title" bounds="[120,80][300,130]"/></hierarchy>') % (x - 6, y - 6, x + icon.width + 6, y + icon.height + 6)
        return view

    def evaluate(self, view, check=None):
        return ip.evaluate(check or self.check, self.root / 'reference.png', self.root / 'shot.jpeg', view)

    def test_a_matching_node_is_judged_from_the_crop_of_its_bounds(self):
        row, crop = self.evaluate(self.screen(glyph('back', 60, color=(40, 40, 40, 255))))
        self.assertEqual((row['status'], row['node']['bounds']), ('MATCH', [54, 74, 126, 146]))
        self.assertEqual(crop.size, (72, 72))
        self.assertEqual(ip.verdict(row['metrics'], row['tolerance']), row['status'])
        self.assertEqual(self.evaluate(self.screen(glyph('back', 60, color=(40, 40, 40, 255))))[0], row)  # deterministic

    def test_a_wrong_icon_in_the_right_place_is_a_mismatch(self):
        row, _ = self.evaluate(self.screen(glyph('star', 60, color=(40, 40, 40, 255))))
        self.assertEqual(row['status'], 'MISMATCH')

    def test_a_missing_or_ambiguous_node_is_incomparable_not_a_pass(self):
        view = self.screen(glyph('back', 60))
        row, crop = self.evaluate(view, {**self.check, 'target': {'selector': {'resource-id': 'absent'}}})
        self.assertEqual((row['status'], crop), ('INCOMPARABLE', None))
        self.assertIn('0 nodes', row['reason'])
        doubled = view.replace('</hierarchy>', '<node class="Image" resource-id="back" bounds="[0,0][50,50]"/></hierarchy>')
        self.assertIn('2 nodes', self.evaluate(doubled)[0]['reason'])
        outside = view.replace('[54,74][126,146]', '[1000,1000][1100,1100]')
        self.assertEqual(self.evaluate(outside)[0]['status'], 'INCOMPARABLE')


@unittest.skipUnless(shutil.which('rsvg-convert'), 'rsvg-convert is not installed')
class VectorRenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def index(self, name, xml, qualifier='default'):
        path = self.root / 'app/src/main/res/drawable' / (name + '.xml')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(xml)
        row = {'ref': '@drawable/' + name, 'kind': 'drawable', 'qualifier': qualifier, 'path': path.relative_to(self.root).as_posix(),
               'sha256': file_ref(path)['sha256']}
        return {'androidRoot': str(self.root), 'resources': [row]}

    def test_a_vector_drawable_renders_its_shape_at_four_pixels_per_dp(self):
        xml = ('<vector xmlns:android="http://schemas.android.com/apk/res/android" android:width="24dp" android:height="24dp" '
               'android:viewportWidth="24" android:viewportHeight="24"><path android:fillColor="@color/ink" '
               'android:pathData="M4,12 L20,4 L20,20 Z"/><group android:translateX="1"><path android:strokeColor="#FF000000" '
               'android:strokeWidth="2" android:pathData="M2,22 L22,22"/></group></vector>')
        out = self.root / 'out'
        out.mkdir()
        document = rr.render(self.index('ic_play', xml), '@drawable/ic_play', 'base', out)
        self.assertEqual((document['mode'], document['width'], document['height'], document['alpha']), ('mask', 96, 96, True))
        self.assertEqual(document['renderer']['name'], 'rsvg-convert')
        with Image.open(out / 'reference.png') as rendered:
            alpha = rendered.getchannel('A')
            self.assertEqual(alpha.getpixel((60, 48)), 255)   # inside the triangle
            self.assertEqual(alpha.getpixel((8, 8)), 0)       # outside every path
            self.assertGreater(alpha.getpixel((60, 88)), 128)  # the stroke, moved by its group
        self.assertEqual(json.loads((out / 'reference.json').read_text())['png_ref'], file_ref(out / 'reference.png'))
        again = self.root / 'again'
        again.mkdir()
        self.assertEqual(rr.render(self.index('ic_play', xml), '@drawable/ic_play', 'default', again)['png_ref']['sha256'],
                         document['png_ref']['sha256'])

    def test_a_gradient_filled_path_is_ink_like_any_other(self):
        gradient = ('<vector xmlns:android="http://schemas.android.com/apk/res/android" xmlns:aapt="http://schemas.android.com/aapt" '
                    'android:width="24dp" android:height="24dp" android:viewportWidth="24" android:viewportHeight="24">'
                    '<path android:pathData="M4,4h16v16h-16z"><aapt:attr name="android:fillColor">'
                    '<gradient android:startColor="#FF0000" android:endColor="#0000FF" android:type="linear"/></aapt:attr></path></vector>')
        import xml.etree.ElementTree as ET
        svg, _ = rr.vector_svg(ET.fromstring(gradient))
        self.assertIn('fill="#000"', svg)
        plain = gradient.replace('<aapt:attr name="android:fillColor"><gradient android:startColor="#FF0000" android:endColor="#0000FF" android:type="linear"/></aapt:attr>', '')
        self.assertIn('fill="none"', rr.vector_svg(ET.fromstring(plain))[0])  # no colour at all stays transparent

    def test_a_clip_path_clips_the_siblings_after_it(self):
        xml = ('<vector xmlns:android="http://schemas.android.com/apk/res/android" android:width="10dp" android:height="10dp" '
               'android:viewportWidth="10" android:viewportHeight="10"><clip-path android:pathData="M0,0 L5,0 L5,10 L0,10 Z"/>'
               '<path android:fillColor="#FF000000" android:pathData="M0,0 L10,0 L10,10 L0,10 Z"/></vector>')
        out = self.root / 'out'
        out.mkdir()
        rr.render(self.index('ic_half', xml), '@drawable/ic_half', 'base', out)
        with Image.open(out / 'reference.png') as rendered:
            self.assertEqual((rendered.getchannel('A').getpixel((10, 20)), rendered.getchannel('A').getpixel((30, 20))), (255, 0))


class ReferenceRenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.out = self.root / 'out'
        self.out.mkdir()

    def asset(self, relative, data, qualifier='xxhdpi', ref='@drawable/ic_back'):
        path = self.root / 'app/src/main/res' / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data) if isinstance(data, bytes) else path.write_text(data)
        row = {'ref': ref, 'kind': ref[1:].split('/')[0], 'qualifier': qualifier, 'path': path.relative_to(self.root).as_posix(),
               'sha256': file_ref(path)['sha256']}
        return {'androidRoot': str(self.root), 'resources': [row]}

    def test_a_raster_asset_is_decoded_to_a_png_of_the_same_size(self):
        data = io.BytesIO()
        glyph('back', 72).save(data, format='WEBP', lossless=True)
        index = self.asset('drawable-xxhdpi/ic_back.webp', data.getvalue())
        document = rr.render(index, '@drawable/ic_back', 'xxhdpi', self.out)
        self.assertEqual((document['mode'], document['width'], document['height'], document['alpha'], document['qualifier']),
                         ('color', 72, 72, True, 'xxhdpi'))
        self.assertEqual(document['source_ref'], {'path': str((self.root / 'app/src/main/res/drawable-xxhdpi/ic_back.webp').resolve()),
                                                  'sha256': index['resources'][0]['sha256']})
        with Image.open(self.out / 'reference.png') as png, Image.open(io.BytesIO(data.getvalue())) as source:
            self.assertEqual(png.convert('RGBA').tobytes(), source.convert('RGBA').tobytes())

    def test_what_has_no_single_picture_is_refused(self):
        for relative, data, reason in (('drawable/ic_state.xml', '<selector xmlns:android="http://schemas.android.com/apk/res/android"/>', 'selector'),
                                       ('raw/spin.json', '{}', 'raster images and vector drawables only')):
            with self.subTest(relative=relative), self.assertRaisesRegex(rr.RenderError, reason):
                rr.render(self.asset(relative, data, 'base', '@drawable/ic_state'), '@drawable/ic_state', 'base', self.out)

    def test_the_file_must_be_the_one_that_was_indexed(self):
        index = self.asset('drawable-xxhdpi/ic_back.png', io.BytesIO(b'').getvalue() or b'not an image')
        (self.root / 'app/src/main/res/drawable-xxhdpi/ic_back.png').write_bytes(b'changed afterwards')
        with self.assertRaisesRegex(rr.RenderError, 'changed after it was indexed'):
            rr.render(index, '@drawable/ic_back', 'xxhdpi', self.out)
        with self.assertRaisesRegex(rr.RenderError, 'no single declaration'):
            rr.render(index, '@drawable/ic_back', 'night', self.out)
        with self.assertRaisesRegex(rr.RenderError, 'no single declaration'):
            rr.render(index, '@drawable/absent', 'xxhdpi', self.out)


if __name__ == '__main__':
    unittest.main()
