"""Explainer videos (free tutorials): the script prompt, validation and manifest builder for render/html/paper.html.

The explainer layout (hook wall, meet card, module grid, learning path, example, numbered steps with a terminal, stats,
call to action) is drawn in the AI Quantum brand look. Every command must come from the repo's README."""
import re

SPECS = """\
hook (ALWAYS scene 1, the problem/promise; a wall of chips names the things the tool covers): {"type":"hook","kicker":"2-3 words CAPS","lines":["max 14 chars","max 14 chars"],"chips":["6 to 8 real parts/features/names from the README, max 14 chars each"],"stamp":"max 24 chars, a question or bold claim","narration":"1-2 short sentences that hook the viewer"}
meet (ALWAYS scene 2, announces the tool): {"type":"meet","kicker":"2-3 words CAPS","name":"exact repo name, max 18 chars","glyph":"one of doc|bolt|robot|bug|folder|mag|star","stickers":["exactly 3 short tags, max 22 chars"],"stamp":"max 24 chars","narration":"ONE short sentence: Meet X, a free ... that ..."}
grid (what is inside: 4-10 real modules/features, two columns): {"type":"grid","kicker":"2-3 words CAPS","title":"max 16 chars","items":[{"label":"max 18 chars, a real name from the README"}],"sticker":"max 26 chars","narration":"..."}
path (a recommended order / roadmap, 3-5 steps): {"type":"path","kicker":"2-3 words CAPS","title":"max 16 chars","steps":[{"name":"max 22 chars","tag":"max 8 chars, e.g. 30 min or empty"}],"stamp":"max 26 chars","narration":"..."}
example (a file/template with a few lines and an idea > command > result flow): {"type":"example","kicker":"2-3 words CAPS","title":"max 16 chars","file":"a real file name from the README, max 20 chars","lines":["2-4 short lines, max 24 chars, the first is a title line"],"flow":["max 9 chars","max 9 chars","max 9 chars"],"stamp":"max 20 chars","sticker":"max 24 chars","narration":"..."}
step (a numbered how-to step; scenes numbered 1,2,3 (4) in order): {"type":"step","n":1,"title":"max 22 chars, imperative","terminal":[{"text":"max 46 chars, a REAL command or line from the README, commands start with $ ","kind":"cmd or out"}],"extra":<ONE of: {"type":"alts","label":"or use one of these","items":[{"text":"max 34 chars real alternative command","tag":"max 9 chars e.g. macOS"}] (1-2)} | {"type":"tree","name":"max 22 chars folder","items":["2-4 real entries, max 24 chars"]} | {"type":"move","from":"max 16 chars","to":"max 22 chars","label":"max 10 chars"} | {"type":"output","cmd":"max 16 chars the thing you run or type","lines":["exactly 4 plausible result lines, max 28 chars"],"stamp":"max 14 chars"} (output steps have NO terminal) | omit>,"narration":"1-2 short sentences that say what to do"}
stats (OPTIONAL, only when the stars number is given below; the pipeline fills the numbers): {"type":"stats","kicker":"2-3 words CAPS","title":"max 16 chars","stickers":["2-4 short facts from the README or the license, max 24 chars"],"narration":"ONE sentence about popularity and the MIT license"}
cta (ALWAYS last): {"type":"cta","kicker":"2-3 words CAPS","lines":["max 16 chars","max 14 chars"],"card":{"desc":"max 150 chars, what it is"},"sticker":"max 34 chars","narration":"2 short sentences: say the link is in the comments, then ask to follow for daily AI news"}
"""

