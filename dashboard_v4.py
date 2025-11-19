import os
import json
import requests
from flask import Flask, request, redirect, url_for, render_template_string, abort

app = Flask(__name__)

# ================================
# CONFIG
# ================================
DASHBOARD_KEY   = os.environ.get("DASHBOARD_KEY", "LennySuper420")
HEROKU_APP_NAME = os.environ.get("HEROKU_APP_NAME", "")
HEROKU_API_KEY  = os.environ.get("HEROKU_API_KEY", "")

# Token / DEX Stats
LENNY_TOKEN_CA = os.environ.get("LENNY_TOKEN_CA", "").strip()
DEX_TOKEN_URL  = os.environ.get("DEX_TOKEN_URL", "").strip()

# Grok Settings
GROK_API_KEY             = os.environ.get("GROK_API_KEY", "")
GROK_BASE_URL            = os.environ.get("GROK_BASE_URL", "https://api.x.ai")
GROK_MODEL               = os.environ.get("GROK_MODEL", "grok-3")
GROK_TONE                = os.environ.get("GROK_TONE", "normal")
GROK_FORCE_ENGLISH       = os.environ.get("GROK_FORCE_ENGLISH", "1")
GROK_ALWAYS_SHILL_LENNY  = os.environ.get("GROK_ALWAYS_SHILL_LENNY", "1")
GROK_EXTRA_PROMPT        = os.environ.get("GROK_EXTRA_PROMPT", "")

BOT_HANDLE = os.environ.get("BOT_HANDLE", "lennyface_bot").lstrip("@")

# Command Toggles
ENABLE_HELP  = os.environ.get("ENABLE_HELP", "1")
ENABLE_LORE  = os.environ.get("ENABLE_LORE", "1")
ENABLE_STATS = os.environ.get("ENABLE_STATS", "1")
ENABLE_ALPHA = os.environ.get("ENABLE_ALPHA", "1")
ENABLE_GM    = os.environ.get("ENABLE_GM", "1")
ENABLE_ROAST = os.environ.get("ENABLE_ROAST", "1")

# Meme Settings
AUTO_MEME_MODE          = os.environ.get("AUTO_MEME_MODE", "1")
MEME_PROBABILITY        = os.environ.get("MEME_PROBABILITY", "0.3")
AUTO_MEME_EXTRA_CHANCE  = os.environ.get("AUTO_MEME_EXTRA_CHANCE", "0.5")
FETCH_MEMES_URL         = os.environ.get("FETCH_MEMES_URL", "")

# Boost Settings
BOOST_ENABLED     = os.environ.get("BOOST_ENABLED", "1")
BOOST_COOLDOWN_S  = os.environ.get("BOOST_COOLDOWN_S", "3")
BOOST_DURATION_S  = os.environ.get("BOOST_DURATION_S", "600")

# Bot Timing
READ_COOLDOWN_S  = os.environ.get("READ_COOLDOWN_S", "6")
LOOP_SLEEP_S     = os.environ.get("LOOP_SLEEP_SECONDS", "240")


# ================================
# HELPER FUNCTIONS
# ================================
def require_key():
    key = request.args.get("key") or request.form.get("key")
    if key != DASHBOARD_KEY:
        abort(401)


def heroku_headers():
    if not HEROKU_API_KEY:
        raise RuntimeError("HEROKU_API_KEY not set")
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
    r = requests.patch(url, headers=heroku_headers(),
                       data=json.dumps(changes), timeout=10)
    r.raise_for_status()
    return r.json()


def parse_ids(csv: str):
    if not csv:
        return []
    return [x.strip() for x in csv.split(",") if x.strip()]


# ================================
# MARKET DATA (DEX)
# ================================
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
        mc    = float(p.get("fdv") or p.get("marketCap") or 0)
        vol24 = float(
            (p.get("volume") or {}).get("h24")
            or p.get("volume24h")
            or 0
        )

        # Manche DEX-APIs haben ein Change-Feld, andere nicht → safe default
        change_raw = p.get("priceChange24h") or p.get("priceChangeH24") or 0
        try:
            change = float(change_raw)
        except Exception:
            change = 0.0

        def fmt(n):
            if n >= 1_000_000_000:
                return f"{n/1_000_000_000:.2f}B"
            if n >= 1_000_000:
                return f"{n/1_000_000:.2f}M"
            if n >= 1_000:
                return f"{n/1_000:.2f}K"
            return f"{n:.4f}"

        return {
            "price": f"${price:.6f}" if price < 1 else f"${price:.4f}",
            "mc": fmt(mc),
            "vol": fmt(vol24),
            "change": change,
            "dex": p.get("dexId", ""),
            "url": p.get("url", ""),
        }
    except Exception:
        return None


