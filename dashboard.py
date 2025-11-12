import os
import json
import logging
from typing import List, Tuple, Dict

import requests
from flask import Flask, request, redirect, url_for, render_template_string, abort, flash, Response

import tweepy

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("dashboard")

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "not-secret")  # Flash-Messages

# ===== ENV =====
DASHBOARD_KEY   = os.environ.get("DASHBOARD_KEY", "LennySuper420")
HEROKU_API_KEY  = os.environ.get("HEROKU_API_KEY", "")
HEROKU_APP_NAME = os.environ.get("HEROKU_APP_NAME", "")

X_BEARER_TOKEN   = os.environ.get("X_BEARER_TOKEN", "")
X_API_KEY        = os.environ.get("X_API_KEY", "")
X_API_SECRET     = os.environ.get("X_API_SECRET", "")
X_ACCESS_TOKEN   = os.environ.get("X_ACCESS_TOKEN", "")
X_ACCESS_SECRET  = os.environ.get("X_ACCESS_SECRET", "")

# Tweepy v2 Client – mit Bearer (für lookups) und User-Tokens (für Mentions), falls vorhanden
client = None
try:
    client = tweepy.Client(
        bearer_token=X_BEARER_TOKEN or None,
        consumer_key=X_API_KEY or None,
        consumer_secret=X_API_SECRET or None,
        access_token=X_ACCESS_TOKEN or None,
        access_token_secret=X_ACCESS_SECRET or None,
        wait_on_rate_limit=True,
    )
except Exception as e:
    log.warning("Tweepy Client init failed: %s", e)
    client = None

# ===== Kleine Utils =====
def require_key():
    key = request.args.get("key") or request.form.get("key")
    if not key or key != DASHBOARD_KEY:
        abort(404)

def get_target_ids_from_env() -> List[str]:
    raw = os.environ.get("TARGET_IDS", "").strip()
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip().isdigit()]

def get_state_ids_from_env() -> List[str]:
    raw = os.environ.get("STATE_SEEN_IDS", "").strip()
    if not raw:
        return []
    # robust split: Komma / Leerzeichen / Neue Zeile
    parts = []
    for token in raw.replace("\n", ",").replace(" ", ",").split(","):
        t = token.strip()
        if t.isdigit():
            parts.append(t)
    return parts

def heroku_set_config_vars(patch: Dict[str, str]) -> bool:
    if not HEROKU_API_KEY or not HEROKU_APP_NAME:
        flash("HEROKU_API_KEY oder HEROKU_APP_NAME fehlt.", "error")
        return False
    url = f"https://api.heroku.com/apps/{HEROKU_APP_NAME}/config-vars"
    headers = {
        "Authorization": f"Bearer {HEROKU_API_KEY}",
        "Accept": "application/vnd.heroku+json; version=3",
        "Content-Type": "application/json",
    }
    try:
        r = requests.patch(url, headers=headers, data=json.dumps(patch), timeout=15)
        r.raise_for_status()
        for k, v in patch.items():
            os.environ[k] = v  # damit die Seite sofort neue Werte anzeigt
        return True
    except Exception as e:
        log.warning("Heroku config update failed: %s", e)
        flash(f"Heroku config update failed: {e}", "error")
        return False

def normalize_handles(text: str) -> List[str]:
    if not text:
        return []
    raw = []
    for token in text.replace(",", " ").split():
        token = token.strip()
        if not token:
            continue
        if token.startswith("@"):
            token = token[1:]
        raw.append(token)
    seen = set()
    out = []
    for h in raw:
        key = h.lower()
        if key not in seen:
            seen.add(key)
            out.append(h)
    return out

def lookup_ids_for_handles(handles: List[str]) -> Tuple[Dict[str, str], List[str]]:
    found, not_found = {}, []
    if not handles:
        return found, not_found
    if not client:
        return found, handles[:]  # kein Client -> nichts gefunden
    CHUNK = 100
    for i in range(0, len(handles), CHUNK):
        chunk = handles[i:i+CHUNK]
        try:
            resp = client.get_users(usernames=chunk, user_fields=["username","name"])
            got = {u.username.lower(): str(u.id) for u in (resp.data or [])}
            for h in chunk:
                if h.lower() in got:
                    found[h] = got[h.lower()]
                else:
                    not_found.append(h)
        except Exception as e:
            log.warning("Lookup error for %s: %s", chunk, e)
            not_found.extend(chunk)
    return found, not_found

def lookup_handles_for_ids(ids: List[str]) -> Dict[str, str]:
    out = {}
    if not ids or not client:
        return out
    CHUNK = 100
    for i in range(0, len(ids), CHUNK):
        chunk = ids[i:i+CHUNK]
        try:
            resp = client.get_users(ids=chunk, user_fields=["username","name"])
            for u in (resp.data or []):
                out[str(u.id)] = u.username
        except Exception as e:
            log.warning("Reverse lookup error: %s", e)
    return out