PROMPT = """You are the scriptwriter and creative director of "AI Quantum", a faceless AI channel \
(YouTube Shorts / Instagram Reels / Facebook Reels). Make a 50-60 second vertical EXPLAINER VIDEO that teaches a viewer with no \
experience how to get this FREE open-source tool running, step by step: what it is, what is inside, how to install it, how to \
use it for the first time.

Tool: <<repo_name>> (<<stars>> GitHub stars, MIT license)
Summary: <<summary>>

SCENES (JSON objects, each with a "narration"):
<<specs>>
ORDER: 1 hook, 2 meet, then ONE or TWO of grid / path / example (what you get), then 2 to 4 "step" scenes numbered 1, 2, 3 (4) \
(install first, run last; the last step may use the "output" extra), then "stats" (optional), then "cta" last. Total 7 to 10 scenes.

CONTENT RULES
- Use ONLY facts from the README and summary below. Every command, file name, package and folder name must appear in the README; copy exact commands \
(shorten only if needed), never invent one. Say what is needed (for example Python, Node, Docker, an API key) ONLY if the README says so.
- Say honestly that the code is free and MIT licensed; do not promise anything else is free.
- Narration is a calm, friendly, spoken voice: short sentences, no lists, no emojis, say "this open source tool". Total narration 120-150 words (about 55 seconds). \
Scene 1 is EXACTLY two very short sentences (each at most 9 words) so the picture changes quickly.
- On-screen text is SHORT: respect every max length; titles and stickers never end with a full stop.
- NEVER name or credit a news outlet.

Return ONE JSON object (no markdown):
{"thumb":{"text":"2-4 WORDS, max 24 chars, a thumbnail headline that promises the tutorial (e.g. RUN X FREE, INSTALL IN 2 MIN, FREE AI TOOL)","hi":"the ONE word to highlight","gap":<optional, pick ONE: {"kind":"steps","items":["INSTALL","RUN","DONE"]} (3 words, max 9 chars) | {"kind":"number","text":"a real number from the README or the star count, max 8 chars"} | {"kind":"chyron","text":"max 26 chars, a short true line"} | omit>},"title":"punchy title under 90 characters that starts with How to","description":"2-3 sentence description ending with a follow prompt","hashtags":["#tutorial","#opensource","#howto","...","8 to 10 total, no spaces"],"scenes":[ ...scene objects exactly as specified, in order... ]}

README (the ONLY source of facts besides the summary):
<<readme>>
"""

ALLOWED = {"hook", "meet", "grid", "path", "example", "step", "stats", "cta"}
CMD_WORDS = {"git", "cd", "cp", "pip", "pip3", "npm", "npx", "pnpm", "yarn", "docker", "curl", "brew", "python", "python3", "uv", "uvx", "pipx", "make",
             "cargo", "go", "source", "export", "claude", "winget", "mkdir", "bun", "node", "chmod", "sudo", "wget", "ollama"}


def prompt(story, feedback=""):
    rp = story.get("repo") or {}
    p = PROMPT
    for k, v in {"repo_name": rp.get("full_name", ""), "stars": f"{rp.get('stars', 0):,}", "summary": story.get("summary", ""),
                 "specs": SPECS, "readme": story.get("readme") or "(no README text available)"}.items():
        p = p.replace(f"<<{k}>>", str(v))
    if feedback:
        p += f"\n\nYour previous attempt was rejected: {feedback}\nFix this and return the full JSON again."
    return p


def validate(script, story):
    sc = script.get("scenes")
    if not isinstance(sc, list) or not 6 <= len(sc) <= 11:
        return "scenes must be a list of 7 to 10 scene objects"
    types = [x.get("type") for x in sc]
    if any(t not in ALLOWED for t in types):
        return f"unknown scene type in {types}; allowed: {sorted(ALLOWED)}"
    if types[0] != "hook" or types[1] != "meet" or types[-1] != "cta":
        return "order must start hook, meet and end with cta"
    steps = [x for x in sc if x["type"] == "step"]
    if not 2 <= len(steps) <= 4:
        return "need 2 to 4 step scenes"
    if [int(x.get("n") or 0) for x in steps] != list(range(1, len(steps) + 1)):
        return "step scenes must be numbered 1, 2, 3 in order"
    if not any(t in ("grid", "path", "example") for t in types):
        return "need at least one of grid, path or example before the steps"
    if len(set(t for t in types if t != "step")) != len([t for t in types if t != "step"]):
        return "each scene type except step may be used once"
    if "stats" in types and not (story.get("repo") or {}).get("stars"):
        return "no stats scene without a star count"
    first = [s for s in re.split(r"(?<=[.!?])\s+", str(sc[0].get("narration", "")).strip()) if s]
    if len(first) < 2 or any(len(s.split()) > 11 for s in first[:2]):
        return "scene 1 narration must be two very short sentences (max 9 words each)"
    for x in sc:
        if len(str(x.get("narration", "")).split()) < 4:
            return f"scene {x.get('type')} needs narration"
    words = sum(len(str(x["narration"]).split()) for x in sc)
    if not 105 <= words <= 165:
        return f"total narration is {words} words; it must be 120-150"
    readme = (story.get("readme") or "").lower()
    cmds = []
    for x in steps:
        cmds += [l.get("text", "") for l in (x.get("terminal") or []) if isinstance(l, dict) and l.get("kind") == "cmd"]
        ex = x.get("extra") if isinstance(x.get("extra"), dict) else {}
        cmds += [i.get("text", "") for i in (ex.get("items") or []) if isinstance(i, dict)] if ex.get("type") == "alts" else []
    if readme:
        for c in cmds:
            toks = re.findall(r"[A-Za-z0-9_.\-/]{4,}", c.lstrip("$> "))
            if toks and not any(t.lower() in readme for t in toks):
                return f"the command '{c}' does not appear in the README; use only commands from the README"
    blob = str(script).lower()
    for outlet in ("techcrunch", "the verge", "wired", "reuters", "bloomberg", "venturebeat"):
        if outlet in blob:
            return f"do not mention '{outlet}'"
    return ""