# ================================
# GLOBAL STATS (BTC / SOL)
# ================================
def fetch_global_stats():
    url = (
        "https://api.coingecko.com/api/v3/simple/price"
        "?ids=bitcoin,solana&vs_currencies=usd&include_24hr_change=true"
    )
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()

        def f(n):
            if n >= 1_000_000:
                return f"${n/1_000_000:.2f}M"
            if n >= 1_000:
                return f"${n/1_000:.2f}K"
            return f"${n:.2f}"

        btc = data.get("bitcoin")
        sol = data.get("solana")

        return {
            "btc_price": f(float(btc["usd"])) if btc else None,
            "btc_change": f"{btc['usd_24h_change']:+.2f}%" if btc else None,
            "sol_price": f(float(sol["usd"])) if sol else None,
            "sol_change": f"{sol['usd_24h_change']:+.2f}%" if sol else None,
        }
    except Exception:
        return None


# ================================
# DASHBOARD HTML – V4 (Cyber Mint)
# ================================
def render_dashboard(preview_text=None):

    cfg = heroku_get_config()
    key = request.args.get("key", "")

    # Live Config
    state_seen_ids = parse_ids(cfg.get("STATE_SEEN_IDS", ""))
    targets        = parse_ids(cfg.get("TARGET_IDS", ""))

    bot_paused     = cfg.get("BOT_PAUSED", "0")

    lenny_stats    = fetch_lenny_stats()
    global_stats   = fetch_global_stats()

    # Stats
    stats_date  = cfg.get("STATS_DATE", "")
    stats_total = cfg.get("STATS_REPLIES_TOTAL", "0")
    stats_mens  = cfg.get("STATS_REPLIES_MENTIONS", "0")
    stats_kol   = cfg.get("STATS_REPLIES_KOL", "0")
    stats_memes = cfg.get("STATS_MEMES_USED", "0")

    template = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Lenny Bot Dashboard v4 – Cyber Mint</title>

