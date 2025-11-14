import os
import time
import json
import re
import random
import logging
import requests
import traceback
from datetime import datetime, timezone

import tweepy  # v4.14.0

# =========================
# Logging
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger(__name__)

# =========================
# ENV / Konfiguration
# =========================
X_API_KEY       = os.environ.get("X_API_KEY")         # consumer key
X_API_SECRET    = os.environ.get("X_API_SECRET")
X_ACCESS_TOKEN  = os.environ.get("X_ACCESS_TOKEN")
X_ACCESS_SECRET = os.environ.get("X_ACCESS_SECRET")
X_BEARER_TOKEN  = os.environ.get("X_BEARER_TOKEN")

# KOL IDs (kommagetrennt), z. B. "111,222,333"
TARGET_IDS      = [t.strip() for t in os.environ.get("TARGET_IDS","").split(",") if t.strip()]

# Timing / Limits
READ_COOLDOWN_S       = int(os.environ.get("READ_COOLDOWN_S", "6"))
PER_KOL_MIN_POLL_S    = int(os.environ.get("PER_KOL_MIN_POLL_S", "1200"))  # 20 min
LOOP_SLEEP_SECONDS    = int(os.environ.get("LOOP_SLEEP_SECONDS", "240"))   # 4 min
MAX_REPLIES_PER_KOL_PER_DAY = int(os.environ.get("MAX_REPLIES_PER_KOL_PER_DAY", "3"))

# Wahrscheinlichkeit
REPLY_PROBABILITY     = float(os.environ.get("REPLY_PROBABILITY", "1.0"))
DEX_REPLY_PROB        = float(os.environ.get("DEX_REPLY_PROB", "0.5"))
ONLY_ORIGINAL         = os.environ.get("ONLY_ORIGINAL", "1") == "1"

# Meme-Frequenz
MEME_PROBABILITY      = float(os.environ.get("MEME_PROBABILITY", "0.3"))

# Grok
GROK_API_KEY   = os.environ.get("GROK_API_KEY","")
GROK_BASE_URL  = os.environ.get("GROK_BASE_URL","https://api.x.ai")
GROK_MODEL     = os.environ.get("GROK_MODEL","grok-3")

# Heroku-Config schreiben (für STATE_SEEN_IDS Backup)
HEROKU_API_KEY  = os.environ.get("HEROKU_API_KEY","")
HEROKU_APP_NAME = os.environ.get("HEROKU_APP_NAME","")

# Handle für Mentions-Check (ohne @)
BOT_HANDLE = os.environ.get("BOT_HANDLE", "lennyface_bot").lstrip("@")

# =========================
# Clients: v2 + v1.1
# =========================
def make_clients():
    # v2 Client (lesen & tweeten)
    v2 = tweepy.Client(
        bearer_token=X_BEARER_TOKEN,
        consumer_key=X_API_KEY,
        consumer_secret=X_API_SECRET,
        access_token=X_ACCESS_TOKEN,
        access_token_secret=X_ACCESS_SECRET,
        wait_on_rate_limit=True,
    )
    # v1.1 API (nur für Media Upload)
    auth = tweepy.OAuth1UserHandler(
        X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET
    )
    v1 = tweepy.API(auth, wait_on_rate_limit=True)
    return v2, v1

client, api_v1 = make_clients()

# =========================
# SEEN / State
# =========================
SEEN = set()

def load_seen_from_env():
    raw = os.environ.get("STATE_SEEN_IDS","").strip()
    if not raw:
        return
    for token in re.split(r"[,\s]+", raw):
        if token.isdigit():
            SEEN.add(token)

def _set_config_vars(patch: dict):
    """Schreibt Werte in Heroku Config Vars (ohne CLI)."""
    if not (HEROKU_API_KEY and HEROKU_APP_NAME):
        return  # lokal leise ignorieren
    url = f"https://api.heroku.com/apps/{HEROKU_APP_NAME}/config-vars"
    headers = {
        "Authorization": f"Bearer {HEROKU_API_KEY}",
        "Accept": "application/vnd.heroku+json; version=3",
        "Content-Type": "application/json",
    }
    try:
        r = requests.patch(url, headers=headers, data=json.dumps(patch), timeout=10)
        r.raise_for_status()
        # lokale Env im Dyno aktualisieren
        for k,v in patch.items():
            os.environ[k] = v
    except Exception:
        pass

