"""Render the link-preview card, `site/media/og.png`.

    python makeog.py

WHAT IT IS FOR
--------------
The landing page's `og:image`. When this link is posted in a Discord or pasted
into an email, the unfurler fetches one picture and shows it above the title.
That picture is the first thing a coach sees, before the site, and a card that
states the promise beats a frame of gameplay: the gameplay frame also carries
ten strangers' Steam avatars, which is somebody else's data on our card.

1200 x 630 because that is what every unfurler crops to. Drawn at 2x and
downsampled with Lanczos, the same trick makeicon.py uses, because Pillow's
text rasteriser is worse than its resampler.

THE NUMBERS ON IT ARE REAL
--------------------------
The line is one of the four on the landing page, and it is a parsed reading
with its denominator beside it. If those change on the page, change them here.

FONTS
-----
The site sets display type in Space Grotesk and numbers in JetBrains Mono,
neither of which is installed on this machine. If a `.ttf` for either is
dropped into `design/fonts/`, this picks it up; otherwise it falls back to
Segoe UI and Consolas, which are close enough in weight and width that the
card reads as the same family of thing. Run this again after adding them.

The file is committed. Run this again only if the wording or the palette
changes.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "site" / "media" / "og.png"
FONTDIR = ROOT / "design" / "fonts"

W, H = 1200, 630
S = 2                                  # supersample factor

# The dark palette from app/theme.py, which is also the one in site/index.html.
# A third copy of these values is a thing that can drift, so they are named
# here the way the stylesheet names them rather than as bare hexes.
BG = "#141119"          # --bg
SURFACE = "#1C1823"     # --surface
BORDER = "#2E2739"      # --border
INK = "#EDE9F3"         # --ink
MUTED = "#A79FB5"       # --muted
FAINT = "#7E7590"       # --faint
PURPLE = "#A78BFA"      # --purple
ORANGE = "#E0A458"      # --t

# The mark, in the same 64-unit geometry as site/favicon.svg.
MARK_ARMS = [(28, 8, 8, 16), (28, 40, 8, 16), (8, 28, 16, 8), (40, 28, 16, 8)]
MARK_DOT = (28, 28, 8, 8)
# The tile behind the mark. The favicon sits it on #17141F, which against
# this card's own ground would be a tile you can only just see; --surface is
# the same relationship the site has between a card and the page behind it.
MARK_BG = SURFACE

HEADLINE = ["Your matches,", "actually read."]
STAT_WHAT = "Rounds won after losing the opening duel"
STAT_PCT = "32%"
STAT_DEN = "39 / 120"
LABEL = "OBSERVED / CHANCES"
TAGLINE = "Every number has a denominator."
DOMAIN = "counterplaycs.com"


def font(kind, size):
    """A face for `kind`, preferring the real one if somebody dropped it in."""
    wanted = {"display": ["SpaceGrotesk-Bold.ttf", "SpaceGrotesk-SemiBold.ttf"],
              "body": ["PublicSans-Regular.ttf"],
              "mono": ["JetBrainsMono-Regular.ttf"]}[kind]
    for name in wanted:
        f = FONTDIR / name
        if f.is_file():
            return ImageFont.truetype(str(f), size * S)
    fallback = {"display": "C:/Windows/Fonts/segoeuib.ttf",
                "body": "C:/Windows/Fonts/segoeui.ttf",
                "mono": "C:/Windows/Fonts/consola.ttf"}[kind]
    return ImageFont.truetype(fallback, size * S)


def px(v):
    return v * S


def tracked(d, xy, text, f, fill, track):
    """Draw `text` one glyph at a time, `track` extra pixels between them.

    Pillow has no letter-spacing and the small caps label on this card is
    unreadable without it.
    """
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=f, fill=fill)
        x += d.textlength(ch, font=f) + px(track)


def right(d, xr, y, text, f, fill):
    d.text((xr - d.textlength(text, font=f), y), text, font=f, fill=fill)


def rounded(d, box, radius, fill, outline=None, width=1):
    d.rounded_rectangle([px(box[0]), px(box[1]), px(box[2]), px(box[3])],
                        radius=px(radius), fill=fill, outline=outline,
                        width=px(width))


def draw_mark(d, x, y, size):
    """The favicon, scaled out of its 64-unit box to `size` pixels."""
    u = px(size) / 64.0
    d.rounded_rectangle([px(x), px(y), px(x) + px(size), px(y) + px(size)],
                        radius=14 * u, fill=MARK_BG)
    for (ax, ay, aw, ah) in MARK_ARMS:
        d.rectangle([px(x) + ax * u, px(y) + ay * u,
                     px(x) + (ax + aw) * u, px(y) + (ay + ah) * u], fill=PURPLE)
    dx, dy, dw, dh = MARK_DOT
    d.rectangle([px(x) + dx * u, px(y) + dy * u,
                 px(x) + (dx + dw) * u, px(y) + (dy + dh) * u], fill=ORANGE)


def build():
    img = Image.new("RGB", (W * S, H * S), BG)
    d = ImageDraw.Draw(img)

    # ---- wordmark
    draw_mark(d, 72, 64, 52)
    f_mark = font("display", 34)
    x = px(72 + 52 + 18)
    d.text((x, px(80)), "Counter", font=f_mark, fill=INK)
    x += d.textlength("Counter", font=f_mark)
    d.text((x, px(80)), "play", font=f_mark, fill=PURPLE)

    # ---- headline
    f_head = font("display", 74)
    for i, line in enumerate(HEADLINE):
        d.text((px(72), px(186 + i * 88)), line, font=f_head, fill=INK)

    # ---- the proof, in the shape the site prints it in
    rounded(d, (72, 398, 1128, 548), 14, SURFACE, outline=BORDER, width=1)
    tracked(d, (px(104), px(420)), LABEL, font("mono", 14), FAINT, 1.6)
    d.text((px(104), px(462)), STAT_WHAT, font=font("body", 29), fill=INK)
    right(d, px(1096), px(446), STAT_PCT, font("display", 46), PURPLE)
    right(d, px(1096), px(504), STAT_DEN, font("mono", 18), MUTED)

    # ---- footer
    d.text((px(72), px(576)), DOMAIN, font=font("mono", 21), fill=MUTED)
    right(d, px(1128), px(572), TAGLINE, font("body", 21), FAINT)

    return img.resize((W, H), Image.LANCZOS)


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    build().save(OUT, "PNG", optimize=True)
    print("wrote %s, %d bytes" % (OUT, OUT.stat().st_size))
