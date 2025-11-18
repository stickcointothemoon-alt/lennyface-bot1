import os
import json
import requests
from flask import Flask, request, redirect, url_for, render_template_string, abort

app = Flask(__name__)

# -----------------------------
# CONFIG
# -----------------------------
DASHBOARD_KEY   = os.environ.get("DASHBOARD_KEY", "LennySuper420")
HEROKU_APP_NAME = os.environ.get("HEROKU_APP_NAME", "lennyface-bot")
HEROKU_API_KEY  = os.environ.get("HEROKU_API_KEY")

# Lenny DEX / Token (selbe ENV wie im Bot)
LENNY_TOKEN_CA = os.environ.get("LENNY_TOKEN_CA", "").strip()
DEX_TOKEN_URL  = os.environ.get("DEX_TOKEN_URL", "").strip()

# Grok Settings (nur für Preview genutzt)
GROK_API_KEY            = os.environ.get("GROK_API_KEY", "")
GROK_BASE_URL           = os.environ.get("GROK_BASE_URL", "https://api.x.ai")
GROK_MODEL              = os.environ.get("GROK_MODEL", "grok-3")
GROK_TONE               = os.environ.get("GROK_TONE", "normal")
GROK_FORCE_ENGLISH      = os.environ.get("GROK_FORCE_ENGLISH", "1")
GROK_ALWAYS_SHILL_LENNY = os.environ.get("GROK_ALWAYS_SHILL_LENNY", "1")
GROK_EXTRA_PROMPT       = os.environ.get("GROK_EXTRA_PROMPT", "")

# Bot Handle (für Help-Box)
BOT_HANDLE = os.environ.get("BOT_HANDLE", "lennyface_bot").lstrip("@")


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
    resp = requests.patch(
        url, headers=heroku_headers(), data=json.dumps(changes), timeout=10
    )
    resp.raise_for_status()
    return resp.json()


def parse_ids(csv_value: str):
    """Hilfsfunktion: aus '1,2,3' wird ['1','2','3'] ohne Leerzeichen."""
    if not csv_value:
        return []
    return [x.strip() for x in csv_value.split(",") if x.strip()]


# -----------------------------
# Lenny Stats via Dexscreener
# -----------------------------
def fetch_lenny_stats_for_dashboard():
    """
    Holt Price / MC / Vol für das Dashboard.
    Nutzt DEX_TOKEN_URL oder LENNY_TOKEN_CA.
    Gibt ein dict mit Strings zurück oder None.
    """
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

        pair = pairs[0]
        price = float(pair.get("priceUsd") or 0)
        mc = float(pair.get("fdv") or pair.get("marketCap") or 0)
        vol24 = float(
            (pair.get("volume") or {}).get("h24")
            or pair.get("volume24h")
            or 0
        )

        def fmt(n: float) -> str:
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
            "vol_str": fmt(vol24),
            "dex_name": pair.get("dexId", ""),
            "pair_url": pair.get("url", ""),
        }
    except Exception:
        return None


# -----------------------------
# Global Stats (BTC, SOL) via CoinGecko
# -----------------------------
def fetch_global_stats():
    """
    Holt BTC & SOL Price + 24h Change von CoinGecko.
    Gibt dict mit Strings zurück oder None.
    """
    url = (
        "https://api.coingecko.com/api/v3/simple/price"
        "?ids=bitcoin,solana&vs_currencies=usd&include_24hr_change=true"
    )
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json() or {}

        def fmt_price(p: float) -> str:
            if p >= 1_000_000:
                return f"${p/1_000_000:.2f}M"
            if p >= 1_000:
                return f"${p/1_000:.2f}K"
            return f"${p:.2f}"

        out = {}

        btc = data.get("bitcoin")
        if btc:
            p = float(btc.get("usd") or 0)
            ch = float(btc.get("usd_24h_change") or 0)
            out["btc_price"] = fmt_price(p)
            out["btc_change"] = f"{ch:+.2f}%"

        sol = data.get("solana")
        if sol:
            p = float(sol.get("usd") or 0)
            ch = float(sol.get("usd_24h_change") or 0)
            out["sol_price"] = fmt_price(p)
            out["sol_change"] = f"{ch:+.2f}%"

        return out or None
    except Exception:
        return None


