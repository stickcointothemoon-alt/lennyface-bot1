import os
import time
import json
import re
import random
import logging
import requests
import traceback
from datetime import datetime, timezone, timedelta

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
# X API Keys
X_API_KEY       = os.environ.get("X_API_KEY")         # consumer key
X_API_SECRET    = os.environ.get("X_API_SECRET")
X_ACCESS_TOKEN  = os.environ.get("X_ACCESS_TOKEN")
X_ACCESS_SECRET = os.environ.get("X_ACCESS_SECRET")
X_BEARER_TOKEN  = os.environ.get("X_BEARER_TOKEN")

# KOL IDs (kommagetrennt), z. B. "111,222,333"
TARGET_IDS = [t.strip() for t in os.environ.get("TARGET_IDS", "").split(",") if t.strip()]

# Timing / Limits
READ_COOLDOWN_S       = int(os.environ.get("READ_COOLDOWN_S", "6"))
PER_KOL_MIN_POLL_S    = int(os.environ.get("PER_KOL_MIN_POLL_S", "1200"))  # 20 min
LOOP_SLEEP_SECONDS    = int(os.environ.get("LOOP_SLEEP_SECONDS", "240"))   # 4 min
MAX_REPLIES_PER_KOL_PER_DAY = int(os.environ.get("MAX_REPLIES_PER_KOL_PER_DAY", "3"))

# Wahrscheinlichkeit
REPLY_PROBABILITY = float(os.environ.get("REPLY_PROBABILITY", "1.0"))
DEX_REPLY_PROB    = float(os.environ.get("DEX_REPLY_PROB", "0.5"))  # aktuell nicht genutzt
ONLY_ORIGINAL     = os.environ.get("ONLY_ORIGINAL", "1") == "1"

# Meme-Frequenz
MEME_PROBABILITY = float(os.environ.get("MEME_PROBABILITY", "0.3"))

# Grok
GROK_API_KEY   = os.environ.get("GROK_API_KEY", "")
GROK_BASE_URL  = os.environ.get("GROK_BASE_URL", "https://api.x.ai")
GROK_MODEL     = os.environ.get("GROK_MODEL", "grok-3")

# Grok Tone / Extra Settings (vom Dashboard)
GROK_TONE               = os.environ.get("GROK_TONE", "normal")            # soft / normal / spicy / savage
GROK_FORCE_ENGLISH      = os.environ.get("GROK_FORCE_ENGLISH", "1")        # "1" = immer Englisch
GROK_ALWAYS_SHILL_LENNY = os.environ.get("GROK_ALWAYS_SHILL_LENNY", "1")   # "1" = immer $LENNY erwähnen
GROK_EXTRA_PROMPT       = os.environ.get("GROK_EXTRA_PROMPT", "")          # extra Text aus dem Dashboard

# Lenny DEX / Token
LENNY_TOKEN_CA = os.environ.get("LENNY_TOKEN_CA", "").strip()
DEX_TOKEN_URL  = os.environ.get("DEX_TOKEN_URL", "").strip()

# Heroku-Config schreiben (für STATE_SEEN_IDS Backup)
HEROKU_API_KEY  = os.environ.get("HEROKU_API_KEY", "")
HEROKU_APP_NAME = os.environ.get("HEROKU_APP_NAME", "")

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
    raw = os.environ.get("STATE_SEEN_IDS", "").strip()
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
        for k, v in patch.items():
            os.environ[k] = v
    except Exception:
        pass

