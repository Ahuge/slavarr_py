from typing import List, Dict, Any, Optional
import httpx
from datetime import datetime, timezone
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
        self.base_url = base_url.rstrip("/")
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
            results.append(
                MovieResult(
                    title=it.get("title"),
                    year=it.get("year"),
                    tmdbId=it.get("tmdbId"),
                    imdbId=it.get("imdbId"),
                    overview=it.get("overview"),
                    titleSlug=it.get("titleSlug"),
                )
            )
        return results

    async def list_quality_profiles(self) -> list[dict]:
        url = f"{self.base_url}/api/v3/qualityprofile"
        headers = {"X-Api-Key": self.api_key}
        r = await self._client.get(url, headers=headers)
        r.raise_for_status()
        return r.json()

    async def get_movie_by_tmdb(self, tmdb_id: int) -> dict | None:
        """Return the Radarr movie (library item) for a TMDB id, or None."""
        url = f"{self.base_url}/api/v3/movie"
        headers = {"X-Api-Key": self.api_key}
        r = await self._client.get(url, headers=headers, params={"tmdbId": tmdb_id})
        r.raise_for_status()
        data = r.json()
        return data[0] if data else None

    async def get_queue(self) -> list[dict]:
        """Get current download queue; tolerate either {records:[...]} or raw list."""
        url = f"{self.base_url}/api/v3/queue"
        headers = {"X-Api-Key": self.api_key}
        r = await self._client.get(url, headers=headers)
        r.raise_for_status()
        data = r.json()
        return data.get("records", data) if isinstance(data, dict) else data

    async def get_history_for_movie(
        self, movie_id: int, page_size: int = 10
    ) -> list[dict]:
        """Recent history for a given movie id."""
        url = f"{self.base_url}/api/v3/history/movie"
        headers = {"X-Api-Key": self.api_key}
        params = {"movieId": movie_id, "pageSize": page_size, "includeMovie": "true"}
        r = await self._client.get(url, headers=headers, params=params)
        r.raise_for_status()
        data = r.json()
        return data.get("records", data) if isinstance(data, dict) else data

    @staticmethod
    def summarize_queue_progress(q_items: list[dict], movie_id: int) -> dict | None:
        for it in q_items:
            if it.get("movieId") == movie_id:
                return {
                    "progress": it.get("sizeleft", 0.0),
                    "size": it.get("size", 0.0),
                    "status": it.get("status"),
                    "title": it.get("title"),
                    "downloadId": it.get("downloadId"),
                    "timeleft": it.get("timeleft"),
                    "protocol": it.get("protocol"),
                    "trackedDownloadStatus": it.get("trackedDownloadStatus"),
                }
        return None

    async def get_movie_by_id(self, movie_id: int) -> dict | None:
        url = f"{self.base_url}/api/v3/movie/{movie_id}"
        headers = {"X-Api-Key": self.api_key}
        r = await self._client.get(url, headers=headers)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    async def get_releases(self, movie_id: int) -> list[dict]:
        """
        Get cached indexer releases for a specific movie.
        """
        url = f"{self.base_url}/api/v3/release"
        headers = {"X-Api-Key": self.api_key}
        r = await self._client.get(url, headers=headers, params={"movieId": movie_id})
        r.raise_for_status()
        data = r.json()
        # Radarr returns a list
        return data if isinstance(data, list) else []

    async def post_release(self, guid: str, indexer_id: int) -> dict:
        """
        Grab a specific release from cache.
        """
        url = f"{self.base_url}/api/v3/release"
        headers = {"X-Api-Key": self.api_key, "Content-Type": "application/json"}
        payload = {"guid": guid, "indexerId": indexer_id}
        r = await self._client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        return r.json()

    async def trigger_movie_search(self, movie_id: int) -> dict:
        """
        If the cached releases are stale, trigger a search.
        """
        url = f"{self.base_url}/api/v3/command"
        headers = {"X-Api-Key": self.api_key, "Content-Type": "application/json"}
        payload = {"name": "MoviesSearch", "movieIds": [movie_id]}
        r = await self._client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        return r.json()

    async def get_existing_by_tmdb(self, tmdb_id: int):
        url = f"{self.base_url}/api/v3/movie"
        headers = {"X-Api-Key": self.api_key}
        r = await self._client.get(url, params={"tmdbId": tmdb_id}, headers=headers)
        r.raise_for_status()
        items = r.json()
        if items:
            return items[0]
        return None

    async def add_movie(
        self,
        tmdb_id: int,
        quality_profile_id: int = 1,
        root_folder_path: str = "/movies",
        monitored: bool = True,
    ) -> Dict[str, Any]:
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
