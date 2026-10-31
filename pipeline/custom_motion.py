"""Custom motion studio: Gemini writes brand-new animated scenes for each video (default 2, max 3), inspired by prompts from the
public repo yihui-dev/awesome-opus5-5-videos. Every scene is then CHECKED the way a person would check it: rendered, frames measured
(empty? text cut off? overlapping? unreadable? still moving?) and a vision pass looks at the picture. Problems go back to Gemini for up to
3 tries; a scene that never passes is dropped and the normal library scene stays. Passing scenes are saved to state/scene_library and
shown to Gemini as quality examples next time. Every failure is non-fatal.

Env: CUSTOM_MOTION=0 turns it off; CUSTOM_SCENES=1..3 (default 2); MOTION_REPO overrides the repo (owner/name)."""
import base64, io, itertools, json, os, random, re, sys, time, zlib
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


LIB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "state", "scene_library")
LIB_MAX = 40
DIRECTIONS = ["a flow diagram: things move from left/top to a result", "a before/after comparison with a clear change",
              "a number or quantity that builds up, with labelled parts", "a timeline or ordered steps that light up one by one",
              "layered cards or blocks that stack, split or merge", "a hub with parts that connect to it",
              "a simple scene of the real thing the story is about (a device, a window, a chart) being used"]

PROMPT = """You write ONE animated scene for "AI Quantum", a faceless AI-news vertical video (1080x1920). The scene lasts about <<dur>> seconds \
and accompanies this voice-over line:

NARRATION: <<narration>>
STORY: <<headline>> - <<summary>>

DESIGN DIRECTION for this scene (a starting point, adapt it to the narration): <<direction>>

INSPIRATION (prompts other creators gave an AI to make motion graphics - borrow the motion language, ideas and composition, \
do not copy their subject):
<<refs>>
<<examples>>
Make a clean, designed, meaningful visual that illustrates THE NARRATION. It must tell the viewer something, never a decorative blob. \
Use the real names, numbers and things from the narration as labels (never invent facts).

TECHNICAL CONTRACT - JavaScript body only (no HTML wrapper). You get these variables: root (an empty 940x1060 div, position:relative), \
W=940, H=1060, clamp(x) (0..1), lerp(a,b,t), E_OUT(x), E_INOUT(x) (easing on 0..1), spr(t,t0,zeta,omega) (damped spring 0..1, use zeta .6-.98).
1. Build the DOM ONCE at the top by setting root.innerHTML (inline SVG and/or absolutely positioned divs with inline styles).
2. Then define function frame(t,p,d): t = seconds since scene start, p = progress 0..1, d = duration. It must set EVERY animated property \
(transform, opacity, attributes, textContent) as a pure function of t/p - fully deterministic. Everything must be settled and readable by p=.55 and then hold COMPLETELY still (no loops, no pulsing after that).
3. Look up elements once (querySelector) outside frame. Never use setTimeout, setInterval, requestAnimationFrame, CSS animation/transition, \
Math.random (use fixed numbers), Date, fetch, images, external fonts or URLs.
4. Colours ONLY via CSS variables: var(--acc) and var(--acc2) (brand accents), #0b1020 (dark ink), #ffffff. The background is dark and already painted. \
TEXT COLOUR RULE: text is #ffffff on the dark background; use #0b1020 text ONLY on top of a light or bright shape you draw yourself. Never dark text on the dark background.
5. Tiles and cards look like soft clay: border-radius 36-46px, background:linear-gradient(180deg,color-mix(in srgb,var(--acc) 72%,#fff),var(--acc) 55%,color-mix(in srgb,var(--acc) 84%,#000)), \
box-shadow:0 26px 40px -14px rgba(0,0,0,.5),inset 0 4px 0 rgba(255,255,255,.5). Alternate var(--acc) and var(--acc2) fills.
6. Text: font-family:inherit; font-weight:800; max 4 words per label, at least 40px, NEVER end with a full stop. Keep ALL content inside the 940x1060 box with 40px margins; \
no two texts may overlap each other; leave breathing space.
7. Motion style: smooth springs and eased moves, directional, one clear focal element at a time. BANNED: shockwave rings, particle bursts, RGB split, \
camera shake, lens flares, neon glows, grid floors, flashing, bouncy overshoot.
8. Maximum 100 lines of code.
<<problems>>
Return ONLY JSON: {"title":"max 22 chars, the scene's fallback headline","code":"<the JavaScript>"}"""

