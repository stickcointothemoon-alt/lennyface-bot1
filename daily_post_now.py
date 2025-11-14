import os
import random
import logging
import requests

from bot_basic import client, choose_meme, upload_media_get_id, grok_generate

log = logging.getLogger(__name__)

# ENV: Contract-Adresse von $LENNY (z.B. Solana CA)
LENNY_TOKEN_CA = os.getenv("LENNY_TOKEN_CA", "").strip()

DEX_TOKEN_URL = os.getenv("DEX_TOKEN_URL", "").strip()
# Falls du keinen eigenen Link setzen willst:
# Wenn DEX_TOKEN_URL leer ist, nehmen wir Dexscreener-Standard:
# https://api.dexscreener.com/latest/dex/tokens/<CA>


def fetch_lenny_stats():
    """
    Holt Preis, MC und 24h Volumen von Dexscreener
    und gibt ein Dictionary zurück oder None.
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

        pair = pairs[0]  # erstes Pair nehmen
        price = float(pair.get("priceUsd") or 0)
        mc = float(pair.get("fdv") or pair.get("marketCap") or 0)
        vol24 = float(
            pair.get("volume", {}).get("h24") or
            pair.get("volume24h") or
            0
        )

        return {
            "price": price,
            "mc": mc,
            "vol24": vol24,
            "dex_name": pair.get("dexId", ""),
            "pair_url": pair.get("url", ""),
        }
    except Exception as e:
        log.warning("DEX-Request fehlgeschlagen: %s", e)
        return None


def format_number(n):
    """Zahlen hübsch formatieren."""
    if n >= 1_000_000_000:
        return f"{n/1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n/1_000:.2f}K"
    return f"{n:.2f}"


def build_daily_text(stats: dict | None) -> str:
    """
    Baut den Text für den Daily-Post.
    Nutzt Grok, wenn verfügbar, sonst Fallback.
    """
    if not stats:
        base = "LENNY daily dose. $LENNY ( ͡° ͜ʖ ͡°)"
        return base + " #Lenny #Solana #Memecoins"

    price = stats["price"]
    mc = stats["mc"]
    vol = stats["vol24"]

    price_str = f"${price:.6f}" if price < 1 else f"${price:.4f}"
    mc_str = format_number(mc)
    vol_str = format_number(vol)

    # Fallback-Text:
    fallback = (
        f"$LENNY daily stats ( ͡° ͜ʖ ͡°)\n"
        f"Price: {price_str}\n"
        f"MC: {mc_str}\n"
        f"24h Vol: {vol_str}\n"
        "#Lenny #Solana #Memecoins"
    )

    # Wenn kein Grok-Key → nur Fallback
    grok_key = os.getenv("GROK_API_KEY", "")
    if not grok_key:
        return fallback

    # Mit Grok einen frechen Market-Text bauen
    ctx = (
        f"Price: {price_str}, Market Cap: {mc_str}, 24h Volume: {vol_str}. "
        "Short, funny degen update for $LENNY."
    )
    prompt = (
        "Write a very short, cheeky daily market update for $LENNY. "
        "Use the numbers I give you, but keep it under 220 characters. "
        "Add 1-2 crypto hashtags. "
        f"Context: {ctx}"
    )

    try:
        txt = grok_generate(prompt)
        if not txt:
            return fallback
        return txt
    except Exception as e:
        log.warning("Grok für Daily-Post fehlgeschlagen: %s", e)
        return fallback


def main():
    print("📅 Starte LENNY Daily-Post...")

    stats = fetch_lenny_stats()
    text = build_daily_text(stats)
    print("Tweet-Text:\n", text)

    # Meme wählen (aus bot_basic)
    meme_path = choose_meme("memes")
    media_ids = None
    if meme_path:
        try:
            mid = upload_media_get_id(meme_path)
            if mid:
                media_ids = [mid]
                print(f"🎯 Verwende Meme: {os.path.basename(meme_path)}")
        except Exception as e:
            print(f"⚠️ Meme-Upload fehlgeschlagen (poste nur Text): {e}")

    kwargs = {"text": text}
    if media_ids:
        kwargs["media_ids"] = media_ids

    client.create_tweet(**kwargs)
    print("✅ Daily-Post gesendet.")


if __name__ == "__main__":
    main()
