# Slavarr (Python rewrite) – Starter

This is a starter scaffold for a Discord bot that integrates with Radarr/Sonarr and a FastAPI webhook server.

## Features (initial)
- Discord bot using `discord.py` 2.x with slash commands
- `/movie add <query>`: searches Radarr and shows a select dropdown to add a movie
- SQLite with SQLAlchemy for per-user preferences (auto_subscribe, dm_instead)
- FastAPI webhook server on port **3001** (stub routes ready for Radarr/Sonarr events)
- Single-process startup that runs both the Discord gateway and the FastAPI server

## Quick start

1. Create `.env` from example:
   ```bash
   cp .env.example .env
   ```

2. Install dependencies (Python 3.11+ recommended):
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # on Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Run:
   ```bash
   python -m src.app.main
   ```

4. In Discord Developer Portal, add the bot to your server (the invite URL is logged at startup).
   In Radarr/Sonarr, configure **Connect → Webhook** to point to your public URL (PORT=3001) `/` endpoint.

## Docker
```bash
docker compose up --build
```

## Notes
- This is a starting point. Add Sonarr, more event types, and richer settings as you iterate.
