"""Optional HyperFrames scenes (https://github.com/heygen-com/hyperframes, Apache 2.0).

The hook (slam) and the key-fact scene (bignumber) can be drawn by HyperFrames instead of engine.html. Each scene becomes a tiny
HTML + GSAP composition (1080x1920, 30 fps, motion rules from HyperFrames' own craft guide: long-tailed arrivals, soft motion blur,
no bounce, titles stay still), is rendered to a clip with the HyperFrames CLI and html_render.py lays the engine's brand bar,
kicker and captions over it. Everything fails soft: on any error the scene is simply drawn by the normal engine.

Needs Node 22+, Chrome and FFmpeg (all present on GitHub's ubuntu runner). Turn off with HYPERFRAMES=0.
"""
import html, json, os, re, shutil, subprocess, sys, tempfile

CLI = "hyperframes@0.8.206"
SUPPORTED = ("slam", "bignumber")
FPS = 30

THEMES = {  # copied from engine.html
    "indigo": dict(acc="#2f55e0", acc2="#22d3ee", lightbg="#f3f6fc", darkbg="#060a1a"),
    "ember": dict(acc="#e11d48", acc2="#fb923c", lightbg="#fff6f4", darkbg="#14070b"),
    "forest": dict(acc="#059669", acc2="#84cc16", lightbg="#f1fbf5", darkbg="#04120c"),
    "ocean": dict(acc="#0284c7", acc2="#22d3ee", lightbg="#eff8ff", darkbg="#031525"),
    "neon": dict(acc="#7c3aed", acc2="#ec4899", lightbg="#faf5ff", darkbg="#0b0620"),
    "signal": dict(acc="#111827", acc2="#f59e0b", lightbg="#fffbeb", darkbg="#0a0a0a"),
    "mint": dict(acc="#0d9488", acc2="#6366f1", lightbg="#effdfa", darkbg="#031a18"),
    "paper": dict(acc="#1d4ed8", acc2="#f43f5e", lightbg="#fafaf9", darkbg="#0c0a09"),
}


def enabled():
    return os.environ.get("HYPERFRAMES", "1") != "0" and bool(shutil.which("npx")) and bool(shutil.which("ffmpeg"))


def _e(v):
    return html.escape(str(v or ""), quote=True)


def _palette(theme, mode):
    T = THEMES.get(theme) or THEMES["indigo"]
    dark = mode != "light"
    return dict(bg=T["darkbg"] if dark else T["lightbg"], ink="#ffffff" if dark else "#0b1020", acc=T["acc2"] if dark else T["acc"],
                acc2=T["acc2"], sub="rgba(255,255,255,.82)" if dark else "rgba(11,16,32,.72)", chip="rgba(255,255,255,.1)" if dark else "rgba(11,16,32,.07)",
                dark=dark)


BASE_CSS = """
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:1080px;height:1920px;overflow:hidden;background:%(bg)s;font-family:'Poppins','Inter',sans-serif}
#root{position:absolute;inset:0;color:%(ink)s;background:radial-gradient(ellipse 80%% 42%% at 50%% 30%%,color-mix(in srgb,%(acc2)s 30%%,transparent),transparent 72%%),%(bg)s}
.abs{position:absolute;left:0;right:0;text-align:center}
"""


