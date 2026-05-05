import pytest
import pytest_asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def sample_settings():
    """Minimal settings for testing."""
    from discord_app.config import Settings

    return Settings(
        discord_token="test_token",
        discord_client_id=1234567890,
        radarr_url="http://localhost:7878",
        radarr_api_key="test_radarr_key",
        sonarr_url="http://localhost:8989",
        sonarr_api_key="test_sonarr_key",
        db_path=":memory:",
    )


@pytest.fixture
def sample_movie_result():
    return {
        "title": "Test Movie",
        "year": 2024,
        "tmdbId": 12345,
        "imdbId": "tt1234567",
        "overview": "A test movie",
        "titleSlug": "test-movie-2024",
    }


@pytest.fixture
def sample_queue_response():
    return [
        {
            "movieId": 1,
            "title": "Downloading Movie",
            "status": "Downloading",
            "size": 1000000000,
            "sizeleft": 500000000,
            "timeleft": "01:00:00",
            "downloadId": "abc123",
            "protocol": "torrent",
            "trackedDownloadStatus": "downloading",
        },
        {
            "movieId": 2,
            "title": "Queued Movie",
            "status": "queued",
            "size": None,
            "sizeleft": None,
            "timeleft": None,
            "downloadId": None,
            "protocol": "torrent",
            "trackedDownloadStatus": "paused",
        },
    ]


@pytest.fixture
def sample_series_data():
    """Sample series data from Sonarr API."""
    return {
        "id": 1,
        "title": "Test Series",
        "tvdbId": 12345,
        "tmdbId": 67890,
        "titleSlug": "test-series",
        "year": 2024,
        "qualityProfileId": 1,
        "rootFolderPath": "/tv",
        "monitored": True,
        "statistics": {
            "episodeFileCount": 10,
            "totalEpisodeCount": 20,
            "percentOfEpisodes": 50.0,
        },
        "seasons": [
            {"seasonNumber": 1, "monitored": True},
            {"seasonNumber": 2, "monitored": False},
        ],
    }


@pytest.fixture
def sample_episode_list():
    """Sample episode list for series."""
    now = datetime.now(timezone.utc)
    return [
        {
            "id": 1,
            "seasonNumber": 1,
            "episodeNumber": 1,
            "title": "Episode 1",
            "airDateUtc": "2024-01-01T00:00:00Z",
            "monitored": True,
            "hasFile": True,
        },
        {
            "id": 2,
            "seasonNumber": 1,
            "episodeNumber": 2,
            "title": "Episode 2",
            "airDateUtc": "2024-01-08T00:00:00Z",
            "monitored": True,
            "hasFile": False,
        },
        {
            "id": 3,
            "seasonNumber": 2,
            "episodeNumber": 1,
            "title": "S2E1",
            "airDateUtc": "2025-01-01T00:00:00Z",
            "monitored": False,
            "hasFile": False,
        },
    ]


@pytest.fixture
def sample_episode_list_past():
    """Episode list with some aired missing episodes."""
    now = datetime.now(timezone.utc)
    return [
        {
            "id": 1,
            "seasonNumber": 1,
            "episodeNumber": 1,
            "title": "Episode 1",
            "airDateUtc": "2020-01-01T00:00:00Z",
            "monitored": True,
            "hasFile": True,
        },
        {
            "id": 2,
            "seasonNumber": 1,
            "episodeNumber": 2,
            "title": "Episode 2",
            "airDateUtc": "2020-01-08T00:00:00Z",
            "monitored": True,
            "hasFile": False,
        },
        {
            "id": 3,
            "seasonNumber": 1,
            "episodeNumber": 3,
            "title": "Episode 3",
            "airDateUtc": "2099-01-01T00:00:00Z",
            "monitored": True,
            "hasFile": False,
        },
    ]