_since_backup = 0
_BACKUP_EVERY = 1  # nach JEDER neuen ID sichern

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
def build_grok_system_prompt() -> str:
    """
    Baut den System-Prompt für Grok dynamisch,
    je nach Tone / Force English / Always Lenny / Extra Prompt.
    """
    base = (
        "You are LENNY, a cheeky, degen-style shill-bot for the $LENNY token. "
        "Reply in short, punchy, funny style. Avoid duplicate text, vary wording. "
        "Always keep replies suitable for public social media."
    )

    # Ton einstellen
    tone = (GROK_TONE or "normal").lower()
    if tone == "soft":
        base += " Keep your tone friendly, kind and low aggression. No insults, just playful fun."
    elif tone == "spicy":
        base += " You may be a bit edgy and teasing, but avoid real toxicity or hate speech."
    elif tone == "savage":
        base += (
            " Use a savage, roasting style with strong banter, but never use slurs, "
            "hate speech, or real-life threats. Keep it fun and within platform rules."
        )
    else:  # normal
        base += " Use a balanced degen tone: fun, confident, slightly cheeky."

    # Immer Englisch?
    if GROK_FORCE_ENGLISH == "1":
        base += " Always respond in English, even if the user writes in another language."

    # Immer $LENNY shillen?
    if GROK_ALWAYS_SHILL_LENNY == "1":
        base += " Always mention $LENNY somewhere in the reply, unless it would be completely out of context."

    # Extra Prompt aus dem Dashboard
    extra = (GROK_EXTRA_PROMPT or "").strip()
    if extra:
        base += " Extra style instructions: " + extra

    # Hashtags-Hinweis
    base += " Add 1-2 fitting crypto or meme hashtags when relevant."

    return base

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
                {"role": "system", "content": build_grok_system_prompt()},
                {"role": "user", "content": prompt},
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
# Market-Helpers (DEX)
# =========================
def format_number(n: float) -> str:
    """Zahlen hübsch formatieren (K, M, B)."""
    if n >= 1_000_000_000:
        return f"{n/1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n/1_000:.2f}K"
    return f"{n:.4f}"

def fetch_lenny_stats_for_bot():
    """
    Holt Preis, MC und 24h Volumen von Dexscreener.
    Nutzt DEX_TOKEN_URL, sonst LENNY_TOKEN_CA.
    Gibt dict oder None zurück.
    """
    if DEX_TOKEN_URL:
        url = DEX_TOKEN_URL
    else:
        if not LENNY_TOKEN_CA:
            log.warning("LENNY_TOKEN_CA fehlt – kann keine DEX-Daten holen.")
            return None
        url = f"https://api.dexscreener.com/latest/dex/tokens/{LENNY_TOKEN_CA}"

    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        pairs = data.get("pairs") or []
        if not pairs:
            log.warning("Keine Pair-Daten von Dex erhalten.")
            return None

        pair = pairs[0]
        price = float(pair.get("priceUsd") or 0)
        mc    = float(pair.get("fdv") or pair.get("marketCap") or 0)
        vol24 = float(
            (pair.get("volume") or {}).get("h24")
            or pair.get("volume24h")
            or 0
        )

        stats = {
            "price": price,
            "mc": mc,
            "vol24": vol24,
            "price_str": f"${price:.6f}" if price < 1 else f"${price:.4f}",
            "mc_str": format_number(mc),
            "vol_str": format_number(vol24),
        }
        log.info("LENNY Stats (Reply): %s", stats)
        return stats
    except Exception as e:
        log.warning("DEX-Request im Reply-Bot fehlgeschlagen: %s", e)
        return None

def build_market_reply(context_snippet: str = "") -> str:
    """
    Antwortet mit Preis/MC/Vol + Lenny-Spruch.
    Nutzt Grok, fällt sonst auf festen Text zurück.
    """
    stats = fetch_lenny_stats_for_bot()
    if not stats:
        txt = (
            "Can’t reach the $LENNY oracle right now, try again later ( ͡° ͜ʖ ͡°) "
            "#Lenny #Solana"
        )
        return txt

    price_str = stats["price_str"]
    mc_str    = stats["mc_str"]
    vol_str   = stats["vol_str"]

    fallback = (
        f"$LENNY stats ( ͡° ͜ʖ ͡°) "
        f"Price: {price_str} | MC: {mc_str} | 24h Vol: {vol_str} "
        "#Lenny #Solana #Memecoins"
    )

    if not GROK_API_KEY:
        return fallback

    ctx = (
        f"User message: {context_snippet[:140]}. "
        f"Numbers: Price {price_str}, Market Cap {mc_str}, 24h Volume {vol_str}."
    )
    prompt = (
        "User asks about the price/market cap/volume of $LENNY. "
        "Write a very short, cheeky answer in degen style, include the Lennyface ( ͡° ͜ʖ ͡°) "
        "and 1-2 crypto hashtags. Use the numbers I give you. "
        f"Context: {ctx}"
    )

    txt = grok_generate(prompt) or fallback

    # sicherstellen, dass das Lennyface drin ist
    if "( ͡° ͜ʖ ͡°)" not in txt:
        txt += " ( ͡° ͜ʖ ͡°)"

    # Bot-Handle entfernen, falls Grok es reinschreibt
    try:
        pattern = re.compile(rf"@{re.escape(BOT_HANDLE)}", re.IGNORECASE)
        txt = pattern.sub("", txt)
    except Exception:
        pass

    return re.sub(r"\s+", " ", txt).strip()