def _slam(d, p, D):
    words = [str(w).upper() for w in (d.get("words") or ["BIG", "NEWS"])][:3]
    hi = d.get("accent")
    hi = len(words) - 1 if hi is None or not isinstance(hi, int) or hi >= len(words) else hi
    n = len(words)
    size = [min(300, int(940 / max(2.2, len(w) * 0.74))) for w in words]
    size = [min(s, 300) for s in size]
    top0 = 360 if n == 3 else 440 if n == 2 else 520
    tops, y = [], top0
    for s in size:
        tops.append(y)
        y += int(s * 0.98)
    wh = "".join(f'<div class="abs w" id="w{i}" style="top:{tops[i]}px;font-size:{size[i]}px;line-height:1;font-weight:900;letter-spacing:-.03em;'
                 f'color:{p["acc"] if i == hi else p["ink"]}">{_e(w)}</div>' for i, w in enumerate(words))
    sub = f'<div class="abs" id="sub" style="top:{y + 40}px;padding:0 90px;font-size:46px;font-weight:600;color:{p["sub"]}">{_e(d.get("sub"))}</div>' if d.get("sub") else ""
    badge = (f'<div class="abs" id="badge" style="top:{y + 190}px"><span style="display:inline-block;font-size:34px;font-weight:800;letter-spacing:.18em;'
             f'padding:12px 36px;border-radius:999px;background:{p["acc2"]};color:#06101f">{_e(str(d.get("badge") or "").upper())}</span></div>') if d.get("badge") else ""
    script = f"""
const tl=gsap.timeline({{paused:true}});const D={D:.3f};
const arrive={{duration:.85,ease:"expo.out"}};
{"".join(f'tl.fromTo("#w{i}",{{opacity:0,scale:1.14,filter:"blur(18px)"}},{{opacity:1,scale:1,filter:"blur(0px)",...arrive}},{0.1 + i * 0.3:.2f});' for i in range(n))}
if(document.getElementById("sub"))tl.fromTo("#sub",{{opacity:0,y:50,filter:"blur(8px)"}},{{opacity:1,y:0,filter:"blur(0px)",...arrive}},{0.1 + n * 0.3 + 0.1:.2f});
if(document.getElementById("badge"))tl.fromTo("#badge",{{opacity:0,y:30,filter:"blur(6px)"}},{{opacity:1,y:0,filter:"blur(0px)",...arrive}},{0.1 + n * 0.3 + 0.35:.2f});
tl.to("#root > *",{{opacity:0,filter:"blur(10px)",duration:.18,ease:"power3.in"}},Math.max(.5,D-.2));
"""
    return wh + sub + badge, script


