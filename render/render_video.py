#!/usr/bin/env python3
"""
AI Quantum motion-graphics renderer.

Design goals, after two rounds of feedback on the first version:
 1. A brand mark that is NOT Anthropic's logo (distinct shape + color).
 2. REAL motion, continuously -- not a static card with a camera zoom.
    Every scene bakes a seamless idle-animation loop (icons rotate/bob,
    the spark pulses, the UI card tilts, accent bars pulse) in addition to
    its entrance pop. There is no frame in the whole video that is frozen.
 3. Real icon artwork (fetched from Lucide's SVG set at render time and
    rasterized), not crude hand-drawn polygons -- with a vector fallback
    only for offline/dev use.
 4. A fresh visual beat roughly every 2-3 seconds: bullets/stats are each
    their own scene with their own entrance pop, instead of one scene
    holding three lines on screen for 5+ seconds.
 5. A punchy flash-pop at the start of every scene (a quick white flash
    that resolves in ~3 frames) so cuts read as edited, not slideshow.

All animation is baked frame-by-frame in PIL (both the entrance pop and the
idle loop), then encoded straight to video -- no ffmpeg zoompan-on-a-still
involved, because that was the root of the "dead" feeling.
"""
import argparse, io, json, math, os, random, subprocess
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import requests

try:
    import cairosvg
    CAIROSVG_OK = True
except Exception:
    CAIROSVG_OK = False

WIDTH, HEIGHT = 1080, 1920
FPS = 24

BG_COLOR = (234, 234, 231)
TEXT_COLOR = (24, 24, 24)
DOT_COLOR = (205, 205, 200)
# Deliberately NOT orange/asterisk-shaped -- that reads as Anthropic's mark.
ACCENT = (79, 70, 229)          # indigo spark -- AI Quantum's own accent
ACCENT_2 = (16, 185, 129)       # emerald -- icon chips / stat ticks / progress
CTA_PINK = (226, 28, 55)        # handle pill / CTA pill
DARK_CARD = (22, 22, 26)
DARK_CARD_2 = (38, 38, 44)
WHITE = (255, 255, 255)

FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")
F_BOLD = os.path.join(FONT_DIR, "Poppins-Bold.ttf")
F_MEDIUM = os.path.join(FONT_DIR, "Poppins-Medium.ttf")
F_REGULAR = os.path.join(FONT_DIR, "Poppins-Regular.ttf")

ENTRANCE_SEC = 0.28       # fast pop-in
FLASH_SEC = 0.09          # white flash at the very start of every cut
LOOP_SEC = 1.2            # seamless idle-animation loop length
MIN_SCENE_SEC = 0.9
MAX_SCENE_SEC = 3.2       # hard cap -- forces frequent cuts/beats

LUCIDE_MAP = {
    "bolt": "zap", "chip": "cpu", "arrow_up": "trending-up",
    "clock": "clock", "brain": "brain-circuit", "target": "target",
    "dollar": "dollar-sign", "globe": "globe", "shield": "shield-check",
    "spark": "sparkles",
}
_icon_cache = {}


def font(weight, size):
    path = {"bold": F_BOLD, "medium": F_MEDIUM, "regular": F_REGULAR}.get(weight, F_REGULAR)
    return ImageFont.truetype(path, size)


def ease_out_back(t, overshoot=1.8):
    t = max(0.0, min(1.0, t)) - 1
    return 1 + overshoot * (t ** 3) + overshoot * (t ** 2)


