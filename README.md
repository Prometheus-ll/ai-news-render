# ai-news-render

Daily AI-news short-video pipeline for **AI Quantum** (YouTube Shorts / Reels), $0 budget, runs on GitHub Actions.

Flow: RSS -> Gemini picks stories -> Gemini writes a 6-scene script -> Gemini TTS narration ->
`render/html_render.py` lays the scenes out on the audio timeline and records `render/html/engine.html`
(HTML/CSS/SVG motion graphics, `seek(t)`-driven) frame-by-frame with headless Chromium (Playwright) -> ffmpeg mux ->
video committed to `renders/output/` and logged to Google Sheets.

Scenes: hook card, terminal readout, alert card, timeline, monitor panel, call-to-action. Captions, brand bar
and scene-start pulse are global. Icons are Lucide (builtin set in `html_render.py`, others fetched from jsDelivr).

Local debug: `python render/html_render.py --manifest m.json --audio a.wav --output out.mp4 --stills 1,8,20`

## Variety (every video gets a new framing)
Gemini chooses, per story, an opening (`hook` / `slam`), four different middle scenes from
`terminal, alert, timeline, monitor, bignumber, versus, leaderboard, chat, quote, checklist`, a closing `cta`,
a storytelling angle, one of 8 color themes, one of 4 transitions (`fade, slide, zoom, wipe`) and a light/dark pattern.
`state/recent.json` remembers the last 8 videos; the prompt tells Gemini not to repeat them and the pipeline
overrides a repeated theme/transition. Add new scene types in `render/html/engine.html` (`BUILDERS`) and
`pipeline/run_pipeline.py` (`SCENE_SPECS`, `SANITIZERS`).
