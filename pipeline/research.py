"""Research step for news stories: before the script is written, collect the real facts.

1. Read the article itself (the RSS summary is only a teaser and is where wrong facts came from).
2. Ask Gemini with Google Search grounding for a fact sheet checked against more than one source.
Everything is best effort: on any failure the story simply goes on without a fact sheet."""
import os, re, json, html
import requests

KEY = os.environ.get("GEMINI_API_KEY", "")
URL = "https://generativelanguage.googleapis.com/v1beta/models"
MODELS = ["gemini-3-flash-preview", "gemini-2.5-flash"]


def article_text(link, limit=6000):
    try:
        r = requests.get(link, headers={"User-Agent": "Mozilla/5.0 (compatible; AIQuantumBot/1.0)"}, timeout=25)
        if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            return ""
        t = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header|form)[^>]*>.*?</\1>", " ", r.text)
        paras = re.findall(r"(?is)<p[^>]*>(.*?)</p>", t)
        txt = " ".join(html.unescape(re.sub(r"<[^>]+>", "", p)).strip() for p in paras)
        txt = re.sub(r"\s+", " ", txt)
        return txt[:limit] if len(txt) > 400 else ""
    except Exception as e:  # noqa
        print(f"[research] article fetch failed: {e}")
        return ""


def fact_sheet(story, article):
    """Grounded fact sheet (Google Search tool). Returns plain text bullets or ''."""
    if not KEY:
        return ""
    prompt = f"""Research this AI news story for a fact-checked 45-second video. Use Google Search and compare AT LEAST two independent sources.

Story headline: {story.get('headline')}
Teaser summary (may be wrong or vague, verify it): {story.get('summary')}
Article text we could read (may be empty):
{article or '(none)'}

Return ONLY a fact sheet of 8-14 short bullet lines, each starting with "- ":
- exactly WHAT the thing is and does (correct any wrong framing in the teaser)
- who made it and when (exact dates)
- concrete numbers: prices, speeds, sizes, funding, valuation, user counts (say who claims each: company or independent)
- what is new compared with before, and who the rivals are
- what is NOT known yet or disputed
Never invent. If sources disagree, say so. Do not name news outlets; name companies and people only."""
    for model in MODELS:
        try:
            r = requests.post(f"{URL}/{model}:generateContent", headers={"x-goog-api-key": KEY}, timeout=120,
                              json={"contents": [{"parts": [{"text": prompt}]}], "tools": [{"google_search": {}}]})
            if r.status_code == 200:
                parts = r.json()["candidates"][0]["content"]["parts"]
                txt = "\n".join(p.get("text", "") for p in parts).strip()
                lines = [l.strip() for l in txt.splitlines() if l.strip().startswith("-")]
                if len(lines) >= 4:
                    return "\n".join(lines)[:3500]
            else:
                print(f"[research] {model} -> {r.status_code}")
        except Exception as e:  # noqa
            print(f"[research] {model} failed: {e}")
    return ""


def enrich(story):
    """Adds story['facts'] (fact sheet) and story['article'] when found. Never raises."""
    try:
        if story.get("kind", "news") != "news":
            return story
        art = article_text(story.get("source_link", ""))
        facts = fact_sheet(story, art)
        if facts:
            story["facts"] = facts
        elif art:
            story["facts"] = "Article excerpt (verify nothing beyond this):\n" + art[:2500]
        print(f"[research] facts: {len((story.get('facts') or '').splitlines())} lines, article: {len(art)} chars")
    except Exception as e:  # noqa
        print(f"[research] skipped: {e}")
    return story
