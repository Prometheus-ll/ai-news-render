"""Check that Facebook, Instagram and YouTube are connected. Run it from the 'Check connections' workflow.
Prints OK / MISSING / FAILED for each platform and, for Instagram, the account id to save as IG_USER_ID."""
import os, sys, requests

GRAPH = "https://graph.facebook.com/v21.0"


def facebook():
    page, tok = os.environ.get("FB_PAGE_ID"), os.environ.get("FB_PAGE_TOKEN")
    if not (page and tok):
        print("FACEBOOK : MISSING - add secrets FB_PAGE_ID and FB_PAGE_TOKEN"); return
    r = requests.get(f"{GRAPH}/{page}", params={"fields": "name,instagram_business_account{id,username}", "access_token": tok}, timeout=30)
    if r.status_code != 200:
        print(f"FACEBOOK : FAILED - {r.text[:300]}"); return
    d = r.json()
    print(f"FACEBOOK : OK - page '{d.get('name')}'")
    ig = d.get("instagram_business_account")
    if ig:
        print(f"INSTAGRAM: linked account @{ig.get('username')}  ->  IG_USER_ID = {ig.get('id')}")
        if not os.environ.get("IG_USER_ID"):
            print("           Add that number as the GitHub secret IG_USER_ID to turn Instagram posting on.")
    else:
        print("INSTAGRAM: no Instagram professional account is linked to this Page (or the token lacks instagram_basic).")
        print("           Link it in Facebook Page settings > Linked accounts, then create a new token with the Instagram permissions.")


def instagram():
    ig, tok = os.environ.get("IG_USER_ID"), os.environ.get("FB_PAGE_TOKEN")
    if not ig:
        print("INSTAGRAM: posting is OFF (secret IG_USER_ID not set)"); return
    r = requests.get(f"{GRAPH}/{ig}", params={"fields": "username,media_count", "access_token": tok}, timeout=30)
    print(f"INSTAGRAM: OK - @{r.json().get('username')}, {r.json().get('media_count')} posts" if r.status_code == 200
          else f"INSTAGRAM: FAILED - {r.text[:300]}")


def youtube():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import youtube as yt
    if not yt.enabled():
        print("YOUTUBE  : MISSING - add secrets YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN"); return
    try:
        tok = yt.access_token()
    except Exception as e:  # noqa
        print(f"YOUTUBE  : FAILED - {e}"); return
    r = requests.get("https://www.googleapis.com/youtube/v3/channels", params={"part": "snippet", "mine": "true"},
                     headers={"Authorization": f"Bearer {tok}"}, timeout=30)
    items = r.json().get("items", []) if r.status_code == 200 else []
    if items:
        print(f"YOUTUBE  : OK - channel '{items[0]['snippet']['title']}'")
    else:
        print(f"YOUTUBE  : token works but no channel was returned ({r.status_code}). The token may lack the youtube scope, or the Google account has no channel.")
        print("           (Upload needs only youtube.upload; this check also needs youtube.readonly - an upload can still work.)")


if __name__ == "__main__":
    facebook(); instagram(); youtube()
