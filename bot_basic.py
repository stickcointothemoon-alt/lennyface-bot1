import os
import time
import json
import re
import random
import logging
import requests
import traceback
import math
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

# Boost-Cooldown (schnellere Antworten im Boost-Mode)
BOOST_COOLDOWN_S = int(os.environ.get("BOOST_COOLDOWN_S", "3"))


# Wahrscheinlichkeit
REPLY_PROBABILITY     = float(os.environ.get("REPLY_PROBABILITY", "1.0"))
DEX_REPLY_PROB        = float(os.environ.get("DEX_REPLY_PROB", "0.5"))
ONLY_ORIGINAL         = os.environ.get("ONLY_ORIGINAL", "1") == "1"

# Meme-Frequenz
MEME_PROBABILITY      = float(os.environ.get("MEME_PROBABILITY", "0.3"))

# Extra-Auto-Meme-Logik: wenn Tweet "nach Meme aussieht"
AUTO_MEME_EXTRA_CHANCE = float(os.environ.get("AUTO_MEME_EXTRA_CHANCE", "0.5"))

LENNY_TONE_MODE = os.environ.get("LENNY_TONE_MODE", "default").lower()
# mögliche Werte:
# "default"  -> normales Lenny-English
# "pk_en"    -> „pakistanisch angehauchter“ Degen-English-Style
# später: "de_en", "es", etc.
# Manueller Season-Override:
# "", "auto"  → automatisch nach Datum
# "xmas"      → Erzwinge Weihnachtsmodus
# "easter"    → Erzwinge Ostern
# "halloween" → Erzwinge Halloween
# "off"/"none"/"0" → Immer ohne Season
SEASON_OVERRIDE = os.environ.get("SEASON_OVERRIDE", "").strip().lower()



# Auto Meme Mode (Dashboard Toggle)
AUTO_MEME_MODE = os.environ.get("AUTO_MEME_MODE", "1") == "1"

# Smart-Meme-Keywords (für Boost-Logik)
MEME_KEYWORDS_SOFT = [
    "lfg",
    "wagmi",
    "ngmi",
    "send it",
    "moon",
    "pump",
    "rekt",
    "lol",
    "haha",
    "😂",
    "🤣",
]

MEME_KEYWORDS_HARD = [
    "meme",
    "memes",
    "gif",
    "pic",
    "picture",
    "image",
    "sticker",
    "reaction",
    "template",
]

MEME_KEYWORDS_LENNY = [
    "lenny",
    "lennyface",
    "$lenny",
    # bewusst OHNE reines "( ͡° ͜ʖ ͡°)", sonst würde er ZU oft triggern
]


# ================================
# LENNY FACE LIBRARY + SEASONS
# ================================

LENNY_BASE_FACES = [
    "( ͡° ͜ʖ ͡°)",
    "( ͡° ʖ̯ ͡°)",
    "( ͡° ͜ʖ ͡°)ﾉ",
    "( ͡° ͜ʖ ͡°)>⌐■-■",
]

LENNY_HYPE_FACES = [
    "( ͡° ͜ʖ ͡°)🚀",
    "( ͡🔥 ͜ʖ ͡🔥)",
    "( ͡$ ͜ʖ ͡$)",
    "( ͡° ͜ʖ ͡°)✨",
]

LENNY_SAD_FACES = [
    "( ͡ಥ ͜ʖ ͡ಥ)",
    "( ͡☉ ʖ̯ ͡☉)",
    "( ͡° ʖ̯ ͡°)💔",
]

LENNY_COPE_FACES = [
    "( ͡⚆ ͜ʖ ͡⚆)",
    "( ͡ಠ ʖ̯ ͡ಠ)",
    "( ͡⚆ ͜ʖ ͡⚆)💊",
]

# Season Faces (ASCII + Emoji)
LENNY_XMAS_FACES = [
    "( ͡° ͜ʖ ͡°)🎄",
    "( ͡° ͜ʖ ͡°)🎅",
    "( ͡° ͜ʖ ͡°)❄️",
    "( ͡° ͜ʖ ͡°)🎁",
    "( ͡° ͜ʖ ͡°)✨",
    "( ͡° ͜ʖ ͡°)⛄",
]

LENNY_EASTER_FACES = [
    "( ͡° ͜ʖ ͡°)🐣",
    "( ͡° ͜ʖ ͡°)🥚",
    "( ͡° ͜ʖ ͡°)🐰",
    "( ͡° ͜ʖ ͡°)🌸",
]

LENNY_HALLOWEEN_FACES = [
    "( ͡° ͜ʖ ͡°)🎃",
    "( ͡° ͜ʖ ͡°)👻",
    "( ͡° ͜ʖ ͡°)🕯️",
    "( ͡° ͜ʖ ͡°)🕷️",
    "( ͡° ͜ʖ ͡°)🕸️",
    "( ͡° ͜ʖ ͡°)💀",
]

def _season_markers_for(season: str) -> list[str]:
    """Nur die Emojis, damit wir doppelte Season-Anhänge vermeiden können."""
    if season == "xmas":
        return ["🎄", "🎅", "❄️", "🎁", "✨", "⛄", "🧦", "🔔", "🌟"]
    if season == "easter":
        return ["🐣", "🥚", "🐰", "🌸"]
    if season == "halloween":
        return ["🎃", "👻", "🕯️", "🕷️", "🕸️", "💀"]
    return []


def current_season() -> str | None:
    """
    Liefert 'xmas', 'easter', 'halloween' oder None.
    Nutzt zuerst SEASON_OVERRIDE, dann Datum.
    """
    # 1) Manueller Override
    if SEASON_OVERRIDE in ("xmas", "easter", "halloween"):
        return SEASON_OVERRIDE
    if SEASON_OVERRIDE in ("off", "none", "0"):
        return None
    # "", "auto" → Automatik

    try:
        today = datetime.now(timezone.utc).date()
    except Exception:
        today = datetime.utcnow().date()

    m = today.month
    d = today.day

    # Dezember = Weihnachten
    if m == 12:
        return "xmas"

    # Grob: Ende März – Mitte April = Ostern
    if (m == 3 and d >= 20) or (m == 4 and d <= 15):
        return "easter"

    # Grob: Ende Oktober = Halloween
    if m == 10 and d >= 20:
        return "halloween"

    return None


def pick_lenny_face(mood: str = "base", season: str | None = None) -> str:
    """
    Basis-Auswahl + optional Season-Override.
    Wenn Season aktiv ist, nehmen wir immer Season-Faces.
    """
    if season == "xmas":
        pool = LENNY_XMAS_FACES
    elif season == "easter":
        pool = LENNY_EASTER_FACES
    elif season == "halloween":
        pool = LENNY_HALLOWEEN_FACES
    else:
        pools = {
            "base":   LENNY_BASE_FACES,
            "hype":   LENNY_HYPE_FACES,
            "sad":    LENNY_SAD_FACES,
            "cope":   LENNY_COPE_FACES,
        }
        pool = pools.get(mood, LENNY_BASE_FACES)

    if not pool:
        pool = LENNY_BASE_FACES
    return random.choice(pool)


def decorate_with_lenny_face(text: str, cmd_used: str | None) -> str:
    """
    Finaler Lenny-/Season-Dekorator.

    Regeln:
    - JEDER Reply hat mindestens EIN Lennyface.
    - Wenn Season (xmas/easter/halloween) aktiv ist:
        → Antwort hat IMMER ein Season-Emoji.
        → Wenn schon ( ͡° ͜ʖ ͡°) drin ist, hängen wir nur noch das Emoji an.
        → Sonst nehmen wir ein Season-Lenny-Face (mit Emoji).
    - Wenn KEINE Season:
        → Wenn schon ( ͡ im Text → nichts doppelt.
        → Sonst Mood je nach Command (gm/alpha/hype, roast/cope etc.).
    """
    if not text:
        return text

    cmd = (cmd_used or "").lower()
    season = current_season()

    # -----------------------------
    # SEASON-AKTIV (global, für alle Commands)
    # -----------------------------
    if season:
        markers = _season_markers_for(season)

        # Wenn schon ein Season-Emoji drin ist → passt, nichts tun
        if any(m in text for m in markers):
            # Sicherstellen, dass irgendwo ein Lennyface drin ist
            if "( ͡" in text:
                return text
            # Kein Lenny drin → Season-Lenny dazu
            face = pick_lenny_face("base", season=season)
            if text.endswith(("!", "?", ".")):
                return text + " " + face
            return text + " " + face

        # Noch kein Season-Emoji im Text
        if "( ͡" in text:
            # Schon ein normales Lennyface → nur noch Season-Emoji anhängen
            emo = random.choice(markers) if markers else ""
            if not emo:
                return text
            if text.endswith(("!", "?", ".")):
                return text + " " + emo
            return text + " " + emo
        else:
            # Weder Lennyface noch Season → Season-Lenny anhängen (ASCII + Emoji)
            face = pick_lenny_face("base", season=season)
            if text.endswith(("!", "?", ".")):
                return text + " " + face
            return text + " " + face

    # -----------------------------
    # KEINE SEASON – normale Mood-Logik
    # -----------------------------
    # Wenn schon irgendein Lennyface drin → so lassen
    if "( ͡" in text:
        return text

    # Mood je nach Command
    if cmd in ("gm", "alpha"):
        mood = "hype"
    elif cmd == "roast":
        mood = "cope"
    elif cmd in ("price", "mc", "mc_compare", "stats", "chart"):
        lower = text.lower()
        if any(k in lower for k in ["dump", "down", "red", "-%"]):
            mood = "sad"
        else:
            mood = "hype"
    elif cmd == "shill":
        mood = random.choice(["base", "hype"])
    else:
        mood = "base"

    face = pick_lenny_face(mood, season=None)

    if text.endswith(("!", "?", ".")):
        return text + " " + face
    return text + " " + face

