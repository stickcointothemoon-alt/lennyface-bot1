# backup_state_now.py
import os, sys, json, subprocess, shlex

STATE_FILE = "/tmp/state.json"

def load_ids_from_file():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                ids = [str(x).strip() for x in data if str(x).strip()]
                return ids
        except Exception as e:
            print(f"WARN: Konnte {STATE_FILE} nicht lesen: {e}")
    return None

def load_ids_from_env():
    env = os.getenv("STATE_SEEN_IDS", "")
    ids = [x.strip() for x in env.split(",") if x.strip()]
    return ids

def main():
    # 1) Bevorzugt aus /tmp/state.json (Output von seed_seen.py)
    ids = load_ids_from_file()
    source = "file"
    if not ids:
        # 2) Fallback: aus ENV
        ids = load_ids_from_env()
        source = "env"

    # Deduplizieren + sortieren (optional)
    ids = sorted(set(ids))
    print(f"INFO: Lade {len(ids)} IDs aus {source}.")

    app = os.environ.get("HEROKU_APP_NAME")
    api_key = os.environ.get("HEROKU_API_KEY")
    if not app:
        print("ERROR: HEROKU_APP_NAME fehlt in den Config Vars.")
        sys.exit(1)
    if not api_key:
        print("ERROR: HEROKU_API_KEY fehlt in den Config Vars.")
        sys.exit(1)

    value = ",".join(ids)
    # Achtung: große Env-Variablen gehen, aber halten wir’s schlank (du hast ~300 IDs -> ok)
    cmd = f'heroku config:set STATE_SEEN_IDS="{value}" -a {app}'
    print(f"INFO: Schreibe {len(ids)} IDs in STATE_SEEN_IDS …")
    rc = subprocess.call(shlex.split(cmd))
    if rc == 0:
        print(f"OK: {len(ids)} IDs in STATE_SEEN_IDS gespeichert.")
        sys.exit(0)
    else:
        print("ERROR: Konnte STATE_SEEN_IDS nicht setzen.")
        sys.exit(rc)

if __name__ == "__main__":
    main()
