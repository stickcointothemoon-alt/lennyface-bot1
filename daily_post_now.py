# daily_post_now.py
import os, random, tempfile
from PIL import Image
import tweepy

def load_env(key, required=True, default=None):
    v = os.getenv(key, default)
    if required and not v:
        raise RuntimeError(f"Missing env var: {key}")
    return v

def make_clients():
    # X/Twitter Keys aus Heroku-Config (bereits gesetzt)
    BT = load_env("X_BEARER_TOKEN")
    CK = load_env("X_API_KEY")
    CS = load_env("X_API_SECRET")
    AT = load_env("X_ACCESS_TOKEN")
    AS = load_env("X_ACCESS_SECRET")

    # v2 Client zum Posten von Tweets
    v2 = tweepy.Client(
        bearer_token=BT,
        consumer_key=CK, consumer_secret=CS,
        access_token=AT, access_token_secret=AS,
        wait_on_rate_limit=True
    )
    # v1.1 API NUR für Medien-Upload
    auth = tweepy.OAuth1UserHandler(CK, CS, AT, AS)
    v1 = tweepy.API(auth, wait_on_rate_limit=True)
    return v2, v1

def pick_meme(path="memes"):
    exts = (".jpg", ".jpeg", ".png")
    files = [f for f in os.listdir(path) if f.lower().endswith(exts)]
    if not files:
        raise RuntimeError("Kein Meme gefunden im 'memes' Ordner.")
    return os.path.join(path, random.choice(files))

def to_jpeg_rgb(src_path):
    # Twitter mag JPEG am zuverlässigsten
    with Image.open(src_path) as im:
        im = im.convert("RGB")
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        im.save(tmp.name, format="JPEG", optimize=True, quality=85)
        return tmp.name

def main():
    print("📅 Starte manuellen Daily-Post...")
    v2, v1 = make_clients()
    meme_path = pick_meme("memes")
    jpeg_path = to_jpeg_rgb(meme_path)

    # Upload (v1.1)
    media = v1.media_upload(jpeg_path)
    media_id = media.media_id_string

    # Text – kurz & lenny
    text = "( ͡° ͜ʖ ͡°) Daily LENNY meme drop"

    # Tweet (v2)
    r = v2.create_tweet(text=text, media={"media_ids": [media_id]})
    print("✅ Daily meme erfolgreich gepostet. Tweet-ID:", r.data.get("id"))

if __name__ == "__main__":
    main()
