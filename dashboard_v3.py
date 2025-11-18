import os
import json
import requests
from flask import Flask, request, redirect, url_for, render_template_string, abort

app = Flask(__name__)

# -----------------------------------------------------
# CONFIG
# -----------------------------------------------------
DASHBOARD_KEY   = os.environ.get("DASHBOARD_KEY", "LennySuper420")
HEROKU_APP_NAME = os.environ.get("HEROKU_APP_NAME", "")
HEROKU_API_KEY  = os.environ.get("HEROKU_API_KEY", "")

# Lenny Token / DEX
LENNY_TOKEN_CA = os.environ.get("LENNY_TOKEN_CA", "").strip()
DEX_TOKEN_URL  = os.environ.get("DEX_TOKEN_URL", "").strip()

# Bot Handle
BOT_HANDLE = os.environ.get("BOT_HANDLE", "lennyface_bot").lstrip("@")

# Grok Defaults
GROK_API_KEY          = os.environ.get("GROK_API_KEY", "")
GROK_BASE_URL         = os.environ.get("GROK_BASE_URL", "https://api.x.ai")
GROK_MODEL            = os.environ.get("GROK_MODEL", "grok-3")
GROK_TONE             = os.environ.get("GROK_TONE", "normal")
GROK_FORCE_ENGLISH    = os.environ.get("GROK_FORCE_ENGLISH", "1")
GROK_ALWAYS_SHILL_LENNY = os.environ.get("GROK_ALWAYS_SHILL_LENNY", "1")
GROK_EXTRA_PROMPT     = os.environ.get("GROK_EXTRA_PROMPT", "")

# -----------------------------------------------------
# SECURITY
# -----------------------------------------------------
def require_key():
    key = request.args.get("key") or request.form.get("key")
    if key != DASHBOARD_KEY:
        abort(401)

# -----------------------------------------------------
# HEROKU HELPERS
# -----------------------------------------------------
def heroku_headers():
    return {
        "Authorization": f"Bearer {HEROKU_API_KEY}",
        "Accept": "application/vnd.heroku+json; version=3",
        "Content-Type": "application/json"
    }

def heroku_get_config():
    url = f"https://api.heroku.com/apps/{HEROKU_APP_NAME}/config-vars"
    r = requests.get(url, headers=heroku_headers(), timeout=10)
    r.raise_for_status()
    return r.json()

def heroku_set_config(changes: dict):
    url = f"https://api.heroku.com/apps/{HEROKU_APP_NAME}/config-vars"
    r = requests.patch(url, headers=heroku_headers(), data=json.dumps(changes), timeout=10)
    r.raise_for_status()
    return r.json()

def parse_ids(text):
    if not text:
        return []
    return [x.strip() for x in text.split(",") if x.strip()]

# -----------------------------------------------------
# MARKET DATA (DEX + COINGECKO)
# -----------------------------------------------------
def fetch_lenny_stats():
    if DEX_TOKEN_URL:
        url = DEX_TOKEN_URL
    else:
        if not LENNY_TOKEN_CA:
            return None
        url = f"https://api.dexscreener.com/latest/dex/tokens/{LENNY_TOKEN_CA}"

    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        pairs = data.get("pairs") or []
        if not pairs:
            return None

        p = pairs[0]
        price = float(p.get("priceUsd") or 0)
        mc = float(p.get("fdv") or p.get("marketCap") or 0)
        vol = float(
            (p.get("volume") or {}).get("h24")
            or p.get("volume24h") or 0
        )

        def fmt(n):
            if n >= 1_000_000_000:
                return f"{n/1_000_000_000:.2f}B"
            if n >= 1_000_000:
                return f"{n/1_000_000:.2f}M"
            if n >= 1_000:
                return f"{n/1_000:.2f}K"
            return f"{n:.4f}"

        price_str = f"${price:.6f}" if price < 1 else f"${price:.4f}"

        return {
            "price_str": price_str,
            "mc_str": fmt(mc),
            "vol_str": fmt(vol),
            "dex_name": p.get("dexId", ""),
            "pair_url": p.get("url", "")
        }
    except:
        return None

def fetch_global_stats():
    url = (
        "https://api.coingecko.com/api/v3/simple/price"
        "?ids=bitcoin,solana&vs_currencies=usd&include_24hr_change=true"
    )
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()

        def fmt(p):
            if p >= 1_000_000:
                return f"${p/1_000_000:.2f}M"
            if p >= 1_000:
                return f"${p/1_000:.2f}K"
            return f"${p:.2f}"

        out = {}

        btc = data.get("bitcoin")
        if btc:
            out["btc_price"] = fmt(float(btc.get("usd") or 0))
            out["btc_change"] = f"{float(btc.get('usd_24h_change') or 0):+.2f}%"

        sol = data.get("solana")
        if sol:
            out["sol_price"] = fmt(float(sol.get("usd") or 0))
            out["sol_change"] = f"{float(sol.get('usd_24h_change') or 0):+.2f}%"

        return out
    except:
        return None

