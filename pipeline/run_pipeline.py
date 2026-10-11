import os, re, json, time, base64, subprocess, struct
import requests
import feedparser

GEMINI_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models"
RSS_URL = "https://techcrunch.com/category/artificial-intelligence/feed/"
CHANNEL_NAME = "AI Quantum"
HANDLE = "@aiquantum"

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIO_DIR = os.path.join(REPO_ROOT, "audio")
OUTPUT_DIR = os.path.join(REPO_ROOT, "renders", "output")
RENDER_SCRIPT = os.path.join(REPO_ROOT, "render", "html_render.py")


# ---------------------------------------------------------------- Gemini

def extract_json(s):
    start = re.search(r"[{\[]", s)
    if not start:
        return s
    start = start.start()
    open_ch = s[start]
    close_ch = "}" if open_ch == "{" else "]"
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(s)):
        ch = s[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return s[start:i + 1]
    return s[start:]


def gemini_text(prompt, retries=3):
    for i in range(retries):
        r = requests.post(
            f"{GEMINI_URL}/gemini-3-flash-preview:generateContent",
            headers={"x-goog-api-key": GEMINI_KEY},
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"responseModalities": ["TEXT"]}}
        )
        if r.status_code == 200:
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            clean = re.sub(r"```json|```", "", text).strip()
            return json.loads(extract_json(clean))
        print(f"Gemini call failed ({r.status_code}), retry {i + 1}/{retries}")
        time.sleep(10)
    raise RuntimeError("Gemini call failed after retries")


def fetch_stories(covered=None):
    covered = covered or []
    done_links = {r.get("link") for r in covered if r.get("link")}
    done_titles = [r.get("headline", "") for r in covered[-15:] if r.get("headline")]
    feed = feedparser.parse(RSS_URL)
    articles = [{"title": e.title, "link": e.link, "summary": getattr(e, "summary", "")}
                for e in feed.entries[:25] if e.link not in done_links][:20]
    prompt = f"""You are a news curator for a faceless AI-news channel posting to YouTube, Facebook, and Instagram.

Here is today's list of AI-related articles as JSON:
{json.dumps(articles)}

Stories we already made videos about (do NOT pick these or follow-ups that are really the same news):
{json.dumps(done_titles)}

From this list, select the 2 or 3 most significant, genuinely newsworthy AI developments. Prioritize real product launches, model releases, research breakthroughs, or policy changes over opinion pieces, rumors, or anything not clearly about AI.

Respond with ONLY a JSON array in this exact format, no markdown, no extra text:
[{{"headline": "...", "summary": "...", "why_it_matters": "...", "source_title": "...", "source_link": "..."}}]"""
    return gemini_text(prompt)


# ---------------------------------------------------------------- script -> manifest

ICON_LIST = ("zap, cpu, shield-check, lock, globe, trending-up, clock, code, terminal, search, eye, bell, "
             "users, dollar-sign, triangle-alert, atom, check, calendar, star, sparkles, brain-circuit, rocket, "
             "bot, building-2, plug, layers, bug, key, database, scale, megaphone, flame, trophy, file-text, "
             "lightbulb, landmark, gavel, banknote, smartphone, monitor, cloud, server, network, workflow, "
             "shield-alert, target, timer, gauge, activity")

HOOK_TYPES = ["hook", "slam"]
MID_TYPES = ["terminal", "alert", "timeline", "monitor", "bignumber", "versus", "leaderboard", "chat", "quote", "checklist"]
THEMES = ["indigo", "ember", "forest", "ocean", "neon", "signal", "mint", "paper"]
TRANSITIONS = ["fade", "slide", "zoom", "wipe"]
MODE_PATTERNS = ["alternate_light", "alternate_dark", "light_then_dark", "dark_then_light"]
ANGLES = ["myth vs reality", "countdown / top 3", "who wins", "what changes for you", "red flags",
          "by the numbers", "behind the scenes", "before vs after", "the big question"]
STATE_PATH = os.path.join(REPO_ROOT, "state", "recent.json")