# ================================
# DIALEKT / TONE HELFER
# ================================

def _apply_pk_english(text: str, cmd_used: str | None) -> str:
    """
    Sehr softer „Pakistani Crypto Twitter“-Vibe.
    Kein komplettes Umschreiben, nur kleine Anpassungen.
    Keine Beleidigungen, kein Hate – nur Flavor.
    """
    # Zu lange Texte nicht mehr anfassen (wegen 280-Char-Limit)
    if len(text) > 240:
        return text

    t = text

    # 1) "bro" -> "bro yaar" (max. 1x)
    t = re.sub(r"\bbro\b", "bro yaar", t, count=1, flags=re.IGNORECASE)

    # 2) "fam" -> "fam yaar" (max. 1x)
    t = re.sub(r"\bfam\b", "fam yaar", t, count=1, flags=re.IGNORECASE)

    # 3) "degen" -> "degen yaar" (max. 1x)
    t = re.sub(r"\bdegen(s)?\b", r"degen\1 yaar", t, count=1, flags=re.IGNORECASE)

    # 4) Wenn noch Platz: kleines Flavor-Tag hinten dran
    if "yaar" not in t.lower() and len(t) < 230:
        if t.endswith((")", "🚀", "😂", "🤣", "✨", "😅", "😎")):
            t = t + " yaar"
        elif t.endswith(("!", "?", ".")):
            t = t[:-1] + " yaar" + t[-1]
        else:
            t = t + " yaar"

    return t


def apply_dialect(text: str, cmd_used: str | None) -> str:
    """
    Wendet je nach LENNY_TONE_MODE einen Dialekt/Style an.
    """
    mode = (LENNY_TONE_MODE or "default").lower()

    if mode == "pk_en":
        return _apply_pk_english(text, cmd_used)

    # später: weitere Modes, z.B. "de_en", "es", ...
    return text


# Feature-Toggles (für Dashboard / Commands)
ENABLE_HELP   = os.environ.get("ENABLE_HELP", "1") == "1"
ENABLE_LORE   = os.environ.get("ENABLE_LORE", "1") == "1"
ENABLE_STATS  = os.environ.get("ENABLE_STATS", "1") == "1"
ENABLE_ALPHA  = os.environ.get("ENABLE_ALPHA", "1") == "1"
ENABLE_GM     = os.environ.get("ENABLE_GM", "1") == "1"
ENABLE_ROAST  = os.environ.get("ENABLE_ROAST", "1") == "1"

# Boost-Mode Settings
BOOST_ENABLED           = os.environ.get("BOOST_ENABLED", "1") == "1"
BOOST_DURATION_S        = int(os.environ.get("BOOST_DURATION_S", "600"))   # 10 min
BOOST_MENTION_WINDOW_S  = int(os.environ.get("BOOST_MENTION_WINDOW_S", "120"))  # 2 min
BOOST_MIN_MENTIONS      = int(os.environ.get("BOOST_MIN_MENTIONS", "4"))   # ab 4 Mentions in Zeitfenster
BOOST_REPLY_PROB        = float(os.environ.get("BOOST_REPLY_PROB", "0.9")) # in Boost fast immer antworten
BOOST_MEME_PROB         = float(os.environ.get("BOOST_MEME_PROB", "0.7"))  # mehr Memes im Boost
BOOST_READ_COOLDOWN_S   = int(os.environ.get("BOOST_READ_COOLDOWN_S", "2"))  # schnellerer Cooldown

# manueller Boost über Config Var (z.B. Dashboard später)
BOOST_MANUAL_FLAG       = os.environ.get("BOOST_MANUAL", "0") == "1"

# User Cooldown (Anti-Repeat: wie oft pro User geantwortet wird)
USER_REPLY_COOLDOWN_S = int(os.environ.get("USER_REPLY_COOLDOWN_S", "600"))  # 600s = 10 Min



# Grok
GROK_API_KEY   = os.environ.get("GROK_API_KEY","")
GROK_BASE_URL  = os.environ.get("GROK_BASE_URL","https://api.x.ai")
GROK_MODEL     = os.environ.get("GROK_MODEL","grok-3")

# Grok Tone / Extra Settings (vom Dashboard)
GROK_TONE               = os.environ.get("GROK_TONE", "normal")              # soft / normal / spicy / savage
GROK_FORCE_ENGLISH      = os.environ.get("GROK_FORCE_ENGLISH", "1")          # "1" = immer Englisch
GROK_ALWAYS_SHILL_LENNY = os.environ.get("GROK_ALWAYS_SHILL_LENNY", "1")     # "1" = immer $LENNY erwähnen
GROK_EXTRA_PROMPT       = os.environ.get("GROK_EXTRA_PROMPT", "")            # extra Text aus dem Dashboard

# Lenny DEX / Token
LENNY_TOKEN_CA = os.environ.get("LENNY_TOKEN_CA", "").strip()
DEX_TOKEN_URL  = os.environ.get("DEX_TOKEN_URL", "").strip()

# --- Link-Sicherheit ---
SAFE_LINK_DOMAINS = os.environ.get(
    "SAFE_LINK_DOMAINS",
    "dexscreener.com,linktr.ee,x.com,twitter.com,lennyface-bot-736b44838bb5.herokuapp.com,solscan.io"
).split(",")

SAFE_LINK_DOMAINS = [d.strip().lower() for d in SAFE_LINK_DOMAINS if d.strip()]


# =====================================
# MC_COMPARE – weitere Tokens aus ENV
# =====================================

# Token 1 (z.B. TROLL)
COMPARE_TOKEN_1_NAME = os.environ.get("COMPARE_TOKEN_1_NAME", "").strip()
COMPARE_TOKEN_1_CA   = os.environ.get("COMPARE_TOKEN_1_CA", "").strip()
COMPARE_TOKEN_1_URL  = os.environ.get("COMPARE_TOKEN_1_URL", "").strip()

# Token 2
COMPARE_TOKEN_2_NAME = os.environ.get("COMPARE_TOKEN_2_NAME", "").strip()
COMPARE_TOKEN_2_CA   = os.environ.get("COMPARE_TOKEN_2_CA", "").strip()
COMPARE_TOKEN_2_URL  = os.environ.get("COMPARE_TOKEN_2_URL", "").strip()

# Token 3
COMPARE_TOKEN_3_NAME = os.environ.get("COMPARE_TOKEN_3_NAME", "").strip()
COMPARE_TOKEN_3_CA   = os.environ.get("COMPARE_TOKEN_3_CA", "").strip()
COMPARE_TOKEN_3_URL  = os.environ.get("COMPARE_TOKEN_3_URL", "").strip()

# Token 4
COMPARE_TOKEN_4_NAME = os.environ.get("COMPARE_TOKEN_4_NAME", "").strip()
COMPARE_TOKEN_4_CA   = os.environ.get("COMPARE_TOKEN_4_CA", "").strip()
COMPARE_TOKEN_4_URL  = os.environ.get("COMPARE_TOKEN_4_URL", "").strip()

# Token 5
COMPARE_TOKEN_5_NAME = os.environ.get("COMPARE_TOKEN_5_NAME", "").strip()
COMPARE_TOKEN_5_CA   = os.environ.get("COMPARE_TOKEN_5_CA", "").strip()
COMPARE_TOKEN_5_URL  = os.environ.get("COMPARE_TOKEN_5_URL", "").strip()

# Token 6 (BTC – wir benutzen später Coingecko)
COMPARE_TOKEN_6_NAME = os.environ.get("COMPARE_TOKEN_6_NAME", "").strip()
COMPARE_TOKEN_6_CA   = os.environ.get("COMPARE_TOKEN_6_CA", "").strip()
COMPARE_TOKEN_6_URL  = os.environ.get("COMPARE_TOKEN_6_URL", "").strip()


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

# =========================
# STATS für Dashboard
# =========================
# Diese Werte werden regelmäßig in Heroku-Config geschrieben,
# damit das Dashboard "Daily Activity" anzeigen kann.
STATS_DATE = os.environ.get("STATS_DATE", "")
try:
    STATS_REPLIES_TOTAL = int(os.environ.get("STATS_REPLIES_TOTAL", "0") or "0")
    STATS_REPLIES_MENTIONS = int(os.environ.get("STATS_REPLIES_MENTIONS", "0") or "0")
    STATS_REPLIES_KOL = int(os.environ.get("STATS_REPLIES_KOL", "0") or "0")
    STATS_MEMES_USED = int(os.environ.get("STATS_MEMES_USED", "0") or "0")
except ValueError:
    STATS_REPLIES_TOTAL = 0
    STATS_REPLIES_MENTIONS = 0
    STATS_REPLIES_KOL = 0
    STATS_MEMES_USED = 0

_STATS_SINCE_FLUSH = 0
_STATS_FLUSH_EVERY = 10  # alle 10 Replies Stats in Config Vars schreiben


def _flush_stats_to_env():
    """Schreibt die aktuellen Stats-Werte in Heroku Config Vars."""
    if not (HEROKU_API_KEY and HEROKU_APP_NAME):
        return
    patch = {
        "STATS_DATE": STATS_DATE,
        "STATS_REPLIES_TOTAL": str(STATS_REPLIES_TOTAL),
        "STATS_REPLIES_MENTIONS": str(STATS_REPLIES_MENTIONS),
        "STATS_REPLIES_KOL": str(STATS_REPLIES_KOL),
        "STATS_MEMES_USED": str(STATS_MEMES_USED),
    }
    _set_config_vars(patch)