<style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;600&family=Inter:wght@300;400;600&display=swap');

    :root {
        --bg: #020617;
        --bg-alt: #020a13;
        --fg: #e2e8f0;
        --card-bg: rgba(15, 23, 42, 0.88);
        --accent: #7CF5E3;
        --accent-dark: #55C8B8;
        --accent-glow: rgba(124,245,227,0.45);
        --danger: #ff4d4d;
        --success: #4dff8c;
        --border-subtle: rgba(148, 163, 184, 0.4);
    }

    [data-theme="mint"] {
        --bg: #f8fffe;
        --bg-alt: #e6fffb;
        --fg: #020617;
        --card-bg: rgba(255,255,255,0.9);
        --accent: #00bfa5;
        --accent-dark: #008f7a;
        --accent-glow: rgba(0,191,165,0.4);
        --border-subtle: rgba(15, 23, 42, 0.2);
    }

    * {
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }

    body {
        background: radial-gradient(circle at top, var(--bg-alt) 0, var(--bg) 45%, #020617 100%);
        color: var(--fg);
        font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
        transition: background 0.4s ease, color 0.4s ease;
    }

    /* NAVBAR */
    .nav {
        width: 100%;
        padding: 12px 26px;
        background: rgba(15,23,42,0.96);
        border-bottom: 1px solid rgba(148,163,184,0.4);
        display: flex;
        align-items: center;
        justify-content: space-between;
        position: sticky;
        top: 0;
        z-index: 999;
        backdrop-filter: blur(12px);
    }
    .nav-left {
        display: flex;
        align-items: center;
        gap: 14px;
    }
    .nav-logo {
        font-family: 'JetBrains Mono', monospace;
        font-size: 1.2rem;
        color: var(--accent);
    }
    .nav-links a {
        margin-right: 18px;
        font-size: 0.9rem;
        font-weight: 500;
        text-decoration: none;
        color: #94a3b8;
        transition: color 0.2s;
    }
    .nav-links a:hover {
        color: var(--accent);
    }
    .theme-toggle {
        padding: 8px 14px;
        border-radius: 999px;
        border: 1px solid rgba(148,163,184,0.6);
        background: rgba(15,23,42,0.8);
        color: var(--fg);
        font-size: 0.82rem;
        cursor: pointer;
        display: flex;
        align-items: center;
        gap: 6px;
    }

    .wrap {
        max-width: 1250px;
        margin: 24px auto 48px;
        padding: 0 16px;
    }

    .ascii {
        font-family: 'JetBrains Mono', monospace;
        color: var(--accent);
        white-space: pre;
        font-size: 0.9rem;
        text-shadow: 0 0 12px var(--accent-glow);
        margin-bottom: 16px;
    }

    .headline {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 18px;
    }

    .headline-left {
        display: flex;
        align-items: center;
        gap: 10px;
    }

    .face {
        font-size: 1.7rem;
    }

    h1 {
        color: var(--accent);
        font-size: 1.45rem;
        text-shadow: 0 0 10px rgba(124,245,227,0.35);
    }

    h2 {
        color: var(--accent);
        margin-bottom: 8px;
        font-size: 1.05rem;
        text-shadow: 0 0 8px rgba(124,245,227,0.3);
    }

    h3 {
        color: #cbd5f5;
        margin-bottom: 6px;
        font-size: 0.95rem;
    }

    .card {
        background: var(--card-bg);
        border: 1px solid rgba(124,245,227,0.2);
        border-radius: 14px;
        padding: 20px 22px;
        margin-bottom: 22px;
        box-shadow:
            0 0 24px rgba(15,23,42,0.9),
            0 0 26px rgba(56,189,248,0.12);
    }

    .row {
        display: flex;
        gap: 18px;
        flex-wrap: wrap;
    }
    .col {
        flex: 1;
        min-width: 330px;
    }

    .stat {
        font-size: 0.9rem;
        margin: 3px 0;
    }

    .pill {
        display: inline-block;
        padding: 4px 11px;
        border-radius: 999px;
        background: rgba(15,23,42,0.9);
        border: 1px solid rgba(148,163,184,0.75);
        color: #e5e7eb;
        font-size: 0.78rem;
        margin-right: 6px;
    }

    .pill-accent {
        border-color: var(--accent);
        color: var(--accent);
        background: rgba(56,189,248,0.08);
    }

    .btn {
        display: inline-block;
        margin-top: 10px;
        padding: 9px 16px;
        border-radius: 10px;
        border: none;
        background: linear-gradient(145deg, var(--accent) 0%, var(--accent-dark) 100%);
        color: #020617;
        font-weight: 600;
        cursor: pointer;
        font-size: 0.9rem;
        box-shadow: 0 0 14px var(--accent-glow);
        transition: 0.18s ease;
    }

    .btn:hover {
        transform: translateY(-1px) scale(1.02);
        box-shadow: 0 0 22px var(--accent-glow);
    }

    .btn-dark {
        background: #020617;
        color: var(--accent);
        border: 1px solid rgba(148,163,184,0.7);
        box-shadow: none;
    }

    input, textarea, select {
        width: 100%;
        padding: 7px 9px;
        margin-top: 6px;
        margin-bottom: 8px;
        border-radius: 8px;
        background: rgba(15,23,42,0.95);
        border: 1px solid var(--border-subtle);
        color: var(--fg);
        font-size: 0.86rem;
    }

    textarea {
        min-height: 70px;
        font-family: "JetBrains Mono", monospace;
        font-size: 0.8rem;
    }

    small {
        color: #9ca3af;
        font-size: 0.78rem;
    }

    pre {
        background: rgba(15,23,42,0.95);
        border-radius: 10px;
        padding: 10px 12px;
        font-family: "JetBrains Mono", monospace;
        font-size: 0.8rem;
        color: #e5f2ff;
        overflow-x: auto;
    }

    a {
        color: var(--accent);
        text-decoration: none;
    }
    a:hover {
        text-decoration: underline;
    }

    .subgrid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(130px,1fr));
        gap: 10px;
        margin-top: 6px;
    }

    .sub-pill-title {
        font-size: 0.7rem;
        color: #9ca3af;
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }

    .sub-pill-value {
        font-size: 0.98rem;
        font-weight: 600;
        margin-top: 2px;
        color: var(--fg);
    }

    .badge-pos {
        color: var(--success);
        font-weight: 600;
    }
    .badge-neg {
        color: var(--danger);
        font-weight: 600;
    }

</style>

</head>
<body>

<div class="nav">
    <div class="nav-left">
        <div class="nav-logo">( ͡° ͜ʖ ͡°)</div>
        <div class="nav-links">
            <a href="#">Dashboard</a>
            <a href="#">Logs</a>
            <a href="#">Settings</a>
        </div>
    </div>
    <button class="theme-toggle" onclick="toggleTheme()">
        <span>Theme</span>
        <span>☯</span>
    </button>
</div>

<div class="wrap">

<pre class="ascii">
  ( ͡° ͜ʖ ͡°)
  L E N N Y   B O T   D A S H B O A R D   V4
</pre>