_since_backup = 0
_BACKUP_EVERY = 30  # nach 30 neuen IDs sichern

def already_replied(tweet_id: str) -> bool:
    return tweet_id in SEEN

def remember_and_maybe_backup(tweet_id: str):
    """Tweet-ID merken und nach X neuen IDs in STATE_SEEN_IDS schreiben."""
    global _since_backup
    if tweet_id and tweet_id.isdigit() and tweet_id not in SEEN:
        SEEN.add(tweet_id)
        _since_backup += 1
    if _since_backup >= _BACKUP_EVERY:
        _since_backup = 0
        csv = ",".join(SEEN)
        _set_config_vars({"STATE_SEEN_IDS": csv})
        log.info("State backup: %d IDs in STATE_SEEN_IDS gespeichert.", len(SEEN))

def save_seen_now():
    csv = ",".join(SEEN)
    _set_config_vars({"STATE_SEEN_IDS": csv})
    log.info("State backup (manual): %d IDs gespeichert.", len(SEEN))

load_seen_from_env()
log.info("State loaded: %d replied tweet IDs remembered", len(SEEN))

# =========================
# Helfer: Grok
# =========================
GROK_SYSTEM_PROMPT = (
    "You are LENNY, a cheeky but helpful shill-bot who ALWAYS shills $LENNY. "
    "Reply in short, punchy, funny English. Avoid duplicate text, vary wording. "
    "Add 1-2 crypto hashtags (e.g., #Lenny #Solana #Memecoins) when relevant."
)

def grok_generate(prompt: str) -> str:
    if not GROK_API_KEY:
        return ""
    try:
        url = f"{GROK_BASE_URL}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {GROK_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": GROK_MODEL,
            "messages": [
                {"role":"system","content":GROK_SYSTEM_PROMPT},
                {"role":"user","content":prompt},
            ],
            "temperature": 0.9,
            "max_tokens": 96,
        }
        r = requests.post(url, headers=headers, json=payload, timeout=20)
        r.raise_for_status()
        data = r.json()
        text = data["choices"][0]["message"]["content"].strip()
        return text
    except Exception as e:
        log.warning("Grok failed: %s", e)
        return ""

def fallback_shill():
    templates = [
        "LENNY strong. $LENNY to the 🌕 ( ͡° ͜ʖ ͡°) #Lenny #Solana",
        "Oi, that’s cute—now watch $LENNY run. 🌕 #Memecoins #Lenny",
        "Chads hold $LENNY, paper hands fold. Your move. #Crypto #Lenny",
    ]
    return random.choice(templates)

# =========================
# Helfer: Tweets holen
# =========================
def fetch_user_tweets(user_id: str, since_id: str|None=None):
    """
    Holt die neusten Tweets eines Users (exclude: replies/retweets je nach ONLY_ORIGINAL).
    Liefert Liste von tweepy.Tweet-Objekten (neuste zuerst).
    """
    try:
        exclude = ["retweets"]
        if ONLY_ORIGINAL:
            exclude.append("replies")
        resp = client.get_users_tweets(
            id=user_id,
            max_results=10,
            since_id=since_id,
            exclude=exclude
        )
        if not resp or not resp.data:
            return []
        return list(resp.data)
    except tweepy.TweepyException as e:
        if "429" in str(e) or "Too Many Requests" in str(e):
            log.warning("Rate limit exceeded. Sleeping for %d seconds.", LOOP_SLEEP_SECONDS)
            time.sleep(LOOP_SLEEP_SECONDS)
            return []
        log.warning("Fetch tweets failed for %s: %s", user_id, e)
        return []
    except Exception as e:
        log.warning("Fetch tweets failed for %s: %s", user_id, e)
        return []