def bump_stats(kind: str, used_meme: bool):
    """
    kind: "mention" oder "kol"
    used_meme: True/False, ob ein Meme angehängt war
    """
    global STATS_DATE, STATS_REPLIES_TOTAL, STATS_REPLIES_MENTIONS
    global STATS_REPLIES_KOL, STATS_MEMES_USED
    global _STATS_SINCE_FLUSH

    today = datetime.now(timezone.utc).date().isoformat()

    # Tageswechsel → neue Stats
    if STATS_DATE != today:
        STATS_DATE = today
        STATS_REPLIES_TOTAL = 0
        STATS_REPLIES_MENTIONS = 0
        STATS_REPLIES_KOL = 0
        STATS_MEMES_USED = 0

    STATS_REPLIES_TOTAL += 1
    if kind == "mention":
        STATS_REPLIES_MENTIONS += 1
    elif kind == "kol":
        STATS_REPLIES_KOL += 1

    if used_meme:
        STATS_MEMES_USED += 1

    _STATS_SINCE_FLUSH += 1
    if _STATS_SINCE_FLUSH >= _STATS_FLUSH_EVERY:
        _STATS_SINCE_FLUSH = 0
        _flush_stats_to_env()

# =========================
# Simple User-Memory (nur im RAM)
# =========================
USER_PROFILES = {}
MAX_USER_PROFILES = 500  # Sicherheit, damit RAM nicht voll läuft

# Anti-Repeat: pro User nur alle X Sekunden antworten
LAST_REPLY_PER_USER = {}


def can_reply_to_user(user_id: str) -> bool:
    """
    Checkt, ob wir diesem User gerade antworten dürfen.
    Nutzt USER_REPLY_COOLDOWN_S als Sperrzeit.
    """
    if USER_REPLY_COOLDOWN_S <= 0:
        return True  # Cooldown deaktiviert

    now = time.time()
    last = LAST_REPLY_PER_USER.get(user_id)
    if last is None:
        return True
    # wenn seit letzter Antwort weniger als Cooldown vergangen ist -> nicht antworten
    return (now - last) >= USER_REPLY_COOLDOWN_S


def mark_replied_to_user(user_id: str):
    """
    Merkt sich, wann wir zuletzt einem User geantwortet haben.
    """
    LAST_REPLY_PER_USER[user_id] = time.time()



def get_user_profile(user_id: str) -> dict:
    """
    Holt oder erzeugt ein kleines Profil pro User.
    Wird nicht persistent gespeichert, nur solange der Dyno läuft.
    """
    if user_id not in USER_PROFILES:
        # Hard-Cap: wenn zu viele User, werfe den ältesten raus
        if len(USER_PROFILES) >= MAX_USER_PROFILES:
            # Primitive Eviction: ersten Key rauswerfen
            oldest_key = next(iter(USER_PROFILES.keys()))
            USER_PROFILES.pop(oldest_key, None)

        USER_PROFILES[user_id] = {
            "total_interactions": 0,
            "last_seen": None,
            "commands_used": {},  # z.B. {"help": 2, "lore": 1}
        }
    return USER_PROFILES[user_id]


def update_user_profile(user_id: str, command: str | None = None):
    """
    Aktualisiert das Profil, z.B. wenn wir auf eine Mention antworten.
    command kann z.B. 'help', 'lore', 'alpha', 'gm', 'roast', 'price' sein.
    """
    prof = get_user_profile(user_id)
    prof["total_interactions"] += 1
    prof["last_seen"] = datetime.now(timezone.utc).isoformat()
    if command:
        prof["commands_used"][command] = prof["commands_used"].get(command, 0) + 1


def personalize_reply(base_text: str, user_id: str) -> str:
    """
    Kleiner Bonus-Touch abhängig vom User.
    NICHT übertreiben, nur minimaler Flavor.
    """
    prof = get_user_profile(user_id)
    total = prof.get("total_interactions", 0)

    # Wenn jemand schon öfter mit dem Bot gespielt hat → kleiner Insider
    extra = ""
    if total >= 5 and "Back again" not in base_text and "again" not in base_text:
        extra = " Back again, degen ( ͡° ͜ʖ ͡°)"

    if not extra:
        return base_text

    # Safety: Länge unter 280 halten
    if len(base_text) + len(extra) <= 270:
        return base_text + extra
    return base_text  # zu lang, dann lieber weglassen


# =========================
# Meme-Entscheidungs-Logik (Smart Boost)
# =========================
def _meme_boost_score(text: str) -> float:
    """
    Gibt einen zusätzlichen Meme-Boost-Wert zurück (0.0–0.7),
    basierend auf den Keywords im Text.
    """
    lower = (text or "").lower()

    soft_hit = any(kw in lower for kw in MEME_KEYWORDS_SOFT)
    hard_hit = any(kw in lower for kw in MEME_KEYWORDS_HARD)
    lenny_hit = any(kw in lower for kw in MEME_KEYWORDS_LENNY)

    boost = 0.0

    if soft_hit:
        boost += 0.10  # leichte Meme-Stimmung
    if hard_hit:
        boost += 0.30  # explizit Meme/pic/gif usw.
    if lenny_hit:
        boost += 0.30  # extra Bonus für Lenny-/Token-Bezug

    # Maximal-Boost begrenzen
    if boost > 0.70:
        boost = 0.70

    # Debug-Log
    if soft_hit or hard_hit or lenny_hit:
        log.info(
            "_meme_boost_score: soft=%s hard=%s lenny=%s → boost=%.2f",
            soft_hit,
            hard_hit,
            lenny_hit,
            boost,
        )

    return boost



def should_attach_meme(text: str, is_mention: bool = False) -> bool:
    """
    Entscheidet, ob ein Meme angehängt wird.

    - Respektiert AUTO_MEME_MODE (Dashboard Toggle)
    - Basis: MEME_PROBABILITY
    - Smart-Boost je nach Keywords im Text
    - Mentions bekommen leicht höhere Chance als KOL-Tweets
    """
    if not AUTO_MEME_MODE:
        log.info("should_attach_meme: AUTO_MEME_MODE=0 → no meme")
        return False

    # Basis-Wahrscheinlichkeit aus ENV
    try:
        base_prob = float(MEME_PROBABILITY)
    except Exception:
        base_prob = 0.3

    # Smart-Boost aus Keywords
    boost = _meme_boost_score(text)

    # Mentions dürfen etwas mehr Meme-Power haben
    try:
        extra = float(AUTO_MEME_EXTRA_CHANCE)
    except Exception:
        extra = 0.5

    if is_mention:
        boost += extra * 0.5

    prob = base_prob + boost

    # Sicherheits-Cap
    if prob > 0.95:
        prob = 0.95
    if prob < 0.0:
        prob = 0.0

    r = random.random()
    decision = r < prob

    log.info(
        "should_attach_meme: base=%.2f boost=%.2f is_mention=%s → prob=%.2f roll=%.3f → %s",
        base_prob,
        boost,
        is_mention,
        prob,
        r,
        "YES" if decision else "NO",
    )

    return decision



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

# ==========================
#  Link- / Scam-Detection
# ==========================
import re
from urllib.parse import urlparse

URL_REGEX = re.compile(r"https?://\S+", re.IGNORECASE)

# Default-Whitelist:
# - dexscreener.com  → dein Chart-Link
# - linktr.ee        → Linktree
# - x.com/twitter.com→ normale X-Posts + Medien
# - lennyface-bot-736b44838bb5.herokuapp.com → dein eigener Bot-Link
SAFE_LINK_DOMAINS = os.environ.get(
    "SAFE_LINK_DOMAINS",
    "dexscreener.com,linktr.ee,x.com,twitter.com,lennyface-bot-736b44838bb5.herokuapp.com"
).split(",")
SAFE_LINK_DOMAINS = [d.strip().lower() for d in SAFE_LINK_DOMAINS if d.strip()]


def _resolve_final_host(url: str) -> str | None:
    """
    Versucht bei Kurzlinks (z.B. t.co) die finale Ziel-Domain zu ermitteln.
    Gibt z.B. 'x.com' oder 'dexscreener.com' zurück.
    """
    try:
        r = requests.head(url, allow_redirects=True, timeout=5)
        final_url = r.url
        parsed = urlparse(final_url)
        host = (parsed.netloc or "").lower()
        return host or None
    except Exception:
        return None


def _get_effective_host(url: str) -> str | None:
    """
    Holt die Domain eines Links.
    Bei t.co wird versucht, auf die echte Ziel-Domain aufzulösen.
    """
    try:
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower()
        if not host:
            return None

        # t.co → versuch, echte Ziel-Domain zu holen
        if host == "t.co":
            resolved = _resolve_final_host(url)
            if resolved:
                return resolved
        return host
    except Exception:
        return None


def extract_urls(text: str) -> list[str]:
    if not text:
        return []
    return URL_REGEX.findall(text)


def is_safe_url(url: str) -> bool:
    """
    True, wenn die Domain (nach evt. Redirect) in SAFE_LINK_DOMAINS whitelisted ist.
    """
    host = _get_effective_host(url)
    if not host:
        return False

    for dom in SAFE_LINK_DOMAINS:
        dom = dom.strip().lower()
        if not dom:
            continue
        # exakte Domain oder Subdomain
        if host == dom or host.endswith("." + dom):
            return True
    return False


def has_suspicious_link(text: str) -> bool:
    """
    True, wenn im Text irgendein Link ist,
    der NICHT in SAFE_LINK_DOMAINS liegt.
    """
    urls = extract_urls(text)
    if not urls:
        return False

    for u in urls:
        if not is_safe_url(u):
            return True
    return False


