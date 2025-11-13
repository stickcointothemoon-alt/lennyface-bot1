import os
import json
import textwrap
import requests
from flask import Flask, request, redirect, url_for, render_template_string, abort, jsonify

app = Flask(__name__)

# -----------------------------
# CONFIG
# -----------------------------
DASHBOARD_KEY = os.environ.get("DASHBOARD_KEY", "LennySuper420")
HEROKU_APP_NAME = os.environ.get("HEROKU_APP_NAME", "lennyface-bot")
HEROKU_API_KEY = os.environ.get("HEROKU_API_KEY")  # muss in Heroku Config Vars gesetzt sein


# -----------------------------
# HILFSFUNKTIONEN
# -----------------------------
def require_key():
    """Einfacher Schutz: ?key=... muss stimmen."""
    key = request.args.get("key") or request.form.get("key")
    if key != DASHBOARD_KEY:
        abort(401)


def heroku_headers():
    if not HEROKU_API_KEY:
        raise RuntimeError("HEROKU_API_KEY ist nicht gesetzt!")
    return {
        "Authorization": f"Bearer {HEROKU_API_KEY}",
        "Accept": "application/vnd.heroku+json; version=3",
        "Content-Type": "application/json",
    }


def heroku_get_config():
    """Liest alle Config Vars von Heroku."""
    url = f"https://api.heroku.com/apps/{HEROKU_APP_NAME}/config-vars"
    resp = requests.get(url, headers=heroku_headers(), timeout=10)
    resp.raise_for_status()
    return resp.json()


def heroku_set_config(changes: dict):
    """Setzt Config Vars auf Heroku (nur teilweise, andere bleiben)."""
    url = f"https://api.heroku.com/apps/{HEROKU_APP_NAME}/config-vars"
    resp = requests.patch(url, headers=heroku_headers(), data=json.dumps(changes), timeout=10)
    resp.raise_for_status()
    return resp.json()


def parse_ids(csv_value: str):
    """Hilfsfunktion: aus '1,2,3' wird ['1','2','3'] ohne Leerzeichen."""
    if not csv_value:
        return []
    return [x.strip() for x in csv_value.split(",") if x.strip()]


