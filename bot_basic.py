# bot_basic.py
import os, json, time, random, logging, glob, mimetypes, io
from datetime import datetime, timedelta
from typing import Set, Dict

import tweepy
import requests
from PIL import Image

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger(__name__)

# === Konfiguration aus ENV ===
MEME_PROBABILITY = float(os.getenv("MEME_PROBABILITY", "0.3"))
REPLY_PROBABILITY = float(os.getenv("REPLY_PROBABILITY", "1.0"))
ONLY_ORIGINAL = os.getenv("ONLY_ORIGINAL", "1") == "1"

COOLDOWN_S = int(os.getenv("COOLDOWN_S", "300"))
LOOP_SLEEP_SECONDS = int(os.getenv("LOOP_SLEEP_SECONDS", "240"))
READ_COOLDOWN_S = int(os.getenv("READ_COOLDOWN_S", "6"))

MAX_REPLIES_PER_KOL_PER_DAY = int(os.getenv("MAX_REPLIES_PER_KOL_PER_DAY", "3"))

TARGET_IDS = [t.strip() for t in os.getenv("TARGET_IDS", "").split(",") if t.strip()]

# Heroku Auto-Backup (optional)
HEROKU_APP_NAME = os.getenv("HEROKU_APP_NAME", "").strip()
HEROKU_API_KEY = os.getenv("HEROKU_API_KEY", "").strip()

STATE_FILE = "/tmp/state.json"  # Ephemer, aber überlebt Dyno-Neustarts bis zum nächsten Wechsel


# ========== SEEN STORE ==========
class SeenStore:
    def __init__(self, state_file=STATE_FILE):
        self.state_file = state_file
        self.seen: Set[str] = set()
        self._load_from_env()
        self._load_from_file()
        self._last_backup = time.time()

    def _load_from_env(self):
        raw = os.getenv("STATE_SEEN_IDS", "").strip()
        if raw:
            parts = [p.strip() for p in raw.split(",") if p.strip()]
            self.seen.update(parts)

    def _load_from_file(self):
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.seen.update([str(x) for x in data])
        except FileNotFoundError:
            pass
        except Exception as e:
            log.warning(f"State-Datei konnte nicht gelesen werden: {e}")

    def save_local(self):
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(sorted(self.seen, key=lambda x: int(x)), f)
        except Exception as e:
            log.warning(f"State-Datei konnte nicht gespeichert werden: {e}")

    def backup_to_env(self):
        if not (HEROKU_API_KEY and HEROKU_APP_NAME):
            return  # optional
        try:
            url = f"https://api.heroku.com/apps/{HEROKU_APP_NAME}/config-vars"
            headers = {
                "Accept": "application/vnd.heroku+json; version=3",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {HEROKU_API_KEY}",
            }
            # Heroku max. Länge beachten: Wir schneiden hart, falls gigantisch
            ids_sorted = sorted(self.seen, key=lambda x: int(x), reverse=True)
            joined = ",".join(ids_sorted[:1000])
            requests.patch(url, headers=headers, json={"STATE_SEEN_IDS": joined}, timeout=30)
            log.info("☁️  Backup OK — STATE_SEEN_IDS in Heroku aktualisiert.")
        except Exception as e:
            log.warning(f"Backup fehlgeschlagen: {e}")

    def add(self, tweet_id: str, force_backup=False):
        before = len(self.seen)
        self.seen.add(str(tweet_id))
        if len(self.seen) != before:
            self.save_local()
            # alle 10 neuen IDs oder alle 30 Min → Backup
            if force_backup or (len(self.seen) % 10 == 0) or (time.time() - self._last_backup > 1800):
                self.backup_to_env()
                self._last_backup = time.time()


SEEN = SeenStore()
log.info(f"State geladen: {len(SEEN.seen)} bereits beantwortete Tweet-IDs")


# ========== TWITTER CLIENTS ==========
BT = os.getenv("X_BEARER_TOKEN")
CK = os.getenv("X_API_KEY")
CS = os.getenv("X_API_SECRET")
AT = os.getenv("X_ACCESS_TOKEN")
AS = os.getenv("X_ACCESS_SECRET")

if not all([BT, CK, CS, AT, AS]):
    raise SystemExit("❌ X API Keys fehlen in Config Vars.")

client_v2 = tweepy.Client(
    bearer_token=BT,
    consumer_key=CK,
    consumer_secret=CS,
    access_token=AT,
    access_token_secret=AS,
    wait_on_rate_limit=True,
)

auth_v1 = tweepy.OAuth1UserHandler(CK, CS, AT, AS)
api_v1 = tweepy.API(auth_v1, wait_on_rate_limit=True)

me = client_v2.get_me().data
log.info(f"Started as @{me.username} — targets: {len(TARGET_IDS)}")