def sanitize_reply_links(text: str) -> str:
    """
    Entfernt ALLE Links aus der Antwort, die nicht whitelisted sind.
    Dexscreener + Linktree + X bleiben erhalten (über SAFE_LINK_DOMAINS).
    """
    if not text:
        return text

    def _replacer(match: re.Match) -> str:
        url = match.group(0)
        return url if is_safe_url(url) else ""

    cleaned = URL_REGEX.sub(_replacer, text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def build_scam_warning_reply(src: str) -> str:
    """
    Standard-Reply bei verdächtigen Links.
    Kein Repost des Links, rotierende sichere Antworten.
    Immer mit $LENNY + Lennyface.
    """

    options = [
        "Easy there, degen. Random links can drain bags real quick. Stick to Dexscreener + official $LENNY links only. ( ͡° ͜ʖ ͡°)",
        "Careful fren — mystery links are how wallets go *bye bye*. Only trust Dexscreener + official $LENNY sources. ( ͡° ͜ʖ ͡°)",
        "Unknown links = danger zone. Protect those bags and use only Dexscreener + official $LENNY links. Stay safe, stay smirkin’. ( ͡° ͜ʖ ͡°)",
        "Random links? Nah fam. That’s a fast-track to getting rugged. Official $LENNY links + Dexscreener only. ( ͡° ͜ʖ ͡°)",
        "Fren, clicking mystery links is like signing a blank check. Keep it clean: Dexscreener + official $LENNY links only. ( ͡° ͜ʖ ͡°)",
        "Heads up — shady links love fresh wallets. Trust only Dexscreener + verified $LENNY sources. Smirk responsibly. ( ͡° ͜ʖ ͡°)",
        "Yo, that link looks spicier than it should. Avoid getting cooked — use Dexscreener + official $LENNY links only. ( ͡° ͜ʖ ͡°)",
        "Hold up degen — before you click anything, remember mystery links = instant regret. Stick to official $LENNY + Dexscreener. ( ͡° ͜ʖ ͡°)",
    ]

    return random.choice(options)



# =========================
# Usage Stats (für Dashboard)
# =========================
USAGE_STATS_ENV_KEY = "LENNY_USAGE_STATS"

STATS = {
    "total_replies": 0,
    "help": 0,
    "lore": 0,
    "market": 0,
    "alpha": 0,
    "gm": 0,
    "roast": 0,
    "generic": 0,
    "kol_replies": 0,
}

_stats_since_flush = 0
_STATS_FLUSH_EVERY = 25  # nach X Replies in ENV schreiben


def load_stats_from_env():
    raw = os.environ.get(USAGE_STATS_ENV_KEY, "").strip()
    if not raw:
        return
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, (int, float)):
                    STATS[k] = int(v)
        log.info("Usage stats loaded: %s", STATS)
    except Exception:
        log.warning("Could not parse LENNY_USAGE_STATS, starting fresh.")


def inc_stat(key: str):
    global _stats_since_flush
    STATS[key] = STATS.get(key, 0) + 1
    _stats_since_flush += 1


def flush_stats_if_needed(force: bool = False):
    global _stats_since_flush
    if not (HEROKU_API_KEY and HEROKU_APP_NAME):
        return
    if not force and _stats_since_flush < _STATS_FLUSH_EVERY:
        return
    try:
        _set_config_vars({USAGE_STATS_ENV_KEY: json.dumps(STATS)})
        log.info("Usage stats backup: %s", STATS)
        _stats_since_flush = 0
    except Exception:
        pass

load_seen_from_env()
log.info("State loaded: %d replied tweet IDs remembered", len(SEEN))

load_stats_from_env()


# =========================
# Helfer: Grok & Text-Bausteine
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

def fetch_lenny_stats():
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
        mc = float(pair.get("fdv") or pair.get("marketCap") or 0)
        vol24 = float(
            (pair.get("volume") or {}).get("h24")
            or pair.get("volume24h")
            or 0
        )

        price_str = f"${price:.6f}" if price < 1 else f"${price:.4f}"

        out = {
            "price": price,
            "mc": mc,
            "vol24": vol24,
            "price_str": price_str,
            "mc_str": format_number(mc),
            "vol_str": format_number(vol24),
            "dex_name": pair.get("dexId", ""),
            "pair_url": pair.get("url", ""),
        }
        log.info("LENNY Stats (Reply): %s", out)
        return out
    except Exception as e:
        log.warning("DEX-Request fehlgeschlagen: %s", e)
        return None

def build_market_reply(context_snippet: str = "") -> str:
    """
    Antwortet NUR mit Market Cap + Lenny-Spruch.
    Nutzt Grok wenn möglich.
    Dex-Link wird IMMER am Ende angehängt.
    Lennyfaces werden NICHT hier eingefügt, sondern später über
    decorate_with_lenny_face().
    """
    stats = fetch_lenny_stats()
    if not stats:
        # Kein Lennyface hier, der kommt später über decorate_with_lenny_face
        return "Can't reach the $LENNY oracle right now, try later. #Lenny #Solana"

    mc = stats["mc"]
    mc_str = format_number(mc)
    pair_url = stats.get("pair_url") or ""

    # -------- Fallback, falls kein Grok / Fehler --------
    # Wichtig: KEIN ( ͡° ͜ʖ ͡°) hier, das macht die Library.
    fallback = f"$LENNY Market Cap: {mc_str}. #Lenny #Solana #Memecoins"

    # -------- Mit Grok --------
    if GROK_API_KEY:
        try:
            ctx = f"User message: {context_snippet[:140]}. Market Cap: {mc_str}."

            prompt = (
                "You are LennyBot, a degen meme coin bot speaking to Crypto Twitter.\n"
                "User asks about $LENNY Market Cap.\n"
                "Write a VERY short, cheeky degen reply.\n"
                "- Use ONLY the Market Cap number given.\n"
                "- Do NOT include any URLs or links.\n"
                "- Do NOT include any Lennyface – that will be added later automatically.\n"
                "- Include 1–2 crypto-related hashtags.\n"
                f"Context: {ctx}"
            )

            base_txt = grok_generate(prompt) or fallback
        except Exception as e:
            log.warning("Grok market reply failed: %s", e)
            base_txt = fallback
    else:
        base_txt = fallback

    # -------- URLs entfernen, falls Grok doch was geschmuggelt hat --------
    base_txt = re.sub(r"https?://\S+", "", base_txt).strip()

    # -------- Falls Grok den Bot erwähnt → raus --------
    try:
        pattern = re.compile(rf"@{re.escape(BOT_HANDLE)}", re.IGNORECASE)
        base_txt = pattern.sub("", base_txt)
    except Exception:
        pass

    base_txt = re.sub(r"\s+", " ", base_txt).strip()

    # -------- Dex-Link selbst anfügen --------
    if pair_url:
        max_len = 280
        url_part = pair_url.strip()
        reserved = len(url_part) + 1  # Leerzeichen + URL

        if len(base_txt) + reserved > max_len:
            base_txt = base_txt[: max_len - reserved].rstrip(" .,!-")

        final_txt = f"{base_txt} {url_part}"
    else:
        final_txt = base_txt[:280]

    return final_txt



# =====================================
# MC COMPARE – Hilfsfunktionen
# =====================================

def _format_usd_short(n: float) -> str:
    """Kurzformat für USD Zahlen (MC etc)."""
    try:
        n = float(n)
    except Exception:
        return str(n)
    if n >= 1_000_000_000:
        return f"{n/1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n/1_000:.2f}K"
    return f"{n:.2f}"


def _fetch_token_stats_for_compare(ca: str, override_url: str | None = None) -> dict | None:
    if not ca:
        return None

    # --- Special Case: BTC via CoinGecko ---
    if ca.upper() == "BTC" or override_url == "COINGECKO":
        try:
            r = requests.get(
                "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_market_cap=true",
                timeout=10
            )
            r.raise_for_status()
            data = r.json() or {}
            btc = data.get("bitcoin") or {}

            price = float(btc.get("usd") or 0)
            mc    = float(btc.get("usd_market_cap") or 0)
            vol24 = 0.0  # Coingecko endpoint liefert kein vol hier

            return {
                "price": price,
                "mc": mc,
                "vol24": vol24,
                "dex": "coingecko",
                "url": "https://www.coingecko.com/en/coins/bitcoin",
            }
        except Exception as e:
            log.warning("Coingecko fetch failed: %s", e)
            return None


    # Immer API benutzen – nie die HTML-Seite
    if override_url:
        url = override_url
    else:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{ca}"

    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json() or {}
        pairs = data.get("pairs") or []
        if not pairs:
            return None

        p = pairs[0]
        price = float(p.get("priceUsd") or 0)
        mc    = float(p.get("fdv") or p.get("marketCap") or 0)
        vol24 = float(
            (p.get("volume") or {}).get("h24")
            or p.get("volume24h")
            or 0
        )

        return {
            "price": price,
            "mc": mc,
            "vol24": vol24,
            "dex": p.get("dexId", ""),
            "url": p.get("url", override_url or ""),
        }
    except Exception as e:
        log.warning("Dexscreener compare failed for %s: %s", ca, e)
        return None


        p = pairs[0]
        price = float(p.get("priceUsd") or 0)
        mc    = float(p.get("fdv") or p.get("marketCap") or 0)
        vol24 = float(
            (p.get("volume") or {}).get("h24")
            or p.get("volume24h")
            or 0
        )

        return {
            "price": price,
            "mc": mc,
            "vol24": vol24,
            "dex": p.get("dexId", ""),
            "url": p.get("url", override_url or ""),
        }
    except Exception as e:
        log.warning("Dexscreener compare failed for %s: %s", ca, e)
        return None


