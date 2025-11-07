# Lenny Bot — Heroku 24/7 (with Memes)

This repo is ready to deploy as a **Heroku worker**. It includes meme support:
- 30% chance to attach a random meme on replies
- Daily post attaches a meme only if 24h change > +1%

## 1) Install tools
- Git: https://git-scm.com/downloads
- Heroku CLI: https://devcenter.heroku.com/articles/heroku-cli

## 2) Put your memes
Place JPG/PNG/GIF files (<=5MB each) into the `memes/` folder.

## 3) Create the Heroku app
```bash
heroku login
heroku create lennyface-bot
```

## 4) Set config vars (NEVER commit your real .env)
```bash
heroku config:set X_BEARER_TOKEN=... X_API_KEY=... X_API_SECRET=...
heroku config:set X_ACCESS_TOKEN=... X_ACCESS_SECRET=...
heroku config:set TARGET_IDS=1762150082600685572,1622243071806128131,1470958472409792515,1729864554296029184,1509239489021030405,2728708501
heroku config:set LINE_MODE=llm GROK_BASE_URL=https://api.x.ai GROK_API_KEY=... GROK_MODEL=grok-3
heroku config:set ONLY_ORIGINAL=1 REPLY_PROBABILITY=1.0 DEX_REPLY_PROB=0.5
heroku config:set COOLDOWN_S=300 MAX_REPLIES_PER_KOL_PER_DAY=3
heroku config:set LOOP_SLEEP_SECONDS=240 PER_KOL_MIN_POLL_S=1200 READ_COOLDOWN_S=6
heroku config:set AUTO_TUNE=1 TUNE_BASE_LOOP_S=240 TUNE_MIN_LOOP_S=120 TUNE_MAX_LOOP_S=900
heroku config:set TUNE_MULTIPLIER=1.7 TUNE_COOLDOWN_LOOPS=3 TUNE_STEP_DOWN=0.8 TUNE_POLL_BUMP_S=180 TUNE_POLL_RELAX_S=90
heroku config:set DAILY_POST_ENABLED=1 DAILY_POST_UTC_HOUR=12 DAILY_POST_MINUTE=0
heroku config:set MEME_PROBABILITY=0.3 DAILY_MEME_THRESHOLD_PCT=1.0
```

## 5) Deploy
```bash
git init
git add .
git commit -m "Lenny bot heroku memes starter"
git branch -M main
heroku git:remote -a lennyface-bot
git push heroku main
```

(If your Heroku stack still uses `master`, push to master:)
```bash
git push heroku master
```

## 6) Run the worker
```bash
heroku ps:scale worker=1
```

## 7) Watch logs
```bash
heroku logs --tail
```

Notes:
- Heroku filesystem is ephemeral. Memes committed in the repo will be available in the slug, but uploaded/changed at runtime won't persist across restarts. For dynamic memes, use a remote source later.