def ease_out_cubic(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def loop_sin(phase, cycles=1):
    """Seamless oscillation for a looping animation: phase in [0,1)."""
    return math.sin(phase * 2 * math.pi * cycles)


# ---------------------------------------------------------------- backdrop

def draw_dot_grid(draw, spacing=58, shift=(0, 0)):
    sx, sy = shift
    for x in range(-spacing, WIDTH + spacing, spacing):
        for y in range(-spacing, HEIGHT + spacing, spacing):
            draw.ellipse([x + sx - 2, y + sy - 2, x + sx + 2, y + sy + 2], fill=DOT_COLOR)


def base_canvas(idle_phase=0.0):
    img = Image.new("RGBA", (WIDTH, HEIGHT), BG_COLOR + (255,))
    # the dot grid itself drifts very slightly -- cheap, constant "alive" feel
    shift = (6 * loop_sin(idle_phase, 1), 4 * loop_sin(idle_phase + 0.25, 1))
    draw_dot_grid(ImageDraw.Draw(img), shift=shift)
    return img


# ---------------------------------------------------------------- real icons

def fetch_icon(kind, size, color, retries=1):
    """Fetch real Lucide icon artwork and rasterize it, tinted to `color`.
    Falls back to a hand-drawn vector glyph if cairosvg/network aren't
    available (e.g. local/offline testing)."""
    key = (kind, size, color)
    if key in _icon_cache:
        return _icon_cache[key]
    img = None
    if CAIROSVG_OK:
        name = LUCIDE_MAP.get(kind, "sparkles")
        try:
            r = requests.get(f"https://cdn.jsdelivr.net/npm/lucide-static@latest/icons/{name}.svg", timeout=6)
            if r.status_code == 200:
                hexcolor = "#%02x%02x%02x" % color
                svg = r.text.replace('stroke="currentColor"', f'stroke="{hexcolor}"')
                png_bytes = cairosvg.svg2png(bytestring=svg.encode(), output_width=size, output_height=size)
                img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
        except Exception as e:
            print(f"Icon fetch skipped ({kind}): {e}")
    if img is None:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw_icon_vector(ImageDraw.Draw(img), size / 2, size / 2, size * 0.36, kind, color)
    _icon_cache[key] = img
    return img


def draw_icon_vector(draw, cx, cy, r, kind, color):
    """Fallback hand-drawn glyphs, used only if the real-icon fetch fails."""
    w = max(4, int(r * 0.26))
    if kind == "bolt":
        pts = [(cx + r * 0.15, cy - r), (cx - r * 0.55, cy + r * 0.15),
               (cx - r * 0.05, cy + r * 0.15), (cx - r * 0.25, cy + r),
               (cx + r * 0.6, cy - r * 0.1), (cx + r * 0.1, cy - r * 0.1)]
        draw.polygon(pts, fill=color)
    elif kind == "chip":
        s = r * 0.7
        draw.rounded_rectangle([cx - s, cy - s, cx + s, cy + s], radius=r * 0.18, outline=color, width=w)
        draw.rectangle([cx - s * 0.35, cy - s * 0.35, cx + s * 0.35, cy + s * 0.35], fill=color)
        for i in range(-1, 2):
            off = i * s * 0.7
            draw.line([(cx + off, cy - s), (cx + off, cy - s * 1.4)], fill=color, width=w)
            draw.line([(cx + off, cy + s), (cx + off, cy + s * 1.4)], fill=color, width=w)
    elif kind == "arrow_up":
        draw.line([(cx, cy + r), (cx, cy - r * 0.3)], fill=color, width=w)
        draw.polygon([(cx - r * 0.55, cy - r * 0.15), (cx + r * 0.55, cy - r * 0.15), (cx, cy - r)], fill=color)
    elif kind == "clock":
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=w)
        draw.line([(cx, cy), (cx, cy - r * 0.6)], fill=color, width=w)
        draw.line([(cx, cy), (cx + r * 0.45, cy + r * 0.15)], fill=color, width=w)
    elif kind == "brain":
        draw.ellipse([cx - r, cy - r * 0.8, cx + r, cy + r * 0.8], outline=color, width=w)
        draw.line([(cx, cy - r * 0.8), (cx, cy + r * 0.8)], fill=color, width=max(3, int(r * 0.12)))
    else:
        pts = []
        for i in range(8):
            a = math.radians(i * 45)
            rad = r if i % 2 == 0 else r * 0.35
            pts.append((cx + rad * math.cos(a), cy + rad * math.sin(a)))
        draw.polygon(pts, fill=color)


