from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, Header
import logging
from typing import Optional

app = FastAPI(lifespan=lifespan)
log = logging.getLogger(__name__)

# Valid API keys - loaded from environment in production
VALID_API_KEYS: set[str] = set()


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
    yield


def verify_api_key(x_api_key: Optional[str]) -> bool:
    if not x_api_key:
        return False
    return x_api_key in VALID_API_KEYS


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
    log.info("Received webhook event: %s", event_type)
    return {"received": True, "event": event_type}