# -----------------------------------------------------
# GROK PREVIEW
# -----------------------------------------------------
def build_grok_prompt():
    base = (
        "You are LENNY, a cheeky, degen-style shill bot for $LENNY. "
        "Be short, punchy, funny. No slurs or toxicity. "
    )

    tone = GROK_TONE.lower()
    if tone == "soft":
        base += "Be friendly."
    elif tone == "spicy":
        base += "Be edgy and teasing."
    elif tone == "savage":
        base += "Be savage but safe."
    else:
        base += "Balanced degen tone."

    if GROK_FORCE_ENGLISH == "1":
        base += " Always reply in English."

    if GROK_ALWAYS_SHILL_LENNY == "1":
        base += " Mention $LENNY when relevant."

    if GROK_EXTRA_PROMPT.strip():
        base += " Extra: " + GROK_EXTRA_PROMPT.strip()

    return base

def grok_preview(text):
    if not GROK_API_KEY:
        return "GROK_API_KEY fehlt."

    try:
        url = f"{GROK_BASE_URL}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {GROK_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": GROK_MODEL,
            "messages": [
                {"role": "system", "content": build_grok_prompt()},
                {
                    "role": "user",
                    "content": "Simulate an X reply (<220 chars) to: " + text
                },
            ],
            "max_tokens": 96,
            "temperature": 0.9
        }

        r = requests.post(url, headers=headers, json=payload, timeout=20)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"Grok Preview failed: {e}"

# -----------------------------------------------------
# RENDER DASHBOARD
# -----------------------------------------------------
def render_dashboard(preview_text=None):
    cfg = heroku_get_config()
    key = request.args.get("key")

    # Raw config
    seen_ids = parse_ids(cfg.get("STATE_SEEN_IDS", ""))
    target_ids = parse_ids(cfg.get("TARGET_IDS", ""))

    # Bot flags
    bot_paused = cfg.get("BOT_PAUSED", "0")
    auto_meme_mode = cfg.get("AUTO_MEME_MODE", "1")

    # Cooldowns
    read_cooldown = cfg.get("READ_COOLDOWN_S", "6")
    loop_sleep = cfg.get("LOOP_SLEEP_SECONDS", "240")

    # Boost
    boost_enabled = cfg.get("BOOST_ENABLED", "1")
    boost_cooldown = cfg.get("BOOST_COOLDOWN_S", "3")
    boost_duration = cfg.get("BOOST_DURATION_S", "600")

    # Command Toggles
    enable_help  = cfg.get("ENABLE_HELP",  "1")
    enable_lore  = cfg.get("ENABLE_LORE",  "1")
    enable_stats = cfg.get("ENABLE_STATS", "1")
    enable_gm    = cfg.get("ENABLE_GM",    "1")
    enable_roast = cfg.get("ENABLE_ROAST", "1")
    enable_alpha = cfg.get("ENABLE_ALPHA", "1")

    # Stats
    stats_date  = cfg.get("STATS_DATE", "")
    stats_total = cfg.get("STATS_REPLIES_TOTAL", "0")
    stats_mens  = cfg.get("STATS_REPLIES_MENTIONS", "0")
    stats_kol   = cfg.get("STATS_REPLIES_KOL", "0")
    stats_memes = cfg.get("STATS_MEMES_USED", "0")

    # Market
    lenny_stats = fetch_lenny_stats()
    global_stats = fetch_global_stats()

    # ------------------------------------
    # Dashboard HTML Template
    # ------------------------------------
    template = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>LennyBot Dashboard v3.5</title>