def _build_compare_registry() -> dict:
    reg = {}

    # LENNY immer im Registry
    if LENNY_TOKEN_CA:
        reg["lenny"] = {
            "symbol": "$LENNY",
            "ca": LENNY_TOKEN_CA,
            "url": DEX_TOKEN_URL or "",
        }
        reg["lennyface"] = reg["lenny"]  # Alias

    # TOKEN 1
    if COMPARE_TOKEN_1_NAME and COMPARE_TOKEN_1_CA:
        key = COMPARE_TOKEN_1_NAME.lower().lstrip("$")
        reg[key] = {
            "symbol": f"${COMPARE_TOKEN_1_NAME.upper().lstrip('$')}",
            "ca": COMPARE_TOKEN_1_CA,
            "url": COMPARE_TOKEN_1_URL,
        }

    # TOKEN 2
    if COMPARE_TOKEN_2_NAME and COMPARE_TOKEN_2_CA:
        key = COMPARE_TOKEN_2_NAME.lower().lstrip("$")
        reg[key] = {
            "symbol": f"${COMPARE_TOKEN_2_NAME.upper().lstrip('$')}",
            "ca": COMPARE_TOKEN_2_CA,
            "url": COMPARE_TOKEN_2_URL,
        }

    # TOKEN 3
    if COMPARE_TOKEN_3_NAME and COMPARE_TOKEN_3_CA:
        key = COMPARE_TOKEN_3_NAME.lower().lstrip("$")
        reg[key] = {
            "symbol": f"${COMPARE_TOKEN_3_NAME.upper().lstrip('$')}",
            "ca": COMPARE_TOKEN_3_CA,
            "url": COMPARE_TOKEN_3_URL,
        }

    # TOKEN 4
    if COMPARE_TOKEN_4_NAME and COMPARE_TOKEN_4_CA:
        key = COMPARE_TOKEN_4_NAME.lower().lstrip("$")
        reg[key] = {
            "symbol": f"${COMPARE_TOKEN_4_NAME.upper().lstrip('$')}",
            "ca": COMPARE_TOKEN_4_CA,
            "url": COMPARE_TOKEN_4_URL,
        }

    # TOKEN 5
    if COMPARE_TOKEN_5_NAME and COMPARE_TOKEN_5_CA:
        key = COMPARE_TOKEN_5_NAME.lower().lstrip("$")
        reg[key] = {
            "symbol": f"${COMPARE_TOKEN_5_NAME.upper().lstrip('$')}",
            "ca": COMPARE_TOKEN_5_CA,
            "url": COMPARE_TOKEN_5_URL,
        }

    # TOKEN 6 — BTC über Coingecko
    if COMPARE_TOKEN_6_NAME and COMPARE_TOKEN_6_CA:
        key = COMPARE_TOKEN_6_NAME.lower().lstrip("$")
        reg[key] = {
            "symbol": f"${COMPARE_TOKEN_6_NAME.upper().lstrip('$')}",
            "ca": COMPARE_TOKEN_6_CA,
            "url": COMPARE_TOKEN_6_URL,   # "COINGECKO"
        }

    return reg




# 👉 Muss VOR build_mc_compare_reply definiert werden
COMPARE_REGISTRY = _build_compare_registry()

# === Token-Emojis je Coin (optional) ===
TOKEN_EMOJIS = {
    "pepe":  "🐸",
    "bonk":  "🐾",
    "wif":   "🐶",
    "wojak": "😢",
    "troll": "👹",
    "btc":   "🟧",
    "lenny": "( ͡° ͜ʖ ͡°)",
    "lennyface": "( ͡° ͜ʖ ͡°)",
}



def _extract_compare_keyword(part: str) -> str | None:
    """
    Versucht aus einem Text-Teil (links/rechts von 'vs') ein Token rauszulesen.
    Nimmt erstes 'Wort' aus Buchstaben/Zahlen/$.
    Ignoriert dabei das eigene Bot-Handle (@lennyface_bot).
    """
    part = part.lower()

    # Eigenes Handle rauswerfen, damit nicht "lennyface" erkannt wird
    try:
        handle = BOT_HANDLE.lower()
        part = re.sub(rf"@{re.escape(handle)}\b", " ", part)
    except Exception:
        # Falls aus irgendeinem Grund BOT_HANDLE spinnt: lieber gar nichts machen als crashen
        pass

    candidates = re.findall(r"[a-z0-9$]{2,15}", part)
    for c in candidates:
        c = c.strip().lstrip("$")
        if len(c) >= 2:
            return c
    return None

def _emoji_for_key(key: str) -> str:
    """
    Liefert ein passendes Emoji für bekannte Tokens.
    """
    k = key.lower().lstrip("$")
    if k in ("lenny", "lennyface"):
        return "( ͡° ͜ʖ ͡°)"
    if k == "troll":
        return "👹"
    if k == "pepe":
        return "🐸"
    if k == "bonk":
        return "🐾"
    if k == "wif":
        return "🐶"
    if k == "wojak":
        return "😢"
    if k == "btc":
        return "₿"
    return ""

def _fix_grok_glitches(text: str) -> str:
    """
    Kleine Nachkorrektur für typische Grok-Fehler.
    """
    # "is market cap is" → "market cap is"
    text = text.replace(" is market cap is", " market cap is")
    text = text.replace("is market cap is", " market cap is")

    return text


WISHLIST_FILE = "mc_compare_requests.txt"


def load_mc_wishlist(limit: int = 50) -> list[dict]:
    """
    Liest die gespeicherten MC-Compare-Wunsch-Tokens aus der Datei.
    Rückgabe: Liste von Dicts:
      [
        {"ts": "2025-11-26T22:03:07.985010Z", "token": "shiba", "src": "@..."},
        ...
      ]
    """
    if not os.path.exists(WISHLIST_FILE):
        return []

    rows: list[dict] = []
    with open(WISHLIST_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            # Format: timestamp; token=XYZ; src=...
            parts = line.split(";")
            if not parts:
                continue

            ts = parts[0].strip()
            token = None
            src = None

            for p in parts[1:]:
                p = p.strip()
                if p.startswith("token="):
                    token = p[len("token="):]
                elif p.startswith("src="):
                    src = p[len("src="):]

            if not token:
                continue

            rows.append({
                "ts": ts,
                "token": token,
                "src": src or "",
            })

    # Neueste zuerst
    rows.sort(key=lambda r: r["ts"], reverse=True)
    return rows[:limit]




def build_mc_compare_reply(src: str) -> str:
    """
    'lenny vs troll' / 'mc lenny vs troll' → vergleicht MC von $LENNY und z.B. $TROLL.
    Nutzt COMPARE_REGISTRY + Dexscreener + optional Grok für spicy Text.
    """
    text_lower = src.lower()
    reg = COMPARE_REGISTRY

    # Ohne "vs" → ganz normaler Market-Reply
    if "vs" not in text_lower:
        return build_market_reply(src)

    left, right = text_lower.split("vs", 1)
    left = left.strip()
    right = right.strip()

    left_key = _extract_compare_keyword(left) or "lenny"
    right_key = _extract_compare_keyword(right)

    # Sicherstellen, dass wir 2 verschiedene haben:
    if not right_key:
        # Nur ein Token gefunden → treat as "LENNY vs <that>"
        if left_key in ("lenny", "lennyface"):
            return build_market_reply(src)
        else:
            base_key = "lenny"
            other_key = left_key
    else:
        # Beide Seiten haben ein Keyword → herausfinden, wo Lenny ist
        if left_key in ("lenny", "lennyface"):
            base_key = left_key
            other_key = right_key
        elif right_key in ("lenny", "lennyface"):
            base_key = right_key
            other_key = left_key
        else:
            # Kein Lenny gefunden → nehmen wir Lenny als Basis, andere Seite als Vergleich
            base_key = "lenny"
            other_key = right_key

    base_key = base_key.lstrip("$")
    other_key = other_key.lstrip("$")

    if base_key not in reg:
        base_key = "lenny"  # Fallback

    if other_key not in reg:
        # Token nicht konfiguriert → Wunsch merken + saubere Antwort senden
        known_others = [k for k in reg.keys() if k not in ("lenny", "lennyface")]
        known_str = ""
        if known_others:
            known_str = ", ".join(sorted({reg[k]["symbol"] for k in known_others}))

        # 1) In Logs sichtbar machen
        log.info(
            "Unconfigured MC-compare token requested: %s (src=%r)",
            other_key,
            src,
        )

        # 2) Versuchen, in eine kleine Wunschliste-Datei zu schreiben
        try:
            with open(WISHLIST_FILE, "a", encoding="utf-8") as f:
                f.write(f"{datetime.utcnow().isoformat()}Z; token={other_key}; src={src}\n")
        except Exception as e:
            log.warning("Could not append mc_compare_requests.txt: %s", e)

        # 3) Antwort für den User
        if known_str:
            return (
                f"I can only compare $LENNY with a few configured tokens right now: "
                f"{known_str}. I saved '{other_key}' as a wishlist token for the dev. "
                f"( ͡° ͜ʖ ͡°)"
            )
        else:
            return (
                f"Right now I only know $LENNY for MC compare. "
                f"I saved '{other_key}' as a wishlist token so the dev can add it later. "
                f"( ͡° ͜ʖ ͡°)"
            )


    base_info = reg[base_key]
    other_info = reg[other_key]

    # Stats holen
    base_stats = _fetch_token_stats_for_compare(base_info["ca"], base_info.get("url") or None)
    other_stats = _fetch_token_stats_for_compare(other_info["ca"], other_info.get("url") or None)

    if not base_stats or not other_stats:
        return (
            "Dexscreener didn’t send me enough data to compare MCs right now. "
            "Try again in a minute, degen. ( ͡° ͜ʖ ͡°)"
        )

    base_mc = base_stats["mc"] or 0
    other_mc = other_stats["mc"] or 0

    if base_mc <= 0 or other_mc <= 0:
        return (
            "One of those MCs looks like zero on Dexscreener. "
            "Hard to compare that, ngl. ( ͡⚆ ͜ʖ ͡⚆)"
        )

    # Wie oft größer ist other vs base?
    factor = other_mc / base_mc

    base_mc_str = _format_usd_short(base_mc)
    other_mc_str = _format_usd_short(other_mc)

    # Labels inkl. Emojis
    base_label = base_info["symbol"]
    other_label = other_info["symbol"]

    base_emoji = TOKEN_EMOJIS.get(base_key, "")
    other_emoji = TOKEN_EMOJIS.get(other_key, "")

    if base_emoji:
        base_label = f"{base_label} {base_emoji}"
    if other_emoji:
        other_label = f"{other_label} {other_emoji}"

    log.info(
        "MC Compare: %s (%s) ~ %s MC vs %s (%s) ~ %s MC → factor=%.2fx",
        base_label, base_info["ca"], base_mc_str,
        other_label, other_info["ca"], other_mc_str,
        factor,
    )

    # --- Neutraler Fallback-Text (falls Grok nicht benutzt werden kann) ---
    if factor >= 1:
        fallback_txt = (
            f"{other_label} is sitting at ~{other_mc_str} MC, "
            f"while {base_label} is around ~{base_mc_str}. "
            f"That’s only about {factor:.1f}x difference. "
            f"Not a crazy degen stretch if the smirk-power kicks in. ( ͡° ͜ʖ ͡°)"
        )
    else:
        inv = 1 / factor
        fallback_txt = (
            f"{base_label} is already ahead: ~{base_mc_str} MC vs {other_label} at ~{other_mc_str}. "
            f"That’s roughly {inv:.1f}x bigger. Who’s the real meme king now, huh? ( ͡$ ͜ʖ ͡$)"
        )

    # --- Grok-Spice oben drauf, wenn API-Key vorhanden ---
    txt = fallback_txt
    if GROK_API_KEY:
        try:
            ctx = (
                f"Base token: {base_label} MC={base_mc_str}. "
                f"Other token: {other_label} MC={other_mc_str}. "
                f"Other/Base factor: {factor:.1f}x."
            )

            prompt = (
                "You are LennyBot, a degen meme coin bot speaking to Crypto Twitter.\n"
                "User asked to compare two tokens by Market Cap (MC).\n"
                "Write ONE very short, spicy degen line about the MC difference.\n"
                "- Use the factor to describe how far apart they are (x).\n"
                "- Keep it under 200 characters.\n"
                "- Do NOT include any Lennyface – that will be added later automatically.\n"
                "- Do NOT include any URLs or @mentions.\n"
                "- Feel free to joke if the gap is huge (e.g. 1000x+).\n"
                f"Context: {ctx}"
           )


            grok_answer = grok_generate(prompt) or ""
            grok_answer = grok_answer.strip()

            # URLs raus
            grok_answer = re.sub(r"https?://\S+", "", grok_answer)
            # @handle raus
            try:
                pattern = re.compile(rf"@{re.escape(BOT_HANDLE)}", re.IGNORECASE)
                grok_answer = pattern.sub("", grok_answer)
            except Exception:
                pass

            grok_answer = re.sub(r"\s+", " ", grok_answer).strip()

            if grok_answer:
                txt = _fix_grok_glitches(grok_answer)

        except Exception as e:
            log.warning("Grok MC compare failed: %s", e)
            # txt bleibt fallback_txt

    # --- Token-Emojis direkt an Ticker im Text kleben ---
    emoji_map = {
        "LENNY": "( ͡° ͜ʖ ͡°)",
        "PEPE":  "🐸",
        "BONK":  "🐾",
        "WIF":   "🐶",
        "WOJAK": "😢",
        "TROLL": "👹",
        "BTC":   "🟧",
    }

    for sym, emo in emoji_map.items():
        pattern = rf"\${sym}\b(?!\s*{re.escape(emo)})"
        replace = f"${sym} {emo}"
        txt = re.sub(pattern, replace, txt)

    # Dex-Link (von base) optional anhängen
    if base_stats.get("url"):
        url_part = base_stats["url"].strip()
        if url_part:
            max_len = 280
            reserved = len(url_part) + 1
            if len(txt) + reserved > max_len:
                txt = txt[: max_len - reserved].rstrip(" .,!-")
            txt = f"{txt} {url_part}"

    # FIX — keeps Twitter blue highlight for $tokens
    txt = re.sub(r"\$([A-Za-z0-9]+)’s", r"$\1 is", txt)
    txt = re.sub(r"\$([A-Za-z0-9]+)'s", r"$\1 is", txt)

    return txt

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
            tweet_fields=["author_id", "created_at"],
        )
        if not resp or not resp.data:
            return []
        return list(resp.data)
    except tweepy.TweepyException as e:
        if "429" in str(e) or "Too Many Requests" in str(e):
            log.warning("Fetch mentions rate limited. Sleeping for %d seconds.", LOOP_SLEEP_SECONDS)
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
# Reply-Text bauen (Standard-Shill)
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
# Command Replies (help, lore, alpha, gm, roast)
# =========================

