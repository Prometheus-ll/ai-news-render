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


def fetch_stories():
    feed = feedparser.parse(RSS_URL)
    articles = [{"title": e.title, "link": e.link, "summary": getattr(e, "summary", "")}
                for e in feed.entries[:20]]
    prompt = f"""You are a news curator for a faceless AI-news channel posting to YouTube, Facebook, and Instagram.

Here is today's list of AI-related articles as JSON:
{json.dumps(articles)}

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

SCRIPT_PROMPT = """You are writing a 45-55 second short-form AI-news video for "AI Quantum" \
(YouTube Shorts / Instagram Reels / Facebook Reels). The video is a MOTION-GRAPHICS explainer: six \
animated scenes (hook card, terminal readout, alert card, timeline, monitor panel, call-to-action), each \
with its own narration. Every on-screen text field is SHORT. The narrator speaks the "narration" fields.

Headline: {headline}
Summary: {summary}
Why it matters: {why_it_matters}
Source: {source_link}

RULES
- Use ONLY facts from the story above. Never invent numbers, quotes, dates, or names. If something is a claim \
by a company, say so ("company-reported", "per OpenAI").
- Scene 1 narration must open with a hook that makes people stay: a surprising fact, a bold claim, or a question.
- Narration is spoken English: short punchy sentences, no lists, no emojis. Each scene narration is 2 sentences \
(scene 6 may be 2 short sentences). Total across all scenes: 115-150 words.
- Icons must be chosen ONLY from this list: {icons}

Return ONE JSON object with EXACTLY this shape (no markdown, no commentary):

{{
  "title": "punchy title under 90 characters",
  "description": "2-3 sentence description ending with a follow prompt and source credit",
  "hashtags": ["#ai", "...", "8 to 10 total, no spaces"],
  "source_name": "publication name, e.g. TechCrunch",
  "scenes": {{
    "hook": {{
      "headline": "4-8 word hook headline shown big on screen, sentence case",
      "word": "ONE product/company/topic word in CAPS, max 10 characters",
      "title": "product or topic name shown on the card, max 14 characters",
      "subtitle": "max 38 characters, e.g. 'By OpenAI - most capable yet'",
      "badge": "1-2 words in caps, e.g. NEW MODEL, FUNDING, POLICY, OUTAGE",
      "icon": "icon name",
      "chips": ["3 short tags, max 16 characters each"],
      "narration": "..."
    }},
    "terminal": {{
      "kicker": "2-3 words in caps, e.g. SOFTWARE ENGINEERING",
      "file": "fake filename like topic_facts.exe",
      "tag": "short label, max 28 chars, e.g. Best for coding - per OpenAI",
      "lines": [{{"cmd": "a command-style line for one KEY FACT, max 34 characters, e.g. astra --task find-bugs", "result": "short result 1-3 words"}}],
      "banner": "one-line takeaway, max 46 characters",
      "note": "max 28 chars, e.g. company-reported",
      "narration": "..."
    }},
    "alert": {{
      "kicker": "2-3 words in caps",
      "chip": "2-3 words, e.g. Dual-use capability",
      "icon": "icon name",
      "big": "the most striking fact/stat, max 26 characters",
      "quote": "one supporting line, max 90 characters (attribute it if it's a claim)",
      "label": "max 40 characters",
      "glyphs": ["short decorative word, max 6 chars", "another, max 6 chars"],
      "narration": "..."
    }},
    "timeline": {{
      "kicker": "2-3 words in caps, e.g. ROLLOUT TIMELINE or WHAT HAPPENED",
      "steps": [{{"icon": "icon name", "title": "max 22 characters", "sub": "max 30 characters"}}],
      "footnote": "max 44 characters, a caveat or open question",
      "narration": "..."
    }},
    "monitor": {{
      "kicker": "2-3 words in caps, e.g. THE CONTROVERSY or THE RISKS",
      "header": "panel title, max 28 characters",
      "rows": ["4 short lines, max 30 characters each, steps or items"],
      "hidden": "max 24 characters, e.g. reasoning hidden",
      "cards": [{{"icon": "icon name", "title": "max 20 characters", "sub": "max 32 characters", "tone": "violet | blue | red"}}],
      "footnote": "max 50 characters, e.g. *as described by TechCrunch",
      "narration": "..."
    }},
    "cta": {{
      "kicker": "2-3 words in caps",
      "label": "max 26 characters, e.g. Our take",
      "plate": "the verdict/punchline in caps, max 20 characters",
      "footnote": "max 70 characters clarifying the verdict",
      "chips": [{{"icon": "icon name", "text": "max 28 characters"}}],
      "follow": "Follow for daily AI news",
      "narration": "ends by asking people to follow for daily AI news"
    }}
  }}
}}

