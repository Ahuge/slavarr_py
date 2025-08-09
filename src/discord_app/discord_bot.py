import asyncio
import logging
import discord
from discord import app_commands
from discord.ext import commands
from discord_app.config import Settings
from discord_app.db import init_engine, make_session_factory, User
from discord_app.services.radarr import RadarrClient, MovieResult
from discord_app.services.plex import PlexClient
from discord_app.services.sonarr import SonarrClient, SeriesResult

log = logging.getLogger(__name__)

class SlavarrBot(commands.Bot):
    def __init__(self, settings: Settings, **kwargs):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents, **kwargs)
        self.settings = settings
        self.radarr = RadarrClient(settings.radarr_url, settings.radarr_api_key)
        self.plex = PlexClient(settings.plex_url, settings.plex_token, settings.plex_movies_section_id, settings.plex_shows_section_id) if getattr(settings,'plex_url',None) and getattr(settings,'plex_token',None) else None
        self.sonarr = SonarrClient(settings.sonarr_url, settings.sonarr_api_key) if getattr(settings, "sonarr_url", None) else None
        self.engine = init_engine(settings.db_path)
        self.Session = make_session_factory(self.engine)

    async def setup_hook(self):
        # register slash commands globally
        self.tree.copy_global_to(guild=None)
        await self.tree.sync()
        # Log invite URL
        perms = discord.Permissions(permissions=self.settings.invite_permissions)
        invite = discord.utils.oauth_url(
            client_id=self.settings.discord_client_id,
            scopes=("bot","applications.commands"),
            permissions=perms,
        )
        log.info("Invite the bot using: %s", invite)

    async def close(self):
        if self.sonarr:
            await self.sonarr.close()
        await self.radarr.close()
        await super().close()

bot: SlavarrBot | None = None

# ===== Movie Flow =====

