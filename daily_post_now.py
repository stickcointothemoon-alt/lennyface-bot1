# daily_post_now.py
import os
import random
import logging
from datetime import datetime

import requests
import tweepy

# Wir nutzen Funktionen/Clients aus deinem Bot
from bot_basic import client, upload_media_get_id, choose_meme, grok_generate

log = logging.getLogger(__name__)

# Dexscreener-Config aus ENV
DEX_TOKEN_URL   = os.environ.get("DEX_TOKEN_URL", "").strip()
LENNY_TOKEN_CA  = os.environ.get("LENNY_TOKEN_CA", "").strip()


def fetch_lenny_stats():
    """
    Holt Price / MC / 24h Vol für $LENNY von Dexscreener.
    Nutzt DEX_TOKEN_URL (API!) oder LENNY_TOKEN_CA.
    Gibt ein dict mit Zahlen UND formatierten Strings zurück oder None.
    """
    if DEX_TOKEN_URL:
        url = DEX_TOKEN_URL
    else:
        if not LENNY_TOKEN_CA:
            log.warning("Kein DEX_TOKEN_URL und kein LENNY_TOKEN_CA gesetzt.")
            return None
        url = f"https://api.dexscreener.com/latest/dex/tokens/{LENNY_TOKEN_CA}"

    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        pairs = data.get("pairs") or []
        if not pairs:
            log.warning("Keine Pairs in Dexscreener-Response.")
            return None

        pair = pairs[0]
        price = float(pair.get("priceUsd") or 0)
        mc    = float(pair.get("fdv") or pair.get("marketCap") or 0)
        vol24 = float(
            (pair.get("volume") or {}).get("h24")
            or pair.get("volume24h")
            or 0
        )

        def fmt(n: float) -> str:
            if n >= 1_000_000_000:
                return f"{n/1_000_000_000:.2f}B"
            if n >= 1_000_000:
                return f"{n/1_000_000:.2f}M"
            if n >= 1_000:
                return f"{n/1_000:.2f}K"
            return f"{n:.4f}"

        price_str = f"${price:.6f}" if price < 1 else f"${price:.4f}"
        stats = {
            "price": price,
            "mc": mc,
            "vol24": vol24,
            "price_str": price_str,
            "mc_str": fmt(mc),
            "vol_str": fmt(vol24),
        }
        log.info("LENNY Stats: %s", stats)
        return stats
    except Exception as e:
        log.warning("DEX-Request im Daily-Post fehlgeschlagen: %s", e)
        return None



def build_daily_text(stats):
    """
    Baut den Daily-Post-Text mit Hilfe von Grok.
    Nutzt zusätzlich eine kleine Einschätzung je nach MC / Vol für mehr Würze.
    """
    base_fallback = "LENNY daily dose. $LENNY ( ͡° ͜ʖ ͡°) #Lenny #Solana #Memecoins"

    if stats:
        price_str = stats["price_str"]
        mc_str    = stats["mc_str"]
        vol_str   = stats["vol_str"]
        mc_val    = stats["mc"]
        vol_val   = stats["vol24"]

        # einfache "Stimmungslogik"
        mood_bits = []

        # MC-Stimmung
        if mc_val < 300_000:
            mood_bits.append("This is still ultra early degen territory.")
        elif mc_val < 1_000_000:
            mood_bits.append("Still early but clearly waking up.")
        elif mc_val < 5_000_000:
            mood_bits.append("Mid-cap meme in motion, momentum building.")
        else:
            mood_bits.append("Big boy territory, but still degen potential left.")

        # Volumen-Stimmung
        if vol_val < 5_000:
            mood_bits.append("Volume is low, feels like stealth accumulation.")
        elif vol_val < 50_000:
            mood_bits.append("Volume is healthy, degens are warming up.")
        else:
            mood_bits.append("Volume is raging, full degen mode right now.")

        sentiment = " ".join(mood_bits)

        context = (
            f"Price: {price_str}, MC: {mc_str}, 24h Vol: {vol_str}. "
            f"Sentiment: {sentiment}"
        )
    else:
        context = "No fresh stats available, but still degen bullish."

    prompt = (
        "Create a short daily tweet for the $LENNY token. "
        "Use this status: " + context + " "
        "Keep it under 220 characters. "
        "Use the Lenny face ( ͡° ͜ʖ ͡°) somewhere. "
        "Sound cheeky, fun and degen, but safe for social media. "
        "Add 1-2 fitting crypto/meme hashtags."
    )

    txt = grok_generate(prompt)
    if not txt:
        log.warning("Grok-Text leer, nutze Fallback für Daily-Post.")
        txt = base_fallback

    # Am Ende noch Datum + kleine Random-ID, damit keine Duplicate-Fehler kommen
    tag = datetime.utcnow().strftime("%Y-%m-%d")
    rnd = random.randint(100, 999)
    final = f"{txt} | {tag} #{rnd}"
    return final



def main():
    print("📅 Starte LENNY Daily-Post (mit Grok)...")

    # 1) Stats holen
    stats = fetch_lenny_stats()

    # 2) Text bauen (Grok + Fallback)
    text = build_daily_text(stats)
    print("Tweet-Text:")
    print(text)

    # 3) Meme wählen
    media_ids = None
    try:
        meme_path = choose_meme("memes")
        print(f"🎯 Verwende Meme: {meme_path}")
        mid = upload_media_get_id(meme_path)
        if mid:
            media_ids = [mid]
    except Exception as e:
        print(f"⚠️ Meme-Upload fehlgeschlagen (poste nur Text): {e}")

    # 4) Tweet senden (mit Duplicate-Fallback)
    try:
        if media_ids:
            client.create_tweet(text=text, media_ids=media_ids)
        else:
            client.create_tweet(text=text)
        print("✅ Daily-Post gesendet.")
    except tweepy.errors.Forbidden as e:
        # Falls X trotzdem Duplicate meckert → Text leicht ändern und einmal neu versuchen
        if "duplicate" in str(e).lower():
            print("⚠️ Duplicate Tweet geblockt, versuche mit anderem Text...")
            alt = text + f" #{random.randint(1000,9999)}"
            if media_ids:
                client.create_tweet(text=alt, media_ids=media_ids)
            else:
                client.create_tweet(text=alt)
            print("✅ Daily-Post (Fallback) gesendet.")
        else:
            print("❌ Fehler beim Tweet:", e)
            raise
    except Exception as e:
        print("❌ Unerwarteter Fehler beim Daily-Post:", e)
        raise


if __name__ == "__main__":
    main()
