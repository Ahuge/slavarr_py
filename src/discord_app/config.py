from pydantic import BaseModel
import os

class Settings(BaseModel):
    plex_url: str | None = None
    plex_token: str | None = None
    plex_movies_section_id: int | None = None
    plex_shows_section_id: int | None = None
    plex_series_section_id: int | None = None
    sonarr_url: str | None = None
    sonarr_api_key: str | None = None
    sonarr_monitor: bool = True
    discord_token: str
    discord_client_id: int
    radarr_url: str
    radarr_api_key: str
    radarr_monitor: bool = True
    bot_max_content: int = 10
    db_path: str = "/app/data/slavarr.db"
    port: int = 3001
    invite_permissions: int = 414464720896  # adjust as needed
    # Root folders (used automatically; no UI prompts)
    sonarr_root_folder: str = "/tv"
    radarr_root_folder: str = "/movies"

def load_settings() -> Settings:
    # Simple env loader; defer to dotenv if present
    from dotenv import load_dotenv
    load_dotenv()
    return Settings(
        discord_token=os.getenv("DISCORD_TOKEN",""),
        discord_client_id=int(os.getenv("DISCORD_CLIENT_ID","0")),
        radarr_url=os.getenv("RADARR_URL","http://localhost:7878").rstrip("/"),
        radarr_api_key=os.getenv("RADARR_API_KEY",""),
        radarr_monitor=os.getenv("RADARR_MONITOR","true").lower() == "true",
        sonarr_url=os.getenv("SONARR_URL"),
        sonarr_api_key=os.getenv("SONARR_API_KEY"),
        sonarr_monitor=os.getenv("SONARR_MONITOR","true").lower() == "true",
        sonarr_root_folder=os.getenv("SONARR_ROOT_FOLDER","/tv"),
        radarr_root_folder=os.getenv("RADARR_ROOT_FOLDER","/movies"),
        bot_max_content=int(os.getenv("BOT_MAX_CONTENT","10")),
        db_path=os.getenv("DB_PATH","/app/data/slavarr.db"),
        port=int(os.getenv("PORT","3001")),
        invite_permissions=int(os.getenv("INVITE_PERMISSIONS","414464720896")),
        plex_url=os.getenv("PLEX_URL"),
        plex_token=os.getenv("PLEX_TOKEN"),
        plex_movies_section_id=int(os.getenv("PLEX_MOVIES_SECTION_ID")) if os.getenv("PLEX_MOVIES_SECTION_ID") else None,
        plex_shows_section_id=int(os.getenv("PLEX_SHOWS_SECTION_ID")) if os.getenv("PLEX_SHOWS_SECTION_ID") else None,
        plex_series_section_id=int(os.getenv("PLEX_SERIES_SECTION_ID")) if os.getenv("PLEX_SERIES_SECTION_ID") else None,
    )