class MovieSelect(discord.ui.Select):
    def __init__(self, results: list[MovieResult], already: set[int]):
        options = []
        for r in results[:25]:
            if not r.tmdbId:
                continue
            label = f"{r.title} ({r.year})" if r.year else r.title
            description = (r.overview or "")[:90]
            # Mark existing items in label
            if r.tmdbId in already:
                label = f"✅ {label}"
                description = "Already in Radarr/Plex"
            options.append(discord.SelectOption(label=label[:100], value=str(r.tmdbId), description=description))
        super().__init__(placeholder="Select a movie to add…", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        tmdb_id = int(self.values[0])
        view: MovieSelectView = self.view  # type: ignore
        await view.add_selected(interaction, tmdb_id)

class MovieSelectView(discord.ui.View):
    def __init__(self, results: list[MovieResult], already: set[int], monitored: bool = True, timeout: float | None = 60.0):
        super().__init__(timeout=timeout)
        self.results = results
        self.already = already
        self.monitored = monitored
        self.add_item(MovieSelect(results, already))

    async def add_selected(self, interaction: discord.Interaction, tmdb_id: int):
        assert isinstance(interaction.client, SlavarrBot)
        bot: SlavarrBot = interaction.client
        await interaction.response.defer(thinking=True, ephemeral=True)
        if tmdb_id in self.already:
            await interaction.followup.send("ℹ️ That movie is already in Radarr.", ephemeral=True)
            return
        try:
            data = await bot.radarr.add_movie(tmdb_id, monitored=bot.settings.radarr_monitor)
            title = data.get("title") or "Movie"
            await interaction.followup.send(f"✅ Added **{title}** (tmdb:{tmdb_id}) to Radarr.", ephemeral=True)
        except Exception as e:
            log.exception("Failed to add movie: %s", e)
            await interaction.followup.send("❌ Failed to add the selected movie (it might already exist or Radarr refused).", ephemeral=True)

# ===== Series Flow =====

class SeriesSelect(discord.ui.Select):
    def __init__(self, results: list[SeriesResult], already_tvdb: set[int], already_tmdb: set[int]):
        options = []
        for r in results[:25]:
            id_label = r.tvdbId or r.tmdbId
            if not id_label:
                continue
            label = f"{r.title} ({r.year})" if r.year else r.title
            description = (r.overview or "")[:90]
            exists = (r.tvdbId in already_tvdb) or (r.tmdbId in already_tmdb if r.tmdbId else False)
            if exists:
                label = f"✅ {label}"
                description = "Already in Sonarr/Plex"
            # value encodes both ids: tvdb:xxx|tmdb:yyy
            value = f"tvdb:{r.tvdbId or 0}|tmdb:{r.tmdbId or 0}"
            options.append(discord.SelectOption(label=label[:100], value=value, description=description))
        super().__init__(placeholder="Select a series to add…", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        raw = self.values[0]
        parts = dict(p.split(":") for p in raw.split("|"))
        tvdb_id = int(parts.get("tvdb","0"))
        tmdb_id = int(parts.get("tmdb","0"))
        view: SeriesSelectView = self.view  # type: ignore
        await view.add_selected(interaction, tvdb_id if tvdb_id>0 else None, tmdb_id if tmdb_id>0 else None)

class SeriesSelectView(discord.ui.View):
    def __init__(self, results: list[SeriesResult], already_tvdb: set[int], already_tmdb: set[int], monitored: bool = True, timeout: float | None = 60.0):
        super().__init__(timeout=timeout)
        self.results = results
        self.already_tvdb = already_tvdb
        self.already_tmdb = already_tmdb
        self.monitored = monitored
        self.add_item(SeriesSelect(results, already_tvdb, already_tmdb))

    async def add_selected(self, interaction: discord.Interaction, tvdb_id: int | None, tmdb_id: int | None):
        assert isinstance(interaction.client, SlavarrBot)
        bot: SlavarrBot = interaction.client
        await interaction.response.defer(thinking=True, ephemeral=True)
        exists = False
        if tvdb_id and tvdb_id in self.already_tvdb:
            exists = True
        if tmdb_id and tmdb_id in self.already_tmdb:
            exists = True
        if exists:
            await interaction.followup.send("ℹ️ That series is already in Sonarr.", ephemeral=True)
            return
        try:
            data = await bot.sonarr.add_series(tvdb_id, tmdb_id, monitored=bot.settings.sonarr_monitor if hasattr(bot.settings,'sonarr_monitor') else True)
            title = data.get("title") or "Series"
            await interaction.followup.send(f"✅ Added **{title}** to Sonarr.", ephemeral=True)
        except Exception as e:
            log.exception("Failed to add series: %s", e)
            await interaction.followup.send("❌ Failed to add the selected series (it might already exist or Sonarr refused).", ephemeral=True)

class ContentCommands(commands.Cog):
    def __init__(self, bot: SlavarrBot):
        self.bot = bot

    @app_commands.command(name="movie_add", description="Search Radarr and add a movie")
    @app_commands.describe(query="Movie title to search")
    async def movie_add(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            results = await self.bot.radarr.search_movies(query)
            if not results:
                await interaction.followup.send("No movies found.", ephemeral=True)
                return
            # existence check per result
            already = set()
            plex_already = set()
            # check up to first 10 to keep latency bounded
            for r in results[:10]:
                if r.tmdbId:
                    try:
                        existing = await self.bot.radarr.get_existing_by_tmdb(r.tmdbId)
                        if existing:
                            already.add(r.tmdbId)
                    except Exception:
                        pass
                # Plex check
                if self.bot.plex and (r.tmdbId or r.imdbId):
                    try:
                        in_plex = await self.bot.plex.movie_exists(tmdb_id=r.tmdbId, imdb_id=r.imdbId, title=r.title, year=r.year)
                        if in_plex and r.tmdbId:
                            plex_already.add(r.tmdbId)
                    except Exception:
                        pass
            # Pass union for label; keep sets separate for messaging if you want later
            union = already.union(plex_already)
            view = MovieSelectView(results, union)
            await interaction.followup.send("Pick a result:", view=view, ephemeral=True)
        except Exception as e:
            log.exception("Search failed: %s", e)
            await interaction.followup.send("Search failed. Check Radarr settings.", ephemeral=True)

    @app_commands.command(name="series_add", description="Search Sonarr and add a series")
    @app_commands.describe(query="Series title to search")
    async def series_add(self, interaction: discord.Interaction, query: str):
        if not self.bot.sonarr:
            await interaction.response.send_message("Sonarr is not configured.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            results = await self.bot.sonarr.search_series(query)
            if not results:
                await interaction.followup.send("No series found.", ephemeral=True)
                return
            # existence checks
            plex_already_tvdb, plex_already_tmdb = set(), set()
            already_tvdb, already_tmdb = set(), set()
            for r in results[:10]:
                tvdb_id = r.tvdbId
                tmdb_id = r.tmdbId
                try:
                    existing = await self.bot.sonarr.get_existing_by_ids(tvdb_id, tmdb_id)
                    if existing:
                        if tvdb_id: already_tvdb.add(tvdb_id)
                        if tmdb_id: already_tmdb.add(tmdb_id)
                except Exception:
                    pass
                # Plex check
                if self.bot.plex and (r.tvdbId or r.tmdbId):
                    try:
                        in_plex_series = await self.bot.plex.series_exists(tvdb_id=r.tvdbId, tmdb_id=r.tmdbId, title=r.title, year=r.year, series_section_id=getattr(self.bot.settings, 'plex_series_section_id', None))
                        if in_plex_series:
                            if r.tvdbId: plex_already_tvdb.add(r.tvdbId)
                            if r.tmdbId: plex_already_tmdb.add(r.tmdbId)
                    except Exception:
                        pass
            # merge sets for marking
            merged_tvdb = already_tvdb.union(plex_already_tvdb)
            merged_tmdb = already_tmdb.union(plex_already_tmdb)
            view = SeriesSelectView(results, merged_tvdb, merged_tmdb, monitored=True)
            await interaction.followup.send("Pick a result:", view=view, ephemeral=True)
        except Exception as e:
            log.exception("Search failed: %s", e)
            await interaction.followup.send("Search failed. Check Sonarr settings.", ephemeral=True)

async def create_bot(settings: Settings) -> SlavarrBot:
    global bot
    bot = SlavarrBot(settings=settings)
    await bot.add_cog(ContentCommands(bot))
    return bot
