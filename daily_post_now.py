# daily_post_now.py
import os
import random
import logging
from datetime import datetime, timezone
from pathlib import Path

import requests
import tweepy

from fetch_memes import main as fetch_memes_main

# =========================
# Logging
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
LOG = logging.getLogger("daily")

# =========================
# ENV / Keys
# =========================
X_API_KEY       = os.environ.get("X_API_KEY")
X_API_SECRET    = os.environ.get("X_API_SECRET")
X_ACCESS_TOKEN  = os.environ.get("X_ACCESS_TOKEN")
X_ACCESS_SECRET = os.environ.get("X_ACCESS_SECRET")
X_BEARER_TOKEN  = os.environ.get("X_BEARER_TOKEN")

LENNY_TOKEN_CA  = os.environ.get("LENNY_TOKEN_CA", "").strip()
DEX_TOKEN_URL   = os.environ.get("DEX_TOKEN_URL", "").strip()

GROK_API_KEY    = os.environ.get("GROK_API_KEY", "")
GROK_BASE_URL   = os.environ.get("GROK_BASE_URL", "https://api.x.ai")
GROK_MODEL      = os.environ.get("GROK_MODEL", "grok-3")
GROK_TONE             = os.environ.get("GROK_TONE", "normal")
GROK_FORCE_ENGLISH    = os.environ.get("GROK_FORCE_ENGLISH", "1")
GROK_ALWAYS_SHILL_LENNY = os.environ.get("GROK_ALWAYS_SHILL_LENNY", "1")
GROK_EXTRA_PROMPT     = os.environ.get("GROK_EXTRA_PROMPT", "")

MEME_DIR = Path("memes")
VALID_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


# =========================
# X Clients
# =========================
def get_client_v2() -> tweepy.Client:
    return tweepy.Client(
        bearer_token=X_BEARER_TOKEN,
        consumer_key=X_API_KEY,
        consumer_secret=X_API_SECRET,
        access_token=X_ACCESS_TOKEN,
        access_token_secret=X_ACCESS_SECRET,
        wait_on_rate_limit=True,
    )


def get_api_v1() -> tweepy.API:
    auth = tweepy.OAuth1UserHandler(
        X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET
    )
    return tweepy.API(auth, wait_on_rate_limit=True)


# =========================
# Memes
# =========================
def ensure_memes_downloaded():
    """ZIP von Dropbox ziehen (FETCH_MEMES_URL) und nach ./memes entpacken."""
    LOG.info("🧷 Hole Memes über fetch_memes.py ...")
    try:
        fetch_memes_main()
        LOG.info("✅ Memes geladen (falls ZIP verfügbar war).")
    except Exception as e:
        LOG.warning("fetch_memes.py fehlgeschlagen: %s", e)


def choose_meme() -> Path | None:
    MEME_DIR.mkdir(exist_ok=True)
    files = [p for p in MEME_DIR.iterdir() if p.is_file() and p.suffix.lower() in VALID_EXT]
    if not files:
        return None
    return random.choice(files)


def upload_media_return_id(api_v1: tweepy.API, meme_path: Path) -> str | None:
    try:
        media = api_v1.media_upload(filename=str(meme_path))
        return media.media_id_string
    except Exception as e:
        LOG.warning("Meme upload failed: %s", e)
        return None


# =========================
# Dexscreener / Market
# =========================
def format_number(n: float) -> str:
    """Zahlen hübsch formatieren (K, M, B)."""
    if n >= 1_000_000_000:
        return f"{n/1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n/1_000:.2f}K"
    return f"{n:.2f}"


