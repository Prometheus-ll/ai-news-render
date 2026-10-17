"""Publish a rendered video to Instagram as a Reel (Instagram Graph API, resumable upload - no public URL needed).

Needs (otherwise Instagram posting is silently skipped):
  IG_USER_ID     - id of the Instagram professional (Business/Creator) account linked to the Facebook Page
  FB_PAGE_TOKEN  - the same long-lived Page token used for Facebook, but created with the extra permissions
                   instagram_basic and instagram_content_publish
"""
import os, time, requests

GRAPH = "https://graph.facebook.com/v21.0"
RUPLOAD = "https://rupload.facebook.com/ig-api-upload/v21.0"


def enabled():
    return bool(os.environ.get("IG_USER_ID") and os.environ.get("FB_PAGE_TOKEN"))


def _check(r, what):
    if r.status_code >= 400:
        raise RuntimeError(f"Instagram {what} failed ({r.status_code}): {r.text[:400]}")
    return r.json()


def post_reel(video_path, caption, wait_s=420):
    """Upload `video_path` as a Reel. Returns the published media id."""
    ig, token = os.environ["IG_USER_ID"], os.environ["FB_PAGE_TOKEN"]
    # 1) create a resumable Reels container
    c = _check(requests.post(f"{GRAPH}/{ig}/media", data={
        "media_type": "REELS", "upload_type": "resumable", "caption": caption[:2200],
        "share_to_feed": "true", "access_token": token}, timeout=60), "container")
    cid = c["id"]
    upload_url = c.get("uri") or f"{RUPLOAD}/{cid}"
    # 2) upload the bytes
    size = os.path.getsize(video_path)
    with open(video_path, "rb") as f:
        _check(requests.post(upload_url, data=f, timeout=600, headers={
            "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)}), "upload")
    # 3) wait until Instagram finished processing
    deadline = time.time() + wait_s
    while True:
        r = requests.get(f"{GRAPH}/{cid}", params={"fields": "status_code,status", "access_token": token}, timeout=30)
        st = r.json() if r.status_code == 200 else {}
        code = st.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram processing {code}: {st.get('status')}")
        if time.time() > deadline:
            raise RuntimeError(f"Instagram processing timed out (last status {code})")
        time.sleep(8)
    # 4) publish
    p = _check(requests.post(f"{GRAPH}/{ig}/media_publish", data={"creation_id": cid, "access_token": token}, timeout=60), "publish")
    return p["id"]