def fetch_mentions(my_user_id: str, since_id: str|None=None):
    try:
        resp = client.get_users_mentions(
            id=my_user_id,
            since_id=since_id,
            max_results=10,
        )
        if not resp or not resp.data:
            return []
        return list(resp.data)
    except tweepy.TweepyException as e:
        if "429" in str(e) or "Too Many Requests" in str(e):
            log.warning("Rate limit exceeded. Sleeping for %d seconds.", LOOP_SLEEP_SECONDS)
            time.sleep(LOOP_SLEEP_SECONDS)
            return []
        log.warning("Fetch mentions failed: %s", e)
        return []
    except Exception as e:
        log.warning("Fetch mentions failed: %s", e)
        return []

# =========================
# Media Upload (v1.1) + Tweet (v2)
# =========================
def choose_meme(path="memes"):
    try:
        files = [f for f in os.listdir(path) if f.lower().endswith((".jpg",".jpeg",".png",".gif"))]
        if not files:
            return None
        return os.path.join(path, random.choice(files))
    except Exception:
        return None

def upload_media_get_id(filepath: str) -> str|None:
    try:
        media = api_v1.media_upload(filename=filepath)
        return media.media_id_string
    except Exception as e:
        log.warning("Meme upload failed: %s", e)
        return None

def post_reply(text: str, in_reply_to: str, with_meme: bool):
    media_ids = None
    if with_meme:
        meme = choose_meme("memes")
        if meme:
            mid = upload_media_get_id(meme)
            if mid:
                media_ids = [mid]
    # create_tweet v2
    if media_ids:
        return client.create_tweet(text=text, in_reply_to_tweet_id=in_reply_to, media_ids=media_ids)
    else:
        return client.create_tweet(text=text, in_reply_to_tweet_id=in_reply_to)

# =========================
# Reply-Text bauen
# =========================
def build_reply_text(context_snippet: str = "") -> str:
    prompt = (
        "Write a short, cheeky, non-repetitive shill reply for $LENNY. "
        "Keep it under 200 chars. Vary wording vs. previous ones. "
        f"Context: {context_snippet[:140]}"
    )
    txt = grok_generate(prompt) if GROK_API_KEY else ""
    if not txt:
        txt = fallback_shill()

    # eigene Handle-Mention aus der Antwort entfernen, damit der Bot sich nicht selbst pingt
    try:
        pattern = re.compile(rf"@{re.escape(BOT_HANDLE)}", re.IGNORECASE)
        txt = pattern.sub("", txt)
    except Exception:
        pass

    # kleine Entdopplung / Aufräumen
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt

# =========================
# Main Loop
# =========================
def main():
    # Eigene User-ID herausfinden
    me = client.get_me()
    my_user_id = str(me.data.id)
    log.info("Started as @%s — targets: %d", BOT_HANDLE, len(TARGET_IDS))

    # pro-User Grenzen / Zeitstempel
    last_checked = {uid: 0 for uid in TARGET_IDS}
    replies_today = {uid: 0 for uid in TARGET_IDS}
    day_marker = datetime.now(timezone.utc).date()

    last_mention_since = None
    last_kol_since = {uid: None for uid in TARGET_IDS}

    while True:
        try:
            # Tageswechsel reset
            today = datetime.now(timezone.utc).date()
            if today != day_marker:
                day_marker = today
                replies_today = {uid: 0 for uid in TARGET_IDS}

            # 1) Mentions beantworten (Bot wird angepingt)
            ments = fetch_mentions(my_user_id, since_id=last_mention_since)
            if ments:
                log.info("Mentions fetched: %d", len(ments))
                # chronologisch von alt -> neu antworten
                for tw in sorted(ments, key=lambda x: int(x.id)):
                    tid = str(tw.id)
                    last_mention_since = tid

                    # eigene Tweets ignorieren
                    if str(tw.author_id) == my_user_id:
                        continue

                    src = (tw.text or "").strip()
                    if not src:
                        continue

                    # Bot-Handle muss vorkommen
                    handle_token = f"@{BOT_HANDLE.lower()}"
                    if handle_token not in src.lower():
                        continue

                    # nur antworten, wenn NUR der Bot erwähnt wird (einziges @ im Text)
                    if src.count("@") > 1:
                        # Gruppen-Mentions / andere User → ignorieren
                        continue

                    if already_replied(tid):
                        continue
                    if random.random() > REPLY_PROBABILITY:
                        continue

                    text = build_reply_text(src)
                    with_meme = (random.random() < MEME_PROBABILITY)
                    try:
                        post_reply(text, tid, with_meme)
                        remember_and_maybe_backup(tid)
                        log.info("Reply (mention) → %s | %s%s",
                                 tid, text, " [+meme]" if with_meme else "")
                        time.sleep(READ_COOLDOWN_S)
                    except tweepy.TweepyException as e:
                        if "duplicate" in str(e).lower():
                            log.warning("Duplicate content blocked; skipping.")
                            remember_and_maybe_backup(tid)  # trotzdem merken
                        else:
                            log.warning("Reply fehlgeschlagen: %s", e)
                    except Exception as e:
                        log.warning("Reply fehlgeschlagen: %s", e)

            # 2) KOL Timelines
               # pro-User Grenzen / Zeitstempel
    last_checked = {uid: 0 for uid in TARGET_IDS}
    replies_today = {uid: 0 for uid in TARGET_IDS}
    day_marker = datetime.now(timezone.utc).date()

    last_mention_since = None

    # Hier merken wir uns für jeden KOL:
    # "Was ist der aktuellste Tweet JETZT?"
    # → Auf alles, was davor war, antwortet der Bot NICHT.
    last_kol_since = {}
    for uid in TARGET_IDS:
        tweets = fetch_user_tweets(uid, since_id=None)
        if tweets:
            # nehme den neuesten Tweet (größte ID)
            newest = max(tweets, key=lambda x: int(x.id))
            last_kol_since[uid] = str(newest.id)
            log.info("Init last_kol_since[%s] = %s (nur neue Tweets ab jetzt)", uid, newest.id)
        else:
            # KOL hat keine Tweets → warten, bis später was Neues kommt
            last_kol_since[uid] = None


                if tweets:
                    # von alt -> neu
                    for tw in sorted(tweets, key=lambda x: int(x.id)):
                        tid = str(tw.id)
                        last_kol_since[uid] = tid

                        if already_replied(tid):
                            continue
                        if replies_today[uid] >= MAX_REPLIES_PER_KOL_PER_DAY:
                            continue
                        if ONLY_ORIGINAL and hasattr(tw, "referenced_tweets") and tw.referenced_tweets:
                            # Sicherheitshalber, falls exclude nicht greift
                            continue
                        if random.random() > REPLY_PROBABILITY:
                            continue

                        text = build_reply_text(tw.text or "")
                        with_meme = (random.random() < MEME_PROBABILITY)

                        try:
                            post_reply(text, tid, with_meme)
                            remember_and_maybe_backup(tid)
                            replies_today[uid] += 1
                            log.info("Reply → %s | %s%s",
                                     tid, text, " [+meme]" if with_meme else "")
                            time.sleep(READ_COOLDOWN_S)
                        except tweepy.TweepyException as e:
                            # Duplicate content block → als gesehen markieren
                            if "duplicate" in str(e).lower():
                                log.warning("Duplicate content blocked; skipping.")
                                remember_and_maybe_backup(tid)
                            elif "429" in str(e) or "Too Many Requests" in str(e):
                                log.warning("Rate limit exceeded. Sleeping for %d seconds.", LOOP_SLEEP_SECONDS)
                                time.sleep(LOOP_SLEEP_SECONDS)
                            else:
                                log.warning("Reply fehlgeschlagen: %s", e)
                        except Exception as e:
                            log.warning("Reply fehlgeschlagen: %s", e)

            time.sleep(LOOP_SLEEP_SECONDS)

        except Exception as e:
            log.error("Loop error: %s", e)
            traceback.print_exc()
            # Crash vermeiden, kurze Pause
            time.sleep(10)

if __name__ == "__main__":
    main()