SCENE_SPECS = """\
hook (opening, card style): {"type":"hook","headline":"4-8 words, sentence case","word":"ONE word CAPS, max 10 chars","title":"max 14 chars","subtitle":"max 38 chars","badge":"1-2 words CAPS","icon":"<icon>","chips":["exactly 3 tags, max 16 chars each"],"narration":"..."}
slam (opening, giant words slamming in): {"type":"slam","words":["2-3 giant words, each max 9 chars"],"accent":<0-based index of the most striking word>,"sub":"max 48 chars","badge":"1-2 words CAPS","word":"ONE ghost word CAPS, max 6 chars","narration":"..."}
terminal (key facts shown as command lines): {"type":"terminal","kicker":"2-3 words CAPS","file":"fake_filename.ext","tag":"max 28 chars","lines":[{"cmd":"max 34 chars, command-style line for ONE key fact","result":"1-3 words"}  (exactly 3)],"banner":"max 46 chars","note":"max 28 chars","narration":"..."}
alert (a risk, warning or shock stat): {"type":"alert","kicker":"2-3 words CAPS","chip":"2-3 words","icon":"<icon>","big":"max 26 chars, the striking fact","quote":"max 90 chars, supporting line (attribute claims)","label":"max 40 chars","glyphs":["max 6 chars","max 6 chars"],"narration":"..."}
timeline (sequence, rollout, what happened when): {"type":"timeline","kicker":"2-3 words CAPS","steps":[{"icon":"<icon>","title":"max 22 chars","sub":"max 30 chars"}  (exactly 4)],"footnote":"max 44 chars","narration":"..."}
monitor (how something works, hidden/opaque parts, controversy): {"type":"monitor","kicker":"2-3 words CAPS","header":"max 28 chars","rows":["exactly 4 lines, max 30 chars each"],"hidden":"max 24 chars","cards":[{"icon":"<icon>","title":"max 20 chars","sub":"max 32 chars","tone":"violet|blue|red"}  (exactly 3)],"footnote":"max 50 chars","narration":"..."}
bignumber (ONE headline stat counting up): {"type":"bignumber","kicker":"2-3 words CAPS","value":"max 8 chars, e.g. 40%, $2B, 9 days, #1 - must come from the story","ring":<optional 0-100 progress-ring number, omit if not a percentage>,"caption":"max 40 chars","sub":"max 60 chars","chips":[{"icon":"<icon>","text":"max 18 chars"}  (2-3)],"narration":"..."}
versus (two sides head to head): {"type":"versus","kicker":"2-3 words CAPS","left":{"icon":"<icon>","name":"max 14 chars","points":["exactly 3, max 26 chars each"]},"right":{"icon":"<icon>","name":"max 14 chars","points":["exactly 3, max 26 chars each"]},"verdict":"max 40 chars","narration":"..."}
leaderboard (animated ranking/benchmark; ONLY with real numbers from the story): {"type":"leaderboard","kicker":"2-3 words CAPS","title":"max 30 chars","unit":"B or % or ms or empty","items":[{"name":"max 16 chars","value":<number>}  (3-5)],"footnote":"max 40 chars","narration":"..."}
chat (an illustrative conversation showing what the product does): {"type":"chat","kicker":"2-3 words CAPS","name":"max 16 chars","icon":"<icon>","status":"illustrative example","bubbles":[{"who":"user|ai","name":"max 14 chars","text":"max 60 chars"}  (3-4, alternate user/ai)],"narration":"..."}
quote (a REAL quote from the story): {"type":"quote","kicker":"2-3 words CAPS","quote":"max 120 chars","highlight":["1-2 phrases copied EXACTLY from the quote"],"who":"max 22 chars","role":"max 34 chars","icon":"users","narration":"..."}
checklist (features in/out, pros/cons, dos/don'ts): {"type":"checklist","kicker":"2-3 words CAPS","title":"max 28 chars","items":[{"text":"max 30 chars","state":"yes|no|maybe"}  (4-5)],"narration":"..."}
cta (closing, always last): {"type":"cta","kicker":"2-3 words CAPS","label":"max 26 chars","plate":"a punchy verdict about THIS story in CAPS, max 20 chars (never the channel name or a follow request)","footnote":"max 70 chars","chips":[{"icon":"<icon>","text":"max 28 chars"}  (exactly 2)],"follow":"Follow for daily AI news","narration":"ends by asking people to follow for daily AI news"}
"""

