"""Draws the installer's Neon Pulsar artwork: wizard banners and the app icon.

Run from the repo root:  python installer/make_art.py
Writes installer/art/*.bmp and installer/art/stellarite-node.ico.
Needs Pillow (pip install pillow). The output is committed, so the build
doesn't need to run this.
"""
import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "art")

BLACK = (0, 0, 0)
CRIMSON = (220, 20, 60)      # #DC143C, the app's accent
AMBER = (255, 176, 0)        # highlights
DIM = (90, 8, 24)            # low crimson for grid and scanlines


def font(size):
    for name in ("Orbitron-Bold.ttf", "ShareTechMono-Regular.ttf",
                 "DejaVuSansMono-Bold.ttf", "consola.ttf"):
        for base in (os.path.join(HERE, "fonts"), "/usr/share/fonts/truetype/dejavu",
                     "C:/Windows/Fonts"):
            path = os.path.join(base, name)
            if os.path.exists(path):
                return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def pulsar(draw, cx, cy, r, rings=4, width=1):
    """The pulsar mark: a bright core, two beams and pulsing rings."""
    for i in range(rings, 0, -1):
        rr = r * i / rings
        shade = tuple(int(c * (0.35 + 0.65 * (rings - i + 1) / rings)) for c in CRIMSON)
        draw.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=shade, width=width)
    core = max(2, r * 0.16)
    draw.ellipse([cx - core, cy - core, cx + core, cy + core], fill=AMBER)
    # beams, tilted like a pulsar's magnetic axis
    a = math.radians(-62)
    for s in (1, -1):
        x2 = cx + s * math.cos(a) * r * 1.35
        y2 = cy + s * math.sin(a) * r * 1.35
        draw.line([cx, cy, x2, y2], fill=AMBER, width=max(1, width))


def brackets(draw, x0, y0, x1, y1, n, color, w=2):
    """HUD corner brackets."""
    for (x, y, dx, dy) in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        draw.line([x, y, x + dx * n, y], fill=color, width=w)
        draw.line([x, y, x, y + dy * n], fill=color, width=w)


def scanlines(img, every=3, strength=0.55):
    px = img.load()
    for y in range(0, img.height, every):
        for x in range(img.width):
            r, g, b = px[x, y]
            px[x, y] = (int(r * strength), int(g * strength), int(b * strength))


def stars(draw, w, h, n, seed):
    rnd = random.Random(seed)
    for _ in range(n):
        x, y = rnd.randrange(w), rnd.randrange(h)
        v = rnd.randrange(60, 200)
        draw.point((x, y), fill=(v, v // 6, v // 4) if rnd.random() < 0.5 else (v, v, v))


def bloom(img, radius):
    blur = img.filter(ImageFilter.GaussianBlur(radius))
    return Image.eval(Image.merge("RGB", [
        Image.eval(Image.blend(a, b, 0.5), lambda v: min(255, v * 2))
        for a, b in zip(img.split(), blur.split())]), lambda v: v)


def wizard_image(scale):
    """The tall banner on the Welcome and Finished pages (164x314 at 100%)."""
    w, h = 164 * scale, 314 * scale
    img = Image.new("RGB", (w, h), BLACK)
    d = ImageDraw.Draw(img)
    stars(d, w, h, 140 * scale, 7)
    # faint perspective grid at the bottom
    for i in range(0, 12):
        y = h - int((i ** 1.6) * 2.2 * scale) - 2
        if y > h * 0.79:
            d.line([0, y, w, y], fill=DIM, width=1)
    for i in range(-6, 7):
        d.line([w / 2 + i * 6 * scale, h * 0.78, w / 2 + i * 40 * scale, h], fill=DIM, width=1)
    pulsar(d, w / 2, h * 0.36, 52 * scale, rings=5, width=max(1, scale))
    img = bloom(img, 4 * scale)
    d = ImageDraw.Draw(img)
    pulsar(d, w / 2, h * 0.36, 52 * scale, rings=5, width=max(1, scale))
    f1, f2 = font(15 * scale), font(9 * scale)
    for text, f, y, col in (("STELLARITE", f1, 0.60, CRIMSON), ("NODE", f1, 0.66, AMBER),
                            ("PLSR // NBLT", f2, 0.73, (200, 200, 200))):
        tw = d.textlength(text, font=f)
        d.text(((w - tw) / 2, h * y), text, font=f, fill=col)
    brackets(d, 6 * scale, 6 * scale, w - 7 * scale, h - 7 * scale, 16 * scale, CRIMSON, max(1, scale))
    scanlines(img, every=3 * scale if scale > 1 else 3, strength=0.7)
    return img


def small_image(scale):
    """The square mark in the top-right of the inner pages (55x55 at 100%)."""
    s = 55 * scale
    img = Image.new("RGB", (s, s), BLACK)
    d = ImageDraw.Draw(img)
    pulsar(d, s / 2, s / 2, 19 * scale, rings=3, width=max(1, scale))
    img = bloom(img, 2 * scale)
    d = ImageDraw.Draw(img)
    pulsar(d, s / 2, s / 2, 19 * scale, rings=3, width=max(1, scale))
    brackets(d, 1, 1, s - 2, s - 2, 9 * scale, CRIMSON, max(1, scale))
    return img


def icon():
    big = Image.new("RGBA", (256, 256), (0, 0, 0, 255))
    d = ImageDraw.Draw(big)
    pulsar(d, 128, 128, 92, rings=4, width=9)
    rgb = bloom(big.convert("RGB"), 8)
    d = ImageDraw.Draw(rgb)
    pulsar(d, 128, 128, 92, rings=4, width=9)
    brackets(d, 10, 10, 245, 245, 46, CRIMSON, 10)
    return rgb


def main():
    os.makedirs(OUT, exist_ok=True)
    wizard_image(1).save(os.path.join(OUT, "wizard-100.bmp"))
    wizard_image(2).save(os.path.join(OUT, "wizard-200.bmp"))
    small_image(1).save(os.path.join(OUT, "small-100.bmp"))
    small_image(2).save(os.path.join(OUT, "small-200.bmp"))
    icon().save(os.path.join(OUT, "stellarite-node.ico"),
                sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", sorted(os.listdir(OUT)))


if __name__ == "__main__":
    main()
