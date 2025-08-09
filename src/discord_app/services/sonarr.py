from typing import List, Dict, Any
import httpx
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
