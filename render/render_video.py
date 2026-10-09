#!/usr/bin/env python3
"""
AI Quantum motion-graphics renderer.

Visual language: off-white background with a faint dotted grid, bold
two-weight kinetic typography, jagged black ink-splat corner decorations on
number/divider cards, a dark rounded "app mockup" card with a progressive
line reveal (real UI-motion, not just text), small icon chips next to
numbered points, and a red pill handle badge that stays on screen
throughout. Text rows alternate their entrance direction (up / left / right)
instead of all rising the same way, and every held frame keeps drifting
(zoom + pan), so nothing in the video is ever fully static.

Scenes are rendered frame-by-frame with PIL, turned into short mp4 clips
with ffmpeg (entrance animation + continuous zoom/pan + progress bar), then
concatenated and muxed against the narration track.

Input: a JSON "manifest" (see pipeline/run_pipeline.py for the generator)
shaped like:

{
  "channel_name": "AI Quantum",
  "handle": "@aiquantum",
  "scenes": [
    {"type": "title",  "burst": true, "rows": [...]},
    {"type": "number", "number": 1, "icon": "bolt", "rows": [...]},
    {"type": "mockup", "lines": ["...", "..."]},
    {"type": "detail", "rows": [...]},
    {"type": "bullets", "items": ["...", "..."]},
    {"type": "outro",  "rows": [...], "cta": "Follow for daily AI news"}
  ]
}

Each scene's on-screen duration is proportional to its narration word count
so the captions stay in sync with the single TTS audio track.
"""
import argparse, json, math, os, random, subprocess
from PIL import Image, ImageDraw, ImageFont, ImageFilter

WIDTH, HEIGHT = 1080, 1920
FPS = 30

BG_COLOR = (234, 234, 231)
TEXT_COLOR = (24, 24, 24)
DOT_COLOR = (205, 205, 200)
# Deliberately NOT orange/asterisk-shaped (that reads as Anthropic's mark).
# AI Quantum's own accent: electric indigo, used for a 4-point "spark" shape
# instead of an 11-petal sunburst.
ACCENT = (79, 70, 229)          # indigo spark
ACCENT_2 = (16, 185, 129)       # emerald, used for icon chips / stat ticks
CTA_PINK = (226, 28, 55)        # handle pill / CTA pill
DARK_CARD = (22, 22, 26)
DARK_CARD_2 = (38, 38, 44)
WHITE = (255, 255, 255)

FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")
F_BOLD = os.path.join(FONT_DIR, "Poppins-Bold.ttf")
F_MEDIUM = os.path.join(FONT_DIR, "Poppins-Medium.ttf")
F_REGULAR = os.path.join(FONT_DIR, "Poppins-Regular.ttf")

ENTRANCE_FRAMES = 10
MIN_SCENE_SECONDS = 1.1


def font(weight, size):
    path = {"bold": F_BOLD, "medium": F_MEDIUM, "regular": F_REGULAR}.get(weight, F_REGULAR)
    return ImageFont.truetype(path, size)


def ease_out_back(t, overshoot=1.6):
    """Snappy 'pop in with a little overshoot' easing, used for icon/number
    entrances so they feel like motion-graphics pops, not plain fades."""
    t -= 1
    return 1 + overshoot * (t ** 3) + overshoot * (t ** 2) if t != 0 else 0.0


def ease_out_cubic(t):
    return 1 - (1 - t) ** 3


# ---------------------------------------------------------------- backdrop

def draw_dot_grid(draw, spacing=58):
    for x in range(0, WIDTH + spacing, spacing):
        for y in range(0, HEIGHT + spacing, spacing):
            draw.ellipse([x - 2, y - 2, x + 2, y + 2], fill=DOT_COLOR)


def base_canvas():
    img = Image.new("RGBA", (WIDTH, HEIGHT), BG_COLOR + (255,))
    draw_dot_grid(ImageDraw.Draw(img))
    return img


# ---------------------------------------------------------------- motifs

def make_spark(diameter, color, seed=0):
    """4-point spark/asterisk mark -- a distinct shape+color from Anthropic's
    sunburst logo, used as AI Quantum's own accent mark."""
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
    """Jagged torn-paper / explosion shape used as a corner decoration."""
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


def paste_corner_splats(img, seed=0):
    tl = make_ink_splat(420, seed=seed * 7 + 1)
    br = make_ink_splat(460, seed=seed * 7 + 2)
    img.alpha_composite(tl, (-140, -140))
    img.alpha_composite(br, (WIDTH - 300, HEIGHT - 300))