<div class="headline">
    <div class="headline-left">
        <div class="face">( ͡° ͜ʖ ͡°)</div>
        <h1>Lenny Bot Dashboard v4 – Cyber Mint</h1>
    </div>
    <div>
        <span class="pill pill-accent">App: {{ HEROKU_APP_NAME or 'n/a' }}</span>
        <span class="pill">Handle: @{{ BOT_HANDLE }}</span>
    </div>
</div>

<!-- ==========================
     BOT STATUS + GLOBAL
=========================== -->
<div class="row">
    <div class="card col">
        <h2>Bot Status</h2>
        <p class="stat">
            <span class="pill">Seen IDs: {{ state_seen_ids|length }}</span>
            <span class="pill">Targets: {{ targets|length }}</span>
            <span class="pill">Paused: {{ 'YES' if bot_paused=='1' else 'NO' }}</span>
        </p>

        <form method="post" action="{{ url_for('update_bot_state', key=key) }}">
            <input type="hidden" name="key" value="{{ key }}">
            <label>Bot Control:</label>
            <select name="bot_paused">
                <option value="0" {% if bot_paused=='0' %}selected{% endif %}>Running</option>
                <option value="1" {% if bot_paused=='1' %}selected{% endif %}>Paused</option>
            </select>
            <button class="btn" type="submit">Save</button>
            <small>Wenn pausiert → Worker schläft komplett.</small>
        </form>
    </div>

    <div class="card col">
        <h2>Global Market</h2>
        {% if global_stats %}
            <p class="stat">
                <b>BTC:</b> {{ global_stats.btc_price }}
                (<span class="{{ 'badge-pos' if global_stats.btc_change.startswith('+') else 'badge-neg' }}">
                    {{ global_stats.btc_change }}
                </span>)
            </p>
            <p class="stat">
                <b>SOL:</b> {{ global_stats.sol_price }}
                (<span class="{{ 'badge-pos' if global_stats.sol_change.startswith('+') else 'badge-neg' }}">
                    {{ global_stats.sol_change }}
                </span>)
            </p>
        {% else %}
            <p class="stat">Keine Daten (CoinGecko Limit oder Netzwerk-Fehler).</p>
        {% endif %}
        <small>Live von CoinGecko.</small>
    </div>
</div>

<!-- ==========================
     LENNY MARKET STATS
=========================== -->
<div class="card">
    <h2>$LENNY Market Stats</h2>
    {% if lenny_stats %}
        <p class="stat"><b>Price:</b> {{ lenny_stats.price }}</p>
        <p class="stat"><b>Market Cap:</b> {{ lenny_stats.mc }}</p>
        <p class="stat"><b>24h Volume:</b> {{ lenny_stats.vol }}</p>
        <p class="stat">
            <b>24h Change:</b>
            <span class="{{ 'badge-pos' if lenny_stats.change > 0 else 'badge-neg' }}">
                {{ "%.2f"|format(lenny_stats.change) }}%
            </span>
        </p>

        {% if lenny_stats.url %}
            <p class="stat"><b>Dex:</b>
                <a href="{{ lenny_stats.url }}" target="_blank">{{ lenny_stats.dex or 'Dexscreener' }}</a>
            </p>
        {% endif %}
    {% else %}
        <p class="stat">Keine DEX Daten – check <code>DEX_TOKEN_URL</code> oder <code>LENNY_TOKEN_CA</code>.</p>
    {% endif %}
</div>

<!-- ==========================
     TARGETS / KOL SYSTEM + GROK