def uniqued(seq: List[str], limit: int | None = None) -> List[str]:
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
            if limit and len(out) >= limit:
                break
    return out

# ===== Templates =====
BASE_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Lenny Dashboard</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {font-family: system-ui, Arial, sans-serif; margin: 20px; line-height:1.35;}
    .wrap {max-width: 1100px; margin: 0 auto;}
    h1 {margin-top: 0;}
    form {margin: 16px 0; padding: 12px; border: 1px solid #ddd; border-radius: 8px;}
    textarea, input[type=text] {width:100%; padding:8px; font-family: monospace;}
    button {padding:8px 14px; cursor:pointer;}
    table {width:100%; border-collapse: collapse; margin-top: 8px;}
    th, td {border:1px solid #eee; padding:8px; text-align:left; font-size:14px;}
    .ok {color:#0a0;}
    .err{color:#b00;}
    .pill {display:inline-block; padding:2px 8px; border-radius:999px; background:#f2f2f2; font-size:12px;}
    .row {display:flex; gap:16px; flex-wrap:wrap;}
    .col {flex:1 1 420px;}
    .foot {margin-top:24px; font-size:12px; color:#666;}
    .toolbar a {margin-right:10px;}
  </style>
</head>
<body>
<div class="wrap">
  <h1>LENNY – Dashboard</h1>
  <div class="toolbar">
    <a href="{{ url_for('home') }}?key={{ key }}">Home</a>
    <a href="{{ url_for('state_page') }}?key={{ key }}">State</a>
    <a href="{{ url_for('heartbeat') }}">Heartbeat</a>
  </div>

  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      <ul>
      {% for cat, msg in messages %}
        <li class="{{ 'ok' if cat=='message' else 'err' }}">{{ msg }}</li>
      {% endfor %}
      </ul>
    {% endif %}
  {% endwith %}

  <div class="row">
    <div class="col">
      <h2>➕ Targets per Handle hinzufügen</h2>
      <form method="post" action="{{ url_for('add_targets_by_handle') }}">
        <input type="hidden" name="key" value="{{ key }}">
        <label>Handles (Komma / Leerzeichen / Zeilen – @ optional):</label>
        <textarea name="handles" rows="5" placeholder="@cobie @binance solana ..."></textarea>
        <p><button type="submit">Handles → IDs umwandeln &amp; speichern</button></p>
        <p class="pill">X v2 users lookup</p>
      </form>

      <h2>🧮 Converter nur anzeigen</h2>
      <form method="post" action="{{ url_for('convert_preview') }}">
        <input type="hidden" name="key" value="{{ key }}">
        <label>Handles:</label>
        <textarea name="handles" rows="4" placeholder="@name1, @name2, name3"></textarea>
        <p><button type="submit">Nur umwandeln (keine Speicherung)</button></p>
      </form>
    </div>

    <div class="col">
      <h2>🎯 Aktuelle Targets</h2>
      {% if targets %}
        <table>
          <thead><tr><th>ID</th><th>Handle</th><th>Aktion</th></tr></thead>
          <tbody>
          {% for row in targets %}
            <tr>
              <td>{{ row.id }}</td>
              <td>@{{ row.handle or '—' }}</td>
              <td>
                <form method="post" action="{{ url_for('remove_target') }}" style="display:inline">
                  <input type="hidden" name="key" value="{{ key }}">
                  <input type="hidden" name="id" value="{{ row.id }}">
                  <button type="submit">Entfernen</button>
                </form>
              </td>
            </tr>
          {% endfor %}
          </tbody>
        </table>
        <p><span class="pill">{{ targets|length }} Targets</span></p>
      {% else %}
        <p>Keine TARGET_IDS gesetzt.</p>
      {% endif %}

      <h2>🧷 Rohwert & Quick-Edit</h2>
      <form method="post" action="{{ url_for('save_raw_targets') }}">
        <input type="hidden" name="key" value="{{ key }}">
        <textarea name="raw" rows="4" placeholder="123,456,789">{{ raw_targets }}</textarea>
        <p><button type="submit">TARGET_IDS als CSV speichern</button></p>
      </form>
    </div>
  </div>

  <div class="foot">
    <p>Heroku App: <b>{{ app_name }}</b></p>
  </div>
</div>
</body>
</html>
"""

PREVIEW_HTML = """
<!doctype html>
<html>
<head><meta charset="utf-8"><title>Converter Preview</title>
<style>
body {font-family: system-ui, Arial, sans-serif; margin: 20px; line-height:1.35;}
.wrap {max-width: 800px; margin: 0 auto;}
table {width:100%; border-collapse: collapse; margin-top: 8px;}
th, td {border:1px solid #eee; padding:8px; text-align:left; font-size:14px;}
.ok {color:#090;} .err{color:#b00;}
a {text-decoration:none;}
</style>
</head>
<body>
<div class="wrap">
  <h1>Converter – Vorschau</h1>
  <p><a href="{{ url_for('home') }}?key={{ key }}">← Zurück</a></p>
  <h2>Ergebnis</h2>
  <table>
    <thead><tr><th>Handle</th><th>Resultat</th></tr></thead>
    <tbody>
      {% for h in ok %}
        <tr><td>@{{ h[0] }}</td><td class="ok">{{ h[1] }}</td></tr>
      {% endfor %}
      {% for h in bad %}
        <tr><td>@{{ h }}</td><td class="err">nicht gefunden</td></tr>
      {% endfor %}
    </tbody>
  </table>
  <p>Gefunden: {{ ok|length }}, Nicht gefunden: {{ bad|length }}</p>
</div>
</body>
</html>
"""

STATE_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>STATE – Lenny</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {font-family: system-ui, Arial, sans-serif; margin: 20px; line-height:1.35;}
    .wrap {max-width: 1000px; margin: 0 auto;}
    textarea {width:100%; height: 220px; font-family: monospace;}
    .pill {display:inline-block; padding:2px 8px; border-radius:999px; background:#f2f2f2; font-size:12px;}
    button {padding:8px 14px; cursor:pointer;}
    .toolbar a {margin-right:10px;}
    .ok {color:#090;} .err{color:#b00;}
  </style>
</head>
<body>
<div class="wrap">
  <div class="toolbar">
    <a href="{{ url_for('home') }}?key={{ key }}">← Home</a>
  </div>
  <h1>STATE_SEEN_IDS</h1>

  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      <ul>
      {% for cat, msg in messages %}
        <li class="{{ 'ok' if cat=='message' else 'err' }}">{{ msg }}</li>
      {% endfor %}
      </ul>
    {% endif %}
  {% endwith %}

  <p><span class="pill">{{ count }} IDs gespeichert</span></p>

  {% if preview %}
    <p>Beispiel (erste {{ preview|length }}): {{ preview|join(", ") }}</p>
  {% endif %}

  <h2>Jetzt seeden (Mentions + Targets)</h2>
  <form method="post" action="{{ url_for('state_seed') }}">
    <input type="hidden" name="key" value="{{ key }}">
    <label>Max Tweets pro Quelle (empfohlen 50–100):</label>
    <input type="text" name="limit" value="60">
    <p>
      <button type="submit">Seed jetzt aus X holen &amp; speichern</button>
      <span class="pill">nutzt Bearer + User-Token</span>
    </p>
  </form>

  <h2>Bearbeiten / Überschreiben</h2>
  <form method="post" action="{{ url_for('state_save') }}">
    <input type="hidden" name="key" value="{{ key }}">
    <textarea name="raw">{{ raw }}</textarea>
    <p><button type="submit">STATE_SEEN_IDS speichern</button></p>
  </form>

  <h2>Download</h2>
  <p><a href="{{ url_for('state_download') }}?key={{ key }}">Als Text herunterladen</a></p>
</div>
</body>
</html>
"""

# ===== Routes: Home & Targets =====
@app.route("/")
def home():
    require_key()
    ids = get_target_ids_from_env()
    id_to_handle = lookup_handles_for_ids(ids) if ids else {}
    targets = [{"id": tid, "handle": id_to_handle.get(tid)} for tid in ids]
    return render_template_string(
        BASE_HTML,
        key=DASHBOARD_KEY,
        targets=targets,
        raw_targets=",".join(ids),
        app_name=HEROKU_APP_NAME or "(unset)",
    )

@app.post("/convert_preview")
def convert_preview():
    require_key()
    handles = normalize_handles(request.form.get("handles",""))
    found_map, not_found = lookup_ids_for_handles(handles)
    ok_pairs = sorted(found_map.items(), key=lambda x: x[0].lower())
    return render_template_string(
        PREVIEW_HTML,
        key=DASHBOARD_KEY,
        ok=ok_pairs,
        bad=not_found
    )

@app.post("/add_targets_by_handle")
def add_targets_by_handle():
    require_key()
    handles = normalize_handles(request.form.get("handles",""))
    if not handles:
        flash("Keine Handles übergeben.", "error")
        return redirect(url_for("home") + f"?key={DASHBOARD_KEY}")

    found_map, not_found = lookup_ids_for_handles(handles)
    add_ids = list(found_map.values())

    cur = get_target_ids_from_env()
    merged = list(dict.fromkeys(cur + add_ids))  # de-dupe & order
    ok = heroku_set_config_vars({"TARGET_IDS": ",".join(merged)})
    if ok:
        msg = f"Hinzugefügt: {len(add_ids)} (nicht gefunden: {len(not_found)})"
        if not_found:
            msg += f" – {', '.join('@'+h for h in not_found[:8])}" + (" …" if len(not_found) > 8 else "")
        flash(msg, "message")
    return redirect(url_for("home") + f"?key={DASHBOARD_KEY}")

@app.post("/remove_target")
def remove_target():
    require_key()
    tid = (request.form.get("id") or "").strip()
    if not tid:
        flash("Keine ID angegeben.", "error")
        return redirect(url_for("home") + f"?key={DASHBOARD_KEY}")
    cur = get_target_ids_from_env()
    new = [x for x in cur if x != tid]
    if new == cur:
        flash("ID war nicht in TARGET_IDS.", "error")
        return redirect(url_for("home") + f"?key={DASHBOARD_KEY}")
    ok = heroku_set_config_vars({"TARGET_IDS": ",".join(new)})
    if ok:
        flash(f"Entfernt: {tid}", "message")
    return redirect(url_for("home") + f"?key={DASHBOARD_KEY}")

@app.post("/save_raw_targets")
def save_raw_targets():
    require_key()
    raw = (request.form.get("raw") or "").strip()
    ids = [x.strip() for x in raw.split(",") if x.strip().isdigit()]
    ok = heroku_set_config_vars({"TARGET_IDS": ",".join(ids)})
    if ok:
        flash(f"TARGET_IDS gespeichert ({len(ids)} IDs).", "message")
    return redirect(url_for("home") + f"?key={DASHBOARD_KEY}")

# ===== STATE: anzeigen / speichern / seeden =====
@app.get("/state")
def state_page():
    require_key()
    ids = get_state_ids_from_env()
    preview = ids[:20]
    raw = ",".join(ids)
    return render_template_string(
        STATE_HTML,
        key=DASHBOARD_KEY,
        count=len(ids),
        preview=preview,
        raw=raw
    )

@app.post("/state/save")
def state_save():
    require_key()
    raw = (request.form.get("raw") or "").strip()
    # sanitize
    cleaned = [t.strip() for t in raw.replace("\n", ",").replace(" ", ",").split(",") if t.strip().isdigit()]
    merged = uniqued(cleaned)  # doppelte entfernen
    if heroku_set_config_vars({"STATE_SEEN_IDS": ",".join(merged)}):
        flash(f"STATE_SEEN_IDS gespeichert ({len(merged)}).", "message")
    return redirect(url_for("state_page") + f"?key={DASHBOARD_KEY}")

@app.get("/state/download")
def state_download():
    require_key()
    ids = get_state_ids_from_env()
    txt = "\n".join(ids)
    return Response(txt, mimetype="text/plain")

@app.post("/state/seed")
def state_seed():
    require_key()
    if not client:
        flash("Kein X-Client verfügbar (prüfe Tokens).", "error")
        return redirect(url_for("state_page") + f"?key={DASHBOARD_KEY}")

    # Limit aus Formular
    try:
        limit = int(request.form.get("limit", "60"))
    except:
        limit = 60
    limit = max(10, min(limit, 200))  # Schutz

    new_ids = []

    # 1) Bot-User ermitteln
    me_id = None
    try:
        me = client.get_me()
        if me and me.data:
            me_id = str(me.data.id)
    except Exception as e:
        log.warning("get_me failed: %s", e)

    # 2) Mentions holen
    if me_id:
        try:
            resp = client.get_users_mentions(
                id=me_id,
                max_results=min(100, limit),
                expansions=None,
                tweet_fields=["id","author_id","created_at"]
            )
            for t in (resp.data or []):
                new_ids.append(str(t.id))
        except Exception as e:
            log.warning("mentions failed: %s", e)

    # 3) Von jedem Target die letzten Tweets holen
    target_ids = get_target_ids_from_env()
    for tid in target_ids:
        try:
            resp = client.get_users_tweets(
                id=tid,
                max_results=min(100, limit),
                tweet_fields=["id","created_at","author_id"]
            )
            for t in (resp.data or []):
                new_ids.append(str(t.id))
        except Exception as e:
            log.warning("user tweets failed for %s: %s", tid, e)

    # 4) Merge mit bestehendem State + Limit hart deckeln (z.B. 5000)
    current = get_state_ids_from_env()
    merged = uniqued(current + new_ids)
    if len(merged) > 5000:
        merged = merged[-5000:]  # die neuesten 5000 behalten

    ok = heroku_set_config_vars({"STATE_SEEN_IDS": ",".join(merged)})
    if ok:
        flash(f"Seed ok — {len(new_ids)} IDs eingesammelt, jetzt {len(merged)} total.", "message")
    return redirect(url_for("state_page") + f"?key={DASHBOARD_KEY}")

# ===== Heartbeat =====
@app.get("/heartbeat")
def heartbeat():
    return {"ok": True, "ts": __import__("time").time()}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT","5000")), debug=False)
