"""Real photos from the web, but only ones we may legally show: Wikimedia Commons files under an open licence
(CC BY, CC BY-SA, CC0, public domain), found through the person's Wikipedia page. The licence + author are returned as a
credit line that the video prints under the photo. Non-free ("fair use") Wikipedia images, news-site pictures and Google images
are NEVER used. Everything is fail-soft: no match -> ('', '') and the scene shows an initial-letter avatar instead."""
import base64, io, re, urllib.parse

import requests

UA = {"User-Agent": "AIQuantumVideoBot/1.0 (faceless AI news channel; open-licence photos only)"}
OK_LICENSE = re.compile(r"^(CC[ -]BY(?![ -](NC|ND))(?:[ -]SA)?|CC0|Public domain|PD)", re.I)


def _strip(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def find_photo(title, size=480):
    """-> (data_uri, credit) for the Wikipedia article called `title` (a real person/organisation), or ('', '')."""
    title = (title or "").strip()
    if not title:
        return "", ""
    try:
        q = urllib.parse.quote(title.replace(" ", "_"), safe="")
        r = requests.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{q}?redirect=true", headers=UA, timeout=20)
        if r.status_code != 200:
            return "", ""
        d = r.json()
        if d.get("type") != "standard":                                     # disambiguation / missing
            return "", ""
        got = {w for w in re.findall(r"[a-z]+", d.get("title", "").lower()) if len(w) > 2}
        want = {w for w in re.findall(r"[a-z]+", title.lower()) if len(w) > 2}
        if want and not (want & got):
            return "", ""
        src = (d.get("originalimage") or d.get("thumbnail") or {}).get("source", "")
        if "/wikipedia/commons/" not in src:                                 # '/wikipedia/en/' = locally uploaded, often non-free
            return "", ""
        fname = urllib.parse.unquote(src.split("/")[-1] if "/thumb/" not in src else src.split("/")[-2])
        r = requests.get("https://commons.wikimedia.org/w/api.php", headers=UA, timeout=20,
                         params={"action": "query", "titles": "File:" + fname, "prop": "imageinfo", "iiprop": "extmetadata", "format": "json"})
        pages = r.json().get("query", {}).get("pages", {})
        meta = (next(iter(pages.values())).get("imageinfo") or [{}])[0].get("extmetadata", {})
        lic = _strip((meta.get("LicenseShortName") or {}).get("value", ""))
        if not OK_LICENSE.match(lic) or (meta.get("Restrictions") or {}).get("value"):
            print(f"[photo] {title}: licence '{lic}' not usable")
            return "", ""
        artist = _strip((meta.get("Artist") or {}).get("value", "")) or "Unknown author"
        artist = re.sub(r"^(Photo(graph)? by|Author:?)\s*", "", artist, flags=re.I)[:28]
        r = requests.get("https://commons.wikimedia.org/wiki/Special:FilePath/" + urllib.parse.quote(fname) + "?width=700", headers=UA, timeout=30)
        if r.status_code != 200 or not (r.headers.get("content-type") or "").startswith("image/"):
            return "", ""
        from PIL import Image
        im = Image.open(io.BytesIO(r.content)).convert("RGB")
        w, h = im.size
        s = min(w, h)
        left, top = (w - s) // 2, int((h - s) * .12)                          # square crop, biased to the top (faces)
        im = im.crop((left, top, left + s, top + s)).resize((size, size), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=86)
        credit = f"Photo: {artist} · {lic} · Wikimedia Commons"
        print(f"[photo] {title}: {credit}")
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(), credit
    except Exception as e:  # noqa
        print(f"[photo] {title}: {e}")
        return "", ""
