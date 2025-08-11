from typing import List, Dict, Any
import httpx
from datetime import datetime, timezone
from operator import itemgetter
from pydantic import BaseModel

class SeriesResult(BaseModel):
    title: str
    year: int | None = None
    tvdbId: int | None = None
    tmdbId: int | None = None
    overview: str | None = None
    titleSlug: str | None = None

class SonarrClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self._client = httpx.AsyncClient(timeout=10.0)

    async def search_series(self, term: str) -> List[SeriesResult]:
        url = f"{self.base_url}/api/v3/series/lookup"
        params = {"term": term}
        headers = {"X-Api-Key": self.api_key}
        r = await self._client.get(url, params=params, headers=headers)
        r.raise_for_status()
        items = r.json()
        results = []
        for it in items[:50]:
            results.append(SeriesResult(
                title=it.get("title"),
                year=it.get("year"),
                tvdbId=it.get("tvdbId"),
                tmdbId=it.get("tmdbId"),
                overview=it.get("overview"),
                titleSlug=it.get("titleSlug"),
            ))
        return results

    async def list_quality_profiles(self) -> list[dict]:
      url = f"{self.base_url}/api/v3/qualityprofile"
      headers = {"X-Api-Key": self.api_key}
      r = await self._client.get(url, headers=headers)
      r.raise_for_status()
      return r.json()

    async def list_root_folders(self) -> list[dict]:
      # Kept for completeness; we won't prompt users. Uses env setting instead.
      url = f"{self.base_url}/api/v3/rootfolder"
      headers = {"X-Api-Key": self.api_key}
      r = await self._client.get(url, headers=headers)
      r.raise_for_status()
      return r.json()

    async def get_series_by_tvdb_or_tmdb(self, tvdb_id: int | None, tmdb_id: int | None) -> dict | None:
        """Return the Sonarr series (library item) for a given TVDB/TMDB id, or None."""
        headers = {"X-Api-Key": self.api_key}
        url_series = f"{self.base_url}/api/v3/series"
        if tvdb_id:
            r = await self._client.get(url_series, headers=headers, params={"tvdbId": tvdb_id})
            if r.status_code == 200 and r.json():
                return r.json()[0]
        if tmdb_id:
            r = await self._client.get(url_series, headers=headers, params={"tmdbId": tmdb_id})
            if r.status_code == 200 and r.json():
                return r.json()[0]
        return None

    async def get_queue(self) -> list[dict]:
        """Get current download queue; tolerate either {records:[...]} or raw list."""
        url = f"{self.base_url}/api/v3/queue"
        headers = {"X-Api-Key": self.api_key}
        r = await self._client.get(url, headers=headers)
        r.raise_for_status()
        data = r.json()
        return data.get("records", data) if isinstance(data, dict) else data

    async def get_history_for_series(self, series_id: int, page_size: int = 10) -> list[dict]:
        """Recent history for a given series id."""
        url = f"{self.base_url}/api/v3/history/series"
        headers = {"X-Api-Key": self.api_key}
        params = {"seriesId": series_id, "pageSize": page_size, "includeSeries": "true"}
        r = await self._client.get(url, headers=headers, params=params)
        r.raise_for_status()
        data = r.json()
        return data.get("records", data) if isinstance(data, dict) else data

    @staticmethod
    def summarize_series_progress(series: dict) -> dict:
        stats = series.get("statistics", {}) or {}
        return {
            "episodeFileCount": stats.get("episodeFileCount", 0),
            "totalEpisodeCount": stats.get("totalEpisodeCount", 0),
            "percentOfEpisodes": stats.get("percentOfEpisodes", 0.0),
        }

    @staticmethod
    def summarize_queue_for_series(q_items: list[dict], series_id: int) -> list[dict]:
        return [
            {
                "title": it.get("title"),
                "status": it.get("status"),
                "downloadId": it.get("downloadId"),
                "size": it.get("size"),
                "sizeleft": it.get("sizeleft"),
                "timeleft": it.get("timeleft"),
                "protocol": it.get("protocol"),
            }
            for it in q_items if it.get("seriesId") == series_id
        ]

    async def get_series_by_id(self, series_id: int) -> dict | None:
        url = f"{self.base_url}/api/v3/series/{series_id}"
        headers = {"X-Api-Key": self.api_key}
        r = await self._client.get(url, headers=headers)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    async def update_series(self, series_obj: dict) -> dict:
        """
        Sonarr requires sending the full series object for updates (PUT /series).
        """
        url = f"{self.base_url}/api/v3/series"
        headers = {"X-Api-Key": self.api_key, "Content-Type": "application/json"}
        r = await self._client.put(url, headers=headers, json=series_obj)
        r.raise_for_status()
        return r.json()

    async def set_quality_profile(self, series_id: int, quality_profile_id: int) -> dict:
        series = await self.get_series_by_id(series_id)
        if not series:
            raise RuntimeError("Series not found")
        series["qualityProfileId"] = quality_profile_id
        return await self.update_series(series)

    async def get_episode_list(self, series_id: int) -> list[dict]:
        """
        Fetch all episodes for a series; we will pick a monitored, aired, missing one.
        """
        url = f"{self.base_url}/api/v3/episode"
        headers = {"X-Api-Key": self.api_key}
        r = await self._client.get(url, headers=headers, params={"seriesId": series_id})
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []

    @staticmethod
    def pick_missing_aired_monitored_episode(episodes: list[dict]) -> dict | None:
        now = datetime.now(timezone.utc)
        candidates = []
        for ep in episodes:
            if not ep.get("monitored", True):
                continue
            if ep.get("hasFile"):
                continue
            air = ep.get("airDateUtc")
            if not air:
                continue
            try:
                air_dt = datetime.fromisoformat(air.replace("Z","+00:00"))
            except Exception:
                continue
            if air_dt <= now:
                candidates.append(ep)
        if not candidates:
            return None
        # pick the newest aired missing monitored (max season, then episode)
        candidates.sort(key=lambda e: (e.get("seasonNumber",0), e.get("episodeNumber",0)), reverse=True)
        return candidates[0]

    async def get_releases_for_episode(self, episode_id: int) -> list[dict]:
        url = f"{self.base_url}/api/v3/release"
        headers = {"X-Api-Key": self.api_key}
        r = await self._client.get(url, headers=headers, params={"episodeId": episode_id})
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []

    async def post_release(self, guid: str, indexer_id: int) -> dict:
        url = f"{self.base_url}/api/v3/release"
        headers = {"X-Api-Key": self.api_key, "Content-Type": "application/json"}
        payload = {"guid": guid, "indexerId": indexer_id}
        r = await self._client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        return r.json()

    async def trigger_series_search(self, series_id: int) -> dict:
        url = f"{self.base_url}/api/v3/command"
        headers = {"X-Api-Key": self.api_key, "Content-Type": "application/json"}
        payload = {"name": "SeriesSearch", "seriesId": series_id}
        r = await self._client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        return r.json()

    async def add_series(self, tvdb_id: int | None, tmdb_id: int | None, quality_profile_id: int = 1, root_folder_path: str = "/tv", monitored: bool = True) -> Dict[str, Any]:
        # Sonarr requires full series body; we'll refetch the series by lookup first
        headers = {"X-Api-Key": self.api_key}
        # Prefer tvdbId
        term = f"tvdb:{tvdb_id}" if tvdb_id else f"tmdb:{tmdb_id}"
        lookup = await self._client.get(f"{self.base_url}/api/v3/series/lookup", params={"term": term}, headers=headers)
        lookup.raise_for_status()
        data = lookup.json()
        if not data:
            raise RuntimeError("Series not found during add")
        series = data[0]
        payload = {
            "tvdbId": series.get("tvdbId"),
            "title": series.get("title"),
            "qualityProfileId": quality_profile_id,
            "titleSlug": series.get("titleSlug"),
            "images": series.get("images", []),
            "seasons": series.get("seasons", []),
            "rootFolderPath": root_folder_path,
            "monitored": monitored,
            "addOptions": {"searchForMissingEpisodes": True},
            "languageProfileId": series.get("languageProfileId", 1),
            "seriesType": series.get("seriesType", "standard"),
        }
        r = await self._client.post(f"{self.base_url}/api/v3/series", headers={**headers, "Content-Type": "application/json"}, json=payload)
        r.raise_for_status()
        return r.json()

    async def get_existing_by_ids(self, tvdb_id: int | None, tmdb_id: int | None):
        headers = {"X-Api-Key": self.api_key}
        if tvdb_id:
            r = await self._client.get(f"{self.base_url}/api/v3/series", params={"tvdbId": tvdb_id}, headers=headers)
            r.raise_for_status()
            items = r.json()
            if items:
                return items[0]
        # Fallback check by tmdbId if supported
        if tmdb_id:
            r = await self._client.get(f"{self.base_url}/api/v3/series", params={"tmdbId": tmdb_id}, headers=headers)
            if r.status_code == 200:
                items = r.json()
                if items:
                    return items[0]
        return None

    async def close(self):
        await self._client.aclose()
