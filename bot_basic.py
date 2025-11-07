# --- Python 3.13 Fix: imghdr wurde entfernt, Tweepy erwartet es beim Import ---
import sys, types
if "imghdr" not in sys.modules:
    m = types.ModuleType("imghdr")
    m.what = lambda f, h=None: None
    sys.modules["imghdr"] = m
# ------------------------------------------------------------------------------

import os, time, random, json, logging, requests, urllib3, glob
import tweepy
from requests.exceptions import ConnectionError as RequestsConnectionError
from dotenv import load_dotenv
from datetime import datetime, timezone

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

BT = os.getenv("X_BEARER_TOKEN")
CK = os.getenv("X_API_KEY")
CS = os.getenv("X_API_SECRET")
AT = os.getenv("X_ACCESS_TOKEN")
AS = os.getenv("X_ACCESS_SECRET")
if not all([BT, CK, CS, AT, AS]):
    raise SystemExit("Bitte .env mit allen X-Keys füllen.")

TARGET_IDS = [i.strip() for i in os.getenv("TARGET_IDS","").split(",") if i.strip()]
if not TARGET_IDS:
    logging.warning("Keine TARGET_IDS gesetzt.")

ONLY_ORIGINAL = int(os.getenv("ONLY_ORIGINAL","1"))
REPLY_PROBABILITY = float(os.getenv("REPLY_PROBABILITY","1.0"))
DEX_REPLY_PROB = float(os.getenv("DEX_REPLY_PROB","0.5"))
COOLDOWN_S = int(os.getenv("COOLDOWN_S","300"))
MAX_REPLIES_PER_KOL_PER_DAY = int(os.getenv("MAX_REPLIES_PER_KOL_PER_DAY","3"))

LOOP_SLEEP_SECONDS = int(os.getenv("LOOP_SLEEP_SECONDS","240"))
PER_KOL_MIN_POLL_S = int(os.getenv("PER_KOL_MIN_POLL_S","1200"))
READ_COOLDOWN_S = float(os.getenv("READ_COOLDOWN_S","6"))

AUTO_TUNE = int(os.getenv("AUTO_TUNE","1"))
TUNE_BASE_LOOP_S = int(os.getenv("TUNE_BASE_LOOP_S", str(LOOP_SLEEP_SECONDS)))
TUNE_MIN_LOOP_S  = int(os.getenv("TUNE_MIN_LOOP_S","120"))
TUNE_MAX_LOOP_S  = int(os.getenv("TUNE_MAX_LOOP_S","900"))
TUNE_MULTIPLIER  = float(os.getenv("TUNE_MULTIPLIER","1.7"))
TUNE_COOLDOWN_LOOPS = int(os.getenv("TUNE_COOLDOWN_LOOPS","3"))
TUNE_STEP_DOWN   = float(os.getenv("TUNE_STEP_DOWN","0.8"))
TUNE_POLL_BUMP_S = int(os.getenv("TUNE_POLL_BUMP_S","180"))
TUNE_POLL_RELAX_S= int(os.getenv("TUNE_POLL_RELAX_S","90"))

CURRENT_LOOP_SLEEP = TUNE_BASE_LOOP_S
BASE_PER_KOL_MIN_POLL_S = PER_KOL_MIN_POLL_S
tune_cooldown_left = 0

LINE_MODE = os.getenv("LINE_MODE","llm")
GROK_BASE_URL = os.getenv("GROK_BASE_URL","").rstrip("/")
GROK_API_KEY  = os.getenv("GROK_API_KEY","")
GROK_MODEL    = os.getenv("GROK_MODEL","grok-3")

DEX_CHAIN = "solana"
DEX_PAIR  = "9MXxzYYszFBu6CvN57hkRrgKXFHGk5PyTLbqWHzRcCZT"

DAILY_POST_ENABLED   = int(os.getenv("DAILY_POST_ENABLED","1"))
DAILY_POST_UTC_HOUR  = int(os.getenv("DAILY_POST_UTC_HOUR","12"))
DAILY_POST_MINUTE    = int(os.getenv("DAILY_POST_MINUTE","0"))

MEME_PROBABILITY = float(os.getenv("MEME_PROBABILITY","0.3"))
DAILY_MEME_THRESHOLD_PCT = float(os.getenv("DAILY_MEME_THRESHOLD_PCT","1.0"))

