import os
import time
import random
import logging
from collections import deque
from pathlib import Path

import tweepy
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("lennybot")

# ---- Config (ENV) ----
LINE_MODE = os.getenv("LINE_MODE", "llm").lower()   # default: llm (Grok)
REPLY_PROBABILITY = float(os.getenv("REPLY_PROBABILITY", "1.0"))
DEX_REPLY_PROB = float(os.getenv("DEX_REPLY_PROB", "0.5"))
ONLY_ORIGINAL = os.getenv("ONLY_ORIGINAL", "1") == "1"
MAX_REPLIES_PER_KOL_PER_DAY = int(os.getenv("MAX_REPLIES_PER_KOL_PER_DAY", "3"))
LOOP_SLEEP_SECONDS = int(os.getenv("LOOP_SLEEP_SECONDS", "240"))
READ_COOLDOWN_S = int(os.getenv("READ_COOLDOWN_S", "6"))
COOLDOWN_S = int(os.getenv("COOLDOWN_S", "300"))
PER_KOL_MIN_POLL_S = int(os.getenv("PER_KOL_MIN_POLL_S", "1200"))
MEME_PROBABILITY = float(os.getenv("MEME_PROBABILITY", "0.3"))

TARGET_IDS = [s.strip() for s in os.getenv("TARGET_IDS", "").split(",") if s.strip()]

# Grok (x.ai)
GROK_API_KEY = os.getenv("GROK_API_KEY")
GROK_BASE_URL = os.getenv("GROK_BASE_URL", "https://api.x.ai")
GROK_MODEL = os.getenv("GROK_MODEL", "grok-3")

# ---- Twitter Clients ----
def build_clients():
    ck = os.getenv("X_API_KEY")
    cs = os.getenv("X_API_SECRET")
    at = os.getenv("X_ACCESS_TOKEN")
    ats = os.getenv("X_ACCESS_SECRET")
    bt = os.getenv("X_BEARER_TOKEN")  # new

    if not bt:
        raise RuntimeError("X_BEARER_TOKEN fehlt – wird zum Lesen benötigt (verhindert 401).")
    if not all([ck, cs, at, ats]):
        raise RuntimeError("Twitter Keys fehlen (X_API_KEY/X_API_SECRET/X_ACCESS_TOKEN/X_ACCESS_SECRET).")

    read_client_v2 = tweepy.Client(bearer_token=bt, wait_on_rate_limit=True)
    post_client_v2 = tweepy.Client(
        consumer_key=ck,
        consumer_secret=cs,
        access_token=at,
        access_token_secret=ats,
        wait_on_rate_limit=True,
    )
    auth = tweepy.OAuth1UserHandler(ck, cs, at, ats)
    api_v11 = tweepy.API(auth, wait_on_rate_limit=True)
    return read_client_v2, post_client_v2, api_v11

read_client, client, api_v1 = build_clients()

# ---- Memes ----
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

def pick_meme(memes_dir="memes") -> str | None:
    p = Path(memes_dir)
    if not p.exists():
        return None
    cand = [x for x in p.iterdir() if x.suffix.lower() in ALLOWED_EXT and x.is_file()]
    if not cand:
        return None
    return str(random.choice(cand))

# ---- Grok completions (English) ----
def grok_complete(prompt: str, max_tokens: int = 60) -> str | None:
    if not GROK_API_KEY:
        return None
    try:
        url = f"{GROK_BASE_URL.rstrip('/')}/v1/chat/completions"
        headers = {"Authorization": f"Bearer {GROK_API_KEY}"}
        payload = {
            "model": GROK_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You speak concise, witty, cheeky ENGLISH. "
                        "Always include $LENNY in every reply. "
                        "No @mentions, no links. Keep it under ~18 words."
                    )
                },
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.9,
        }
        r = requests.post(url, json=payload, headers=headers, timeout=20)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.warning(f"Grok request failed: {e}")
        return None

_LAST_TEXTS = deque(maxlen=120)
EMOJIS = ["🚀","🌕","🔥","😎","💎","✨","🧠","🌀"]
TAGLINES = ["Powered by $LENNY","#Lenny #Solana","Join the wave $LENNY","meme magic ( ͡° ͜ʖ ͡°)","LENNY > fiat"]
SHUFFLE_HASHTAGS = ["#Lenny","#Solana","#Memecoins","#Crypto","#WAGMI","#Chads"]

def _mix_hashtags() -> str:
    tags = random.sample(SHUFFLE_HASHTAGS, k=random.randint(2,3))
    return " ".join(tags)

def _variant_tail() -> str:
    parts = []
    if random.random() < 0.7: parts.append(random.choice(EMOJIS))
    if random.random() < 0.7: parts.append(random.choice(TAGLINES))
    if random.random() < 0.7: parts.append(_mix_hashtags())
    parts = [p for p in parts if p]
    return (" " + " ".join(parts)) if parts else ""

def build_reply_text(ctx: str) -> str:
    base = None
    if LINE_MODE == "llm" and GROK_API_KEY:
        prompt = (
            "Write a very short, cheeky ENGLISH reply (≤18 words). "
            "Be witty and a bit bold. ALWAYS include $LENNY. "
            "No @mentions. No links. Context: " + repr(ctx[:220])
        )
        base = grok_complete(prompt)

    if not base:
        fallback = [
            "LENNY moves fast—catch the wave. $LENNY",
            "If it pumps, it’s $LENNY. Simple.",
            "Stronger every dip. $LENNY",
            "Buy memes, stay wise. $LENNY",
            "Talk less, send more. $LENNY",
        ]
        base = random.choice(fallback)

    if "$LENNY" not in base:
        base = f"{base} $LENNY"

    for _ in range(4):
        out = (base + random.choice(["", " •", " —", " |"])) + _variant_tail()
        out = out.strip()
        if out not in _LAST_TEXTS:
            _LAST_TEXTS.append(out)
            return out

    salt = str(random.randint(123, 987))
    out = f"{base} {salt}"
    _LAST_TEXTS.append(out)
    return out

