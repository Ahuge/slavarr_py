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

from discord_app.services.transmission import TransmissionClient

log = logging.getLogger(__name__)

class SlavarrBot(commands.Bot):
    def __init__(self, settings: Settings, **kwargs):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents, **kwargs)
        self.settings = settings
        self.radarr = RadarrClient(settings.radarr_url, settings.radarr_api_key)
        self.plex = PlexClient(settings.plex_url, settings.plex_token, settings.plex_movies_section_id, settings.plex_shows_section_id) if getattr(settings,'plex_url',None) and getattr(settings,'plex_token',None) else None
        self.sonarr = SonarrClient(settings.sonarr_url, settings.sonarr_api_key) if getattr(settings, "sonarr_url", None) else None
        self.transmission = None
        if settings.transmission_url:
            self.transmission = TransmissionClient(settings.transmission_url, settings.transmission_user, settings.transmission_password)
        self.engine = init_engine(settings.db_path)
        self.Session = make_session_factory(self.engine)

    async def setup_hook(self):
        # register slash commands globally
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
        # try:
        #     data = await bot.radarr.add_movie(tmdb_id, monitored=bot.settings.radarr_monitor)
        #     title = data.get("title") or "Movie"
        #     await interaction.followup.send(f"✅ Added **{title}** (tmdb:{tmdb_id}) to Radarr.", ephemeral=True)
        # except Exception as e:
        #     log.exception("Failed to add movie: %s", e)
        #     await interaction.followup.send("❌ Failed to add the selected movie (it might already exist or Radarr refused).", ephemeral=True)
       # Start quality selection flow (no root folder prompt)
        view = QualityOnlyMovieView(tmdb_id)
        # First response already deferred; send a followup with components
        profiles = await bot.radarr.list_quality_profiles()
        select = QualitySelect(profiles, kind="movie", payload={"tmdb_id": tmdb_id})
        view.clear_items()
        view.add_item(select)
        await interaction.followup.send("Pick a quality profile:", view=view, ephemeral=True)


