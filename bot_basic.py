# bot_basic.py
# v2025-11-12 — stable V1.1 posting + mentions gate + state auto-backup (optional)

import os
import re
import json
import time
import random
import logging
import requests
from datetime import datetime, timezone
from typing import List, Set, Optional

import tweepy  # 4.14.0 (du hast das schon)

# ---------- Logging ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger(__name__)

# ---------- ENV ----------
X_API_KEY = os.getenv("X_API_KEY") or os.getenv("TWITTER_API_KEY") or ""
X_API_SECRET = os.getenv("X_API_SECRET") or os.getenv("TWITTER_API_SECRET") or ""
X_ACCESS_TOKEN = os.getenv("X_ACCESS_TOKEN") or ""
X_ACCESS_SECRET = os.getenv("X_ACCESS_SECRET") or ""

# Verhalten
REPLY_PROBABILITY = float(os.getenv("REPLY_PROBABILITY", "0.6"))
MEME_PROBABILITY  = float(os.getenv("MEME_PROBABILITY", "0.3"))
ONLY_ORIGINAL     = os.getenv("ONLY_ORIGINAL", "1") == "1"
COOLDOWN_S        = int(os.getenv("COOLDOWN_S", "300"))
READ_COOLDOWN_S   = int(os.getenv("READ_COOLDOWN_S", "6"))
MAX_REPLIES_PER_KOL_PER_DAY = int(os.getenv("MAX_REPLIES_PER_KOL_PER_DAY", "3"))

TARGET_IDS = [t.strip() for t in os.getenv("TARGET_IDS", "").split(",") if t.strip()]

# Mentions Gate
MY_BOT_HANDLE = os.getenv("MY_BOT_HANDLE", "lennyface_bot")  # ohne '@'
MENTIONS_MODE = os.getenv("MENTIONS_MODE", "direct").lower()  # off | direct | all

# State/Backup
STATE_FILE = "/tmp/state.json"
STATE_SEEN_IDS = os.getenv("STATE_SEEN_IDS", "")
HEROKU_API_KEY = os.getenv("HEROKU_API_KEY", "")
HEROKU_APP_NAME = os.getenv("HEROKU_APP_NAME", "")
BACKUP_EVERY_N_WRITES = int(os.getenv("BACKUP_EVERY_N_WRITES", "25"))

# Grok (wir nutzen’s nur, wenn KEY da ist; sonst fallback Sätze)
GROK_API_KEY = os.getenv("GROK_API_KEY", "")
GROK_BASE_URL = os.getenv("GROK_BASE_URL", "https://api.x.ai")
GROK_MODEL = os.getenv("GROK_MODEL", "grok-3")

# ---------- Twitter Clients ----------
def build_clients():
    # V1.1 für Post + Media (robust)
    auth = tweepy.OAuth1UserHandler(
        X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET
    )
    api_v1 = tweepy.API(auth, wait_on_rate_limit=True)

    # V2 Client für Lesen (wenn Keys stimmen)
    client_v2 = tweepy.Client(
        consumer_key=X_API_KEY,
        consumer_secret=X_API_SECRET,
        access_token=X_ACCESS_TOKEN,
        access_token_secret=X_ACCESS_SECRET,
        wait_on_rate_limit=True
    )
    return api_v1, client_v2

API_V1, CLIENT_V2 = build_clients()

# ---------- State ----------
def load_state() -> Set[str]:
    # 1) /tmp/state.json
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            seen = set(str(x) for x in data)
            log.info(f"State loaded: {len(seen)} replied tweet IDs remembered")
            return seen
    except Exception as e:
        log.warning(f"State read failed, fallback to env: {e}")

    # 2) ENV
    if STATE_SEEN_IDS:
        seen = set(i.strip() for i in STATE_SEEN_IDS.split(",") if i.strip())
        log.info(f"State loaded from env: {len(seen)} ids")
        return seen

    log.info("State loaded: 0 replied tweet IDs remembered")
    return set()

def write_state(seen: Set[str]):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(seen), f)
    except Exception as e:
        log.warning(f"State write failed: {e}")

