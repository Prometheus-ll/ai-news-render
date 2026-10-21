"""Publish a rendered video to a Facebook Page as a Reel, then add the source link as the first comment.

Needs two secrets (otherwise posting is silently skipped):
  FB_PAGE_ID     - numeric id of the Facebook Page
  FB_PAGE_TOKEN  - long-lived Page access token (pages_manage_posts, pages_read_engagement, pages_manage_engagement)
"""
import os, time, requests

GRAPH = "https://graph.facebook.com/v21.0"
RUPLOAD = "https://rupload.facebook.com/video-upload/v21.0"


def enabled():
    return bool(os.environ.get("FB_PAGE_ID") and os.environ.get("FB_PAGE_TOKEN"))


def _check(r, what):
    if r.status_code >= 400:
        raise RuntimeError(f"Facebook {what} failed ({r.status_code}): {r.text[:400]}")
    return r.json()


def post_reel(video_path, description, source_link=None, wait_s=300, thumb=""):
    """Upload `video_path` as a Reel. Returns the video id. Comments the source link if given."""
    page, token = os.environ["FB_PAGE_ID"], os.environ["FB_PAGE_TOKEN"]
    # 1) start an upload session
    start = _check(requests.post(f"{GRAPH}/{page}/video_reels",
                                 data={"upload_phase": "start", "access_token": token}, timeout=60), "start")
    video_id, upload_url = start["video_id"], start.get("upload_url") or f"{RUPLOAD}/{start['video_id']}"
    # 2) upload the bytes
    size = os.path.getsize(video_path)
    with open(video_path, "rb") as f:
        _check(requests.post(upload_url, data=f, timeout=600, headers={
            "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)}), "upload")
    # 3) publish
    _check(requests.post(f"{GRAPH}/{page}/video_reels", data={
        "upload_phase": "finish", "video_id": video_id, "video_state": "PUBLISHED",
        "description": description[:2000], "access_token": token}, timeout=60), "publish")
    # 4) wait until Facebook finished processing
    deadline, status = time.time() + wait_s, {}
    while time.time() < deadline:
        r = requests.get(f"{GRAPH}/{video_id}", params={"fields": "status", "access_token": token}, timeout=30)
        status = (r.json().get("status") or {}) if r.status_code == 200 else {}
        if status.get("video_status") in ("ready", "published") or (status.get("publishing_phase") or {}).get("status") == "complete":
            break
        if status.get("video_status") == "error":
            raise RuntimeError(f"Facebook processing error: {status}")
        time.sleep(10)
    # 5a) cover image (best effort - Facebook may ignore it for Reels)
    if thumb:
        try:
            with open(thumb, "rb") as f:
                _check(requests.post(f"{GRAPH}/{video_id}/thumbnails", data={"is_preferred": "true", "access_token": token},
                                     files={"source": ("cover.jpg", f, "image/jpeg")}, timeout=120), "thumbnail")
        except Exception as e:  # noqa
            print(f"[facebook] thumbnail not set: {e}")
    # 5) first comment with the source link
    if source_link:
        try:
            _check(requests.post(f"{GRAPH}/{video_id}/comments",
                                 data={"message": f"Source: {source_link}", "access_token": token}, timeout=30), "comment")
        except Exception as e:  # noqa - the Reel is already live; do not fail the run over the comment
            print(f"[facebook] comment failed: {e}")
    return video_id
