#!/usr/bin/env python3
"""
AI Quantum motion-graphics renderer.

Reverse-engineered visual style: off-white background with a faint dotted
grid, bold two-weight kinetic typography, a terracotta pinwheel "burst" mark,
jagged black ink-splat corner decorations on number/divider cards, a dark
rounded "app mockup" card, and a red pill handle badge that stays on screen
throughout. Scenes are rendered frame-by-frame with PIL, turned into short
mp4 clips with ffmpeg (entrance animation + slow zoom + progress bar), then
concatenated and muxed against the narration track.

Input: a JSON "manifest" (see pipeline/run_pipeline.py for the generator)
shaped like:

{
  "channel_name": "AI Quantum",
  "handle": "@aiquantum",
  "scenes": [
    {"type": "title",  "kicker": "BREAKING",  "rows": [...], "weight_words": 3},
    {"type": "number", "number": 1, "rows": [...]},
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
ACCENT = (214, 93, 67)          # terracotta burst
CTA_PINK = (226, 28, 55)        # handle pill / CTA pill
DARK_CARD = (24, 24, 26)
DARK_CARD_2 = (36, 36, 39)
WHITE = (255, 255, 255)

FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")
F_BOLD = os.path.join(FONT_DIR, "Poppins-Bold.ttf")
F_MEDIUM = os.path.join(FONT_DIR, "Poppins-Medium.ttf")
F_REGULAR = os.path.join(FONT_DIR, "Poppins-Regular.ttf")

ENTRANCE_FRAMES = 8
MIN_SCENE_SECONDS = 1.0


def font(weight, size):
    path = {"bold": F_BOLD, "medium": F_MEDIUM, "regular": F_REGULAR}.get(weight, F_REGULAR)
    return ImageFont.truetype(path, size)


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

def make_burst(diameter, color, points=11, seed=0):
    """Pinwheel / sunburst mark like the reference video's opening icon."""
    pad = int(diameter * 0.35)
    size = diameter + pad * 2
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    cx = cy = size / 2
    rnd = random.Random(seed)
    r_out = diameter / 2
    r_in = r_out * 0.16

    def petal_polygon(angle, jitter):
        a = math.radians(angle)
        tip_r = r_out * (0.92 + jitter)
        tip = (cx + tip_r * math.cos(a), cy + tip_r * math.sin(a))
        spread = math.radians(360 / points * 0.30)
        base_l = (cx + r_in * math.cos(a - spread), cy + r_in * math.sin(a - spread))
        base_r = (cx + r_in * math.cos(a + spread), cy + r_in * math.sin(a + spread))
        mid_l = (cx + r_out * 0.45 * math.cos(a - spread * 0.5), cy + r_out * 0.45 * math.sin(a - spread * 0.5))
        mid_r = (cx + r_out * 0.45 * math.cos(a + spread * 0.5), cy + r_out * 0.45 * math.sin(a + spread * 0.5))
        return [base_l, mid_l, tip, mid_r, base_r]

    sdraw = ImageDraw.Draw(shadow)
    ldraw = ImageDraw.Draw(layer)
    for i in range(points):
        angle = i * (360 / points)
        jitter = rnd.uniform(-0.05, 0.08)
        poly = petal_polygon(angle, jitter)
        sdraw.polygon([(x + 6, y + 10) for x, y in poly], fill=(0, 0, 0, 70))
        ldraw.polygon(poly, fill=color + (255,))
    ldraw.ellipse([cx - r_in * 1.6, cy - r_in * 1.6, cx + r_in * 1.6, cy + r_in * 1.6], fill=color + (255,))
    shadow = shadow.filter(ImageFilter.GaussianBlur(10))
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


# ---------------------------------------------------------------- text rows

def measure_rows(rows, max_width):
    """rows: list of {text, weight, size, color, align}. Returns render plan."""
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


def draw_rows_centered(img, rows, max_width=900, top=None, line_gap=1.18, reveal=1.0):
    """Draw stacked text rows centered horizontally. `reveal` in [0,1] lets N
    of the rows progressively fade/slide in (used for kinetic build-up)."""
    draw = ImageDraw.Draw(img)
    plan = measure_rows(rows, max_width)
    heights = [int(p["size"] * line_gap) for p in plan]
    total_h = sum(heights)
    y = top if top is not None else (HEIGHT - total_h) / 2

    n = len(plan)
    for idx, (p, h) in enumerate(zip(plan, heights)):
        row_reveal = max(0.0, min(1.0, reveal * n - idx))
        if row_reveal <= 0:
            y += h
            continue
        ease = 1 - (1 - row_reveal) ** 3
        offset = int((1 - ease) * 40)
        alpha = int(255 * ease)
        tw = draw.textlength(p["text"], font=p["font"])
        x = (WIDTH - tw) / 2
        layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        if p["highlight"]:
            asc, desc = p["font"].getmetrics()
            pad = 16
            box = [x - pad, y + offset - pad * 0.5, x + tw + pad, y + offset + asc + desc * 0.55 + pad * 0.5]
            ld.rounded_rectangle(box, radius=14, fill=(*TEXT_COLOR, alpha))
            ld.text((x, y + offset), p["text"], font=p["font"], fill=(*WHITE, alpha))
        else:
            ld.text((x, y + offset), p["text"], font=p["font"], fill=(*p["color"], alpha))
        img.alpha_composite(layer)
        y += h
    return img


# ---------------------------------------------------------------- scenes
# Each scene_* function returns a list of PIL RGBA frames for its entrance
# animation; the caller then holds the last frame for the remaining duration.

