"""Render the favicon to the raster sizes browsers still ask for.

    python makeicon.py

`site/favicon.svg` is the artwork and this draws the same rectangles from the
same numbers rather than converting it: the mark is five rectangles and a
rounded tile, and a converter would be a dependency carried for a file that
changes once a year.

WHY IT IS SHARP
---------------
The geometry sits on a four-unit grid in a 64-unit box, so at 16 pixels every
edge falls exactly on a pixel boundary and at 32 and 48 it still does. That is
most of the sharpness. The rest is drawing at 8x and downsampling with
Lanczos, which is what a browser does with the SVG, so the raster and the
vector agree.

Sizes, and why each exists:

    16, 32   what a tab strip and a bookmark bar draw
    48       Windows taskbar and the Chrome shortcut icon
    64       a 32-pixel slot on a 2x display
    180      apple-touch-icon, for a phone home screen

Both files are committed. Run this again only if the mark changes.
"""
import io
import struct
from pathlib import Path

from PIL import Image, ImageDraw

SITE = Path(__file__).resolve().parent / "site"

# The dark theme's own ground and the two sides' colours, so the mark is drawn
# in a palette the site already speaks in.
INK = (23, 20, 31, 255)              # --bg, dark
PURPLE = (139, 92, 246, 255)         # --ct, dark
ORANGE = (224, 164, 88, 255)         # --t, dark

BOX, RADIUS = 64, 14
ARMS = [(28, 8, 8, 16), (28, 40, 8, 16),      # up, down
        (8, 28, 16, 8), (40, 28, 16, 8)]      # left, right
DOT = (28, 28, 8, 8)
ICO_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64)]


def draw(px: int) -> Image.Image:
    """One icon at `px`: the tile smoothed, the mark placed on whole pixels.

    Two passes, because the two halves of this drawing want opposite things.
    The tile's corners are curves and have to be antialiased, so they are
    drawn at 8x and brought down. The arms are axis-aligned rectangles that
    already land on pixel boundaries, and antialiasing them is pure loss: a
    downsample spreads each edge across the neighbouring pixel and a 16-pixel
    icon comes back with twenty-eight half-tone pixels and no crisp edge
    anywhere. So they are drawn last, straight onto the finished tile, at
    integer coordinates.
    """
    s = px * 8
    k = s / BOX
    tile = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(tile).rounded_rectangle(
        [0, 0, s - 1, s - 1], radius=RADIUS * k, fill=INK)
    im = tile.resize((px, px), Image.LANCZOS)

    d = ImageDraw.Draw(im)
    u = px / BOX                      # pixels per viewBox unit
    for (x, y, w, h), col in [(a, PURPLE) for a in ARMS] + [(DOT, ORANGE)]:
        d.rectangle([round(x * u), round(y * u),
                     round((x + w) * u) - 1, round((y + h) * u) - 1], fill=col)
    return im


def main() -> int:
    ico = SITE / "favicon.ico"
    # EVERY FRAME DRAWN AT ITS OWN SIZE.
    #
    # Handing Pillow one big image and a list of sizes makes it produce the
    # small frames by resizing the big one, which undoes the whole point: the
    # 16-pixel frame comes back as a blur of a 64-pixel drawing. `draw` is
    # cheap; call it once per size and hand the frames over.
    # Written by hand, because Pillow's ICO writer takes one image and a list
    # of sizes and makes the small frames by resizing the big one -- which is
    # exactly the blur `draw` exists to avoid. Passing `append_images`
    # alongside `sizes` silently keeps only the first frame. The container is
    # a six-byte header, a sixteen-byte entry per frame and then the PNGs, so
    # writing it is shorter than working around the library.
    frames = [(w, draw(w)) for w, _ in ICO_SIZES]
    blobs = []
    for _w, im in frames:
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        blobs.append(buf.getvalue())
    head = struct.pack("<HHH", 0, 1, len(frames))
    offset = len(head) + 16 * len(frames)
    entries, body = [], []
    for (w, _im), blob in zip(frames, blobs):
        entries.append(struct.pack("<BBBBHHII", w % 256, w % 256, 0, 0, 1, 32,
                                   len(blob), offset))
        body.append(blob)
        offset += len(blob)
    ico.write_bytes(head + b"".join(entries) + b"".join(body))
    draw(180).save(SITE / "apple-touch-icon.png")
    # 192 and 512 are what a web app manifest asks for: Android draws the
    # home screen icon from the first and the splash from the second. Drawn
    # at size like every other frame here rather than resampled down from
    # one big one, for the same reason.
    for size in (192, 512):
        draw(size).save(SITE / f"icon-{size}.png")
    print(f"wrote {ico}  ({', '.join(str(s[0]) for s in ICO_SIZES)})")
    print(f"wrote {SITE / 'apple-touch-icon.png'}  (180)")
    print(f"wrote icon-192.png and icon-512.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
