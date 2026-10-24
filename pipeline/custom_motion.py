"""Custom motion scene: Gemini writes ONE brand-new animated scene per video, inspired by prompts from the
public repo yihui-dev/awesome-opus5-5-videos. Every failure is non-fatal: the video keeps its normal scenes.

Env: CUSTOM_MOTION=0 turns it off; MOTION_REPO overrides the repo (owner/name)."""
import json, os, random, re, time, zlib
import requests

REPO = os.environ.get("MOTION_REPO", "yihui-dev/awesome-opus5-5-videos")
URL = f"https://raw.githubusercontent.com/{REPO}/main/data/videos.json"
FORBIDDEN = re.compile(r"\b(fetch|XMLHttpRequest|WebSocket|import|eval|Function|localStorage|sessionStorage|cookie|location|setTimeout|"
                       r"setInterval|requestAnimationFrame|Math\.random|Date|performance|navigator|window|globalThis|constructor|"
                       r"http|https)\b|<script|<iframe|<img|<link|url\(|@import|\.animate\(|animation\s*:|transition\s*:|"
                       r"\bdocument\.(write|cookie|location|domain)|(?<![\w.])(parent|top)\.|\.style\.transition|\.style\.animation")
NO_REPLACE = {"hook", "slam", "appclutter", "repohook", "reveal", "stars", "cta", "terminal"}


def enabled():
    return os.environ.get("CUSTOM_MOTION", "1") != "0"


def load_refs():
    r = requests.get(URL, timeout=60)
    r.raise_for_status()
    out = []
    for v in r.json():
        p = str(v.get("prompt") or "")
        tags = set(v.get("tech_tags") or [])
        if v.get("category") not in ("motion", "explainer") or v.get("prompt_partial"):
            continue
        if not 60 <= len(p) <= 1100 or (tags & {"three", "threejs", "webgl", "glsl", "game"}):
            continue
        out.append({"slug": v.get("slug", ""), "prompt": " ".join(p.split())})
    return out


def pick_refs(refs, story, k=3):
    words = set(re.findall(r"[a-z]{4,}", (story.get("headline", "") + " " + story.get("summary", "")).lower()))
    rng = random.Random(zlib.crc32(story.get("headline", "x").encode()) ^ int(time.time() // 3600))
    scored = sorted(refs, key=lambda r: -(len(words & set(re.findall(r"[a-z]{4,}", r["prompt"].lower()))) + rng.random() * 2.5))
    return scored[:k]


PROMPT = """You write ONE animated scene for "AI Quantum", a faceless AI-news vertical video (1080x1920). The scene lasts about <<dur>> seconds \
and accompanies this voice-over line:

NARRATION: <<narration>>
STORY: <<headline>> - <<summary>>

INSPIRATION (prompts other creators gave an AI to make motion graphics - borrow the motion language, ideas and composition, \
do not copy their subject):
<<refs>>

Make a clean, designed, meaningful visual that illustrates THE NARRATION (a diagram, flow, comparison, counter, \
orbiting parts, morphing card, timeline... whatever fits). It must tell the viewer something, never a decorative blob.

TECHNICAL CONTRACT - JavaScript body only (no HTML wrapper). You get these variables: root (an empty 940x1060 div, position:relative), \
W=940, H=1060, clamp(x) (0..1), lerp(a,b,t), E_OUT(x), E_INOUT(x) (easing on 0..1), spr(t,t0,zeta,omega) (damped spring 0..1, use zeta .6-.98).
1. Build the DOM ONCE at the top by setting root.innerHTML (inline SVG and/or absolutely positioned divs with inline styles).
2. Then define function frame(t,p,d): t = seconds since scene start, p = progress 0..1, d = duration. It must set EVERY animated property \
(transform, opacity, attributes, textContent) as a pure function of t/p - fully deterministic. Everything should be settled and readable by p=.55 and hold still after.
3. Look up elements once (querySelector) outside frame. Never use setTimeout, setInterval, requestAnimationFrame, CSS animation/transition, \
Math.random (use fixed numbers), Date, fetch, images, external fonts or URLs.
4. Colours ONLY via CSS variables: var(--acc) and var(--acc2) (brand accents), #0b1020 (dark ink), #ffffff. Background is already dark - do not paint a full background.
5. Text: font-family:inherit; font-weight:800; max 4 words per label, at least 44px, uppercase or Sentence case, NEVER end with a full stop. \
Keep all content inside the 940x1060 box with 40px margins.
6. Motion style: smooth springs and eased moves, directional, one clear focal element. BANNED: shockwave rings, particle bursts, RGB split, \
camera shake, lens flares, neon glows, grid floors, flashing, bouncy overshoot.
7. Maximum 90 lines of code.

Return ONLY JSON: {"title":"max 22 chars, the scene's fallback headline","code":"<the JavaScript>"}"""


def make_scene(story, scene, dur):
    """Returns {'title','code'} or None."""
    import run_pipeline as rp
    refs = pick_refs(load_refs(), story)
    if not refs:
        return None
    prompt = (PROMPT.replace("<<dur>>", f"{dur:.0f}").replace("<<narration>>", str(scene.get("narration", "")))
              .replace("<<headline>>", story.get("headline", "")).replace("<<summary>>", str(story.get("summary", ""))[:400])
              .replace("<<refs>>", "\n".join(f"- {r['prompt'][:700]}" for r in refs)))
    for attempt in range(2):
        try:
            out = rp.gemini_text(prompt, retries=3)
            code, title = str(out.get("code", "")), str(out.get("title", ""))
            bad = FORBIDDEN.search(code.replace("http://www.w3.org/2000/svg", ""))
            if bad:
                print(f"[motion] rejected code (uses '{bad.group(0)}')")
                prompt += f"\n\nYour previous attempt used the forbidden construct '{bad.group(0)}'. Rewrite without it."
                continue
            if "function frame" not in code or not 200 < len(code) < 14000:
                print("[motion] rejected code (no frame() or bad size)")
                continue
            return {"title": re.sub(r"[.!?]+$", "", title)[:22] or "AI NEWS", "code": code, "refs": [r["slug"] for r in refs]}
        except Exception as e:  # noqa
            print(f"[motion] attempt {attempt + 1} failed: {e}")
    return None


def add_to_manifest(manifest, story, est_scene_s=7.0):
    """Replace one middle scene by a custom one (keeps its narration, so timing is unchanged). Returns refs or []."""
    if not enabled():
        return []
    try:
        scenes = manifest["scenes"]
        idx = [i for i, s in enumerate(scenes) if s["type"] not in NO_REPLACE]
        if len(idx) < 2:
            return []
        i = idx[-2] if len(idx) >= 3 else idx[-1]          # a middle scene, not the first one after the reveal
        got = make_scene(story, scenes[i], est_scene_s)
        if not got:
            return []
        old = scenes[i]
        scenes[i] = {"type": "custom", "mode": "dark", "title": got["title"], "code": got["code"], "narration": old["narration"]}
        print(f"[motion] scene {i + 1} ({old['type']}) replaced by a custom Gemini scene inspired by {got['refs']}")
        return got["refs"]
    except Exception as e:  # noqa
        print(f"[motion] skipped: {e}")
        return []
