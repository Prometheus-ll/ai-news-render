"""Publish a rendered video to YouTube as a Short (YouTube Data API v3, resumable upload).

Needs (otherwise YouTube posting is silently skipped):
  YT_CLIENT_ID, YT_CLIENT_SECRET - OAuth client of your Google Cloud project
  YT_REFRESH_TOKEN               - refresh token with the scope https://www.googleapis.com/auth/youtube.upload
Optional: YT_PRIVACY (public | unlisted | private; default public)
Vertical videos under 60 s are treated as Shorts automatically; '#Shorts' is added to the title for good measure.
"""
import os, re, requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"


def enabled():
    return all(os.environ.get(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"))


def access_token():
    r = requests.post(TOKEN_URL, data={
        "client_id": os.environ["YT_CLIENT_ID"], "client_secret": os.environ["YT_CLIENT_SECRET"],
        "refresh_token": os.environ["YT_REFRESH_TOKEN"], "grant_type": "refresh_token"}, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"YouTube token refresh failed ({r.status_code}): {r.text[:300]}")
    return r.json()["access_token"]


def upload_short(video_path, title, description, tags=None):
    """Upload `video_path`. Returns the YouTube video id."""
    tok = access_token()
    title = re.sub(r"\s+", " ", title).strip()
    if "#shorts" not in title.lower():
        title = title[:90].rstrip() + " #Shorts"
    meta = {"snippet": {"title": title[:100], "description": description[:4900], "tags": (tags or [])[:15], "categoryId": "28"},
            "status": {"privacyStatus": os.environ.get("YT_PRIVACY", "public"), "selfDeclaredMadeForKids": False}}
    size = os.path.getsize(video_path)
    init = requests.post(UPLOAD_URL, params={"uploadType": "resumable", "part": "snippet,status"}, json=meta, timeout=60, headers={
        "Authorization": f"Bearer {tok}", "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)})
    if init.status_code >= 400:
        raise RuntimeError(f"YouTube upload start failed ({init.status_code}): {init.text[:400]}")
    with open(video_path, "rb") as f:
        up = requests.put(init.headers["Location"], data=f, timeout=900, headers={"Content-Type": "video/mp4"})
    if up.status_code >= 400:
        raise RuntimeError(f"YouTube upload failed ({up.status_code}): {up.text[:400]}")
    return up.json()["id"]