_backup_counter = 0
def backup_env_state_if_possible(seen: Set[str]):
    """Optional: schreibe STATE_SEEN_IDS in Heroku Config, wenn KEY+APP vorhanden."""
    global _backup_counter
    _backup_counter += 1
    if not HEROKU_API_KEY or not HEROKU_APP_NAME:
        return
    if _backup_counter < BACKUP_EVERY_N_WRITES:
        return
    _backup_counter = 0

    try:
        ids_str = ",".join(sorted(seen))
        url = f"https://api.heroku.com/apps/{HEROKU_APP_NAME}/config-vars"
        headers = {
            "Accept": "application/vnd.heroku+json; version=3",
            "Authorization": f"Bearer {HEROKU_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {"STATE_SEEN_IDS": ids_str}
        r = requests.patch(url, headers=headers, data=json.dumps(payload), timeout=30)
        if r.status_code in (200, 201):
            log.info(f"Backup OK — {len(seen)} IDs in STATE_SEEN_IDS gespeichert.")
        else:
            log.warning(f"Backup failed {r.status_code}: {r.text[:200]}")
    except Exception as e:
        log.warning(f"Backup exception: {e}")

# ---------- Utils ----------
def pick_meme(meme_dir: str = "memes") -> Optional[str]:
    try:
        files = [f for f in os.listdir(meme_dir) if f.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp"))]
        if not files:
            return None
        return os.path.join(meme_dir, random.choice(files))
    except Exception:
        return None

def upload_media_if_any(api_v1: tweepy.API, meme_path: Optional[str]) -> Optional[List[str]]:
    if not meme_path or not os.path.exists(meme_path):
        return None
    try:
        media = api_v1.media_upload(meme_path)
        return [str(media.media_id)]
    except Exception as e:
        log.warning(f"Meme upload failed: {e}")
        return None

def is_mention(tweet) -> bool:
    try:
        ents = getattr(tweet, "entities", None)
        if not ents:
            return False
        m = ents.get("mentions") or []
        return len(m) > 0
    except Exception:
        return False

def is_direct_mention_to_me(text: str, my_handle: str) -> bool:
    tags = re.findall(r'@\w+', (text or "").lower())
    return bool(tags) and tags[0] == f"@{my_handle.lower()}"

def vary_lenny_line() -> str:
    variants = [
        "LENNY strong. $LENNY to the 🌕 ( ͡° ͜ʖ ͡°)",
        "Powered by $LENNY — meme magic to the 🌕",
        "$LENNY on duty. Stay cheeky, stay degen.",
        "Lenny approves. $LENNY > fiat.",
        "WAGMI, $LENNY gang. ( ͡~ ͜ʖ ͡°)"
    ]
    return random.choice(variants)

def grok_reply(prompt: str) -> Optional[str]:
    if not GROK_API_KEY:
        return None
    try:
        # Minimaler JSON-Aufruf (kein Streaming)
        resp = requests.post(
            f"{GROK_BASE_URL}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": GROK_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a cheeky crypto reply bot. Be witty, short, and always shill $LENNY. ALWAYS reply in English. No hashtags unless natural."
                    },
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.8,
                "max_tokens": 80
            },
            timeout=20
        )
        if resp.status_code != 200:
            log.warning(f"Grok {resp.status_code}: {resp.text[:200]}")
            return None
        data = resp.json()
        text = data["choices"][0]["message"]["content"].strip()
        return text
    except Exception as e:
        log.warning(f"Grok error: {e}")
        return None

# ---------- Lesen + Antworten ----------
def fetch_recent_tweets_for_user(user_id: str, limit: int = 5):
    """Hole letzte Tweets (exkl. Retweets/Replies wenn ONLY_ORIGINAL=1)."""
    try:
        ex = ["referenced_tweets.id"]
        if ONLY_ORIGINAL:
            # exclude RETWEETS & REPLIES
            ex = ["retweets", "replies"]
        resp = CLIENT_V2.get_users_tweets(
            id=user_id,
            max_results=min(5, limit),
            tweet_fields=["created_at","entities","conversation_id"],
            expansions=[],
            exclude=ex
        )
        if resp.data is None:
            return []
        return resp.data
    except tweepy.TooManyRequests:
        # Rate limit
        raise
    except Exception as e:
        log.warning(f"Fetch tweets failed for {user_id}: {e}")
        return []

def build_reply_text(raw_text: str) -> str:
    # 1) Grok wenn verfügbar
    g = grok_reply(raw_text[:500])
    if g:
        # Anhängen eines Lenny-Snippets, um Duplikate zu variieren
        return g + " — " + vary_lenny_line()
    # 2) Fallback
    return f"{vary_lenny_line()}"

