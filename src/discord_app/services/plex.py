from typing import Optional, List
import httpx
import xml.etree.ElementTree as ET


class PlexClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        movies_section_id: Optional[int] = None,
        shows_section_id: Optional[int] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.movies_section_id = movies_section_id
        self.shows_section_id = shows_section_id
        self._client = httpx.AsyncClient(timeout=10.0)

    def _auth_params(self):
        return {"X-Plex-Token": self.token}

    async def search_movies(self, query: str) -> List[dict]:
        # Prefer library section search if provided; falls back to global /search
        params = self._auth_params()
        if self.movies_section_id:
            url = f"{self.base_url}/library/sections/{self.movies_section_id}/all"
            params = {**params, "type": "1", "query": query}
        else:
            url = f"{self.base_url}/search"
            params = {**params, "query": query}
        r = await self._client.get(
            url, params=params, headers={"Accept": "application/xml"}
        )
        r.raise_for_status()
        return self._parse_metadata_list(r.text)

    def _parse_metadata_list(self, xml_text: str) -> List[dict]:
        out: List[dict] = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return out
        for md in root.iter("Video"):
            item = {
                "title": md.attrib.get("title"),
                "year": int(md.attrib["year"]) if md.attrib.get("year") else None,
                "ratingKey": md.attrib.get("ratingKey"),
                "guids": [],
            }
            for guid in md.findall("Guid"):
                gid = guid.attrib.get("id")
                if gid:
                    item["guids"].append(gid)
            out.append(item)
        # Some Plex servers use <Metadata> elements under a parent; include those too
        for md in root.findall(".//Metadata"):
            if md.attrib.get("type") != "movie":
                continue
            item = {
                "title": md.attrib.get("title"),
                "year": int(md.attrib["year"]) if md.attrib.get("year") else None,
                "ratingKey": md.attrib.get("ratingKey"),
                "guids": [],
            }
            for guid in md.findall("Guid"):
                gid = guid.attrib.get("id")
                if gid:
                    item["guids"].append(gid)
            out.append(item)
        return out

    async def movie_exists(
        self,
        *,
        tmdb_id: Optional[int] = None,
        imdb_id: Optional[str] = None,
        title: Optional[str] = None,
        year: Optional[int] = None,
    ) -> bool:
        # Strategy:
        # 1) If tmdb/imdb provided, search by title (fast) and match GUIDs: tmdb://<id>, imdb://<ttid>
        # 2) If only title/year, do a fuzzy match on title + year.
        q = title or ""
        if not q and tmdb_id:
            q = str(tmdb_id)
        if not q and imdb_id:
            q = imdb_id
        if not q:
            return False
        items = await self.search_movies(q)
        tmdb_sig = f"tmdb://{tmdb_id}" if tmdb_id else None
        imdb_sig = (
            imdb_id.replace("tt", "imdb://tt")
            if imdb_id and not imdb_id.startswith("imdb://")
            else imdb_id
        )
        for it in items:
            guids = it.get("guids", [])
            if tmdb_sig and any(g.lower() == tmdb_sig for g in guids):
                return True
            if imdb_sig and any(g.lower() == imdb_sig.lower() for g in guids):
                return True
            if title and it.get("title") and it["title"].lower() == title.lower():
                if year and it.get("year") and year == it["year"]:
                    return True
        return False

    async def close(self):
        await self._client.aclose()

    async def search_series(
        self, query: str, series_section_id: Optional[int] = None
    ) -> List[dict]:
        params = self._auth_params()
        section_id = series_section_id or self.movies_section_id  # allow override
        # For shows, type=2
        if section_id:
            url = f"{self.base_url}/library/sections/{section_id}/all"
            params = {**params, "type": "2", "query": query}
        else:
            url = f"{self.base_url}/search"
            params = {**params, "query": query}
        r = await self._client.get(
            url, params=params, headers={"Accept": "application/xml"}
        )
        r.raise_for_status()
        return self._parse_metadata_list(r.text)

    async def series_exists(
        self,
        *,
        tvdb_id: Optional[int] = None,
        tmdb_id: Optional[int] = None,
        title: Optional[str] = None,
        year: Optional[int] = None,
        series_section_id: Optional[int] = None,
    ) -> bool:
        q = title or ""
        if not q and tmdb_id:
            q = str(tmdb_id)
        if not q and tvdb_id:
            q = str(tvdb_id)
        if not q:
            return False
        items = await self.search_series(q, series_section_id)
        tmdb_sig = f"tmdb://{tmdb_id}" if tmdb_id else None
        tvdb_sig = f"tvdb://{tvdb_id}" if tvdb_id else None
        for it in items:
            guids = it.get("guids", [])
            if tmdb_sig and any(g.lower() == tmdb_sig for g in guids):
                return True
            if tvdb_sig and any(g.lower() == tvdb_sig for g in guids):
                return True
            if title and it.get("title") and it["title"].lower() == title.lower():
                if year and it.get("year") and year == it["year"]:
                    return True
        return False

    async def search_series2(self, query: str) -> list[dict]:
        params = self._auth_params()
        if self.shows_section_id:
            url = f"{self.base_url}/library/sections/{self.shows_section_id}/all"
            params = {**params, "type": "2", "query": query}
        else:
            url = f"{self.base_url}/search"
            params = {**params, "query": query}
        r = await self._client.get(
            url, params=params, headers={"Accept": "application/xml"}
        )
        r.raise_for_status()
        return self._parse_metadata_list(r.text)

    async def series_exists2(
        self,
        *,
        tvdb_id: int | None = None,
        tmdb_id: int | None = None,
        title: str | None = None,
        year: int | None = None,
    ) -> bool:
        q = title or ""
        if not q and tmdb_id:
            q = str(tmdb_id)
        if not q and tvdb_id:
            q = str(tvdb_id)
        if not q:
            return False
        items = await self.search_series(q)
        tvdb_sig = f"tvdb://{tvdb_id}" if tvdb_id else None
        tmdb_sig = f"tmdb://{tmdb_id}" if tmdb_id else None
        for it in items:
            guids = it.get("guids", [])
            if tvdb_sig and any(g.lower() == tvdb_sig for g in guids):
                return True
            if tmdb_sig and any(g.lower() == tmdb_sig for g in guids):
                return True
            if title and it.get("title") and it["title"].lower() == title.lower():
                if year and it.get("year") and year == it["year"]:
                    return True
        return False