SCRIPT_PROMPT = """You are the creative director and scriptwriter of "AI Quantum", a faceless AI-news channel \
(YouTube Shorts / Instagram Reels / Facebook Reels). Each video is a 45-55 second vertical MOTION-GRAPHICS explainer \
built from animated scenes. EVERY VIDEO MUST FEEL DIFFERENT: you choose the scene sequence, storytelling angle, \
color theme and transition to fit THIS story.

Headline: <<headline>>
Summary: <<summary>>
Why it matters: <<why_it_matters>>
Source: <<source_link>>

FRAMING MENU
Scene types you can use (each at most once per video):
<<specs>>
Build the video as 6 scenes in this order:
 1. exactly one OPENING scene: "hook" or "slam"
 2-5. FOUR DIFFERENT scenes chosen from: terminal, alert, timeline, monitor, bignumber, versus, leaderboard, chat, quote, checklist - \
the ones that tell THIS story best (a funding story wants bignumber/leaderboard, a product launch wants chat/checklist/timeline, \
a controversy wants versus/monitor/alert, a security story wants alert/terminal, etc.)
 6. "cta" (always last)
Also choose:
 - "angle": the storytelling frame, one of <<angles>>. Let it shape how the narration is written.
 - "theme": one of <<themes>> (pick the mood that suits the story)
 - "transition": one of <<transitions>>
 - "mode_pattern": one of <<modes>>

VARIETY RULES - recent videos on this channel (do NOT repeat their look):
<<recent>>
Use a different opening type, a different theme, a different transition and a clearly different set of middle scenes \
from the most recent videos.

CONTENT RULES
- Use ONLY facts from the story above. Never invent numbers, quotes, dates or names. Attribute claims ("per OpenAI", "company-reported").
- A "quote" scene needs a real quote from the story; a "leaderboard" or "bignumber" needs real figures from the story. \
If the story lacks them, choose other scene types. "chat" is an illustrative example of the product, never presented as a real quote.
- Narration is spoken English: short punchy sentences, no lists, no emojis. Each scene has 2 sentences of narration \
(the cta may have 2 short sentences). Scene 1's narration opens with a hook that makes people stay (surprising fact, bold claim or question). \
Total narration across all scenes: 95-115 words (about 45 seconds spoken) - be concise.
- All on-screen text is SHORT; respect every max length.
- Icons must come ONLY from this list: <<icons>>

Return ONE JSON object (no markdown, no commentary):
{"title":"punchy title under 90 characters","description":"2-3 sentence description ending with a follow prompt and source credit",\
"hashtags":["#ai","...","8 to 10 total, no spaces"],"source_name":"publication name","angle":"...","theme":"...","transition":"...",\
"mode_pattern":"...","scenes":[ ...6 scene objects exactly as specified above, in order... ]}"""


def load_recent():
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except Exception:
        return []


def save_recent(recent, record, keep=40):
    recent = (recent + [record])[-keep:]
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(recent, f, indent=1)
    return recent


def describe_recent(recent):
    if not recent:
        return "(no previous videos yet - choose freely)"
    lines = []
    for r in recent[-4:][::-1]:
        lines.append(f"- opening={r.get('scenes', ['?'])[0]}, theme={r.get('theme')}, transition={r.get('transition')}, "
                     f"angle={r.get('angle')}, scenes={'/'.join(r.get('scenes', []))}")
    return "\n".join(lines)


def build_script_prompt(story, recent, feedback=""):
    p = SCRIPT_PROMPT
    for k, v in {
        "headline": story["headline"], "summary": story["summary"], "why_it_matters": story["why_it_matters"],
        "source_link": story["source_link"], "specs": SCENE_SPECS, "angles": ", ".join(ANGLES),
        "themes": ", ".join(THEMES), "transitions": ", ".join(TRANSITIONS), "modes": ", ".join(MODE_PATTERNS),
        "recent": describe_recent(recent), "icons": ICON_LIST,
    }.items():
        p = p.replace(f"<<{k}>>", str(v))
    if feedback:
        p += f"\n\nYour previous attempt was rejected: {feedback}\nFix this and return the full JSON again."
    return p