def draw_icon_chip(img, cx, cy, r, kind, bg, fg, alpha=255, rotation=0, scale=1.0):
    size = int(r * 2.6 * max(scale, 0.05))
    if size < 4:
        return
    icon_png = fetch_icon(kind, int(r * 1.5), fg)
    chip = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    cd = ImageDraw.Draw(chip)
    cd.ellipse([0, 0, size, size], fill=bg + (alpha,))
    ic = icon_png.copy()
    if ic.size != (int(r * 1.5), int(r * 1.5)):
        ic = ic.resize((int(r * 1.5), int(r * 1.5)))
    if alpha < 255:
        a = ic.split()[3].point(lambda p: int(p * alpha / 255))
        ic.putalpha(a)
    chip.alpha_composite(ic, (int((size - ic.width) / 2), int((size - ic.height) / 2)))
    if rotation:
        chip = chip.rotate(rotation, resample=Image.BICUBIC, expand=False)
    img.alpha_composite(chip, (int(cx - size / 2), int(cy - size / 2)))


# ---------------------------------------------------------------- motifs

def make_spark(diameter, color):
    """4-point spark mark -- distinct shape+color from Anthropic's sunburst."""
    pad = int(diameter * 0.35)
    size = diameter + pad * 2
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    cx = cy = size / 2
    r = diameter / 2

    def spark_points(rr):
        pts = []
        for i in range(8):
            a = math.radians(i * 45 - 90)
            rad = rr if i % 2 == 0 else rr * 0.30
            pts.append((cx + rad * math.cos(a), cy + rad * math.sin(a)))
        return pts

    ImageDraw.Draw(shadow).polygon([(x + 7, y + 11) for x, y in spark_points(r)], fill=(0, 0, 0, 70))
    shadow = shadow.filter(ImageFilter.GaussianBlur(10))
    ImageDraw.Draw(layer).polygon(spark_points(r), fill=color + (255,))
    ImageDraw.Draw(layer).ellipse([cx - r * 0.42, cy - r * 0.42, cx + r * 0.42, cy + r * 0.42], fill=color + (255,))
    small = spark_points(r * 0.46)
    small = [(cx + (x - cx) * 2.1 + r * 1.35, cy + (y - cy) * 0.55 - r * 0.55) for x, y in small]
    ImageDraw.Draw(layer).polygon(small, fill=color + (255,))
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.alpha_composite(shadow)
    out.alpha_composite(layer)
    return out