# =========================
# Helfer: Tweets holen
# =========================
def fetch_user_tweets(user_id: str, since_id: str | None = None):
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
            exclude=exclude,
            tweet_fields=["created_at"],
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

def fetch_mentions(my_user_id: str, since_id: str | None = None):
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
        files = [
            f
            for f in os.listdir(path)
            if f.lower().endswith((".jpg", ".jpeg", ".png", ".gif"))
        ]
        if not files:
            return None
        return os.path.join(path, random.choice(files))
    except Exception:
        return None

def upload_media_get_id(filepath: str) -> str | None:
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
        return client.create_tweet(
            text=text, in_reply_to_tweet_id=in_reply_to, media_ids=media_ids
        )
    else:
        return client.create_tweet(text=text, in_reply_to_tweet_id=in_reply_to)

# =========================
# Reply-Text bauen (normaler Shill)
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
    # kleiner Delay nach Deploy
    log.info("Warte 30 Sekunden, um Rate-Limit nach Deploy zu vermeiden…")
    time.sleep(30)

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
            # Bot pausieren über ENV
            if os.environ.get("BOT_PAUSED", "0") == "1":
                log.info("BOT_PAUSED=1 → Bot pausiert, schlafe nur.")
                time.sleep(LOOP_SLEEP_SECONDS)
                continue

            # Tageswechsel: Limit zurücksetzen
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

                    # prüfen, ob jemand nach Price/MC/Stats fragt
                    src_lower = src.lower()
                    wants_stats = any(
                        k in src_lower
                        for k in [
                            "price",
                            " mc",
                            "market cap",
                            "marketcap",
                            "volume",
                            "vol ",
                            "stats",
                            "chart",
                        ]
                    )

                    if wants_stats:
                        text = build_market_reply(src)
                    else:
                        text = build_reply_text(src)

                    with_meme = random.random() < MEME_PROBABILITY
                    try:
                        post_reply(text, tid, with_meme)
                        remember_and_maybe_backup(tid)
                        log.info(
                            "Reply (mention) → %s | %s%s",
                            tid,
                            text,
                            " [+meme]" if with_meme else "",
                        )
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
            now = time.time()
            for uid in TARGET_IDS:
                if now - last_checked[uid] < PER_KOL_MIN_POLL_S:
                    continue
                last_checked[uid] = now

                tweets = fetch_user_tweets(uid, since_id=last_kol_since.get(uid))
                log.info("KOL %s: fetched %d tweets", uid, len(tweets))

                if tweets:
                    # von alt -> neu
                    for tw in sorted(tweets, key=lambda x: int(x.id)):
                        tid = str(tw.id)
                        last_kol_since[uid] = tid

                        # alte Tweets (älter als 3 Tage) ignorieren
                        if hasattr(tw, "created_at") and tw.created_at:
                            age = datetime.now(timezone.utc) - tw.created_at
                            if age > timedelta(days=3):
                                continue

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
                        with_meme = random.random() < MEME_PROBABILITY

                        try:
                            post_reply(text, tid, with_meme)
                            remember_and_maybe_backup(tid)
                            replies_today[uid] += 1
                            log.info(
                                "Reply → %s | %s%s",
                                tid,
                                text,
                                " [+meme]" if with_meme else "",
                            )
                            time.sleep(READ_COOLDOWN_S)
                        except tweepy.TweepyException as e:
                            # Duplicate content block → als gesehen markieren
                            if "duplicate" in str(e).lower():
                                log.warning("Duplicate content blocked; skipping.")
                                remember_and_maybe_backup(tid)
                            elif "429" in str(e) or "Too Many Requests" in str(e):
                                log.warning(
                                    "Rate limit exceeded. Sleeping for %d seconds.",
                                    LOOP_SLEEP_SECONDS,
                                )
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