# ---- Robust posting (no 'media='/'reply=' kwargs) ----
def post_reply_robust(client_v2: tweepy.Client,
                      api_v1: tweepy.API,
                      text: str,
                      reply_to_id: str | int | None = None,
                      media_path: str | None = None):
    media_ids = None

    if media_path:
        try:
            up = api_v1.media_upload(filename=media_path)
            media_ids = [up.media_id]
        except Exception as e:
            log.warning(f"Meme upload failed: {e}. Sending without image.")
            media_ids = None

    try:
        if reply_to_id and media_ids:
            return client_v2.create_tweet(
                text=text,
                in_reply_to_tweet_id=str(reply_to_id),
                media_ids=media_ids
            )
        elif reply_to_id:
            return client_v2.create_tweet(
                text=text,
                in_reply_to_tweet_id=str(reply_to_id)
            )
        elif media_ids:
            return client_v2.create_tweet(text=text, media_ids=media_ids)
        else:
            return client_v2.create_tweet(text=text)
    except TypeError as te:
        log.warning(f"create_tweet TypeError: {te}. Falling back to v1.1.")
    except Exception as e:
        log.warning(f"create_tweet v2 failed: {e}. Falling back to v1.1.")

    if reply_to_id and media_ids:
        return api_v1.update_status(
            status=text,
            in_reply_to_status_id=reply_to_id,
            auto_populate_reply_metadata=True,
            media_ids=media_ids
        )
    elif reply_to_id:
        return api_v1.update_status(
            status=text,
            in_reply_to_status_id=reply_to_id,
            auto_populate_reply_metadata=True
        )
    elif media_ids:
        return api_v1.update_status(status=text, media_ids=media_ids)
    else:
        return api_v1.update_status(status=text)

# ---- Simple in-process seen state ----
SEEN_IDS: set[str] = set()

_env_seen = (os.getenv("STATE_SEEN_IDS") or "").strip()
if _env_seen:
    try:
        parts = [p.strip() for p in _env_seen.split(",") if p.strip().isdigit()]
        SEEN_IDS.update(parts)
    except Exception:
        pass

def have_seen(tid: str) -> bool:
    return tid in SEEN_IDS

def mark_seen(tid: str):
    SEEN_IDS.add(tid)

# ---- Polling & reply loop ----
def fetch_recent_tweets(read_client_v2: tweepy.Client, user_id: str, since_id: str | None = None):
    params = {
        "max_results": 10,
        "tweet_fields": "created_at,public_metrics,referenced_tweets,author_id",
    }
    try:
        if since_id:
            resp = read_client_v2.get_users_tweets(id=user_id, since_id=since_id, **params)
        else:
            resp = read_client_v2.get_users_tweets(id=user_id, **params)
        tweets = resp.data or []
        if ONLY_ORIGINAL:
            filtered = []
            for t in tweets:
                refs = getattr(t, "referenced_tweets", None) or []
                is_rt_or_reply = any(r.type in ("replied_to", "retweeted") for r in refs)
                if not is_rt_or_reply:
                    filtered.append(t)
            return filtered
        return tweets
    except Exception as e:
        log.warning(f"Fetch tweets failed for {user_id}: {e}")
        return []

def main_loop():
    if not TARGET_IDS:
        log.error("TARGET_IDS is empty.")
        return

    try:
        me = client.get_me()
        handle = me.data.username if me and me.data else "unknown"
    except Exception:
        handle = "unknown"
    log.info(f"Started as @{handle} — targets: {len(TARGET_IDS)}")
    log.info(f"State loaded: {len(SEEN_IDS)} replied tweet IDs remembered")

    last_poll = {uid: 0.0 for uid in TARGET_IDS}
    since_map = {uid: None for uid in TARGET_IDS}
    per_user_count = {uid: 0 for uid in TARGET_IDS}

    while True:
        now = time.time()
        for uid in TARGET_IDS:
            if now - last_poll[uid] < PER_KOL_MIN_POLL_S:
                continue
            last_poll[uid] = now

            tweets = fetch_recent_tweets(read_client, uid, since_map[uid])
            if tweets:
                since_map[uid] = max(str(t.id) for t in tweets)

            for t in tweets:
                tid = str(t.id)
                if have_seen(tid):
                    continue
                if per_user_count[uid] >= MAX_REPLIES_PER_KOL_PER_DAY:
                    continue
                if random.random() > REPLY_PROBABILITY:
                    continue

                original_text = getattr(t, "text", "") or ""
                body = build_reply_text(original_text)
                media_path = pick_meme("memes") if random.random() < MEME_PROBABILITY else None

                try:
                    post_reply_robust(client_v2=client, api_v1=api_v1,
                                      text=body, reply_to_id=tid, media_path=media_path)
                    mark_seen(tid)
                    per_user_count[uid] += 1
                    suffix = " [+meme]" if media_path else ""
                    log.info(f"Reply → {tid} | {body}{suffix}")
                    time.sleep(READ_COOLDOWN_S)
                except Exception as e:
                    log.warning(f"Reply failed: {e}")

            time.sleep(1)

        time.sleep(LOOP_SLEEP_SECONDS)

if __name__ == "__main__":
    main_loop()