Counts: terminal.lines = exactly 3; timeline.steps = exactly 4; monitor.rows = exactly 4; monitor.cards = exactly 3; \
cta.chips = exactly 2; hook.chips = exactly 3; alert.glyphs = exactly 2. Respond with ONLY the JSON object."""


def write_script(story):
    prompt = SCRIPT_PROMPT.format(icons=ICON_LIST, **story)
    return gemini_text(prompt)


def _clip(v, n):
    v = " ".join(str(v or "").split())
    return v if len(v) <= n else v[: n - 1].rstrip() + "..."


def _fit(lst, n, filler):
    lst = list(lst or [])[:n]
    while len(lst) < n:
        lst.append(filler)
    return lst


def script_to_manifest(script, story=None):
    """Turn the Gemini script JSON into the html_render.py scene manifest and the full narration."""
    sc = script["scenes"]
    h, t, a, tl, mo, c = (sc["hook"], sc["terminal"], sc["alert"], sc["timeline"], sc["monitor"], sc["cta"])
    tone_ok = {"violet", "blue", "red"}

    scenes = [
        {"type": "hook", "headline": _clip(h.get("headline"), 60), "word": _clip(h.get("word"), 10),
         "title": _clip(h.get("title"), 14), "subtitle": _clip(h.get("subtitle"), 40),
         "badge": _clip(h.get("badge"), 14), "icon": h.get("icon", "sparkles"),
         "chips": [_clip(x, 16) for x in _fit(h.get("chips"), 3, "AI news")],
         "narration": h["narration"]},
        {"type": "terminal", "kicker": _clip(t.get("kicker"), 28), "file": _clip(t.get("file"), 24),
         "tag": _clip(t.get("tag"), 30),
         "lines": [{"cmd": _clip(x.get("cmd"), 36), "result": _clip(x.get("result"), 16)}
                   for x in _fit(t.get("lines"), 3, {"cmd": "ai --news", "result": "done"})],
         "banner": _clip(t.get("banner"), 48), "note": _clip(t.get("note"), 30),
         "narration": t["narration"]},
        {"type": "alert", "kicker": _clip(a.get("kicker"), 28), "chip": _clip(a.get("chip"), 26),
         "icon": a.get("icon", "triangle-alert"), "big": _clip(a.get("big"), 28),
         "quote": _clip(a.get("quote"), 100), "label": _clip(a.get("label"), 44),
         "glyphs": [_clip(x, 6) for x in _fit(a.get("glyphs"), 2, "AI")],
         "narration": a["narration"]},
        {"type": "timeline", "kicker": _clip(tl.get("kicker"), 28),
         "steps": [{"icon": x.get("icon", "clock"), "title": _clip(x.get("title"), 24), "sub": _clip(x.get("sub"), 32)}
                   for x in _fit(tl.get("steps"), 4, {"icon": "clock", "title": "Next", "sub": ""})],
         "footnote": _clip(tl.get("footnote"), 46), "narration": tl["narration"]},
        {"type": "monitor", "kicker": _clip(mo.get("kicker"), 28), "header": _clip(mo.get("header"), 30),
         "rows": [_clip(x, 32) for x in _fit(mo.get("rows"), 4, "...")],
         "hidden": _clip(mo.get("hidden"), 26),
         "cards": [{"icon": x.get("icon", "eye"), "title": _clip(x.get("title"), 22), "sub": _clip(x.get("sub"), 34),
                    "tone": x.get("tone") if x.get("tone") in tone_ok else ["violet", "blue", "red"][i]}
                   for i, x in enumerate(_fit(mo.get("cards"), 3, {"icon": "eye", "title": "Watch this", "sub": ""}))],
         "footnote": _clip(mo.get("footnote"), 54), "narration": mo["narration"]},
        {"type": "cta", "kicker": _clip(c.get("kicker"), 28), "label": _clip(c.get("label"), 28),
         "plate": _clip(c.get("plate"), 22), "footnote": _clip(c.get("footnote"), 74),
         "chips": [{"icon": x.get("icon", "star"), "text": _clip(x.get("text"), 30)}
                   for x in _fit(c.get("chips"), 2, {"icon": "star", "text": "AI Quantum"})],
         "bell": "bell", "follow": _clip(c.get("follow") or "Follow for daily AI news", 32),
         "narration": c["narration"]},
    ]
    manifest = {
        "brand": {"name": CHANNEL_NAME, "icon": "atom"},
        "source": script.get("source_name") or "",
        "scenes": scenes,
    }
    voice = " ".join(s["narration"].strip() for s in scenes)
    return manifest, voice


# ---------------------------------------------------------------- TTS

def gemini_tts(text, out_wav_path, retries=3):
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
            data = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
            pcm = base64.b64decode(data)
            build_wav(pcm, out_wav_path)
            return out_wav_path
        print(f"TTS call failed ({r.status_code}), retry {i + 1}/{retries}")
        time.sleep(10)
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
    subprocess.run(["git", "add", "renders/output", "audio"], cwd=REPO_ROOT, check=True)
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


def main():
    os.makedirs(AUDIO_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    stories = fetch_stories()
    print(f"Selected {len(stories)} stories")

    for i, story in enumerate(stories):
        print(f"--- Processing story {i}: {story['headline']} ---")
        script = write_script(story)
        manifest, voice_script = script_to_manifest(script, story)

        stamp = time.strftime("%Y-%m-%d-%H%M%S") + f"-{i}"
        manifest_path = f"/tmp/manifest_{stamp}.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f)

        audio_path = os.path.join(AUDIO_DIR, f"{stamp}.wav")
        gemini_tts(voice_script, audio_path)

        video_path = os.path.join(OUTPUT_DIR, f"{stamp}.mp4")
        render_video(manifest_path, audio_path, video_path)

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


if __name__ == "__main__":
    main()