def _bignumber(d, p, D):
    val = str(d.get("value") or "").strip()
    mo = re.match(r"^(\D*?)(\d[\d,]*\.?\d*)(.*)$", val)
    pre, num, suf = (mo.group(1), mo.group(2), mo.group(3)) if mo else ("", "", val)
    decimals = len(num.split(".")[1]) if "." in num else 0
    target = float(num.replace(",", "")) if num else 0.0
    size = max(150, min(400, int(930 / max(1.0, len(val) * 0.62))))
    ring = d.get("ring")
    ring_html = ""
    if isinstance(ring, (int, float)) and 0 < ring <= 100:
        circ = 2 * 3.14159 * 400
        ring_html = (f'<svg id="ringsvg" class="abs" style="top:300px;left:140px;width:800px;height:800px" viewBox="0 0 800 800">'
                     f'<circle cx="400" cy="400" r="400" fill="none" stroke="{p["chip"]}" stroke-width="22" transform="scale(.94) translate(25 25)"/>'
                     f'<circle id="ringarc" cx="400" cy="400" r="400" fill="none" stroke="{p["acc"]}" stroke-width="22" stroke-linecap="round" '
                     f'stroke-dasharray="{circ:.1f}" stroke-dashoffset="{circ:.1f}" transform="rotate(-90 400 400) scale(.94) translate(25 25)"/></svg>')
    top = 520
    chips = d.get("chips") or []
    ch = "".join(f'<span class="chip" style="display:inline-flex;align-items:center;gap:14px;font-size:34px;font-weight:700;padding:16px 30px;border-radius:999px;'
                 f'background:{p["chip"]};margin:0 8px"><i style="display:inline-block;width:38px;height:38px;color:{p["acc"]}">{c.get("icon") or ""}</i>{_e(c.get("text"))}</span>'
                 for c in chips[:3] if isinstance(c, dict))
    body = (ring_html + f'<div class="abs" id="num" style="top:{top}px;font-size:{size}px;line-height:1;font-weight:900;letter-spacing:-.04em;color:{p["acc"]}">{_e(val)}</div>'
            f'<div class="abs" id="cap" style="top:{top + size + 30}px;padding:0 80px;font-size:54px;font-weight:700">{_e(d.get("caption"))}</div>'
            + (f'<div class="abs" id="sub" style="top:{top + size + 140}px;padding:0 100px;font-size:36px;font-weight:500;color:{p["sub"]}">{_e(d.get("sub"))}</div>' if d.get("sub") else "")
            + (f'<div class="abs" id="chips" style="top:{top + size + 260}px">{ch}</div>' if ch else ""))
    script = f"""
const tl=gsap.timeline({{paused:true}});const D={D:.3f};const o={{v:0}};
tl.fromTo("#num",{{opacity:0,filter:"blur(16px)"}},{{opacity:1,filter:"blur(0px)",duration:.7,ease:"expo.out"}},.1);
tl.to(o,{{v:{target},duration:1.0,ease:"power2.out",onUpdate:()=>{{const n=o.v.toFixed({decimals});const a=n.split(".");a[0]=Number({target})>=1000?a[0].replace(/\\B(?=(\\d{{3}})+(?!\\d))/g,","):a[0];document.getElementById("num").textContent={json.dumps(pre)}+a.join(".")+{json.dumps(suf)};}}}},.1);
if(document.getElementById("ringarc"))tl.to("#ringarc",{{strokeDashoffset:{2 * 3.14159 * 400 * (1 - (ring or 0) / 100):.1f},duration:1.2,ease:"power2.out"}},.1);
tl.fromTo("#cap",{{opacity:0,y:44,filter:"blur(8px)"}},{{opacity:1,y:0,filter:"blur(0px)",duration:.85,ease:"expo.out"}},.9);
if(document.getElementById("sub"))tl.fromTo("#sub",{{opacity:0}},{{opacity:1,duration:.6,ease:"power2.out"}},1.3);
if(document.getElementById("chips"))tl.fromTo("#chips .chip",{{opacity:0,y:30,filter:"blur(6px)"}},{{opacity:1,y:0,filter:"blur(0px)",duration:.7,ease:"expo.out",stagger:.12}},1.5);
tl.to("#root > *",{{opacity:0,filter:"blur(10px)",duration:.18,ease:"power3.in"}},Math.max(.5,D-.2));
"""
    return body, script


def composition(scene, theme, D):
    p = _palette(theme, scene.get("mode"))
    body, script = (_slam if scene["type"] == "slam" else _bignumber)(scene, p, D)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="UTF-8" />
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
<style>{BASE_CSS % p}</style></head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{D:.3f}" data-width="1080" data-height="1920">
{body}
</div>
<script>
window.__timelines = window.__timelines || {{}};
{script}
window.__timelines["main"] = tl;
</script></body></html>
"""


def render_clip(scene, theme, D, workdir):
    """Render one scene to a directory of JPEG frames (f00000.jpg ...). Returns the directory or None."""
    if scene.get("type") not in SUPPORTED:
        return None
    proj = tempfile.mkdtemp(prefix="aq_hf_", dir=workdir)
    try:
        with open(os.path.join(proj, "index.html"), "w") as f:
            f.write(composition(scene, theme, D))
        out = os.path.join(proj, "clip.mp4")
        r = subprocess.run(["npx", "--yes", CLI, "render", "--quality", "looks", "--output", out], cwd=proj, capture_output=True, text=True, timeout=420)
        if r.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) < 5000:
            print(f"[hf] render failed ({r.returncode}): {(r.stdout + r.stderr)[-500:]}", file=sys.stderr)
            return None
        fr = os.path.join(proj, "frames")
        os.makedirs(fr)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", out, "-vf", f"fps={FPS},scale=1080:1920", "-q:v", "2", os.path.join(fr, "f%05d.jpg")], check=True)
        n = len(os.listdir(fr))
        print(f"[hf] {scene['type']} rendered: {n} frames for {D:.1f}s")
        return fr if n >= int(D * FPS * 0.8) else None
    except Exception as e:  # noqa
        print(f"[hf] skipped: {e}", file=sys.stderr)
        return None
