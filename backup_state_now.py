# backup_state_now.py — einmaliges, manuelles Backup des Seen-States in Heroku Config

import os, json, requests

STATE_PATHS = ["/tmp/state.json", "state.json"]

HEROKU_APP_NAME = os.getenv("HEROKU_APP_NAME","").strip()
HEROKU_API_KEY  = os.getenv("HEROKU_API_KEY","").strip()
MAX_SEEN_IDS_FOR_CONFIG = int(os.getenv("MAX_SEEN_IDS_FOR_CONFIG","2000"))

def load_state():
    s=set()
    env = os.getenv("STATE_SEEN_IDS","").strip()
    if env:
        for t in env.split(","):
            if t.strip().isdigit():
                s.add(t.strip())
    for p in STATE_PATHS:
        if os.path.exists(p):
            try:
                with open(p,"r",encoding="utf-8") as f:
                    data = json.load(f)
                    for t in data:
                        if str(t).isdigit():
                            s.add(str(t))
            except Exception:
                pass
    return s

def heroku_set_config(var_key, var_value):
    if not HEROKU_APP_NAME or not HEROKU_API_KEY:
        print("❌ HEROKU_APP_NAME / HEROKU_API_KEY fehlen.")
        return False
    url = f"https://api.heroku.com/apps/{HEROKU_APP_NAME}/config-vars"
    headers = {
        "Authorization": f"Bearer {HEROKU_API_KEY}",
        "Accept": "application/vnd.heroku+json; version=3",
        "Content-Type": "application/json",
    }
    r = requests.patch(url, headers=headers, json={var_key: var_value}, timeout=20)
    if r.status_code in (200,201):
        return True
    print("❌ Heroku error:", r.status_code, r.text[:200])
    return False

if __name__ == "__main__":
    seen = load_state()
    if not seen:
        print("⚠️ Keine IDs gefunden.")
        raise SystemExit(0)
    ids_sorted = sorted(seen, key=lambda x:int(x))[-MAX_SEEN_IDS_FOR_CONFIG:]
    value = ",".join(ids_sorted)
    ok = heroku_set_config("STATE_SEEN_IDS", value)
    if ok:
        print(f"✅ Backup OK — {len(ids_sorted)} IDs in STATE_SEEN_IDS gespeichert.")
    else:
        print("❌ Backup fehlgeschlagen.")
