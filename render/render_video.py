#!/usr/bin/env python3
import argparse, json, re, subprocess, os, io
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import requests
try:
    import cairosvg
    CAIROSVG_OK = True
except Exception:
    CAIROSVG_OK = False

WIDTH, HEIGHT = 1080, 1920
BG_COLOR = (245, 245, 243)
TEXT_COLOR = (25, 25, 25)
DOT_COLOR = (222, 222, 218)
ACCENT_COLOR = (255, 107, 74)
WATERMARK_COLOR = (140, 140, 140)
FONT_BOLD = "render/fonts/Poppins-Bold.ttf"
FONT_REGULAR = "render/fonts/Poppins-Regular.ttf"
FONT_SIZE = 68
ENTRANCE_FRAMES = 6
FPS = 30

def fetch_logo(slug, size=180):
    if not CAIROSVG_OK:
        return None
    try:
        r = requests.get(f"https://cdn.simpleicons.org/{slug}", timeout=6)
        if r.status_code != 200:
            return None
        png_bytes = cairosvg.svg2png(bytestring=r.content, output_width=size, output_height=size)
        logo = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
        card = Image.new("RGBA", (size + 40, size + 40), (0, 0, 0, 0))
        shadow = Image.new("RGBA", (size + 40, size + 40), (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(shadow)
        sdraw.rounded_rectangle([20, 24, size + 20, size + 24], radius=28, fill=(0, 0, 0, 60))
        shadow = shadow.filter(ImageFilter.GaussianBlur(12))
        card.alpha_composite(shadow)
        cdraw = ImageDraw.Draw(card)
        cdraw.rounded_rectangle([20, 20, size + 20, size + 20], radius=28, fill=(255, 255, 255, 255))
        card.alpha_composite(logo, (20 + (size - logo.width) // 2, 20 + (size - logo.height) // 2))
        return card
    except Exception as e:
        print(f"Logo fetch skipped ({slug}): {e}")
        return None

def draw_dot_grid(draw):
    for x in range(0, WIDTH, 54):
        for y in range(0, HEIGHT, 54):
            draw.ellipse([x-2, y-2, x+2, y+2], fill=DOT_COLOR)

def wrap_words(draw, words, font, max_width):
    space_w = draw.textlength(' ', font=font)
    lines, current, current_w = [], [], 0
    for w in words:
        wlen = draw.textlength(w, font=font)
        add = wlen if not current else wlen + space_w
        if current_w + add > max_width and current:
            lines.append(current); current, current_w = [w], wlen
        else:
            current.append(w); current_w += add
    if current: lines.append(current)
    return lines

def render_caption_frame(caption_text, watermark_text, scale, opacity, out_path, logo_img=None):
    img = Image.new('RGBA', (WIDTH, HEIGHT), BG_COLOR + (255,))
    draw = ImageDraw.Draw(img)
    draw_dot_grid(draw)

    if logo_img is not None:
        logo_layer = Image.new('RGBA', (WIDTH, HEIGHT), (0, 0, 0, 0))
        resized = logo_img.resize((int(logo_img.width * scale), int(logo_img.height * scale)))
        lx = (WIDTH - resized.width) // 2
        ly = int(HEIGHT * 0.32 - resized.height / 2)
        logo_layer.paste(resized, (lx, ly), resized)
        logo_alpha = logo_layer.split()[3].point(lambda p: int(p * opacity))
        logo_layer.putalpha(logo_alpha)
        img = Image.alpha_composite(img, logo_layer)

    font_bold = ImageFont.truetype(FONT_BOLD, int(FONT_SIZE * scale))
    words = [w for w in caption_text.split(' ') if w]
    lines = wrap_words(draw, words, font_bold, WIDTH - 180)

    line_h = int(FONT_SIZE * scale * 1.4)
    total_h = line_h * len(lines)
    y = (HEIGHT - total_h) / 2 + (100 if logo_img is not None else 0)

    text_layer = Image.new('RGBA', (WIDTH, HEIGHT), (0, 0, 0, 0))
    tdraw = ImageDraw.Draw(text_layer)

    word_counter = 0
    for line in lines:
        line_w = sum(tdraw.textlength(w, font=font_bold) for w in line) + tdraw.textlength(' ', font=font_bold) * (len(line) - 1)
        x = (WIDTH - line_w) / 2
        for w in line:
            ww = tdraw.textlength(w, font=font_bold)
            if word_counter == 0:
                pad = 14
                asc, desc = font_bold.getmetrics()
                box = [x - pad, y - pad * 0.4, x + ww + pad, y + asc + desc * 0.6 + pad * 0.4]
                tdraw.rounded_rectangle(box, radius=16, fill=ACCENT_COLOR + (255,))
                tdraw.text((x, y), w, font=font_bold, fill=(255, 255, 255, 255))
            else:
                tdraw.text((x, y), w, font=font_bold, fill=TEXT_COLOR + (255,))
            x += ww + tdraw.textlength(' ', font=font_bold)
            word_counter += 1
        y += line_h

    alpha = text_layer.split()[3].point(lambda p: int(p * opacity))
    text_layer.putalpha(alpha)
    img = Image.alpha_composite(img, text_layer)

    wm_font = ImageFont.truetype(FONT_REGULAR, 30)
    wdraw = ImageDraw.Draw(img)
    wm_w = wdraw.textlength(watermark_text, font=wm_font)
    wdraw.text(((WIDTH - wm_w) / 2, HEIGHT - 100), watermark_text, font=wm_font, fill=WATERMARK_COLOR)

    img.convert('RGB').save(out_path)

def get_audio_duration(audio_path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                         '-of', 'default=noprint_wrappers=1:nokey=1', audio_path],
                        capture_output=True, text=True, check=True)
    return float(r.stdout.strip())

def make_caption_segment(caption, channel_name, duration, seg_start, total_duration, work_dir, idx, out_path, logo_img=None):
    entrance_dir = f"{work_dir}/entrance_{idx}"
    os.makedirs(entrance_dir, exist_ok=True)
    for i in range(ENTRANCE_FRAMES):
        t = i / (ENTRANCE_FRAMES - 1)
        ease = 1 - (1 - t) ** 3
        render_caption_frame(caption, channel_name, 0.88 + 0.12 * ease, ease, f"{entrance_dir}/f_{i:02d}.png", logo_img=logo_img)
    held_path = f"{entrance_dir}/held.png"
    render_caption_frame(caption, channel_name, 1.0, 1.0, held_path, logo_img=logo_img)

    entrance_dur = ENTRANCE_FRAMES / FPS
    held_dur = max(duration - entrance_dur, 0.1)

    entrance_clip = f"{entrance_dir}/entrance.mp4"
    subprocess.run(['ffmpeg', '-y', '-framerate', str(FPS), '-i', f'{entrance_dir}/f_%02d.png',
                     '-frames:v', str(ENTRANCE_FRAMES), '-pix_fmt', 'yuv420p', entrance_clip], check=True)

    held_clip = f"{entrance_dir}/held.mp4"
    total_frames = max(int(held_dur * FPS), 1)
    zoom_expr = f"1+0.05*min(1,on/{total_frames})"
    bar_w = f"{WIDTH}*({seg_start}+{entrance_dur}+t)/{total_duration}"
    vf = (f"scale=2160:3840,zoompan=z='{zoom_expr}':d={total_frames}:s={WIDTH}x{HEIGHT}:fps={FPS},"
          f"drawbox=x=0:y={HEIGHT-20}:w='{bar_w}':h=8:color=0xFF6B4A@1:t=fill")
    subprocess.run(['ffmpeg', '-y', '-loop', '1', '-i', held_path, '-t', str(held_dur),
                     '-vf', vf, '-pix_fmt', 'yuv420p', held_clip], check=True)

    concat_list = f"{entrance_dir}/concat.txt"
    with open(concat_list, 'w') as f:
        f.write(f"file '{os.path.abspath(entrance_clip)}'\n")
        f.write(f"file '{os.path.abspath(held_clip)}'\n")
    subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat_list,
                     '-c', 'copy', out_path], check=True)

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--manifest', required=True)
    p.add_argument('--audio', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()

    manifest = json.load(open(args.manifest))
    captions = manifest['captions']
    channel_name = manifest.get('channel_name', 'AI Quantum').upper()

    logo_slugs = manifest.get("logo_slugs", [])
    logo_imgs = [img for img in (fetch_logo(s) for s in logo_slugs) if img is not None]
    combined_logo = logo_imgs[0] if logo_imgs else None

    total_duration = get_audio_duration(args.audio)
    seg_duration = total_duration / len(captions)

    work_dir = 'render_tmp'
    os.makedirs(work_dir, exist_ok=True)
    seg_paths = []
    elapsed = 0.0
    for i, cap in enumerate(captions):
        seg_path = f'{work_dir}/seg_{i}.mp4'
        make_caption_segment(cap, channel_name, seg_duration, elapsed, total_duration, work_dir, i, seg_path,
                              logo_img=(combined_logo if i == 0 else None))
        seg_paths.append(seg_path)
        elapsed += seg_duration

    concat_list = f'{work_dir}/concat_final.txt'
    with open(concat_list, 'w') as f:
        for sp in seg_paths:
            f.write(f"file '{os.path.abspath(sp)}'\n")

    silent = f'{work_dir}/silent.mp4'
    subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat_list,
                     '-c', 'copy', silent], check=True)
    subprocess.run(['ffmpeg', '-y', '-i', silent, '-i', args.audio,
                     '-c:v', 'copy', '-c:a', 'aac', '-shortest', args.output], check=True)
    print(f"Rendered: {args.output}")

if __name__ == '__main__':
    main()
