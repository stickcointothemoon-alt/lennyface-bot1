# daily_post_now.py
import os, random, glob, sys
import tweepy

# Erwartet, dass diese ENV Variablen in Heroku gesetzt sind:
# X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET

def pick_meme(folder="memes"):
    exts = (".jpg", ".jpeg", ".png", ".gif", ".webp")
    files = [p for p in glob.glob(os.path.join(folder, "*")) if p.lower().endswith(exts)]
    if not files:
        raise RuntimeError("Kein Meme gefunden im 'memes' Ordner.")
    return random.choice(files)

def make_api():
    ck = os.environ["X_API_KEY"]
    cs = os.environ["X_API_SECRET"]
    at = os.environ["X_ACCESS_TOKEN"]
    ats = os.environ["X_ACCESS_SECRET"]

    auth = tweepy.OAuth1UserHandler(ck, cs, at, ats)
    api = tweepy.API(auth)
    return api

def main():
    print("📅 Starte manuellen Daily-Post...")
    meme = pick_meme("memes")
    print(f"🎯 Verwende Meme: {os.path.basename(meme)}")
    api = make_api()

    text = "gm ( ͡° ͜ʖ ͡°) #LENNY"
    media = api.media_upload(filename=meme)
    api.update_status(status=text, media_ids=[media.media_id_string])
    print("✅ Meme gepostet!")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ Fehler beim Daily-Post: {e}")
        sys.exit(1)
