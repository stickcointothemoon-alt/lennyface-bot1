# dashboard.py
import os
import csv
import io
import json
from datetime import datetime
from functools import wraps

import requests
from flask import Flask, request, Response, redirect, url_for, render_template_string, flash

# ----- Grund-Setup -----
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "lenny_secret_dev")  # nur für Flash-Messages

DASHBOARD_KEY = os.environ.get("DASHBOARD_KEY", "")
PORT = int(os.environ.get("PORT", os.environ.get("DASHBOARD_PORT", 5000)))

HEROKU_API_KEY  = os.environ.get("HEROKU_API_KEY", "")
HEROKU_APP_NAME = os.environ.get("HEROKU_APP_NAME", "")

# ----- kleine Helpers -----
def require_key(fn):
    """Einfacher Guard: ?key=DEIN_PASSWORT oder POST-Form-Feld key=..."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        supplied = request.args.get("key") or request.form.get("key")
        if not DASHBOARD_KEY:
            return "DASHBOARD_KEY not set in Config Vars.", 401
        if supplied != DASHBOARD_KEY:
            return Response("Unauthorized (add ?key=YOUR_KEY)", 401)
        return fn(*args, **kwargs)
    return wrapper

def get_env_list(name: str):
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return []
    # erlaubt Komma / Zeilenumbruch / Whitespace
    items = []
    for part in raw.replace("\r", "\n").split("\n"):
        for p2 in part.split(","):
            p2 = p2.strip()
            if p2:
                items.append(p2)
    return items

def set_config_vars(payload: dict) -> bool:
    """
    Schreibt Config Vars zurück in Heroku, wenn HEROKU_API_KEY & HEROKU_APP_NAME vorhanden sind.
    Fällt sonst stillschweigend auf False zurück (nur in-memory sichtbar).
    """
    if not HEROKU_API_KEY or not HEROKU_APP_NAME:
        return False
    url = f"https://api.heroku.com/apps/{HEROKU_APP_NAME}/config-vars"
    headers = {
        "Accept": "application/vnd.heroku+json; version=3",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {HEROKU_API_KEY}",
    }
    try:
        r = requests.patch(url, headers=headers, data=json.dumps(payload), timeout=20)
        r.raise_for_status()
        # Lokales os.environ aktualisieren, damit Seite direkt neuen Stand zeigt
        for k, v in payload.items():
            os.environ[k] = v
        return True
    except Exception as e:
        print("set_config_vars error:", e)
        return False

def now_str():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")

# ----- HTML (einfach & ohne externe Dateien) -----
PAGE = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Lenny Dashboard</title>
<style>
 body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;margin:24px;line-height:1.45}
 h1{margin:0 0 4px}
 .sub{color:#666;margin-bottom:18px}
 .card{border:1px solid #ddd;border-radius:10px;padding:16px;margin:12px 0;background:#fff}
 .row{display:flex;gap:12px;flex-wrap:wrap}
 .col{flex:1 1 320px}
 button, .btn{background:#111;color:#fff;border:none;border-radius:8px;padding:10px 14px;cursor:pointer}
 .btn.secondary{background:#444}
 input[type=file], input[type=text], textarea{width:100%;padding:10px;border:1px solid #ccc;border-radius:8px}
 code,kbd{background:#f5f5f5;padding:2px 6px;border-radius:6px}
 footer{margin-top:24px;color:#888}
 table{border-collapse:collapse;width:100%}
 th,td{border:1px solid #eee;padding:8px;text-align:left}
 .note{font-size:12px;color:#777}
 .ok{color:#0a8}
 .warn{color:#c70}
</style>
</head>
<body>
  <h1>🧠 Lenny Control</h1>
  <div class="sub">UTC: {{now}} • App: <b>{{app_name}}</b> • Worker alive? <span class="{{'ok' if worker_hint else 'warn'}}">{{ 'likely' if worker_hint else 'unknown' }}</span></div>

  <div class="row">
    <div class="card col">
      <h3>State & Targets</h3>
      <p>Seen IDs: <b>{{seen_count}}</b></p>
      <p>Targets: <b>{{targets_count}}</b></p>
      <details>
        <summary>Show first items</summary>
        <p><b>First Targets:</b> {{first_targets}}</p>
        <p><b>First Seen IDs:</b> {{first_seen}}</p>
      </details>
    </div>

    <div class="card col">
      <h3>Quick Actions</h3>
      <form method="post" action="{{url_for('reload_env')}}?key={{key}}">
        <input type="hidden" name="key" value="{{key}}"/>
        <button>Reload ENV (refresh page)</button>
      </form>
      <p class="note">Lädt nur die aktuelle Ansicht neu (ENV wird vom Dyno ohnehin bei Start gelesen).</p>
    </div>
  </div>

  <div class="card">
    <h3>Export</h3>
    <div class="row">
      <div class="col">
        <form method="get" action="{{url_for('export_targets')}}?key={{key}}">
          <button class="btn">⬇️ Download targets.csv</button>
        </form>
      </div>
      <div class="col">
        <form method="get" action="{{url_for('export_seen')}}?key={{key}}">
          <button class="btn">⬇️ Download seen.csv</button>
        </form>
      </div>
    </div>
    <p class="note">CSV Format: eine ID pro Zeile. Überschrift optional (user_id / tweet_id).</p>
  </div>

  <div class="card">
    <h3>Import</h3>
    <div class="row">
      <div class="col">
        <form method="post" action="{{url_for('import_targets')}}?key={{key}}" enctype="multipart/form-data">
          <input type="hidden" name="key" value="{{key}}"/>
          <p><b>Import Targets CSV</b></p>
          <input type="file" name="file" required/>
          <button class="btn">⬆️ Upload targets.csv</button>
        </form>
      </div>
      <div class="col">
        <form method="post" action="{{url_for('import_seen')}}?key={{key}}" enctype="multipart/form-data">
          <input type="hidden" name="key" value="{{key}}"/>
          <p><b>Import Seen CSV</b></p>
          <input type="file" name="file" required/>
          <button class="btn">⬆️ Upload seen.csv</button>
        </form>
      </div>
    </div>
    <p class="note">Schreibt die ENV Variablen <code>TARGET_IDS</code> bzw. <code>STATE_SEEN_IDS</code> (Komma-getrennt). Wenn <code>HEROKU_API_KEY</code> &amp; <code>HEROKU_APP_NAME</code> gesetzt sind, wird direkt in Heroku gespeichert.</p>
  </div>

  <footer>
    Secure key in URL: <code>?key=&lt;DEIN_KEY&gt;</code>. • Keep this private.
  </footer>
</body>
</html>
"""