# ========== MEME PICK / UPLOAD ==========
def list_memes():
    files = []
    for pat in ("memes/*.jpg", "memes/*.jpeg", "memes/*.png", "memes/*.gif"):
        files.extend(glob.glob(pat))
    return files

def pick_meme():
    files = list_memes()
    if not files:
        return None
    return random.choice(files)

def upload_media_v11(path: str) -> str:
    # Sichere Mime-Erkennung
    mime, _ = mimetypes.guess_type(path)
    if not mime:
        # Fallback: per PIL als PNG/JPEG neu speichern
        with Image.open(path) as im:
            tmp = io.BytesIO()
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGB")
            im.save(tmp, format="PNG", optimize=True)
            tmp.seek(0)
            return api_v1.media_upload(filename="meme.png", file=tmp).media_id_string

    try:
        media = api_v1.media_upload(filename=path)
        return media.media_id_string
    except Exception:
        # Fallback beim Mime-Fehler:
        with Image.open(path) as im:
            tmp = io.BytesIO()
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGB")
            # PNG Fallback
            im.save(tmp, format="PNG", optimize=True)
            tmp.seek(0)
            media = api_v1.media_upload(filename="meme.png", file=tmp)
            return media.media_id_string


# ========== LOGIK ==========
_last_reply_time_per_kol: Dict[str, list] = {}  # user_id -> [timestamps]

def within_daily_limit(user_id: str) -> bool:
    now = time.time()
    arr = _last_reply_time_per_kol.setdefault(user_id, [])
    # purge älter 24h
    cutoff = now - 24*3600
    arr[:] = [t for t in arr if t >= cutoff]
    return len(arr) < MAX_REPLIES_PER_KOL_PER_DAY

def remember_reply(user_id: str):
    _last_reply_time_per_kol.setdefault(user_id, []).append(time.time())

def should_reply_to(tweet) -> bool:
    if str(tweet.id) in SEEN.seen:
        return False
    if ONLY_ORIGINAL and tweet.referenced_tweets:
        # ist Reply/Retweet/Quote
        return False
    # Zufallsfaktor global
    return random.random() < REPLY_PROBABILITY

def craft_text(tweet, author):
    # Sehr simpel, du kannst später GROK einhängen/verschärfen
    base = f"( ͡° ͜ʖ ͡°) $LENNY on Sol — join the cult."
    return base

def reply_with_optional_meme(tweet_id: str, text: str):
    use_meme = (random.random() < MEME_PROBABILITY)
    media_ids = None
    if use_meme:
        meme = pick_meme()
        if meme:
            try:
                mid = upload_media_v11(meme)
                media_ids = [mid]
            except Exception as e:
                log.warning(f"Meme upload failed: {e}")

    # Reply via v2
    try:
        client_v2.create_tweet(text=text, in_reply_to_tweet_id=tweet_id, media={"media_ids": media_ids} if media_ids else None)
        log.info(f"Reply → {tweet_id} | {'[meme]' if media_ids else '[text]'} {text[:80]}")
    except Exception as e:
        log.warning(f"Reply fehlgeschlagen: {e}")
        raise

def loop_once():
    if not TARGET_IDS:
        log.warning("Keine TARGET_IDS gesetzt.")
        time.sleep(10)
        return

    for uid in TARGET_IDS:
        try:
            # Neueste Tweets eines Users
            resp = client_v2.get_users_tweets(id=uid, max_results=5, expansions=["referenced_tweets.id"], tweet_fields=["created_at"])
            tweets = resp.data or []
            for tw in tweets:
                if not should_reply_to(tw):
                    continue
                if not within_daily_limit(uid):
                    continue

                # Antworten:
                try:
                    author = None
                    text = craft_text(tw, author)
                    reply_with_optional_meme(str(tw.id), text)
                    SEEN.add(str(tw.id))        # Sofort merken
                    remember_reply(uid)         # Tageslimit zählen
                    time.sleep(READ_COOLDOWN_S) # leichtes Delay
                except Exception:
                    # Fehler schon geloggt, einfach weiter
                    continue
        except tweepy.TooManyRequests:
            log.warning("Rate-Limit — kurz warten.")
            time.sleep(60)
        except Exception as e:
            log.warning(f"Fehler beim Lesen von {uid}: {e}")
            time.sleep(3)

def main():
    cooldown_until = 0
    while True:
        now = time.time()
        if now < cooldown_until:
            time.sleep(1)
            continue

        loop_once()
        # Grundschlaf
        time.sleep(LOOP_SLEEP_SECONDS)
        # kleiner Cooldown, wenn eben geantwortet wurde
        cooldown_until = time.time() + COOLDOWN_S

if __name__ == "__main__":
    main()