# -----------------------------
# Grok für Preview (Simulate Reply)
# -----------------------------
def build_grok_system_prompt() -> str:
    base = (
        "You are LENNY, a cheeky, degen-style shill-bot for the $LENNY token. "
        "Reply in short, punchy, funny style. Avoid duplicate text, vary wording. "
        "Always keep replies suitable for public social media."
    )

    tone = (GROK_TONE or "normal").lower()
    if tone == "soft":
        base += " Keep your tone friendly and kind, low aggression."
    elif tone == "spicy":
        base += " You may be a bit edgy and teasing, but avoid real toxicity."
    elif tone == "savage":
        base += (
            " Use a savage, roasting banter style, but never use slurs, "
            "hate speech or real-life threats. Keep it fun."
        )
    else:
        base += " Use a balanced degen tone: fun, confident, slightly cheeky."

    if GROK_FORCE_ENGLISH == "1":
        base += " Always respond in English."

    if GROK_ALWAYS_SHILL_LENNY == "1":
        base += " Always mention $LENNY somewhere in the reply when it makes sense."

    extra = (GROK_EXTRA_PROMPT or "").strip()
    if extra:
        base += " Extra style instructions: " + extra

    base += " Add 1-2 fitting crypto or meme hashtags when relevant."
    return base


def grok_generate_preview(user_text: str) -> str:
    if not GROK_API_KEY:
        return "GROK_API_KEY fehlt – Preview nicht möglich."
    try:
        url = f"{GROK_BASE_URL}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {GROK_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": GROK_MODEL,
            "messages": [
                {"role": "system", "content": build_grok_system_prompt()},
                {
                    "role": "user",
                    "content": (
                        "Simulate how you would reply on X to this tweet. "
                        "Keep it under 220 chars. Tweet text: " + user_text[:280]
                    ),
                },
            ],
            "temperature": 0.9,
            "max_tokens": 96,
        }
        r = requests.post(url, headers=headers, json=payload, timeout=20)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"Grok Preview failed: {e}"