def fetch_lenny_stats():
    """
    Holt Stats von Dexscreener.
    Gibt dict mit price, mc, vol24, price_str, mc_str, vol_str, dex_name, pair_url oder None.
    """
    if DEX_TOKEN_URL:
        url = DEX_TOKEN_URL
    else:
        if not LENNY_TOKEN_CA:
            LOG.warning("LENNY_TOKEN_CA fehlt – keine DEX-Daten.")
            return None
        url = f"https://api.dexscreener.com/latest/dex/tokens/{LENNY_TOKEN_CA}"

    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        pairs = data.get("pairs") or []
        if not pairs:
            LOG.warning("Keine Pair-Daten von Dex erhalten.")
            return None

        pair = pairs[0]
        price = float(pair.get("priceUsd") or 0)
        mc    = float(pair.get("fdv") or pair.get("marketCap") or 0)
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
        LOG.info("LENNY Stats: %s", out)
        return out
    except Exception as e:
        LOG.warning("DEX-Request im Daily-Post fehlgeschlagen: %s", e)
        return None


# =========================
# Grok Helpers
# =========================
def build_grok_system_prompt() -> str:
    base = (
        "You are LENNY, a cheeky, degen-style shill-bot for the $LENNY token. "
        "Reply in short, punchy, funny style. Avoid duplicate text, vary wording. "
        "Always keep replies suitable for public social media."
    )

    tone = (GROK_TONE or "normal").lower()
    if tone == "soft":
        base += " Keep your tone friendly and kind, low aggression."
    elif tone == "spicy":
        base += " You may be a bit edgy and teasing, but avoid real toxicity."
    elif tone == "savage":
        base += (
            " Use a savage, roasting banter style, but never use slurs, "
            "hate speech or real-life threats. Keep it fun."
        )
    else:
        base += " Use a balanced degen tone: fun, confident, slightly cheeky."

    if GROK_FORCE_ENGLISH == "1":
        base += " Always respond in English."

    if GROK_ALWAYS_SHILL_LENNY == "1":
        base += " Always mention $LENNY somewhere in the reply when it makes sense."

    extra = (GROK_EXTRA_PROMPT or "").strip()
    if extra:
        base += " Extra style instructions: " + extra

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
            "max_tokens": 120,
        }
        r = requests.post(url, headers=headers, json=payload, timeout=20)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        LOG.warning("Grok im Daily-Post failed: %s", e)
        return ""


# =========================
# Daily-Text (nur MC)
# =========================
def build_daily_text() -> str:
    stats = fetch_lenny_stats()
    if stats:
        mc_str = stats["mc_str"]

        prompt = (
            "Write a daily tweet for the $LENNY token using ONLY the Market Cap number. "
            f"Market Cap: {mc_str}. "
            "Tone: bullish degen, funny, under 220 characters. "
            "Include the Lennyface ( ͡° ͜ʖ ͡°) and 1-2 crypto hashtags."
        )
        txt = grok_generate(prompt)
        if txt:
            return txt.strip()

        # Fallback ohne Grok
        return (
            f"Daily $LENNY update: Market Cap sitting at {mc_str}. "
            "Still early, still spicy ( ͡° ͜ʖ ͡°) #Lenny #Solana"
        )
    else:
        return (
            "No fresh $LENNY Market Cap today, but the meme energy never dies "
            "( ͡° ͜ʖ ͡°) #Lenny #Solana"
        )


# =========================
# Main
# =========================
def main():
    LOG.info("📅 Starte LENNY Daily-Post (mit Grok & Memes)...")

    # Memes updaten / laden
    ensure_memes_downloaded()

    client = get_client_v2()
    api_v1 = get_api_v1()

    # Text bauen (nur MC)
    base_text = build_daily_text()

    # Datum + random Tag (wie früher #433 etc.)
    tag_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rand_tag = random.randint(100, 999)
    full_text = f"{base_text.strip()} | {tag_date} #{rand_tag}"

    LOG.info("Tweet-Text:\n%s", full_text)

    # Meme wählen
    meme_path = choose_meme()
    media_id = None
    if meme_path:
        LOG.info("🎯 Verwende Meme: %s", meme_path)
        media_id = upload_media_return_id(api_v1, meme_path)
    else:
        LOG.warning("Kein Meme gefunden – poste nur Text.")

    # Tweet senden
    kwargs = {"text": full_text}
    if media_id:
        kwargs["media_ids"] = [media_id]

    client.create_tweet(**kwargs)
    LOG.info("✅ Daily-Post gesendet.")


if __name__ == "__main__":
    main()