STATE_FILE = "bot_state.json"
last_seen_id = {}
replied_ids = set()
last_poll_ts  = {}
last_reply_ts = {}
daily_count   = {}
NEXT_INDEX    = 0
last_daily_post_date = ""
last_meme_path = ""

def load_state():
    global last_seen_id, replied_ids, last_daily_post_date, last_meme_path
    if not os.path.exists(STATE_FILE): return
    try:
        import json
        with open(STATE_FILE,"r",encoding="utf-8") as f:
            d=json.load(f)
        last_seen_id = d.get("last_seen_id",{})
        replied_ids.update(d.get("replied_ids",[]))
        last_daily_post_date = d.get("last_daily_post_date","") or ""
        last_meme_path = d.get("last_meme_path","") or ""
    except Exception as e:
        logging.warning("State laden fehlgeschlagen: %s", e)

def save_state():
    try:
        import json
        with open(STATE_FILE,"w",encoding="utf-8") as f:
            json.dump({
                "last_seen_id": last_seen_id,
                "replied_ids": list(replied_ids)[-800:],
                "last_daily_post_date": last_daily_post_date,
                "last_meme_path": last_meme_path
            }, f)
    except Exception as e:
        logging.warning("State speichern fehlgeschlagen: %s", e)

load_state()

client = tweepy.Client(bearer_token=BT, consumer_key=CK, consumer_secret=CS,
                       access_token=AT, access_token_secret=AS, wait_on_rate_limit=False)
auth_v1 = tweepy.OAuth1UserHandler(CK, CS, AT, AS)
api_v1 = tweepy.API(auth_v1)

def _fmt_money(n):
    try: n=float(n)
    except: return "n/a"
    a=abs(n)
    return f"${n/1_000_000_000:.2f}B" if a>=1e9 else f"${n/1_000_000:.2f}M" if a>=1e6 else f"${n/1_000:.2f}k" if a>=1e3 else f"${n:.2f}"

def dex_stats():
    try:
        r = requests.get(f"https://api.dexscreener.com/latest/dex/pairs/{DEX_CHAIN}/{DEX_PAIR}", timeout=12); r.raise_for_status()
        d = r.json(); p = d.get("pair") or (d.get("pairs") or [None])[0]
        if not p: return {"mc":"n/a","vol":"n/a","price":"n/a","change24":None}
        mc = p.get("marketCap") or p.get("fdv")
        vol = (p.get("volume") or {}).get("h24") or (p.get("volume24h") or {}).get("usd")
        price = p.get("priceUsd")
        ch=None
        try: ch=float((p.get("priceChange") or {}).get("h24"))
        except: ch=None
        return {"mc":_fmt_money(mc), "vol":_fmt_money(vol), "price": f"${float(price):.6f}" if price is not None else "n/a", "change24": ch}
    except Exception:
        return {"mc":"n/a","vol":"n/a","price":"n/a","change24":None}

def grok_line(tweet_text, mc="", vol="", price="", mode="reply"):
    if LINE_MODE.lower()!="llm" or not (GROK_BASE_URL and GROK_API_KEY): return None
    try:
        if mode=="reply":
            sys_prompt=("You are a witty Lennyface meme bot for X. Reply in English, <=140 chars, include ( ͡° ͜ʖ ͡°), playful, slightly provocative. No @, no #, no links.")
            user_prompt=(f'Tweet: "{tweet_text}"\nContext: token=LENNY, mc={mc}, vol={vol}, price={price}\nReply ONLY with the one-liner.')
        else:
            sys_prompt=("You are a witty Lennyface meme bot for X. Create a standalone tweet in English, <=140 chars, include ( ͡° ͜ʖ ͡°). Playful hype about a token with today's stats. No @, no #, no links.")
            user_prompt=(f"Daily stats: token=LENNY, mc={mc}, vol={vol}, price={price}. Write a fun one-liner that teases momentum.")
        r=requests.post(f"{GROK_BASE_URL}/v1/chat/completions",
                        headers={"Authorization":f"Bearer {GROK_API_KEY}","Content-Type":"application/json"},
                        json={"model":GROK_MODEL,"messages":[{"role":"system","content":sys_prompt},{"role":"user","content":user_prompt}],
                              "temperature":0.9,"max_tokens":70}, timeout=20)
        r.raise_for_status()
        t=r.json()["choices"][0]["message"]["content"].strip()
        return t[:140].replace("@","").replace("#","")
    except Exception as e:
        logging.warning("Grok fallback: %s", e); return None

