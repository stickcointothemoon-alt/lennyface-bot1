# seed_and_backup_env.py
import os, json, requests
import imghdr  # noqa  (bleibt wegen deiner Umgebung)
from datetime import datetime

# 👉 Diese zwei ENV Variablen müssen im Heroku-Dashboard gesetzt sein:
# HEROKU_APP_NAME = lennyface-bot
# HEROKU_API_KEY  = <dein Heroku API Key>

APP = os.getenv("HEROKU_APP_NAME")
API_KEY = os.getenv("HEROKU_API_KEY")
if not APP or not API_KEY:
    raise SystemExit("HEROKU_APP_NAME oder HEROKU_API_KEY fehlt in den Config Vars.")

# ---- Schritt 1: vorhandenes seed_seen importieren und ausführen ----
# Wir erwarten, dass seed_seen.py eine Funktion get_seen_ids() bereitstellt.
# Falls nicht, fallback: wir führen sie als Modul aus und lesen /tmp/state.json.
SEED_FILE = "/tmp/state.json"

def run_seed_and_collect_ids():
    # Versuche, die Funktion direkt zu nutzen
    try:
        import seed_seen  # type: ignore
        if hasattr(seed_seen, "get_seen_ids"):
            ids = seed_seen.get_seen_ids()
            with open(SEED_FILE, "w") as f:
                json.dump(ids, f)
            return ids
    except Exception:
        pass

    # Fallback: starte seed logic per subprocess (import innerhalb des Dynos)
    import subprocess, sys, shlex, pathlib
    cmd = f"{sys.executable} seed_seen.py"
    rc = subprocess.call(shlex.split(cmd))
    if rc != 0 or not pathlib.Path(SEED_FILE).exists():
        raise SystemExit("Seeding fehlgeschlagen: /tmp/state.json nicht erzeugt.")
    return json.loads(pathlib.Path(SEED_FILE).read_text())

ids = run_seed_and_collect_ids()
print(f"✅ Seed ok — {len(ids)} IDs gesammelt. Beispiel: {ids[:3]}")

# ---- Schritt 2: in ENV (STATE_SEEN_IDS) schreiben via Heroku Platform API ----
ids_csv = ",".join(ids)
url = f"https://api.heroku.com/apps/{APP}/config-vars"
headers = {
    "Accept": "application/vnd.heroku+json; version=3",
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}
resp = requests.patch(url, headers=headers, json={"STATE_SEEN_IDS": ids_csv})
resp.raise_for_status()
print(f"💾 ENV aktualisiert: STATE_SEEN_IDS = {len(ids)} IDs")

# ---- Schritt 3: kleine Quittung ----
print(f"📦 Done {datetime.utcnow().isoformat()}Z")
