#!/usr/bin/env python3
import argparse, json, re, subprocess, os
from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1080, 1920
BG_COLOR = (245, 245, 243)
TEXT_COLOR = (30, 30, 30)
WATERMARK_COLOR = (150, 150, 150)
DOT_COLOR = (225, 225, 222)
FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_SIZE = 64
WATERMARK_SIZE = 32

def draw_dot_grid(draw):
    for x in range(0, WIDTH, 60):
        for y in range(0, HEIGHT, 60):
            draw.ellipse([x-2, y-2, x+2, y+2], fill=DOT_COLOR)

def parse_bold_segments(text):
    tokens = []
    for part in re.split(r'(\*\*.*?\*\*)', text):
        if not part:
            continue
        bold = part.startswith('**') and part.endswith('**')
        word_text = part[2:-2] if bold else part
        for w in word_text.split(' '):
            if w:
                tokens.append((w, bold))
    return tokens

def wrap_and_draw_caption(draw, text, font_regular, font_bold, max_width, center_y):
    tokens = parse_bold_segments(text)
    space_w = draw.textlength(' ', font=font_regular)
    lines, current, current_w = [], [], 0
    for word, bold in tokens:
        f = font_bold if bold else font_regular
        w = draw.textlength(word, font=f)
        add_w = w if not current else w + space_w
        if current_w + add_w > max_width and current:
            lines.append(current)
            current, current_w = [(word, bold, w)], w
        else:
            current.append((word, bold, w))
            current_w += add_w
    if current:
        lines.append(current)
    line_h = FONT_SIZE * 1.35
    y = center_y - (line_h * len(lines)) / 2
    for line in lines:
        line_w = sum(w for _, _, w in line) + space_w * (len(line) - 1)
        x = (WIDTH - line_w) / 2
        for word, bold, w in line:
            f = font_bold if bold else font_regular
            draw.text((x, y), word, font=f, fill=TEXT_COLOR)
            x += w + space_w
        y += line_h

def render_frame(caption_text, watermark_text, out_path):
    img = Image.new('RGB', (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)
    draw_dot_grid(draw)
    font_regular = ImageFont.truetype(FONT_REGULAR, FONT_SIZE)
    font_bold = ImageFont.truetype(FONT_BOLD, FONT_SIZE)
    wrap_and_draw_caption(draw, caption_text, font_regular, font_bold, WIDTH - 160, HEIGHT / 2)
    wm_font = ImageFont.truetype(FONT_REGULAR, WATERMARK_SIZE)
    wm_w = draw.textlength(watermark_text, font=wm_font)
    draw.text(((WIDTH - wm_w) / 2, HEIGHT - 100), watermark_text, font=wm_font, fill=WATERMARK_COLOR)
    img.save(out_path)

def get_audio_duration(audio_path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                         '-of', 'default=noprint_wrappers=1:nokey=1', audio_path],
                        capture_output=True, text=True, check=True)
    return float(r.stdout.strip())

def make_segment(frame_path, duration, out_path):
    fade = min(0.4, duration / 4)
    vf = f"fade=t=in:st=0:d={fade},fade=t=out:st={max(duration-fade,0)}:d={fade}"
    subprocess.run(['ffmpeg', '-y', '-loop', '1', '-i', frame_path, '-t', str(duration),
                     '-vf', vf, '-pix_fmt', 'yuv420p', out_path], check=True)

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--manifest', required=True)
    p.add_argument('--audio', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()

    manifest = json.load(open(args.manifest))
    captions = manifest['captions']
    channel_name = manifest.get('channel_name', 'AI Quantum')

    total_duration = get_audio_duration(args.audio)
    seg_duration = total_duration / len(captions)

    work_dir = 'render_tmp'
    os.makedirs(work_dir, exist_ok=True)
    seg_paths = []
    for i, cap in enumerate(captions):
        frame_path = f'{work_dir}/frame_{i}.png'
        seg_path = f'{work_dir}/seg_{i}.mp4'
        render_frame(cap, channel_name, frame_path)
        make_segment(frame_path, seg_duration, seg_path)
        seg_paths.append(seg_path)

    concat_list = f'{work_dir}/concat.txt'
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
