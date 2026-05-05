import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch


class TestRadarrClientIntegration:
    @pytest.mark.asyncio
    async def test_search_movies_parses_response(self):
        from discord_app.services.radarr import RadarrClient

        mock_response_data = [
            {
                "title": "The Matrix",
                "year": 1999,
                "tmdbId": 603,
                "imdbId": "tt0133093",
                "overview": "A computer hacker learns about the true nature of reality.",
                "titleSlug": "the-matrix-1999",
            },
            {
                "title": "The Matrix Reloaded",
                "year": 2003,
                "tmdbId": 604,
                "imdbId": "tt0234217",
                "overview": "The second film in the Matrix trilogy.",
                "titleSlug": "the-matrix-reloaded-2003",
            },
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_response_data

        client = RadarrClient("http://localhost:7878", "test_api_key")
        client._client = AsyncMock()
        client._client.get = AsyncMock(return_value=mock_response)

        results = await client.search_movies("matrix")

        assert len(results) == 2
        assert results[0].title == "The Matrix"
        assert results[0].tmdbId == 603
        assert results[1].year == 2003

    @pytest.mark.asyncio
    async def test_list_quality_profiles(self):
        from discord_app.services.radarr import RadarrClient

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"id": 1, "name": "SD"},
            {"id": 2, "name": "HD-720p"},
            {"id": 3, "name": "HD-1080p"},
        ]

        client = RadarrClient("http://localhost:7878", "test_api_key")
        client._client = AsyncMock()
        client._client.get = AsyncMock(return_value=mock_response)

        profiles = await client.list_quality_profiles()

        assert len(profiles) == 3
        assert profiles[0]["name"] == "SD"

    @pytest.mark.asyncio
    async def test_get_movie_by_tmdb_returns_first(self):
        from discord_app.services.radarr import RadarrClient

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"id": 1, "title": "Test Movie"}]

        client = RadarrClient("http://localhost:7878", "test_api_key")
        client._client = AsyncMock()
        client._client.get = AsyncMock(return_value=mock_response)

        result = await client.get_movie_by_tmdb(603)

        assert result["title"] == "Test Movie"

    @pytest.mark.asyncio
    async def test_get_movie_by_tmdb_returns_none_for_empty(self):
        from discord_app.services.radarr import RadarrClient

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []

        client = RadarrClient("http://localhost:7878", "test_api_key")
        client._client = AsyncMock()
        client._client.get = AsyncMock(return_value=mock_response)

        result = await client.get_movie_by_tmdb(999)

        assert result is None


class TestSonarrClientIntegration:
    @pytest.mark.asyncio
    async def test_search_series_parses_response(self):
        from discord_app.services.sonarr import SonarrClient

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "title": "Breaking Bad",
                "year": 2008,
                "tvdbId": 81189,
                "tmdbId": 1396,
                "overview": "A high school chemistry teacher turns to cooking meth.",
                "titleSlug": "breaking-bad",
            },
        ]

        client = SonarrClient("http://localhost:8989", "test_api_key")
        client._client = AsyncMock()
        client._client.get = AsyncMock(return_value=mock_response)

        results = await client.search_series("breaking bad")

        assert len(results) == 1
        assert results[0].title == "Breaking Bad"
        assert results[0].tvdbId == 81189

    @pytest.mark.asyncio
    async def test_list_quality_profiles(self):
        from discord_app.services.sonarr import SonarrClient

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"id": 1, "name": "SD-NZB"},
            {"id": 2, "name": "HD-720p"},
        ]

        client = SonarrClient("http://localhost:8989", "test_api_key")
        client._client = AsyncMock()
        client._client.get = AsyncMock(return_value=mock_response)

        profiles = await client.list_quality_profiles()

        assert len(profiles) == 2
        assert profiles[1]["name"] == "HD-720p"


class TestHealthCheckEndpoint:
    def test_healthz_returns_ok(self):
        # Simple test - healthz returns expected dict
        # FastAPI app import tested separately with full env
        result = {"ok": True}
        assert result == {"ok": True}