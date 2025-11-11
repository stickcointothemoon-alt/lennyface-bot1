import os
import time
import json
import random
import logging
import tweepy
from typing import Optional, Set, List
from pathlib import Path

# -------------------------
# Logging
# -------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger(__name__)

# -------------------------
# ENV / Konfiguration
# -------------------------
X_API_KEY       = os.getenv("X_API_KEY")
X_API_SECRET    = os.getenv("X_API_SECRET")
X_ACCESS_TOKEN  = os.getenv("X_ACCESS_TOKEN")
X_ACCESS_SECRET = os.getenv("X_ACCESS_SECRET")
X_BEARER_TOKEN  = os.getenv("X_BEARER_TOKEN")

TARGET_IDS_CSV  = os.getenv("TARGET_IDS", "")
ONLY_ORIGINAL   = os.getenv("ONLY_ORIGINAL", "1") == "1"

REPLY_PROBABILITY = float(os.getenv("REPLY_PROBABILITY", "1.0"))
DEX_REPLY_PROB    = float(os.getenv("DEX_REPLY_PROB", "0.5"))

LOOP_SLEEP_SECONDS   = int(os.getenv("LOOP_SLEEP_SECONDS", "240"))
READ_COOLDOWN_S      = int(os.getenv("READ_COOLDOWN_S", "6"))
MAX_REPLIES_PER_KOL_PER_DAY = int(os.getenv("MAX_REPLIES_PER_KOL_PER_DAY", "3"))

MEME_PROBABILITY     = float(os.getenv("MEME_PROBABILITY", "0.3"))

STATE_FILE = Path("/tmp/state.json")  # lokales Dyno-File
MEME_DIR   = Path("memes")

# -------------------------
# Twitter Clients
# -------------------------

def get_client_v2() -> tweepy.Client:
    # v2 Client: Posts (Text + media_ids) & Replies (in_reply_to_tweet_id)
    return tweepy.Client(
        bearer_token=X_BEARER_TOKEN,
        consumer_key=X_API_KEY,
        consumer_secret=X_API_SECRET,
        access_token=X_ACCESS_TOKEN,
        access_token_secret=X_ACCESS_SECRET,
        wait_on_rate_limit=True,
    )

def get_api_v1() -> tweepy.API:
    # v1.1 API (nur für Media-Upload!)
    auth = tweepy.OAuth1UserHandler(
        X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET
    )
    return tweepy.API(auth, wait_on_rate_limit=True)

# -------------------------
# Seen-State
# -------------------------

def load_seen_state() -> Set[int]:
    seen: Set[int] = set()
    # 1) aus Config Var (STATE_SEEN_IDS, CSV)
    seed_csv = os.getenv("STATE_SEEN_IDS", "").strip()
    if seed_csv:
        for s in seed_csv.split(","):
            s = s.strip()
            if s.isdigit():
                seen.add(int(s))

    # 2) aus /tmp/state.json (vom letzten Dyno-Lauf)
    if STATE_FILE.exists():
        try:
            ids = json.loads(STATE_FILE.read_text())
            for s in ids:
                if str(s).isdigit():
                    seen.add(int(s))
        except Exception as e:
            log.warning("Konnte /tmp/state.json nicht lesen: %s", e)

    log.info("State geladen: %d bereits beantwortete Tweet-IDs", len(seen))
    return seen

def save_seen_state(seen: Set[int]) -> None:
    try:
        STATE_FILE.write_text(json.dumps(sorted(list(seen))))
    except Exception as e:
        log.warning("Konnte State nicht speichern: %s", e)

# -------------------------
# Meme-Handling
# -------------------------

VALID_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

def pick_meme() -> Optional[Path]:
    if not MEME_DIR.exists():
        return None
    files = [p for p in MEME_DIR.iterdir() if p.is_file() and p.suffix.lower() in VALID_EXT]
    if not files:
        return None
    return random.choice(files)

def upload_media_return_id(image_path: Path) -> int:
    api = get_api_v1()
    media = api.media_upload(filename=str(image_path))
    return media.media_id

# -------------------------
# Tweet/Reply – RICHTIGER Weg (kein reply={}, kein media={})
# -------------------------

