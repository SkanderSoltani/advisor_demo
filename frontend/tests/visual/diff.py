"""Pixel diff of parity screenshots: python -m tests.visual.diff <name> [widths...]

Prints % of pixels differing (per-channel delta > 24) and writes .screens/<name>-<w>-diff.png
(differences in magenta over a faded React screenshot). Heights are padded to the taller image.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageChops

OUT = Path(__file__).resolve().parents[2] / ".screens"


def diff(name: str, w: int) -> float:
    a = Image.open(OUT / f"{name}-{w}-react.png").convert("RGB")
    b = Image.open(OUT / f"{name}-{w}-dash.png").convert("RGB")
    h = max(a.height, b.height)
    pa, pb = Image.new("RGB", (w, h), "white"), Image.new("RGB", (w, h), "white")
    pa.paste(a, (0, 0))
    pb.paste(b, (0, 0))
    d = ImageChops.difference(pa, pb).convert("L").point(lambda v: 255 if v > 24 else 0)
    changed = sum(1 for v in d.getdata() if v)
    overlay = Image.blend(pa, Image.new("RGB", pa.size, "white"), 0.7)
    overlay.paste(Image.new("RGB", pa.size, (255, 0, 200)), mask=d)
    overlay.save(OUT / f"{name}-{w}-diff.png")
    return 100 * changed / (w * h)


if __name__ == "__main__":
    name, widths = sys.argv[1], [int(x) for x in sys.argv[2:]] or [1440, 1024]
    for w in widths:
        print(f"{name} @ {w}px: {diff(name, w):.2f}% pixels differ")