def make_ink_splat(size, seed=0, color=(20, 20, 22)):
    rnd = random.Random(seed)
    pad = int(size * 0.25)
    canvas = size + pad * 2
    shadow = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    layer = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    cx = cy = canvas / 2
    spikes = rnd.randint(9, 12)
    pts = []
    for i in range(spikes * 2):
        a = math.radians(i * (360 / (spikes * 2)))
        r = size / 2 * (0.95 if i % 2 == 0 else rnd.uniform(0.28, 0.42))
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    ImageDraw.Draw(shadow).polygon([(x + 8, y + 12) for x, y in pts], fill=(0, 0, 0, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    ImageDraw.Draw(layer).polygon(pts, fill=color + (255,))
    out = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    out.alpha_composite(shadow)
    out.alpha_composite(layer)
    return out


_splat_cache = {}


def paste_corner_splats(img, seed=0, idle_phase=0.0):
    key = seed
    if key not in _splat_cache:
        _splat_cache[key] = (make_ink_splat(420, seed=seed * 7 + 1), make_ink_splat(460, seed=seed * 7 + 2))
    tl, br = _splat_cache[key]
    tl_off = (6 * loop_sin(idle_phase, 1), 5 * loop_sin(idle_phase + 0.3, 1))
    br_off = (5 * loop_sin(idle_phase + 0.5, 1), 6 * loop_sin(idle_phase + 0.1, 1))
    img.alpha_composite(tl, (int(-140 + tl_off[0]), int(-140 + tl_off[1])))
    img.alpha_composite(br, (int(WIDTH - 300 + br_off[0]), int(HEIGHT - 300 + br_off[1])))


def draw_pill(draw, box, fill, radius=None):
    if radius is None:
        radius = (box[3] - box[1]) / 2
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def handle_badge(img, handle, idle_phase=0.0):
    draw = ImageDraw.Draw(img)
    f = font("bold", 34)
    tw = draw.textlength(handle, font=f)
    pad_x, pad_y = 44, 20
    box_w = tw + pad_x * 2
    box_h = 34 + pad_y * 2
    bob = 3 * loop_sin(idle_phase, 1)
    x0 = (WIDTH - box_w) / 2
    y0 = HEIGHT - 170 + bob
    draw_pill(draw, [x0, y0, x0 + box_w, y0 + box_h], CTA_PINK)
    draw.text((x0 + pad_x, y0 + pad_y - 2), handle, font=f, fill=WHITE)


def wrap_text(draw, text, f, max_width):
    words = text.split()
    lines, cur, cur_w = [], [], 0
    space_w = draw.textlength(" ", font=f)
    for w in words:
        ww = draw.textlength(w, font=f)
        add = ww if not cur else ww + space_w
        if cur_w + add > max_width and cur:
            lines.append(cur); cur, cur_w = [w], ww
        else:
            cur.append(w); cur_w += add
    if cur:
        lines.append(cur)
    return [" ".join(l) for l in lines]


# ---------------------------------------------------------------- text rows

def measure_rows(rows, max_width):
    plan = []
    dummy = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    for row in rows:
        f = font(row.get("weight", "bold"), row["size"])
        lines = wrap_text(dummy, row["text"], f, max_width)
        for ln in lines:
            plan.append({"text": ln, "font": f, "size": row["size"],
                         "color": row.get("color", TEXT_COLOR),
                         "highlight": row.get("highlight", False)})
    return plan


def draw_rows_centered(img, rows, max_width=900, top=None, line_gap=1.18, reveal=1.0,
                        alternate_slide=True, idle_phase=None):
    """Draw stacked text rows centered horizontally. `reveal` in [0,1] builds
    rows in with alternating left/right/up entrance directions. Once fully
    revealed, if `idle_phase` is given, the highlighted/bold row gets a
    very subtle continuous breathing-scale pulse so text scenes aren't
    completely frozen either."""
    draw = ImageDraw.Draw(img)
    plan = measure_rows(rows, max_width)
    heights = [int(p["size"] * line_gap) for p in plan]
    total_h = sum(heights)
    y = top if top is not None else (HEIGHT - total_h) / 2

    n = len(plan)
    directions = ["left", "up", "right"]
    for idx, (p, h) in enumerate(zip(plan, heights)):
        row_reveal = max(0.0, min(1.0, reveal * n - idx))
        if row_reveal <= 0:
            y += h
            continue
        ease = ease_out_cubic(row_reveal)
        alpha = int(255 * ease)
        pulse = 1.0
        if idle_phase is not None and row_reveal >= 1.0 and (p["highlight"] or idx == n - 1):
            pulse = 1.0 + 0.025 * (0.5 + 0.5 * loop_sin(idle_phase, 1))
        f = p["font"] if pulse == 1.0 else font("bold", int(p["size"] * pulse))
        tw = draw.textlength(p["text"], font=f)
        x_base = (WIDTH - tw) / 2
        direction = directions[idx % 3] if alternate_slide else "up"
        if direction == "up":
            x, yoff = x_base, int((1 - ease) * 42)
        elif direction == "left":
            x, yoff = x_base - int((1 - ease) * 90), 0
        else:
            x, yoff = x_base + int((1 - ease) * 90), 0
        layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        if p["highlight"]:
            asc, desc = f.getmetrics()
            pad = 16
            box = [x - pad, y + yoff - pad * 0.5, x + tw + pad, y + yoff + asc + desc * 0.55 + pad * 0.5]
            ld.rounded_rectangle(box, radius=14, fill=(*TEXT_COLOR, alpha))
            ld.text((x, y + yoff), p["text"], font=f, fill=(*WHITE, alpha))
        else:
            ld.text((x, y + yoff), p["text"], font=f, fill=(*p["color"], alpha))
        img.alpha_composite(layer)
        y += h
    return img


# ---------------------------------------------------------------- app mockup

def draw_mockup_card(img, lines, reveal, rotation=0.0, bob=0.0, accent=ACCENT_2):
    card_w, card_h = 860, 560
    card = Image.new("RGBA", (card_w + 80, card_h + 80), (0, 0, 0, 0))
    shadow = Image.new("RGBA", card.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([40, 50, 40 + card_w, 50 + card_h], radius=36, fill=(0, 0, 0, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    card.alpha_composite(shadow)
    cd = ImageDraw.Draw(card)
    cd.rounded_rectangle([40, 40, 40 + card_w, 40 + card_h], radius=36, fill=DARK_CARD + (255,))
    for i, col in enumerate([(237, 106, 94), (245, 191, 79), (97, 197, 79)]):
        cd.ellipse([74 + i * 34, 72, 74 + i * 34 + 18, 90], fill=col)
    cd.line([(74, 118), (40 + card_w - 34, 118)], fill=DARK_CARD_2, width=2)

    f_line = font("medium", 40)
    n = len(lines)
    ly = 170
    for idx, line in enumerate(lines):
        line_reveal = max(0.0, min(1.0, reveal * n - idx))
        if line_reveal <= 0:
            break
        ease = ease_out_cubic(line_reveal)
        alpha = int(255 * ease)
        xoff = int((1 - ease) * 36)
        sub_lines = wrap_text(cd, line, f_line, card_w - 130)
        for sl in sub_lines:
            layer = Image.new("RGBA", card.size, (0, 0, 0, 0))
            ImageDraw.Draw(layer).text((74 + xoff, ly), sl, font=f_line, fill=(230, 230, 232, alpha))
            card.alpha_composite(layer)
            ly += 56
        if idx == n - 1 or line_reveal < 1.0:
            bar_w = int((card_w - 148) * min(1.0, line_reveal))
            cd.rounded_rectangle([74, ly + 6, 74 + max(bar_w, 6), ly + 12], radius=3, fill=accent)
        ly += 26

    if rotation:
        card = card.rotate(rotation, resample=Image.BICUBIC, expand=False)
    img.alpha_composite(card, (int((WIDTH - card.width) / 2), int(HEIGHT * 0.30 + bob)))


# ---------------------------------------------------------------- scene frame functions
# Each scene_* function takes (data, reveal, idle_phase, seed) and returns ONE
# composed RGBA frame. `reveal` drives the entrance (0 -> 1, then clamps at
# 1). `idle_phase` is a seamless 0..1 loop used for continuous idle motion
# AFTER the entrance completes (icons rotate/bob, card tilts, spark pulses).

def scene_title(data, reveal, idle_phase, seed=0):
    rows = data["rows"]
    show_spark = data.get("burst", False)
    img = base_canvas(idle_phase if reveal >= 1 else 0.0)
    if show_spark:
        spark = make_spark(240, ACCENT)
        pop = max(0.0, ease_out_back(min(1.0, reveal * 1.6)))
        idle_pulse = 1.0 + 0.05 * loop_sin(idle_phase, 1) if reveal >= 1 else 0.0
        sscale = max(0.05, 0.75 + 0.30 * pop + idle_pulse * 0.0)
        if reveal >= 1:
            sscale = 1.0 + 0.05 * loop_sin(idle_phase, 1)
        sresized = spark.resize((max(1, int(spark.width * sscale)), max(1, int(spark.height * sscale))))
        spin = (-40 + 40 * ease_out_cubic(reveal)) if reveal < 1 else 10 * loop_sin(idle_phase, 1)
        sresized = sresized.rotate(spin, resample=Image.BICUBIC, expand=False)
        sx = (WIDTH - sresized.width) // 2
        sy = int(HEIGHT * 0.25 - sresized.height / 2)
        img.alpha_composite(sresized, (sx, sy))
    top = HEIGHT * 0.38 if show_spark else None
    draw_rows_centered(img, rows, top=top, reveal=reveal, idle_phase=idle_phase if reveal >= 1 else None)
    handle_badge(img, data.get("handle", "@aiquantum"), idle_phase)
    return img


def scene_number(data, reveal, idle_phase, seed=0):
    number = data["number"]
    rows = data["rows"]
    icon_kind = data.get("icon", ["bolt", "chip", "arrow_up", "clock", "brain"][seed % 5])
    ease = ease_out_cubic(reveal)
    pop = max(0.0, ease_out_back(min(1.0, reveal * 1.4)))
    img = base_canvas(idle_phase if reveal >= 1 else 0.0)
    paste_corner_splats(img, seed=seed, idle_phase=idle_phase if reveal >= 1 else 0.0)

    chip_cy = HEIGHT * 0.30
    chip_bob = 10 * loop_sin(idle_phase, 1) if reveal >= 1 else 0
    chip_rot = 14 * loop_sin(idle_phase, 1) if reveal >= 1 else (1 - pop) * 30
    draw_icon_chip(img, WIDTH / 2, chip_cy + chip_bob, 54, icon_kind, ACCENT_2, WHITE,
                   alpha=int(255 * ease), rotation=chip_rot)

    draw = ImageDraw.Draw(img)
    num_scale = (0.8 + 0.2 * pop) if reveal < 1 else (1.0 + 0.02 * loop_sin(idle_phase, 1))
    f_num = font("bold", int(150 * num_scale))
    num_text = f"#{number}"
    tw = draw.textlength(num_text, font=f_num)
    asc, desc = f_num.getmetrics()
    ny = HEIGHT * 0.46 - (asc + desc)
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text(((WIDTH - tw) / 2, ny), num_text, font=f_num,
                                fill=(*TEXT_COLOR, int(255 * ease)))
    img.alpha_composite(layer)
    draw_rows_centered(img, rows, top=HEIGHT * 0.46 + (asc + desc) * 0.15, reveal=min(1.0, reveal * 1.4),
                        alternate_slide=False)
    handle_badge(img, data.get("handle", "@aiquantum"), idle_phase)
    return img


def scene_detail(data, reveal, idle_phase, seed=0):
    rows = data["rows"]
    img = base_canvas(idle_phase if reveal >= 1 else 0.0)
    draw_rows_centered(img, rows, reveal=reveal, idle_phase=idle_phase if reveal >= 1 else None)
    handle_badge(img, data.get("handle", "@aiquantum"), idle_phase)
    return img


def scene_mockup(data, reveal, idle_phase, seed=0):
    lines = data["lines"]
    kicker_rows = data.get("rows")
    img = base_canvas(idle_phase if reveal >= 1 else 0.0)
    if kicker_rows:
        draw_rows_centered(img, kicker_rows, top=HEIGHT * 0.13, reveal=min(1.0, reveal * 1.8))
    if reveal < 1:
        rotation = -4.0 + 4.0 * ease_out_cubic(reveal)
        bob = 0
    else:
        rotation = 1.6 * loop_sin(idle_phase, 1)
        bob = 10 * loop_sin(idle_phase + 0.25, 1)
    draw_mockup_card(img, lines, reveal=max(0.0, (reveal - 0.1) / 0.9), rotation=rotation, bob=bob)
    handle_badge(img, data.get("handle", "@aiquantum"), idle_phase)
    return img


def scene_stat(data, reveal, idle_phase, seed=0):
    """A single bullet/stat as its own beat: sparkle icon pop + one line,
    replacing the old 'hold 3 bullets for 5 seconds' approach."""
    text = data["text"]
    icon_kind = data.get("icon", "target")
    ease = ease_out_cubic(reveal)
    pop = max(0.0, ease_out_back(min(1.0, reveal * 1.5)))
    img = base_canvas(idle_phase if reveal >= 1 else 0.0)
    if data.get("title"):
        draw_rows_centered(img, data["title"], top=HEIGHT * 0.14, reveal=1.0, alternate_slide=False)

    chip_cy = HEIGHT * 0.32
    chip_bob = 10 * loop_sin(idle_phase, 1) if reveal >= 1 else 0
    chip_rot = 12 * loop_sin(idle_phase + 0.4, 1) if reveal >= 1 else (1 - pop) * 24
    draw_icon_chip(img, WIDTH / 2, chip_cy + chip_bob, 58, icon_kind, ACCENT, WHITE,
                   alpha=int(255 * ease), rotation=chip_rot)

    f_item = font("bold", 56)
    draw = ImageDraw.Draw(img)
    lines = wrap_text(draw, text, f_item, 860)
    ly = HEIGHT * 0.50
    for ln in lines:
        tw = draw.textlength(ln, font=f_item)
        offset = int((1 - ease) * 50)
        layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        ImageDraw.Draw(layer).text(((WIDTH - tw) / 2, ly + offset), ln, font=f_item,
                                    fill=(*TEXT_COLOR, int(255 * ease)))
        img.alpha_composite(layer)
        ly += 68
    handle_badge(img, data.get("handle", "@aiquantum"), idle_phase)
    return img


def scene_outro(data, reveal, idle_phase, seed=0):
    rows = data["rows"]
    cta = data.get("cta", "Follow for daily AI news")
    handle = data.get("handle", "@aiquantum")
    ease = ease_out_cubic(reveal)
    pop = max(0.0, ease_out_back(min(1.0, reveal * 1.4)))
    img = base_canvas(idle_phase if reveal >= 1 else 0.0)
    draw_rows_centered(img, rows, top=HEIGHT * 0.28, reveal=reveal)
    draw = ImageDraw.Draw(img)
    f_cta = font("bold", 42)
    tw = draw.textlength(cta, font=f_cta)
    pad_x, pad_y = 46, 26
    box_w, box_h = tw + pad_x * 2, 42 + pad_y * 2
    scale = (0.85 + 0.15 * pop) if reveal < 1 else (1.0 + 0.02 * loop_sin(idle_phase, 1))
    x0 = (WIDTH - box_w * scale) / 2
    y0 = HEIGHT * 0.58
    alpha = int(255 * ease)
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.rounded_rectangle([x0, y0, x0 + box_w * scale, y0 + box_h * scale], radius=box_h * scale / 2,
                          fill=(*CTA_PINK, alpha))
    ld.text((x0 + pad_x * scale, y0 + pad_y * scale - 4), cta, font=f_cta, fill=(*WHITE, alpha))
    img.alpha_composite(layer)
    f_handle = font("medium", 34)
    tw2 = draw.textlength(handle, font=f_handle)
    draw.text(((WIDTH - tw2) / 2, y0 + box_h * scale + 36), handle, font=f_handle, fill=(90, 90, 90))
    return img


SCENE_BUILDERS = {
    "title": scene_title,
    "number": scene_number,
    "detail": scene_detail,
    "mockup": scene_mockup,
    "stat": scene_stat,
    "outro": scene_outro,
}


def scene_word_count(data):
    total = 0
    if "rows" in data:
        total += sum(len(r["text"].split()) for r in data["rows"])
    if "text" in data:
        total += len(data["text"].split())
    if "lines" in data:
        total += sum(len(i.split()) for i in data["lines"])
    return total or 5


def expand_bullets_scene(scene):
    """A 'bullets' scene in the manifest becomes N individual 'stat' scenes
    -- one beat per item -- instead of one static scene holding all of them."""
    icons = ["target", "bolt", "arrow_up", "clock", "shield", "globe"]
    out = []
    for i, item in enumerate(scene["items"]):
        out.append({
            "type": "stat",
            "title": scene.get("title") if i == 0 else None,
            "icon": icons[i % len(icons)],
            "text": item,
        })
    return out


# ---------------------------------------------------------------- assembly

def get_audio_duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                         "-of", "default=noprint_wrappers=1:nokey=1", path],
                        capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def render_scene_clip(scene, duration, work_dir, idx, out_path, handle):
    scene = dict(scene)
    scene.setdefault("handle", handle)
    builder = SCENE_BUILDERS.get(scene["type"], scene_detail)

    seg_dir = f"{work_dir}/scene_{idx}"
    os.makedirs(seg_dir, exist_ok=True)

    # --- entrance (flash + pop), baked frame by frame
    entrance_frames = max(3, int(ENTRANCE_SEC * FPS))
    flash_frames = max(1, int(FLASH_SEC * FPS))
    frame_i = 0
    for i in range(entrance_frames):
        t = i / (entrance_frames - 1)
        frame = builder(scene, reveal=t, idle_phase=0.0, seed=idx)
        if i < flash_frames:
            flash_alpha = int(180 * (1 - i / flash_frames))
            flash = Image.new("RGBA", frame.size, (255, 255, 255, flash_alpha))
            frame = Image.alpha_composite(frame, flash)
        frame.convert("RGB").save(f"{seg_dir}/f_{frame_i:03d}.png")
        frame_i += 1

    # --- seamless idle loop (icons/card/spark keep moving for the hold)
    held_dur = max(duration - ENTRANCE_SEC, 0.3)
    loop_frame_count = max(6, int(LOOP_SEC * FPS))
    loop_frames = []
    for j in range(loop_frame_count):
        phase = j / loop_frame_count
        loop_frames.append(builder(scene, reveal=1.0, idle_phase=phase, seed=idx))

    reps = max(1, math.ceil(held_dur / LOOP_SEC))
    for _ in range(reps):
        for lf in loop_frames:
            if (frame_i - entrance_frames) >= held_dur * FPS:
                break
            lf.convert("RGB").save(f"{seg_dir}/f_{frame_i:03d}.png")
            frame_i += 1
        if (frame_i - entrance_frames) >= held_dur * FPS:
            break

    total_frames = frame_i
    subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", f"{seg_dir}/f_%03d.png",
                     "-frames:v", str(total_frames), "-pix_fmt", "yuv420p", out_path], check=True)
    return total_frames / FPS


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", required=True)
    p.add_argument("--audio", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()

    manifest = json.load(open(args.manifest))
    raw_scenes = manifest["scenes"]
    handle = manifest.get("handle", "@aiquantum")

    # Split any 'bullets' scene into individual one-beat 'stat' scenes so
    # the pacing stays frequent instead of one long static hold.
    scenes = []
    for s in raw_scenes:
        if s["type"] == "bullets":
            scenes.extend(expand_bullets_scene(s))
        else:
            scenes.append(s)

    total_duration = get_audio_duration(args.audio)
    weights = [scene_word_count(s) for s in scenes]
    total_w = sum(weights) or len(scenes)
    durations = [max(MIN_SCENE_SEC, min(MAX_SCENE_SEC, total_duration * w / total_w)) for w in weights]
    scale = total_duration / sum(durations)
    durations = [d * scale for d in durations]

    work_dir = "render_tmp"
    os.makedirs(work_dir, exist_ok=True)
    seg_paths = []
    for i, (scene, dur) in enumerate(zip(scenes, durations)):
        seg_path = f"{work_dir}/seg_{i}.mp4"
        render_scene_clip(scene, dur, work_dir, i, seg_path, handle)
        seg_paths.append(seg_path)

    concat_list = f"{work_dir}/concat_final.txt"
    with open(concat_list, "w") as f:
        for sp in seg_paths:
            f.write(f"file '{os.path.abspath(sp)}'\n")

    silent = f"{work_dir}/silent.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
                     "-c", "copy", silent], check=True)

    # Single continuous progress bar drawn once over the whole assembled
    # video (smoother than recomputing it per scene segment).
    with_bar = f"{work_dir}/with_bar.mp4"
    bar_w = f"{WIDTH}*t/{total_duration}"
    subprocess.run(["ffmpeg", "-y", "-i", silent, "-vf",
                     f"drawbox=x=0:y={HEIGHT-14}:w='{bar_w}':h=6:color=0x4F46E5@1:t=fill",
                     "-pix_fmt", "yuv420p", with_bar], check=True)

    subprocess.run(["ffmpeg", "-y", "-i", with_bar, "-i", args.audio,
                     "-c:v", "libx264", "-c:a", "aac", "-shortest", args.output], check=True)
    print(f"Rendered: {args.output}")


if __name__ == "__main__":
    main()
