"""Draw the ShambaSense app icons (PNG for the installable app and Android, SVG favicon).

    python scripts/make_icons.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

LEAF = (31, 94, 59)       # napier green
MAIZE = (242, 194, 48)    # maize yellow
SOIL = (43, 33, 24)
OUT = Path(__file__).resolve().parent.parent / "web" / "icons"


def draw(size: int, maskable: bool = False) -> Image.Image:
    s = size * 4                                       # draw large, then downsample for smooth edges
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if maskable:
        d.rectangle([0, 0, s, s], fill=LEAF)
        k = 0.72                                       # keep the mark inside the safe zone
    else:
        d.rounded_rectangle([0, 0, s, s], radius=int(s * 0.22), fill=LEAF)
        k = 0.86
    c = s / 2

    def p(x, y):                                       # coordinates on a 100-unit grid, centred
        return (c + (x - 50) * s / 100 * k, c + (y - 50) * s / 100 * k)

    import math

    def leaf(base, tip, width):
        (bx, by), (tx, ty) = base, tip
        dx, dy = tx - bx, ty - by
        length = math.hypot(dx, dy)
        nx, ny = -dy / length, dx / length
        left, right = [], []
        for i in range(41):
            t = i / 40
            w = width * math.sin(math.pi * t) ** 0.8
            cx, cy = bx + dx * t, by + dy * t
            left.append(p(cx + nx * w, cy + ny * w))
            right.append(p(cx - nx * w, cy - ny * w))
        d.polygon(left + right[::-1], fill=MAIZE)

    # soil furrow, stem and two leaves
    d.rounded_rectangle([*p(24, 72), *p(76, 79)], radius=int(s * 0.03 * k), fill=MAIZE)
    stem_w = int(s * 0.05 * k)
    d.line([p(50, 73), p(50, 43)], fill=MAIZE, width=stem_w)
    d.ellipse([*p(50 - 2.5, 43 - 2.5), *p(50 + 2.5, 43 + 2.5)], fill=MAIZE)
    leaf((50, 52), (22, 34), 8.5)
    leaf((50, 45), (80, 24), 10)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        draw(size).save(OUT / f"icon-{size}.png")
    draw(512, maskable=True).save(OUT / "icon-maskable-512.png")
    draw(180, maskable=True).convert("RGB").save(OUT / "apple-touch-icon.png")
    draw(1024, maskable=True).save(OUT / "icon-foreground-1024.png")
    svg = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><rect width='100' height='100' rx='22' "
           "fill='#1F5E3B'/><g fill='#F2C230' transform='translate(7 7) scale(0.86)'>"
           "<rect x='24' y='72' width='52' height='7' rx='3'/><rect x='47.5' y='43' width='5' height='30' rx='2.5'/>"
           "<path d='M50 52 C 42 52 27 46 22 34 C 33 34 45 41 50 52 Z'/>"
           "<path d='M50 45 C 57 33 70 26 80 24 C 79 36 64 46 50 45 Z'/></g></svg>")
    (OUT / "icon.svg").write_text(svg)
    print("icons written to", OUT)


if __name__ == "__main__":
    main()