def scene_title(data, seed=0):
    rows = data["rows"]
    kicker_burst = data.get("burst", False)
    frames = []
    for i in range(ENTRANCE_FRAMES):
        t = i / (ENTRANCE_FRAMES - 1)
        img = base_canvas()
        if kicker_burst:
            burst = make_burst(260, ACCENT, seed=seed)
            bscale = 0.85 + 0.15 * (1 - (1 - t) ** 3)
            bresized = burst.resize((int(burst.width * bscale), int(burst.height * bscale)))
            bx = (WIDTH - bresized.width) // 2
            by = int(HEIGHT * 0.26 - bresized.height / 2)
            img.alpha_composite(bresized, (bx, by))
        top = HEIGHT * 0.40 if kicker_burst else None
        draw_rows_centered(img, rows, top=top, reveal=t)
        handle_badge(img, data.get("handle", "@aiquantum"))
        frames.append(img)
    return frames


def scene_number(data, seed=0):
    number = data["number"]
    rows = data["rows"]
    frames = []
    for i in range(ENTRANCE_FRAMES):
        t = i / (ENTRANCE_FRAMES - 1)
        ease = 1 - (1 - t) ** 3
        img = base_canvas()
        paste_corner_splats(img, seed=seed)
        draw = ImageDraw.Draw(img)
        f_num = font("bold", int(150 * (0.85 + 0.15 * ease)))
        num_text = f"#{number}"
        tw = draw.textlength(num_text, font=f_num)
        asc, desc = f_num.getmetrics()
        ny = HEIGHT * 0.44 - (asc + desc)
        layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        ImageDraw.Draw(layer).text(((WIDTH - tw) / 2, ny), num_text, font=f_num,
                                    fill=(*TEXT_COLOR, int(255 * ease)))
        img.alpha_composite(layer)
        draw_rows_centered(img, rows, top=HEIGHT * 0.44 + (asc + desc) * 0.15, reveal=min(1.0, t * 1.3))
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


def draw_sparkle(draw, cx, cy, r, color, alpha=255):
    """4-point sparkle/diamond-star, drawn as a vector shape (no font glyph)."""
    pts = []
    for i in range(8):
        a = math.radians(i * 45)
        rad = r if i % 2 == 0 else r * 0.32
        pts.append((cx + rad * math.cos(a), cy + rad * math.sin(a)))
    draw.polygon(pts, fill=(*color, alpha))


def scene_bullets(data, seed=0):
    items = data["items"]
    frames = []
    f_item = font("medium", 46)
    for i in range(ENTRANCE_FRAMES):
        t = i / (ENTRANCE_FRAMES - 1)
        img = base_canvas()
        draw = ImageDraw.Draw(img)
        if data.get("title"):
            draw_rows_centered(img, data["title"], top=HEIGHT * 0.14, reveal=1.0)
        n = len(items)
        block_h = 140
        total_h = block_h * n
        y0 = HEIGHT * 0.38
        for idx, item in enumerate(items):
            reveal = max(0.0, min(1.0, t * n - idx))
            if reveal <= 0:
                continue
            ease = 1 - (1 - reveal) ** 3
            offset = int((1 - ease) * 30)
            alpha = int(255 * ease)
            y = y0 + idx * block_h + offset
            layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
            ld = ImageDraw.Draw(layer)
            draw_sparkle(ld, 108, y + 30, 26, ACCENT, alpha)
            lines = wrap_text(draw, item, f_item, 760)
            ly = y - 6
            for ln in lines:
                ld.text((170, ly), ln, font=f_item, fill=(*TEXT_COLOR, alpha))
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
        ease = 1 - (1 - t) ** 3
        img = base_canvas()
        draw_rows_centered(img, rows, top=HEIGHT * 0.30, reveal=t)
        draw = ImageDraw.Draw(img)
        f_cta = font("bold", 42)
        tw = draw.textlength(cta, font=f_cta)
        pad_x, pad_y = 46, 26
        box_w, box_h = tw + pad_x * 2, 42 + pad_y * 2
        x0 = (WIDTH - box_w) / 2
        y0 = HEIGHT * 0.62
        alpha = int(255 * ease)
        layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.rounded_rectangle([x0, y0, x0 + box_w, y0 + box_h], radius=box_h / 2, fill=(*CTA_PINK, alpha))
        ld.text((x0 + pad_x, y0 + pad_y - 4), cta, font=f_cta, fill=(*WHITE, alpha))
        img.alpha_composite(layer)
        f_handle = font("medium", 34)
        tw2 = draw.textlength(handle, font=f_handle)
        draw.text(((WIDTH - tw2) / 2, y0 + box_h + 36), handle, font=f_handle, fill=(90, 90, 90))
        frames.append(img)
    return frames


SCENE_BUILDERS = {
    "title": scene_title,
    "number": scene_number,
    "detail": scene_detail,
    "bullets": scene_bullets,
    "outro": scene_outro,
}


def scene_word_count(data):
    if "rows" in data:
        return sum(len(r["text"].split()) for r in data["rows"]) or 4
    if "items" in data:
        return sum(len(i.split()) for i in data["items"]) or 4
    return 6


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
    zoom_expr = f"1+0.04*min(1,on/{total_frames})"
    bar_w = f"{WIDTH}*({seg_start}+{entrance_dur}+t)/{total_duration}"
    vf = (f"scale=2160:3840,zoompan=z='{zoom_expr}':d={total_frames}:s={WIDTH}x{HEIGHT}:fps={FPS},"
          f"drawbox=x=0:y={HEIGHT-14}:w='{bar_w}':h=6:color=0xD65D43@1:t=fill")
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
