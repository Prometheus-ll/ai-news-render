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
RENDER_SCRIPT = os.path.join(REPO_ROOT, "render", "render_video.py")


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

SCRIPT_PROMPT = """You are writing a 45-60 second short-form AI-news video script for "AI Quantum" \
(YouTube Shorts / Instagram Reels / Facebook Reels). The visual style is bold kinetic \
typography: short punchy phrases, numbered points, a quick bullet-point payoff, and a \
follow call-to-action. No visuals are described here -- you are writing ONLY the words \
that will appear on screen and be spoken by the narrator.

Headline: {headline}
Summary: {summary}
Why it matters: {why_it_matters}
Source: {source_link}

Structure your output as a JSON object with this EXACT shape:

{{
  "title": "a punchy YouTube/Instagram title, under 90 characters",
  "description": "2-3 sentence description ending with a follow prompt and source credit",
  "hashtags": ["#ai", "...", "8 to 10 total, no spaces"],
  "hook": {{
    "kicker": "a short 2-4 word lead-in phrase, regular weight, e.g. 'OpenAI just'",
    "headline": "the punchy 2-5 word bold headline, ALL CAPS, e.g. 'SHIPPED GPT-6'",
    "subline": "a short follow-up phrase, 3-6 words, e.g. 'and nobody saw it coming'"
  }},
  "points": [
    {{
      "number": 1,
      "icon": "one of: bolt, chip, arrow_up, clock, brain -- pick whichever best fits this point",
      "keyword": "a short 2-5 word bold phrase naming this point",
      "detail_lead": "a short regular-weight lead-in sentence fragment, 3-6 words",
      "detail_bold": "the key 2-5 word bold phrase/number/stat for this point, ALL CAPS",
      "detail_tail": "a short regular-weight closing fragment, 3-6 words"
    }}
  ],
  "mockup_kicker": "a short 2-4 word label above the mockup card, e.g. 'In their own words'",
  "mockup_lines": ["2 to 4 short lines (under 10 words each) styled like a quoted excerpt, stat callout, or snippet from the source article -- this renders inside a dark app-style card, NOT spoken verbatim by the narrator"],
  "bullets_title": "a short 2-3 word section title, lowercase, e.g. 'why it matters'",
  "bullets": ["3 to 4 short punchy one-line takeaways, each under 9 words"],
  "outro_line": "a short 3-6 word question or statement, e.g. 'Want the full breakdown?'",
  "cta": "a short call to action, 3-6 words, e.g. 'Follow for daily AI news'",
  "voice_script": "the FULL narration script as continuous spoken-language sentences, \
energetic and fast-paced, covering the hook, every point (in order), the bullets, and the \
outro/CTA -- this is what the narrator actually says, written as natural sentences, NOT \
labeled or bulleted. 120-170 words."
}}

Produce exactly 2 or 3 "points". Keep every on-screen phrase SHORT -- these are kinetic \
type cards, not paragraphs. Respond with ONLY the JSON object, no markdown, no extra text."""


def write_script(story):
    prompt = SCRIPT_PROMPT.format(**story)
    return gemini_text(prompt)


def script_to_manifest(script):
    """Turn the Gemini script JSON into the render_video.py scene manifest."""
    rows_hook = [
        {"text": script["hook"]["kicker"], "weight": "regular", "size": 60, "color": [24, 24, 24]},
        {"text": script["hook"]["headline"], "weight": "bold", "size": 88, "color": [24, 24, 24]},
        {"text": script["hook"]["subline"], "weight": "bold", "size": 46, "highlight": True},
    ]
    scenes = [{"type": "title", "burst": True, "rows": rows_hook}]

    for pt in script["points"]:
        scenes.append({
            "type": "number",
            "number": pt["number"],
            "icon": pt.get("icon", "bolt"),
            "rows": [{"text": pt["keyword"], "weight": "bold", "size": 60, "color": [24, 24, 24]}],
        })
        scenes.append({
            "type": "detail",
            "rows": [
                {"text": pt["detail_lead"], "weight": "regular", "size": 50, "color": [24, 24, 24]},
                {"text": pt["detail_bold"], "weight": "bold", "size": 74, "color": [24, 24, 24]},
                {"text": pt["detail_tail"], "weight": "regular", "size": 50, "color": [90, 90, 90]},
            ],
        })

    if script.get("mockup_lines"):
        scenes.append({
            "type": "mockup",
            "rows": [{"text": script.get("mockup_kicker", "In their own words"), "weight": "bold",
                      "size": 48, "color": [24, 24, 24]}],
            "lines": script["mockup_lines"],
        })

    scenes.append({
        "type": "bullets",
        "title": [{"text": script["bullets_title"], "weight": "bold", "size": 56, "color": [24, 24, 24]}],
        "items": script["bullets"],
    })

    scenes.append({
        "type": "outro",
        "rows": [{"text": script["outro_line"], "weight": "bold", "size": 58, "color": [24, 24, 24]}],
        "cta": script["cta"],
    })

    return {"channel_name": CHANNEL_NAME, "handle": HANDLE, "scenes": scenes}


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
        manifest = script_to_manifest(script)

        stamp = time.strftime("%Y-%m-%d-%H%M%S") + f"-{i}"
        manifest_path = f"/tmp/manifest_{stamp}.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f)

        audio_path = os.path.join(AUDIO_DIR, f"{stamp}.wav")
        gemini_tts(script["voice_script"], audio_path)

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