=========================== -->
<div class="row">
    <div class="card col">
        <h2>Targets (KOLs)</h2>
        <form method="post" action="{{ url_for('update_targets', key=key) }}">
            <input type="hidden" name="key" value="{{ key }}">
            <label>Aktuelle TARGET_IDS (eine pro Zeile):</label>
            <textarea name="targets_text">{% for t in targets %}{{ t }}
{% endfor %}</textarea>
            <button class="btn" type="submit">Save Targets</button>
            <small>Wird in TARGET_IDS als Komma-Liste gespeichert.</small>
        </form>

        <hr style="border-color: rgba(148,163,184,0.3); margin: 12px 0;">

        <h3>Handle → ID Converter</h3>
        <form method="post" action="{{ url_for('convert_handle', key=key) }}">
            <input type="hidden" name="key" value="{{ key }}">
            <label>X Handle:</label>
            <input type="text" name="handle" placeholder="@username">
            <button class="btn" type="submit">Convert</button>
        </form>

        {% if request.args.get('conv_handle') %}
        <p class="stat">
            <b>Handle:</b> {{ request.args.get('conv_handle') }}<br>
            <b>User ID:</b> {{ request.args.get('conv_id') }}
        </p>
        {% endif %}
    </div>

    <div class="card col">
        <h2>Grok Settings</h2>
        <form method="post" action="{{ url_for('update_grok', key=key) }}">
            <input type="hidden" name="key" value="{{ key }}">

            <label>GROK Tone:</label>
            <select name="grok_tone">
                <option value="soft"   {% if GROK_TONE=='soft' %}selected{% endif %}>Soft 😇</option>
                <option value="normal" {% if GROK_TONE=='normal' %}selected{% endif %}>Normal 😎</option>
                <option value="spicy"  {% if GROK_TONE=='spicy' %}selected{% endif %}>Spicy 😏</option>
                <option value="savage" {% if GROK_TONE=='savage' %}selected{% endif %}>Savage 🤬</option>
            </select>

            <label>
                <input type="checkbox" name="grok_force_en" value="1"
                    {% if GROK_FORCE_ENGLISH=='1' %}checked{% endif %}>
                Always respond in English
            </label>

            <label>
                <input type="checkbox" name="grok_always_lenny" value="1"
                    {% if GROK_ALWAYS_SHILL_LENNY=='1' %}checked{% endif %}>
                Always shill $LENNY
            </label>

            <label>Extra Prompt:</label>
            <textarea name="grok_extra">{{ GROK_EXTRA_PROMPT }}</textarea>

            <button class="btn" type="submit">Save Grok Settings</button>
        </form>
    </div>
</div>

<!-- ==========================
     COMMAND TOGGLES
=========================== -->
<div class="card">
    <h2>Command Toggles</h2>
    <form method="post" action="{{ url_for('update_command_toggles', key=key) }}">
        <input type="hidden" name="key" value="{{ key }}">

        <label><input type="checkbox" name="enable_help" value="1"
            {% if ENABLE_HELP=='1' %}checked{% endif %}> help command</label><br>

        <label><input type="checkbox" name="enable_lore" value="1"
            {% if ENABLE_LORE=='1' %}checked{% endif %}> lore command</label><br>

        <label><input type="checkbox" name="enable_stats" value="1"
            {% if ENABLE_STATS=='1' %}checked{% endif %}> stats/mc/price commands</label><br>

        <label><input type="checkbox" name="enable_alpha" value="1"
            {% if ENABLE_ALPHA=='1' %}checked{% endif %}> alpha command</label><br>

        <label><input type="checkbox" name="enable_gm" value="1"
            {% if ENABLE_GM=='1' %}checked{% endif %}> gm replies</label><br>

        <label><input type="checkbox" name="enable_roast" value="1"
            {% if ENABLE_ROAST=='1' %}checked{% endif %}> roast replies</label><br>

        <button class="btn" type="submit">Save Command Settings</button>
    </form>
</div>

<!-- ==========================
     MEME SETTINGS + BOOST
=========================== -->
<div class="row">

    <div class="card col">
        <h2>Meme System</h2>

        <p class="stat"><b>FETCH_MEMES_URL:</b><br>
            <code>{{ FETCH_MEMES_URL or 'not set' }}</code></p>

        <form method="post" action="{{ url_for('trigger_fetch_memes', key=key) }}">
            <input type="hidden" name="key" value="{{ key }}">
            <button class="btn" type="submit">Reload Memes</button>
        </form>

        <hr style="border-color: rgba(148,163,184,0.3); margin: 12px 0;">

        <form method="post" action="{{ url_for('update_meme_settings', key=key) }}">
            <input type="hidden" name="key" value="{{ key }}">

            <label>Auto Meme Mode:</label>
            <select name="auto_meme_mode">
                <option value="1" {% if AUTO_MEME_MODE=='1' %}selected{% endif %}>ON</option>
                <option value="0" {% if AUTO_MEME_MODE=='0' %}selected{% endif %}>OFF</option>
            </select>

            <label>Meme Probability (0–1):</label>
            <input type="text" name="meme_probability" value="{{ MEME_PROBABILITY }}">

            <label>Extra Chance on Meme Keywords (0–1):</label>
            <input type="text" name="extra_chance" value="{{ AUTO_MEME_EXTRA_CHANCE }}">

            <button class="btn" type="submit">Save Meme Settings</button>
        </form>
    </div>

    <div class="card col">
        <h2>Boost Mode</h2>

        <p class="stat">
            <span class="pill pill-accent">Boost: {{ 'ON' if BOOST_ENABLED=='1' else 'OFF' }}</span>
            <span class="pill">Cooldown: {{ BOOST_COOLDOWN_S }}s</span>
            <span class="pill">Duration: {{ BOOST_DURATION_S }}s</span>
        </p>

        <form method="post" action="{{ url_for('update_boost', key=key) }}">
            <input type="hidden" name="key" value="{{ key }}">

            <label>Boost Enabled:</label>
            <select name="boost_enabled">
                <option value="1" {% if BOOST_ENABLED=='1' %}selected{% endif %}>ON</option>
                <option value="0" {% if BOOST_ENABLED=='0' %}selected{% endif %}>OFF</option>
            </select>

            <label>Boost Cooldown (seconds):</label>
            <input type="text" name="boost_cooldown" value="{{ BOOST_COOLDOWN_S }}">

            <label>Boost Duration (seconds):</label>
            <input type="text" name="boost_duration" value="{{ BOOST_DURATION_S }}">

            <button class="btn" type="submit">Save Boost Settings</button>
        </form>
        <small>Empfehlung: normal ~6s, Boost ~3s für 600s.</small>
    </div>