def build_help_reply() -> str:
    """Kurzer Help-Text für die Community (Englisch)."""
    # bewusst ohne Grok, damit stabil & kurz
    return (
        "I’m LennyBot ( ͡° ͜ʖ ͡°) — tag me alone to use commands:\n"
        "help  → show this menu\n"
        "lore  → Lenny meme history\n"
        "price / mc / stats / volume / chart → live $LENNY data\n"
        "alpha → spicy degen alpha line\n"
        "gm    → good-morning reply\n"
        "roast → light roast, no slurs"
    )

def build_lore_reply() -> str:
    """
    Lenny Lore in kurz, mit starken Fakten.
    Keine exakten View-Zahlen erfinden, nur belegbare Aussagen.
    """
    return (
        "Lennyface ( ͡° ͜ʖ ͡°) was born on a Finnish imageboard in 2012 and got "
        "picked up by 4chan, Reddit and gaming chats worldwide. It’s an OG Unicode meme "
        "documented on KnowYourMeme and still used after 10+ years. While frogs and Wojaks "
        "come and go, Lenny is pure ASCII energy — simple, universal and hard to kill. "
        "$LENNY rides that evergreen meme power, not a random clone. #LennyLore"
    )

def build_alpha_reply(context_snippet: str = "") -> str:
    """Kurze Alpha-Line, optional mit Grok, sonst Fallback."""
    base = (
        "Drop one short degen alpha line about $LENNY. Be confident but not promising profits. "
        "Max 200 chars."
    )
    if GROK_API_KEY:
        prompt = base + f" Context tweet: {context_snippet[:180]}"
        txt = grok_generate(prompt)
        if txt:
            return re.sub(r"\s+", " ", txt).strip()

    return (
        "Alpha? Simple: early on $LENNY, strong meme, real degen culture. "
        "No guarantees, but I know which side of history I’d pick ( ͡° ͜ʖ ͡°) #LennyAlpha"
    )

def build_gm_reply(context_snippet: str = "") -> str:
    """GM-Antwort, leicht degen."""
    if GROK_API_KEY:
        prompt = (
            "Write a short GM reply in degen style for $LENNY. "
            "Max 160 chars, include ( ͡° ͜ʖ ͡°) and 1-2 crypto hashtags. "
            f"Original tweet: {context_snippet[:180]}"
        )
        txt = grok_generate(prompt)
        if txt:
            return re.sub(r"\s+", " ", txt).strip()

    return "GM degen, stack $LENNY, sip coffee, ignore jeets ( ͡° ͜ʖ ͡°) #GM #Lenny"

def build_roast_reply(context_snippet: str = "") -> str:
    """
    Leichter Roast – kein Hate, keine Slurs.
    Nur spielerisches Necken.
    """
    if GROK_API_KEY:
        prompt = (
            "User asked to be roasted. Write a short, playful roast in degen style, "
            "but no slurs, hate speech or real-life threats. Include $LENNY and ( ͡° ͜ʖ ͡°). "
            "Max 200 chars. Tweet: " + context_snippet[:180]
        )
        txt = grok_generate(prompt)
        if txt:
            return re.sub(r"\s+", " ", txt).strip()

    templates = [
        "You call that a portfolio? Even my memecoins laugh at you. Touch some $LENNY and try again ( ͡° ͜ʖ ͡°)",
        "Bro, your bags look like you bought every top since 2021. Time to upgrade your taste with $LENNY ( ͡° ͜ʖ ͡°)",
        "I’ve seen more conviction in paper straws than in your entries. At least $LENNY is holding strong ( ͡° ͜ʖ ͡°)",
    ]
    return random.choice(templates)

# =========================
# Helius – Whale Watcher
# =========================

HELIUS_API_KEY       = os.environ.get("HELIUS_API_KEY", "").strip()
HELIUS_POLL_SECONDS  = int(os.environ.get("HELIUS_POLL_SECONDS", "45"))
HELIUS_MIN_BUY_SOL   = float(os.environ.get("HELIUS_MIN_BUY_SOL", "5"))  # ab wie viel SOL = Whale
HELIUS_LAST_SIG_ENV  = "HELIUS_LAST_SIGNATURE"

# optional: für später, wenn wir Tweets schicken wollen
HELIUS_WHALE_TWEETS_ENABLED = os.environ.get("HELIUS_WHALE_TWEETS_ENABLED", "0") == "1"

# Pump/Raydium etc. – wir starten erst mal einfach mit "alle Transfers in den Lenny-Pool"
# Dafür brauchen wir den Pool-Account, aber fürs MVP zeigen wir nur Logs.

# Helius – Whale Watcher
HELIUS_API_KEY       = os.environ.get("HELIUS_API_KEY", "").strip()
HELIUS_POLL_SECONDS  = int(os.environ.get("HELIUS_POLL_SECONDS", "45"))

# MIN-Buy / Sell (delta in SOL)
HELIUS_MIN_BUY_SOL      = float(os.environ.get("HELIUS_MIN_BUY_SOL", "2"))   # normaler Buy
HELIUS_MIN_WHALE_SOL    = float(os.environ.get("HELIUS_MIN_WHALE_SOL", "10"))  # Whale-Buy
HELIUS_MIN_SELL_SOL     = float(os.environ.get("HELIUS_MIN_SELL_SOL", "5"))  # großer Sell für Stats
HELIUS_LAST_SIG_ENV  = "HELIUS_LAST_SIGNATURE"

