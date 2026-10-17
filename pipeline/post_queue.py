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


def enqueue(video_rel, caption, source_link, headline):
    """Add a rendered video (path relative to the repo root) to the queue."""
    q = load()
    if any(x.get("video") == video_rel for x in q):
        return
    q.append({"video": video_rel, "caption": caption, "source_link": source_link or "", "headline": headline or "",
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


def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import facebook
    if not facebook.enabled():
        print("[post] FB_PAGE_ID / FB_PAGE_TOKEN not set - nothing to do")
        return
    q = load()
    # skip entries whose video file is gone
    for x in q:
        if x.get("status") == "pending" and not os.path.exists(os.path.join(ROOT, x["video"])):
            x["status"], x["error"] = "failed", "video file missing"
    item = next_pending(q)
    if not item:
        print("[post] queue is empty - nothing to post this slot")
        save(q)
        push_state("Update post queue")
        return
    print(f"[post] posting: {item.get('headline') or item['video']}")
    failed = None
    try:
        fb_id = facebook.post_reel(os.path.join(ROOT, item["video"]), item["caption"], item.get("source_link"))
        item.update(status="posted", fb_id=fb_id, posted_at=time.strftime("%Y-%m-%d %H:%M"))
        update_log(item["video"], status="posted", fb_id=fb_id, posted_at=item["posted_at"])
        print(f"[facebook] posted reel {fb_id}")
    except Exception as e:  # noqa
        item["attempts"] = item.get("attempts", 0) + 1
        item["error"] = str(e)[:300]
        if item["attempts"] >= MAX_ATTEMPTS:
            item["status"] = "failed"
            update_log(item["video"], status="failed")
        failed = e
        print(f"[facebook] failed (attempt {item['attempts']}/{MAX_ATTEMPTS}): {e}")
    save(q)
    push_state("Update post queue")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