</div>

<!-- ==========================
     STATE / SEEN IDS + STATS
=========================== -->
<div class="row">

    <div class="card col">
        <h2>State / Seen IDs</h2>
        <p class="stat">Total Seen: {{ state_seen_ids|length }}</p>

        <form method="post" action="{{ url_for('trigger_seed_backup', key=key) }}">
            <input type="hidden" name="key" value="{{ key }}">
            <button class="btn btn-dark" type="submit">🔄 Seed + Backup STATE</button>
        </form>

        <small>
            Führt <code>seed_and_backup_env.py</code> aus:<br>
            • synchronisiert Seen-IDs<br>
            • schreibt sie in STATE_SEEN_IDS<br>
            • verhindert doppelte Antworten.
        </small>
    </div>

    <div class="card col">
        <h2>Daily Activity / Stats</h2>
        <p class="stat"><b>Date (UTC):</b> {{ stats_date or 'n/a' }}</p>

        <div class="subgrid">
            <div>
                <div class="sub-pill-title">Replies total</div>
                <div class="sub-pill-value">{{ stats_total }}</div>
            </div>
            <div>
                <div class="sub-pill-title">Mentions replied</div>
                <div class="sub-pill-value">{{ stats_mens }}</div>
            </div>
            <div>
                <div class="sub-pill-title">KOL replies</div>
                <div class="sub-pill-value">{{ stats_kol }}</div>
            </div>
            <div>
                <div class="sub-pill-title">Memes used</div>
                <div class="sub-pill-value">{{ stats_memes }}</div>
            </div>
        </div>

        <small>Werte kommen aus den Config Vars, die der Bot schreibt.</small>
    </div>
</div>

<!-- ==========================
     DAILY POST
=========================== -->
<div class="card">
    <h2>$LENNY Daily Post</h2>
    <p class="stat">
        Starte einen manuellen, einmaligen $LENNY-Post über einen One-off Dyno.
    </p>
    <form method="post" action="{{ url_for('trigger_daily_post', key=key) }}">
        <input type="hidden" name="key" value="{{ key }}">
        <button class="btn" type="submit">🚀 Daily Post jetzt senden</button>
    </form>
    <small>Startet <code>python daily_post_now.py</code> in einem One-off Dyno.</small>
</div>

<!-- ==========================
     REPLY SIMULATOR
=========================== -->
<div class="card">
    <h2>Reply Simulator (Grok Preview)</h2>

    <form method="post" action="{{ url_for('simulate_reply', key=key) }}">
        <input type="hidden" name="key" value="{{ key }}">

        <label>Beispiel-Tweet:</label>
        <textarea name="sample_text" placeholder="@{{ BOT_HANDLE }} what do you think about this pump?"></textarea>

        <button class="btn" type="submit">Simulate Reply</button>
    </form>

    {% if preview_text %}
        <h3>Preview:</h3>
        <pre>{{ preview_text }}</pre>
    {% endif %}

    <small>Nutze Grok mit deinen aktuellen Einstellungen, ohne X-API-Limit.</small>
</div>

</div> <!-- .wrap -->

<script>
function toggleTheme() {
    const body = document.body;
    if (body.getAttribute("data-theme") === "mint") {
        body.removeAttribute("data-theme");
        localStorage.setItem("theme", "dark");
    } else {
        body.setAttribute("data-theme", "mint");
        localStorage.setItem("theme", "mint");
    }
}

// Theme aus localStorage beim Laden setzen
(function() {
    const saved = localStorage.getItem("theme");
    if (saved === "mint") {
        document.body.setAttribute("data-theme", "mint");
    }
})();
</script>