# Tweets für Whales
HELIUS_BUY_TWEETS_ENABLED   = os.environ.get("HELIUS_BUY_TWEETS_ENABLED", "1") == "1"
HELIUS_WHALE_TWEETS_ENABLED = os.environ.get("HELIUS_WHALE_TWEETS_ENABLED", "1") == "1"
HELIUS_SELL_STATS_ENABLED   = os.environ.get("HELIUS_SELL_STATS_ENABLED", "1") == "1"

# In-Memory Anti-Spam für TXs (damit wir dieselbe Signatur nicht dauernd verarbeiten)
WHALE_SEEN_SIGS: set[str] = set()
MAX_WHALE_SEEN = 500


def _get_helius_base_url() -> str:
    """
    Standard-RPC Endpoint von Helius für parsed transactions.
    """
    if not HELIUS_API_KEY:
        return ""
    return f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"


def _load_last_helius_sig() -> str | None:
    """
    Letzte verarbeitete Signature aus ENV lesen (wenn vorhanden).
    """
    return os.environ.get(HELIUS_LAST_SIG_ENV, "").strip() or None


def _load_last_helius_sig() -> str | None:
    """
    Letzte verarbeitete Signature aus der lokalen Prozess-Env lesen (nur für aktuellen Dyno-Lauf).
    Kein Heroku-Config-Write, damit keine Restarts ausgelöst werden.
    """
    return os.environ.get(HELIUS_LAST_SIG_ENV, "").strip() or None


def _save_last_helius_sig(sig: str):
    """
    Letzte Signature nur im laufenden Prozess merken.
    KEIN Aufruf von _set_config_vars → keine neuen Releases, keine Restarts.
    """
    if not sig:
        return
    os.environ[HELIUS_LAST_SIG_ENV] = sig
    log.info("Helius: last signature updated (local only) → %s", sig)



def _helius_fetch_recent_txs(limit: int = 50) -> list[dict]:
    """
    Holt die letzten Transaktionen für das $LENNY Mint über Helius.
    Für MVP: wir holen einfach alle Transaktionen, später filtern wir gezielter auf Pool/DEX.
    """
    if not HELIUS_API_KEY or not LENNY_TOKEN_CA:
        return []

    url = _get_helius_base_url()
    if not url:
        return []

    payload = {
        "jsonrpc": "2.0",
        "id": "lenny-whales",
        "method": "getSignaturesForAddress",
        "params": [
            LENNY_TOKEN_CA,
            {
                "limit": limit
            }
        ]
    }

    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        data = r.json() or {}
        result = data.get("result") or []
        log.info("Helius: fetched %d signatures for %s", len(result), LENNY_TOKEN_CA)
        return result
    except Exception as e:
        log.warning("Helius getSignaturesForAddress failed: %s", e)
        return []


