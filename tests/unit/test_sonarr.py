import pytest
from datetime import datetime, timezone
from discord_app.services.sonarr import SonarrClient, SeriesResult


class TestSonarrClientSummarizeSeries:
    def test_summarize_series_progress(self, sample_series_data):
        result = SonarrClient.summarize_series_progress(sample_series_data)
        assert result["episodeFileCount"] == 10
        assert result["totalEpisodeCount"] == 20
        assert result["percentOfEpisodes"] == 50.0

    def test_handles_empty_statistics(self):
        series = {"statistics": None}
        result = SonarrClient.summarize_series_progress(series)
        assert result["episodeFileCount"] == 0
        assert result["totalEpisodeCount"] == 0
        assert result["percentOfEpisodes"] == 0.0


class TestSonarrClientSummarizeQueueForSeries:
    def test_finds_queue_items_for_series(self):
        queue = [
            {"seriesId": 1, "title": "Show 1", "status": "downloading"},
            {"seriesId": 2, "title": "Show 2", "status": "queued"},
        ]
        result = SonarrClient.summarize_queue_for_series(queue, series_id=1)
        assert len(result) == 1
        assert result[0]["title"] == "Show 1"

    def test_empty_queue(self):
        result = SonarrClient.summarize_queue_for_series([], series_id=1)
        assert result == []


class TestBuildMonitoredSeasons:
    def test_selects_only_specified_seasons(self):
        seasons_source = [
            {"seasonNumber": 1, "monitored": True},
            {"seasonNumber": 2, "monitored": True},
            {"seasonNumber": 3, "monitored": True},
        ]
        client = SonarrClient("http://localhost:8989", "test_key")
        result = client.build_monitored_seasons(seasons_source, {1, 3})
        # Returns ALL seasons, with monitoring toggled
        assert len(result) == 3
        # Selected seasons are monitored
        assert result[0]["seasonNumber"] == 1
        assert result[0]["monitored"] is True
        assert result[2]["seasonNumber"] == 3
        assert result[2]["monitored"] is True
        # Unselected is marked as not monitored
        assert result[1]["seasonNumber"] == 2
        assert result[1]["monitored"] is False

    def test_deselects_all_if_empty_set(self):
        seasons_source = [
            {"seasonNumber": 1, "monitored": True},
            {"seasonNumber": 2, "monitored": True},
        ]
        client = SonarrClient("http://localhost:8989", "test_key")
        result = client.build_monitored_seasons(seasons_source, set())
        # Still returns all seasons, but all marked unmonitored
        assert all(s["monitored"] is False for s in result)

    def test_preserves_other_season_fields(self):
        seasons_source = [
            {
                "seasonNumber": 1,
                "monitored": True,
                "statistics": {"episodeCount": 10},
                "images": [],
            }
        ]
        client = SonarrClient("http://localhost:8989", "test_key")
        result = client.build_monitored_seasons(seasons_source, {1})
        assert result[0].get("statistics", {}).get("episodeCount") == 10
        assert result[0].get("images") == []


class TestPickMissingAiredMonitoredEpisode:
    def test_finds_monitored_aired_missing(self, sample_episode_list_past):
        result = SonarrClient.pick_missing_aired_monitored_episode(sample_episode_list_past)
        # Should find episode 2 (aired, monitored, missing file, and newest)
        assert result is not None
        assert result["episodeNumber"] == 2
        assert result["seasonNumber"] == 1

    def test_skips_unmonitored(self, sample_episode_list_past):
        # Mark episode 2 as unmonitored
        sample_episode_list_past[1]["monitored"] = False
        result = SonarrClient.pick_missing_aired_monitored_episode(sample_episode_list_past)
        # Episode 3 is future, episode 1 has file - should return None
        assert result is None

    def test_skips_future_episodes(self, sample_episode_list_past):
        # Remove episode 2's file (make it missing)
        sample_episode_list_past[1]["hasFile"] = True
        result = SonarrClient.pick_missing_aired_monitored_episode(sample_episode_list_past)
        # Only left is episode 3 which is future dated
        assert result is None

    def test_returns_none_for_empty_list(self):
        result = SonarrClient.pick_missing_aired_monitored_episode([])
        assert result is None


class TestSeriesResult:
    def test_basic_creation(self):
        series = SeriesResult(
            title="Test Series",
            year=2024,
            tvdbId=12345,
            tmdbId=67890,
            overview="A test series",
            titleSlug="test-series-2024",
        )
        assert series.title == "Test Series"
        assert series.tvdbId == 12345
        assert series.tmdbId == 67890

    def test_optional_fields(self):
        series = SeriesResult(title="Minimal Series")
        assert series.title == "Minimal Series"
        assert series.year is None
        assert series.tvdbId is None