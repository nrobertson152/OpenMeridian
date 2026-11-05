#!/usr/bin/env python3
"""Draw the OpenMeridian application icon (development tool, needs Pillow).

Same family as the OpenSchematix mark: a rounded square with a faint grid, a white line and gold ports,
here drawn as an "M". Placeholder artwork until a Director-supplied logo replaces it.
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "openmeridian" / "resources"
S = 1024


def base():
    grad = Image.new("RGBA", (S, S))
    px = grad.load()
    for y in range(S):
        for x in range(S):
            t = (x + y) / (2 * S)
            px[x, y] = (int(20 - 8 * t), int(112 - 44 * t), int(150 - 40 * t), 255)
    d = ImageDraw.Draw(grad)
    for i in range(0, S, 64):
        d.line([(i, 0), (i, S)], fill=(255, 255, 255, 24), width=2)
        d.line([(0, i), (S, i)], fill=(255, 255, 255, 24), width=2)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([40, 40, S - 40, S - 40], 190, fill=255)
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.paste(grad, (0, 0), mask)
    return out


def main():
    im = base()
    d = ImageDraw.Draw(im)
    w = 90
    white = (255, 255, 255, 255)
    # an M drawn as one line between two ports, with a third at its valley: a meridian over the family's grid
    pts = [(250, 790), (250, 280), (512, 620), (774, 280), (774, 790)]
    d.line(pts, fill=white, width=w, joint="curve")
    for p in pts[1:4:2]:
        d.ellipse([p[0] - w / 2, p[1] - w / 2, p[0] + w / 2, p[1] + w / 2], fill=white)
    gold, navy = (246, 178, 40, 255), (12, 66, 92, 255)
    for x, y in ((250, 790), (774, 790), (512, 620)):
        d.ellipse([x - 82, y - 82, x + 82, y + 82], fill=gold)
        d.ellipse([x - 38, y - 38, x + 38, y + 38], fill=navy)
    im = im.resize((512, 512), Image.LANCZOS)
    OUT.mkdir(exist_ok=True)
    for size in (512, 256, 64):
        im.resize((size, size), Image.LANCZOS).save(OUT / f"openmeridian-{size}.png")
    im.save(OUT / "openmeridian.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


if __name__ == "__main__":
    main()
