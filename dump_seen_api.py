# dump_seen_api.py — liest die letzten Antworten des Bot-Accounts aus der X API
# und gibt die Ziel-Tweet-IDs als CSV aus (für STATE_SEEN_IDS)

# --- Fix für Py3.12/3.13 (imghdr entfernt) ---
try:
    import imghdr  # noqa
except Exception:
    import types, sys
    m = types.ModuleType("imghdr")
    m.what = lambda f, h=None: None
    sys.modules["imghdr"] = m
# ---------------------------------------------

import os, tweepy
from dotenv import load_dotenv

def main():
    load_dotenv()
    BT=os.getenv("X_BEARER_TOKEN")
    CK=os.getenv("X_API_KEY")
    CS=os.getenv("X_API_SECRET")
    AT=os.getenv("X_ACCESS_TOKEN")
    AS=os.getenv("X_ACCESS_SECRET")
    if not all([BT,CK,CS,AT,AS]):
        print("❌ X keys missing in env.")
        return

    client=tweepy.Client(
        bearer_token=BT, consumer_key=CK, consumer_secret=CS,
        access_token=AT, access_token_secret=AS,
        wait_on_rate_limit=True
    )

    me = client.get_me(user_auth=True)
    me_id = me.data.id

    ids = []
    # bis ~200 eigene Tweets holen (max 100 je Seite)
    resp = client.get_users_tweets(
        id=me_id,
        max_results=100,
        tweet_fields=["referenced_tweets"]
    )
    data = resp.data or []
    if resp.meta and resp.meta.get("next_token"):
        resp2 = client.get_users_tweets(
            id=me_id,
            max_results=100,
            pagination_token=resp.meta["next_token"],
            tweet_fields=["referenced_tweets"]
        )
        if resp2.data:
            data += resp2.data

    for tw in data:
        refs = getattr(tw, "referenced_tweets", None) or []
        for r in refs:
            if r["type"] == "replied_to":
                ids.append(str(r["id"]))

    # Duplikate entfernen, etwas sortieren (optional)
    try:
        ids = sorted(set(ids), key=lambda s: int(s), reverse=True)
    except Exception:
        ids = list(set(ids))

    if not ids:
        print("⚠️ Keine reply-IDs gefunden.")
    else:
        print(",".join(ids))

if __name__ == "__main__":
    main()
