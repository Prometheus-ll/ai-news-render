"""Post queue: the daily pipeline renders every video up front and adds it here;
the 'Post next video' workflow (3 time slots a day) publishes ONE queued video per run.

  python pipeline/post_queue.py     # post the oldest pending video to the Facebook Page

Needs FB_PAGE_ID / FB_PAGE_TOKEN (see facebook.py). Without them it does nothing.
"""
import json, os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE_PATH = os.path.join(ROOT, "state", "post_queue.json")
LOG_PATH = os.path.join(ROOT, "state", "content_log.json")  # permanent history for the dashboard
MAX_ATTEMPTS = 3
KEEP = 60


def load():
    try:
        with open(QUEUE_PATH) as f:
            q = json.load(f)
        return q if isinstance(q, list) else []
    except Exception:
        return []


def save(q):
    os.makedirs(os.path.dirname(QUEUE_PATH), exist_ok=True)
    finished = [x for x in q if x.get("status") != "pending"]
    drop = {id(x) for x in finished[:-KEEP]} if len(finished) > KEEP else set()
    q = [x for x in q if id(x) not in drop]
    with open(QUEUE_PATH, "w") as f:
        json.dump(q, f, indent=1)


def enqueue(video_rel, caption, source_link, headline, thumb=""):
    """Add a rendered video (path relative to the repo root) to the queue."""
    q = load()
    if any(x.get("video") == video_rel for x in q):
        return
    q.append({"video": video_rel, "caption": caption, "source_link": source_link or "", "headline": headline or "", "thumb": thumb or "",
              "added": time.strftime("%Y-%m-%d %H:%M"), "status": "pending", "attempts": 0})
    save(q)


def _load_log():
    try:
        with open(LOG_PATH) as f:
            q = json.load(f)
        return q if isinstance(q, list) else []
    except Exception:
        return []


def log_content(entry):
    """Append one rendered video to the permanent content log (state/content_log.json)."""
    lg = [x for x in _load_log() if x.get("video") != entry.get("video")]
    lg.append(entry)
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "w") as f:
        json.dump(lg[-500:], f, indent=1)


def update_log(video, **fields):
    lg = _load_log()
    for x in lg:
        if x.get("video") == video:
            x.update(fields)
    with open(LOG_PATH, "w") as f:
        json.dump(lg, f, indent=1)


def next_pending(q):
    for x in q:
        if x.get("status") == "pending":
            return x
    return None


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def push_state(message, attempts=5):
    _git("config", "user.name", "ai-quantum-bot")
    _git("config", "user.email", "bot@ai-quantum.local")
    _git("add", "state")
    if not _git("status", "--porcelain").stdout.strip():
        return
    _git("commit", "-m", message)
    for i in range(attempts):
        if _git("push").returncode == 0:
            print("Pushed state.")
            return
        print(f"Push failed, pulling and retrying ({i + 1}/{attempts})...")
        if _git("pull", "--rebase", "-X", "theirs").returncode != 0:
            _git("rebase", "--abort")
            _git("pull", "--no-rebase", "-X", "theirs", "--no-edit")
        time.sleep(3)
    print("WARNING: could not push state/post_queue.json - the next run may re-post this video")


PLATFORMS = ["facebook", "instagram", "youtube"]
RETRY_WAIT = 45  # seconds before one in-run retry of a failed platform


def _post(platform, item):
    """Publish one queued item to one platform. Returns the platform's post id."""
    import facebook, instagram, youtube
    path = os.path.join(ROOT, item["video"])
    cap = item["caption"]
    thumb = os.path.join(ROOT, item["thumb"]) if item.get("thumb") and os.path.exists(os.path.join(ROOT, item["thumb"])) else ""
    if platform == "facebook":
        return facebook.post_reel(path, cap, item.get("source_link"), thumb=thumb)
    if platform == "instagram":
        return instagram.post_reel(path, cap, thumb_rel=item.get("thumb", "") if thumb else "")
    title = cap.split("\n")[0] or item.get("headline", "AI news")
    tags = [t.lstrip("#") for t in cap.split() if t.startswith("#")]
    desc = cap + (f"\n\nSource: {item['source_link']}" if item.get("source_link") else "") + "\n\n#Shorts"
    return youtube.upload_short(path, title, desc, tags, thumb=thumb)


def _enabled():
    import facebook, instagram, youtube
    mods = {"facebook": facebook, "instagram": instagram, "youtube": youtube}
    return [p for p in PLATFORMS if mods[p].enabled()]


def _remaining(item, enabled):
    pl = item.get("platforms", {})
    return [p for p in enabled if pl.get(p, {}).get("status") not in ("posted", "failed")]


def _finish(item, enabled):
    """Set the overall item status from its per-platform results."""
    pl = item.get("platforms", {})
    if _remaining(item, enabled):
        item["status"] = "pending"
        return
    done = [p for p in enabled if pl.get(p, {}).get("status") == "posted"]
    item["status"] = "posted" if done else "failed"
    if done and not item.get("posted_at"):
        item["posted_at"] = time.strftime("%Y-%m-%d %H:%M")
    ids = {p: pl[p].get("id") for p in done}
    if ids.get("facebook"):
        item["fb_id"] = ids["facebook"]


def _log(item):
    update_log(item["video"], status=item["status"], posted_at=item.get("posted_at"), fb_id=item.get("fb_id"),
               platforms={p: {"status": v.get("status"), "id": v.get("id")} for p, v in item.get("platforms", {}).items()})


def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    enabled = _enabled()
    if not enabled:
        print("[post] no platform is configured (FB_PAGE_ID/FB_PAGE_TOKEN, IG_USER_ID, YT_* secrets) - nothing to do")
        return
    print(f"[post] platforms: {', '.join(enabled)}")
    q = load()
    for x in q:  # skip entries whose video file is gone
        if x.get("status") == "pending" and not os.path.exists(os.path.join(ROOT, x["video"])):
            x["status"], x["error"] = "failed", "video file missing"
    item = next((x for x in q if x.get("status") == "pending" and _remaining(x, enabled)), None)
    if not item:
        print("[post] queue is empty - nothing to post this slot")
        save(q)
        push_state("Update post queue")
        return
    print(f"[post] posting: {item.get('headline') or item['video']}")
    pl = item.setdefault("platforms", {})

    def attempt(p):
        st = pl.setdefault(p, {"status": "pending", "attempts": 0})
        try:
            st["id"] = _post(p, item)
            st.update(status="posted", at=time.strftime("%Y-%m-%d %H:%M"))
            st.pop("error", None)
            print(f"[{p}] posted {st['id']}")
            return True
        except Exception as e:  # noqa
            st["attempts"] = st.get("attempts", 0) + 1
            st["error"] = str(e)[:300]
            if st["attempts"] >= MAX_ATTEMPTS:
                st["status"] = "failed"
            print(f"[{p}] failed (attempt {st['attempts']}/{MAX_ATTEMPTS}): {e}")
            return False

    todo = _remaining(item, enabled)
    retry = [p for p in todo if not attempt(p)]
    if retry:
        time.sleep(RETRY_WAIT)
        for p in retry:
            if pl[p].get("status") != "failed":
                attempt(p)
    failures = [p for p in todo if pl[p].get("status") != "posted"]
    _finish(item, enabled)
    if failures:
        item["error"] = "; ".join(f"{p}: {pl[p].get('error', '')}" for p in failures)[:300]
    else:
        item.pop("error", None)
    _log(item)
    save(q)
    push_state("Update post queue")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