class QualityOnlyMovieView(discord.ui.View):
    def __init__(self, tmdb_id: int, timeout: float | None = 120.0):
        super().__init__(timeout=timeout)
        self.tmdb_id = tmdb_id

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
        # try:
        #     data = await bot.sonarr.add_series(tvdb_id, tmdb_id, monitored=bot.settings.sonarr_monitor if hasattr(bot.settings,'sonarr_monitor') else True)
        #     title = data.get("title") or "Series"
        #     await interaction.followup.send(f"✅ Added **{title}** to Sonarr.", ephemeral=True)
        # except Exception as e:
        #     log.exception("Failed to add series: %s", e)
        #     await interaction.followup.send("❌ Failed to add the selected series (it might already exist or Sonarr refused).", ephemeral=True)
       # Start quality selection flow (no root folder prompt)
        view = QualityOnlySeriesView(tvdb_id, tmdb_id)
        profiles = await bot.sonarr.list_quality_profiles()
        select = QualitySelect(profiles, kind="series", payload={"tvdb_id": tvdb_id, "tmdb_id": tmdb_id})
        view.clear_items()
        view.add_item(select)
        await interaction.followup.send("Pick a quality profile:", view=view, ephemeral=True)

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
                        import traceback
                        traceback.print_exc()
            # merge sets for marking
            merged_tvdb = already_tvdb.intersection(plex_already_tvdb)
            merged_tmdb = already_tmdb.intersection(plex_already_tmdb)
            view = SeriesSelectView(results, merged_tvdb, merged_tmdb, monitored=True)
            await interaction.followup.send("Pick a result:", view=view, ephemeral=True)
        except Exception as e:
            log.exception("Search failed: %s", e)
            await interaction.followup.send("Search failed. Check Sonarr settings.", ephemeral=True)

    @app_commands.command(name="movie_status", description="Check the status of a movie in Radarr (and Transmission if downloading)")
    @app_commands.describe(query="Movie title to check")
    async def movie_status(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            results = await self.bot.radarr.search_movies(query)
        except Exception as e:
            log.exception("Radarr search failed: %s", e)
            await interaction.followup.send("Radarr search failed.", ephemeral=True)
            return
        if not results:
            await interaction.followup.send("No movies found.", ephemeral=True)
            return
        m = results[0]
        movie = await self.bot.radarr.get_movie_by_tmdb(m.tmdbId) if m.tmdbId else None
        if not movie:
            await interaction.followup.send("Not in Radarr yet.", ephemeral=True)
            return
        movie_id = movie["id"]
        downloaded = bool(movie.get("movieFile"))
        queue = await self.bot.radarr.get_queue()
        q = self.bot.radarr.summarize_queue_progress(queue, movie_id)
        t_line = None
        if q and self.bot.transmission and q.get("downloadId"):
            try:
                t = await self.bot.transmission.get_by_hash(q["downloadId"])
                if t:
                    t_line = f"{self.bot.transmission.human_status(t)} | {(t.get('percentDone',0.0)*100):.1f}% | {t.get('rateDownload',0)} B/s | eta {t.get('eta','?')}"
            except Exception:
                pass
        color = 0x2ecc71 if downloaded else (0xf39c12 if q else 0x95a5a6)
        embed = discord.Embed(title=f"{movie.get('title')} ({movie.get('year')})", color=color)
        state = "✅ Downloaded" if downloaded else ("⬇️ Downloading" if q else "❌ Missing")
        embed.add_field(name="State", value=state, inline=False)
        if q:
            pct = None
            if q.get("size"):
                try:
                    pct = 100 * (1 - (q.get("sizeleft",0)/q.get("size",1)))
                except Exception:
                    pct = None
            qline = f"{q.get('status','queue')}"
            if pct is not None:
                qline += f" | {pct:.1f}%"
            if q.get("timeleft"):
                qline += f" | time left {q.get('timeleft')}"
            embed.add_field(name="Queue", value=qline, inline=False)
        if t_line:
            embed.add_field(name="Transmission", value=t_line, inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="series_status", description="Check the status of a series in Sonarr (and Transmission if downloading)")
    @app_commands.describe(query="Series title to check")
    async def series_status(self, interaction: discord.Interaction, query: str):
        if not self.bot.sonarr:
            await interaction.response.send_message("Sonarr is not configured.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            results = await self.bot.sonarr.search_series(query)
        except Exception as e:
            log.exception("Sonarr search failed: %s", e)
            await interaction.followup.send("Sonarr search failed.", ephemeral=True)
            return
        if not results:
            await interaction.followup.send("No series found.", ephemeral=True)
            return
        s = results[0]
        series = await self.bot.sonarr.get_series_by_tvdb_or_tmdb(s.tvdbId, s.tmdbId)
        if not series:
            await interaction.followup.send("Not in Sonarr yet.", ephemeral=True)
            return
        series_id = series["id"]
        stats = self.bot.sonarr.summarize_series_progress(series)
        q_items = await self.bot.sonarr.get_queue()
        q_for_series = self.bot.sonarr.summarize_queue_for_series(q_items, series_id)
        t_line = None
        if q_for_series and self.bot.transmission:
            for qi in q_for_series:
                thash = qi.get("downloadId")
                if not thash:
                    continue
                try:
                    t = await self.bot.transmission.get_by_hash(thash)
                    if t:
                        t_line = f"{self.bot.transmission.human_status(t)} | {(t.get('percentDone',0.0)*100):.1f}% | {t.get('rateDownload',0)} B/s | eta {t.get('eta','?')}"
                        break
                except Exception:
                    pass
        pct = stats.get("percentOfEpisodes") or 0
        color = 0x2ecc71 if pct >= 99.9 else (0xf39c12 if q_for_series else 0x95a5a6)
        embed = discord.Embed(title=series.get("title"), color=color)
        embed.add_field(
            name="Progress",
            value=f"{stats.get('episodeFileCount',0)}/{stats.get('totalEpisodeCount',0)} episodes ({pct:.1f}%)",
            inline=False
        )
        if q_for_series:
            first = q_for_series[0]
            pct_q = None
            if first.get("size"):
                try:
                    pct_q = 100 * (1 - (first.get("sizeleft",0)/first.get("size",1)))
                except Exception:
                    pct_q = None
            qline = f"{first.get('status','queue')}"
            if pct_q is not None:
                qline += f" | {pct_q:.1f}%"
            if first.get("timeleft"):
                qline += f" | time left {first.get('timeleft')}"
            embed.add_field(name="Queue", value=qline, inline=False)
        if t_line:
            embed.add_field(name="Transmission", value=t_line, inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

async def create_bot(settings: Settings) -> SlavarrBot:
    global bot
    bot = SlavarrBot(settings=settings)
    await bot.add_cog(ContentCommands(bot))
    return bot

class QualityOnlySeriesView(discord.ui.View):
    def __init__(self, tvdb_id: int | None, tmdb_id: int | None, timeout: float | None = 120.0):
        super().__init__(timeout=timeout)
        self.tvdb_id = tvdb_id
        self.tmdb_id = tmdb_id

class QualitySelect(discord.ui.Select):
    def __init__(self, profiles: list[dict], kind: str, payload: dict):
        self.kind = kind
        self.payload = payload  # carries tmdb_id or tvdb/tmdb ids; we also include selected profile label to detect expectations
        options = [discord.SelectOption(label=p["name"][:100], value=f"{p['id']}|{p['name']}") for p in profiles[:25]]
        super().__init__(placeholder="Choose a quality profile…", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        assert isinstance(interaction.client, SlavarrBot)
        bot: SlavarrBot = interaction.client
        raw = self.values[0]
        qid_s, qlabel = raw.split("|", 1)
        qid = int(qid_s)
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            if self.kind == "movie":
                tmdb_id = self.payload["tmdb_id"]
                data = await bot.radarr.add_movie(
                    tmdb_id=tmdb_id,
                    quality_profile_id=qid,
                    root_folder_path=bot.settings.radarr_root_folder,
                    monitored=bot.settings.radarr_monitor,
                )
                title = data.get("title") or "Movie"
                # After successful add, validate releases for expected quality
                await maybe_offer_release_picker_for_movie(interaction, data["id"], expected_quality_label=qlabel)
            else:
                tvdb_id = self.payload.get("tvdb_id")
                tmdb_id = self.payload.get("tmdb_id")
                data = await bot.sonarr.add_series(
                    tvdb_id=tvdb_id,
                    tmdb_id=tmdb_id,
                    quality_profile_id=qid,
                    root_folder_path=bot.settings.sonarr_root_folder,
                    monitored=bot.settings.sonarr_monitor if hasattr(bot.settings,'sonarr_monitor') else True,
                )
                title = data.get("title") or "Series"
                # Pick a representative missing aired monitored episode
                ep = None
                try:
                    eps = await bot.sonarr.get_episode_list(data["id"])
                    ep = bot.sonarr.pick_missing_aired_monitored_episode(eps)
                except Exception:
                    ep = None
                await maybe_offer_release_picker_for_series(interaction, series_id=data["id"], episode=ep, expected_quality_label=qlabel)
        except Exception as e:
            log.exception("Add failed: %s", e)
            await interaction.followup.send("❌ Add failed (check quality profile or *arr config).", ephemeral=True)

# ============== Release fallback helpers & views ==============

async def maybe_offer_release_picker_for_movie(interaction: discord.Interaction, movie_id: int, expected_quality_label: str):
    """
    After a movie add, check releases cache. If none match expected quality, present a picker.
    """
    assert isinstance(interaction.client, SlavarrBot)
    bot: SlavarrBot = interaction.client
    try:
        releases = await bot.radarr.get_releases(movie_id)
    except Exception:
        releases = []
    matches = [r for r in releases if str(r.get("quality",{}).get("quality",{}).get("name","")).lower() == expected_quality_label.lower()]
    if matches:
        # success path
        await interaction.followup.send("✅ Added and releases match your profile.", ephemeral=True)
        return
    # Offer picker of available releases
    top = releases[:25]
    if not top:
        # trigger search to refresh
        try:
            await bot.radarr.trigger_movie_search(movie_id)
            await interaction.followup.send(f"ℹ️ No cached releases matched **{expected_quality_label}**. Triggered a fresh Radarr search; try again in a moment.", ephemeral=True)
        except Exception:
            await interaction.followup.send(f"ℹ️ No cached releases matched **{expected_quality_label}** and search could not be triggered.", ephemeral=True)
        return
    view = discord.ui.View(timeout=120)
    view.add_item(ReleaseSelect(kind="movie", options=top, payload={"movie_id": movie_id}))
    await interaction.followup.send(f"⚠️ No **{expected_quality_label}** releases found right now. Pick an available release to grab:", view=view, ephemeral=True)

async def maybe_offer_release_picker_for_series(interaction: discord.Interaction, series_id: int, episode: dict | None, expected_quality_label: str):
    """
    After a series add, check a representative episode's releases.
    """
    assert isinstance(interaction.client, SlavarrBot)
    bot: SlavarrBot = interaction.client
    if not episode:
        await interaction.followup.send("✅ Series added. (No missing aired episodes to validate releases.)", ephemeral=True)
        return
    try:
        releases = await bot.sonarr.get_releases_for_episode(episode["id"])
    except Exception:
        releases = []
    matches = [r for r in releases if str(r.get("quality",{}).get("quality",{}).get("name","")).lower() == expected_quality_label.lower()]
    if matches:
        await interaction.followup.send("✅ Series added and releases match your profile.", ephemeral=True)
        return
    top = releases[:25]
    if not top:
        try:
            await bot.sonarr.trigger_series_search(series_id)
            await interaction.followup.send(f"ℹ️ No cached releases matched **{expected_quality_label}**. Triggered a fresh Sonarr search; try again in a moment.", ephemeral=True)
        except Exception:
            await interaction.followup.send(f"ℹ️ No cached releases matched **{expected_quality_label}** and search could not be triggered.", ephemeral=True)
        return
    view = discord.ui.View(timeout=120)
    # carry both series and episode ids, Sonarr grabs by guid/indexerId independent of episode param
    view.add_item(ReleaseSelect(kind="series", options=top, payload={"series_id": series_id, "episode_id": episode["id"]}))
    await interaction.followup.send(f"⚠️ No **{expected_quality_label}** releases found right now. Pick an available release to grab:", view=view, ephemeral=True)

class ReleaseSelect(discord.ui.Select):
    """
    Presents available releases. On selection, we POST /release with guid + indexerId.
    """
    def __init__(self, kind: str, options: list[dict], payload: dict):
        self.kind = kind  # "movie" | "series"
        self.payload = payload
        select_opts: list[discord.SelectOption] = []
        for r in options[:25]:
            qname = r.get("quality",{}).get("quality",{}).get("name","?")
            indexer = r.get("indexer","?")
            size = r.get("size","")
            size_gb = f"{(size/1_000_000_000):.1f} GB" if isinstance(size,(int,float)) and size>0 else ""
            age = r.get("age","")
            label = f"{qname} • {indexer} • {size_gb}"
            # value encodes guid|indexerId
            val = f"{r.get('guid','')}|{r.get('indexerId',0)}"
            if val.split("|")[0]:
                select_opts.append(discord.SelectOption(label=label[:100], value=val))
        placeholder = "Choose a release to grab…"
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=select_opts or [discord.SelectOption(label="No releases available", value="")])

    async def callback(self, interaction: discord.Interaction):
        assert isinstance(interaction.client, SlavarrBot)
        bot: SlavarrBot = interaction.client
        if not self.values or not self.values[0]:
            await interaction.response.send_message("No releases to choose from.", ephemeral=True)
            return
        guid, idx = self.values[0].split("|", 1)
        indexer_id = int(idx)
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            if self.kind == "movie":
                await bot.radarr.post_release(guid, indexer_id)
            else:
                await bot.sonarr.post_release(guid, indexer_id)
            await interaction.followup.send("✅ Grabbed the selected release.", ephemeral=True)
        except Exception as e:
            log.exception("Grab failed: %s", e)
            # try to trigger a search and inform user
            try:
                if self.kind == "movie":
                    await bot.radarr.trigger_movie_search(self.payload.get("movie_id"))
                else:
                    await bot.sonarr.trigger_series_search(self.payload.get("series_id"))
                await interaction.followup.send("⚠️ Couldn’t grab from cache (maybe expired). Triggered a fresh search—try again shortly.", ephemeral=True)
            except Exception:
                await interaction.followup.send("❌ Couldn’t grab and couldn’t trigger a search. Please try again later.", ephemeral=True)