# ----- Views -----
@app.route("/")
@require_key
def index():
    targets = get_env_list("TARGET_IDS")
    seen = get_env_list("STATE_SEEN_IDS")

    ctx = {
        "now": now_str(),
        "app_name": HEROKU_APP_NAME or "(unset)",
        "seen_count": len(seen),
        "targets_count": len(targets),
        "first_targets": targets[:5],
        "first_seen": seen[:5],
        "key": request.args.get("key"),
        # Faustregel: wenn wir hier sind, läuft der Web dyno — Worker-status kennen wir nicht genau
        "worker_hint": True,
    }
    return render_template_string(PAGE, **ctx)

@app.route("/reload", methods=["POST"])
@require_key
def reload_env():
    flash("Reloaded view.")
    return redirect(url_for("index", key=request.form.get("key")))

# ----- Export -----
@app.route("/export/targets.csv")
@require_key
def export_targets():
    rows = get_env_list("TARGET_IDS")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["user_id"])
    for r in rows:
        w.writerow([r])
    data = buf.getvalue()
    return Response(
        data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=targets.csv"},
    )

@app.route("/export/seen.csv")
@require_key
def export_seen():
    rows = get_env_list("STATE_SEEN_IDS")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["tweet_id"])
    for r in rows:
        w.writerow([r])
    data = buf.getvalue()
    return Response(
        data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=seen.csv"},
    )

# ----- Import -----
def _read_csv_ids(file_storage) -> list:
    content = file_storage.read().decode("utf-8", errors="ignore")
    # CSV tolerant lesen: Header + eine ID pro Zeile
    reader = csv.reader(io.StringIO(content))
    out = []
    for row in reader:
        if not row:
            continue
        cell = row[0].strip()
        if not cell:
            continue
        # Header „user_id“ / „tweet_id“ überspringen
        if cell.lower() in ("user_id", "tweet_id", "id"):
            continue
        out.append(cell)
    return out

@app.route("/import/targets", methods=["POST"])
@require_key
def import_targets():
    f = request.files.get("file")
    if not f:
        return "No file", 400
    ids = _read_csv_ids(f)
    value = ",".join(ids)
    ok = set_config_vars({"TARGET_IDS": value})
    note = " (Heroku saved)" if ok else " (in-memory only; set HEROKU_API_KEY / HEROKU_APP_NAME)"
    flash(f"Imported {len(ids)} targets{note}.")
    return redirect(url_for("index", key=request.form.get("key")))

@app.route("/import/seen", methods=["POST"])
@require_key
def import_seen():
    f = request.files.get("file")
    if not f:
        return "No file", 400
    ids = _read_csv_ids(f)
    value = ",".join(ids)
    ok = set_config_vars({"STATE_SEEN_IDS": value})
    note = " (Heroku saved)" if ok else " (in-memory only; set HEROKU_API_KEY / HEROKU_APP_NAME)"
    flash(f"Imported {len(ids)} seen IDs{note}.")
    return redirect(url_for("index", key=request.form.get("key")))

# ----- Run -----
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
