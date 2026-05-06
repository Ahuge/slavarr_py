from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, Header
import logging
from typing import Optional

log = logging.getLogger(__name__)

VALID_API_KEYS: set[str] = set()

EVENT_NAMES = {
    "grab": "Grabbed",
    "download": "Downloaded",
    "upgrade": "Upgraded",
    "rename": "Renamed",
    "health": "Health",
    "missing": "Missing",
    "wanted": "Wanted",
    "unmanaged": "Unmanaged",
}

RADARR_EVENTS = {"grab", "download", "upgrade", "rename", "health", "missing", "wanted", "unmanaged"}
SONARR_EVENTS = {"grab", "download", "upgrade", "rename", "health", "missing", "wanted", "unmanaged", "seriesGrab"}


def set_api_keys(radarr_key: str, sonarr_key: str):
    if radarr_key:
        VALID_API_KEYS.add(radarr_key)
    if sonarr_key:
        VALID_API_KEYS.add(sonarr_key)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from discord_app.config import load_settings
    settings = load_settings()
    set_api_keys(settings.radarr_api_key, settings.sonarr_api_key)
    log.info("Webhook API keys loaded")
    yield


def verify_api_key(x_api_key: Optional[str]) -> bool:
    if not x_api_key:
        return False
    return x_api_key in VALID_API_KEYS


def get_event_description(event_type: str, source: str, data: dict) -> str:
    """Build human-readable event description."""
    title = data.get("movie") or data.get("series") or data.get("title", "Unknown")
    
    if event_type in ("grab", "download", "upgrade"):
        return f"{source}: {title} - {event_type.title()}"
    elif event_type == "health":
        return f"{source}: {title} - Health warning"
    elif event_type == "missing":
        return f"{source}: {title} - Missing"
    elif event_type == "wanted":
        return f"{source}: {title} - Wanted"
    elif event_type == "rename":
        return f"{source}: {title} - Renamed"
    else:
        return f"{source}: {title} - {event_type}"


app = FastAPI(lifespan=lifespan)


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.post("/")
async def receive_webhook(
    req: Request,
    x_api_key: Optional[str] = Header(None, alias="X-Api-Key"),
):
    if not verify_api_key(x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    try:
        payload = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    
    event_type = payload.get("eventType") or payload.get("event") or "unknown"
    
    is_radarr = event_type in RADARR_EVENTS
    is_sonarr = event_type in SONARR_EVENTS
    
    desc = get_event_description(event_type, "Radarr" if is_radarr else "Sonarr" if is_sonarr else "Unknown", payload)
    log.info(f"Webhook event: %s - %s", event_type, desc)
    
    # TODO: Implement user notifications
    # - Query User table for subscribers
    # - Send Discord DM or post to channel based on user preferences
    
    return {"received": True, "event": event_type}
