#!/usr/bin/env python3
"""HTML motion-graphics renderer.

Takes a content manifest (scenes + narration) and the narration audio, lays the
scenes out against the audio timeline, drives render/html/engine.html with
Playwright (seek(t) per frame), and muxes the frames with the audio via ffmpeg.

Usage:
  python render/html_render.py --manifest m.json --audio a.wav --output out.mp4
  python render/html_render.py ... --stills 1,5,12 --stills-dir /tmp/stills   # debug frames only
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(HERE, "html", "engine.html")
ICON_DIR = os.path.join(HERE, "icons")
FPS = 30
TAIL = 0.6  # seconds of video after the narration ends

# ---------------------------------------------------------------- icons (Lucide, ISC licence)
_A = 'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'


def _svg(body):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" {_A}>{body}</svg>'


BUILTIN = {
    "zap": '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/>',
    "lock": '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    "shield-check": '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
    "cpu": '<rect width="16" height="16" x="4" y="4" rx="2"/><rect width="6" height="6" x="9" y="9" rx="1"/><path d="M15 2v2M15 20v2M2 15h2M2 9h2M20 15h2M20 9h2M9 2v2M9 20v2"/>',
    "globe": '<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/>',
    "trending-up": '<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "code": '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
    "terminal": '<polyline points="4 17 10 11 4 5"/><line x1="12" x2="20" y1="19" y2="19"/>',
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "eye": '<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/><circle cx="12" cy="12" r="3"/>',
    "bell": '<path d="M10.268 21a2 2 0 0 0 3.464 0"/><path d="M3.262 15.326A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.673C19.41 13.956 18 12.499 18 8A6 6 0 0 0 6 8c0 4.499-1.411 5.956-2.738 7.326"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "dollar-sign": '<line x1="12" x2="12" y1="2" y2="22"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>',
    "triangle-alert": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "atom": '<circle cx="12" cy="12" r="1"/><path d="M20.2 20.2c2.04-2.03.02-7.36-4.5-11.9-4.54-4.52-9.87-6.54-11.9-4.5-2.04 2.03-.02 7.36 4.5 11.9 4.54 4.52 9.87 6.54 11.9 4.5Z"/><path d="M15.7 15.7c4.52-4.54 6.54-9.87 4.5-11.9-2.03-2.04-7.36-.02-11.9 4.5-4.52 4.54-6.54 9.87-4.5 11.9 2.03 2.04 7.36.02 11.9-4.5Z"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "calendar": '<path d="M8 2v4M16 2v4"/><rect width="18" height="18" x="3" y="4" rx="2"/><path d="M3 10h18"/>',
    "star": '<path d="M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z"/>',
    "sparkles": '<path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/><path d="M20 3v4M22 5h-4M4 17v2M5 18H3"/>',
}
FALLBACK = _svg(BUILTIN['sparkles'])
_icon_cache = {}


def icon_svg(name):
    """Return inline SVG markup for a Lucide icon name (builtin -> local file -> jsdelivr -> fallback)."""
    name = (name or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9-]{1,40}", name):
        return FALLBACK
    if name in _icon_cache:
        return _icon_cache[name]
    svg = None
    if name in BUILTIN:
        svg = _svg(BUILTIN[name])
    else:
        local = os.path.join(ICON_DIR, name + ".svg")
        if os.path.exists(local):
            svg = open(local).read()
        else:
            try:
                url = f"https://cdn.jsdelivr.net/npm/lucide-static@0.468.0/icons/{name}.svg"
                svg = urllib.request.urlopen(url, timeout=8).read().decode()
                os.makedirs(ICON_DIR, exist_ok=True)
                open(local, "w").write(svg)
            except Exception as e:  # noqa
                print(f"[icons] could not fetch '{name}': {e}; using fallback", file=sys.stderr)
    svg = svg or FALLBACK
    svg = re.sub(r"<svg[^>]*>", lambda mo: re.sub(r'\s(width|height)="[^"]*"', "", mo.group(0)), svg, count=1)
    _icon_cache[name] = svg
    return svg


def resolve_icons(obj):
    """Replace every `icon`/`bell` value (a Lucide name) with inline SVG."""
    if isinstance(obj, dict):
        return {k: (icon_svg(v) if k in ("icon", "bell") and isinstance(v, str) else resolve_icons(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_icons(x) for x in obj]
    return obj


# ---------------------------------------------------------------- audio timing
def probe_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nk=1:nw=1", path], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def detect_silences(path, noise="-32dB", d=0.18):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af",
                        f"silencedetect=noise={noise}:d={d}", "-f", "null", "-"],
                       capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    sil = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else None
        sil.append((s, e))
    return sil


def split_sentences(text):
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return [p for p in parts if p]


def weight(s):
    return len(s) + 5 * len(re.findall(r"[,;:.!?]", s))


def chunk_caption(sentence, max_words=7):
    words = sentence.split()
    if len(words) <= max_words + 1:
        return [sentence]
    n = -(-len(words) // max_words)
    size = -(-len(words) // n)
    return [" ".join(words[i:i + size]) for i in range(0, len(words), size)]


def plan_timeline(scenes, audio_path):
    dur = probe_duration(audio_path)
    sil = detect_silences(audio_path)
    speech_start, speech_end = 0.0, dur
    if sil and sil[0][0] <= 0.05 and sil[0][1] is not None:
        speech_start = sil[0][1]
    if sil and sil[-1][1] is None:
        speech_end = sil[-1][0]
    elif sil and abs(sil[-1][1] - dur) < 0.1:
        speech_end = sil[-1][0]
    speech_start = min(speech_start, 1.0)
    mids = [(s + (e if e is not None else dur)) / 2 for s, e in sil if s > speech_start + 0.2 and s < speech_end - 0.2]

    sents = []  # (scene_idx, text, weight)
    for i, sc in enumerate(scenes):
        for t in split_sentences(sc.get("narration", "")):
            sents.append((i, t, weight(t)))
    if not sents:
        raise SystemExit("no narration text in manifest")
    total_w = sum(w for _, _, w in sents)
    span = max(0.5, speech_end - speech_start)
    bounds = [speech_start]
    acc = 0
    for _, _, w in sents:
        acc += w
        bounds.append(speech_start + span * acc / total_w)
    bounds[-1] = speech_end
    # snap interior boundaries to nearest detected pause (monotonic)
    prev = speech_start
    for k in range(1, len(bounds) - 1):
        cands = [m for m in mids if abs(m - bounds[k]) <= 1.1 and m > prev + 0.6]
        if cands:
            bounds[k] = min(cands, key=lambda m: abs(m - bounds[k]))
        bounds[k] = max(bounds[k], prev + 0.6)
        prev = bounds[k]

    total = dur + TAIL
    # scene starts
    first_idx = {}
    for k, (si, _, _) in enumerate(sents):
        first_idx.setdefault(si, k)
    starts = []
    for i in range(len(scenes)):
        starts.append(0.0 if i == 0 else max(0.0, bounds[first_idx[i]] - 0.12))
    ends = starts[1:] + [total]
    for i, sc in enumerate(scenes):
        sc["start"], sc["end"] = round(starts[i], 3), round(ends[i], 3)

    caps = []
    for k, (si, text, w) in enumerate(sents):
        a, b = bounds[k], bounds[k + 1]
        chunks = chunk_caption(text)
        cw = [max(1, len(c)) for c in chunks]
        tot = sum(cw)
        t0 = a
        for c, wc in zip(chunks, cw):
            t1 = t0 + (b - a) * wc / tot
            caps.append([round(t0 + 0.02, 3), round(t1 - 0.02, 3), c])
            t0 = t1
    return total, caps


# ---------------------------------------------------------------- capture
def launch(p):
    args = ["--no-sandbox", "--font-render-hinting=none", "--hide-scrollbars"]
    try:
        return p.chromium.launch(args=args)
    except Exception:
        for path in ("/opt/pw-browsers/chromium/chrome", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"):
            if os.path.exists(path):
                return p.chromium.launch(args=args, executable_path=path)
        raise


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--audio", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--stills", default="")
    ap.add_argument("--stills-dir", default="/tmp/stills")
    a = ap.parse_args()

    m = json.load(open(a.manifest))
    m = resolve_icons(m)
    total, caps = plan_timeline(m["scenes"], a.audio)
    m["captions"] = caps
    m["total"] = total
    print(f"[html_render] duration {total:.1f}s, scenes: " +
          ", ".join(f"{s['type']}@{s['start']:.1f}-{s['end']:.1f}" for s in m["scenes"]))

    # music bed + scene sound effects under the voice (synthesized, licence-free); falls back to voice only
    audio_in = a.audio
    tmp_audio = ""
    if os.environ.get("MUSIC", "1") != "0" and not a.stills:
        try:
            sys.path.insert(0, HERE)
            import soundtrack
            tmp_audio = tempfile.mkdtemp(prefix="aq_snd_")
            audio_in = soundtrack.mix(m, total, a.audio, os.path.join(tmp_audio, "mix.wav"))
            print("[html_render] soundtrack mixed:", audio_in)
        except Exception as e:  # noqa
            print(f"[html_render] soundtrack skipped ({e}); using voice only")
            audio_in = a.audio

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = launch(p)
        page = browser.new_page(viewport={"width": 1080, "height": 1920}, device_scale_factor=1)
        page.goto("file://" + ENGINE)
        page.evaluate("m => build(m)", m)
        page.evaluate("document.fonts.ready.then(()=>{window.refit&&window.refit();return true;})")

        if a.stills:
            os.makedirs(a.stills_dir, exist_ok=True)
            for t in [float(x) for x in a.stills.split(",")]:
                page.evaluate("t => seek(t)", t)
                page.screenshot(path=os.path.join(a.stills_dir, f"t{t:05.1f}.jpg"), type="jpeg", quality=90)
            browser.close()
            return

        os.makedirs(os.path.dirname(os.path.abspath(a.output)), exist_ok=True)
        ff = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS),
             "-c:v", "mjpeg", "-i", "-", "-i", audio_in,
             "-map", "0:v", "-map", "1:a", "-af", "apad",
             "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS),
             "-c:a", "aac", "-b:a", "160k", "-t", f"{total:.3f}", "-movflags", "+faststart", a.output],
            stdin=subprocess.PIPE)
        n = int(total * FPS)
        for i in range(n):
            page.evaluate("t => seek(t)", i / FPS)
            ff.stdin.write(page.screenshot(type="jpeg", quality=90))
            if i % 150 == 0:
                print(f"[html_render] frame {i}/{n}", flush=True)
        ff.stdin.close()
        if ff.wait() != 0:
            raise SystemExit("ffmpeg failed")
        if tmp_audio:
            shutil.rmtree(tmp_audio, ignore_errors=True)
        browser.close()
    print("[html_render] wrote", a.output)


if __name__ == "__main__":
    main()
