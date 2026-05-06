# AGENTS.md

## Project
Discord bot (`discord.py`) integrating with Radarr/Sonarr, Plex (optional), and Transmission (optional). Runs a FastAPI webhook server on port 3001 in the same process.

## Entry Point
```bash
python -m src.discord_app.main
```
Docker CMD: `python /app/src/discord_app/main.py`

## Setup
1. Copy `.env.example` to `.env` and fill in credentials
2. `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
3. Run the entry point above

## Testing
```bash
PYTHONPATH=src python -m pytest tests/ -v
```
No linter or typechecker configured.

## Architecture
- `src/discord_app/main.py` – entry point; runs Discord bot + uvicorn concurrently via `asyncio.gather`
- `src/discord_app/discord_bot.py` – `SlavarrBot` class, all slash commands (`/movie_add`, `/series_add`, `/movie_status`, `/series_status`), UI views, and tracking loops
- `src/discord_app/services/` – `radarr.py`, `sonarr.py`, `plex.py`, `transmission.py` (async HTTP clients)
- `src/discord_app/webhook.py` – FastAPI app with `/healthz` (GET) and `/` (POST for Radarr/Sonarr events)
- `src/discord_app/db.py` – SQLAlchemy SQLite with `User` and `UserEvent` tables
- `src/discord_app/config.py` – Pydantic `Settings`; loads env via `python-dotenv`

## Key Conventions
- All services are async and use `httpx` for HTTP calls
- Bot registers slash commands globally via `tree.sync()` in `setup_hook`
- DB uses `StaticPool` with `check_same_thread=False` (single-threaded asyncio, safe)
- Sonarr is conditionally initialized only if `SONARR_URL` is set; Plex and Transmission similarly optional
- Radarr and Sonarr are required (no None guards); missing credentials will crash at startup

## Docker
- `docker-compose.yml` – QNAP NAS paths (`/share/CACHEDEV1_DATA/...`)
- `docker-compose.yml.local` – local dev paths (Windows/WSL at `/mnt/d/Discord/slavarr_py`)
- SQLite DB persisted via volume at `/app/data`
- Port 3001 exposed for webhook

## Environment Quirks
- `DB_PATH` has duplicate definition in `.env` (line 18: `/app/data/slavarr.db`, line 38: `slavarr.db`) - later one takes precedence with python-dotenv
- `RADARR_URL`/`SONARR_URL` are `.rstrip("/")` in config – trailing slashes are stripped automatically
- `SONARR_URL`/`SONARR_API_KEY` in `.env` - Sonarr IS fully wired (not placeholder)

## Workflow
- **Always create a branch** for any code changes (don't commit directly to main)
- Make **logical commits** – one feature, fix, or refactor per commit with a clear message
- Warn the user if not on a feature branch before making changes