def validate_script(script):
    sc = script.get("scenes")
    if not isinstance(sc, list) or not (5 <= len(sc) <= 7):
        return "scenes must be a list of 6 scene objects"
    types = [x.get("type") for x in sc]
    if types[0] not in HOOK_TYPES:
        return "first scene must be hook or slam"
    if types[-1] != "cta":
        return "last scene must be cta"
    if len(set(types)) != len(types):
        return "each scene type may be used only once"
    for x in sc:
        if x.get("type") not in HOOK_TYPES + MID_TYPES + ["cta"]:
            return f"unknown scene type {x.get('type')}"
        if len(str(x.get("narration", "")).split()) < 6:
            return f"scene {x.get('type')} needs a 2-sentence narration"
    words = sum(len(str(x["narration"]).split()) for x in sc)
    if not (75 <= words <= 135):
        return f"total narration is {words} words; it must be 95-115"
    return ""


def write_script(story, recent=None, attempts=3):
    recent = recent or []
    feedback = ""
    for i in range(attempts):
        try:
            script = gemini_text(build_script_prompt(story, recent, feedback))
            err = validate_script(script)
        except Exception as e:  # noqa
            script, err = None, f"invalid JSON or call failure ({e})"
        if not err:
            return script
        print(f"[script] attempt {i + 1} rejected: {err}")
        feedback = err
    raise RuntimeError(f"could not get a valid script: {feedback}")


# ---------------------------------------------------------------- sanitizers (one per scene type)

def _clip(v, n):
    v = " ".join(str(v or "").split())
    return v if len(v) <= n else v[: n - 1].rstrip() + "..."


def _fit(lst, n, filler):
    lst = list(lst or [])[:n]
    while len(lst) < n:
        lst.append(filler)
    return lst


def _min_fit(lst, lo, hi, filler):
    lst = list(lst or [])[:hi]
    while len(lst) < lo:
        lst.append(filler)
    return lst


def _icon(v, default):
    return v if isinstance(v, str) and re.fullmatch(r"[a-z0-9-]{1,40}", v.strip().lower() or "!") else default


def _num(v):
    try:
        return float(re.sub(r"[^0-9.\-]", "", str(v)))
    except ValueError:
        return 0.0


def _san_hook(x):
    return {"headline": _clip(x.get("headline"), 60), "word": _clip(x.get("word"), 10), "title": _clip(x.get("title"), 14),
            "subtitle": _clip(x.get("subtitle"), 40), "badge": _clip(x.get("badge"), 14), "icon": _icon(x.get("icon"), "sparkles"),
            "chips": [_clip(c, 16) for c in _fit(x.get("chips"), 3, "AI news")]}


def _san_slam(x):
    words = [_clip(w, 9) for w in (x.get("words") or [])[:3]] or ["BREAKING"]
    acc = x.get("accent")
    acc = acc if isinstance(acc, int) and 0 <= acc < len(words) else len(words) - 1
    return {"words": words, "accent": acc, "sub": _clip(x.get("sub"), 50), "badge": _clip(x.get("badge"), 14),
            "word": _clip(x.get("word") or words[acc], 6)}


def _san_terminal(x):
    return {"kicker": _clip(x.get("kicker"), 28), "file": _clip(x.get("file"), 24), "tag": _clip(x.get("tag"), 30),
            "lines": [{"cmd": _clip(l.get("cmd"), 36), "result": _clip(l.get("result"), 16)}
                      for l in _fit(x.get("lines"), 3, {"cmd": "ai --news", "result": "done"})],
            "banner": _clip(x.get("banner"), 48), "note": _clip(x.get("note"), 30)}


def _san_alert(x):
    return {"kicker": _clip(x.get("kicker"), 28), "chip": _clip(x.get("chip"), 26), "icon": _icon(x.get("icon"), "triangle-alert"),
            "big": _clip(x.get("big"), 28), "quote": _clip(x.get("quote"), 100), "label": _clip(x.get("label"), 44),
            "glyphs": [_clip(g, 6) for g in _fit(x.get("glyphs"), 2, "AI")]}