VISION = """You are the art director checking ONE frame (the settled end state) of an animated scene for a vertical news video. \
The voice says: "<<narration>>". Judge only what you SEE. Fail it if any of these is true: it does not illustrate the narration; text is cut off, \
overlaps other text or shapes, or is hard to read; it looks empty, cramped or unbalanced; it is a meaningless decorative blob. \
Return ONLY JSON: {"ok":true|false,"problems":["short, concrete, fixable problems"]}"""


# ------------------------------------------------------------------ the checker (renders and measures, like a person would)

def _lum(c):
    f = lambda v: (v / 255 / 12.92) if v / 255 <= .03928 else ((v / 255 + .055) / 1.055) ** 2.4
    return .2126 * f(c[0]) + .7152 * f(c[1]) + .0722 * f(c[2])


COLLECT_JS = """
() => {
 const root=document.querySelector('.cu-root'); if(!root) return {fb:'no root',items:[],box:null};
 const rb=root.getBoundingClientRect(), cv=document.createElement('canvas').getContext('2d');
 const rgba=c=>{cv.clearRect(0,0,1,1);cv.fillStyle='#000';cv.fillStyle=c;cv.fillRect(0,0,1,1);const d=cv.getImageData(0,0,1,1).data;return [d[0],d[1],d[2],d[3]/255]};
 const out=[],w=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);let n;
 while(n=w.nextNode()){const tx=n.textContent.trim();if(!tx)continue;const el=n.parentElement,cs=getComputedStyle(el);
  if(cs.display==='none'||cs.visibility==='hidden')continue;
  let op=1,p=el;while(p&&p!==document.body){op*=parseFloat(getComputedStyle(p).opacity);p=p.parentElement;} if(op<.5)continue;
  const r=document.createRange();r.selectNodeContents(n);const b=r.getBoundingClientRect();if(b.width<4||b.height<4)continue;
  const svg=el instanceof SVGElement, col=rgba(svg?cs.fill:cs.color);if(col[3]<.3)continue;
  out.push({t:tx.slice(0,28),x:b.left,y:b.top,w:b.width,h:b.height,fs:parseFloat(cs.fontSize)||0,col:col.slice(0,3)});}
 return {fb:root.dataset.fb||'',items:out,box:[rb.left,rb.top,rb.width,rb.height],kids:root.children.length};
}"""