</body>
</html>
    """

    grok_tone        = cfg.get("GROK_TONE", GROK_TONE)
    grok_force_en    = cfg.get("GROK_FORCE_ENGLISH", GROK_FORCE_ENGLISH)
    grok_always_len  = cfg.get("GROK_ALWAYS_SHILL_LENNY", GROK_ALWAYS_SHILL_LENNY)
    grok_extra       = cfg.get("GROK_EXTRA_PROMPT", GROK_EXTRA_PROMPT)

    enable_help      = cfg.get("ENABLE_HELP", ENABLE_HELP)
    enable_lore      = cfg.get("ENABLE_LORE", ENABLE_LORE)
    enable_stats     = cfg.get("ENABLE_STATS", ENABLE_STATS)
    enable_alpha     = cfg.get("ENABLE_ALPHA", ENABLE_ALPHA)
    enable_gm        = cfg.get("ENABLE_GM", ENABLE_GM)
    enable_roast     = cfg.get("ENABLE_ROAST", ENABLE_ROAST)

    fetch_memes_url  = cfg.get("FETCH_MEMES_URL", FETCH_MEMES_URL)
    auto_meme_mode   = cfg.get("AUTO_MEME_MODE", AUTO_MEME_MODE)
    meme_prob        = cfg.get("MEME_PROBABILITY", MEME_PROBABILITY)
    extra_chance     = cfg.get("AUTO_MEME_EXTRA_CHANCE", AUTO_MEME_EXTRA_CHANCE)

    boost_enabled    = cfg.get("BOOST_ENABLED", BOOST_ENABLED)
    boost_cooldown   = cfg.get("BOOST_COOLDOWN_S", BOOST_COOLDOWN_S)
    boost_duration   = cfg.get("BOOST_DURATION_S", BOOST_DURATION_S)

    return render_template_string(
        template,
        key=key,
        state_seen_ids=state_seen_ids,
        targets=targets,
        bot_paused=bot_paused,
        lenny_stats=lenny_stats,
        global_stats=global_stats,
        stats_date=stats_date,
        stats_total=stats_total,
        stats_mens=stats_mens,
        stats_kol=stats_kol,
        stats_memes=stats_memes,
        GROK_TONE=grok_tone,
        GROK_FORCE_ENGLISH=grok_force_en,
        GROK_ALWAYS_SHILL_LENNY=grok_always_len,
        GROK_EXTRA_PROMPT=grok_extra,
        ENABLE_HELP=enable_help,
        ENABLE_LORE=enable_lore,
        ENABLE_STATS=enable_stats,
        ENABLE_ALPHA=enable_alpha,
        ENABLE_GM=enable_gm,
        ENABLE_ROAST=enable_roast,
        FETCH_MEMES_URL=fetch_memes_url,
        AUTO_MEME_MODE=auto_meme_mode,
        MEME_PROBABILITY=meme_prob,
        AUTO_MEME_EXTRA_CHANCE=extra_chance,
        BOOST_ENABLED=boost_enabled,
        BOOST_COOLDOWN_S=boost_cooldown,
        BOOST_DURATION_S=boost_duration,
        BOT_HANDLE=BOT_HANDLE,
        HEROKU_APP_NAME=HEROKU_APP_NAME,
        preview_text=preview_text,
    )


# ================================
# GROK PREVIEW HELPER
# ================================
def build_grok_preview_prompt():
    base = (
        "You are LENNY, a cheeky, degen-style shill bot for $LENNY. "
        "Your replies are short, punchy, funny and non-repetitive. "
        "No slurs, no real-life threats, keep it within social platform rules."
    )

    tone = GROK_TONE.lower() if GROK_TONE else "normal"
    if tone == "soft":
        base += " Keep the tone friendly and kind, low aggression."
    elif tone == "spicy":
        base += " You can be a bit edgy and teasing, but stay safe."
    elif tone == "savage":
        base += " You can be savage banter-style, but still no hate speech or slurs."

    if GROK_FORCE_ENGLISH == "1":
        base += " Always reply in English."

    if GROK_ALWAYS_SHILL_LENNY == "1":
        base += " Try to mention $LENNY when it fits naturally."

    extra = (GROK_EXTRA_PROMPT or "").strip()
    if extra:
        base += " Extra style instructions: " + extra

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
                {"role": "system", "content": build_grok_preview_prompt()},
                {
                    "role": "user",
                    "content": (
                        "Simulate how you would reply on X to this tweet. "
                        "Keep it under 220 characters. Tweet text: " + text[:280]
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


# ================================
# ROUTES
# ================================
@app.route("/")
def index():
    require_key()
    return render_dashboard(preview_text=None)


@app.route("/update_bot_state", methods=["POST"])
def update_bot_state():
    require_key()
    paused = request.form.get("bot_paused", "0")
    paused = "1" if paused == "1" else "0"
    heroku_set_config({"BOT_PAUSED": paused})
    key = request.args.get("key", "")
    return redirect(url_for("index", key=key))


@app.route("/update_targets", methods=["POST"])
def update_targets():
    require_key()
    text = request.form.get("targets_text", "") or ""
    ids = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            ids.append(line)
    csv_value = ",".join(ids)
    heroku_set_config({"TARGET_IDS": csv_value})
    key = request.args.get("key", "")
    return redirect(url_for("index", key=key))


@app.route("/convert_handle", methods=["POST"])
def convert_handle():
    require_key()
    handle = (request.form.get("handle", "") or "").strip()
    key = request.args.get("key", "")

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


@app.route("/update_grok", methods=["POST"])
def update_grok():
    require_key()
    tone = request.form.get("grok_tone", "normal")
    force_en = "1" if request.form.get("grok_force_en") == "1" else "0"
    always_lenny = "1" if request.form.get("grok_always_lenny") == "1" else "0"
    extra = request.form.get("grok_extra", "") or ""

    heroku_set_config({
        "GROK_TONE": tone,
        "GROK_FORCE_ENGLISH": force_en,
        "GROK_ALWAYS_SHILL_LENNY": always_lenny,
        "GROK_EXTRA_PROMPT": extra,
    })

    key = request.args.get("key", "")
    return redirect(url_for("index", key=key))


@app.route("/update_command_toggles", methods=["POST"])
def update_command_toggles():
    require_key()

    def cb(name: str) -> str:
        return "1" if request.form.get(name) == "1" else "0"

    patch = {
        "ENABLE_HELP":  cb("enable_help"),
        "ENABLE_LORE":  cb("enable_lore"),
        "ENABLE_STATS": cb("enable_stats"),
        "ENABLE_ALPHA": cb("enable_alpha"),
        "ENABLE_GM":    cb("enable_gm"),
        "ENABLE_ROAST": cb("enable_roast"),
    }
    heroku_set_config(patch)
    key = request.args.get("key", "")
    return redirect(url_for("index", key=key))


@app.route("/trigger_fetch_memes", methods=["POST"])
def trigger_fetch_memes():
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
    return redirect(url_for("index", key=key))


@app.route("/update_meme_settings", methods=["POST"])
def update_meme_settings():
    require_key()
    auto_mode = request.form.get("auto_meme_mode", "1")
    meme_prob = request.form.get("meme_probability", MEME_PROBABILITY) or MEME_PROBABILITY
    extra_chance = request.form.get("extra_chance", AUTO_MEME_EXTRA_CHANCE) or AUTO_MEME_EXTRA_CHANCE

    heroku_set_config({
        "AUTO_MEME_MODE": auto_mode,
        "MEME_PROBABILITY": meme_prob,
        "AUTO_MEME_EXTRA_CHANCE": extra_chance,
    })

    key = request.args.get("key", "")
    return redirect(url_for("index", key=key))


@app.route("/update_boost", methods=["POST"])
def update_boost():
    require_key()
    enabled   = request.form.get("boost_enabled", BOOST_ENABLED)
    cooldown  = request.form.get("boost_cooldown", BOOST_COOLDOWN_S) or BOOST_COOLDOWN_S
    duration  = request.form.get("boost_duration", BOOST_DURATION_S) or BOOST_DURATION_S

    if not cooldown.isdigit():
        cooldown = BOOST_COOLDOWN_S
    if not duration.isdigit():
        duration = BOOST_DURATION_S

    heroku_set_config({
        "BOOST_ENABLED": enabled,
        "BOOST_COOLDOWN_S": cooldown,
        "BOOST_DURATION_S": duration,
    })

    key = request.args.get("key", "")
    return redirect(url_for("index", key=key))


@app.route("/trigger_seed_backup", methods=["POST"])
def trigger_seed_backup():
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
    return redirect(url_for("index", key=key))


@app.route("/trigger_daily_post", methods=["POST"])
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
    key = request.args.get("key", "")
    return redirect(url_for("index", key=key))


@app.route("/simulate_reply", methods=["POST"])
def simulate_reply():
    require_key()
    sample = (request.form.get("sample_text", "") or "").strip()
    key = request.args.get("key", "")
    if not sample:
        return redirect(url_for("index", key=key))

    preview = grok_preview(sample)
    return render_dashboard(preview_text=preview)


# ================================
# MAIN
# ================================
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=True,
    )
