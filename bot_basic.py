# bot_basic.py
# -----------------------------------------------------------
# Lenny-Bot – stabile Basis mit:
# - KORREKTER Medienbehandlung (media_ids statt media)
# - Fallback auf v1.1 bei Problemen
# - State (/tmp/state.json + ENV STATE_SEEN_IDS)
# - Meme-Auswahl aus ./memes
# - Einfacher Reply-Loop über TARGET_IDS
# -----------------------------------------------------------
import os
import io
import json
import time
import random
import logging
from typing import List, Set, Optional

import tweepy

# -------------------------
# Logging
# -------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# -------------------------
# Env-Helper
# -------------------------
def env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip() in ("1", "true", "True", "yes", "YES")

def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default

def env_csv(name: str) -> List[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]

# -------------------------
# Konfiguration
# -------------------------
X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN")
X_API_KEY      = os.getenv("X_API_KEY")
X_API_SECRET   = os.getenv("X_API_SECRET")
X_ACCESS_TOKEN = os.getenv("X_ACCESS_TOKEN")
X_ACCESS_SECRET= os.getenv("X_ACCESS_SECRET")

TARGET_IDS          = [t for t in env_csv("TARGET_IDS") if t.isdigit()]
ONLY_ORIGINAL       = env_bool("ONLY_ORIGINAL", True)
REPLY_PROBABILITY   = env_float("REPLY_PROBABILITY", 1.0)  # 0..1
MEME_PROBABILITY    = env_float("MEME_PROBABILITY", 0.30)  # 0..1
DEX_REPLY_PROB      = env_float("DEX_REPLY_PROB", 0.50)    # optional

COOLDOWN_S          = env_int("COOLDOWN_S", 300)           # Pause nach Reply-Wellen
READ_COOLDOWN_S     = env_int("READ_COOLDOWN_S", 6)        # kurze Pause zwischen Reads
LOOP_SLEEP_SECONDS  = env_int("LOOP_SLEEP_SECONDS", 240)   # Pause zwischen Loops
PER_KOL_MIN_POLL_S  = env_int("PER_KOL_MIN_POLL_S", 1200)  # Mind. Pause je KOL

MEME_DIR            = "memes"
STATE_PATH          = "/tmp/state.json"  # wird von Dyno überlebt bis Neustart
SEEN_ENV_NAME       = "STATE_SEEN_IDS"   # einmaliger Seed / Backup via Config Var

# -------------------------
# Clients (v2 + v1.1)
# -------------------------
client = tweepy.Client(
    bearer_token=X_BEARER_TOKEN,
    consumer_key=X_API_KEY,
    consumer_secret=X_API_SECRET,
    access_token=X_ACCESS_TOKEN,
    access_token_secret=X_ACCESS_SECRET,
    wait_on_rate_limit=True
)

auth_v1 = tweepy.OAuth1UserHandler(
    X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET
)
api_v1 = tweepy.API(auth_v1, wait_on_rate_limit=True)

# -------------------------
# State: SEEN Tweet-IDs
# -------------------------
def load_state() -> Set[str]:
    seen: Set[str] = set()
    # 1) aus Datei
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                seen |= set(str(x) for x in data if str(x).isdigit())
        except Exception as e:
            logging.warning(f"State-Datei fehlerhaft: {e}")

    # 2) Merge mit ENV (Seed/Backup)
    env_ids = env_csv(SEEN_ENV_NAME)
    for x in env_ids:
        if x.isdigit():
            seen.add(x)

    logging.info(f"State geladen: {len(seen)} bereits beantwortete Tweet-IDs")
    return seen

def save_state(seen: Set[str]) -> None:
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(sorted(seen), f)
    except Exception as e:
        logging.warning(f"State konnte nicht gespeichert werden: {e}")

# -------------------------
# Memes
# -------------------------
ALLOWED_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp")

def ensure_meme_dir() -> None:
    os.makedirs(MEME_DIR, exist_ok=True)

def list_memes() -> List[str]:
    ensure_meme_dir()
    files = []
    for fn in os.listdir(MEME_DIR):
        if fn.lower().endswith(ALLOWED_EXT):
            files.append(os.path.join(MEME_DIR, fn))
    return files

def pick_meme() -> Optional[str]:
    files = list_memes()
    if not files:
        return None
    return random.choice(files)

# -------------------------
# Posting / Replies – FIXED (media_ids statt media)
# -------------------------
def post_meme_with_caption(meme_path: str, caption: str) -> bool:
    try:
        media = api_v1.media_upload(filename=meme_path)  # v1.1 Upload
        client.create_tweet(text=caption, media_ids=[media.media_id])  # v2 Tweet
        logging.info("Meme-Post OK (v2 with media_ids)")
        return True
    except tweepy.Forbidden as e:
        # Manche Accounts/API-Stufen blocken v2+media → Fallback v1.1
        logging.warning(f"v2 create_tweet forbidden ({e}); fallback v1.1")
        try:
            api_v1.update_status(status=caption, media_ids=[media.media_id])
            logging.info("Meme-Post OK (v1.1 fallback)")
            return True
        except Exception as e2:
            logging.warning(f"Fallback v1.1 fehlgeschlagen: {e2}")
            return False
    except Exception as e:
        logging.warning(f"Meme-Post fehlgeschlagen: {e}")
        return False

