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

# Bot Handle (für Info / Doku)
BOT_HANDLE = os.environ.get("BOT_HANDLE", "lennyface_bot").lstrip("@")

# Grok Defaults
GROK_API_KEY            = os.environ.get("GROK_API_KEY", "")
GROK_BASE_URL           = os.environ.get("GROK_BASE_URL", "https://api.x.ai")
GROK_MODEL              = os.environ.get("GROK_MODEL", "grok-3")
GROK_TONE               = os.environ.get("GROK_TONE", "normal")
GROK_FORCE_ENGLISH      = os.environ.get("GROK_FORCE_ENGLISH", "1")
GROK_ALWAYS_SHILL_LENNY = os.environ.get("GROK_ALWAYS_SHILL_LENNY", "1")
GROK_EXTRA_PROMPT       = os.environ.get("GROK_EXTRA_PROMPT", "")


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
    if not HEROKU_API_KEY:
        raise RuntimeError("HEROKU_API_KEY missing")
    return {
        "Authorization": f"Bearer {HEROKU_API_KEY}",
        "Accept": "application/vnd.heroku+json; version=3",
        "Content-Type": "application/json",
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


def parse_ids(text: str):
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
        data = r.json() or {}
        pairs = data.get("pairs") or []
        if not pairs:
            return None

        p = pairs[0]
        price = float(p.get("priceUsd") or 0)
        mc = float(p.get("fdv") or p.get("marketCap") or 0)
        vol = float(
            (p.get("volume") or {}).get("h24")
            or p.get("volume24h")
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
            "vol_str": fmt(vol),
            "dex_name": p.get("dexId", "") or "Dexscreener",
            "pair_url": p.get("url", ""),
        }
    except Exception:
        return None


def fetch_global_stats():
    url = (
        "https://api.coingecko.com/api/v3/simple/price"
        "?ids=bitcoin,solana&vs_currencies=usd&include_24hr_change=true"
    )
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json() or {}

        def fmt(p: float) -> str:
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

        return out or None
    except Exception:
        return None


# -----------------------------------------------------
# GROK PREVIEW
# -----------------------------------------------------
def build_grok_prompt() -> str:
    base = (
        "You are LENNY, a cheeky, degen-style shill bot for $LENNY. "
        "Be short, punchy, funny and varied. No slurs or real toxicity."
    )

    tone = (GROK_TONE or "normal").lower()
    if tone == "soft":
        base += " Keep the tone friendly and kind."
    elif tone == "spicy":
        base += " Be a bit edgy and teasing."
    elif tone == "savage":
        base += " Be savage banter style, but stay safe."

    if GROK_FORCE_ENGLISH == "1":
        base += " Always reply in English."

    if GROK_ALWAYS_SHILL_LENNY == "1":
        base += " Mention $LENNY when it fits."

    extra = (GROK_EXTRA_PROMPT or "").strip()
    if extra:
        base += " Extra instructions: " + extra

    return base


def grok_preview(text: str) -> str:
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
                {"role": "system", "content": build_grok_prompt()},
                {
                    "role": "user",
                    "content": (
                        "Simulate how you would reply on X to this tweet. "
                        "Keep it under 220 chars. Tweet text: " + text[:280]
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


# -----------------------------------------------------
# RENDER DASHBOARD
# -----------------------------------------------------
def render_dashboard(preview_text: str | None = None):
    cfg = heroku_get_config()
    key = request.args.get("key")

    # State
    seen_ids = parse_ids(cfg.get("STATE_SEEN_IDS", ""))
    target_ids = parse_ids(cfg.get("TARGET_IDS", ""))

    # Bot status
    bot_paused = cfg.get("BOT_PAUSED", "0")
    auto_meme_mode = cfg.get("AUTO_MEME_MODE", "1")

    # Cooldowns / Loop
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

    template = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>LennyBot Dashboard v3.6</title>
  <style>
    :root {
      --bg-main: #020617;
      --bg-card: #020617;
      --bg-card-soft: #020617;
      --border-subtle: #1e293b;
      --accent-mint: #2dd4bf;
      --accent-mint-soft: rgba(45,212,191,0.12);
      --accent-blue: #38bdf8;
      --accent-red: #f97373;
      --accent-orange: #fb923c;
      --text-main: #e5e7eb;
      --text-soft: #9ca3af;
      --text-strong: #f9fafb;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 0;
      background:
        radial-gradient(circle at 0% 0%, #0f172a 0, #020617 45%),
        radial-gradient(circle at 100% 100%, #0b1120 0, #020617 55%);
      color: var(--text-main);
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    a { color: var(--accent-mint); text-decoration: none; }
    a:hover { text-decoration: underline; }
    .wrap {
      max-width: 1200px;
      margin: 24px auto 40px;
      padding: 0 16px;
    }
    .header {
      display: flex;
      gap: 12px;
      align-items: center;
      margin-bottom: 20px;
    }
    .header-face {
      font-size: 2rem;
      padding: 8px 12px;
      border-radius: 999px;
      background: radial-gradient(circle at 30% 20%, #22c55e 0, #0f172a 45%, #020617 80%);
      box-shadow: 0 0 25px rgba(45,212,191,0.3);
    }
    h1 {
      margin: 0;
      font-size: 1.6rem;
      color: var(--text-strong);
    }
    .header-sub {
      font-size: 0.85rem;
      color: var(--text-soft);
    }
    .row {
      display: flex;
      flex-wrap: wrap;
      gap: 16px;
      margin-bottom: 16px;
    }
    .col {
      flex: 1;
      min-width: 320px;
    }
    .card {
      background: radial-gradient(circle at top left, rgba(45,212,191,0.08) 0, var(--bg-card) 55%);
      border-radius: 18px;
      padding: 16px 18px 18px;
      border: 1px solid var(--border-subtle);
      box-shadow: 0 18px 35px rgba(0,0,0,0.55);
    }
    .card h2 {
      margin: 0 0 10px;
      font-size: 1.1rem;
      letter-spacing: 0.03em;
      text-transform: uppercase;
      color: var(--accent-mint);
    }
    .card h3 {
      margin: 6px 0 6px;
      font-size: 0.95rem;
      color: var(--accent-blue);
    }
    label {
      display: block;
      margin-top: 6px;
      font-size: 0.87rem;
    }
    input[type="text"],
    textarea,
    select {
      width: 100%;
      padding: 7px 9px;
      margin-top: 2px;
      border-radius: 10px;
      border: 1px solid #1f2937;
      background: #020617;
      color: var(--text-main);
      font-size: 0.9rem;
    }
    textarea {
      min-height: 74px;
      resize: vertical;
      font-family: monospace;
    }
    input[type="checkbox"] {
      width: auto;
      margin-right: 6px;
    }
    .btn {
      display: inline-block;
      margin-top: 10px;
      padding: 8px 14px;
      border-radius: 999px;
      border: none;
      cursor: pointer;
      font-weight: 600;
      font-size: 0.86rem;
      letter-spacing: 0.03em;
      text-transform: uppercase;
    }
    .btn-mint {
      background: var(--accent-mint);
      color: #022c22;
      box-shadow: 0 8px 18px rgba(45,212,191,0.35);
    }
    .btn-orange {
      background: var(--accent-orange);
      color: #2b1104;
      box-shadow: 0 8px 18px rgba(251,146,60,0.3);
    }
    .btn-blue {
      background: var(--accent-blue);
      color: #022c42;
      box-shadow: 0 8px 18px rgba(56,189,248,0.35);
    }
    .btn-red {
      background: var(--accent-red);
      color: #450a0a;
      box-shadow: 0 8px 18px rgba(248,113,113,0.35);
    }
    .pill {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 4px 10px;
      margin: 0 6px 6px 0;
      border-radius: 999px;
      background: rgba(15,23,42,0.9);
      border: 1px solid #111827;
      font-size: 0.78rem;
      color: var(--text-soft);
    }
    .pill-dot {
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: var(--accent-mint);
    }
    .pill-dot-red {
      background: var(--accent-red);
    }
    .pill-dot-grey {
      background: #4b5563;
    }
    small { font-size: 0.78rem; color: var(--text-soft); }
    pre {
      background: #020617;
      border-radius: 10px;
      padding: 10px;
      font-size: 0.82rem;
      overflow-x: auto;
      border: 1px solid #111827;
    }
    .stat-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
      gap: 8px;
      margin-top: 4px;
    }
    .stat-item-title {
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--text-soft);
    }
    .stat-item-value {
      font-size: 0.95rem;
      font-weight: 600;
      color: var(--text-strong);
    }
    .badge-pos { color: #22c55e; font-weight: 600; }
    .badge-neg { color: #f97373; font-weight: 600; }
    hr {
      border: none;
      border-top: 1px solid rgba(148,163,184,0.18);
      margin: 10px 0;
    }
  </style>
</head>
<body>
<div class="wrap">

  <div class="header">
    <div class="header-face">( ͡° ͜ʖ ͡°)</div>
    <div>
      <h1>LennyBot Dashboard v3.6 — Cyber Mint</h1>
      <div class="header-sub">
        Connected to Heroku app <code>{{ app_name }}</code> · Bot: <strong>@{{ bot_handle }}</strong>
      </div>
    </div>
  </div>

  <!-- ROW 1: BOT STATUS + GLOBAL MARKET -->
  <div class="row">
    <div class="col">
      <div class="card">
        <h2>Bot Status</h2>
        <div>
          <span class="pill">
            <span class="pill-dot"></span> Seen IDs: {{ seen_count }}
          </span>
          <span class="pill">
            <span class="pill-dot"></span> Targets: {{ target_count }}
          </span>
          <span class="pill">
            <span class="pill-dot {% if bot_paused=='1' %}pill-dot-red{% else %}pill-dot{% endif %}"></span>
            {{ 'Paused' if bot_paused=='1' else 'Running' }}
          </span>
        </div>

        <form method="post" action="{{ url_for('update_bot_state', key=key) }}">
          <input type="hidden" name="key" value="{{ key }}">
          <label>Bot Running / Paused</label>
          <select name="bot_paused">
            <option value="0" {% if bot_paused=='0' %}selected{% endif %}>Running</option>
            <option value="1" {% if bot_paused=='1' %}selected{% endif %}>Paused</option>
          </select>
          <label>Read cooldown (s)</label>
          <input type="text" value="{{ read_cooldown }}" disabled>
          <label>Loop sleep (s)</label>
          <input type="text" value="{{ loop_sleep }}" disabled>
          <button class="btn btn-mint" type="submit">Save Status</button>
        </form>
        <small>BOT_PAUSED = 1 → Worker schläft, 0 → aktiv.</small>
      </div>
    </div>

    <div class="col">
      <div class="card">
        <h2>Global Market</h2>
        {% if global_stats %}
          <div class="stat-grid">
            <div>
              <div class="stat-item-title">BTC</div>
              <div class="stat-item-value">
                {{ global_stats.btc_price }}
                <span class="{% if global_stats.btc_change.startswith('+') %}badge-pos{% else %}badge-neg{% endif %}">
                  {{ global_stats.btc_change }}
                </span>
              </div>
            </div>
            <div>
              <div class="stat-item-title">SOL</div>
              <div class="stat-item-value">
                {{ global_stats.sol_price }}
                <span class="{% if global_stats.sol_change.startswith('+') %}badge-pos{% else %}badge-neg{% endif %}">
                  {{ global_stats.sol_change }}
                </span>
              </div>
            </div>
          </div>
        {% else %}
          <p>Keine BTC/SOL Daten (CoinGecko-Limit oder Netzwerk).</p>
        {% endif %}
        <small>Daten direkt von CoinGecko – unabhängig von X API.</small>
      </div>
    </div>
  </div>

  <!-- ROW 2: LENNY MARKET + DAILY POST -->
  <div class="row">
    <div class="col">
      <div class="card">
        <h2>$LENNY Market</h2>
        {% if lenny_stats %}
          <div class="stat-grid">
            <div>
              <div class="stat-item-title">Price</div>
              <div class="stat-item-value">{{ lenny_stats.price_str }}</div>
            </div>
            <div>
              <div class="stat-item-title">Market Cap</div>
              <div class="stat-item-value">{{ lenny_stats.mc_str }}</div>
            </div>
            <div>
              <div class="stat-item-title">24h Vol</div>
              <div class="stat-item-value">{{ lenny_stats.vol_str }}</div>
            </div>
          </div>
          {% if lenny_stats.pair_url %}
            <p style="margin-top:8px;">
              <small>Dex:</small>
              <a href="{{ lenny_stats.pair_url }}" target="_blank">
                {{ lenny_stats.dex_name }}
              </a>
            </p>
          {% endif %}
        {% else %}
          <p>Keine DEX Daten. Prüfe <code>LENNY_TOKEN_CA</code> / <code>DEX_TOKEN_URL</code>.</p>
        {% endif %}
      </div>
    </div>

    <div class="col">
      <div class="card">
        <h2>$LENNY Daily Post</h2>
        <p style="font-size:0.9rem; margin-bottom:8px;">
          Starte den täglichen $LENNY Tweet manuell – gut für geplante Shill-Wellen.
        </p>
        <form method="post" action="{{ url_for('trigger_daily_post', key=key) }}">
          <input type="hidden" name="key" value="{{ key }}">
          <button class="btn btn-orange" type="submit">🚀 Daily Post jetzt senden</button>
        </form>
        <small>Startet einen One-off Dyno:
          <code>python daily_post_now.py</code></small>
      </div>
    </div>
  </div>

  <!-- ROW 3: COMMAND TOGGLES + MEMES -->
  <div class="row">
    <div class="col">
      <div class="card">
        <h2>Command Toggles</h2>
        <p style="font-size:0.85rem; margin-bottom:8px;">
          Steuert, welche Commands der Bot aktiv beantwortet.
        </p>
        <form method="post" action="{{ url_for('update_command_toggles', key=key) }}">
          <input type="hidden" name="key" value="{{ key }}">
          <label><input type="checkbox" name="enable_help"  value="1" {% if enable_help=='1' %}checked{% endif %}> help</label>
          <label><input type="checkbox" name="enable_lore"  value="1" {% if enable_lore=='1' %}checked{% endif %}> lore</label>
          <label><input type="checkbox" name="enable_stats" value="1" {% if enable_stats=='1' %}checked{% endif %}> stats / price / mc</label>
          <label><input type="checkbox" name="enable_gm"    value="1" {% if enable_gm=='1' %}checked{% endif %}> gm</label>
          <label><input type="checkbox" name="enable_roast" value="1" {% if enable_roast=='1' %}checked{% endif %}> roast</label>
          <label><input type="checkbox" name="enable_alpha" value="1" {% if enable_alpha=='1' %}checked{% endif %}> alpha</label>
          <button class="btn btn-mint" type="submit">Save Command Toggles</button>
        </form>
        <small>Wenn ein Command deaktiviert ist, sendet der Bot normale Shill-Replies.</small>
      </div>
    </div>

    <div class="col">
      <div class="card">
        <h2>Memes & Auto Meme Mode</h2>
        <form method="post" action="{{ url_for('fetch_memes_now', key=key) }}">
          <input type="hidden" name="key" value="{{ key }}">
          <button class="btn btn-blue" type="submit">📥 Fetch Memes Now</button>
        </form>
        <small>Lädt ZIP von deiner Dropbox / URL und cached die Memes im Worker.</small>
        <hr>
        <form method="post" action="{{ url_for('update_meme_settings', key=key) }}">
          <input type="hidden" name="key" value="{{ key }}">
          <label>
            <input type="checkbox" name="auto_meme_mode" value="1" {% if auto_meme_mode=='1' %}checked{% endif %}>
            Auto Meme Mode aktiv (smart Memes in Replies)
          </label>
          <button class="btn btn-mint" type="submit">Save Meme Settings</button>
        </form>
        <small>Wenn deaktiviert, sendet der Bot überwiegend Text (oder nur Basis-Memes, je nach Code).</small>
      </div>
    </div>
  </div>

  <!-- ROW 4: TARGETS / BOOST -->
  <div class="row">
    <div class="col">
      <div class="card">
        <h2>Targets / KOLs</h2>
        <form method="post" action="{{ url_for('update_targets', key=key) }}">
          <input type="hidden" name="key" value="{{ key }}">
          <label>Target User IDs (eine pro Zeile)</label>
          <textarea name="targets_text">{% for t in targets %}{{ t }}
{% endfor %}</textarea>
          <button class="btn btn-blue" type="submit">Save Target IDs</button>
        </form>
        <hr>
        <h3>Handle → ID Converter</h3>
        <form method="post" action="{{ url_for('convert_handle', key=key) }}">
          <input type="hidden" name="key" value="{{ key }}">
          <label>X Handle</label>
          <input type="text" name="handle" placeholder="@username">
          <button class="btn btn-orange" type="submit">Convert</button>
        </form>
        {% if request.args.get('conv_handle') %}
          <p style="margin-top:6px;">
            <small>Ergebnis:</small><br>
            <code>{{ request.args.get('conv_handle') }}</code> → <strong>{{ request.args.get('conv_id') }}</strong>
          </p>
        {% endif %}
        <small>Nutze das, um saubere KOL-Listen in TARGET_IDS zu pflegen.</small>
      </div>
    </div>

    <div class="col">
      <div class="card">
        <h2>Boost Mode</h2>
        <p style="font-size:0.85rem; margin-bottom:8px;">
          Steuert, wie aggressiv der Bot bei hoher Aktivität antwortet.
        </p>
        <form method="post" action="{{ url_for('update_boost', key=key) }}">
          <input type="hidden" name="key" value="{{ key }}">
          <label>Boost Enabled</label>
          <select name="boost_enabled">
            <option value="1" {% if boost_enabled=='1' %}selected{% endif %}>ON</option>
            <option value="0" {% if boost_enabled=='0' %}selected{% endif %}>OFF</option>
          </select>
          <label>Boost Cooldown (Sekunden)</label>
          <input type="text" name="boost_cooldown" value="{{ boost_cooldown }}">
          <label>Boost Dauer (Sekunden)</label>
          <input type="text" name="boost_duration" value="{{ boost_duration }}">
          <button class="btn btn-mint" type="submit">Save Boost Settings</button>
        </form>
        <small>Empfehlung: normal 6s, Boost 3s, Dauer ~600s. Auto-Boost wird im Bot-Code entschieden.</small>
      </div>
    </div>
  </div>

  <!-- ROW 5: STATS + STATE -->
  <div class="row">
    <div class="col">
      <div class="card">
        <h2>Daily Activity</h2>
        <p style="font-size:0.9rem;">
          <strong>Date (UTC):</strong> {{ stats_date or 'n/a' }}
        </p>
        <div class="stat-grid">
          <div>
            <div class="stat-item-title">Replies total</div>
            <div class="stat-item-value">{{ stats_total }}</div>
          </div>
          <div>
            <div class="stat-item-title">Mentions replied</div>
            <div class="stat-item-value">{{ stats_mens }}</div>
          </div>
          <div>
            <div class="stat-item-title">KOL replies</div>
            <div class="stat-item-value">{{ stats_kol }}</div>
          </div>
          <div>
            <div class="stat-item-title">Memes used</div>
            <div class="stat-item-value">{{ stats_memes }}</div>
          </div>
        </div>
        <small>Diese Werte werden vom Worker in Config Vars geschrieben und bei Tageswechsel resettet.</small>
      </div>
    </div>

    <div class="col">
      <div class="card">
        <h2>State / Seen IDs</h2>
        <p style="font-size:0.9rem;">
          <strong>STATE_SEEN_IDS:</strong> {{ seen_count }} IDs
        </p>
        <small>Gesehenen Tweets, damit der Bot nicht doppelt antwortet. Voller Inhalt in Heroku Config Vars.</small>
      </div>
    </div>
  </div>

  <!-- ROW 6: REPLY SIMULATOR -->
  <div class="card">
    <h2>Reply Simulator (Grok Preview)</h2>
    <p style="font-size:0.9rem; margin-bottom:8px;">
      Teste, wie Lenny antworten würde – ohne X API Limit.
    </p>
    <form method="post" action="{{ url_for('simulate_reply', key=key) }}">
      <input type="hidden" name="key" value="{{ key }}">
      <label>Beispiel-Tweet:</label>
      <textarea name="sample_text" placeholder="@{{ bot_handle }} what do you think about this pump?"></textarea>
      <button class="btn btn-mint" type="submit">Simulate Reply</button>
    </form>
    {% if preview_text %}
      <h3>Preview</h3>
      <pre>{{ preview_text }}</pre>
    {% endif %}
    <small>Nutze den gleichen System-Prompt & Tone wie der echte Bot.</small>
  </div>

</div>
</body>
</html>
    """

    return render_template_string(
        template,
        key=key,
        app_name=HEROKU_APP_NAME,
        bot_handle=BOT_HANDLE,
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
        preview_text=preview_text,
    )


# -----------------------------------------------------
# ROUTES — MAIN
# -----------------------------------------------------
@app.route("/")
def index():
    require_key()
    preview = request.args.get("preview")
    return render_dashboard(preview_text=preview)


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
# ROUTES — TARGETS / KOL
# -----------------------------------------------------
@app.route("/update_targets", methods=["POST"])
def update_targets():
    require_key()
    text = (request.form.get("targets_text", "") or "").strip()
    ids = []
    for line in text.splitlines():
        clean = line.strip()
        if clean:
            ids.append(clean)
    csv_value = ",".join(ids)
    heroku_set_config({"TARGET_IDS": csv_value})
    key = request.args.get("key")
    return redirect(url_for("index", key=key))


@app.route("/convert_handle", methods=["POST"])
def convert_handle():
    require_key()
    handle = (request.form.get("handle", "") or "").strip()
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
        data = r.json() or {}
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

    def cb(name: str) -> str:
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
        "time_to_live": 300,
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
    cooldown = (request.form.get("boost_cooldown", "") or "").strip() or "3"
    duration = (request.form.get("boost_duration", "") or "").strip() or "600"

    if not cooldown.isdigit():
        cooldown = "3"
    if not duration.isdigit():
        duration = "600"

    patch = {
        "BOOST_ENABLED": enabled,
        "BOOST_COOLDOWN_S": cooldown,
        "BOOST_DURATION_S": duration,
    }
    heroku_set_config(patch)
    key = request.args.get("key")
    return redirect(url_for("index", key=key))


# -----------------------------------------------------
# ROUTES — DAILY POST TRIGGER
# -----------------------------------------------------
@app.route("/daily_post_now", methods=["POST"])
def trigger_daily_post():
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

    key = request.args.get("key")
    return redirect(url_for("index", key=key))


# -----------------------------------------------------
# ROUTES — REPLY SIMULATOR
# -----------------------------------------------------
@app.route("/simulate_reply", methods=["POST"])
def simulate_reply():
    require_key()
    sample = (request.form.get("sample_text", "") or "").strip()
    key = request.args.get("key")
    if not sample:
        return redirect(url_for("index", key=key))

    preview = grok_preview(sample)
    return render_dashboard(preview_text=preview)


# -----------------------------------------------------
# START SERVER
# -----------------------------------------------------
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=True,
    )