def _san_timeline(x):
    return {"kicker": _clip(x.get("kicker"), 28),
            "steps": [{"icon": _icon(s.get("icon"), "clock"), "title": _clip(s.get("title"), 24), "sub": _clip(s.get("sub"), 32)}
                      for s in _fit(x.get("steps"), 4, {"icon": "clock", "title": "Next", "sub": ""})],
            "footnote": _clip(x.get("footnote"), 46)}


def _san_monitor(x):
    tones = {"violet", "blue", "red"}
    return {"kicker": _clip(x.get("kicker"), 28), "header": _clip(x.get("header"), 30),
            "rows": [_clip(r, 32) for r in _fit(x.get("rows"), 4, "...")], "hidden": _clip(x.get("hidden"), 26),
            "cards": [{"icon": _icon(c.get("icon"), "eye"), "title": _clip(c.get("title"), 22), "sub": _clip(c.get("sub"), 34),
                       "tone": c.get("tone") if c.get("tone") in tones else ["violet", "blue", "red"][i]}
                      for i, c in enumerate(_fit(x.get("cards"), 3, {"icon": "eye", "title": "Watch this", "sub": ""}))],
            "footnote": _clip(x.get("footnote"), 54)}


def _san_bignumber(x):
    out = {"kicker": _clip(x.get("kicker"), 28), "value": _clip(x.get("value"), 9) or "NEW",
           "caption": _clip(x.get("caption"), 44), "sub": _clip(x.get("sub"), 64),
           "chips": [{"icon": _icon(c.get("icon"), "star"), "text": _clip(c.get("text"), 20)}
                     for c in _min_fit(x.get("chips"), 2, 3, {"icon": "star", "text": "AI Quantum"})]}
    ring = x.get("ring")
    if ring not in (None, ""):
        out["ring"] = max(0.0, min(100.0, _num(ring)))
    return out


def _san_side(s):
    s = s or {}
    return {"icon": _icon(s.get("icon"), "star"), "name": _clip(s.get("name"), 14),
            "points": [_clip(p, 28) for p in _fit(s.get("points"), 3, "-")]}


def _san_versus(x):
    return {"kicker": _clip(x.get("kicker"), 28), "left": _san_side(x.get("left")), "right": _san_side(x.get("right")),
            "verdict": _clip(x.get("verdict"), 42)}


def _san_leaderboard(x):
    items = [{"name": _clip(i.get("name"), 16), "value": _num(i.get("value"))} for i in (x.get("items") or [])[:5]]
    items = _min_fit(items, 3, 5, {"name": "-", "value": 0})
    return {"kicker": _clip(x.get("kicker"), 28), "title": _clip(x.get("title"), 32), "unit": _clip(x.get("unit"), 4),
            "items": items, "footnote": _clip(x.get("footnote"), 44)}


def _san_chat(x):
    bubbles = []
    for i, b in enumerate((x.get("bubbles") or [])[:4]):
        bubbles.append({"who": "user" if b.get("who") == "user" else "ai", "name": _clip(b.get("name"), 14),
                        "text": _clip(b.get("text"), 64)})
    return {"kicker": _clip(x.get("kicker"), 28), "name": _clip(x.get("name"), 16) or "AI Assistant",
            "icon": _icon(x.get("icon"), "bot"), "status": _clip(x.get("status") or "illustrative example", 24),
            "bubbles": _min_fit(bubbles, 3, 4, {"who": "ai", "name": "", "text": "..."})}


def _san_quote(x):
    q = _clip(x.get("quote"), 124)
    hl = [h for h in (x.get("highlight") or [])[:2] if isinstance(h, str) and h and h in q]
    return {"kicker": _clip(x.get("kicker"), 28), "quote": q, "highlight": hl, "who": _clip(x.get("who"), 24),
            "role": _clip(x.get("role"), 36), "icon": _icon(x.get("icon"), "users")}


def _san_checklist(x):
    items = [{"text": _clip(i.get("text"), 32), "state": i.get("state") if i.get("state") in ("yes", "no", "maybe") else "yes"}
             for i in (x.get("items") or [])[:5]]
    return {"kicker": _clip(x.get("kicker"), 28), "title": _clip(x.get("title"), 30),
            "items": _min_fit(items, 4, 5, {"text": "-", "state": "maybe"})}


