import os, re, sys, json, time, base64, subprocess, struct
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


TEXT_MODELS = ["gemini-3-flash-preview", "gemini-3-flash-preview", "gemini-3-flash-preview",
               "gemini-2.5-flash", "gemini-2.5-flash", "gemini-3-flash-preview"]


def gemini_text(prompt, retries=6):
    """JSON text call. Rides out 503/429 overload with growing waits and a fallback model."""
    waits = [15, 30, 60, 90, 120, 120]
    for i in range(retries):
        model = TEXT_MODELS[min(i, len(TEXT_MODELS) - 1)]
        try:
            r = requests.post(
                f"{GEMINI_URL}/{model}:generateContent",
                headers={"x-goog-api-key": GEMINI_KEY},
                json={"contents": [{"parts": [{"text": prompt}]}],
                      "generationConfig": {"responseModalities": ["TEXT"]}},
                timeout=180,
            )
            if r.status_code == 200:
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                clean = re.sub(r"```json|```", "", text).strip()
                return json.loads(extract_json(clean))
            print(f"Gemini call failed ({r.status_code}, {model}), retry {i + 1}/{retries}")
        except (requests.RequestException, KeyError, IndexError, ValueError) as e:
            print(f"Gemini call error ({type(e).__name__}, {model}), retry {i + 1}/{retries}")
        if i < retries - 1:
            time.sleep(waits[min(i, len(waits) - 1)])
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


# ---------------------------------------------------------------- viral MIT-licensed GitHub repos

GITHUB_VIDEOS = int(os.environ.get("GITHUB_VIDEOS", "1"))   # how many repo videos per run
TOTAL_VIDEOS = int(os.environ.get("TOTAL_VIDEOS", "3"))
AI_WORDS = re.compile(r"\b(ai|llm|llms|gpt|agent|agents|agentic|rag|mcp|ml|machine.learning|deep.learning|neural|"
                      r"transformer|diffusion|openai|claude|gemini|ollama|copilot|embedding|inference|prompt|chatbot|"
                      r"vision|speech|whisper|langchain|model|models|automation)\b", re.I)


