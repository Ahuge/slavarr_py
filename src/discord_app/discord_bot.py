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
        self.plex = (
            PlexClient(
                settings.plex_url,
                settings.plex_token,
                settings.plex_movies_section_id,
                settings.plex_shows_section_id,
            )
            if getattr(settings, "plex_url", None)
            and getattr(settings, "plex_token", None)
            else None
        )
        self.sonarr = (
            SonarrClient(settings.sonarr_url, settings.sonarr_api_key)
            if getattr(settings, "sonarr_url", None)
            else None
        )
        self.transmission = None
        if settings.transmission_url:
            self.transmission = TransmissionClient(
                settings.transmission_url,
                settings.transmission_user,
                settings.transmission_password,
            )
        self.engine = init_engine(settings.db_path)
        self.Session = make_session_factory(self.engine)

    async def setup_hook(self):
        # register slash commands globally
        await self.tree.sync()
        # Log invite URL
        perms = discord.Permissions(permissions=self.settings.invite_permissions)
        invite = discord.utils.oauth_url(
            client_id=self.settings.discord_client_id,
            scopes=("bot", "applications.commands"),
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
            options.append(
                discord.SelectOption(
                    label=label[:100], value=str(r.tmdbId), description=description
                )
            )
        super().__init__(
            placeholder="Select a movie to add…",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        tmdb_id = int(self.values[0])
        view: MovieSelectView = self.view  # type: ignore
        await view.add_selected(interaction, tmdb_id)


class MovieSelectView(discord.ui.View):
    def __init__(
        self,
        results: list[MovieResult],
        already: set[int],
        monitored: bool = True,
        timeout: float | None = 60.0,
    ):
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
            await interaction.followup.send(
                "ℹ️ That movie is already in Radarr.", ephemeral=True
            )
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
        await interaction.followup.send(
            "Pick a quality profile:", view=view, ephemeral=True
        )


class QualityOnlyMovieView(discord.ui.View):
    def __init__(self, tmdb_id: int, timeout: float | None = 120.0):
        super().__init__(timeout=timeout)
        self.tmdb_id = tmdb_id


# ===== Series Flow =====


class SeriesSelect(discord.ui.Select):
    def __init__(
        self,
        results: list[SeriesResult],
        already_tvdb: set[int],
        already_tmdb: set[int],
    ):
        options = []
        for r in results[:25]:
            id_label = r.tvdbId or r.tmdbId
            if not id_label:
                continue
            label = f"{r.title} ({r.year})" if r.year else r.title
            description = (r.overview or "")[:90]
            exists = (r.tvdbId in already_tvdb) or (
                r.tmdbId in already_tmdb if r.tmdbId else False
            )
            if exists:
                label = f"✅ {label}"
                description = "Already in Sonarr/Plex"
            # value encodes both ids: tvdb:xxx|tmdb:yyy
            value = f"tvdb:{r.tvdbId or 0}|tmdb:{r.tmdbId or 0}"
            options.append(
                discord.SelectOption(
                    label=label[:100], value=value, description=description
                )
            )
        super().__init__(
            placeholder="Select a series to add…",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        raw = self.values[0]
        parts = dict(p.split(":") for p in raw.split("|"))
        tvdb_id = int(parts.get("tvdb", "0"))
        tmdb_id = int(parts.get("tmdb", "0"))
        view: SeriesSelectView = self.view  # type: ignore
        await view.add_selected(
            interaction,
            tvdb_id if tvdb_id > 0 else None,
            tmdb_id if tmdb_id > 0 else None,
        )


class SeriesSelectView(discord.ui.View):
    def __init__(
        self,
        results: list[SeriesResult],
        already_tvdb: set[int],
        already_tmdb: set[int],
        monitored: bool = True,
        timeout: float | None = 60.0,
    ):
        super().__init__(timeout=timeout)
        self.results = results
        self.already_tvdb = already_tvdb
        self.already_tmdb = already_tmdb
        self.monitored = monitored
        self.add_item(SeriesSelect(results, already_tvdb, already_tmdb))

    async def add_selected(
        self, interaction: discord.Interaction, tvdb_id: int | None, tmdb_id: int | None
    ):
        assert isinstance(interaction.client, SlavarrBot)
        bot: SlavarrBot = interaction.client
        await interaction.response.defer(thinking=True, ephemeral=True)
        # Launch the Season + Quality wizard (works for new or existing series)
        profiles = await bot.sonarr.list_quality_profiles()
        # Gather base season list from lookup (for new) and per-season file counts if it already exists
        lookup = await bot.sonarr.series_lookup(tvdb_id, tmdb_id)
        existing = await bot.sonarr.get_series_by_tvdb_or_tmdb(tvdb_id, tmdb_id)
        existing_counts = await bot.sonarr.season_file_counts(existing["id"]) if existing else {}
        seasons_source = (existing.get("seasons") if existing else (lookup.get("seasons") if lookup else [])) or []
        view = SeriesAddWizardView(tvdb_id, tmdb_id, profiles, seasons_source, existing_counts, existing_id=(existing["id"] if existing else None))
        await interaction.followup.send("Pick a quality profile and the seasons you want:", view=view, ephemeral=True)


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
                        in_plex = await self.bot.plex.movie_exists(
                            tmdb_id=r.tmdbId,
                            imdb_id=r.imdbId,
                            title=r.title,
                            year=r.year,
                        )
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
            await interaction.followup.send(
                "Search failed. Check Radarr settings.", ephemeral=True
            )

    @app_commands.command(
        name="series_add", description="Search Sonarr and add a series"
    )
    @app_commands.describe(query="Series title to search")
    async def series_add(self, interaction: discord.Interaction, query: str):
        if not self.bot.sonarr:
            await interaction.response.send_message(
                "Sonarr is not configured.", ephemeral=True
            )
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
                    existing = await self.bot.sonarr.get_existing_by_ids(
                        tvdb_id, tmdb_id
                    )
                    if existing:
                        if tvdb_id:
                            already_tvdb.add(tvdb_id)
                        if tmdb_id:
                            already_tmdb.add(tmdb_id)
                except Exception:
                    pass
                # Plex check
                if self.bot.plex and (r.tvdbId or r.tmdbId):
                    try:
                        in_plex_series = await self.bot.plex.series_exists(
                            tvdb_id=r.tvdbId,
                            tmdb_id=r.tmdbId,
                            title=r.title,
                            year=r.year,
                            series_section_id=getattr(
                                self.bot.settings, "plex_series_section_id", None
                            ),
                        )
                        if in_plex_series:
                            if r.tvdbId:
                                plex_already_tvdb.add(r.tvdbId)
                            if r.tmdbId:
                                plex_already_tmdb.add(r.tmdbId)
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
            await interaction.followup.send(
                "Search failed. Check Sonarr settings.", ephemeral=True
            )

    @app_commands.command(
        name="movie_status",
        description="Check the status of a movie in Radarr (and Transmission if downloading)",
    )
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
        color = 0x2ECC71 if downloaded else (0xF39C12 if q else 0x95A5A6)
        embed = discord.Embed(
            title=f"{movie.get('title')} ({movie.get('year')})", color=color
        )
        state = (
            "✅ Downloaded" if downloaded else ("⬇️ Downloading" if q else "❌ Missing")
        )
        embed.add_field(name="State", value=state, inline=False)
        if q:
            pct = None
            if q.get("size"):
                try:
                    pct = 100 * (1 - (q.get("sizeleft", 0) / q.get("size", 1)))
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

    @app_commands.command(
        name="series_status",
        description="Check the status of a series in Sonarr (and Transmission if downloading)",
    )
    @app_commands.describe(query="Series title to check")
    async def series_status(self, interaction: discord.Interaction, query: str):
        if not self.bot.sonarr:
            await interaction.response.send_message(
                "Sonarr is not configured.", ephemeral=True
            )
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
        color = 0x2ECC71 if pct >= 99.9 else (0xF39C12 if q_for_series else 0x95A5A6)
        embed = discord.Embed(title=series.get("title"), color=color)
        embed.add_field(
            name="Progress",
            value=f"{stats.get('episodeFileCount',0)}/{stats.get('totalEpisodeCount',0)} episodes ({pct:.1f}%)",
            inline=False,
        )
        if q_for_series:
            first = q_for_series[0]
            pct_q = None
            if first.get("size"):
                try:
                    pct_q = 100 * (
                        1 - (first.get("sizeleft", 0) / first.get("size", 1))
                    )
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

class SeriesAddWizardView(discord.ui.View):
    """
    Combined UI: choose quality profile + one or more seasons, then confirm.
    If the series exists, we update monitored seasons and optionally profile;
    if new, we add with only the selected seasons monitored.
    """
    def __init__(self, tvdb_id: int | None, tmdb_id: int | None, profiles: list[dict], seasons_source: list[dict], season_counts: dict[int, dict], existing_id: int | None, timeout: float | None = 180.0):
        super().__init__(timeout=timeout)
        self.tvdb_id = tvdb_id
        self.tmdb_id = tmdb_id
        self.profiles = profiles
        self.seasons_source = seasons_source
        self.season_counts = season_counts
        self.existing_id = existing_id
        self.selected_quality_id: int | None = None
        self.selected_seasons: set[int] = set()
        self.add_item(SeriesQualitySelect(profiles))
        self.add_item(SeasonMultiSelect(seasons_source, season_counts))
        self.add_item(ConfirmSeriesAddButton())

class SeriesQualitySelect(discord.ui.Select):
    def __init__(self, profiles: list[dict]):
        options = [discord.SelectOption(label=p["name"][:100], value=f"{p['id']}|{p['name']}") for p in profiles[:25]]
        super().__init__(placeholder="Choose a quality profile…", min_values=1, max_values=1, options=options)
    async def callback(self, interaction: discord.Interaction):
        view: SeriesAddWizardView = self.view  # type: ignore
        qid_s, qlabel = self.values[0].split("|", 1)
        view.selected_quality_id = int(qid_s)
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(f"Quality set to **{qlabel}**. Now select seasons and hit **Add/Update**.", ephemeral=True)

class SeasonMultiSelect(discord.ui.Select):
    """
    Multiselect of seasons; labels show how many episodes already have files.
    """
    def __init__(self, seasons_source: list[dict], season_counts: dict[int, dict]):
        opts: list[discord.SelectOption] = []
        for s in seasons_source:
            num = s.get("seasonNumber")
            if num is None:
                continue
            counts = season_counts.get(num, {"total": 0, "have": 0})
            total, have = counts.get("total", 0), counts.get("have", 0)
            status = "✅" if total and have >= total else ("➖" if have > 0 else "○")
            label = f"Season {num}  {status}  ({have}/{total} eps)"
            opts.append(discord.SelectOption(label=label[:100], value=str(num)))
        placeholder = "Select one or more seasons…"
        super().__init__(placeholder=placeholder, min_values=1 if opts else 0, max_values=min(25, len(opts) or 1), options=opts or [discord.SelectOption(label="No seasons", value="")])
    async def callback(self, interaction: discord.Interaction):
        view: SeriesAddWizardView = self.view  # type: ignore
        view.selected_seasons = set(int(v) for v in self.values if v.isdigit())
        await interaction.response.defer(ephemeral=True)
        pretty = ", ".join(sorted([f"S{n}" for n in view.selected_seasons], key=lambda x: int(x[1:])))
        await interaction.followup.send(f"Selected seasons: {pretty or '(none)'}", ephemeral=True)

class ConfirmSeriesAddButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Add / Update Series", style=discord.ButtonStyle.success)
    async def callback(self, interaction: discord.Interaction):
        assert isinstance(interaction.client, SlavarrBot)
        bot: SlavarrBot = interaction.client
        view: SeriesAddWizardView = self.view  # type: ignore
        await interaction.response.defer(thinking=True, ephemeral=True)
        if not view.selected_quality_id:
            await interaction.followup.send("Please choose a quality profile first.", ephemeral=True)
            return
        # Build monitored seasons array
        seasons_override = bot.sonarr.build_monitored_seasons(view.seasons_source, view.selected_seasons)
        try:
            if view.existing_id:
                # Update existing: set quality + monitored flags, then search selected seasons
                series = await bot.sonarr.get_series_by_id(view.existing_id)
                if not series:
                    await interaction.followup.send("Could not load existing series.", ephemeral=True)
                    return
                series["qualityProfileId"] = view.selected_quality_id
                series["seasons"] = seasons_override
                await bot.sonarr.update_series(series)
                # Trigger searches for each selected season
                for sn in view.selected_seasons:
                    try:
                        await bot.sonarr.season_search(view.existing_id, sn)
                    except Exception:
                        pass
                await interaction.followup.send("✅ Series updated with selected seasons and profile.", ephemeral=True)
            else:
                # New add with selected seasons monitored only
                data = await bot.sonarr.add_series(
                    tvdb_id=view.tvdb_id,
                    tmdb_id=view.tmdb_id,
                    quality_profile_id=view.selected_quality_id,
                    root_folder_path=bot.settings.sonarr_root_folder,
                    monitored=True,
                    seasons_override=seasons_override,
                )
                series_view = TrackSeriesView(series_id=data["id"])
                msg = await interaction.followup.send(
                    "✅ Series added with selected seasons monitored. Tracking started:",
                    view=series_view,
                    ephemeral=True
                )
                await series_view.start_auto_update(interaction, msg)
        except Exception as e:
            log.exception("Series add/update failed: %s", e)
            await interaction.followup.send("❌ Failed to add/update the series. Please check Sonarr config.", ephemeral=True)


# ===================== Request Tracking (Live Updates) =====================

def _progress_bar(pct: float | None, width: int = 20) -> str:
    if pct is None:
        return "∙" * width
    pct = max(0.0, min(100.0, pct))
    filled = int(round((pct / 100.0) * width))
    return "█" * filled + "░" * (width - filled)

def _first_poster(item: dict) -> str | None:
    """
    Try to extract a poster URL from *arr entity images.
    Prefer remoteUrl, fall back to url.
    """
    imgs = item.get("images") or []
    for im in imgs:
        if im.get("coverType") == "poster":
            return im.get("remoteUrl") or im.get("url")
    return None

async def _render_movie_embed(bot: "SlavarrBot", movie_id: int) -> tuple[discord.Embed, bool]:
    """Build a rich embed for a movie; returns (embed, done)."""
    # library state
    movie = await bot.radarr.get_movie_by_id(movie_id)
    if not movie:
        emb = discord.Embed(title="Movie", description="⚠️ Movie not found in Radarr.", color=0xe74c3c)
        return emb, True
    title = f"{movie.get('title')} ({movie.get('year')})"
    downloaded = bool(movie.get("movieFile"))
    # queue state
    q = bot.radarr.summarize_queue_progress(await bot.radarr.get_queue(), movie_id)
    pct = None
    eta = None
    if q and q.get("size"):
        try:
            pct = 100 * (1 - (q.get("sizeleft",0)/q.get("size",1)))
        except Exception:
            pct = None
        eta = q.get("timeleft")
    t_details = None
    if q and bot.transmission and q.get("downloadId"):
        try:
            t = await bot.transmission.get_by_hash(q["downloadId"])
            if t:
                t_pct = (t.get("percentDone",0.0)*100.0)
                t_rate = t.get("rateDownload",0)
                t_eta = t.get("eta","?")
                t_details = f"{bot.transmission.human_status(t)} • {t_pct:.1f}% • {t_rate} B/s • eta {t_eta}"
        except Exception:
            pass
    color = 0x2ecc71 if downloaded else (0xf39c12 if q else 0x95a5a6)
    emb = discord.Embed(title=title, color=color)
    poster = _first_poster(movie)
    if poster:
        emb.set_thumbnail(url=poster)
    if downloaded:
        emb.add_field(name="State", value="✅ Downloaded", inline=False)
        return emb, True
    if q:
        bar = _progress_bar(pct)
        eta_txt = f" • ETA {eta}" if eta else ""
        emb.add_field(name="State", value="⬇️ Downloading", inline=True)
        emb.add_field(name="Progress", value=f"`{bar}` {pct:.1f if pct is not None else 0:.1f}％{eta_txt}", inline=False)
        if t_details:
            emb.add_field(name="Transmission", value=t_details, inline=False)
        return emb, False
    emb.add_field(name="State", value="🕘 Queued / Waiting for a matching release", inline=False)
    return emb, False


async def _render_series_embed(bot: "SlavarrBot", series_id: int) -> tuple[discord.Embed, bool]:
    """Series-wide progress embed; done when nearly complete or no queue."""
    series = await bot.sonarr.get_series_by_id(series_id) if bot.sonarr else None
    if not series:
        return "⚠️ Series not found in Sonarr.", True
        emb = discord.Embed(title="Series", description="⚠️ Series not found in Sonarr.", color=0xe74c3c)
        return emb, True
    stats = bot.sonarr.summarize_series_progress(series)
    have = stats.get("episodeFileCount",0)
    total = stats.get("totalEpisodeCount",0)
    pct = stats.get("percentOfEpisodes") or (100.0 * have / total if total else 0.0)
    q_items = await bot.sonarr.get_queue()
    active = bot.sonarr.summarize_queue_for_series(q_items, series_id)
    title = series.get("title")
    bar = _progress_bar(pct)
    color = 0x2ecc71 if pct >= 99.9 else (0xf39c12 if active else 0x95a5a6)
    emb = discord.Embed(title=title, color=color)
    poster = _first_poster(series)
    if poster:
        emb.set_thumbnail(url=poster)
    emb.add_field(name="Progress", value=f"`{bar}` {pct:.1f}%  ({have}/{total} eps)", inline=False)
    if active:
        # try to enrich first item with Transmission
        t_details = None
        if bot.transmission:
            for qi in active:
                if qi.get("downloadId"):
                    try:
                        t = await bot.transmission.get_by_hash(qi["downloadId"])
                        if t:
                            t_pct = (t.get("percentDone",0.0)*100.0)
                            t_rate = t.get("rateDownload",0)
                            t_eta = t.get("eta","?")
                            t_details = f"{bot.transmission.human_status(t)} • {t_pct:.1f}% • {t_rate} B/s • eta {t_eta}"
                            break
                    except Exception:
                        pass
        emb.add_field(name="State", value="⬇️ Downloading", inline=True)
        if t_details:
            emb.add_field(name="Transmission", value=t_details, inline=False)
        return emb, False
    # done when ~complete or nothing actively downloading; Sonarr may still index new eps later
    done = pct >= 99.9
    emb.add_field(name="State", value=("✅ Complete" if done else "🕘 Waiting / Idle"), inline=True)
    return emb, done

class TrackMovieView(discord.ui.View):
    def __init__(self, movie_id: int, timeout: float | None = 300.0):
        super().__init__(timeout=timeout)
        self.movie_id = movie_id
        self._task: asyncio.Task | None = None
        self._stopped = False
        self._message_id: int | None = None
        self.add_item(RefreshMovieButton())
        self.add_item(StopTrackingButton())

    async def on_timeout(self) -> None:
        try:
            # When view times out, do nothing (components will disable automatically in Discord)
            pass
        except Exception:
            pass

    async def start_auto_update(self, interaction: discord.Interaction, message: discord.Message,
                                interval_sec: int = 10, max_iters: int = 30):
        """Kick off a background loop editing the same ephemeral message."""
        self._message_id = message.id
        if self._task and not self._task.done():
            return

        async def _loop():
            it = 0
            while it < max_iters and not self._stopped:
                emb, done = await _render_movie_embed(interaction.client, self.movie_id)  # type: ignore
                try:
                    await interaction.followup.edit_message(self._message_id, embed=emb, view=self)
                except Exception:
                    # swallow edit errors (ephemeral lifecycle etc.)
                    return
                if done:
                    return
                it += 1
                await asyncio.sleep(interval_sec)

        self._task = asyncio.create_task(_loop())

class RefreshMovieButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Refresh now", style=discord.ButtonStyle.primary)
    async def callback(self, interaction: discord.Interaction):
        bot: SlavarrBot = interaction.client  # type: ignore
        view: TrackMovieView = self.view  # type: ignore
        await interaction.response.defer(thinking=True, ephemeral=True)
        emb, done = await _render_movie_embed(bot, view.movie_id)
        if view._message_id:
            try:
                await interaction.followup.edit_message(view._message_id, embed=emb, view=view)
            except Exception:
                pass
        else:
            await interaction.followup.send(embed=emb, ephemeral=True)

class StopTrackingButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Stop tracking", style=discord.ButtonStyle.danger)
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        # Disable the view components
        v: discord.ui.View = self.view  # type: ignore
        # signal loop to stop
        if hasattr(v, "_stopped"):
            v._stopped = True  # type: ignore
        for item in v.children:
            item.disabled = True
        await interaction.edit_original_response(view=v)
        await interaction.followup.send("🛑 Tracking stopped.", ephemeral=True)

class TrackSeriesView(discord.ui.View):
    def __init__(self, series_id: int, timeout: float | None = 300.0):
        super().__init__(timeout=timeout)
        self.series_id = series_id
        self._task: asyncio.Task | None = None
        self._stopped = False
        self._message_id: int | None = None
        self.add_item(RefreshSeriesButton())
        self.add_item(StopTrackingButton())

    async def start_auto_update(self, interaction: discord.Interaction, message: discord.Message,
                                interval_sec: int = 10, max_iters: int = 30):
        self._message_id = message.id
        if self._task and not self._task.done():
            return

        async def _loop():
            it = 0
            while it < max_iters and not self._stopped:
                emb, done = await _render_series_embed(interaction.client, self.series_id)  # type: ignore
                try:
                    await interaction.followup.edit_message(self._message_id, embed=emb, view=self)
                except Exception:
                    return
                if done:
                    return
                it += 1
                await asyncio.sleep(interval_sec)

        self._task = asyncio.create_task(_loop())

class RefreshSeriesButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Refresh now", style=discord.ButtonStyle.primary)
    async def callback(self, interaction: discord.Interaction):
        bot: SlavarrBot = interaction.client  # type: ignore
        view: TrackSeriesView = self.view  # type: ignore
        await interaction.response.defer(thinking=True, ephemeral=True)
        emb, done = await _render_series_embed(bot, view.series_id)
        if view._message_id:
            try:
                await interaction.followup.edit_message(view._message_id, embed=emb, view=view)
            except Exception:
                pass
        else:
            await interaction.followup.send(embed=emb, ephemeral=True)


async def create_bot(settings: Settings) -> SlavarrBot:
    global bot
    bot = SlavarrBot(settings=settings)
    await bot.add_cog(ContentCommands(bot))
    return bot


class QualityOnlySeriesView(discord.ui.View):
    def __init__(
        self, tvdb_id: int | None, tmdb_id: int | None, timeout: float | None = 120.0
    ):
        super().__init__(timeout=timeout)
        self.tvdb_id = tvdb_id
        self.tmdb_id = tmdb_id


class QualitySelect(discord.ui.Select):
    def __init__(self, profiles: list[dict], kind: str, payload: dict):
        self.kind = kind
        self.payload = payload  # carries tmdb_id or tvdb/tmdb ids; we also include selected profile label to detect expectations
        options = [
            discord.SelectOption(label=p["name"][:100], value=f"{p['id']}|{p['name']}")
            for p in profiles[:25]
        ]
        super().__init__(
            placeholder="Choose a quality profile…",
            min_values=1,
            max_values=1,
            options=options,
        )

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
                # After successful add, offer tracking (with background updates) + validate releases
                movie_view = TrackMovieView(movie_id=data["id"])
                msg = await interaction.followup.send(
                    content="🎬 Request added. Tracking started:",
                    view=movie_view,
                    ephemeral=True
                )
                await movie_view.start_auto_update(interaction, msg)
                await maybe_offer_release_picker_for_movie(interaction, data["id"], expected_quality_label=qlabel)
            else:
                tvdb_id = self.payload.get("tvdb_id")
                tmdb_id = self.payload.get("tmdb_id")
                data = await bot.sonarr.add_series(
                    tvdb_id=tvdb_id,
                    tmdb_id=tmdb_id,
                    quality_profile_id=qid,
                    root_folder_path=bot.settings.sonarr_root_folder,
                    monitored=bot.settings.sonarr_monitor
                    if hasattr(bot.settings, "sonarr_monitor")
                    else True,
                )
                title = data.get("title") or "Series"
                # Pick a representative missing aired monitored episode
                ep = None
                try:
                    eps = await bot.sonarr.get_episode_list(data["id"])
                    ep = bot.sonarr.pick_missing_aired_monitored_episode(eps)
                except Exception:
                    ep = None
                # Offer tracking (series-wide) with background updates, then fallback picker if needed
                series_view = TrackSeriesView(series_id=data["id"])
                msg = await interaction.followup.send(
                    content="📺 Series added. Tracking started:",
                    view=series_view,
                    ephemeral=True
                )
                await series_view.start_auto_update(interaction, msg)
                await maybe_offer_release_picker_for_series(
                    interaction,
                    series_id=data["id"],
                    episode=ep,
                    expected_quality_label=qlabel
                )
        except Exception as e:
            log.exception("Add failed: %s", e)
            await interaction.followup.send(
                "❌ Add failed (check quality profile or *arr config).", ephemeral=True
            )


# ============== Release fallback helpers & views ==============


async def maybe_offer_release_picker_for_movie(
    interaction: discord.Interaction, movie_id: int, expected_quality_label: str
):
    """
    After a movie add, check releases cache. If none match expected quality, present a picker.
    """
    assert isinstance(interaction.client, SlavarrBot)
    bot: SlavarrBot = interaction.client
    try:
        releases = await bot.radarr.get_releases(movie_id)
    except Exception:
        releases = []
    matches = [
        r
        for r in releases
        if str(r.get("quality", {}).get("quality", {}).get("name", "")).lower()
        == expected_quality_label.lower()
    ]
    if matches:
        # success path
        await interaction.followup.send(
            "✅ Added and releases match your profile.", ephemeral=True
        )
        return
    # Offer picker of available releases
    top = releases[:25]
    if not top:
        # trigger search to refresh
        try:
            await bot.radarr.trigger_movie_search(movie_id)
            await interaction.followup.send(
                f"ℹ️ No cached releases matched **{expected_quality_label}**. Triggered a fresh Radarr search; try again in a moment.",
                ephemeral=True,
            )
        except Exception:
            await interaction.followup.send(
                f"ℹ️ No cached releases matched **{expected_quality_label}** and search could not be triggered.",
                ephemeral=True,
            )
        return
    view = discord.ui.View(timeout=120)
    view.add_item(
        ReleaseSelect(kind="movie", options=top, payload={"movie_id": movie_id})
    )
    await interaction.followup.send(
        f"⚠️ No **{expected_quality_label}** releases found right now. Pick an available release to grab:",
        view=view,
        ephemeral=True,
    )


async def maybe_offer_release_picker_for_series(
    interaction: discord.Interaction,
    series_id: int,
    episode: dict | None,
    expected_quality_label: str,
):
    """
    After a series add, check a representative episode's releases.
    """
    assert isinstance(interaction.client, SlavarrBot)
    bot: SlavarrBot = interaction.client
    if not episode:
        await interaction.followup.send(
            "✅ Series added. (No missing aired episodes to validate releases.)",
            ephemeral=True,
        )
        return
    try:
        releases = await bot.sonarr.get_releases_for_episode(episode["id"])
    except Exception:
        releases = []
    matches = [
        r
        for r in releases
        if str(r.get("quality", {}).get("quality", {}).get("name", "")).lower()
        == expected_quality_label.lower()
    ]
    if matches:
        await interaction.followup.send(
            "✅ Series added and releases match your profile.", ephemeral=True
        )
        return
    top = releases[:25]
    if not top:
        try:
            await bot.sonarr.trigger_series_search(series_id)
            await interaction.followup.send(
                f"ℹ️ No cached releases matched **{expected_quality_label}**. Triggered a fresh Sonarr search; try again in a moment.",
                ephemeral=True,
            )
        except Exception:
            await interaction.followup.send(
                f"ℹ️ No cached releases matched **{expected_quality_label}** and search could not be triggered.",
                ephemeral=True,
            )
        return
    view = discord.ui.View(timeout=120)
    # carry both series and episode ids, Sonarr grabs by guid/indexerId independent of episode param
    view.add_item(
        ReleaseSelect(
            kind="series",
            options=top,
            payload={"series_id": series_id, "episode_id": episode["id"]},
        )
    )
    await interaction.followup.send(
        f"⚠️ No **{expected_quality_label}** releases found right now. Pick an available release to grab:",
        view=view,
        ephemeral=True,
    )


class ReleaseSelect(discord.ui.Select):
    """
    Presents available releases. On selection, we POST /release with guid + indexerId.
    """

    def __init__(self, kind: str, options: list[dict], payload: dict):
        self.kind = kind  # "movie" | "series"
        self.payload = payload
        select_opts: list[discord.SelectOption] = []
        for r in options[:25]:
            qname = r.get("quality", {}).get("quality", {}).get("name", "?")
            indexer = r.get("indexer", "?")
            size = r.get("size", "")
            size_gb = (
                f"{(size/1_000_000_000):.1f} GB"
                if isinstance(size, (int, float)) and size > 0
                else ""
            )
            age = r.get("age", "")
            label = f"{qname} • {indexer} • {size_gb}"
            # value encodes guid|indexerId
            val = f"{r.get('guid','')}|{r.get('indexerId',0)}"
            if val.split("|")[0]:
                select_opts.append(discord.SelectOption(label=label[:100], value=val))
        placeholder = "Choose a release to grab…"
        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=select_opts
            or [discord.SelectOption(label="No releases available", value="")],
        )

    async def callback(self, interaction: discord.Interaction):
        assert isinstance(interaction.client, SlavarrBot)
        bot: SlavarrBot = interaction.client
        if not self.values or not self.values[0]:
            await interaction.response.send_message(
                "No releases to choose from.", ephemeral=True
            )
            return
        guid, idx = self.values[0].split("|", 1)
        indexer_id = int(idx)
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            if self.kind == "movie":
                await bot.radarr.post_release(guid, indexer_id)
            else:
                await bot.sonarr.post_release(guid, indexer_id)
            await interaction.followup.send(
                "✅ Grabbed the selected release.", ephemeral=True
            )
        except Exception as e:
            log.exception("Grab failed: %s", e)
            # try to trigger a search and inform user
            try:
                if self.kind == "movie":
                    await bot.radarr.trigger_movie_search(self.payload.get("movie_id"))
                else:
                    await bot.sonarr.trigger_series_search(
                        self.payload.get("series_id")
                    )
                await interaction.followup.send(
                    "⚠️ Couldn’t grab from cache (maybe expired). Triggered a fresh search—try again shortly.",
                    ephemeral=True,
                )
            except Exception:
                await interaction.followup.send(
                    "❌ Couldn’t grab and couldn’t trigger a search. Please try again later.",
                    ephemeral=True,
                )