<style>
body {
  background: radial-gradient(circle at top, #1e293b 0, #020617 55%);
  color: #f9fafb;
  font-family: Arial;
  margin: 0;
}
.wrap {
  max-width: 1200px;
  margin: 20px auto;
  padding-bottom: 40px;
}
.card {
  background: rgba(15,23,42,0.95);
  border-radius: 12px;
  margin-bottom: 18px;
  padding: 20px;
  box-shadow: 0 10px 30px rgba(0,0,0,0.4);
}
.row {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
}
.col {
  flex: 1;
  min-width: 320px;
}
label { display: block; margin-top: 6px; }
input, textarea, select {
  width: 100%; padding: 6px 8px;
  border-radius: 8px; border: 1px solid #374151;
  background: #0f172a; color: #f9fafb;
}
textarea { min-height: 70px; font-family: monospace; }
.btn {
  margin-top: 10px; padding: 8px 14px;
  border-radius: 6px; border: none;
  font-weight: bold; cursor: pointer;
}
.btn-green { background: #22c55e; color: #000; }
.btn-red   { background: #ef4444; color: #fff; }
.btn-blue  { background: #3b82f6; color: #fff; }
.btn-orange{ background: #f97316; color: #000; }
.pill {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 999px;
  background: #111827;
  margin-right: 5px;
  font-size: 0.8rem;
}
small { color: #9ca3af; }
pre {
  background: #0f172a;
  padding: 10px;
  border-radius: 6px;
  overflow-x: auto;
}
h1,h2,h3 { color: #ffe66d; }
.headline-face { font-size: 1.6rem; margin-right: 10px; }
</style>
</head>
<body>
<div class="wrap">

<h1><span class="headline-face">( ͡° ͜ʖ ͡°)</span> LennyBot Dashboard v3.5</h1>

<!-- BOT STATUS ROW -->
<div class="row">
  <!-- BOT STATUS CARD -->
  <div class="card col">
    <h2>Bot Status</h2>
    <div class="pill">Seen IDs: {{ seen_count }}</div>
    <div class="pill">Targets: {{ target_count }}</div>
    <div class="pill">Paused: {{ 'YES' if bot_paused=='1' else 'NO' }}</div>

    <form method="post" action="{{ url_for('update_bot_state') }}?key={{ key }}">
      <input type="hidden" name="key" value="{{ key }}">
      <label>Bot Running / Paused</label>
      <select name="bot_paused">
        <option value="0" {% if bot_paused=='0' %}selected{% endif %}>Running</option>
        <option value="1" {% if bot_paused=='1' %}selected{% endif %}>Paused</option>
      </select>
      <button class="btn btn-green">Save</button>
    </form>
  </div>

  <!-- GLOBAL MARKET -->
  <div class="card col">
    <h2>BTC / SOL</h2>
    {% if global_stats %}
      <p>
      <strong>BTC:</strong> {{ global_stats.btc_price }}
      ({{ global_stats.btc_change }})<br>
      <strong>SOL:</strong> {{ global_stats.sol_price }}
      ({{ global_stats.sol_change }})
      </p>
    {% else %}
      <p>Keine Daten.</p>
    {% endif %}
  </div>
</div>

<!-- LENNY MARKET -->
<div class="card">
  <h2>$LENNY Market</h2>
  {% if lenny_stats %}
    <p>
      <strong>Price:</strong> {{ lenny_stats.price_str }}<br>
      <strong>Market Cap:</strong> {{ lenny_stats.mc_str }}<br>
      <strong>24h Vol:</strong> {{ lenny_stats.vol_str }}<br>
      <strong>Dex:</strong>
      <a target="_blank" href="{{ lenny_stats.pair_url }}">{{ lenny_stats.dex_name }}</a>
    </p>
  {% else %}
    <p>Keine Daten.</p>
  {% endif %}
</div>

<!-- COMMAND TOGGLES -->
<div class="card">
  <h2>Command Toggles</h2>

  <form method="post" action="{{ url_for('update_command_toggles') }}?key={{ key }}">
    <input type="hidden" name="key" value="{{ key }}">

    <label><input type="checkbox" name="enable_help"  value="1" {% if enable_help=='1' %}checked{% endif %}> help</label>
    <label><input type="checkbox" name="enable_lore"  value="1" {% if enable_lore=='1' %}checked{% endif %}> lore</label>
    <label><input type="checkbox" name="enable_stats" value="1" {% if enable_stats=='1' %}checked{% endif %}> stats</label>
    <label><input type="checkbox" name="enable_gm"    value="1" {% if enable_gm=='1' %}checked{% endif %}> gm</label>
    <label><input type="checkbox" name="enable_roast" value="1" {% if enable_roast=='1' %}checked{% endif %}> roast</label>
    <label><input type="checkbox" name="enable_alpha" value="1" {% if enable_alpha=='1' %}checked{% endif %}> alpha</label>

    <button class="btn btn-green">Save Command Toggles</button>
  </form>
</div>

<!-- MEMES -->
<div class="card">
  <h2>Memes</h2>

  <form method="post" action="{{ url_for('fetch_memes_now') }}?key={{ key }}">
    <input type="hidden" name="key" value="{{ key }}">
    <button class="btn btn-orange">Fetch Memes Now</button>
  </form>

  <hr>

  <form method="post" action="{{ url_for('update_meme_settings') }}?key={{ key }}">
    <input type="hidden" name="key" value="{{ key }}">
    <label><input type="checkbox" name="auto_meme_mode" value="1" {% if auto_meme_mode=='1' %}checked{% endif %}> Auto Meme Mode aktiv</label>
    <button class="btn btn-green">Save Meme Settings</button>
  </form>
</div>

<!-- TARGETS / KOLs -->
<div class="card">
  <h2>Targets / KOL</h2>

  <form method="post" action="{{ url_for('update_targets') }}?key={{ key }}">
    <input type="hidden" name="key" value="{{ key }}">
    <textarea name="targets_text">{% for t in targets %}{{ t }}
{% endfor %}</textarea>
    <button class="btn btn-blue">Save Target IDs</button>
  </form>

  <hr>
  <h3>Handle → ID Tool</h3>
  <form method="post" action="{{ url_for('convert_handle') }}?key={{ key }}">
    <input type="hidden" name="key" value="{{ key }}">
    <label>X Handle</label>
    <input type="text" name="handle" placeholder="@user">
    <button class="btn btn-orange">Convert</button>
  </form>

  {% if request.args.get('conv_handle') %}
    <p>
      <strong>{{ request.args.get('conv_handle') }}</strong> → ID:
      <strong>{{ request.args.get('conv_id') }}</strong>
    </p>
  {% endif %}
</div>

<!-- BOOST -->
<div class="card">
  <h2>Boost Mode</h2>

  <form method="post" action="{{ url_for('update_boost') }}?key={{ key }}">
    <input type="hidden" name="key" value="{{ key }}">

    <label>Boost Enabled</label>
    <select name="boost_enabled">
      <option value="1" {% if boost_enabled=='1' %}selected{% endif %}>ON</option>
      <option value="0" {% if boost_enabled=='0' %}selected{% endif %}>OFF</option>
    </select>

    <label>Boost Cooldown (s)</label>
    <input type="text" name="boost_cooldown" value="{{ boost_cooldown }}">

    <label>Boost Duration (s)</label>
    <input type="text" name="boost_duration" value="{{ boost_duration }}">

    <button class="btn btn-green">Save Boost Settings</button>
  </form>
</div>

<!-- DAILY STATS -->
<div class="card">
  <h2>Daily Stats</h2>
  <p>Date: {{ stats_date }}</p>
  <p>Total Replies: {{ stats_total }}</p>
  <p>Mentions: {{ stats_mens }}</p>
  <p>KOL Replies: {{ stats_kol }}</p>
  <p>Memes Used: {{ stats_memes }}</p>
</div>

<!-- GROK PREVIEW -->
<div class="card">
  <h2>Reply Simulator</h2>

  <form method="post" action="{{ url_for('simulate_reply') }}?key={{ key }}">
    <input type="hidden" name="key" value="{{ key }}">
    <textarea name="sample_text" placeholder="@lennyface_bot what do you think?"></textarea>
    <button class="btn btn-green">Simulate</button>
  </form>

  {% if preview_text %}
    <h3>Preview</h3>
    <pre>{{ preview_text }}</pre>
  {% endif %}
</div>

</div>
</body>
</html>
    """

    return render_template_string(
        template,
        key=key,
        seen_count=len(seen_ids),
        target_count=len(target_ids),
        targets=target_ids,
        bot_paused=bot_paused,
        auto_meme_mode=auto_meme_mode,
        enable_help=enable_help,
        enable_lore=enable_lore,
        enable_stats=enable_stats,
        enable_gm=enable_gm,
        enable_roast=enable_roast,
        enable_alpha=enable_alpha,
        read_cooldown=read_cooldown,
        loop_sleep=loop_sleep,
        boost_enabled=boost_enabled,
        boost_cooldown=boost_cooldown,
        boost_duration=boost_duration,
        stats_date=stats_date,
        stats_total=stats_total,
        stats_mens=stats_mens,
        stats_kol=stats_kol,
        stats_memes=stats_memes,
        lenny_stats=lenny_stats,
        global_stats=global_stats,
        preview_text=preview_text
    )

# -----------------------------------------------------
# ROUTES — BOT STATE
# -----------------------------------------------------
@app.route("/update_bot_state", methods=["POST"])
def update_bot_state():
    require_key()
    paused = request.form.get("bot_paused", "0")
    paused = "1" if paused == "1" else "0"
    heroku_set_config({"BOT_PAUSED": paused})
    key = request.args.get("key")
    return redirect(url_for("index", key=key))


# -----------------------------------------------------
# ROUTES — TARGETS
# -----------------------------------------------------
@app.route("/update_targets", methods=["POST"])
def update_targets():
    require_key()
    text = request.form.get("targets_text", "").strip()

    ids = []
    for line in text.splitlines():
        clean = line.strip()
        if clean:
            ids.append(clean)

    csv_value = ",".join(ids)
    heroku_set_config({"TARGET_IDS": csv_value})

    key = request.args.get("key")
    return redirect(url_for("index", key=key))


# -----------------------------------------------------
# HANDLE → ID CONVERTER
# -----------------------------------------------------
@app.route("/convert_handle", methods=["POST"])
def convert_handle():
    require_key()
    handle = request.form.get("handle", "").strip()
    key = request.args.get("key")

    if not handle:
        return redirect(url_for("index", key=key))

    if handle.startswith("@"):
        handle = handle[1:]

    bearer = os.environ.get("X_BEARER_TOKEN")
    if not bearer:
        return redirect(url_for("index", key=key))

    url = f"https://api.twitter.com/2/users/by/username/{handle}"
    headers = {"Authorization": f"Bearer {bearer}"}

    try:
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        uid = data.get("data", {}).get("id", "UNKNOWN")
    except Exception:
        uid = "ERROR"

    return redirect(url_for("index", key=key, conv_handle=handle, conv_id=uid))


# -----------------------------------------------------
# ROUTES — COMMAND TOGGLES
# -----------------------------------------------------
@app.route("/update_command_toggles", methods=["POST"])
def update_command_toggles():
    require_key()

    # Checkbox = 1, sonst 0
    def cb(name):
        return "1" if request.form.get(name) == "1" else "0"

    patch = {
        "ENABLE_HELP":  cb("enable_help"),
        "ENABLE_LORE":  cb("enable_lore"),
        "ENABLE_STATS": cb("enable_stats"),
        "ENABLE_GM":    cb("enable_gm"),
        "ENABLE_ROAST": cb("enable_roast"),
        "ENABLE_ALPHA": cb("enable_alpha"),
    }

    heroku_set_config(patch)

    key = request.args.get("key")
    return redirect(url_for("index", key=key))


# -----------------------------------------------------
# ROUTES — MEMES
# -----------------------------------------------------
@app.route("/fetch_memes_now", methods=["POST"])
def fetch_memes_now():
    require_key()
    url = f"https://api.heroku.com/apps/{HEROKU_APP_NAME}/dynos"
    payload = {
        "command": "python fetch_memes.py",
        "type": "run",
        "time_to_live": 300
    }
    try:
        requests.post(url, headers=heroku_headers(), data=json.dumps(payload), timeout=10)
    except Exception:
        pass

    key = request.args.get("key")
    return redirect(url_for("index", key=key))


@app.route("/update_meme_settings", methods=["POST"])
def update_meme_settings():
    require_key()
    auto_meme = "1" if request.form.get("auto_meme_mode") == "1" else "0"
    heroku_set_config({"AUTO_MEME_MODE": auto_meme})

    key = request.args.get("key")
    return redirect(url_for("index", key=key))


# -----------------------------------------------------
# ROUTES — BOOST SETTINGS
# -----------------------------------------------------
@app.route("/update_boost", methods=["POST"])
def update_boost():
    require_key()

    enabled = "1" if request.form.get("boost_enabled") == "1" else "0"
    cooldown = request.form.get("boost_cooldown", "3").strip()
    duration = request.form.get("boost_duration", "600").strip()

    if not cooldown.isdigit():
        cooldown = "3"
    if not duration.isdigit():
        duration = "600"

    patch = {
        "BOOST_ENABLED": enabled,
        "BOOST_COOLDOWN_S": cooldown,
        "BOOST_DURATION_S": duration
    }

    heroku_set_config(patch)

    key = request.args.get("key")
    return redirect(url_for("index", key=key))


# -----------------------------------------------------
# ROUTES — SIMULATE REPLY (GROK PREVIEW)
# -----------------------------------------------------
@app.route("/simulate_reply", methods=["POST"])
def simulate_reply():
    require_key()
    sample = request.form.get("sample_text", "").strip()
    key = request.args.get("key")

    if not sample:
        return redirect(url_for("index", key=key))

    preview = grok_preview(sample)
    return render_dashboard(preview_text=preview)


# -----------------------------------------------------
# MAIN DASHBOARD ROUTE
# -----------------------------------------------------
@app.route("/")
def index():
    require_key()
    preview = request.args.get("preview")
    return render_dashboard(preview_text=preview)


# -----------------------------------------------------
# START SERVER
# -----------------------------------------------------
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=True
    )
