import os, re, json, time, base64, struct, subprocess
import requests
import feedparser

GEMINI_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models"
RSS_URL = "https://techcrunch.com/category/artificial-intelligence/feed/"
CHANNEL_NAME = "AI Quantum"

def extract_json(s):
    start = re.search(r"[{\[]", s)
    if not start: return s
    start = start.start()
    open_ch = s[start]
    close_ch = "}" if open_ch == "{" else "]"
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(s)):
        ch = s[i]
        if escape: escape = False; continue
        if ch == "\\": escape = True; continue
        if ch == '"': in_str = not in_str; continue
        if in_str: continue
        if ch == open_ch: depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0: return s[start:i+1]
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
        print(f"Gemini text call failed ({r.status_code}), retry {i+1}/{retries}")
        time.sleep(10)
    raise RuntimeError("Gemini text call failed after retries")

def gemini_tts(script_text, retries=3):
    for i in range(retries):
        r = requests.post(
            f"{GEMINI_URL}/gemini-3.1-flash-tts-preview:generateContent",
            headers={"x-goog-api-key": GEMINI_KEY},
            json={"contents": [{"parts": [{"text": script_text}]}],
                  "generationConfig": {"responseModalities": ["AUDIO"],
                      "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Kore"}}}}}
        )
        if r.status_code == 200:
            return r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
        print(f"Gemini TTS call failed ({r.status_code}), retry {i+1}/{retries}")
        time.sleep(10)
    raise RuntimeError("Gemini TTS call failed after retries")

def build_wav(base64_pcm, out_path):
    pcm = base64.b64decode(base64_pcm)
    sample_rate, channels, bits = 24000, 1, 16
    byte_rate = sample_rate * channels * bits // 8
    block_align = channels * bits // 8
    header = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
    header += struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, block_align, bits)
    header += b"data" + struct.pack("<I", len(pcm))
    with open(out_path, "wb") as f:
        f.write(header + pcm)

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

def write_script(story):
    prompt = f"""You are a scriptwriter for a fast-paced, faceless AI-news short-form video channel (YouTube Shorts / Instagram Reels / Facebook Reels), 45-60 seconds long.

Here is the story:
Headline: {story['headline']}
Summary: {story['summary']}
Why it matters: {story['why_it_matters']}

Write:
1. A spoken narration script, roughly 120-150 words. Open with a strong hook. Explain what happened in simple, energetic language. Close with why it matters and a short call-to-action to follow for daily AI updates. Write ONLY the words to be spoken.
2. On-screen captions: split the narration into short caption lines for burned-in subtitles. Each line must be a few words (max ~7 words) taken verbatim from the narration, in order, covering the ENTIRE script with no words skipped.

Respond with ONLY this JSON:
{{"script": "the full narration text", "captions": ["caption line 1", "caption line 2"]}}"""
    data = gemini_text(prompt)

    captions = data.get("captions", [])
    if isinstance(captions, str):
        captions = re.split(r"\r?\n|(?<=[.!?])\s+", captions)
    captions = [c.strip() for c in captions if isinstance(c, str) and c.strip()]
    if not captions and data.get("script"):
        captions = [s.strip() for s in re.split(r"(?<=[.!?])\s+", data["script"]) if s.strip()]
    data["captions"] = captions
    return data

def write_metadata(story):
    prompt = f"""You are writing metadata for a short-form AI-news video on "AI Quantum".

Headline: {story['headline']}
Why it matters: {story['why_it_matters']}
Source: {story['source_link']}

Write:
1. A short punchy video title, under 60 characters.
2. A 2-3 sentence description ending with a follow prompt and a credit to the source.
3. 8-10 relevant hashtags as an array.

Respond with ONLY this JSON:
{{"title": "...", "description": "...", "hashtags": ["...", "..."]}}"""
    return gemini_text(prompt)

def render_video(video_id, manifest, audio_path):
    os.makedirs("renders/output", exist_ok=True)
    manifest_path = f"manifest_{video_id}.json"
    json.dump(manifest, open(manifest_path, "w"))
    out_path = f"renders/output/{video_id}.mp4"
    subprocess.run(["python", "render/render_video.py",
                     "--manifest", manifest_path, "--audio", audio_path,
                     "--output", out_path], check=True)
    return out_path

def log_to_sheets(row):
    import gspread
    from google.oauth2.service_account import Credentials
    creds_dict = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(
        creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)
    sheet = gc.open_by_key(os.environ["GOOGLE_SHEET_ID"]).sheet1
    sheet.append_row(row)

def main():
    stories = fetch_stories()
    print(f"Selected {len(stories)} stories")
    for i, story in enumerate(stories):
        print(f"--- Processing story {i}: {story['headline']} ---")
        script_data = write_script(story)
        video_id = f"{time.strftime('%Y-%m-%d-%H%M%S')}-{i}"
        audio_path = f"{video_id}.wav"

        pcm_b64 = gemini_tts(script_data["script"])
        build_wav(pcm_b64, audio_path)

        manifest = {"captions": script_data["captions"], "channel_name": CHANNEL_NAME}
        video_path = render_video(video_id, manifest, audio_path)

        meta = write_metadata(story)

        subprocess.run(["git", "add", video_path], check=True)
        subprocess.run(["git", "commit", "-m", f"Render {video_id}"], check=False)
        for attempt in range(5):
            push = subprocess.run(["git", "push"])
            if push.returncode == 0:
                break
            subprocess.run(["git", "pull", "--rebase", "origin", "main"], check=True)
            time.sleep(3)

        video_url = f"https://raw.githubusercontent.com/Prometheus-ll/ai-news-render/main/{video_path}"
        log_to_sheets([time.strftime("%Y-%m-%d %H:%M"), story["headline"], meta["title"],
                       meta["description"], " ".join(meta["hashtags"]), video_url, story["source_link"]])
        print(f"Done: {video_id}")

        os.remove(audio_path)

if __name__ == "__main__":
    main()
