"""Generate the 1200x630 Open Graph share image (docs/assets/og-image.png).

Run:  .venv/bin/python tools/make_og_image.py   (from the repo root)
No external assets — draws everything with Pillow using system fonts.
"""
from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
OUT = os.path.join(os.path.dirname(__file__), "..", "docs", "assets", "og-image.png")

GOLD = (255, 213, 74)
BLUE = (90, 155, 255)
INK = (232, 232, 234)
MUTE = (150, 152, 160)

# --- background: vertical gradient (deep navy -> near black) ----------------
img = Image.new("RGB", (W, H), (11, 13, 20))
px = img.load()
top = (18, 22, 38)
bot = (8, 9, 14)
for y in range(H):
    t = y / H
    px_row = tuple(int(top[i] * (1 - t) + bot[i] * t) for i in range(3))
    for x in range(W):
        px[x, y] = px_row

draw = ImageDraw.Draw(img)


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


HELV = "/System/Library/Fonts/Helvetica.ttc"
SF = "/System/Library/Fonts/SFNS.ttf"
try:
    f_title = font(SF, 82)
    f_sub = font(SF, 38)
    f_small = font(SF, 28)
except Exception:
    f_title = font(HELV, 82)
    f_sub = font(HELV, 38)
    f_small = font(HELV, 28)

# --- decorative price line (rising, jagged) --------------------------------
pts = []
base_y = 470
for i in range(0, W + 1, 24):
    prog = i / W
    noise = math.sin(i * 0.03) * 34 + math.sin(i * 0.011) * 60
    y = base_y - prog * 210 + noise
    pts.append((i, y))
draw.line(pts, fill=(60, 70, 95), width=3)

# moon markers along the line (gold = full/top, blue = new/bottom)
for idx, (x, y) in enumerate(pts):
    if idx % 8 == 3:
        draw.ellipse([x - 9, y - 9, x + 9, y + 9], fill=GOLD)
    elif idx % 8 == 7:
        draw.ellipse([x - 9, y - 9, x + 9, y + 9], outline=BLUE, width=4)

# --- big full moon, top-right ----------------------------------------------
cx, cy, r = 1010, 150, 92
for gr in range(28, 0, -1):
    a = int(6 * (gr / 28))
    draw.ellipse([cx - r - gr, cy - r - gr, cx + r + gr, cy + r + gr],
                 fill=(GOLD[0], GOLD[1], GOLD[2]))
draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 226, 130))
# subtle craters
for (dx, dy, rr) in [(-30, -20, 16), (24, 10, 12), (-8, 34, 10), (34, -34, 8)]:
    draw.ellipse([cx + dx - rr, cy + dy - rr, cx + dx + rr, cy + dy + rr],
                 fill=(240, 208, 108))

# --- text -------------------------------------------------------------------
draw.text((72, 118), "Bitcoin", font=f_title, fill=INK)
draw.text((72, 210), "vs the ", font=f_title, fill=INK)
w_vs = draw.textlength("vs the ", font=f_title)
draw.text((72 + w_vs, 210), "Moon", font=f_title, fill=GOLD)

draw.text((74, 322), "Do full moons mark tops and new moons mark",
          font=f_sub, fill=MUTE)
draw.text((74, 368), "bottoms? Measuring the lag — and predicting it.",
          font=f_sub, fill=MUTE)

# footer strip
draw.line([(72, 560), (1128, 560)], fill=(40, 44, 58), width=2)
draw.text((72, 578), "interactive lunar-cycle analysis for Bitcoin",
          font=f_small, fill=MUTE)
draw.text((absx := 1128 - int(draw.textlength("bitcoinvsthemoon.com", font=f_small)), 578),
          "bitcoinvsthemoon.com", font=f_small, fill=GOLD)

img.save(OUT, "PNG", optimize=True)
print(f"wrote {OUT} ({os.path.getsize(OUT)//1024} KB)")
