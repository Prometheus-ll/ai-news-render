import os, re, json, time
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
        print(f"Gemini call failed ({r.status_code}), retry {i+1}/{retries}")
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

def write_package(story):
    prompt = f"""You are producing a short-form AI-news video package for "AI Quantum" (YouTube Shorts / Instagram Reels / Facebook Reels).

Headline: {story['headline']}
Summary: {story['summary']}
Why it matters: {story['why_it_matters']}
Source: {story['source_link']}

Produce THREE things:

1. "source_text": a well-organized 200-300 word briefing document about this story (background, what happened, why it matters, who's involved). This will be the source material fed into an AI video generation tool.

2. "master_prompt": detailed generation instructions for that tool. Must specify: (a) 45-60 second short-form vertical video, (b) tone: energetic, clear, fast-paced tech news, (c) open with a strong hook, (d) end with "Follow AI Quantum for daily AI updates", (e) visual style: minimal, premium, editorial motion-graphics — off-white background, clean modern sans-serif typography, restrained color palette, company/product logos and icons used as visual objects, no random unrelated stock footage, (f) channel name "AI Quantum" mentioned for branding.

3. "title", "description" (2-3 sentences, ending with a follow prompt and source credit), and "hashtags" (8-10, as an array).

Respond with ONLY this JSON:
{{"source_text": "...", "master_prompt": "...", "title": "...", "description": "...", "hashtags": ["...", "..."]}}"""
    return gemini_text(prompt)

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
        pkg = write_package(story)
        log_to_sheets([
            time.strftime("%Y-%m-%d %H:%M"),
            story["headline"],
            pkg["title"],
            pkg["description"],
            " ".join(pkg["hashtags"]),
            pkg["source_text"],
            pkg["master_prompt"],
            story["source_link"],
        ])
        print(f"Done: {story['headline']}")

if __name__ == "__main__":
    main()