class Studio:
    """One headless browser for all checks of a video. Use as a context manager; check() returns (problems, png_of_settled_frame)."""

    def __init__(self, theme):
        self.theme = theme

    def __enter__(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "render"))
        import html_render as hr
        from playwright.sync_api import sync_playwright
        self.hr = hr
        self.pw = sync_playwright().start()
        self.browser = hr.launch(self.pw)
        return self

    def __exit__(self, *a):
        try:
            self.browser.close()
            self.pw.stop()
        except Exception:  # noqa
            pass

    def check(self, code, title, dur):
        from PIL import Image, ImageChops
        m = {"brand": {"name": "AI Quantum", "icon": "atom"}, "product": {}, "theme": self.theme, "transition": "fade",
             "scenes": [{"type": "custom", "mode": "dark", "title": title, "code": code, "kicker": "CHECK", "narration": "x",
                         "start": 0, "end": dur, "duration": dur}]}
        pg = self.browser.new_page(viewport={"width": 1080, "height": 1920})
        logs = []
        pg.on("console", lambda msg: logs.append(msg.text))
        pg.on("pageerror", lambda e: logs.append(str(e)))
        try:
            pg.goto("file://" + self.hr.ENGINE)
            pg.evaluate("m=>build(m)", m)
            shots = {}
            for name, p in (("early", .08), ("mid", .6), ("end", .985)):
                pg.evaluate("t=>seek(t)", dur * p)
                pg.wait_for_timeout(60)
                shots[name] = Image.open(io.BytesIO(pg.screenshot())).convert("RGB")
            info = pg.evaluate(COLLECT_JS)
            if info.get("fb"):
                return [f"the code threw an error or built nothing ({info['fb'][:120]}); fix it"], None
            x, y, w, h = [int(v) for v in info["box"]]
            box = (max(0, x), max(0, y), min(1080, x + w), min(1920, y + h))
            hide = pg.add_style_tag(content=".cu-root{visibility:hidden!important}")
            pg.evaluate("t=>seek(t)", dur * .985)
            empty = Image.open(io.BytesIO(pg.screenshot())).convert("RGB")
            pg.add_style_tag(content="*{color:transparent!important;-webkit-text-fill-color:transparent!important;text-shadow:none!important} text,tspan{fill:transparent!important}")
            pg.evaluate("e=>e.remove()", hide)
            pg.evaluate("t=>seek(t)", dur * .985)
            notext = Image.open(io.BytesIO(pg.screenshot())).convert("RGB")
        finally:
            pg.close()

        def frac(a, b, thr=28):
            d = ImageChops.difference(a.crop(box), b.crop(box)).convert("L").point(lambda v: 255 if v > thr else 0)
            hist = d.histogram()
            return hist[255] / max(1, sum(hist))

        problems = []
        if frac(shots["end"], empty) < .03:
            problems.append("the scene is almost empty: draw much more (shapes, labels, a clear focal element)")
        if frac(shots["early"], shots["mid"]) < .015:
            problems.append("nothing visibly animates between the start and p=.6: add a clear entrance and movement")
        if frac(shots["mid"], shots["end"]) > .02:
            problems.append("the scene is still moving after p=.55: everything must be settled by p=.55 and hold completely still")
        items = info["items"]
        if not items:
            problems.append("there is no readable text: add short labels taken from the narration")
        bx, by, bw, bh = info["box"]
        for it in items:
            if it["x"] < bx - 10 or it["y"] < by - 10 or it["x"] + it["w"] > bx + bw + 10 or it["y"] + it["h"] > by + bh + 10:
                problems.append(f"the text '{it['t']}' sticks out of the 940x1060 box: shorten it or move it inside")
            if it["fs"] < 30:
                problems.append(f"the text '{it['t']}' is only {it['fs']:.0f}px: use at least 40px")
        for a, b in itertools.combinations(items, 2):
            ox = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
            oy = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])
            if ox > 4 and oy > 4 and ox * oy > .25 * min(a["w"] * a["h"], b["w"] * b["h"]):
                problems.append(f"the texts '{a['t']}' and '{b['t']}' overlap: separate them")
        seen = set()
        for it in items:
            x0, y0 = max(0, int(it["x"])), max(0, int(it["y"]))
            x1, y1 = min(1080, int(it["x"] + it["w"])), min(1920, int(it["y"] + it["h"]))
            if x1 - x0 < 3 or y1 - y0 < 3:
                continue
            lums = sorted(_lum(c) for c in notext.crop((x0, y0, x1, y1)).getdata())
            bl, cl = lums[len(lums) // 2], _lum(it["col"])
            cr = (max(cl, bl) + .05) / (min(cl, bl) + .05)
            if cr < 3 and it["t"] not in seen:
                seen.add(it["t"])
                problems.append(f"the text '{it['t']}' is hard to read (contrast {cr:.1f}): white text on dark, dark text only on a light shape")
        png = io.BytesIO()
        shots["end"].crop(box).save(png, "PNG")
        return problems[:8], png.getvalue()


def vision_check(png, narration):
    """Gemini looks at the settled frame. Returns a list of problems ([] = fine, also when the call fails)."""
    try:
        import run_pipeline as rp
        r = requests.post(f"{rp.GEMINI_URL}/{rp.TEXT_MODELS[0]}:generateContent", headers={"x-goog-api-key": rp.GEMINI_KEY},
                          json={"contents": [{"parts": [{"text": VISION.replace("<<narration>>", narration[:300])},
                                                        {"inline_data": {"mime_type": "image/png", "data": base64.b64encode(png).decode()}}]}],
                                "generationConfig": {"responseModalities": ["TEXT"]}}, timeout=120)
        if r.status_code != 200:
            return []
        out = json.loads(rp.extract_json(re.sub(r"```json|```", "", r.json()["candidates"][0]["content"]["parts"][0]["text"]).strip()))
        return [] if out.get("ok", True) else [str(x)[:140] for x in (out.get("problems") or [])][:4]
    except Exception as e:  # noqa
        print(f"[studio] vision check skipped: {e}")
        return []


# ------------------------------------------------------------------ the scene library (passing scenes, shown as examples next time)

def library_examples(k=2):
    try:
        files = sorted(os.listdir(LIB_DIR))
        picks = random.sample(files, min(k, len(files)))
        out = []
        for f in picks:
            d = json.load(open(os.path.join(LIB_DIR, f)))
            out.append(f"EXAMPLE (passed every check, match this quality, never copy the subject) - narration: \"{d['narration'][:120]}\"\n{d['code'][:1800]}")
        return ("\nSCENES OF OURS THAT PASSED ALL CHECKS:\n" + "\n\n".join(out) + "\n") if out else ""
    except Exception:  # noqa
        return ""


def library_save(story, scene, got):
    try:
        os.makedirs(LIB_DIR, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", got["title"].lower()).strip("-")[:24] or "scene"
        name = f"{time.strftime('%Y%m%d')}-{slug}-{zlib.crc32(got['code'].encode()) & 0xffff:04x}.json"
        json.dump({"title": got["title"], "code": got["code"], "narration": str(scene.get("narration", "")),
                   "headline": story.get("headline", ""), "ts": time.strftime("%Y-%m-%d %H:%M")}, open(os.path.join(LIB_DIR, name), "w"))
        files = sorted(os.listdir(LIB_DIR))
        for f in files[:-LIB_MAX]:
            os.remove(os.path.join(LIB_DIR, f))
    except Exception as e:  # noqa
        print(f"[studio] could not save to library: {e}")


# ------------------------------------------------------------------ generate -> check -> fix

def make_scene(story, scene, dur, studio, direction, refs, tries=3):
    """Returns {'title','code','refs','tries'} that PASSED every check, or None."""
    import run_pipeline as rp
    base = (PROMPT.replace("<<dur>>", f"{dur:.0f}").replace("<<narration>>", str(scene.get("narration", "")))
            .replace("<<headline>>", story.get("headline", "")).replace("<<summary>>", str(story.get("summary", ""))[:400])
            .replace("<<direction>>", direction).replace("<<examples>>", library_examples())
            .replace("<<refs>>", "\n".join(f"- {r['prompt'][:700]}" for r in refs)))
    problems = []
    last = ""
    for attempt in range(tries):
        prompt = base.replace("<<problems>>", ("\nYOUR PREVIOUS ATTEMPT FAILED THESE CHECKS - fix every one, keep what worked:\n- " + "\n- ".join(problems) + "\nPrevious code:\n" + last[:3500] + "\n") if problems else "")
        try:
            out = rp.gemini_text(prompt, retries=3)
            code, title = str(out.get("code", "")), str(out.get("title", ""))
            last = code
            bad = FORBIDDEN.search(code.replace("http://www.w3.org/2000/svg", ""))
            if bad:
                problems = [f"it used the forbidden construct '{bad.group(0)}': rewrite without it"]
                print(f"[studio] try {attempt + 1}: {problems[0]}")
                continue
            if "function frame" not in code or not 200 < len(code) < 14000:
                problems = ["it must define function frame(t,p,d) and be 200-14000 characters"]
                continue
            title = re.sub(r"[.!?]+$", "", title)[:22] or "AI NEWS"
            problems, png = studio.check(code, title, dur)
            if not problems and png:
                problems = vision_check(png, str(scene.get("narration", "")))
            if not problems:
                print(f"[studio] passed on try {attempt + 1}")
                return {"title": title, "code": code, "refs": [r["slug"] for r in refs], "tries": attempt + 1}
            print(f"[studio] try {attempt + 1} failed: {problems[:3]}")
        except Exception as e:  # noqa
            problems = []
            print(f"[studio] try {attempt + 1} errored: {e}")
    return None


def add_to_manifest(manifest, story, est_scene_s=7.0):
    """Replace up to CUSTOM_SCENES middle scenes by checked custom ones (each keeps its narration, so timing is unchanged). Returns refs or []."""
    if not enabled():
        return []
    try:
        scenes = manifest["scenes"]
        idx = [i for i, s in enumerate(scenes) if s["type"] not in NO_REPLACE and not s.get("beat")]
        n = max(1, min(3, int(os.environ.get("CUSTOM_SCENES", "2"))))
        if len(idx) < 2:
            return []
        pick = (idx[1:] if len(idx) >= 3 else idx)[-n:]           # middle scenes, never the first one after the reveal
        refs_all = load_refs()
        if not refs_all:
            return []
        seed = zlib.crc32(story.get("headline", "x").encode()) + int(time.time() // 3600)
        used = []
        with Studio(manifest.get("theme", "indigo")) as studio:
            for k, i in enumerate(pick):
                refs = pick_refs(refs_all, story)
                random.Random(seed + k).shuffle(refs)
                direction = DIRECTIONS[(seed + k * 3) % len(DIRECTIONS)]
                old = scenes[i]
                got = make_scene(story, old, est_scene_s, studio, direction, refs)
                if not got:
                    print(f"[studio] scene {i + 1} ({old['type']}) kept: no custom version passed the checks")
                    continue
                scenes[i] = {"type": "custom", "mode": "dark", "title": got["title"], "code": got["code"], "narration": old["narration"]}
                library_save(story, old, got)
                used += got["refs"]
                print(f"[studio] scene {i + 1} ({old['type']}) replaced by a checked custom scene (try {got['tries']}), inspired by {got['refs']}")
        return used
    except Exception as e:  # noqa
        print(f"[studio] skipped: {e}")
        return []