def fallback_line(mode="reply"):
    return f"( ͡° ͜ʖ ͡°) $LENNY daily check — tiny cap, big grin." if mode=="daily" else f"( ͡° ͜ʖ ͡°) $LENNY vibes strong {random.randint(100,999)}"

def can_reply(uid):
    now=time.time()
    if now - last_reply_ts.get(uid,0) < COOLDOWN_S: return False
    today=datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d=daily_count.get(uid,{"date":today,"count":0})
    if d.get("date")!=today: d={"date":today,"count":0}
    if d["count"]>=MAX_REPLIES_PER_KOL_PER_DAY: daily_count[uid]=d; return False
    daily_count[uid]=d; return True

def mark_replied(uid):
    last_reply_ts[uid]=time.time()
    today=datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d=daily_count.get(uid,{"date":today,"count":0})
    if d.get("date")!=today: d={"date":today,"count":0}
    d["count"]+=1; daily_count[uid]=d

def upload_meme_get_id():
    global last_meme_path
    files=[f for f in glob.glob("memes/*.*") if os.path.getsize(f)<=5*1024*1024]
    if not files: return None
    if len(files)>1 and last_meme_path:
        files=[f for f in files if os.path.abspath(f)!=os.path.abspath(last_meme_path)] or files
    path=random.choice(files)
    try:
        media=api_v1.media_upload(path); last_meme_path=path; save_state(); return media.media_id
    except Exception as e:
        logging.warning("Meme upload failed: %s", e); return None

def call_with_retry(fn,*args,_retries=3,_what="call",_min_wait=1.0,_max_wait=3.0,**kwargs):
    global CURRENT_LOOP_SLEEP, tune_cooldown_left, PER_KOL_MIN_POLL_S
    tries=0
    while True:
        try:
            return fn(*args,**kwargs)
        except (RequestsConnectionError, urllib3.exceptions.ProtocolError) as e:
            tries+=1
            if tries>_retries: logging.error("%s failed after %d retries: %s",_what,tries-1,e); raise
            sleep_s=min(_max_wait,_min_wait*tries)+random.uniform(0,0.3)
            logging.warning("%s transient error → retry %d/%d in %.1fs",_what,tries,_retries,sleep_s); time.sleep(sleep_s)
        except tweepy.TooManyRequests as e:
            reset_hdr=e.response.headers.get("x-rate-limit-reset","0"); remaining=e.response.headers.get("x-rate-limit-remaining","?")
            try: reset=int(reset_hdr)
            except: reset=0
            now=int(time.time()); sleep_s=900 if reset<=now else max(5,reset-now+2)
            logging.warning("rate limit (remaining=%s) → sleep %ss (reset=%s)",remaining,sleep_s,reset_hdr)
            if int(os.getenv("AUTO_TUNE","1")):
                global CURRENT_LOOP_SLEEP, PER_KOL_MIN_POLL_S, tune_cooldown_left
                CURRENT_LOOP_SLEEP=min(int(max(TUNE_MIN_LOOP_S,CURRENT_LOOP_SLEEP)*TUNE_MULTIPLIER),TUNE_MAX_LOOP_S)
                PER_KOL_MIN_POLL_S=min(BASE_PER_KOL_MIN_POLL_S+TUNE_POLL_BUMP_S, BASE_PER_KOL_MIN_POLL_S+3*TUNE_POLL_BUMP_S)
                tune_cooldown_left=max(tune_cooldown_left,TUNE_COOLDOWN_LOOPS)
                logging.warning("auto-tune → CURRENT_LOOP_SLEEP=%ss, PER_KOL_MIN_POLL_S=%ss, cooldown_loops=%s",CURRENT_LOOP_SLEEP,PER_KOL_MIN_POLL_S,tune_cooldown_left)
            time.sleep(sleep_s)

def get_recent_tweets(user_id):
    params={"id":user_id,"max_results":5,"tweet_fields":["referenced_tweets","created_at"]}
    if ONLY_ORIGINAL: params["exclude"]=["retweets","replies"]
    sid=last_seen_id.get(str(user_id)); 
    if sid: params["since_id"]=sid
    return client.get_users_tweets(**params)