def _helius_get_parsed_tx(signature: str) -> dict | None:
    """
    Holt die parsed Transaction für eine Signatur.
    """
    if not HELIUS_API_KEY:
        return None

    url = _get_helius_base_url()
    if not url:
        return None

    payload = {
        "jsonrpc": "2.0",
        "id": "lenny-whales-tx",
        "method": "getTransaction",
        "params": [
            signature,
            {
                "encoding": "jsonParsed",
                "maxSupportedTransactionVersion": 0
            }
        ]
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        r.raise_for_status()
        data = r.json() or {}
        return data.get("result") or None
    except Exception as e:
        log.warning("Helius getTransaction failed for %s: %s", signature, e)
        return None


def _estimate_sol_in_tx(tx: dict) -> float:
    """
    Gibt eine *signierte* SOL-Änderung für den Fee-Payer zurück.

    > 0  → Fee-Payer hat SOL ausgegeben  (typisch BUY in den Pool)
    < 0  → Fee-Payer hat SOL bekommen   (typisch SELL / Exit aus dem Pool)
    """
    try:
        meta = tx.get("meta") or {}
        pre = meta.get("preBalances") or []
        post = meta.get("postBalances") or []
        if not pre or not post:
            return 0.0

        # nur Index 0 (Fee-Payer)
        sol_before = pre[0] / 1e9
        sol_after  = post[0] / 1e9

        # POSITIV = SOL ging raus (er hat bezahlt → eher BUY)
        # NEGATIV = SOL kam rein (er hat bekommen → eher SELL)
        return sol_before - sol_after
    except Exception:
        return 0.0

# =========================
# Lenny Helius Trade Tweets (Buys + Whales)
# =========================
import random

# Fallback-Templates, falls Grok nichts liefert
NORMAL_BUY_TEMPLATES = [
    "Smol degen buy: ~{sol:.2f} SOL into $LENNY. Brick by brick. ( ͡° ͜ʖ ͡°)",
    "Fresh $LENNY buy spotted: ~{sol:.2f} SOL. Chads quietly stacking.",
    "Another ~{sol:.2f} SOL just flowed into $LENNY. Slow grind up only.",
]

WHALE_BUY_TEMPLATES = [
    "Whale aped ~{sol:.2f} SOL into $LENNY! Moon mission fueled, degens—LFG! 🚀 #LENNY #SolanaSzn",
    "🐳 Big smirk energy: ~{sol:.2f} SOL just slammed into $LENNY. Chads stack, jeets cope.",
    "Fresh whale just dropped ~{sol:.2f} SOL on $LENNY. Smirk, sip, enjoy the green candles.",
]


def build_lenny_trade_tweet(sol_delta: float, signature: str, kind: str) -> str:
    """
    kind:
      - 'normal_buy'
      - 'whale_buy'
      - 'sell' (aktuell nur für später, wir twittern Sells nicht)
    sol_delta: signiertes Delta (SOL). Für Text nehmen wir abs(sol_delta).
    """
    amount = abs(sol_delta)
    base = ""

    # 1) Versuche Grok-Text zu generieren (nur für Buys sinnvoll)
    if GROK_API_KEY and kind in ("normal_buy", "whale_buy"):
        if kind == "whale_buy":
            mood = "very bullish, hype, but no promises, degen fun"
        else:
            mood = "positive, degen, small buy, accumulation vibe"

        prompt = (
            "Write ONE short degen-style Twitter line about a buy into $LENNY.\n"
            f"- Type: {kind}\n"
            f"- Amount: ~{amount:.2f} SOL\n"
            f"- Tone: {mood}\n"
            "- Max 200 characters.\n"
            "- No links, no @mentions.\n"
            "- Do NOT include any Lennyface, that will be added later.\n"
            "- Prefer 1–2 relevant hashtags like #LENNY #Solana.\n"
        )

        try:
            base = grok_generate(prompt) or ""
            base = re.sub(r"\s+", " ", base).strip()
        except Exception as e:
            log.warning("Grok trade text failed: %s", e)
            base = ""

    # 2) Fallback-Templates, wenn Grok nichts liefert
    if not base:
        if kind == "whale_buy":
            template = random.choice(WHALE_BUY_TEMPLATES)
        elif kind == "normal_buy":
            template = random.choice(NORMAL_BUY_TEMPLATES)
        else:
            # Für Sells (falls wir später mal twittern wollen)
            template = "Big move: ~{sol:.2f} SOL trade on $LENNY. Degens watching."
        base = template.format(sol=amount)

    # 3) Lennyface + Season-Deko
    base = decorate_with_lenny_face(base, cmd_used="whale")

    # 4) Standard-Hashtags absichern (falls Grok keine gesetzt hat)
    up = base.upper()
    if "#LENNY" not in up:
        base += " #LENNY"
    if "#SOLANA" not in up:
        base += " #Solana"

    # 5) Solscan-Link anhängen
    tx_url = f"https://solscan.io/tx/{signature}"

    max_len = 280
    reserved = len(tx_url) + 1  # Leerzeichen + URL

    if len(base) + reserved > max_len:
        base = base[: max_len - reserved].rstrip(" .,!-\n")

    return f"{base} {tx_url}"


def _remember_whale_sig(sig: str):
    """Merk dir, welche Signaturen wir schon verarbeitet haben (Anti-Doppel-Check)."""
    try:
        WHALE_SEEN_SIGS.add(sig)
        if len(WHALE_SEEN_SIGS) > MAX_WHALE_SEEN:
            # irgendeinen alten rauswerfen
            WHALE_SEEN_SIGS.pop()
    except Exception:
        pass


def check_lenny_whales_once():
    """
    Whale/Buy-Check:
    - fetch signatures via Helius
    - parse new ones
    - detect normal buys, whale buys & sells
    - twittern: nur Buys (normal + whale), keine Sells
    """
    log.info(
        "Helius-check: api_key_set=%s, lenny_ca=%s, normal_buy=%.3f, whale_buy=%.3f, sell_thr=%.3f",
        bool(HELIUS_API_KEY),
        LENNY_TOKEN_CA,
        HELIUS_MIN_NORMAL_BUY_SOL,
        HELIUS_MIN_WHALE_BUY_SOL,
        HELIUS_MIN_SELL_SOL,
    )

    if not HELIUS_API_KEY or not LENNY_TOKEN_CA:
        log.info("Helius or LENNY_TOKEN_CA missing → whale watcher inactive.")
        return

    last_known_sig = _load_last_helius_sig()
    sigs = _helius_fetch_recent_txs(limit=30)
    if not sigs:
        return

    # neue Signaturen filtern
    new_sigs: list[str] = []
    for row in sigs:
        sig = row.get("signature")
        if not sig:
            continue
        if last_known_sig and sig == last_known_sig:
            break
        new_sigs.append(sig)

    if not new_sigs:
        return

    # ältere zuerst prüfen
    new_sigs = list(reversed(new_sigs))
    log.info("Helius: checking %d new signatures for whales/buys", len(new_sigs))

    last_processed = None

    for sig in new_sigs:
        # Anti-Spam: Signatur schon mal gesehen?
        if sig in WHALE_SEEN_SIGS:
            continue
        _remember_whale_sig(sig)

        tx = _helius_get_parsed_tx(sig)
        if not tx:
            continue

        sol_delta = _estimate_sol_in_tx(tx)  # Buy > 0, Sell < 0
        log.info(
            "Helius TX: signature=%s ~ %.4f SOL delta (normal_buy_thr=%.3f / whale_buy_thr=%.3f / sell_thr=%.3f)",
            sig,
            sol_delta,
            HELIUS_MIN_NORMAL_BUY_SOL,
            HELIUS_MIN_WHALE_BUY_SOL,
            HELIUS_MIN_SELL_SOL,
        )

        trade_type = None

        # Whale-Buy
        if sol_delta >= HELIUS_MIN_WHALE_BUY_SOL:
            trade_type = "whale_buy"

        # Normaler Buy
        elif sol_delta >= HELIUS_MIN_NORMAL_BUY_SOL:
            trade_type = "normal_buy"

        # Großer Sell (nur loggen, nicht twittern)
        elif sol_delta <= -HELIUS_MIN_SELL_SOL:
            trade_type = "sell"

        # sonst: kleiner Move → ignorieren
        if trade_type is None:
            last_processed = sig
            continue

        # --- Handle Buys (Tweets) ---
        if trade_type == "whale_buy":
            log.info(
                "🐳 Whale detected (BUY): signature=%s ~ %.3f SOL",
                sig,
                sol_delta,
            )
            if HELIUS_WHALE_TWEETS_ENABLED:
                try:
                    tweet_text = build_lenny_trade_tweet(sol_delta, sig, kind="whale_buy")
                    client.create_tweet(text=tweet_text)
                    log.info("🐳 Whale BUY Tweet sent: %s", tweet_text)
                except Exception as e:
                    log.error("Whale BUY tweet failed: %s", e)

        elif trade_type == "normal_buy":
            log.info(
                "✅ Normal buy detected: signature=%s ~ %.3f SOL",
                sig,
                sol_delta,
            )
            if HELIUS_NORMAL_BUY_TWEETS_ENABLED:
                try:
                    tweet_text = build_lenny_trade_tweet(sol_delta, sig, kind="normal_buy")
                    client.create_tweet(text=tweet_text)
                    log.info("✅ Normal BUY Tweet sent: %s", tweet_text)
                except Exception as e:
                    log.error("Normal BUY tweet failed: %s", e)

        # --- Sells nur loggen (für späteres Dashboard/Stats) ---
        elif trade_type == "sell":
            log.info(
                "📉 Big SELL detected (log only): signature=%s ~ %.3f SOL",
                sig,
                sol_delta,
            )
            # TODO: hier später Stats/Dashboard-Update einbauen

        last_processed = sig

    if last_processed:
        _save_last_helius_sig(last_processed)
        log.info("Helius: last signature updated → %s", last_processed)


# =========================
# Main Loop
# =========================
def main():

    # *** NEU: Start-Delay verhindert sofortiges Rate-Limit nach Deploy ***
    log.info("Warte 30 Sekunden, um Rate-Limit nach Deploy zu vermeiden…")
    time.sleep(30)
    # *** ENDE NEU ***

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

                    # Anti-Repeat: pro User nur alle X Sekunden antworten
                    author_id = getattr(tw, "author_id", None)
                    if author_id is None:
                        log.warning("Mention %s has no author_id, using fallback key", tid)
                        author_id_str = f"anon-{tid}"
                    else:
                        author_id_str = str(author_id)

                    if not can_reply_to_user(author_id_str):
                        log.info(
                            "Skip mention %s from user %s due to user cooldown (%ds)",
                            tid,
                            author_id_str,
                            USER_REPLY_COOLDOWN_S,
                        )
                        remember_and_maybe_backup(tid)
                        continue

                    # --- Command-Erkennung mit Toggles ---
                    src_lower = src.lower()
                    cmd_used = None  # für User-Memory

                    # DEBUG: Command-Detection loggen
                    log.info("Command detection for mention %s: %s", tid, src_lower)

                    # --- NEU: Scam-Link-Check ---
                    if has_suspicious_link(src):
                        # Wenn ein verdächtiger Link im User-Tweet ist:
                        # → KEIN normaler Command, nur Warnung schicken
                        text = build_scam_warning_reply(src)
                        cmd_used = "scam_warn"

                    else:
                        # 1) HELP
                        if "help" in src_lower and "mc" not in src_lower and "vs" not in src_lower:
                            if not ENABLE_HELP:
                                log.info("help command ignored (disabled)")
                                remember_and_maybe_backup(tid)
                                continue
                            text = build_help_reply()
                            cmd_used = "help"

                        # 2) LORE
                        elif "lore" in src_lower:
                            if not ENABLE_LORE:
                                log.info("lore command ignored (disabled)")
                                remember_and_maybe_backup(tid)
                                continue
                            text = build_lore_reply()
                            cmd_used = "lore"

                        # 3) MC COMPARE (z.B. "lenny vs troll", "bonk vs lenny", mit oder ohne 'mc')
                        elif "vs" in src_lower and any(tok in src_lower for tok in [
                            "lenny", "lennyface", "$lenny",
                            "troll", "$troll",
                            "bonk", "$bonk",
                            "pepe", "$pepe",
                            "wojak", "$wojak",
                            "wif", "$wif",
                            "btc", "bitcoin",
                        ]):
                            log.info("Using MC_COMPARE for: %s", src)
                            text = build_mc_compare_reply(src)
                            cmd_used = "mc_compare"

                        # 4) PRICE / MC / STATS / VOLUME / CHART (Standard)
                        elif any(k in src_lower for k in [
                            "price", " mc", "market cap", "marketcap",
                            "volume", "vol ", "stats", "chart"
                        ]):
                            if not ENABLE_STATS:
                                log.info("stats/price/mc command ignored (disabled)")
                                remember_and_maybe_backup(tid)
                                continue
                            text = build_market_reply(src)
                            cmd_used = "price"

                        # 5) ALPHA
                        elif "alpha" in src_lower:
                            if not ENABLE_ALPHA:
                                log.info("alpha command ignored (disabled)")
                                remember_and_maybe_backup(tid)
                                continue
                            text = build_alpha_reply(src)
                            cmd_used = "alpha"

                        # 6) GM
                        elif src_lower.startswith("gm") or " gm" in src_lower:
                            if not ENABLE_GM:
                                log.info("gm command ignored (disabled)")
                                remember_and_maybe_backup(tid)
                                continue
                            text = build_gm_reply(src)
                            cmd_used = "gm"

                        # 7) ROAST
                        elif "roast me" in src_lower or " roast" in src_lower:
                            if not ENABLE_ROAST:
                                log.info("roast command ignored (disabled)")
                                remember_and_maybe_backup(tid)
                                continue
                            text = build_roast_reply(src)
                            cmd_used = "roast"

                        # 8) Default-Shill
                        else:
                            text = build_reply_text(src)
                            cmd_used = "shill"

                    # SAFETY: falls irgendeine Funktion None zurückgibt
                    if not text:
                        log.warning("Empty text from command '%s', using fallback.", cmd_used)
                        text = "My brain just lagged, degen. Try again in a sec. ( ͡° ͜ʖ ͡°)"

                    # eigenes Handle aus der Antwort entfernen (Grok baut oft @lennyface_bot ein)
                    try:
                        pattern = re.compile(rf"@{re.escape(BOT_HANDLE)}", re.IGNORECASE)
                        text = pattern.sub("", text)
                        text = re.sub(r"\s+", " ", text).strip()
                    except Exception:
                        pass

                    # Dialekt / Ton anpassen
                    text = apply_dialect(text, cmd_used)

                    # LennyFace + Season anhängen
                    text = decorate_with_lenny_face(text, cmd_used)

                    # User-Memory updaten
                    update_user_profile(author_id_str, cmd_used)

                    # Unsichere Links aus der Antwort entfernen
                    text = sanitize_reply_links(text)

                    # Danach personalisieren
                    text = personalize_reply(text, author_id_str)

                    # Meme-Entscheidung (smart)
                    with_meme = should_attach_meme(src, is_mention=True)

                    try:
                        post_reply(text, tid, with_meme)
                        remember_and_maybe_backup(tid)

                        # Anti-Repeat: Zeitstempel setzen
                        mark_replied_to_user(author_id_str)

                        # Stats fürs Dashboard
                        bump_stats(kind="mention", used_meme=with_meme)

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

                if not tweets:
                    continue

                # von alt → neu
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

                    src_text = tw.text or ""
                    text = build_reply_text(src_text)

                    # Smart Meme Boost (für KOL-Tweets → is_mention=False)
                    with_meme = should_attach_meme(src_text, is_mention=False)

                    try:
                        post_reply(text, tid, with_meme)
                        remember_and_maybe_backup(tid)
                        bump_stats(kind="kol", used_meme=with_meme)
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
                            log.warning("Rate limit exceeded. Sleeping for %d seconds.", LOOP_SLEEP_SECONDS)
                            time.sleep(LOOP_SLEEP_SECONDS)
                        else:
                            log.warning("Reply fehlgeschlagen: %s", e)
                    except Exception as e:
                        log.warning("Reply fehlgeschlagen: %s", e)

            # 3) Whale-Check (MVP – nur Logs)
            try:
                check_lenny_whales_once()
            except Exception as e:
                log.warning("Helius whale-check failed: %s", e)


            # Hauptschlaf am Ende der Schleife
            time.sleep(LOOP_SLEEP_SECONDS)

        except Exception as e:
            log.error("Loop error: %s", e)
            traceback.print_exc()
            # Crash vermeiden, kurze Pause
            time.sleep(10)


if __name__ == "__main__":
    main()