def draw_pill(draw, box, fill, radius=None):
    if radius is None:
        radius = (box[3] - box[1]) / 2
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def handle_badge(img, handle):
    draw = ImageDraw.Draw(img)
    f = font("bold", 34)
    tw = draw.textlength(handle, font=f)
    pad_x, pad_y = 44, 20
    box_w = tw + pad_x * 2
    box_h = 34 + pad_y * 2
    x0 = (WIDTH - box_w) / 2
    y0 = HEIGHT - 170
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


# ---------------------------------------------------------------- icon chips

def draw_icon(draw, cx, cy, r, kind, color):
    """Small vector glyphs drawn from primitives -- no external assets,
    no font glyph dependency. Gives number/point cards a real graphic
    element instead of pure typography."""
    if kind == "bolt":
        pts = [(cx + r * 0.15, cy - r), (cx - r * 0.55, cy + r * 0.15),
               (cx - r * 0.05, cy + r * 0.15), (cx - r * 0.25, cy + r),
               (cx + r * 0.6, cy - r * 0.1), (cx + r * 0.1, cy - r * 0.1)]
        draw.polygon(pts, fill=color)
    elif kind == "chip":
        s = r * 0.7
        draw.rounded_rectangle([cx - s, cy - s, cx + s, cy + s], radius=r * 0.18, outline=color, width=max(3, int(r * 0.12)))
        draw.rectangle([cx - s * 0.35, cy - s * 0.35, cx + s * 0.35, cy + s * 0.35], fill=color)
        for i in range(-1, 2):
            off = i * s * 0.7
            draw.line([(cx + off, cy - s), (cx + off, cy - s * 1.4)], fill=color, width=max(3, int(r * 0.1)))
            draw.line([(cx + off, cy + s), (cx + off, cy + s * 1.4)], fill=color, width=max(3, int(r * 0.1)))
    elif kind == "arrow_up":
        draw.line([(cx, cy + r), (cx, cy - r * 0.3)], fill=color, width=max(4, int(r * 0.22)))
        draw.polygon([(cx - r * 0.55, cy - r * 0.15), (cx + r * 0.55, cy - r * 0.15), (cx, cy - r)], fill=color)
    elif kind == "clock":
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=max(4, int(r * 0.18)))
        draw.line([(cx, cy), (cx, cy - r * 0.6)], fill=color, width=max(3, int(r * 0.15)))
        draw.line([(cx, cy), (cx + r * 0.45, cy + r * 0.15)], fill=color, width=max(3, int(r * 0.15)))
    elif kind == "brain":
        draw.ellipse([cx - r, cy - r * 0.8, cx + r, cy + r * 0.8], outline=color, width=max(4, int(r * 0.16)))
        draw.line([(cx, cy - r * 0.8), (cx, cy + r * 0.8)], fill=color, width=max(3, int(r * 0.12)))
        for s in (-1, 1):
            draw.arc([cx + s * r * 0.1 - r * 0.45, cy - r * 0.55, cx + s * r * 0.1 + r * 0.45, cy - r * 0.05],
                      0, 360, fill=color, width=max(2, int(r * 0.08)))
    else:  # default: spark
        pts = []
        for i in range(8):
            a = math.radians(i * 45)
            rad = r if i % 2 == 0 else r * 0.35
            pts.append((cx + rad * math.cos(a), cy + rad * math.sin(a)))
        draw.polygon(pts, fill=color)


def draw_icon_chip(img, cx, cy, r, kind, bg, fg, alpha=255, rotation=0):
    size = int(r * 2.6)
    chip = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    cd = ImageDraw.Draw(chip)
    cd.ellipse([0, 0, size, size], fill=bg + (alpha,))
    draw_icon(cd, size / 2, size / 2, r * 0.85, kind, fg + (alpha,))
    if rotation:
        chip = chip.rotate(rotation, resample=Image.BICUBIC, expand=False)
    img.alpha_composite(chip, (int(cx - size / 2), int(cy - size / 2)))


def draw_sparkle(draw, cx, cy, r, color, alpha=255):
    pts = []
    for i in range(8):
        a = math.radians(i * 45)
        rad = r if i % 2 == 0 else r * 0.32
        pts.append((cx + rad * math.cos(a), cy + rad * math.sin(a)))
    draw.polygon(pts, fill=(*color, alpha))


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