def maybe_daily_post():
    global last_daily_post_date
    if not DAILY_POST_ENABLED: return
    now=datetime.now(timezone.utc); today=now.strftime("%Y-%m-%d")
    target=now.replace(hour=DAILY_POST_UTC_HOUR,minute=DAILY_POST_MINUTE,second=0,microsecond=0)
    if last_daily_post_date==today or now<target: return
    s=dex_stats(); mc,vol,price,ch=s["mc"],s["vol"],s["price"],s["change24"]
    line=grok_line("",mc,vol,price,mode="daily") or f"( ͡° ͜ʖ ͡°) $LENNY daily check — MC: {mc}, Vol: {vol}, Price: {price}"
    media_ids=None
    if ch is not None and ch>DAILY_MEME_THRESHOLD_PCT:
        mid=upload_meme_get_id(); 
        if mid: media_ids=[mid]
    try:
        if media_ids: client.create_tweet(text=line, media_ids=media_ids)
        else: client.create_tweet(text=line)
        last_daily_post_date=today; save_state()
        logging.info("Daily post → %s%s", line, " [with meme]" if media_ids else "")
    except Exception as e:
        logging.warning("Daily post failed: %s", e)

def main_loop():
    global NEXT_INDEX, CURRENT_LOOP_SLEEP, tune_cooldown_left, PER_KOL_MIN_POLL_S
    me=client.get_me(user_auth=True); logging.info("Started as @%s — targets: %s", me.data.username, len(TARGET_IDS)); time.sleep(15)
    while True:
        if not TARGET_IDS:
            logging.warning("No TARGET_IDS configured."); maybe_daily_post(); save_state(); time.sleep(CURRENT_LOOP_SLEEP); continue
        uid=TARGET_IDS[NEXT_INDEX % len(TARGET_IDS)]; NEXT_INDEX=(NEXT_INDEX+1) % max(1,len(TARGET_IDS))
        now=time.time()
        if now - last_poll_ts.get(uid,0) >= PER_KOL_MIN_POLL_S:
            last_poll_ts[uid]=now
            resp=call_with_retry(get_recent_tweets, uid, _what="get_users_tweets"); time.sleep(READ_COOLDOWN_S)
            tweets=resp.data or []
            if ONLY_ORIGINAL:
                def _is_quote(tw):
                    for ref in getattr(tw,"referenced_tweets",[]) or []:
                        if getattr(ref,"type",None)=="quoted": return True
                    return False
                tweets=[tw for tw in tweets if not _is_quote(tw)]
            if tweets:
                try: last_seen_id[str(uid)]=str(max(int(t.id) for t in tweets))
                except: pass
                tw=tweets[0]
                if str(tw.id) not in replied_ids and can_reply(uid) and random.random()<REPLY_PROBABILITY:
                    mc=vol=price=""
                    if random.random()<DEX_REPLY_PROB:
                        s=dex_stats(); mc,vol,price=s["mc"],s["vol"],s["price"]
                    line=grok_line(getattr(tw,"text","") or "", mc,vol,price, mode="reply") or f"( ͡° ͜ʖ ͡°) $LENNY vibes strong {random.randint(100,999)}"
                    media_ids=None
                    if random.random()<MEME_PROBABILITY:
                        mid=upload_meme_get_id()
                        if mid: media_ids=[mid]
                    def _reply_fn(tid, txt, mids):
                        if mids: client.create_tweet(text=txt, in_reply_to_tweet_id=tid, media_ids=mids)
                        else:    client.create_tweet(text=txt, in_reply_to_tweet_id=tid)
                        return True
                    call_with_retry(_reply_fn, tw.id, line, media_ids, _what="create_tweet")
                    logging.info("Reply → %s | %s%s", tw.id, line, " [with meme]" if media_ids else "")
                    last_reply_ts[uid]=time.time(); replied_ids.add(str(tw.id)); save_state()
        maybe_daily_post()
        if int(os.getenv("AUTO_TUNE","1")) and tune_cooldown_left>0:
            tune_cooldown_left-=1
            if tune_cooldown_left==0:
                CURRENT_LOOP_SLEEP=max(TUNE_BASE_LOOP_S, int(max(TUNE_MIN_LOOP_S,CURRENT_LOOP_SLEEP)*TUNE_STEP_DOWN))
                PER_KOL_MIN_POLL_S=max(PER_KOL_MIN_POLL_S, PER_KOL_MIN_POLL_S - TUNE_POLL_RELAX_S)
                logging.info("auto-tune relax → CURRENT_LOOP_SLEEP=%ss, PER_KOL_MIN_POLL_S=%ss", CURRENT_LOOP_SLEEP, PER_KOL_MIN_POLL_S)
        save_state(); time.sleep(CURRENT_LOOP_SLEEP)

if __name__ == "__main__":
    main_loop()