# -----------------------------
# STARTSEITE / DASHBOARD
# -----------------------------
def render_dashboard(preview_text: str | None = None):
    cfg = heroku_get_config()
    key = request.args.get("key", "")

    # State / Targets
    state_seen_csv = cfg.get("STATE_SEEN_IDS", "")
    seen_ids = parse_ids(state_seen_csv)
    seen_count = len(seen_ids)

    target_csv = cfg.get("TARGET_IDS", "")
    targets = parse_ids(target_csv)
    target_count = len(targets)

    bot_paused = cfg.get("BOT_PAUSED", "0")  # "0" oder "1"

    # Grok Settings aus Config (falls via Dashboard geändert)
    grok_tone = cfg.get("GROK_TONE", GROK_TONE)
    grok_force_en = cfg.get("GROK_FORCE_ENGLISH", GROK_FORCE_ENGLISH)
    grok_always_lenny = cfg.get("GROK_ALWAYS_SHILL_LENNY", GROK_ALWAYS_SHILL_LENNY)
    grok_extra = cfg.get("GROK_EXTRA_PROMPT", GROK_EXTRA_PROMPT)

    # Meme Fetch URL
    fetch_url = cfg.get("FETCH_MEMES_URL", "")

    # Cooldowns / Boost aus Config
    read_cooldown = cfg.get("READ_COOLDOWN_S", os.environ.get("READ_COOLDOWN_S", "6"))
    loop_sleep = cfg.get("LOOP_SLEEP_SECONDS", os.environ.get("LOOP_SLEEP_SECONDS", "240"))

    boost_enabled  = cfg.get("BOOST_ENABLED", os.environ.get("BOOST_ENABLED", "1"))
    boost_cooldown = cfg.get("BOOST_COOLDOWN_S", os.environ.get("BOOST_COOLDOWN_S", "3"))
    boost_duration = cfg.get("BOOST_DURATION_S", os.environ.get("BOOST_DURATION_S", "600"))

    # Command-Toggles aus Config
    enable_help  = cfg.get("ENABLE_HELP", os.environ.get("ENABLE_HELP", "1"))
    enable_lore  = cfg.get("ENABLE_LORE", os.environ.get("ENABLE_LORE", "1"))
    enable_stats = cfg.get("ENABLE_STATS", os.environ.get("ENABLE_STATS", "1"))
    enable_alpha = cfg.get("ENABLE_ALPHA", os.environ.get("ENABLE_ALPHA", "1"))
    enable_gm    = cfg.get("ENABLE_GM", os.environ.get("ENABLE_GM", "1"))
    enable_roast = cfg.get("ENABLE_ROAST", os.environ.get("ENABLE_ROAST", "1"))

    # Stats aus Config (vom Bot geschrieben)
    stats_date  = cfg.get("STATS_DATE", "")
    stats_total = cfg.get("STATS_REPLIES_TOTAL", "0")
    stats_mens  = cfg.get("STATS_REPLIES_MENTIONS", "0")
    stats_kol   = cfg.get("STATS_REPLIES_KOL", "0")
    stats_memes = cfg.get("STATS_MEMES_USED", "0")

    # Market Daten
    lenny_stats  = fetch_lenny_stats_for_dashboard()
    global_stats = fetch_global_stats()

    template = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Lenny Bot Dashboard v3</title>
  <style>
    body {
      background: radial-gradient(circle at top, #1e293b 0, #020617 55%);
      color: #f9fafb;
      font-family: Arial, sans-serif;
      margin: 0;
      padding: 0;
    }
    .wrap {
      max-width: 1200px;
      margin: 20px auto;
      padding: 0 10px 40px;
    }
    h1, h2, h3 {
      color: #ffe66d;
    }
    .card {
      border: 1px solid #1f2937;
      border-radius: 12px;
      padding: 15px 20px;
      margin-bottom: 16px;
      background: rgba(15,23,42,0.95);
      box-shadow: 0 10px 30px rgba(0,0,0,0.45);
    }
    .row {
      display: flex;
      gap: 16px;
      flex-wrap: wrap;
    }
    .col {
      flex: 1;
      min-width: 280px;
    }
    label {
      display: block;
      margin-top: 8px;
      font-size: 0.9rem;
    }
    input[type="text"], textarea, select {
      width: 100%;
      padding: 6px 8px;
      border-radius: 6px;
      border: 1px solid #374151;
      background: #020617;
      color: #f9fafb;
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
      padding: 8px 14px;
      border-radius: 999px;
      border: none;
      cursor: pointer;
      font-weight: bold;
      font-size: 0.9rem;
    }
    .btn-green { background: #22c55e; color: #000; }
    .btn-orange { background: #f97316; color: #000; }
    .btn-red { background: #ef4444; color: #fff; }
    .btn-blue { background: #3b82f6; color: #fff; }
    small { color: #9ca3af; }
    pre {
      background: #020617;
      padding: 10px;
      border-radius: 6px;
      overflow-x: auto;
      font-size: 0.8rem;
    }
    .stat-line {
      margin: 3px 0;
      font-size: 0.9rem;
    }
    .pill {
      display: inline-block;
      padding: 4px 10px;
      border-radius: 999px;
      font-size: 0.75rem;
      background: #111827;
      margin-right: 4px;
    }
    a {
      color: #60a5fa;
    }
    .badge-pos { color: #22c55e; font-weight: bold; }
    .badge-neg { color: #ef4444; font-weight: bold; }
    .headline {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .headline-face {
      font-size: 1.4rem;
    }
    .subgrid {
      display: grid;
      grid-template-columns: repeat(auto-fit,minmax(160px,1fr));
      gap: 8px;
      margin-top: 6px;
    }
    .subpill-title {
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: #9ca3af;
    }
    .subpill-value {
      font-size: 0.95rem;
      font-weight: bold;
    }
  </style>
</head>
<body>
<div class="wrap">
  <div class="headline">
    <div class="headline-face">( ͡° ͜ʖ ͡°)</div>
    <h1>Lenny Bot Dashboard v3</h1>
  </div>

  <!-- BOT STATUS + GLOBAL -->
  <div class="row">
    <div class="card col">
      <h2>Bot Status</h2>
      <div class="stat-line">
        <span class="pill">Seen IDs: {{ seen_count }}</span>
        <span class="pill">Targets: {{ target_count }}</span>
        <span class="pill">BOT_PAUSED: {{ 'YES' if bot_paused=='1' else 'NO' }}</span>
      </div>
      <div class="subgrid">
        <div>
          <div class="subpill-title">Normal cooldown</div>
          <div class="subpill-value">{{ read_cooldown }} s</div>
        </div>
        <div>
          <div class="subpill-title">Loop sleep</div>
          <div class="subpill-value">{{ loop_sleep }} s</div>
        </div>
      </div>
      <form method="post" action="{{ url_for('update_bot_control_v3') }}?key={{ key }}">
        <input type="hidden" name="key" value="{{ key }}">
        <label>Bot Control:</label>
        <select name="bot_paused">
          <option value="0" {% if bot_paused=='0' %}selected{% endif %}>Running</option>
          <option value="1" {% if bot_paused=='1' %}selected{% endif %}>Paused</option>
        </select>
        <button class="btn btn-green" type="submit">Save Bot State</button>
        <small>BOT_PAUSED = 1 → Worker schläft, 0 → aktiv.</small>
      </form>
    </div>

    <div class="card col">
      <h2>Global Market (BTC / SOL)</h2>
      {% if global_stats %}
        <p class="stat-line">
          <strong>BTC:</strong>
          {{ global_stats.btc_price }} (<span class="{{ 'badge-pos' if global_stats.btc_change.startswith('+') else 'badge-neg' }}">{{ global_stats.btc_change }}</span>)<br>
          <strong>SOL:</strong>
          {{ global_stats.sol_price }} (<span class="{{ 'badge-pos' if global_stats.sol_change.startswith('+') else 'badge-neg' }}">{{ global_stats.sol_change }}</span>)
        </p>
      {% else %}
        <p class="stat-line">Keine BTC/SOL-Daten (CoinGecko-Rate-Limit oder Netzwerk-Fehler).</p>
      {% endif %}
      <small>Diese Daten kommen direkt von CoinGecko (kein X-API Limit).</small>
    </div>
  </div>

  <!-- LENNY STATS + DAILY POST -->
  <div class="card">
    <h2>$LENNY Market Stats</h2>
    {% if lenny_stats %}
      <p class="stat-line">
        <strong>Price:</strong> {{ lenny_stats.price_str }}<br>
        <strong>Market Cap:</strong> {{ lenny_stats.mc_str }}<br>
        <strong>24h Vol:</strong> {{ lenny_stats.vol_str }}<br>
        {% if lenny_stats.pair_url %}
          <strong>Dex:</strong> <a href="{{ lenny_stats.pair_url }}" target="_blank">
            {{ lenny_stats.dex_name or 'Dexscreener' }}
          </a>
        {% endif %}
      </p>
    {% else %}
      <p class="stat-line">
        Keine $LENNY DEX-Daten. Prüfe <code>LENNY_TOKEN_CA</code> / <code>DEX_TOKEN_URL</code> in den Config Vars.
      </p>
    {% endif %}

    <form method="post" action="{{ url_for('trigger_daily_post_v3') }}?key={{ key }}">
      <input type="hidden" name="key" value="{{ key }}">
      <button class="btn btn-orange" type="submit">🚀 Daily Post jetzt senden</button>
    </form>
    <small>Startet einen One-off Dyno mit <code>python daily_post_now.py</code>.</small>
  </div>

  <!-- ROW: TARGETS + GROK -->
  <div class="row">
    <!-- TARGETS -->
    <div class="card col">
      <h2>Targets (KOLs)</h2>
      <form method="post" action="{{ url_for('update_targets_v3') }}?key={{ key }}">
        <input type="hidden" name="key" value="{{ key }}">
        <label>Aktuelle TARGET_IDS (eine pro Zeile):</label>
        <textarea name="targets_text">{% for t in targets %}{{ t }}
{% endfor %}</textarea>
        <button class="btn btn-blue" type="submit">Save TARGET_IDS</button>
        <small>Wird als Komma-Liste in TARGET_IDS gespeichert.</small>
      </form>

      <hr>
      <h3>Handle → ID Converter</h3>
      <form method="post" action="{{ url_for('convert_handle_v3') }}?key={{ key }}">
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
      <form method="post" action="{{ url_for('update_grok_v3') }}?key={{ key }}">
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

  <!-- MEMES & STATE + BOOST + STATS -->
  <div class="row">
    <div class="card col">
      <h2>Memes</h2>
      <p class="stat-line">
        <strong>FETCH_MEMES_URL:</strong><br>
        <code>{{ fetch_url or 'nicht gesetzt' }}</code>
      </p>
      <form method="post" action="{{ url_for('trigger_fetch_memes_v3') }}?key={{ key }}">
        <input type="hidden" name="key" value="{{ key }}">
        <button class="btn btn-orange" type="submit">Fetch Memes Now</button>
      </form>
      <small>Ruft intern <code>python fetch_memes.py</code> als One-off Dyno auf.</small>
    </div>

    <div class="card col">
      <h2>State / Seen IDs</h2>
      <p class="stat-line">
        <strong>STATE_SEEN_IDS:</strong> {{ seen_count }} IDs
      </p>
      <form method="post" action="{{ url_for('trigger_seed_backup_v3') }}?key={{ key }}">
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

  <div class="row">
    <!-- BOOST -->
    <div class="card col">
      <h2>Boost Mode</h2>
      <p class="stat-line">
        <span class="pill">Boost: {{ 'ON' if boost_enabled=='1' else 'OFF' }}</span>
        <span class="pill">Boost cooldown: {{ boost_cooldown }}s</span>
        <span class="pill">Normal: {{ read_cooldown }}s</span>
      </p>
      <p class="stat-line">
        Wenn Boost aktiv ist, antwortet der Bot enger getaktet (kürzerer Cooldown)
        für {{ boost_duration }} Sekunden, sobald viele Mentions reinfliegen.
      </p>
      <form method="post" action="{{ url_for('update_boost_v3') }}?key={{ key }}">
        <input type="hidden" name="key" value="{{ key }}">

        <label>Boost Enabled:</label>
        <select name="boost_enabled">
          <option value="1" {% if boost_enabled=='1' %}selected{% endif %}>ON</option>
          <option value="0" {% if boost_enabled=='0' %}selected{% endif %}>OFF</option>
        </select>

        <label>Boost Cooldown (Sekunden):</label>
        <input type="text" name="boost_cooldown" value="{{ boost_cooldown }}">

        <label>Boost Dauer (Sekunden):</label>
        <input type="text" name="boost_duration" value="{{ boost_duration }}">

        <button class="btn btn-green" type="submit">Save Boost Settings</button>
      </form>
      <small>
        Empfehlung: normaler Cooldown z.B. 6s, Boost 3s für 600s.<br>
        Der Bot entscheidet intern, wann auto-Boost getriggert wird (Mentions-Spike).
      </small>
    </div>

    <!-- DAILY STATS -->
    <div class="card col">
      <h2>Daily Activity / Stats</h2>
      <p class="stat-line">
        <strong>Date (UTC):</strong> {{ stats_date or 'n/a' }}
      </p>
      <div class="subgrid">
        <div>
          <div class="subpill-title">Replies total</div>
          <div class="subpill-value">{{ stats_total }}</div>
        </div>
        <div>
          <div class="subpill-title">Mentions replied</div>
          <div class="subpill-value">{{ stats_mens }}</div>
        </div>
        <div>
          <div class="subpill-title">KOL replies</div>
          <div class="subpill-value">{{ stats_kol }}</div>
        </div>
        <div>
          <div class="subpill-title">Memes used</div>
          <div class="subpill-value">{{ stats_memes }}</div>
        </div>
      </div>
      <small>
        Diese Werte werden vom Bot über Config Vars geschrieben.<br>
        Wenn alles auf 0 steht, wurde heute noch nichts getrackt oder der Bot läuft erst seit kurzem.
      </small>
    </div>
  </div>

  <!-- COMMAND TOGGLES -->
  <div class="card">
    <h2>Command Toggles</h2>
    <form method="post" action="{{ url_for('update_commands_v3') }}?key={{ key }}">
      <input type="hidden" name="key" value="{{ key }}">

      <label>
        <input type="checkbox" name="enable_help" value="1" {% if enable_help=='1' %}checked{% endif %}>
        Enable <code>help</code>
      </label>

      <label>
        <input type="checkbox" name="enable_lore" value="1" {% if enable_lore=='1' %}checked{% endif %}>
        Enable <code>lore</code>
      </label>

      <label>
        <input type="checkbox" name="enable_stats" value="1" {% if enable_stats=='1' %}checked{% endif %}>
        Enable <code>price/mc/stats/volume/chart</code>
      </label>

      <label>
        <input type="checkbox" name="enable_alpha" value="1" {% if enable_alpha=='1' %}checked{% endif %}>
        Enable <code>alpha</code>
      </label>

      <label>
        <input type="checkbox" name="enable_gm" value="1" {% if enable_gm=='1' %}checked{% endif %}>
        Enable <code>gm</code>
      </label>

      <label>
        <input type="checkbox" name="enable_roast" value="1" {% if enable_roast=='1' %}checked{% endif %}>
        Enable <code>roast</code>
      </label>

      <button class="btn btn-green" type="submit">Save Command Settings</button>
    </form>
    <small>
      Wenn ein Command deaktiviert ist, antwortet der Bot stattdessen mit einem normalen $LENNY-Shill.
    </small>
  </div>

  <!-- REPLY SIMULATOR -->
  <div class="card">
    <h2>Reply Simulator (Grok Preview)</h2>
    <form method="post" action="{{ url_for('simulate_reply_v3') }}?key={{ key }}">
      <input type="hidden" name="key" value="{{ key }}">
      <label>Beispiel-Tweet eingeben:</label>
      <textarea name="sample_text" placeholder="@lennyface_bot what do you think about this pump?"></textarea>
      <button class="btn btn-green" type="submit">Simulate Reply</button>
    </form>
    {% if preview_text %}
      <h3>Preview:</h3>
      <pre>{{ preview_text }}</pre>
    {% endif %}
    <small>Nutze das, um zu testen, wie Lenny in deinem aktuellen Tone/Prompt antwortet – ohne X-API Limit.</small>
  </div>

  <div class="card">
    <h2>Bot Commands / Usage</h2>
    <p class="stat-line">
      How to interact with <strong>@{{ BOT_HANDLE }}</strong>:
    </p>
    <pre>
@lennyface_bot help
  → Show full help menu.

@lennyface_bot lore
  → Lenny ( ͡° ͜ʖ ͡°) meme history / big facts.

Contains: price / mc / stats / volume / chart
  → Live $LENNY market cap (and link to DEX).

Contains: alpha
  → Degen alpha line.

Starts with gm / contains " gm"
  → Good-morning degen reply.

Contains: roast / "roast me"
  → Light roast, no slurs.
    </pre>
    <small>Bot replies only if he's mentioned alone in the tweet.</small>
  </div>

  <div class="card">
    <h3>Hinweis</h3>
    <small>
      Vollständige Heroku-Logs weiterhin über:
      <code>heroku logs -t -a {{ app_name }}</code><br>
      Dieses Dashboard steuert den Bot rein über Config Vars & One-off Dynos.
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
        lenny_stats=lenny_stats,
        global_stats=global_stats,
        preview_text=preview_text,
        BOT_HANDLE=BOT_HANDLE,
        read_cooldown=read_cooldown,
        loop_sleep=loop_sleep,
        boost_enabled=boost_enabled,
        boost_cooldown=boost_cooldown,
        boost_duration=boost_duration,
        enable_help=enable_help,
        enable_lore=enable_lore,
        enable_stats=enable_stats,
        enable_alpha=enable_alpha,
        enable_gm=enable_gm,
        enable_roast=enable_roast,
        stats_date=stats_date,
        stats_total=stats_total,
        stats_mens=stats_mens,
        stats_kol=stats_kol,
        stats_memes=stats_memes,
    )


@app.route("/")
def index_v3():
    require_key()
    preview = request.args.get("preview") or None
    return render_dashboard(preview_text=preview)


# -----------------------------
# BOT CONTROL
# -----------------------------
@app.route("/update_bot_v3", methods=["POST"])
def update_bot_control_v3():
    require_key()
    paused = request.form.get("bot_paused", "0")
    paused = "1" if paused == "1" else "0"
    heroku_set_config({"BOT_PAUSED": paused})
    key = request.args.get("key", "")
    return redirect(url_for("index_v3", key=key))


# -----------------------------
# TARGETS
# -----------------------------
@app.route("/update_targets_v3", methods=["POST"])
def update_targets_v3():
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
    return redirect(url_for("index_v3", key=key))


# -----------------------------
# GROK SETTINGS
# -----------------------------
@app.route("/update_grok_v3", methods=["POST"])
def update_grok_v3():
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
    return redirect(url_for("index_v3", key=key))


# -----------------------------
# BOOST SETTINGS
# -----------------------------
@app.route("/update_boost_v3", methods=["POST"])
def update_boost_v3():
    require_key()
    enabled = "1" if request.form.get("boost_enabled") == "1" else "0"
    cooldown = (request.form.get("boost_cooldown", "") or "").strip() or "3"
    duration = (request.form.get("boost_duration", "") or "").strip() or "600"

    # Nur Zahlen basic filtern
    if not cooldown.isdigit():
        cooldown = "3"
    if not duration.isdigit():
        duration = "600"

    heroku_set_config({
        "BOOST_ENABLED": enabled,
        "BOOST_COOLDOWN_S": cooldown,
        "BOOST_DURATION_S": duration,
    })

    key = request.args.get("key", "")
    return redirect(url_for("index_v3", key=key))


# -----------------------------
# COMMAND TOGGLES
# -----------------------------
@app.route("/update_commands_v3", methods=["POST"])
def update_commands_v3():
    require_key()

    def flag(field_name: str) -> str:
        # Checkbox → "1" wenn angehakt, sonst "0"
        return "1" if request.form.get(field_name) == "1" else "0"

    changes = {
        "ENABLE_HELP":  flag("enable_help"),
        "ENABLE_LORE":  flag("enable_lore"),
        "ENABLE_STATS": flag("enable_stats"),
        "ENABLE_ALPHA": flag("enable_alpha"),
        "ENABLE_GM":    flag("enable_gm"),
        "ENABLE_ROAST": flag("enable_roast"),
    }

    heroku_set_config(changes)
    key = request.args.get("key", "")
    return redirect(url_for("index_v3", key=key))


# -----------------------------
# HANDLE → ID CONVERTER
# -----------------------------
@app.route("/convert_handle_v3", methods=["POST"])
def convert_handle_v3():
    require_key()
    handle = request.form.get("handle", "").strip()
    key = request.args.get("key", "")

    if not handle:
        return redirect(url_for("index_v3", key=key))

    if handle.startswith("@"):
        handle = handle[1:]

    bearer = os.environ.get("X_BEARER_TOKEN")
    if not bearer:
        return redirect(url_for("index_v3", key=key))

    url = f"https://api.twitter.com/2/users/by/username/{handle}"
    headers = {"Authorization": f"Bearer {bearer}"}

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        user_id = data.get("data", {}).get("id", "UNKNOWN")
    except Exception:
        user_id = "ERROR"

    return redirect(url_for("index_v3", key=key, conv_handle=handle, conv_id=user_id))


# -----------------------------
# MEMES TRIGGER
# -----------------------------
@app.route("/fetch_memes_now_v3", methods=["POST"])
def trigger_fetch_memes_v3():
    require_key()
    url = f"https://api.heroku.com/apps/{HEROKU_APP_NAME}/dynos"
    payload = {
        "command": "python fetch_memes.py",
        "type": "run",
        "time_to_live": 300,
    }
    try:
        requests.post(url, headers=heroku_headers(), data=json.dumps(payload), timeout=10)
    except Exception:
        pass

    key = request.args.get("key", "")
    return redirect(url_for("index_v3", key=key))


# -----------------------------
# SEED + BACKUP ENV TRIGGER
# -----------------------------
@app.route("/seed_backup_now_v3", methods=["POST"])
def trigger_seed_backup_v3():
    require_key()
    url = f"https://api.heroku.com/apps/{HEROKU_APP_NAME}/dynos"
    payload = {
        "command": "python seed_and_backup_env.py",
        "type": "run",
        "time_to_live": 600,
    }
    try:
        requests.post(url, headers=heroku_headers(), data=json.dumps(payload), timeout=10)
    except Exception:
        pass

    key = request.args.get("key", "")
    return redirect(url_for("index_v3", key=key))


# -----------------------------
# DAILY POST TRIGGER
# -----------------------------
@app.route("/daily_post_now_v3", methods=["POST"])
def trigger_daily_post_v3():
    require_key()
    url = f"https://api.heroku.com/apps/{HEROKU_APP_NAME}/dynos"
    payload = {
        "command": "python daily_post_now.py",
        "type": "run",
        "time_to_live": 600,
    }
    try:
        requests.post(url, headers=heroku_headers(), data=json.dumps(payload), timeout=10)
    except Exception:
        pass

    key = request.args.get("key", "")
    return redirect(url_for("index_v3", key=key))


# -----------------------------
# REPLY SIMULATOR
# -----------------------------
@app.route("/simulate_reply_v3", methods=["POST"])
def simulate_reply_v3():
    require_key()
    sample = request.form.get("sample_text", "").strip()
    key = request.args.get("key", "")
    if not sample:
        return redirect(url_for("index_v3", key=key))

    preview = grok_generate_preview(sample)
    return render_dashboard(preview_text=preview)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
