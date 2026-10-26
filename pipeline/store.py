"""Video carrier between the 'Daily Pipeline' and 'Post next video' workflows: GitHub Release assets instead of git commits,
so finished videos never enter the repository history (which kept growing by ~60 MB a day).

Needs GITHUB_REPOSITORY and GITHUB_TOKEN (both exist inside GitHub Actions). Every function fails soft:
upload() returns None when anything is wrong and the caller falls back to committing the file, as before."""
import os
import requests

TAG = "video-queue"
API = "https://api.github.com"


def _repo():
    return os.environ.get("GITHUB_REPOSITORY", "")


def _h(extra=None):
    h = {"Authorization": f"Bearer {os.environ.get('GITHUB_TOKEN', '')}", "Accept": "application/vnd.github+json",
         "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "ai-quantum-pipeline"}
    h.update(extra or {})
    return h


def available():
    return bool(_repo() and os.environ.get("GITHUB_TOKEN"))


def _release_id():
    r = requests.get(f"{API}/repos/{_repo()}/releases/tags/{TAG}", headers=_h(), timeout=30)
    if r.status_code == 200:
        return r.json()["id"]
    r = requests.post(f"{API}/repos/{_repo()}/releases", headers=_h(), timeout=30,
                      json={"tag_name": TAG, "name": "Video queue (temporary files, deleted after posting)",
                            "body": "Rendered videos waiting to be posted. Managed by the pipeline.", "prerelease": True})
    r.raise_for_status()
    return r.json()["id"]


def upload(path):
    """Upload a video. Returns {"id": asset_id, "url": browser_download_url} or None."""
    if not available():
        return None
    try:
        rid = _release_id()
        name = os.path.basename(path)
        with open(path, "rb") as f:
            r = requests.post(f"https://uploads.github.com/repos/{_repo()}/releases/{rid}/assets", params={"name": name},
                              headers=_h({"Content-Type": "video/mp4"}), data=f, timeout=600)
        r.raise_for_status()
        j = r.json()
        print(f"[store] uploaded {name} as release asset {j['id']}")
        return {"id": j["id"], "url": j.get("browser_download_url", "")}
    except Exception as e:  # noqa
        print(f"[store] upload failed, keeping the file in git: {e}")
        return None


def download(asset_id, dest):
    r = requests.get(f"{API}/repos/{_repo()}/releases/assets/{asset_id}", headers=_h({"Accept": "application/octet-stream"}),
                     timeout=600, stream=True)
    r.raise_for_status()
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        for chunk in r.iter_content(1 << 20):
            f.write(chunk)
    return dest


def delete(asset_id):
    try:
        r = requests.delete(f"{API}/repos/{_repo()}/releases/assets/{asset_id}", headers=_h(), timeout=30)
        print(f"[store] deleted asset {asset_id} ({r.status_code})")
    except Exception as e:  # noqa
        print(f"[store] could not delete asset {asset_id}: {e}")
