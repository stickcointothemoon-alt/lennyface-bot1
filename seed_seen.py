# seed_seen.py — füllt das Gedächtnis mit bereits beantworteten Tweets

# --- Fix für Py3.12/3.13 (imghdr entfernt) ---
try:
    import imghdr  # noqa
except Exception:
    import types, sys
    m = types.ModuleType("imghdr")
    m.what = lambda f, h=None: None
    sys.modules["imghdr"] = m
# ---------------------------------------------

import os, json, time
import tweepy
from dotenv import load_dotenv

# dieselben Konstanten wie im Bot
STATE_FILE = "/tmp/state.json"
STATE_ENV_VAR = "STATE_SEEN_IDS"
STATE_MAX_IDS = 500

def load_state():
    seen = set()
    # 1) Datei
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                seen = set(str(x) for x in data)
    except FileNotFoundError:
        pass
    except Exception as e:
        print("WARN state file load:", e)
    # 2) ENV
    env_line = os.getenv(STATE_ENV_VAR, "").strip()
    if env_line:
        for tid in env_line.split(","):
            tid = tid.strip()
            if tid:
                seen.add(tid)
    return seen

def save_state(seen):
    try:
        recent = sorted({str(x) for x in seen}, key=lambda s: int(s), reverse=True)[:STATE_MAX_IDS]
    except Exception:
        recent = list({str(x) for x in seen})[:STATE_MAX_IDS]
    # Datei
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(recent, f)
    except Exception as e:
        print("WARN state file save:", e)
    # Laufzeit-ENV aktualisieren (für Sichtprüfung in Logs)
    os.environ[STATE_ENV_VAR] = ",".join(recent)
    print(f"Saved {len(recent)} IDs to state. (Top example: {recent[:3]})")

def main():
    load_dotenv()  # lokal ok, auf Heroku ignoriert
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
    print(f"✅ Logged in as @{me.data.username} ({me_id})")

    seen = load_state()
    before = len(seen)

    # Hole die letzten 200 Tweets des Bots
    resp = client.get_users_tweets(
        id=me_id,
        max_results=100, # bis zu 100 pro Page
        tweet_fields=["referenced_tweets","in_reply_to_user_id","created_at"],
        expansions=None
    )
    data = resp.data or []

    # Falls Paginierung vorhanden, eine zweite Seite holen (insgesamt ~200)
    if resp.meta and resp.meta.get("next_token"):
        resp2 = client.get_users_tweets(
            id=me_id,
            max_results=100,
            pagination_token=resp.meta["next_token"],
            tweet_fields=["referenced_tweets","in_reply_to_user_id","created_at"],
        )
        if resp2.data:
            data += resp2.data

    added = 0
    for tw in data:
        # Wir interessieren uns nur für Antworten (reply)
        # d.h. der eigene Tweet referenziert einen anderen Tweet als "replied_to"
        refs = getattr(tw, "referenced_tweets", None) or []
        for r in refs:
            if r["type"] == "replied_to":
                target_id = str(r["id"])
                if target_id not in seen:
                    seen.add(target_id)
                    added += 1

    save_state(seen)
    after = len(seen)
    print(f"📦 Seed done. Previously had {before}, added {added}, now {after} IDs remembered.")

if __name__ == "__main__":
    main()
