#!/usr/bin/env python3
"""Generate deterministic evidence for mobile UI screenshot alignment.

The score is evidence for an agent reviewer. It should not be the sole basis for
code changes.
"""

from __future__ import annotations

import argparse
import json
import math
import warnings
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True, help="Android/reference screenshot")
    parser.add_argument("--candidate", required=True, help="KMP/candidate screenshot")
    parser.add_argument("--out", required=True, help="Output report directory")
    parser.add_argument("--profile", default="mobile-app", choices=["mobile-app"])
    parser.add_argument("--ignore-top-ratio", type=float, default=0.045)
    parser.add_argument("--compare-width", type=int, default=390)
    return parser.parse_args()


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def load_rgb(path: Path):
    from PIL import Image, ImageOps

    image = Image.open(path)
    image = ImageOps.exif_transpose(image)
    if image.mode in ("RGBA", "LA"):
        background = Image.new("RGB", image.size, "white")
        background.paste(image, mask=image.getchannel("A"))
        return background
    return image.convert("RGB")


def resize_to_width(image, width: int):
    from PIL import Image

    if image.width == width:
        return image.copy()
    height = max(1, round(image.height * width / image.width))
    return image.resize((width, height), Image.Resampling.LANCZOS)


def crop_common(a, b, ignore_top_px: int):
    width = min(a.width, b.width)
    height = min(a.height, b.height)
    top = min(ignore_top_px, max(0, height - 1))
    return a.crop((0, top, width, height)), b.crop((0, top, width, height))


def downsample_pair(a, b, max_width: int = 320):
    from PIL import Image

    if a.width <= max_width:
        return a, b
    height = max(1, round(a.height * max_width / a.width))
    size = (max_width, height)
    return a.resize(size, Image.Resampling.BILINEAR), b.resize(size, Image.Resampling.BILINEAR)


def global_ssim_gray(a, b) -> float:
    a, b = downsample_pair(a.convert("L"), b.convert("L"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        data_a = list(a.getdata())
        data_b = list(b.getdata())
    n = len(data_a)
    if n < 2:
        return 0.0
    mean_a = sum(data_a) / n
    mean_b = sum(data_b) / n
    var_a = sum((x - mean_a) ** 2 for x in data_a) / (n - 1)
    var_b = sum((x - mean_b) ** 2 for x in data_b) / (n - 1)
    cov = sum((data_a[i] - mean_a) * (data_b[i] - mean_b) for i in range(n)) / (n - 1)
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2
    denom = (mean_a * mean_a + mean_b * mean_b + c1) * (var_a + var_b + c2)
    if denom == 0:
        return 1.0 if data_a == data_b else 0.0
    return ((2 * mean_a * mean_b + c1) * (2 * cov + c2)) / denom


def mean_abs_error(a, b) -> float:
    from PIL import ImageChops

    a, b = downsample_pair(a.convert("RGB"), b.convert("RGB"))
    diff = ImageChops.difference(a, b)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        pixels = list(diff.getdata())
    if not pixels:
        return 0.0
    return sum(sum(pixel) for pixel in pixels) / (len(pixels) * 3)


def average_rgb(image) -> tuple[int, int, int]:
    from PIL import Image

    return image.resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))


def rgb_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def make_heatmap(reference, candidate, ignore_top_px: int):
    from PIL import Image, ImageChops, ImageDraw, ImageEnhance

    width = min(reference.width, candidate.width)
    height = min(reference.height, candidate.height)
    ref = reference.crop((0, 0, width, height))
    cand = candidate.crop((0, 0, width, height))
    diff = ImageChops.difference(ref, cand).convert("L")
    if ignore_top_px > 0:
        draw = ImageDraw.Draw(diff)
        draw.rectangle((0, 0, width, min(ignore_top_px, height)), fill=0)
    diff = ImageEnhance.Contrast(diff).enhance(3.0)
    base = Image.blend(ref, cand, 0.5).convert("RGBA")
    overlay = Image.new("RGBA", (width, height), (255, 0, 0, 0))
    alpha = diff.point(lambda value: min(210, int(value * 1.2)))
    overlay.putalpha(alpha)
    return Image.alpha_composite(base, overlay).convert("RGB")