def draw_rows_centered(img, rows, max_width=900, top=None, line_gap=1.18, reveal=1.0, alternate_slide=True):
    """Draw stacked text rows centered horizontally. `reveal` in [0,1] lets N
    of the rows progressively build in. Consecutive rows alternate their
    entrance direction (left / right / up) for more varied on-screen motion
    than a uniform rise-and-fade."""
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
        tw = draw.textlength(p["text"], font=p["font"])
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
            asc, desc = p["font"].getmetrics()
            pad = 16
            box = [x - pad, y + yoff - pad * 0.5, x + tw + pad, y + yoff + asc + desc * 0.55 + pad * 0.5]
            ld.rounded_rectangle(box, radius=14, fill=(*TEXT_COLOR, alpha))
            ld.text((x, y + yoff), p["text"], font=p["font"], fill=(*WHITE, alpha))
        else:
            ld.text((x, y + yoff), p["text"], font=p["font"], fill=(*p["color"], alpha))
        img.alpha_composite(layer)
        y += h
    return img


# ---------------------------------------------------------------- app mockup

def draw_mockup_card(img, lines, reveal, rotation=0.0, accent=ACCENT_2):
    """Dark rounded 'app / chat UI' card with window-chrome dots and a
    top-to-bottom progressive line reveal (simulated streaming response).
    This is the genuine graphic/UI motion element -- not text on a plain
    background -- that a kinetic-type-only approach was missing."""
    card_w, card_h = 860, 620
    card = Image.new("RGBA", (card_w + 80, card_h + 80), (0, 0, 0, 0))
    shadow = Image.new("RGBA", card.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([40, 50, 40 + card_w, 50 + card_h], radius=36, fill=(0, 0, 0, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    card.alpha_composite(shadow)
    cd = ImageDraw.Draw(card)
    cd.rounded_rectangle([40, 40, 40 + card_w, 40 + card_h], radius=36, fill=DARK_CARD + (255,))
    # window chrome dots
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
        # a thin accent progress tick under the most-recently-revealed line
        if idx == n - 1 or line_reveal < 1.0:
            bar_w = int((card_w - 148) * min(1.0, line_reveal))
            cd.rounded_rectangle([74, ly + 6, 74 + max(bar_w, 6), ly + 12], radius=3, fill=accent)
        ly += 26

    if rotation:
        card = card.rotate(rotation, resample=Image.BICUBIC, expand=False)
    img.alpha_composite(card, (int((WIDTH - card.width) / 2), int(HEIGHT * 0.30)))


# ---------------------------------------------------------------- scenes
# Each scene_* function returns a list of PIL RGBA frames for its entrance
# animation; the caller then holds the last frame for the remaining duration.

def scene_title(data, seed=0):
    rows = data["rows"]
    show_spark = data.get("burst", False)
    frames = []
    for i in range(ENTRANCE_FRAMES):
        t = i / (ENTRANCE_FRAMES - 1)
        img = base_canvas()
        if show_spark:
            spark = make_spark(240, ACCENT, seed=seed)
            pop = max(0.0, ease_out_back(min(1.0, t * 1.4)))
            sscale = max(0.05, 0.75 + 0.30 * pop)
            sresized = spark.resize((max(1, int(spark.width * sscale)), max(1, int(spark.height * sscale))))
            spin = -40 + 40 * ease_out_cubic(t)
            sresized = sresized.rotate(spin, resample=Image.BICUBIC, expand=False)
            sx = (WIDTH - sresized.width) // 2
            sy = int(HEIGHT * 0.25 - sresized.height / 2)
            img.alpha_composite(sresized, (sx, sy))
        top = HEIGHT * 0.38 if show_spark else None
        draw_rows_centered(img, rows, top=top, reveal=t)
        handle_badge(img, data.get("handle", "@aiquantum"))
        frames.append(img)
    return frames


def scene_number(data, seed=0):
    number = data["number"]
    rows = data["rows"]
    icon_kind = data.get("icon", ["bolt", "chip", "arrow_up", "clock", "brain"][seed % 5])
    frames = []
    for i in range(ENTRANCE_FRAMES):
        t = i / (ENTRANCE_FRAMES - 1)
        ease = ease_out_cubic(t)
        pop = max(0.0, ease_out_back(min(1.0, t * 1.3)))
        img = base_canvas()
        paste_corner_splats(img, seed=seed)

        chip_cy = HEIGHT * 0.30
        draw_icon_chip(img, WIDTH / 2, chip_cy, 54, icon_kind, ACCENT_2, WHITE,
                        alpha=int(255 * ease), rotation=(1 - pop) * 30)

        draw = ImageDraw.Draw(img)
        f_num = font("bold", int(150 * (0.8 + 0.2 * pop)))
        num_text = f"#{number}"
        tw = draw.textlength(num_text, font=f_num)
        asc, desc = f_num.getmetrics()
        ny = HEIGHT * 0.46 - (asc + desc)
        layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        ImageDraw.Draw(layer).text(((WIDTH - tw) / 2, ny), num_text, font=f_num,
                                    fill=(*TEXT_COLOR, int(255 * ease)))
        img.alpha_composite(layer)
        draw_rows_centered(img, rows, top=HEIGHT * 0.46 + (asc + desc) * 0.15, reveal=min(1.0, t * 1.3),
                            alternate_slide=False)
        handle_badge(img, data.get("handle", "@aiquantum"))
        frames.append(img)
    return frames


def scene_detail(data, seed=0):
    rows = data["rows"]
    frames = []
    for i in range(ENTRANCE_FRAMES):
        t = i / (ENTRANCE_FRAMES - 1)
        img = base_canvas()
        draw_rows_centered(img, rows, reveal=t)
        handle_badge(img, data.get("handle", "@aiquantum"))
        frames.append(img)
    return frames


def scene_mockup(data, seed=0):
    """A dark app/chat-style UI card that 'types out' its lines -- the real
    motion-graphics element: an animated object, not just moving text."""
    lines = data["lines"]
    kicker_rows = data.get("rows")
    frames = []
    for i in range(ENTRANCE_FRAMES):
        t = i / (ENTRANCE_FRAMES - 1)
        img = base_canvas()
        if kicker_rows:
            draw_rows_centered(img, kicker_rows, top=HEIGHT * 0.13, reveal=min(1.0, t * 1.6))
        rotation = -3.5 + 3.5 * ease_out_cubic(t)
        draw_mockup_card(img, lines, reveal=max(0.0, (t - 0.15) / 0.85), rotation=rotation)
        handle_badge(img, data.get("handle", "@aiquantum"))
        frames.append(img)
    return frames


def scene_bullets(data, seed=0):
    items = data["items"]
    frames = []
    f_item = font("medium", 46)
    for i in range(ENTRANCE_FRAMES):
        t = i / (ENTRANCE_FRAMES - 1)
        img = base_canvas()
        draw = ImageDraw.Draw(img)
        if data.get("title"):
            draw_rows_centered(img, data["title"], top=HEIGHT * 0.14, reveal=1.0, alternate_slide=False)
        n = len(items)
        block_h = 140
        y0 = HEIGHT * 0.38
        for idx, item in enumerate(items):
            reveal = max(0.0, min(1.0, t * n - idx))
            if reveal <= 0:
                continue
            ease = ease_out_cubic(reveal)
            pop = max(0.0, ease_out_back(reveal))
            offset_x = int((1 - ease) * (60 if idx % 2 == 0 else -60))
            alpha = int(255 * ease)
            y = y0 + idx * block_h
            layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
            ld = ImageDraw.Draw(layer)
            draw_sparkle(ld, 108 + offset_x, y + 30, 20 + 8 * pop, ACCENT, alpha)
            lines = wrap_text(draw, item, f_item, 760)
            ly = y - 6
            for ln in lines:
                ld.text((170 + offset_x, ly), ln, font=f_item, fill=(*TEXT_COLOR, alpha))
                ly += 56
            img.alpha_composite(layer)
        handle_badge(img, data.get("handle", "@aiquantum"))
        frames.append(img)
    return frames


def scene_outro(data, seed=0):
    rows = data["rows"]
    cta = data.get("cta", "Follow for daily AI news")
    handle = data.get("handle", "@aiquantum")
    frames = []
    for i in range(ENTRANCE_FRAMES):
        t = i / (ENTRANCE_FRAMES - 1)
        ease = ease_out_cubic(t)
        pop = max(0.0, ease_out_back(t))
        img = base_canvas()
        draw_rows_centered(img, rows, top=HEIGHT * 0.28, reveal=t)
        draw = ImageDraw.Draw(img)
        f_cta = font("bold", 42)
        tw = draw.textlength(cta, font=f_cta)
        pad_x, pad_y = 46, 26
        box_w, box_h = tw + pad_x * 2, 42 + pad_y * 2
        scale = 0.85 + 0.15 * pop
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
        frames.append(img)
    return frames


SCENE_BUILDERS = {
    "title": scene_title,
    "number": scene_number,
    "detail": scene_detail,
    "mockup": scene_mockup,
    "bullets": scene_bullets,
    "outro": scene_outro,
}


def scene_word_count(data):
    total = 0
    if "rows" in data:
        total += sum(len(r["text"].split()) for r in data["rows"])
    if "items" in data:
        total += sum(len(i.split()) for i in data["items"])
    if "lines" in data:
        total += sum(len(i.split()) for i in data["lines"])
    return total or 6


# ---------------------------------------------------------------- assembly

def get_audio_duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                         "-of", "default=noprint_wrappers=1:nokey=1", path],
                        capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def render_scene_clip(scene, duration, seg_start, total_duration, work_dir, idx, out_path, handle):
    scene = dict(scene)
    scene.setdefault("handle", handle)
    builder = SCENE_BUILDERS.get(scene["type"], scene_detail)
    frames = builder(scene, seed=idx)

    seg_dir = f"{work_dir}/scene_{idx}"
    os.makedirs(seg_dir, exist_ok=True)
    for i, frame in enumerate(frames):
        frame.convert("RGB").save(f"{seg_dir}/f_{i:02d}.png")

    entrance_dur = len(frames) / FPS
    held_dur = max(duration - entrance_dur, 0.15)

    entrance_clip = f"{seg_dir}/entrance.mp4"
    subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", f"{seg_dir}/f_%02d.png",
                     "-frames:v", str(len(frames)), "-pix_fmt", "yuv420p", entrance_clip], check=True)

    held_png = f"{seg_dir}/held.png"
    frames[-1].convert("RGB").save(held_png)
    held_clip = f"{seg_dir}/held.mp4"
    total_frames = max(int(held_dur * FPS), 1)
    # Continuous motion through the whole hold, not just a static image:
    # slow zoom + a gentle diagonal drift (sine-based pan), alternated by
    # scene index so consecutive cards don't drift identically.
    zoom_expr = f"1+0.05*min(1,on/{total_frames})"
    pan_dir = 1 if idx % 2 == 0 else -1
    x_expr = f"iw/2-(iw/zoom/2)+{pan_dir}*14*sin(on/{max(total_frames,1)}*3.14159)"
    y_expr = f"ih/2-(ih/zoom/2)+10*sin(on/{max(total_frames,1)}*3.14159*0.6)"
    bar_w = f"{WIDTH}*({seg_start}+{entrance_dur}+t)/{total_duration}"
    vf = (f"scale=2160:3840,zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}':d={total_frames}:s={WIDTH}x{HEIGHT}:fps={FPS},"
          f"drawbox=x=0:y={HEIGHT-14}:w='{bar_w}':h=6:color=0x4F46E5@1:t=fill")
    subprocess.run(["ffmpeg", "-y", "-loop", "1", "-i", held_png, "-t", str(held_dur),
                     "-vf", vf, "-pix_fmt", "yuv420p", held_clip], check=True)

    concat_list = f"{seg_dir}/concat.txt"
    with open(concat_list, "w") as f:
        f.write(f"file '{os.path.abspath(entrance_clip)}'\n")
        f.write(f"file '{os.path.abspath(held_clip)}'\n")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
                     "-c", "copy", out_path], check=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", required=True)
    p.add_argument("--audio", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()

    manifest = json.load(open(args.manifest))
    scenes = manifest["scenes"]
    handle = manifest.get("handle", "@aiquantum")

    total_duration = get_audio_duration(args.audio)
    weights = [scene_word_count(s) for s in scenes]
    total_w = sum(weights) or len(scenes)
    durations = [max(MIN_SCENE_SECONDS, total_duration * w / total_w) for w in weights]
    scale = total_duration / sum(durations)
    durations = [d * scale for d in durations]

    work_dir = "render_tmp"
    os.makedirs(work_dir, exist_ok=True)
    seg_paths = []
    elapsed = 0.0
    for i, (scene, dur) in enumerate(zip(scenes, durations)):
        seg_path = f"{work_dir}/seg_{i}.mp4"
        render_scene_clip(scene, dur, elapsed, total_duration, work_dir, i, seg_path, handle)
        seg_paths.append(seg_path)
        elapsed += dur

    concat_list = f"{work_dir}/concat_final.txt"
    with open(concat_list, "w") as f:
        for sp in seg_paths:
            f.write(f"file '{os.path.abspath(sp)}'\n")

    silent = f"{work_dir}/silent.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
                     "-c", "copy", silent], check=True)
    subprocess.run(["ffmpeg", "-y", "-i", silent, "-i", args.audio,
                     "-c:v", "copy", "-c:a", "aac", "-shortest", args.output], check=True)
    print(f"Rendered: {args.output}")


if __name__ == "__main__":
    main()