def _san_cta(x):
    return {"kicker": _clip(x.get("kicker"), 28), "label": _clip(x.get("label"), 28), "plate": _clip(x.get("plate"), 22),
            "footnote": _clip(x.get("footnote"), 74),
            "chips": [{"icon": _icon(c.get("icon"), "star"), "text": _clip(c.get("text"), 30)}
                      for c in _fit(x.get("chips"), 2, {"icon": "star", "text": "AI Quantum"})],
            "bell": "bell", "follow": _clip(x.get("follow") or "Follow for daily AI news", 32)}


SANITIZERS = {"hook": _san_hook, "slam": _san_slam, "terminal": _san_terminal, "alert": _san_alert, "timeline": _san_timeline,
              "monitor": _san_monitor, "bignumber": _san_bignumber, "versus": _san_versus, "leaderboard": _san_leaderboard,
              "chat": _san_chat, "quote": _san_quote, "checklist": _san_checklist, "cta": _san_cta}


def _pick(choice, allowed, avoid, seed):
    """Use Gemini's choice unless invalid or recently used; then pick deterministically from the rest."""
    if choice in allowed and choice not in avoid:
        return choice
    pool = [a for a in allowed if a not in avoid] or list(allowed)
    return pool[seed % len(pool)]


def _modes(pattern, n):
    start_dark = pattern in ("alternate_dark", "dark_then_light")
    if pattern in ("alternate_light", "alternate_dark"):
        return [("dark" if (i % 2 == 0) == start_dark else "light") for i in range(n)]
    half = n // 2
    first, second = ("dark", "light") if start_dark else ("light", "dark")
    return [first if i < half else second for i in range(n)]


def script_to_manifest(script, story=None, recent=None):
    """Gemini script -> (render manifest, voice-over text, framing record for the anti-repeat state)."""
    recent = recent or []
    seed = sum(ord(c) for c in (story or {}).get("headline", "x")) + len(recent)
    theme = _pick(script.get("theme"), THEMES, [r.get("theme") for r in recent[-3:]], seed)
    transition = _pick(script.get("transition"), TRANSITIONS, [r.get("transition") for r in recent[-2:]], seed // 3)
    pattern = _pick(script.get("mode_pattern"), MODE_PATTERNS, [], seed // 5)

    raw = script["scenes"]
    modes = _modes(pattern, len(raw))
    scenes = []
    for i, x in enumerate(raw):
        t = x["type"]
        sc = {"type": t, "mode": modes[i], **SANITIZERS[t](x), "narration": str(x["narration"]).strip()}
        scenes.append(sc)
    manifest = {"brand": {"name": CHANNEL_NAME, "icon": "atom"}, "source": script.get("source_name") or "",
                "theme": theme, "transition": transition, "scenes": scenes}
    voice = " ".join(s["narration"] for s in scenes)
    record = {"ts": time.strftime("%Y-%m-%d %H:%M"), "theme": theme, "transition": transition,
              "angle": script.get("angle"), "scenes": [s["type"] for s in scenes],
              "headline": (story or {}).get("headline", "")[:80], "link": (story or {}).get("source_link", "")}
    return manifest, voice, record


# ---------------------------------------------------------------- TTS

def gemini_tts(text, out_wav_path, retries=5):
    """Call Gemini TTS. On 429 (rate limit) wait long enough for the per-minute quota to reset."""
    for i in range(retries):
        r = requests.post(
            f"{GEMINI_URL}/gemini-3.1-flash-tts-preview:generateContent",
            headers={"x-goog-api-key": GEMINI_KEY},
            json={
                "contents": [{"parts": [{"text": text}]}],
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {
                        "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Kore"}}
                    },
                },
            },
        )
        if r.status_code == 200:
            try:
                data = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
                build_wav(base64.b64decode(data), out_wav_path)
                return out_wav_path
            except (KeyError, IndexError):
                print("TTS returned no audio, retrying")
        wait = 20 * (i + 1)
        if r.status_code == 429:
            m = re.search(r"retry in ([\d.]+)s", r.text) or re.search(r'"retryDelay":\s*"(\d+)s"', r.text)
            wait = max(wait, int(float(m.group(1))) + 5) if m else max(wait, 65)
            print(f"TTS rate-limited (429): {r.text[:200]!r}")
        print(f"TTS call failed ({r.status_code}), waiting {wait}s, retry {i + 1}/{retries}")
        time.sleep(wait)
    raise RuntimeError("Gemini TTS call failed after retries")