def _gh_headers(raw=False):
    h = {"Accept": "application/vnd.github.raw+json" if raw else "application/vnd.github+json",
         "User-Agent": "ai-quantum-pipeline"}
    if os.environ.get("GITHUB_TOKEN"):
        h["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    return h


def parse_trending(html):
    """owner/name pairs in page order from github.com/trending HTML."""
    names = re.findall(r'<h2 class="h3 lh-condensed">\s*<a[^>]*href="/([\w.\-]+/[\w.\-]+)"', html)
    if not names:  # layout changed: fall back to any repo-looking article link
        names = re.findall(r'<article[^>]*>.*?href="/([\w.\-]+/[\w.\-]+)"', html, re.S)
    seen, out = set(), []
    for n in names:
        if n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out


SKIP_SECTIONS = re.compile(r"sponsor|contribut|license|licence|star history|acknowledg|changelog|roadmap|faq|support|"
                           r"community|follow|credits|authors|citation|translations?|table of contents", re.I)
KEEP_SECTIONS = re.compile(r"quick ?start|getting started|install|usage|how it works|how to|features|what you get|"
                           r"architecture|overview|examples?|why|pipelines?|requirements|prerequisites|demo|commands", re.I)


def clean_readme(text, limit=7000):
    """README -> compact plain text: no HTML/badges/images/sponsor blocks, key sections first."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"<details[^>]*>.*?</details>", lambda m: m.group(0) if not SKIP_SECTIONS.search(m.group(0)[:300]) else "",
                  text, flags=re.S)
    text = re.sub(r"\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)|!\[[^\]]*\]\([^)]*\)|<img[^>]*>|<picture>.*?</picture>", "", text, flags=re.S)
    text = re.sub(r"</?(p|div|a|table|tr|td|th|tbody|thead|sub|sup|em|strong|b|i|center|br|summary|details|source|picture)[^>]*>", " ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    parts = re.split(r"(?m)^(?=#{1,3} )", text)
    intro, secs = [], []
    for part in parts:
        head = (part.splitlines() or [""])[0]
        if not head.startswith("#"):
            intro.append(part)
        elif SKIP_SECTIONS.search(head):
            continue
        else:
            secs.append((0 if KEEP_SECTIONS.search(head) else 1, part))
    secs.sort(key=lambda x: x[0])          # stable: keeps README order inside each group
    out = "\n".join(intro[:1])[:900] + "\n" + "\n".join(p for _, p in secs)
    out = re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]{2,}", " ", out)).strip()
    return out[:limit]


def repo_to_story(d, readme):
    desc = (d.get("description") or "").strip()
    owner = d.get("owner") or {}
    return {
        "kind": "repo",
        "headline": f"{d['name']}: {desc}"[:110] if desc else d["name"],
        "summary": f"{d['full_name']} - {desc}. {d.get('stargazers_count', 0):,} GitHub stars, language: "
                   f"{d.get('language') or 'n/a'}, license: MIT, topics: {', '.join((d.get('topics') or [])[:8])}.",
        "why_it_matters": "A trending open-source project under the MIT license: free to use, modify and ship in your own products.",
        "source_link": d["html_url"],
        "readme": clean_readme(readme or ""),
        "repo": {"full_name": d["full_name"], "name": d["name"], "stars": d.get("stargazers_count", 0),
                 "language": d.get("language") or "", "owner_type": owner.get("type", ""), "avatar": owner.get("avatar_url", ""),
                 "owner": owner.get("login", "")},
    }


def fetch_github_repos(covered, count):
    """Pick `count` fresh, viral, MIT-licensed repos (AI/dev-tool related first)."""
    if count <= 0:
        return []
    done = {(r.get("link") or "").lower() for r in covered}
    cands = []
    try:
        r = requests.get("https://github.com/trending?since=daily", headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        if r.status_code == 200:
            cands += parse_trending(r.text)
        r = requests.get("https://github.com/trending?since=weekly", headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        if r.status_code == 200:
            cands += [n for n in parse_trending(r.text) if n not in cands]
    except Exception as e:  # noqa
        print(f"[github] trending page failed: {e}")
    details = []
    for full in dict.fromkeys(cands):
        if f"https://github.com/{full}".lower() in done:
            continue
        try:
            r = requests.get(f"https://api.github.com/repos/{full}", headers=_gh_headers(), timeout=30)
            if r.status_code == 200:
                details.append(r.json())
        except Exception as e:  # noqa
            print(f"[github] {full} failed: {e}")
        if len(details) >= 40:
            break
    try:  # also: recently created, fast-rising MIT repos via the search API
        since = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 21 * 86400))
        r = requests.get("https://api.github.com/search/repositories", headers=_gh_headers(), timeout=30,
                         params={"q": f"license:mit created:>{since} stars:>300", "sort": "stars", "order": "desc", "per_page": 30})
        if r.status_code == 200:
            known = {d["full_name"].lower() for d in details}
            details += [d for d in r.json().get("items", []) if d["full_name"].lower() not in known
                        and d["html_url"].lower() not in done]
    except Exception as e:  # noqa
        print(f"[github] search failed: {e}")
    good = [d for d in details if (d.get("license") or {}).get("spdx_id") == "MIT" and not d.get("archived")
            and not d.get("fork") and d["html_url"].lower() not in done and (d.get("description") or "").strip()]
    ai = lambda d: bool(AI_WORDS.search(" ".join([d.get("description") or "", " ".join(d.get("topics") or []), d["name"]])))
    good.sort(key=lambda d: (not ai(d)))          # AI-related first, trending order kept inside each group
    stories = []
    for d in good[:count]:
        readme = ""
        try:
            r = requests.get(f"https://api.github.com/repos/{d['full_name']}/readme", headers=_gh_headers(raw=True), timeout=30)
            if r.status_code == 200:
                readme = r.text
        except Exception as e:  # noqa
            print(f"[github] readme failed: {e}")
        stories.append(repo_to_story(d, readme))
    print(f"[github] selected {[s['repo']['full_name'] for s in stories]}")
    return stories


REPO_MODE = """

ADDITIONAL INSTRUCTIONS FOR THIS VIDEO - it is a GITHUB REPO EXPLAINER (these override earlier rules where they conflict)
The story is a viral, MIT-licensed open-source project on GitHub: <<repo_name>> (<<stars>> stars). Teach viewers three things, in this order:
 1. WHAT it is and why it is going viral (hook first).
 2. HOW IT WORKS - the idea/architecture in plain words, using only the README below.
 3. HOW TO USE IT - the real install/run steps. Say it is free and MIT licensed.
Scene order is FIXED for repo videos: scene 1 "repohook" (a glimpse of its GitHub page; narration starts "This GitHub repo ..."; ignore the opening-type variety rule), scene 2 "reveal" (announce the repo's name), then three more scenes, then cta. Scene choices: use "terminal" for the install/run commands (copy exact commands from the README, shorten only if needed, never invent one; if the README has \
no commands, use "checklist" for key features instead), "timeline" or "hubmap" for how it works / the steps, plus "profile", "checklist", "bignumber" (only for the star count) as fits; "stack" (2-3 key features or steps as glass cards) is great for explaining. \
Narration says "this open source project", never "article" or "report". Do not name any news outlet. Hashtags must include #opensource and #github.

README (the ONLY source of facts besides the summary above):
<<readme>>
"""


def fetch_repo_logo(story):
    """Org avatar for organisations; the GitHub mark for individual owners (no personal photos)."""
    repo = story.get("repo") or {}
    urls = []
    if repo.get("owner_type") == "Organization" and repo.get("avatar"):
        urls.append(repo["avatar"] + ("&" if "?" in repo["avatar"] else "?") + "s=256")
    urls.append("https://cdn.simpleicons.org/github")
    for u in urls:
        try:
            r = requests.get(u, timeout=15)
            ctype = (r.headers.get("content-type") or "").split(";")[0].strip()
            if r.status_code == 200 and len(r.content) > 200 and ctype.startswith("image/"):
                return f"data:{ctype};base64," + base64.b64encode(r.content).decode()
        except Exception as e:  # noqa
            print(f"[logo] {u} failed: {e}")
    return ""


# ---------------------------------------------------------------- script -> manifest

ICON_LIST = ("zap, cpu, shield-check, lock, globe, trending-up, clock, code, terminal, search, eye, bell, "
             "users, dollar-sign, triangle-alert, atom, check, calendar, star, sparkles, brain-circuit, rocket, "
             "bot, building-2, plug, layers, bug, key, database, scale, megaphone, flame, trophy, file-text, "
             "lightbulb, landmark, gavel, banknote, smartphone, monitor, cloud, server, network, workflow, "
             "shield-alert, target, timer, gauge, activity, message-circle, shopping-cart, house, list-checks, moon, sun, "
             "book-open, calendar-check, mail, send, app-window")

HOOK_TYPES = ["hook", "slam", "appclutter"]
REPO_HOOK = "repohook"
MID_TYPES = ["terminal", "alert", "timeline", "monitor", "bignumber", "versus", "leaderboard", "chat", "quote", "checklist",
             "profile", "hubmap", "roundup", "reveal", "phases", "cycle", "stars",
             "morph", "bars", "command", "tabs", "prompt", "stack", "orbit"]
THEMES = ["indigo", "ember", "forest", "ocean", "neon", "signal", "mint", "paper"]
TRANSITIONS = ["fade", "slide", "zoom", "wipe", "panel"]
MODE_PATTERNS = ["alternate_light", "alternate_dark", "light_then_dark", "dark_then_light"]
ANGLES = ["myth vs reality", "countdown / top 3", "who wins", "what changes for you", "red flags",
          "by the numbers", "behind the scenes", "before vs after", "the big question",
          "problem, solution, 3 steps, proof"]
STATE_PATH = os.path.join(REPO_ROOT, "state", "recent.json")

# One "style pack" per video: the explanation scenes come mostly from the pack's set, with its own theme family, transition and
# light/dark rhythm. The signature parts (opening, reveal with logo, cta, thumbnail) stay the same in every pack.
STYLE_PACKS = {
    "Terminal Ops":     {"mid": ["terminal", "command", "prompt", "checklist", "phases", "morph"], "themes": ["neon", "forest"], "transition": "wipe", "mode": "alternate_dark"},
    "Data Story":       {"mid": ["bignumber", "bars", "leaderboard", "versus", "monitor"], "themes": ["ocean", "signal"], "transition": "slide", "mode": "light_then_dark"},
    "Editorial": {"mid": ["quote", "stack", "tabs", "alert", "bars"], "themes": ["ember", "paper"], "transition": "panel", "mode": "alternate_light"},
    "Product Keynote":  {"mid": ["profile", "stack", "orbit", "morph", "tabs"], "themes": ["indigo", "mint"], "transition": "zoom", "mode": "dark_then_light"},
    "Conversation":     {"mid": ["chat", "prompt", "quote", "versus", "command", "morph"], "themes": ["mint", "ocean"], "transition": "fade", "mode": "alternate_light"},
    "Systems Map":      {"mid": ["hubmap", "orbit", "cycle", "timeline", "phases", "stack"], "themes": ["forest", "indigo"], "transition": "slide", "mode": "alternate_dark"},
    "Playbook Steps":   {"mid": ["phases", "timeline", "checklist", "tabs", "roundup", "morph"], "themes": ["signal", "paper"], "transition": "wipe", "mode": "alternate_light"},
    "Alert Room":       {"mid": ["alert", "monitor", "versus", "bignumber", "command"], "themes": ["ember", "neon"], "transition": "zoom", "mode": "dark_then_light"},
}
TUTORIAL_VIDEOS = int(os.environ.get("TUTORIAL_VIDEOS", "1"))   # how many "how to install and use it free" videos per run
KINDS_WITH_REPO = ("repo", "tutorial")


def pick_pack(recent, kind="news"):
    """Least recently used style pack (tutorials skip the news-only packs)."""
    names = [n for n in STYLE_PACKS if kind != "tutorial" or n in ("Terminal Ops", "Product Keynote", "Systems Map", "Playbook Steps", "Editorial")]
    last = {}
    for i, r in enumerate(recent):
        if r.get("pack"):
            last[r["pack"]] = i
    return min(names, key=lambda n: (last.get(n, -1), names.index(n)))


def pack_rule(pack, kind):
    if not pack:
        return ""
    mid = STYLE_PACKS[pack]["mid"]
    need = "AT LEAST THREE of the four" if kind == "news" else ("AT LEAST TWO of the three" if kind == "repo" else "AT LEAST TWO of the middle")
    return (f"\n STYLE PACK for THIS video: \"{pack}\". {need} explanation scenes (everything except the opening, reveal, terminal and cta) MUST be "
            f"chosen from: {', '.join(mid)}. Pick the ones that fit the story and order them so the video builds. "
            f"(Theme, transition and light/dark rhythm are assigned automatically by the pack; still fill those fields.)")


REPOHOOK_SPEC = """\
repohook (ONLY for GitHub repo videos, ALWAYS scene 1: the screen opens on a glimpse of the repo's real GitHub page under the words "THIS GITHUB REPO" + your headline): {"type":"repohook","headline":"max 56 chars, lowercase start, COMPLETES the sentence 'This GitHub repo ...' with the single most surprising thing it does, e.g. turns any PDF into a podcast","narration":"2 sentences. MUST begin with the exact words 'This GitHub repo' and finish the hook, e.g. 'This GitHub repo turns any PDF into a podcast. And it is completely free.'"}
"""

SCENE_SPECS = """\
hook (opening, card style): {"type":"hook","headline":"4-8 words, sentence case","word":"ONE word CAPS, max 10 chars","title":"max 14 chars","subtitle":"max 38 chars","badge":"1-2 words CAPS","icon":"<icon>","chips":["exactly 3 tags, max 16 chars each"],"narration":"..."}
slam (opening, giant words slamming in): {"type":"slam","words":["2-3 giant words, each max 9 chars"],"accent":<0-based index of the most striking word>,"sub":"max 48 chars","badge":"1-2 words CAPS","word":"ONE ghost word CAPS, max 6 chars","narration":"..."}
appclutter (opening, "too many apps -> just one simple thing" metaphor; best for products that replace/simplify apps or live inside chat): {"type":"appclutter","before":"max 34 chars, the pain, e.g. Another app to download?","after":"max 24 chars, the relief, e.g. Just send a text.","user":"max 40 chars illustrative request","ai":"max 24 chars illustrative reply","narration":"..."}
reveal (NAME REVEAL right after the opening: announces the real name of the tool/product/model/repo the story is about; its narration is ONE short sentence like "Meet X, a free tool that ..."): {"type":"reveal","kicker":"2-3 words CAPS","meet":"1-2 words CAPS e.g. MEET or INTRODUCING","name":"max 18 chars, the exact name","tagline":"max 58 chars, what it does","badges":["2-3 short tags CAPS max 14 chars, e.g. OPEN SOURCE, MIT LICENSE, FREE"],"icon":"<icon>","narration":"one short sentence naming it"}
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
profile (spotlight ONE product/agent/model: name, where it lives, what it does): {"type":"profile","kicker":"2-3 words CAPS","name":"max 12 chars","icon":"<icon>","tag":"max 34 chars","pills":["2-3 platforms/tags, max 12 chars each"],"tagline":"max 40 chars","cards":[{"icon":"<icon>","title":"max 20 chars","sub":"max 32 chars"}  (exactly 2, concrete things it does)],"narration":"..."}
hubmap (one central thing connected to 3 parts + a summary card): {"type":"hubmap","kicker":"2-3 words CAPS","icon":"<icon>","hub":"max 16 chars","nodes":[{"icon":"<icon>","label":"max 12 chars"}  (exactly 3)],"card":{"title":"max 26 chars","rows":[{"icon":"<icon>","text":"max 30 chars"}  (exactly 3)]},"narration":"..."}
roundup (3 items announced, 'three more X', numbered cards sliding in): {"type":"roundup","title":"max 22 chars","sub":"max 30 chars","items":[{"name":"max 12 chars","icon":"<icon>","sub":"max 34 chars"}  (exactly 3)],"narration":"..."}
phases (a process in 3-4 ordered steps, cards stacking top to bottom): {"type":"phases","kicker":"2-3 words CAPS","steps":[{"title":"max 20 chars","sub":"max 32 chars"}  (3-4)],"footnote":"optional max 44 chars","narration":"..."}
cycle (a loop / feedback cycle of 3-4 stages, e.g. plan -> build -> test -> repeat): {"type":"cycle","kicker":"2-3 words CAPS","center":"max 16 chars","nodes":[{"icon":"<icon>","label":"max 12 chars"}  (3-4)],"footnote":"optional max 44 chars","narration":"..."}
stars (ONLY for a GitHub repo: its star count counting up): {"type":"stars","kicker":"2-3 words CAPS","value":"the real star count, e.g. 12.3k or 12345","caption":"max 30 chars","narration":"..."}
morph (a tool/AI does ONE thing: a single pill becomes button -> loader -> check -> result as a cursor clicks it): {"type":"morph","kicker":"2-3 words CAPS","label":"max 20 chars, the button text e.g. Generate video","result":"max 26 chars, the outcome e.g. Done in 12 seconds","narration":"..."}
bars (a REAL growth/comparison figure with a chart that grows; ONLY with real numbers from the story): {"type":"bars","kicker":"2-3 words CAPS","value":"max 8 chars, the real figure e.g. 128%","label":"max 30 chars","series":[5-8 numbers showing the trend ending at the headline figure],"narration":"..."}
command (an AI search/command tool: a command palette, type, the list filters, Enter, a toast confirms): {"type":"command","kicker":"2-3 words CAPS","query":"max 22 chars","results":["exactly 3, max 26 chars each"],"toast":"max 28 chars","narration":"..."}
tabs (a choice between 3 modes/plans/models; a liquid indicator slides to the one that matters): {"type":"tabs","kicker":"2-3 words CAPS","items":["exactly 3, max 12 chars each"],"pick":<0-2 index of the highlighted one>,"detail":"max 34 chars about the picked one","narration":"..."}
prompt (an AI tool you talk to: a glass prompt box types the request, then the screen whips up to the answer; use only a prompt/answer that matches the story): {"type":"prompt","kicker":"2-3 words CAPS","prompt":"max 46 chars, what the user types","reply":"max 72 chars, the answer text","hi":"1-3 words copied EXACTLY from reply, shown in bold","narration":"..."}
stack (2-3 named modes/features/models/modules as stacked cards with giant glass titles): {"type":"stack","kicker":"2-3 words CAPS","items":[{"title":"max 10 chars","tag":"max 12 chars"}  (2-3)],"narration":"..."}
orbit (four related things: squares spin in around the product, lock into a cross, then slide into a labelled row): {"type":"orbit","kicker":"2-3 words CAPS","icon":"<icon>","items":["exactly 4 labels, max 10 chars each"],"narration":"..."}
cta (closing, always last): {"type":"cta","kicker":"2-3 words CAPS","label":"max 26 chars","plate":"a punchy verdict about THIS story in CAPS, max 20 chars (never the channel name or a follow request)","footnote":"max 70 chars","chips":[{"icon":"<icon>","text":"max 28 chars"}  (exactly 2)],"follow":"Follow for daily AI news","narration":"2 short sentences: first says the source link is in the comments, then asks people to follow for daily AI news"}
"""

def _san_phases(x):
    st = [{"title": _clip(i.get("title"), 20), "sub": _clip(i.get("sub"), 32)} for i in (x.get("steps") or [])[:4]]
    return {"kicker": _clip(x.get("kicker"), 28), "steps": _min_fit(st, 3, 4, {"title": "Next step", "sub": ""}),
            "footnote": _clip(x.get("footnote"), 44)}


def _san_cycle(x):
    nd = [{"icon": _icon(n.get("icon"), "refresh-cw"), "label": _clip(n.get("label"), 12)} for n in (x.get("nodes") or [])[:4]]
    return {"kicker": _clip(x.get("kicker"), 28), "center": _clip(x.get("center"), 16),
            "nodes": _min_fit(nd, 3, 4, {"icon": "refresh-cw", "label": "Repeat"}), "footnote": _clip(x.get("footnote"), 44)}


def _san_stars(x):
    return {"kicker": _clip(x.get("kicker"), 28) or "GITHUB STARS", "icon": "star", "value": _clip(x.get("value"), 8) or "0",
            "caption": _clip(x.get("caption"), 30) or "GitHub stars"}


NEWS_STRUCTURE = """Build the video as 6 scenes in this order:
 1. exactly one OPENING scene: "hook", "slam" or "appclutter"
 2-5. FOUR DIFFERENT scenes chosen from: terminal, alert, timeline, monitor, bignumber, versus, leaderboard, chat, quote, checklist, profile, hubmap, roundup, reveal, phases, cycle, morph, bars, command, tabs, prompt, stack, orbit - \
the ones that tell THIS story best (a funding story wants bignumber/leaderboard, a product launch wants chat/checklist/timeline, \
a controversy wants versus/monitor/alert, a security story wants alert/terminal, a story about several products or agents wants roundup then profile, a platform/ecosystem story wants hubmap, a tool that does one thing wants morph, an AI search tool wants command, a choice of modes/plans wants tabs, a real growth number wants bars, a chatbot/assistant story wants prompt, two or three named modes or models want stack, four related products wants orbit, etc.)
 ON-SCREEN TEXT of morph, bars, command, tabs, prompt, stack and orbit never ends with a full stop.
 NAME RULE: if the story is about ONE specific named tool, product, model or repo, scene 2 MUST be "reveal" - announce its real name right after the hook.
 6. "cta" (always last)"""

REPO_STRUCTURE = """Build the video as 6 scenes in this order:
 1. "repohook" - the opening: a quick glimpse of the repo's real GitHub page. Its narration MUST start with "This GitHub repo".
 2. "reveal" - announces the repo's real name right after the opening.
 3-5. THREE DIFFERENT scenes chosen from: terminal, timeline, hubmap, checklist, profile, phases, cycle, stars, morph, command, tabs, prompt, stack, orbit - the ones that best explain how it works and how to use it.
 6. "cta" (always last)"""


SCRIPT_PROMPT = """You are the creative director and scriptwriter of "AI Quantum", a faceless AI-news channel \
(YouTube Shorts / Instagram Reels / Facebook Reels). Each video is a 45-55 second vertical MOTION-GRAPHICS explainer \
built from animated scenes. EVERY VIDEO MUST FEEL DIFFERENT: you choose the scene sequence, storytelling angle, \
color theme and transition to fit THIS story.

Headline: <<headline>>
Summary: <<summary>>
Why it matters: <<why_it_matters>>

FRAMING MENU
Scene types you can use (each at most once per video):
<<specs>>
<<structure>>
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
- NEVER name or credit the publication/outlet the story came from (no TechCrunch, Verge, Reuters, etc.) in narration, on-screen text, title or description - the source link goes in the comments. Say \"according to the company\" or \"reports say\" if attribution is needed.
- Use ONLY facts from the story above. Never invent numbers, quotes, dates or names. Attribute claims ("per OpenAI", "company-reported").
- A "quote" scene needs a real quote from the story; a "leaderboard" or "bignumber" needs real figures; "profile", "hubmap" and "roundup" must only name things from the story from the story. \
If the story lacks them, choose other scene types. "chat" is an illustrative example of the product, never presented as a real quote.
- Narration is spoken English: short punchy sentences, no lists, no emojis. Each scene has 2 sentences of narration \
(the cta may have 2 short sentences). Scene 1's narration opens with a hook that makes people stay (surprising fact, bold claim or question) and is EXACTLY TWO very short sentences, each at most 9 words (about 3-4 seconds each): the viewer must see a new visual every 4 seconds, so the second sentence becomes its own fast follow-up scene. \
Total narration across all scenes: 95-115 words (about 45 seconds spoken) - be concise.
- All on-screen text is SHORT; respect every max length.
- Icons must come ONLY from this list: <<icons>>

Return ONE JSON object (no markdown, no commentary):
{"beat":{"words":["2 or 3 punchy words that sum up the SECOND sentence of scene 1, each max 10 chars, no full stops"]},"thumb":{"text":"2-4 WORDS, max 24 chars total, the thumbnail headline: a curiosity gap or striking fact that makes people tap (e.g. FREE AI VIDEO TOOL, OPENAI JUST CHANGED EVERYTHING, STOP USING CHATGPT). Never a full sentence, never clickbait that the story does not back up","hi":"the ONE word of that text to highlight"},"title":"punchy title under 90 characters","description":"2-3 sentence description ending with a follow prompt (do not name any news outlet)",\
"hashtags":["#ai","...","8 to 10 total, no spaces"],"angle":"...","theme":"...","transition":"...",\
"mode_pattern":"...","product":{"name":"the main company or product this story is about","domain":"its website domain, e.g. openai.com","simple_icon":"its lowercase slug on simpleicons.org, e.g. openai, or empty"},"scenes":[ ...6 scene objects exactly as specified above, in order... ]}"""



# ---------------------------------------------------------------- FOCUS style (default): one visual per spoken idea
VIDEO_STYLE = os.environ.get("VIDEO_STYLE", "rich")   # "rich" (default, the original multi-element scenes) or "focus" (new minimal style, still being tuned; opt in with VIDEO_STYLE=focus)
FOCUS_EXTRA = ["morph", "bars", "command", "tabs", "prompt", "stack", "orbit"]   # motion-library scenes, max 3 per video
FOCUS_TYPES = ["say", "stat", "icon", "name", "code", "end"] + FOCUS_EXTRA
HOOK_FORMATS = ["bold claim", "counterintuitive statement", "direct question", "list promise", "story open"]

FOCUS_SPECS = """\
say (the workhorse: ONE big phrase on screen): {"type":"say","text":"3-7 word KEY PHRASE, max 44 chars - the heart of what the voice says right now, never the whole sentence","hi":["1-2 words copied from text to highlight"],"narration":"ONE sentence, 6-14 words"}
stat (ONE huge number counting up): {"type":"stat","value":"max 8 chars, a REAL figure from the story, e.g. 40%, $2B, 12k, 9 days","label":"max 4 words saying what it measures","narration":"ONE sentence, 6-14 words"}
icon (ONE big symbol for a concept): {"type":"icon","icon":"<icon>","label":"max 3 words, e.g. Runs locally","narration":"ONE sentence, 6-14 words"}
name (scene 2 only, when the story is about ONE named tool/product/model/repo): {"type":"name","name":"max 20 chars, its real name","icon":"<icon>","narration":"ONE short sentence that says the name, e.g. Meet X, a free tool that ..."}
code (GitHub repo videos only: ONE exact command from the README): {"type":"code","cmd":"max 52 chars, copied from the README, never invented","narration":"ONE sentence telling what the command does"}
morph (a tool does ONE thing: a single pill becomes button -> loader -> check -> result): {"type":"morph","label":"max 20 chars, the button text","result":"max 26 chars, the outcome","narration":"ONE sentence, 6-14 words"}
bars (a REAL growth figure with a chart that grows; real numbers from the story only): {"type":"bars","value":"max 8 chars, the real figure","label":"max 30 chars","series":[5-8 numbers showing the trend, ending at the headline figure],"narration":"ONE sentence, 6-14 words"}
command (an AI search/command tool: a command palette types, filters, Enter, a toast confirms): {"type":"command","query":"max 22 chars","results":["exactly 3, max 26 chars each"],"toast":"max 28 chars","narration":"ONE sentence, 6-14 words"}
tabs (a choice between 3 modes/plans/models; a liquid indicator slides to the one that matters): {"type":"tabs","items":["exactly 3, max 12 chars each"],"pick":<0-2>,"detail":"max 34 chars about the picked one","narration":"ONE sentence, 6-14 words"}
prompt (an AI tool you talk to: a glass prompt box types the request, then the screen whips up to the answer): {"type":"prompt","prompt":"max 46 chars, what the user types","reply":"max 72 chars, the answer text","hi":"1-3 words copied EXACTLY from reply","narration":"ONE sentence, 6-14 words"}
stack (2-3 named modes/features/models as stacked cards with giant glass titles): {"type":"stack","items":[{"title":"max 10 chars","tag":"max 12 chars"}  (2-3)],"narration":"ONE sentence, 6-14 words"}
orbit (four related things: squares spin in around the product, lock into a cross, then slide into a labelled row): {"type":"orbit","icon":"<icon>","items":["exactly 4 labels, max 10 chars each"],"narration":"ONE sentence, 6-14 words"}
end (always last): {"type":"end","text":"max 40 chars, the takeaway - echo or answer the opening hook so the video loops","hi":["1-2 words from text"],"narration":"ONE sentence whose last words flow naturally back into the opening line"}
"""

FOCUS_NEWS_STRUCTURE = """Build the video as 8 or 9 scenes in this order:
 1. "say" - the HOOK (see HOOK RULES). Its narration is at most 9 words.
 2. "name" - ONLY if the story is about ONE specific named tool, product or model; otherwise skip it and use another beat.
 3 to n-1. The body: 5-7 beats, each "say", "stat" or "icon", plus AT MOST 3 beats from the motion scenes morph, bars, command, tabs, prompt, stack, orbit - use one only when it truly matches what the voice says (a tool doing one thing = morph, a real growth figure = bars, an AI search tool = command, a choice of 3 modes = tabs, a chatbot/assistant = prompt, 2-3 named modes or models = stack, four related products = orbit). Never more than 2 of the same type in a row. Use "stat" or "bars" only for a REAL figure from the story. On-screen text of the motion scenes never ends with a full stop.
 n. "end" (always last)"""

FOCUS_REPO_STRUCTURE = """Build the video as 8 to 10 scenes in this order:
 1. "repohook" - the opening glimpse of the repo's real GitHub page. Its narration MUST start with "This GitHub repo" and is at most 11 words.
 2. "name" - the repo's real name.
 3 to n-1. The body: "say" beats for what it does and how it works, one "stat" for the star count, and one or two "code" scenes for the real install/run commands. Never more than 2 of the same type in a row.
 n. "end" (always last)"""

FOCUS_PROMPT = """You are the scriptwriter and creative director of "AI Quantum", a faceless AI-news channel \
(YouTube Shorts / Instagram Reels / Facebook Reels). The video is a 28-36 second vertical explainer. \
FOCUS RULE: the screen shows ONLY what the voice is saying right now - one big phrase, number, symbol or command per beat, \
nothing else, no decoration. The viewer's eyes must stay on one thing at a time.

Headline: <<headline>>
Summary: <<summary>>
Why it matters: <<why_it_matters>>

SCENE TYPES (each beat is one scene):
<<specs>>
<<structure>>
Also choose:
 - "hook_format": one of <<hooks>>
 - "angle": the storytelling frame, one of <<angles>>
 - "theme": one of <<themes>> (mood that suits the story)
 - "transition": one of <<transitions>>
 - "mode_pattern": one of <<modes>>

HOOK RULES (the first 3 seconds decide everything)
- Scene 1's narration is the hook: at most 9 words (about 3 seconds spoken), specific and concrete, a bold claim, a counterintuitive statement, \
a direct question, or a list promise. Start with the interesting thing itself - never "So", "Today", "In this video", "Did you know" or any warm-up.
- The on-screen text of scene 1 shows the hook's most striking 3-6 words, and the voice and screen say the same thing.
- After the hook, pay it off fast: the next beat delivers the first concrete fact.
- The "end" scene echoes the opening so the video loops back into its first line.

PACING RULES
- One idea per beat; each beat's narration is ONE sentence of 6-14 words (about 3-4 seconds) so the screen changes every 2-4 seconds.
- Total narration 70-95 words. Shorter is better; cut anything that does not earn its place.
- Spoken English: short, punchy, concrete, no lists, no emojis, no jargon without a one-line explanation.

VARIETY - recent videos on this channel (do NOT repeat their look or opening style):
<<recent>>

CONTENT RULES
- NEVER name or credit the publication/outlet the story came from (no TechCrunch, Verge, Reuters, etc.) anywhere. Say "according to the company" or "reports say" if attribution is needed.
- Use ONLY facts from the story above. Never invent numbers, quotes, dates or names.
- On-screen text is SHORT; respect every max length. "hi" words must appear inside "text".
- Icons must come ONLY from this list: <<icons>>

Return ONE JSON object (no markdown, no commentary):
{"thumb":{"text":"2-4 WORDS, max 24 chars total, the thumbnail headline: a curiosity gap or striking fact that makes people tap (e.g. FREE AI VIDEO TOOL, OPENAI JUST CHANGED EVERYTHING, STOP USING CHATGPT). Never a full sentence, never clickbait that the story does not back up","hi":"the ONE word of that text to highlight","gap":<optional ONE extra element that opens an information gap the video answers, readable at 120px wide, must be TRUE to the video; pick ONE: {"kind":"number","text":"a real number from the story, max 8 chars, e.g. 42K or 10X or $0"} | {"kind":"steps","items":["3 words, max 9 chars each, e.g. INSTALL","RUN","DONE"]} | {"kind":"versus","items":["max 11 chars","max 11 chars"]} | {"kind":"chyron","text":"max 26 chars, a short true line"} | omit when nothing fits>},"title":"punchy title under 90 characters","description":"2-3 sentence description (do not name any news outlet)",\
"hashtags":["#ai","...","8 to 10 total, no spaces"],"hook_format":"...","angle":"...","theme":"...","transition":"...",\
"mode_pattern":"...","product":{"name":"the main company or product this story is about","domain":"its website domain, e.g. openai.com","simple_icon":"its lowercase slug on simpleicons.org, e.g. openai, or empty"},\
"scenes":[ ...the 8-10 scene objects exactly as specified above, in order... ]}"""

FOCUS_REPO_MODE = """

ADDITIONAL INSTRUCTIONS - this video is a GITHUB REPO EXPLAINER (they override earlier rules where they conflict)
The story is a viral, MIT-licensed open-source project: <<repo_name>> (<<stars>> stars). In this order: what it is and why it is spreading, \
how it works in plain words, then the real install/run commands (each as its own "code" scene - copy exact commands from the README, shorten only if needed, never invent one; \
if the README has no commands, use "say" beats about the key features instead). Say it is free and MIT licensed. \
Narration says "this open source project", never "article" or "report". Do not name any news outlet. Hashtags must include #opensource and #github.

README (the ONLY source of facts besides the summary above):
<<readme>>
"""


def validate_focus(script, story=None):
    sc = script.get("scenes")
    if not isinstance(sc, list) or not (7 <= len(sc) <= 11):
        return "scenes must be a list of 8 to 10 scene objects"
    types = [x.get("type") for x in sc]
    is_repo = (story or {}).get("kind") == "repo"
    allowed = FOCUS_TYPES + [REPO_HOOK]
    for x in sc:
        if x.get("type") not in allowed:
            return f"unknown scene type {x.get('type')}"
        n = len(str(x.get("narration", "")).split())
        if not (4 <= n <= 20):
            return f"scene {x.get('type')} narration is {n} words; each beat is ONE sentence of 6-14 words"
    if is_repo:
        if types[0] != REPO_HOOK:
            return "repo videos must open with the repohook scene"
        if not str(sc[0].get("narration", "")).strip().lower().startswith("this github repo"):
            return "the repohook narration must begin with the words 'This GitHub repo'"
        if len(str(sc[0]["narration"]).split()) > 12:
            return "the repohook narration must be at most 11 words"
        if types[1] != "name":
            return "repo videos need scene 2 = name"
    else:
        if types[0] != "say":
            return "first scene must be a 'say' hook"
        if len(str(sc[0]["narration"]).split()) > 10:
            return "the hook narration must be at most 9 words (about 3 seconds)"
        if REPO_HOOK in types or "code" in types:
            return "repohook and code scenes are only for GitHub repo videos"
    if types[-1] != "end":
        return "last scene must be end"
    if sum(1 for t in types if t in FOCUS_EXTRA) > 3:
        return "use at most 3 of the motion scenes (morph, bars, command, tabs, prompt, stack, orbit)"
    if "name" in types and types.index("name") != 1:
        return "the name scene must be scene 2"
    if types.count("name") > 1 or types.count("end") > 1:
        return "name and end may appear only once"
    for i in range(2, len(types)):
        if types[i] == types[i - 1] == types[i - 2]:
            return f"no more than 2 '{types[i]}' scenes in a row"
    blob = json.dumps(script).lower()
    for outlet in OUTLETS:
        if outlet in blob:
            return f"do not mention the news outlet '{outlet}' anywhere"
    words = sum(len(str(x["narration"]).split()) for x in sc)
    if not (62 <= words <= 105):
        return f"total narration is {words} words; it must be 70-95"
    return ""


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
                     f"pack={r.get('pack')}, angle={r.get('angle')}, scenes={'/'.join(r.get('scenes', []))}")
    return "\n".join(lines)


def build_script_prompt(story, recent, feedback=""):
    kind = story.get("kind", "news")
    if kind == "tutorial":
        import explainer
        return explainer.prompt(story, feedback)
    focus = VIDEO_STYLE == "focus" and kind != "tutorial"
    p = FOCUS_PROMPT if focus else SCRIPT_PROMPT
    for k, v in {
        "headline": story["headline"], "summary": story["summary"], "why_it_matters": story["why_it_matters"],
        "source_link": story["source_link"],
        "specs": (FOCUS_SPECS if focus else SCENE_SPECS) + (REPOHOOK_SPEC if story.get("kind") == "repo" else ""),
        "structure": ((FOCUS_REPO_STRUCTURE if focus else REPO_STRUCTURE) if kind == "repo" else (FOCUS_NEWS_STRUCTURE if focus else NEWS_STRUCTURE))
                     + ("" if focus else pack_rule(story.get("pack"), kind)),
        "hooks": ", ".join(HOOK_FORMATS), "angles": ", ".join(ANGLES),
        "themes": ", ".join(THEMES), "transitions": ", ".join(TRANSITIONS), "modes": ", ".join(MODE_PATTERNS),
        "recent": describe_recent(recent), "icons": ICON_LIST,
    }.items():
        p = p.replace(f"<<{k}>>", str(v))
    if story.get("facts") and kind == "news":
        p += ("\n\nFACT SHEET - researched across several sources. It OVERRIDES the headline and summary wherever they disagree or are vague "
              "(for example it says what the product really is). Build the video from these facts; use their exact numbers and dates, attribute company claims "
              "('per the company'), never mention an outlet, and say what is still unknown rather than guessing:\n" + story["facts"])
    if kind in KINDS_WITH_REPO:
        rp = story.get("repo") or {}
        p += (FOCUS_REPO_MODE if focus else REPO_MODE).replace("<<repo_name>>", rp.get("full_name", "")).replace("<<stars>>", f"{rp.get('stars', 0):,}").replace("<<readme>>", story.get("readme") or "(no README text available)")
    if feedback:
        p += f"\n\nYour previous attempt was rejected: {feedback}\nFix this and return the full JSON again."
    return p


OUTLETS = ["techcrunch", "tech crunch", "the verge", "wired", "reuters", "bloomberg", "venturebeat", "the information", "cnbc", "ars technica", "engadget", "zdnet", "forbes"]


MOTION_SET = ["morph", "command", "tabs", "prompt", "stack", "orbit", "bars"]


def validate_script(script, story=None):
    kind = (story or {}).get("kind", "news")
    if kind == "tutorial":
        import explainer
        return explainer.validate(script, story or {})
    if VIDEO_STYLE == "focus" and kind != "tutorial":
        return validate_focus(script, story)
    if kind == "news" and (story or {}).get("facts") and (story or {}).get("_strict", True):
        src = re.sub(r"[^0-9a-z. ]", " ", " ".join(str((story or {}).get(k, "")) for k in ("headline", "summary", "why_it_matters", "facts")).lower().replace(",", ""))
        words = {"ten": "10", "hundred": "100", "thousand": "1000", "million": "m", "billion": "b", "twice": "2", "double": "2", "triple": "3"}
        text = json.dumps(script.get("scenes", [])).lower().replace(",", "")
        bad = []
        for n in set(re.findall(r"(?<![\w.])\$?(\d[\d.]*)\s*(?:x|k|m|b|%)?", text)):
            n = n.rstrip(".")
            if len(n.replace(".", "")) >= 2 and not re.search(r"(?<![0-9])" + re.escape(n) + r"(?![0-9])", src) and n not in ("1080", "1920"):
                bad.append(n)
        if bad:
            return f"the numbers {sorted(bad)[:4]} are not in the fact sheet or summary; use only numbers from the fact sheet"
    sc = script.get("scenes")
    if not isinstance(sc, list) or not (5 <= len(sc) <= 7):
        return "scenes must be a list of 6 scene objects"
    types = [x.get("type") for x in sc]
    is_repo = kind == "repo"
    if kind == "tutorial":
        if types[0] not in ("hook", "slam") or types[1] != "reveal":
            return "tutorial videos open with hook or slam, then reveal as scene 2"
        if "terminal" not in types:
            return "tutorial videos need a terminal scene with the install commands"
        if not 6 <= len(sc) <= 7:
            return "tutorial videos have 7 scenes"
    elif is_repo:
        if types[0] != REPO_HOOK:
            return "repo videos must open with the repohook scene"
        if not str(sc[0].get("narration", "")).strip().lower().startswith("this github repo"):
            return "the repohook narration must begin with the words 'This GitHub repo'"
        if types[1] != "reveal":
            return "repo videos need scene 2 = reveal"
    elif types[0] not in HOOK_TYPES:
        return "first scene must be hook, slam or appclutter"
    if types[-1] != "cta":
        return "last scene must be cta"
    if len(set(types)) != len(types):
        return "each scene type may be used only once"
    pack = (story or {}).get("pack")
    if pack and (story or {}).get("_strict", True):
        in_pack = sum(1 for t in types if t in STYLE_PACKS[pack]["mid"] and t != "terminal")
        need = 3 if kind == "news" else 2 if kind == "tutorial" else 2
        if in_pack < need:
            return (f"style pack '{pack}': at least {need} of the explanation scenes must be chosen from {', '.join(STYLE_PACKS[pack]['mid'])} "
                    f"(you used {in_pack}); swap other scenes for pack scenes")
    for x in sc:
        if x.get("type") not in HOOK_TYPES + MID_TYPES + ["cta", REPO_HOOK]:
            return f"unknown scene type {x.get('type')}"
        if len(str(x.get("narration", "")).split()) < 6:
            return f"scene {x.get('type')} needs a 2-sentence narration"
    if REPO_HOOK in types and not is_repo:
        return "the repohook scene is only for GitHub repo videos"
    if "stars" in types and not is_repo:
        return "the stars scene is only for GitHub repo videos"
    if "reveal" in types and types.index("reveal") != 1:
        return "the reveal scene must be scene 2, right after the opening"
    blob = json.dumps(script).lower()
    for outlet in OUTLETS:
        if outlet in blob:
            return f"do not mention the news outlet '{outlet}' anywhere (narration, on-screen text, title, description)"
    words = sum(len(str(x["narration"]).split()) for x in sc)
    if not (75 <= words <= 135):
        return f"total narration is {words} words; it must be 95-115"
    return ""


def write_script(story, recent=None, attempts=3):
    recent = recent or []
    feedback = ""
    for i in range(attempts):
        story["_strict"] = i < attempts - 1      # the style-pack rule relaxes on the last attempt so a story is never lost
        try:
            script = gemini_text(build_script_prompt(story, recent, feedback))
            err = validate_script(script, story)
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


def _san_appclutter(x):
    return {"before": _clip(x.get("before"), 36) or "Another app to download?", "after": _clip(x.get("after"), 26) or "Just one simple thing.",
            "user": _clip(x.get("user"), 42) or "Hey, can you handle this?", "ai": _clip(x.get("ai"), 26) or "On it."}


def _san_profile(x):
    cards = [{"icon": _icon(c.get("icon"), "check"), "title": _clip(c.get("title"), 22), "sub": _clip(c.get("sub"), 34)}
             for c in _fit(x.get("cards"), 2, {"icon": "check", "title": "Gets it done", "sub": ""})]
    return {"kicker": _clip(x.get("kicker"), 28), "name": _clip(x.get("name"), 12) or "AI", "icon": _icon(x.get("icon"), "bot"),
            "tag": _clip(x.get("tag"), 36), "pills": [_clip(p, 12) for p in _min_fit(x.get("pills"), 1, 3, "AI")],
            "tagline": _clip(x.get("tagline"), 42), "cards": cards}


def _san_hubmap(x):
    nodes = [{"icon": _icon(n.get("icon"), "star"), "label": _clip(n.get("label"), 12)}
             for n in _fit(x.get("nodes"), 3, {"icon": "star", "label": "..."})]
    cd = x.get("card") or {}
    rows = [{"icon": _icon(r.get("icon"), "check"), "text": _clip(r.get("text"), 32)}
            for r in _fit(cd.get("rows"), 3, {"icon": "check", "text": "..."})]
    return {"kicker": _clip(x.get("kicker"), 28), "icon": _icon(x.get("icon"), "network"), "hub": _clip(x.get("hub"), 16),
            "nodes": nodes, "card": {"title": _clip(cd.get("title"), 28), "rows": rows}}


def _san_roundup(x):
    items = [{"name": _clip(i.get("name"), 12), "icon": _icon(i.get("icon"), "star"), "sub": _clip(i.get("sub"), 36)}
             for i in _fit(x.get("items"), 3, {"name": "-", "icon": "star", "sub": ""})]
    return {"title": _clip(x.get("title"), 24), "sub": _clip(x.get("sub"), 32), "items": items}


def _san_reveal(x):
    return {"kicker": _clip(x.get("kicker"), 28), "meet": _clip(x.get("meet"), 14) or "MEET", "name": _clip(x.get("name"), 20),
            "tagline": _clip(x.get("tagline"), 60), "badges": [_clip(b, 14) for b in _min_fit(x.get("badges"), 1, 3, "AI")],
            "icon": _icon(x.get("icon"), "sparkles")}


def _san_repohook(x):
    h = re.sub(r"^\s*this github repo[\s,:\-]*", "", str(x.get("headline") or ""), flags=re.I)
    return {"kicker": "OPEN SOURCE \u00b7 MIT", "headline": _clip(h, 58) or "is going viral on GitHub"}


def _san_screenshot(x):
    return {"kicker": _clip(x.get("kicker"), 28), "caption": _clip(x.get("caption"), 46)}


def _san_cta(x):
    return {"kicker": _clip(x.get("kicker"), 28), "label": _clip(x.get("label"), 28), "plate": _clip(x.get("plate"), 22),
            "footnote": _clip(x.get("footnote"), 74),
            "chips": [{"icon": _icon(c.get("icon"), "star"), "text": _clip(c.get("text"), 30)}
                      for c in _fit(x.get("chips"), 2, {"icon": "star", "text": "AI Quantum"})],
            "bell": "bell", "comment": "Source link in the comments", "follow": _clip(x.get("follow") or "Follow for daily AI news", 32)}


def _words_in(text, hi):
    """Highlight words that really appear in text; fall back to the last word."""
    have = {re.sub(r"[^a-z0-9$%.]", "", w.lower()): w for w in text.split()}
    out = []
    for h in (hi or [])[:2]:
        for part in str(h).split():
            k = re.sub(r"[^a-z0-9$%.]", "", part.lower())
            if k in have and have[k] not in out:
                out.append(have[k])
    return out[:2] or ([text.split()[-1]] if text.split() else [])


def _san_say(x):
    t = _clip(x.get("text"), 48)
    return {"text": t, "hi": _words_in(t, x.get("hi"))}


def _san_stat(x):
    return {"value": _clip(x.get("value"), 8) or "0", "label": _clip(x.get("label"), 30)}


def _san_iconfx(x):
    return {"icon": _icon(x.get("icon"), "zap"), "label": _clip(x.get("label"), 24)}


def _san_name(x):
    return {"name": _clip(x.get("name"), 22), "icon": _icon(x.get("icon"), "sparkles")}


def _san_code(x):
    return {"cmd": _clip(x.get("cmd"), 56)}


def _nofs(v, n):
    """On-screen text for the motion scenes: clipped, and never ends with a full stop."""
    return _clip(v, n).rstrip(". ").strip()


def _list_fit(v, lo, hi, n, filler):
    out = [_nofs(i, n) for i in (v or []) if str(i).strip()][:hi]
    while len(out) < lo:
        out.append(filler)
    return out


def _san_morph(x):
    return {"kicker": _clip(x.get("kicker"), 28), "label": _nofs(x.get("label"), 22) or "Generate", "result": _nofs(x.get("result"), 28) or "Done"}


def _san_shapes(x):
    return {"kicker": _clip(x.get("kicker"), 28), "items": _list_fit(x.get("items"), 2, 4, 12, "Next")}


def _san_bars(x):
    ser = []
    for v in (x.get("series") or [])[:8]:
        n = _num(v)
        ser.append(n if n > 0 else 0.0)
    if len(ser) < 5 or max(ser or [0]) <= 0:
        ser = [28, 38, 34, 52, 48, 70, 64, 95]     # neutral rising shape if Gemini gave no usable trend
    return {"kicker": _clip(x.get("kicker"), 28), "value": _clip(x.get("value"), 8) or "0", "label": _nofs(x.get("label"), 30), "series": ser}


def _san_command(x):
    return {"kicker": _clip(x.get("kicker"), 28), "query": _nofs(x.get("query"), 22) or "search",
            "results": _list_fit(x.get("results"), 3, 3, 26, "Result"), "toast": _nofs(x.get("toast"), 28) or "Done"}


def _san_tabs(x):
    try:
        pick = max(0, min(2, int(x.get("pick"))))
    except (TypeError, ValueError):
        pick = 2
    return {"kicker": _clip(x.get("kicker"), 28), "items": _list_fit(x.get("items"), 3, 3, 12, "Option"), "pick": pick, "detail": _nofs(x.get("detail"), 34)}


def _san_mark(x):
    return {"kicker": "", "name": _nofs(x.get("name"), 20) or CHANNEL_NAME}


def _san_prompt(x):
    rep_ = _nofs(x.get("reply"), 76) or "Here is your answer"
    hi = _nofs(x.get("hi"), 24)
    if not hi or hi.lower() not in rep_.lower():
        hi = " ".join(rep_.split()[-2:])
    return {"kicker": _clip(x.get("kicker"), 28), "prompt": _nofs(x.get("prompt"), 48) or "Make a launch video", "reply": rep_, "hi": hi}


def _san_stack(x):
    its = []
    for i in (x.get("items") or [])[:3]:
        i = i if isinstance(i, dict) else {"title": i}
        its.append({"title": _nofs(i.get("title"), 10) or "Next", "tag": _nofs(i.get("tag"), 12)})
    while len(its) < 2:
        its.append({"title": "Next", "tag": ""})
    return {"kicker": _clip(x.get("kicker"), 28), "items": its}


def _san_orbit(x):
    return {"kicker": _clip(x.get("kicker"), 28), "icon": _icon(x.get("icon"), "sparkles"), "items": _list_fit(x.get("items"), 4, 4, 10, "Item")}


def _san_wordmark(x):
    return {"name": _nofs(x.get("name"), 20) or CHANNEL_NAME}


SANITIZERS = {"prompt": _san_prompt, "stack": _san_stack, "orbit": _san_orbit, "wordmark": _san_wordmark, "morph": _san_morph, "shapes": _san_shapes, "bars": _san_bars, "command": _san_command,
              "tabs": _san_tabs, "mark": _san_mark, "hook": _san_hook, "slam": _san_slam, "terminal": _san_terminal, "alert": _san_alert, "timeline": _san_timeline,
              "monitor": _san_monitor, "bignumber": _san_bignumber, "versus": _san_versus, "leaderboard": _san_leaderboard,
              "chat": _san_chat, "quote": _san_quote, "checklist": _san_checklist, "cta": _san_cta,
              "reveal": _san_reveal, "screenshot": _san_screenshot, "repohook": _san_repohook, "appclutter": _san_appclutter, "profile": _san_profile, "hubmap": _san_hubmap, "roundup": _san_roundup,
              "phases": _san_phases, "cycle": _san_cycle, "stars": _san_stars,
              "say": _san_say, "end": _san_say, "stat": _san_stat, "icon": _san_iconfx, "name": _san_name, "code": _san_code}


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


def _san_thumb(t, scenes, story):
    """Thumbnail text: 2-4 uppercase words from Gemini, else built from the opening scene / headline."""
    t = t if isinstance(t, dict) else {}
    def clean(v):
        v = re.sub(r"[.!?,;:]+", "", str(v or "")).upper()
        return " ".join(v.split()[:4])
    text = clean(t.get("text"))
    if len(text) > 26 or len(text.split()) < 2:
        first = scenes[0] if scenes else {}
        text = clean(first.get("headline") or first.get("text") or (story or {}).get("headline", "AI NEWS"))
        if len(text) > 26:
            text = " ".join(text.split()[:3])
    words = text.split()
    hi = clean(t.get("hi")).split()[:1]
    hi = hi[0] if hi and hi[0] in words else (max(words, key=len) if words else "")
    out = {"text": text or "AI NEWS", "hi": hi}
    gap = _san_gap(t.get("gap"), story)
    if gap:
        out["gap"] = gap
    return out


def _san_gap(g, story):
    """Optional thumbnail information-gap element. Numbers must exist in the story; everything is short and has no full stops."""
    if not isinstance(g, dict):
        return None
    kind = g.get("kind")
    def c(v, n):
        return re.sub(r"[.!?]+", "", " ".join(str(v or "").split()))[:n].strip().upper()
    st = story or {}
    rp = st.get("repo") or {}
    hay = " ".join(str(st.get(k, "")) for k in ("headline", "summary", "why_it_matters", "readme")).lower() + f" {rp.get('stars', 0)}"
    if kind == "number":
        t = c(g.get("text"), 8)
        digits = re.sub(r"[^0-9]", "", t)
        stars = int(rp.get("stars") or 0)
        ok = t and digits and (digits in re.sub(r"[^0-9 ]", "", hay.replace(",", "")) or (stars >= 1000 and digits.startswith(str(stars)[:2])) or t in ("$0", "0"))
        return {"kind": "number", "text": t} if ok else None
    if kind == "steps":
        it = [c(x, 9) for x in (g.get("items") or []) if c(x, 9)][:3]
        return {"kind": "steps", "items": it} if len(it) == 3 else None
    if kind == "versus":
        it = [c(x, 11) for x in (g.get("items") or []) if c(x, 11)][:2]
        return {"kind": "versus", "items": it} if len(it) == 2 else None
    if kind == "chyron":
        t = c(g.get("text"), 26)
        return {"kind": "chyron", "text": t} if len(t) >= 6 else None
    return None


_STOP = set("the a an and or of to in on for with is are was were be been it its this that these those you your they their we our as at by from but not no so if than then there here can will just now into over more most very new".split())


def _split_opening(raw, beat):
    """The opening scene would hold ONE visual for ~10 s. Split its two sentences: sentence 1 stays on the hook,
    sentence 2 becomes a fast glass-card scene, so the picture changes every ~4 s."""
    sents = [x for x in re.split(r"(?<=[.!?])\s+", str(raw[0].get("narration", "")).strip()) if x.strip()]
    if len(sents) < 2:
        return raw
    rest = " ".join(sents[1:])
    words = [str(w).strip()[:10] for w in ((beat or {}).get("words") or []) if str(w).strip()][:3]
    if len(words) < 2:
        toks = [re.sub(r"[^A-Za-z0-9$%+\-]", "", w) for w in rest.split()]
        toks = [t for t in toks if t and t.lower() not in _STOP]
        top = sorted(range(len(toks)), key=lambda i: -len(toks[i]))[:3]
        words = [toks[i] for i in sorted(top)] or ["Here is why"]
        if len(words) < 2:
            words.append("Next")
    first = dict(raw[0], narration=sents[0])
    used = {x.get("type") for x in raw}
    if "stack" in used and "morph" not in used:      # never two stack scenes in one video: the beat becomes a button that morphs
        beat_scene = {"type": "morph", "label": words[0], "result": words[1], "narration": rest, "_beat": True}
    else:
        beat_scene = {"type": "stack", "items": [{"title": w, "tag": ""} for w in words[:3]], "narration": rest, "_beat": True}
    return [first, beat_scene] + list(raw[1:])


def script_to_manifest(script, story=None, recent=None):
    """Gemini script -> (render manifest, voice-over text, framing record for the anti-repeat state)."""
    recent = recent or []
    seed = sum(ord(c) for c in (story or {}).get("headline", "x")) + len(recent)
    if (story or {}).get("kind") == "tutorial":
        import explainer
        theme = _pick(None, THEMES, [r.get("theme") for r in recent[-3:]], seed)
        manifest = explainer.to_manifest(script, story, theme, CHANNEL_NAME)
        manifest["thumb"] = _san_thumb(script.get("thumb"), [], story)
        record = {"ts": time.strftime("%Y-%m-%d %H:%M"), "pack": "Explainer", "theme": theme, "transition": "sweep", "angle": "tutorial",
                  "hook": "", "scenes": [x["type"] for x in manifest["scenes"]], "kind": "tutorial",
                  "headline": story.get("headline", "")[:80], "link": story.get("source_link", "")}
        return manifest, " ".join(x["narration"] for x in manifest["scenes"]), record
    pack = (story or {}).get("pack")
    if pack in STYLE_PACKS:
        pk = STYLE_PACKS[pack]
        theme = _pick(None, pk["themes"], [r.get("theme") for r in recent[-3:]], seed)
        transition, pattern = pk["transition"], pk["mode"]
    else:
        theme = _pick(script.get("theme"), THEMES, [r.get("theme") for r in recent[-3:]], seed)
        transition = _pick(script.get("transition"), TRANSITIONS, [r.get("transition") for r in recent[-2:]], seed // 3)
        pattern = _pick(script.get("mode_pattern"), MODE_PATTERNS, [], seed // 5)

    raw = script["scenes"]
    if not (VIDEO_STYLE == "focus" and (story or {}).get("kind") != "tutorial"):
        raw = _split_opening(raw, script.get("beat"))
    modes = _modes(pattern, len(raw))
    scenes = []
    for i, x in enumerate(raw):
        t = x["type"]
        sc = {"type": t, "mode": modes[i], **SANITIZERS[t](x), "narration": str(x["narration"]).strip()}
        if x.get("_beat"):
            sc["beat"] = True
        scenes.append(sc)
    pr = script.get("product") if isinstance(script.get("product"), dict) else {}
    product = {"name": _clip(pr.get("name"), 30), "domain": re.sub(r"[^a-z0-9.\-]", "", str(pr.get("domain") or "").lower().replace("https://", "").replace("www.", "").split("/")[0]),
               "slug": re.sub(r"[^a-z0-9]", "", str(pr.get("simple_icon") or "").lower())}
    manifest = {"brand": {"name": CHANNEL_NAME, "icon": "atom"}, "product": product, "source": "",
                "theme": theme, "transition": transition, "scenes": scenes}
    if VIDEO_STYLE == "focus" and (story or {}).get("kind") != "tutorial":
        manifest["style"] = "focus"
    manifest["thumb"] = _san_thumb(script.get("thumb"), scenes, story)
    voice = " ".join(s["narration"] for s in scenes)
    record = {"ts": time.strftime("%Y-%m-%d %H:%M"), "pack": pack, "theme": theme, "transition": transition,
              "angle": script.get("angle"), "hook": script.get("hook_format"), "scenes": [s["type"] for s in scenes],
              "kind": (story or {}).get("kind", "news"), "headline": (story or {}).get("headline", "")[:80], "link": (story or {}).get("source_link", "")}
    return manifest, voice, record


# ---------------------------------------------------------------- product logo

def fetch_product_logo(product):
    """Real brand logo of the product the story is about, as a data URI ('' if none found)."""
    product = product or {}
    urls = []
    if product.get("slug"):
        urls.append(f"https://cdn.simpleicons.org/{product['slug']}")          # official brand-coloured SVG
    if product.get("domain"):
        urls.append(f"https://www.google.com/s2/favicons?domain={product['domain']}&sz=256")
        urls.append(f"https://icons.duckduckgo.com/ip3/{product['domain']}.ico")
    for u in urls:
        try:
            r = requests.get(u, timeout=15)
            ctype = (r.headers.get("content-type") or "").split(";")[0].strip()
            if r.status_code == 200 and len(r.content) > 300 and ctype.startswith("image/"):
                return f"data:{ctype};base64," + base64.b64encode(r.content).decode()
        except Exception as e:  # noqa
            print(f"[logo] {u} failed: {e}")
    print(f"[logo] no logo found for {product}")
    return ""


# ---------------------------------------------------------------- repo screenshot

def capture_repo_screenshot(full_name):
    """Screenshot of the repo's real GitHub page (top of the README) as a JPEG data URI ('' on failure)."""
    try:
        sys.path.insert(0, os.path.join(REPO_ROOT, "render"))
        import html_render as hr
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = hr.launch(p)
            ctx = b.new_context(viewport={"width": 800, "height": 1500}, color_scheme="dark", device_scale_factor=1.5)
            page = ctx.new_page()
            page.goto(f"https://github.com/{full_name}", wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(3500)
            for sel in ("button:has-text('Accept')", "button:has-text('Reject')"):  # cookie banners, if any
                try:
                    page.click(sel, timeout=800)
                except Exception:  # noqa
                    pass
            jpg = page.screenshot(type="jpeg", quality=76, full_page=True,
                                  clip={"x": 0, "y": 0, "width": 800, "height": 2400})
            b.close()
        return "data:image/jpeg;base64," + base64.b64encode(jpg).decode()
    except Exception as e:  # noqa
        print(f"[screenshot] failed for {full_name}: {e}")
        return ""


# ---------------------------------------------------------------- TTS

# Male Gemini voice (calm, informative). Alternatives: Orus, Algenib, Alnilam, Iapetus, Umbriel, Schedar.
VOICE_NAME = os.environ.get("TTS_VOICE", "Charon")


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
                        "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOICE_NAME}}
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


def render_thumbnail(manifest, story, out_path):
    """Designed cover image (1080x1920 JPEG) for the video. Best effort: returns the path or ''."""
    try:
        th = manifest.get("thumb") or {}
        repo = story.get("kind") == "repo"
        tut = story.get("kind") == "tutorial"
        tm = {"brand": manifest.get("brand", {}), "product": manifest.get("product", {}), "theme": manifest.get("theme"),
              "style": "focus", "product_logo": manifest.get("product_logo", ""),
              "scenes": [{"type": "thumb", "mode": "dark", "text": th.get("text", "AI NEWS"), "hi": th.get("hi", ""),
                          "badge": "FREE TUTORIAL" if tut else "GITHUB REPO" if repo else "AI NEWS",
                          "icon": (manifest["scenes"][0].get("icon") if manifest.get("scenes") else "") or "sparkles", "gap": th.get("gap"),
                          "start": 0, "end": 2, "narration": ""}]}
        tp = out_path + ".json"
        with open(tp, "w") as f:
            json.dump(tm, f)
        subprocess.run(["python3", RENDER_SCRIPT, "--manifest", tp, "--thumb", out_path], check=True, cwd=REPO_ROOT, timeout=240)
        os.remove(tp)
        return out_path if os.path.getsize(out_path) > 5000 else ""
    except Exception as e:  # noqa
        print(f"[thumb] could not render thumbnail: {e}")
        return ""


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
        # -X theirs: on a conflict (e.g. state/recent.json edited elsewhere) keep OUR newest commit.
        pull = subprocess.run(["git", "pull", "--rebase", "-X", "theirs"], cwd=REPO_ROOT,
                              capture_output=True, text=True)
        if pull.returncode != 0:
            print("Rebase failed, aborting it and merging instead:", pull.stdout[-300:], pull.stderr[-300:])
            subprocess.run(["git", "rebase", "--abort"], cwd=REPO_ROOT)
            subprocess.run(["git", "pull", "--no-rebase", "-X", "theirs", "--no-edit"], cwd=REPO_ROOT)
        time.sleep(3)
    raise RuntimeError("git push failed after retries")


def process_story(i, story, recent_holder):
    recent = recent_holder[0]
    print(f"--- Processing story {i}: {story['headline']} ---")
    story["pack"] = pick_pack(recent, story.get("kind", "news")) if VIDEO_STYLE != "focus" and story.get("kind") != "tutorial" else None
    print(f"Style pack: {story['pack']}")
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import research
        research.enrich(story)
    except Exception as e:  # noqa
        print(f"[research] skipped: {e}")
    script = write_script(story, recent)
    manifest, voice_script, record = script_to_manifest(script, story, recent)
    if story.get("kind") in KINDS_WITH_REPO:
        rp = story.get("repo") or {}
        manifest["product_logo"] = fetch_repo_logo(story)
        manifest["repo_shot"] = capture_repo_screenshot(rp.get("full_name", ""))
        manifest["repo_info"] = {"full_name": rp.get("full_name", ""), "description": story.get("headline", "").split(": ", 1)[-1],
                                 "stars_text": f"{rp.get('stars', 0):,}", "language": rp.get("language", "")}
    else:
        manifest["product_logo"] = fetch_product_logo(manifest.get("product"))
    try:
        if manifest.get("engine") == "paper":
            raise RuntimeError("explainer videos use their own scene set")
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import custom_motion
        record["motion_refs"] = custom_motion.add_to_manifest(manifest, story)
        record["scenes"] = [x["type"] for x in manifest["scenes"]]
    except Exception as e:  # noqa
        print(f"[motion] skipped: {e}")
    print(f"Framing: {record['theme']} / {record['transition']} / {record['angle']} / {' > '.join(record['scenes'])}")

    stamp = time.strftime("%Y-%m-%d-%H%M%S") + f"-{i}"
    manifest_path = f"/tmp/manifest_{stamp}.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f)

    audio_path = os.path.join(AUDIO_DIR, f"{stamp}.wav")
    gemini_tts(voice_script, audio_path)

    video_path = os.path.join(OUTPUT_DIR, f"{stamp}.mp4")
    render_video(manifest_path, audio_path, video_path)
    thumb_path = render_thumbnail(manifest, story, os.path.join(OUTPUT_DIR, f"{stamp}.jpg"))
    thumb_rel = os.path.relpath(thumb_path, REPO_ROOT) if thumb_path else ""
    asset = None
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import store
        asset = store.upload(video_path)
        if asset:                                   # the video now lives in a release, not in git history
            os.remove(video_path)
            os.remove(audio_path)
    except Exception as e:  # noqa
        print(f"[store] skipped: {e}")

    recent = save_recent(recent, record)
    video_rel_path = os.path.relpath(video_path, REPO_ROOT)
    # Queue the video; the "Post next video" workflow publishes one per daily slot (morning / afternoon / evening).
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import post_queue
        caption = f"{script['title']}\n\n{script['description']}\n\n{' '.join(script['hashtags'])}"
        post_queue.enqueue(video_rel_path, caption, story["source_link"], story["headline"], thumb_rel, asset)
        post_queue.log_content({
            "video": video_rel_path, "ts": time.strftime("%Y-%m-%d %H:%M"), "kind": story.get("kind", "news"),
            "headline": story["headline"], "title": script.get("title", ""), "source_link": story.get("source_link", ""),
            "theme": record.get("theme", ""), "angle": record.get("angle", ""),
            "scenes": record.get("scenes", []),
            "words": sum(len(str(x.get("narration", "")).split()) for x in script.get("scenes", [])),
            "caption": caption, "thumb": thumb_rel, "status": "queued"})
        print("[queue] added to the post queue")
    except Exception as e:  # noqa
        print(f"[queue] could not enqueue: {e}")
    git_push_with_retry(f"Add rendered video {stamp}")

    repo = os.environ.get("GITHUB_REPOSITORY", "")
    video_url = (asset or {}).get("url") or (f"https://github.com/{repo}/raw/main/{video_rel_path}" if repo else video_rel_path)

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


HAS_COMMANDS = re.compile(r"```[^\n]*\n[^`]*\b(pip3? install|npm (i|install)|npx |pnpm |yarn |docker |git clone|uvx? |pipx |brew install|cargo install|go install|curl )", re.I)


def pick_tutorials(cands, n):
    """Repos whose README has real install commands, turned into tutorial stories."""
    good = [c for c in cands if HAS_COMMANDS.search(c.get("readme") or "")]
    out = []
    for c in good[:n]:
        t = dict(c)
        t["kind"] = "tutorial"
        t["why_it_matters"] = "Free and open source (MIT license): anyone can install it and run it today."
        out.append(t)
    print(f"[tutorial] selected {[t['repo']['full_name'] for t in out]}")
    return out


def main():
    os.makedirs(AUDIO_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    recent = load_recent()
    recent_holder = [recent]
    n_repo = min(GITHUB_VIDEOS, TOTAL_VIDEOS)
    n_tut = min(TUTORIAL_VIDEOS, max(0, TOTAL_VIDEOS - n_repo - 1))
    stories = []
    try:
        stories = fetch_stories(recent)[: max(1, TOTAL_VIDEOS - n_repo - n_tut)]
    except Exception as e:  # noqa
        print(f"[news] skipped: {e}")
    try:
        cands = fetch_github_repos(recent, n_repo + n_tut + (3 if n_tut else 0))
        stories += cands[:n_repo]
        if n_tut:
            stories += pick_tutorials(cands[n_repo:], n_tut)
    except Exception as e:  # noqa
        print(f"[github] skipped: {e}")
    print(f"Selected {len(stories)} stories")
    if not stories:
        raise SystemExit("No stories could be selected")

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