def _clip(v, n):
    v = " ".join(str(v or "").split())
    return v if len(v) <= n else v[: n - 1].rstrip() + "..."


def _nofs(v, n):
    return _clip(v, n).rstrip(". ").strip()


def _list(v, lo, hi, n, filler, fn=_nofs):
    out = [fn(i, n) for i in (v or []) if str(i).strip()][:hi]
    while len(out) < lo:
        out.append(filler)
    return out


def _stars_text(n):
    n = int(n or 0)
    return (f"{n / 1000:.1f}K".replace(".0K", "K") if n >= 1000 else str(n))


def to_manifest(script, story, theme, brand="AI Quantum"):
    rp = story.get("repo") or {}
    stars = int(rp.get("stars") or 0)
    scenes = []
    for i, x in enumerate(script["scenes"]):
        t = x["type"]
        k = _nofs(x.get("kicker"), 24)
        if t == "hook":
            d = {"lines": _list(x.get("lines"), 2, 2, 16, "Free tool"), "chips": _list(x.get("chips"), 4, 8, 14, "more"), "stamp": _nofs(x.get("stamp"), 24)}
        elif t == "meet":
            owner = (rp.get("owner") or rp.get("full_name", "/").split("/")[0]) + "/"
            d = {"meet": "MEET", "owner": owner, "name": _nofs(rp.get("name") or x.get("name"), 18),
                 "glyph": x.get("glyph") if x.get("glyph") in ("doc", "bolt", "robot", "bug", "folder", "mag", "star") else "doc",
                 "stickers": _list(x.get("stickers"), 3, 3, 22, "Open source"), "stamp": _nofs(x.get("stamp"), 24)}
        elif t == "grid":
            its = [i if isinstance(i, dict) else {"label": i} for i in (x.get("items") or [])][:10]
            d = {"title": _nofs(x.get("title"), 16) or "What you get", "items": [{"n": j + 1, "label": _nofs(i.get("label"), 18) or "Item"} for j, i in enumerate(its)] or [{"n": 1, "label": "Guide"}, {"n": 2, "label": "Examples"}],
                 "sticker": _nofs(x.get("sticker"), 26)}
        elif t == "path":
            st = [i if isinstance(i, dict) else {"name": i} for i in (x.get("steps") or [])][:5]
            d = {"title": _nofs(x.get("title"), 16) or "The path", "steps": [{"name": _nofs(i.get("name"), 22) or "Step", "tag": _nofs(i.get("tag"), 8)} for i in st] or [{"name": "Start", "tag": ""}, {"name": "Build", "tag": ""}, {"name": "Share", "tag": ""}],
                 "stamp": _nofs(x.get("stamp"), 26)}
        elif t == "example":
            fl = _list(x.get("flow"), 3, 3, 9, "Result")
            d = {"title": _nofs(x.get("title"), 16) or "Example", "file": _clip(x.get("file"), 20) or "example.md", "lines": _list(x.get("lines"), 2, 4, 24, "..."),
                 "flow": fl, "stamp": _nofs(x.get("stamp"), 20), "sticker": _nofs(x.get("sticker"), 24)}
        elif t == "step":
            ex = x.get("extra") if isinstance(x.get("extra"), dict) else {}
            et = ex.get("type")
            extra = {}
            if et == "alts":
                extra = {"type": "alts", "label": _nofs(ex.get("label"), 24) or "or use one of these",
                         "items": [{"text": _clip(i.get("text"), 34), "tag": _nofs(i.get("tag"), 9)} for i in (ex.get("items") or []) if isinstance(i, dict)][:2]}
                if not extra["items"]:
                    extra = {}
            elif et == "tree":
                extra = {"type": "tree", "name": _clip(ex.get("name"), 22) or "folder/", "items": _list(ex.get("items"), 2, 4, 24, "...", _clip)}
            elif et == "move":
                extra = {"type": "move", "from": _clip(ex.get("from"), 16) or "repo", "to": _clip(ex.get("to"), 22) or "project", "label": _nofs(ex.get("label"), 10) or "done"}
            elif et == "output":
                extra = {"type": "output", "cmd": _clip(ex.get("cmd"), 16) or "run", "lines": _list(ex.get("lines"), 4, 4, 28, "Done"), "stamp": _nofs(ex.get("stamp"), 14) or "It works"}
            term = [{"text": _clip(l.get("text"), 46), "kind": "out" if l.get("kind") == "out" else "cmd"} for l in (x.get("terminal") or []) if isinstance(l, dict)][:3]
            if extra.get("type") == "output":
                term = []
            elif not term:
                term = [{"text": "$ " + rp.get("name", "run"), "kind": "cmd"}]
            d = {"n": int(x.get("n") or 1), "title": _nofs(x.get("title"), 22) or "Step", "terminal": term, "extra": extra}
        elif t == "stats":
            d = {"title": _nofs(x.get("title"), 16) or "Free & loved", "value": float(_stars_text(stars).rstrip("K")), "decimals": 1 if stars >= 1000 and not _stars_text(stars).replace("K", "").isdigit() else 0,
                 "suffix": "K" if stars >= 1000 else "", "label": "GitHub stars", "stickers": ["MIT LICENSE"] + _list(x.get("stickers"), 0, 3, 24, "")}
            d["stickers"] = [s for s in d["stickers"] if s][:4]
        else:  # cta
            cd = x.get("card") if isinstance(x.get("card"), dict) else {}
            d = {"lines": _list(x.get("lines"), 2, 2, 16, "Try it today"), "search": rp.get("full_name", ""),
                 "card": {"title": rp.get("full_name", ""), "desc": _clip(cd.get("desc"), 150), "chips": [("★ " + _stars_text(stars)) if stars else "OPEN SOURCE", "MIT"]},
                 "sticker": _nofs(x.get("sticker"), 34) or f"github.com/{rp.get('full_name', '')}"}
        scenes.append({"type": t, "kicker": k, "mode": "dark" if i % 2 == 0 else "light", "narration": str(x["narration"]).strip(), "data": d})
    return {"engine": "paper", "brand": {"name": brand}, "footer": f"Source: github.com/{rp.get('full_name', '')}", "theme": theme, "product": {}, "scenes": scenes}


def add_shot(manifest, story):
    """Insert the real GitHub page glimpse (a scrolling screenshot) right after the 'meet' scene, like the repo videos."""
    if not manifest.get("repo_shot") or any(x["type"] == "shot" for x in manifest["scenes"]):
        return manifest
    idx = next((i + 1 for i, x in enumerate(manifest["scenes"]) if x["type"] == "meet"), 1)
    manifest["scenes"].insert(idx, {"type": "shot", "kicker": "THE REAL REPO", "mode": "dark", "data": {"stamp": ""},
                                    "narration": "Here is the real GitHub page, open source and ready to use."})
    for i, x in enumerate(manifest["scenes"]):
        x["mode"] = "dark" if i % 2 == 0 else "light"
    return manifest
