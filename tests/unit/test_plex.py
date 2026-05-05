import pytest


@pytest.mark.asyncio
async def test_shows_section_id_used():
    """Verify shows_section_id is stored and used."""
    from discord_app.services.plex import PlexClient
    
    client = PlexClient(
        "http://localhost:32400",
        "test_token",
        movies_section_id=1,
        shows_section_id=2,
    )
    assert client.shows_section_id == 2