def build_wav(pcm_bytes, out_path, sample_rate=24000, channels=1, bits=16):
    byte_rate = sample_rate * channels * bits // 8
    block_align = channels * bits // 8
    data_size = len(pcm_bytes)
    with open(out_path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, block_align, bits))
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(pcm_bytes)


# ---------------------------------------------------------------- render + sheets

def render_video(manifest_path, audio_path, output_path):
    subprocess.run(
        ["python3", RENDER_SCRIPT, "--manifest", manifest_path, "--audio", audio_path, "--output", output_path],
        check=True, cwd=REPO_ROOT,
    )


def log_to_sheets(row):
    import gspread
    from google.oauth2.service_account import Credentials
    creds_dict = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(
        creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)
    sheet = gc.open_by_key(os.environ["GOOGLE_SHEET_ID"]).sheet1
    sheet.append_row(row)


def git_push_with_retry(message, attempts=5):
    subprocess.run(["git", "config", "user.name", "ai-quantum-bot"], cwd=REPO_ROOT, check=True)
    subprocess.run(["git", "config", "user.email", "bot@ai-quantum.local"], cwd=REPO_ROOT, check=True)
    subprocess.run(["git", "add", "renders/output", "audio", "state"], cwd=REPO_ROOT, check=True)
    status = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT, capture_output=True, text=True)
    if not status.stdout.strip():
        print("Nothing to commit.")
        return
    subprocess.run(["git", "commit", "-m", message], cwd=REPO_ROOT, check=True)
    for i in range(attempts):
        push = subprocess.run(["git", "push"], cwd=REPO_ROOT, capture_output=True, text=True)
        if push.returncode == 0:
            print("Pushed.")
            return
        print(f"Push failed, pulling and retrying ({i + 1}/{attempts})...")
        subprocess.run(["git", "pull", "--rebase"], cwd=REPO_ROOT, check=True)
        time.sleep(3)
    raise RuntimeError("git push failed after retries")


def process_story(i, story, recent_holder):
    recent = recent_holder[0]
    print(f"--- Processing story {i}: {story['headline']} ---")
    script = write_script(story, recent)
    manifest, voice_script, record = script_to_manifest(script, story, recent)
    print(f"Framing: {record['theme']} / {record['transition']} / {record['angle']} / {' > '.join(record['scenes'])}")

    stamp = time.strftime("%Y-%m-%d-%H%M%S") + f"-{i}"
    manifest_path = f"/tmp/manifest_{stamp}.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f)

    audio_path = os.path.join(AUDIO_DIR, f"{stamp}.wav")
    gemini_tts(voice_script, audio_path)

    video_path = os.path.join(OUTPUT_DIR, f"{stamp}.mp4")
    render_video(manifest_path, audio_path, video_path)

    recent = save_recent(recent, record)
    video_rel_path = os.path.relpath(video_path, REPO_ROOT)
    git_push_with_retry(f"Add rendered video {stamp}")

    repo = os.environ.get("GITHUB_REPOSITORY", "")
    video_url = f"https://github.com/{repo}/raw/main/{video_rel_path}" if repo else video_rel_path

    log_to_sheets([
        time.strftime("%Y-%m-%d %H:%M"),
        story["headline"],
        script["title"],
        script["description"],
        " ".join(script["hashtags"]),
        video_url,
        story["source_link"],
    ])
    print(f"Done: {story['headline']}")
    recent_holder[0] = recent


def main():
    os.makedirs(AUDIO_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    recent = load_recent()
    recent_holder = [recent]
    stories = fetch_stories(recent)
    print(f"Selected {len(stories)} stories")

    failures = 0
    for i, story in enumerate(stories):
        try:
            process_story(i, story, recent_holder)
        except Exception as e:
            failures += 1
            print(f"Story {i} failed, skipping: {e}")
    if failures == len(stories):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
