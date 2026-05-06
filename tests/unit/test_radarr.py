import pytest
from discord_app.services.radarr import RadarrClient, MovieResult


class TestRadarrClientSummarizeQueue:
    def test_finds_movie_in_queue(self, sample_queue_response):
        result = RadarrClient.summarize_queue_progress(sample_queue_response, movie_id=1)
        assert result is not None
        assert result["title"] == "Downloading Movie"
        assert result["status"] == "Downloading"
        assert result["downloadId"] == "abc123"

    def test_returns_none_when_not_in_queue(self, sample_queue_response):
        result = RadarrClient.summarize_queue_progress(sample_queue_response, movie_id=999)
        assert result is None

    def test_empty_queue(self):
        result = RadarrClient.summarize_queue_progress([], movie_id=1)
        assert result is None


class TestMovieResult:
    def test_basic_creation(self):
        movie = MovieResult(
            title="Test Movie",
            year=2024,
            tmdbId=12345,
            imdbId="tt1234567",
            overview="A test overview",
            titleSlug="test-movie-2024",
        )
        assert movie.title == "Test Movie"
        assert movie.year == 2024
        assert movie.tmdbId == 12345

    def test_optional_fields(self):
        movie = MovieResult(title="Minimal Movie")
        assert movie.title == "Minimal Movie"
        assert movie.year is None
        assert movie.tmdbId is None