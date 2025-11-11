import os
from pathlib import Path
import random
import tweepy

from bot_basic import get_client_v2, upload_media_return_id, VALID_EXT, MEME_DIR

def pick_meme() -> Path:
    files = [p for p in MEME_DIR.iterdir() if p.is_file() and p.suffix.lower() in VALID_EXT]
    if not files:
        raise RuntimeError("Kein Meme gefunden im 'memes' Ordner.")
    return random.choice(files)

def main():
    print("📅 Starte manuellen Daily-Post...")
    client = get_client_v2()
    meme = pick_meme()
    print(f"🎯 Verwende Meme: {meme.name}")

    kwargs = {"text": "LENNY daily dose. $LENNY ( ͡° ͜ʖ ͡°)"}
    try:
        media_id = upload_media_return_id(meme)
        kwargs["media_ids"] = [media_id]
    except Exception as e:
        print(f"⚠️ Meme-Upload fehlgeschlagen (poste Text): {e}")

    client.create_tweet(**kwargs)
    print("✅ Daily-Post gesendet.")

if __name__ == "__main__":
    main()