def reply_with_text(target_tweet_id: int, reply_text: str) -> bool:
    try:
        client.create_tweet(
            text=reply_text,
            reply={'in_reply_to_tweet_id': str(target_tweet_id)}
        )
        logging.info(f"Reply (nur Text) OK → {target_tweet_id}")
        return True
    except tweepy.Forbidden as e:
        logging.warning(f"v2 reply forbidden ({e}); fallback v1.1")
        try:
            api_v1.update_status(
                status=reply_text,
                in_reply_to_status_id=target_tweet_id,
                auto_populate_reply_metadata=True
            )
            logging.info(f"Reply (nur Text) OK (v1.1 fallback) → {target_tweet_id}")
            return True
        except Exception as e2:
            logging.warning(f"Fallback v1.1 reply failed: {e2}")
            return False
    except Exception as e:
        logging.warning(f"Reply fehlgeschlagen: {e}")
        return False

def reply_with_meme(target_tweet_id: int, reply_text: str, meme_path: str) -> bool:
    try:
        media = api_v1.media_upload(filename=meme_path)
        client.create_tweet(
            text=reply_text,
            reply={'in_reply_to_tweet_id': str(target_tweet_id)},
            media_ids=[media.media_id]
        )
        logging.info(f"Reply mit Meme OK → {target_tweet_id}")
        return True
    except tweepy.Forbidden as e:
        logging.warning(f"v2 reply forbidden ({e}); fallback v1.1")
        try:
            api_v1.update_status(
                status=reply_text,
                media_ids=[media.media_id],
                in_reply_to_status_id=target_tweet_id,
                auto_populate_reply_metadata=True
            )
            logging.info(f"Reply mit Meme OK (v1.1 fallback) → {target_tweet_id}")
            return True
        except Exception as e2:
            logging.warning(f"Fallback v1.1 reply failed: {e2}")
            return False
    except Exception as e:
        logging.warning(f"Reply fehlgeschlagen: {e}")
        return False

# -------------------------
# Text-Generator (simpel, immer $LENNY shillen)
# -------------------------
LENNY_TAG = "$LENNY"

FALLBACK_LINES = [
    f"{LENNY_TAG} ist wieder am Marschieren ( ͡° ͜ʖ ͡°)  🚀",
    f"Nur echte Chads hodln {LENNY_TAG} ( ͡° ͜ʖ ͡°) ✊",
    f"Mehr Memes, mehr Reichweite, mehr {LENNY_TAG}! ( ͡° ͜ʖ ͡°)",
    f"Lass die Timeline lachen – buy {LENNY_TAG}! ( ͡° ͜ʖ ͡°)"
]

def make_reply_text() -> str:
    return random.choice(FALLBACK_LINES)

def make_caption_text() -> str:
    return random.choice(FALLBACK_LINES)

# -------------------------
# Bot-Loop (einfach & stabil)
# -------------------------
def should_reply() -> bool:
    return random.random() <= REPLY_PROBABILITY

def use_meme() -> bool:
    return random.random() <= MEME_PROBABILITY

def get_latest_user_tweets(user_id: str) -> List[tweepy.Tweet]:
    # exclude: replies/retweets falls ONLY_ORIGINAL aktiv
    exclude = []
    if ONLY_ORIGINAL:
        exclude = ["replies", "retweets"]
    try:
        resp = client.get_users_tweets(
            id=user_id,
            max_results=5,
            exclude=exclude,
            tweet_fields=["created_at"]
        )
        if resp.data:
            return list(resp.data)
        return []
    except tweepy.TooManyRequests:
        # Rate Limit → kurz schlafen, dann leer zurück
        logging.warning("Rate limit exceeded. Sleeping for 249 seconds.")
        time.sleep(249)
        return []
    except Exception as e:
        logging.warning(f"get_users_tweets Fehler: {e}")
        return []

def main_loop():
    logging.info(f"Started as @lennyface_bot — targets: {len(TARGET_IDS)}")

    ensure_meme_dir()
    seen = load_state()
    last_poll_at = {}  # user_id -> last poll timestamp

    while True:
        loop_start = time.time()

        for uid in TARGET_IDS:
            # Rate-Limit / Poll-Minimum je KOL
            last_t = last_poll_at.get(uid, 0)
            if time.time() - last_t < PER_KOL_MIN_POLL_S:
                continue
            last_poll_at[uid] = time.time()

            tweets = get_latest_user_tweets(uid)
            if not tweets:
                time.sleep(READ_COOLDOWN_S)
                continue

            for tw in tweets:
                tid = str(tw.id)
                if tid in seen:
                    continue

                if not should_reply():
                    continue

                text = make_reply_text()

                ok = False
                if use_meme():
                    meme = pick_meme()
                    if meme:
                        ok = reply_with_meme(int(tid), text, meme)
                    else:
                        ok = reply_with_text(int(tid), text)
                else:
                    ok = reply_with_text(int(tid), text)

                if ok:
                    seen.add(tid)
                    save_state(seen)
                    time.sleep(COOLDOWN_S)  # kleine Pause nach Erfolg
                else:
                    # auch bei Fail merken, damit wir nicht spammen
                    seen.add(tid)
                    save_state(seen)
                    time.sleep(READ_COOLDOWN_S)

                # sanfte Pause zwischen Tweets
                time.sleep(READ_COOLDOWN_S)

        # Loop-Pause
        elapsed = time.time() - loop_start
        if elapsed < LOOP_SLEEP_SECONDS:
            time.sleep(LOOP_SLEEP_SECONDS - elapsed)

# -------------------------
# Start
# -------------------------
if __name__ == "__main__":
    # Optional: Auto-Fetch, falls du FETCH_MEMES_URL nutzt und Procfile NICHT "fetch_memes && bot" macht.
    # Einfach aktivieren, wenn gewünscht:
    # try:
    #     from fetch_memes import fetch_if_configured
    #     fetch_if_configured(dest_dir=MEME_DIR)
    # except Exception as e:
    #     logging.warning(f"Auto-Fetch übersprungen: {e}")
    main_loop()