def should_reply_this_time() -> bool:
    return random.random() < REPLY_PROBABILITY

def maybe_attach_meme() -> bool:
    return random.random() < MEME_PROBABILITY

def post_reply(api_v1: tweepy.API, text: str, in_reply_to_id: str, meme_path: Optional[str] = None):
    media_ids = upload_media_if_any(api_v1, meme_path)
    # V1.1 Status-Update
    if media_ids:
        return api_v1.update_status(
            status=text,
            in_reply_to_status_id=in_reply_to_id,
            auto_populate_reply_metadata=True,
            media_ids=media_ids
        )
    else:
        return api_v1.update_status(
            status=text,
            in_reply_to_status_id=in_reply_to_id,
            auto_populate_reply_metadata=True
        )

# ---------- Tageszähler für KOLs ----------
# (Einfacher In-Memory Zähler; resetten wir grob alle ~24h per Epoch-Tag)
_per_kol_count = {}
_last_reset_day = None

def may_reply_to_kol_today(kol_id: str) -> bool:
    global _last_reset_day
    now_day = datetime.now(timezone.utc).timetuple().tm_yday
    if _last_reset_day != now_day:
        _per_kol_count.clear()
        _last_reset_day = now_day
    _per_kol_count.setdefault(kol_id, 0)
    return _per_kol_count[kol_id] < MAX_REPLIES_PER_KOL_PER_DAY

def bump_kol(kol_id: str):
    _per_kol_count[kol_id] = _per_kol_count.get(kol_id, 0) + 1

# ---------- Main Loop ----------
def main_loop():
    seen = load_state()
    log.info(f"Started as @{MY_BOT_HANDLE} — targets: {len(TARGET_IDS)}")

    while True:
        try:
            # KOLs
            for kol in TARGET_IDS:
                if not may_reply_to_kol_today(kol):
                    continue

                tweets = fetch_recent_tweets_for_user(kol, limit=5)

                for tw in tweets:
                    tid = str(tw.id)
                    if tid in seen:
                        continue

                    # Text extrahieren
                    text = getattr(tw, "text", "") or ""

                    # Mentions-Gate:
                    if is_mention(tw):
                        if MENTIONS_MODE == "off":
                            seen.add(tid); write_state(seen); backup_env_state_if_possible(seen); continue
                        elif MENTIONS_MODE == "direct":
                            if not is_direct_mention_to_me(text, MY_BOT_HANDLE):
                                seen.add(tid); write_state(seen); backup_env_state_if_possible(seen); continue
                        # "all" = alles erlaubt
                    else:
                        # kein Mention → normale KOL-Logik, aber evtl. Skipping nach Wahrscheinlichkeit
                        if not should_reply_this_time():
                            seen.add(tid); write_state(seen); backup_env_state_if_possible(seen); continue

                    # Reply bauen
                    out = build_reply_text(text)
                    meme_path = pick_meme("memes") if maybe_attach_meme() else None

                    try:
                        post_reply(API_V1, out, tid, meme_path)
                        log.info(f"Reply → {tid} | {out[:120]}{' [+meme]' if meme_path else ''}")
                        seen.add(tid)
                        write_state(seen)
                        backup_env_state_if_possible(seen)
                        bump_kol(kol)
                        time.sleep(READ_COOLDOWN_S)
                    except tweepy.TooManyRequests:
                        # Rate Limit
                        sleep_s = 900
                        log.warning(f"Rate limit exceeded. Sleeping for {sleep_s} seconds.")
                        time.sleep(sleep_s)
                    except Exception as e:
                        log.warning(f"Reply failed: {e}")
                        # markiere trotzdem als gesehen, um Loops zu vermeiden
                        seen.add(tid)
                        write_state(seen)
                        backup_env_state_if_possible(seen)
                        time.sleep(READ_COOLDOWN_S)

                time.sleep(READ_COOLDOWN_S)

            # Grundschlaf zwischen KOL-Runden
            time.sleep(COOLDOWN_S)

        except tweepy.TooManyRequests:
            sleep_s = 900
            log.warning(f"Rate limit exceeded. Sleeping for {sleep_s} seconds.")
            time.sleep(sleep_s)
        except Exception as e:
            log.warning(f"Loop error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main_loop()
