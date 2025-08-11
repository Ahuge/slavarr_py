from fastapi import FastAPI, Request
import logging

app = FastAPI()
log = logging.getLogger(__name__)


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.post("/")
async def receive_webhook(req: Request):
    # Radarr/Sonarr webhook payloads differ; accept any JSON and log for now
    payload = await req.json()
    event_type = payload.get("eventType") or payload.get("event") or "unknown"
    log.info("Received webhook event: %s", event_type)
    # TODO: normalize and notify subscribed users via Discord DM or channel
    return {"received": True, "event": event_type}