def make_side_by_side(reference, candidate, heatmap):
    from PIL import Image, ImageDraw, ImageFont

    thumb_w = 260
    max_h = 560
    canvases = []
    for image in (reference, candidate, heatmap):
        thumb = image.copy()
        thumb.thumbnail((thumb_w, max_h), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (thumb_w, max_h), "white")
        canvas.paste(thumb, ((thumb_w - thumb.width) // 2, 0))
        canvases.append(canvas)
    gutter = 18
    header = 34
    out = Image.new("RGB", (thumb_w * 3 + gutter * 4, max_h + header), (245, 245, 245))
    draw = ImageDraw.Draw(out)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 16)
    except Exception:
        font = ImageFont.load_default()
    for index, label in enumerate(("reference", "candidate", "heatmap")):
        x = gutter + index * (thumb_w + gutter)
        draw.text((x, 10), label, fill=(20, 20, 20), font=font)
        out.paste(canvases[index], (x, header))
    return out


def score_from_metrics(ssim: float, edge_ssim: float, color_dist: float, mae: float, height_delta_ratio: float) -> float:
    ssim_score = clamp((ssim + 1) * 50)
    edge_score = clamp((edge_ssim + 1) * 50)
    color_score = clamp(100 - color_dist * 1.1)
    mae_score = clamp(100 - mae * 1.25)
    height_score = clamp(100 - height_delta_ratio * 180)
    return round(ssim_score * 0.34 + edge_score * 0.22 + color_score * 0.16 + mae_score * 0.16 + height_score * 0.12, 1)


def main() -> int:
    args = parse_args()
    reference_path = Path(args.reference).expanduser().resolve()
    candidate_path = Path(args.candidate).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        from PIL import ImageFilter
    except Exception as exc:  # pragma: no cover - environment dependent
        (out_dir / "score.json").write_text(
            json.dumps({"status": "BLOCKED", "reason": f"Pillow is required: {exc}"}, indent=2),
            encoding="utf-8",
        )
        return 2

    if not reference_path.exists() or not candidate_path.exists():
        (out_dir / "score.json").write_text(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "reason": "reference or candidate screenshot is missing",
                    "reference": str(reference_path),
                    "candidate": str(candidate_path),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return 2

    reference = load_rgb(reference_path)
    candidate = load_rgb(candidate_path)
    normalized_reference = resize_to_width(reference, args.compare_width)
    normalized_candidate = resize_to_width(candidate, args.compare_width)
    ignore_top_px = round(args.compare_width * args.ignore_top_ratio)
    ref_cmp, cand_cmp = crop_common(normalized_reference, normalized_candidate, ignore_top_px)

    ssim = global_ssim_gray(ref_cmp, cand_cmp)
    edge_ssim = global_ssim_gray(ref_cmp.filter(ImageFilter.FIND_EDGES), cand_cmp.filter(ImageFilter.FIND_EDGES))
    mae = mean_abs_error(ref_cmp, cand_cmp)
    color_dist = rgb_distance(average_rgb(ref_cmp), average_rgb(cand_cmp))
    height_delta_ratio = abs(normalized_reference.height - normalized_candidate.height) / max(1, normalized_reference.height)
    final_score = score_from_metrics(ssim, edge_ssim, color_dist, mae, height_delta_ratio)

    heatmap = make_heatmap(normalized_reference, normalized_candidate, ignore_top_px)
    heatmap.save(out_dir / "heatmap.png")
    make_side_by_side(normalized_reference, normalized_candidate, heatmap).save(out_dir / "side-by-side.png")
    normalized_reference.save(out_dir / "reference-normalized.png")
    normalized_candidate.save(out_dir / "candidate-normalized.png")

    score = {
        "status": "COMPLETE",
        "reference": str(reference_path),
        "candidate": str(candidate_path),
        "reference_size": list(reference.size),
        "candidate_size": list(candidate.size),
        "normalized_size": {
            "reference": list(normalized_reference.size),
            "candidate": list(normalized_candidate.size),
        },
        "ignored_top_px": ignore_top_px,
        "metrics": {
            "global_ssim": ssim,
            "edge_ssim": edge_ssim,
            "mean_abs_error": mae,
            "average_color_distance": color_dist,
            "height_delta_ratio": height_delta_ratio,
            "final_baseline_score": final_score,
        },
        "artifacts": {
            "heatmap": str(out_dir / "heatmap.png"),
            "side_by_side": str(out_dir / "side-by-side.png"),
            "reference_normalized": str(out_dir / "reference-normalized.png"),
            "candidate_normalized": str(out_dir / "candidate-normalized.png"),
        },
        "interpretation_note": "Use these metrics as evidence only; select final UI issues by semantic region inspection.",
    }
    (out_dir / "score.json").write_text(json.dumps(score, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit("Use the managed lean_worker.py entry point; this is a private library.")
