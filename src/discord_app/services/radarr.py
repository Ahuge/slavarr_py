from typing import List, Dict, Any, Optional
import httpx
from pydantic import BaseModel

class MovieResult(BaseModel):
    title: str
    year: int | None = None
    tmdbId: int | None = None
    imdbId: str | None = None
    overview: str | None = None
    titleSlug: str | None = None

class RadarrClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self._client = httpx.AsyncClient(timeout=10.0)

    async def search_movies(self, term: str) -> List[MovieResult]:
        url = f"{self.base_url}/api/v3/movie/lookup"
        params = {"term": term}
        headers = {"X-Api-Key": self.api_key}
        r = await self._client.get(url, params=params, headers=headers)
        r.raise_for_status()
        items = r.json()
        results = []
        for it in items[:50]:
            results.append(MovieResult(
                title=it.get("title"),
                year=it.get("year"),
                tmdbId=it.get("tmdbId"),
                imdbId=it.get("imdbId"),
                overview=it.get("overview"),
                titleSlug=it.get("titleSlug"),
            ))
        return results

    async def get_existing_by_tmdb(self, tmdb_id: int):
        url = f"{self.base_url}/api/v3/movie"
        headers = {"X-Api-Key": self.api_key}
        r = await self._client.get(url, params={"tmdbId": tmdb_id}, headers=headers)
        r.raise_for_status()
        items = r.json()
        if items:
            return items[0]
        return None

    async def add_movie(self, tmdb_id: int, quality_profile_id: int = 1, root_folder_path: str = "/movies", monitored: bool = True) -> Dict[str, Any]:
        url = f"{self.base_url}/api/v3/movie"
        headers = {"X-Api-Key": self.api_key, "Content-Type": "application/json"}
        payload = {
            "tmdbId": tmdb_id,
            "qualityProfileId": quality_profile_id,
            "rootFolderPath": root_folder_path,
            "monitored": monitored,
            "addOptions": {"searchForMovie": True},
        }
        r = await self._client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        return r.json()

    async def close(self):
        await self._client.aclose()