# -----------------------------
# STARTSEITE / DASHBOARD
# -----------------------------
@app.route("/")
def index():
    require_key()
    cfg = heroku_get_config()

    key = request.args.get("key", "")

    # Status / State
    state_seen_csv = cfg.get("STATE_SEEN_IDS", "")
    seen_ids = parse_ids(state_seen_csv)
    seen_count = len(seen_ids)

    target_csv = cfg.get("TARGET_IDS", "")
    targets = parse_ids(target_csv)
    target_count = len(targets)

    bot_paused = cfg.get("BOT_PAUSED", "0")  # "0" oder "1"
    grok_tone = cfg.get("GROK_TONE", "normal")
    grok_force_en = cfg.get("GROK_FORCE_ENGLISH", "1")
    grok_always_lenny = cfg.get("GROK_ALWAYS_SHILL_LENNY", "1")
    grok_extra = cfg.get("GROK_EXTRA_PROMPT", "")

    fetch_url = cfg.get("FETCH_MEMES_URL", "")

    template = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Lennyface Bot Dashboard v2</title>
  <style>
    body {
      background: #0b0f19;
      color: #f0f0f0;
      font-family: Arial, sans-serif;
      margin: 0;
      padding: 0;
    }
    .wrap {
      max-width: 1100px;
      margin: 20px auto;
      padding: 0 10px;
    }
    h1, h2, h3 {
      color: #ffe66d;
    }
    .card {
      border: 1px solid #222a3a;
      border-radius: 8px;
      padding: 15px 20px;
      margin-bottom: 16px;
      background: #121829;
    }
    .row {
      display: flex;
      gap: 16px;
      flex-wrap: wrap;
    }
    .col {
      flex: 1;
      min-width: 260px;
    }
    label {
      display: block;
      margin-top: 8px;
      font-size: 0.9rem;
    }
    input[type="text"], textarea, select {
      width: 100%;
      padding: 6px 8px;
      border-radius: 4px;
      border: 1px solid #36415b;
      background: #0b1020;
      color: #f0f0f0;
      box-sizing: border-box;
    }
    textarea {
      min-height: 70px;
      font-family: monospace;
      font-size: 0.85rem;
    }
    .btn {
      display: inline-block;
      margin-top: 10px;
      padding: 6px 12px;
      border-radius: 4px;
      border: none;
      cursor: pointer;
      font-weight: bold;
      font-size: 0.9rem;
    }
    .btn-green { background: #2ecc71; color: #000; }
    .btn-orange { background: #f39c12; color: #000; }
    .btn-red { background: #e74c3c; color: #fff; }
    .btn-blue { background: #3498db; color: #fff; }
    small { color: #9da6c4; }
    pre {
      background: #060912;
      padding: 10px;
      border-radius: 4px;
      overflow-x: auto;
      font-size: 0.8rem;
    }
    .stat-line {
      margin: 3px 0;
      font-size: 0.9rem;
    }
    .pill {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 0.75rem;
      background: #1f2937;
      margin-right: 4px;
    }
  </style>
</head>
<body>
<div class="wrap">
  <h1>( ͡° ͜ʖ ͡°) Lenny Dashboard v2</h1>

  <!-- BOT STATUS -->
  <div class="card">
    <h2>Bot Status</h2>
    <div class="stat-line">
      <span class="pill">Seen IDs: {{ seen_count }}</span>
      <span class="pill">Targets: {{ target_count }}</span>
      <span class="pill">BOT_PAUSED: {{ 'YES' if bot_paused=='1' else 'NO' }}</span>
    </div>
    <form method="post" action="{{ url_for('update_bot_control') }}?key={{ key }}">
      <input type="hidden" name="key" value="{{ key }}">
      <label>Bot Control:</label>
      <select name="bot_paused">
        <option value="0" {% if bot_paused=='0' %}selected{% endif %}>Running</option>
        <option value="1" {% if bot_paused=='1' %}selected{% endif %}>Paused</option>
      </select>
      <button class="btn btn-green" type="submit">Save Bot State</button>
      <small>Bot checkt in der Loop BOT_PAUSED: 1 = schläft nur, 0 = aktiv.</small>
    </form>
  </div>

  <!-- ROW: TARGETS + GROK -->
  <div class="row">
    <!-- TARGETS -->
    <div class="card col">
      <h2>Targets (KOLs)</h2>
      <form method="post" action="{{ url_for('update_targets') }}?key={{ key }}">
        <input type="hidden" name="key" value="{{ key }}">
        <label>Aktuelle TARGET_IDS (eine pro Zeile):</label>
        <textarea name="targets_text">{% for t in targets %}{{ t }}
{% endfor %}</textarea>
        <button class="btn btn-blue" type="submit">Save TARGET_IDS</button>
        <small>Wird als Komma-Liste in TARGET_IDS gespeichert.</small>
      </form>

      <hr>
      <h3>Handle → ID Converter</h3>
      <form method="post" action="{{ url_for('convert_handle') }}?key={{ key }}">
        <input type="hidden" name="key" value="{{ key }}">
        <label>X Handle (z.B. @Loomdart):</label>
        <input type="text" name="handle" placeholder="@username">
        <button class="btn btn-orange" type="submit">Convert</button>
      </form>
      {% if request.args.get('conv_handle') %}
        <p>
          <strong>Handle:</strong> {{ request.args.get('conv_handle') }}<br>
          <strong>User-ID:</strong> {{ request.args.get('conv_id') }}
        </p>
      {% endif %}
    </div>

    <!-- GROK -->
    <div class="card col">
      <h2>Grok / Tone Settings</h2>
      <form method="post" action="{{ url_for('update_grok') }}?key={{ key }}">
        <input type="hidden" name="key" value="{{ key }}">

        <label>GROK Tone:</label>
        <select name="grok_tone">
          <option value="soft" {% if grok_tone=='soft' %}selected{% endif %}>😇 Soft</option>
          <option value="normal" {% if grok_tone=='normal' %}selected{% endif %}>😎 Normal</option>
          <option value="spicy" {% if grok_tone=='spicy' %}selected{% endif %}>😏 Spicy</option>
          <option value="savage" {% if grok_tone=='savage' %}selected{% endif %}>🤬 Very Savage</option>
        </select>

        <label>
          <input type="checkbox" name="grok_force_en" value="1" {% if grok_force_en=='1' %}checked{% endif %}>
          Immer auf Englisch antworten
        </label>

        <label>
          <input type="checkbox" name="grok_always_lenny" value="1" {% if grok_always_lenny=='1' %}checked{% endif %}>
          Immer $LENNY shillen
        </label>

        <label>Extra Prompt (wird an Grok angehängt):</label>
        <textarea name="grok_extra" placeholder="Extra Anweisungen für Grok…">{{ grok_extra }}</textarea>

        <button class="btn btn-green" type="submit">Save Grok Settings</button>
      </form>
      <small>Der Bot liest diese Variablen beim Start ein und passt seine Antworten an.</small>
    </div>
  </div>

  <!-- MEMES & STATE -->
  <div class="row">
    <div class="card col">
      <h2>Memes</h2>
      <p class="stat-line">
        <strong>FETCH_MEMES_URL:</strong><br>
        <code>{{ fetch_url or 'nicht gesetzt' }}</code>
      </p>
      <form method="post" action="{{ url_for('trigger_fetch_memes') }}?key={{ key }}">
        <input type="hidden" name="key" value="{{ key }}">
        <button class="btn btn-orange" type="submit">Fetch Memes Now</button>
      </form>
      <small>Ruft intern <code>python fetch_memes.py</code> auf (als One-off Dyno).</small>
    </div>

    <div class="card col">
      <h2>State / Seen IDs</h2>
      <p class="stat-line">
        <strong>STATE_SEEN_IDS:</strong> {{ seen_count }} IDs
      </p>
      <form method="post" action="{{ url_for('trigger_seed_backup') }}?key={{ key }}">
        <input type="hidden" name="key" value="{{ key }}">
        <button class="btn btn-blue" type="submit">Seed + Backup ENV (safe)</button>
      </form>
      <small>
        Führt <code>seed_and_backup_env.py</code> aus:<br>
        • holt neue Seen-IDs per API<br>
        • schreibt sie sicher in <code>STATE_SEEN_IDS</code>.
      </small>
    </div>
  </div>

  <div class="card">
    <h3>Hinweis</h3>
    <small>
      Vollständige Heroku-Logs weiterhin über:
      <code>heroku logs -t -a {{ app_name }}</code><br>
      Dieses Dashboard zeigt dir State + Config und steuert den Bot über Config Vars.
    </small>
  </div>
</div>
</body>
</html>
    """

    return render_template_string(
        template,
        key=key,
        seen_count=seen_count,
        target_count=target_count,
        targets=targets,
        bot_paused=bot_paused,
        grok_tone=grok_tone,
        grok_force_en=grok_force_en,
        grok_always_lenny=grok_always_lenny,
        grok_extra=grok_extra,
        fetch_url=fetch_url,
        app_name=HEROKU_APP_NAME,
    )


# -----------------------------
# BOT CONTROL
# -----------------------------
@app.route("/update_bot", methods=["POST"])
def update_bot_control():
    require_key()
    paused = request.form.get("bot_paused", "0")
    paused = "1" if paused == "1" else "0"
    heroku_set_config({"BOT_PAUSED": paused})
    key = request.args.get("key", "")
    return redirect(url_for("index", key=key))


# -----------------------------
# TARGETS
# -----------------------------
@app.route("/update_targets", methods=["POST"])
def update_targets():
    require_key()
    text = request.form.get("targets_text", "")
    ids = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        ids.append(line)
    csv_value = ",".join(ids)
    heroku_set_config({"TARGET_IDS": csv_value})
    key = request.args.get("key", "")
    return redirect(url_for("index", key=key))

# -----------------------------
# GROK SETTINGS
# -----------------------------
@app.route("/update_grok", methods=["POST"])
def update_grok():
    require_key()

    tone = request.form.get("grok_tone", "normal")

    force_en = "1" if request.form.get("grok_force_en") == "1" else "0"
    always_lenny = "1" if request.form.get("grok_always_lenny") == "1" else "0"

    extra = request.form.get("grok_extra", "")

    heroku_set_config({
        "GROK_TONE": tone,
        "GROK_FORCE_ENGLISH": force_en,
        "GROK_ALWAYS_SHILL_LENNY": always_lenny,
        "GROK_EXTRA_PROMPT": extra,
    })

    key = request.args.get("key", "")
    return redirect(url_for("index", key=key))



# -----------------------------
# HANDLE → ID CONVERTER
# (WICHTIG: nutzt deine bestehende X_BEARER_TOKEN)
# -----------------------------

@app.route("/convert_handle", methods=["POST"])
def convert_handle():
    require_key()
    handle = request.form.get("handle", "").strip()
    key = request.args.get("key", "")

    if not handle:
        return redirect(url_for("index", key=key))

    if handle.startswith("@"):
        handle = handle[1:]

    bearer = os.environ.get("X_BEARER_TOKEN")
    if not bearer:
        return redirect(url_for("index", key=key))

    # Offizielle stabile Twitter/X Developer API
    url = f"https://api.twitter.com/2/users/by/username/{handle}"
    headers = {"Authorization": f"Bearer {bearer}"}

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        user_id = data.get("data", {}).get("id", "UNKNOWN")
    except Exception:
        user_id = "ERROR"

    return redirect(url_for("index", key=key, conv_handle=handle, conv_id=user_id))

# -----------------------------
# MEMES TRIGGER
# -----------------------------
@app.route("/fetch_memes_now", methods=["POST"])
def trigger_fetch_memes():
    """
    Startet einen One-off Dyno: `heroku run python fetch_memes.py`.
    Dafür nutzen wir die Heroku API 'dynos'.
    """
    require_key()
    url = f"https://api.heroku.com/apps/{HEROKU_APP_NAME}/dynos"
    payload = {
        "command": "python fetch_memes.py",
        "type": "run",
        "time_to_live": 300,
    }
    try:
        resp = requests.post(url, headers=heroku_headers(), data=json.dumps(payload), timeout=10)
        # wenn ok, egal was zurückkommt
    except Exception:
        pass

    key = request.args.get("key", "")
    return redirect(url_for("index", key=key))


# -----------------------------
# SEED + BACKUP ENV TRIGGER
# -----------------------------
@app.route("/seed_backup_now", methods=["POST"])
def trigger_seed_backup():
    """
    Startet einen One-off Dyno: `python seed_and_backup_env.py`.
    """
    require_key()
    url = f"https://api.heroku.com/apps/{HEROKU_APP_NAME}/dynos"
    payload = {
        "command": "python seed_and_backup_env.py",
        "type": "run",
        "time_to_live": 600,
    }
    try:
        resp = requests.post(url, headers=heroku_headers(), data=json.dumps(payload), timeout=10)
    except Exception:
        pass

    key = request.args.get("key", "")
    return redirect(url_for("index", key=key))


# -----------------------------
# ALIASHILFEN FÜR Routen-Namen
# (damit die Namen im Template stimmen)
# -----------------------------
# update_bot_control      → /update_bot
# update_targets          → /update_targets
# convert_handle          → /convert_handle
# trigger_fetch_memes     → /fetch_memes_now
# trigger_seed_backup     → /seed_backup_now

if __name__ == "__main__":
    # lokal zum Testen
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)