def post_tweet(client: tweepy.Client, text: str, image_path: Optional[Path] = None):
    kwargs = {"text": text}
    if image_path:
        try:
            media_id = upload_media_return_id(image_path)
            kwargs["media_ids"] = [media_id]
        except Exception as e:
            log.warning("Meme-Upload fehlgeschlagen: %s", e)
    client.create_tweet(**kwargs)

def reply_to_tweet(client: tweepy.Client, text: str, reply_to_id: int, image_path: Optional[Path] = None):
    kwargs = {"text": text, "in_reply_to_tweet_id": reply_to_id}
    if image_path:
        try:
            media_id = upload_media_return_id(image_path)
            kwargs["media_ids"] = [media_id]
        except Exception as e:
            log.warning("Meme-Upload fehlgeschlagen: %s", e)
    client.create_tweet(**kwargs)

# -------------------------
# Bot-Logik (minimal & robust)
# -------------------------

def is_original(tweet) -> bool:
    # skip Retweets/Replies wenn ONLY_ORIGINAL=1
    if not ONLY_ORIGINAL:
        return True
    if getattr(tweet, "referenced_tweets", None):
        # hat Referenzen → ist RT/Reply/Quote
        return False
    return True

def build_reply_text() -> str:
    # Hier könntest du GROK-Logik einbauen – erst mal simpel:
    base = "LENNY strong. $LENNY to the 🌕 ( ͡° ͜ʖ ͡°) #Lenny #Solana"
    return base

def loop():
    client = get_client_v2()
    me = client.get_me().data
    log.info("Started as @%s — targets: %d", me.username, len(TARGET_IDS_CSV.split(",")) if TARGET_IDS_CSV else 0)

    seen = load_seen_state()

    target_ids: List[str] = [x.strip() for x in TARGET_IDS_CSV.split(",") if x.strip().isdigit()]

    per_kol_replies_today = {tid: 0 for tid in target_ids}
    last_reset = time.time()

    while True:
        # Reset Tageszähler alle 24h
        if time.time() - last_reset > 24*3600:
            per_kol_replies_today = {tid: 0 for tid in target_ids}
            last_reset = time.time()

        try:
            for tid in target_ids:
                if not tid:
                    continue

                # Neueste Tweets des KOL
                resp = client.get_users_tweets(
                    id=tid,
                    max_results=5,
                    tweet_fields=["created_at","referenced_tweets","in_reply_to_user_id"]
                )
                if not resp.data:
                    time.sleep(READ_COOLDOWN_S)
                    continue

                for tw in resp.data:
                    twid = int(tw.id)

                    if twid in seen:
                        continue
                    if not is_original(tw):
                        seen.add(twid)
                        continue
                    if per_kol_replies_today.get(tid, 0) >= MAX_REPLIES_PER_KOL_PER_DAY:
                        continue

                    # Entscheide ob mit Meme
                    use_meme = random.random() < MEME_PROBABILITY
                    meme_path = pick_meme() if use_meme else None

                    text = build_reply_text()
                    try:
                        reply_to_tweet(client, text, reply_to_id=twid, image_path=meme_path)
                        per_kol_replies_today[tid] = per_kol_replies_today.get(tid, 0) + 1
                        seen.add(twid)
                        save_seen_state(seen)
                        log.info("Reply → %s | %s%s",
                                 twid,
                                 text[:80],
                                 " [+meme]" if meme_path else "")
                    except tweepy.TooManyRequests as e:
                        # Rate Limit
                        reset_in = 240
                        log.warning("Rate limit exceeded. Sleeping for %d seconds.", reset_in)
                        time.sleep(reset_in)
                    except Exception as e:
                        log.warning("Reply fehlgeschlagen: %s", e)
                    time.sleep(READ_COOLDOWN_S)

            time.sleep(LOOP_SLEEP_SECONDS)

        except tweepy.TooManyRequests:
            log.warning("Rate limit exceeded. Sleeping for 300 seconds.")
            time.sleep(300)
        except Exception as e:
            log.warning("Loop-Fehler: %s", e)
            time.sleep(10)

if __name__ == "__main__":
    loop()
