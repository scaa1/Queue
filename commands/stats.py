# commands/stats.py
"""
Statistics and leaderboard commands for the volleyball bot.
Generates image-based stats cards using Pillow/matplotlib.
"""

import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional
import json
import io

from views import LeaderboardView
from views.stats_views import StatsView, CompareView
from utils import create_error_embed
from config import is_5v5_region, get_region_team_size
from stats_card import generate_stats_card, generate_compare_card, generate_leaderboard_card


async def _get_avatar_bytes(user: discord.User) -> bytes:
    """Download a user's avatar as bytes."""
    try:
        asset = user.display_avatar.with_size(128).with_format('png')
        return await asset.read()
    except Exception:
        return None


async def _get_rank_role_info(bot, guild_id, avg_elo):
    """Get the current rank role name and thresholds for a player's avg ELO."""
    mappings_v2 = await bot.db.get_all_elo_role_mappings_v2(guild_id)
    if not mappings_v2:
        return None, None, None

    # Filter to 6v6 queue type only for rank display
    mappings = [(m[0], m[1], m[2]) for m in mappings_v2 if m[3] == '6v6']
    if not mappings:
        return None, None, None

    all_thresholds = sorted(set(m[1] for m in mappings))

    current_threshold = None
    next_threshold = None
    current_role_id = None

    for i, threshold in enumerate(all_thresholds):
        if avg_elo >= threshold:
            current_threshold = threshold
            for m in mappings:
                if m[1] == threshold:
                    current_role_id = m[2]
                    break
            if i + 1 < len(all_thresholds):
                next_threshold = all_thresholds[i + 1]
            else:
                next_threshold = None

    if current_role_id is None:
        if all_thresholds:
            next_threshold = all_thresholds[0]
        return None, None, next_threshold

    return current_role_id, current_threshold, next_threshold


async def _resolve_role_name(bot, guild_id, role_id):
    """Resolve a role ID to its name."""
    if role_id is None:
        return "Unranked"
    guild = bot.get_guild(guild_id)
    if guild:
        role = guild.get_role(role_id)
        if role:
            return role.name
    return "Unranked"


async def _resolve_role_color(bot, guild_id, role_id):
    """Resolve a role ID to its color as an RGB tuple."""
    if role_id is None:
        return None
    guild = bot.get_guild(guild_id)
    if guild:
        role = guild.get_role(role_id)
        if role and role.color and role.color.value != 0:
            return (role.color.r, role.color.g, role.color.b)
    return None


async def _build_recent_matches(bot, guild_id, user_id, limit=5, queue_type=None, season_id=None):
    """Build recent match data for the stats card, optionally filtered by queue type and season."""
    history = await bot.db.get_elo_history(guild_id, user_id, queue_type=queue_type, limit=limit, latest=True, season_id=season_id)
    if not history:
        return None

    recent = []
    for h in history:
        match_id, qt, pos, elo_before, elo_after, elo_change, is_winner, ts = h
        # For 2v2/3v3 queues, use queue_type as the label instead of player position
        if qt in ('2v2', '3v3', 'highrank_2v2', 'highrank_3v3'):
            recent.append((match_id, bool(is_winner), elo_change, qt))
        else:
            recent.append((match_id, bool(is_winner), elo_change, pos or qt))
    return recent


async def _build_tier_roles(bot, guild_id):
    """Build tier role data for progress bars."""
    mappings_v2 = await bot.db.get_all_elo_role_mappings_v2(guild_id)
    if not mappings_v2:
        return None

    # Filter to 6v6 queue type only for tier bars
    mappings = [(m[0], m[1], m[2]) for m in mappings_v2 if m[3] == '6v6']
    if not mappings:
        return None

    guild = bot.get_guild(guild_id)
    if not guild:
        return None

    # Group by threshold, preferring "all" position mappings for display
    threshold_map = {}
    for position, threshold, role_id in mappings:
        if threshold not in threshold_map or position == "all":
            threshold_map[threshold] = role_id

    all_thresholds = sorted(threshold_map.keys())

    tier_roles = []
    for i, threshold in enumerate(all_thresholds):
        role_id = threshold_map[threshold]
        role = guild.get_role(role_id)
        role_name = role.name if role else f"Role {role_id}"
        role_color = None
        if role and role.color and role.color.value != 0:
            role_color = (role.color.r, role.color.g, role.color.b)

        next_thresh = all_thresholds[i + 1] if i + 1 < len(all_thresholds) else None
        tier_roles.append((role_name, threshold, next_thresh, "6v6", role_color))

    return tier_roles if tier_roles else None


async def _gather_stats_data(bot, interaction, user, region=None, season_id=None, season_2v2_id=None, season_3v3_id=None):
    """Gather all stats data for a user into a dict.
    If region is specified, reads from regional tables for ELO data.
    If season_id is specified, reads season-specific stats.
    season_2v2_id/season_3v3_id allow per-queue-type season lookups.
    """
    config = await bot.db.get_config(interaction.guild.id)
    current_starting_elo = config["starting_elo"]

    # Determine effective region: explicit param > player's stored region
    user_region = region or await bot.db.get_player_region(interaction.guild.id, user.id)
    user_is_5v5 = is_5v5_region(config, user_region) if user_region else False
    display_region = user_region  # always show the player's region on card

    ds_elo = fs_elo = s_elo = l_elo = current_starting_elo
    games = wins = losses = 0
    ds_games = fs_games = s_games = l_games = 0
    ws = ls = best_ws = best_ls = 0

    if region and not season_id:
        # Read from regional tables when region is explicitly specified (no season)
        regional_stats = await bot.db.get_player_regional_stats(interaction.guild.id, user.id, region)
        if regional_stats:
            ds_elo, fs_elo, s_elo, l_elo, games, wins, losses = regional_stats[:7]
            ws, ls, best_ws, best_ls = regional_stats[7:11]
        # Position games from global (no regional position_stats table)
        ds_games = await bot.db.get_position_games_played(interaction.guild.id, user.id, "Defense Specialist")
        fs_games = await bot.db.get_position_games_played(interaction.guild.id, user.id, "Front Spiker")
        s_games = await bot.db.get_position_games_played(interaction.guild.id, user.id, "Setter")
        l_games = await bot.db.get_position_games_played(interaction.guild.id, user.id, "Libero")
    else:
        stats = await bot.db.get_player_stats(interaction.guild.id, user.id, season_id)
        if stats:
            ds_elo, fs_elo, s_elo, l_elo, games, wins, losses = stats
            ds_games = await bot.db.get_position_games_played(interaction.guild.id, user.id, "Defense Specialist", season_id)
            fs_games = await bot.db.get_position_games_played(interaction.guild.id, user.id, "Front Spiker", season_id)
            s_games = await bot.db.get_position_games_played(interaction.guild.id, user.id, "Setter", season_id)
            l_games = await bot.db.get_position_games_played(interaction.guild.id, user.id, "Libero", season_id)
            streaks = await bot.db.get_player_streaks(interaction.guild.id, user.id, '6v6')
            ws, ls, best_ws, best_ls = streaks

    # For season stats: if we have a season, use all-time ELO for positions where
    # the player has 0 season games and the season ELO is just a default value.
    # This ensures admin-adjusted ELOs are reflected.
    if season_id:
        all_time_stats = await bot.db.get_player_stats(interaction.guild.id, user.id)
        if all_time_stats:
            at_ds, at_fs, at_s, at_l, at_g, at_w, at_lo = all_time_stats
            default_elos = {current_starting_elo, 1000}  # config starting + table default
            positions_list = ["Defense Specialist", "Front Spiker", "Setter", "Libero"]
            # Per-position: if no season games and season ELO is a default, use all-time
            if ds_games == 0 and ds_elo in default_elos:
                ds_elo = at_ds
                at_gp = await bot.db.get_position_games_played(interaction.guild.id, user.id, positions_list[0])
                if at_gp > 0:
                    ds_games = at_gp
            if fs_games == 0 and fs_elo in default_elos:
                fs_elo = at_fs
                at_gp = await bot.db.get_position_games_played(interaction.guild.id, user.id, positions_list[1])
                if at_gp > 0:
                    fs_games = at_gp
            if s_games == 0 and s_elo in default_elos:
                s_elo = at_s
                at_gp = await bot.db.get_position_games_played(interaction.guild.id, user.id, positions_list[2])
                if at_gp > 0:
                    s_games = at_gp
            if l_games == 0 and l_elo in default_elos:
                l_elo = at_l
                at_gp = await bot.db.get_position_games_played(interaction.guild.id, user.id, positions_list[3])
                if at_gp > 0:
                    l_games = at_gp
            # If no season games at all, also pull W/L from all-time
            if games == 0 and at_g > 0:
                games, wins, losses = at_g, at_w, at_lo

    # Highest ELO — include positions with games played or admin-set ELO
    played_elos = []
    if ds_games > 0 or ds_elo != current_starting_elo: played_elos.append(ds_elo)
    if fs_games > 0 or fs_elo != current_starting_elo: played_elos.append(fs_elo)
    if s_games > 0 or s_elo != current_starting_elo: played_elos.append(s_elo)
    if (l_games > 0 or l_elo != current_starting_elo) and not user_is_5v5: played_elos.append(l_elo)
    highest_elo = max(played_elos) if played_elos else current_starting_elo

    # Rank info — always use all-time ELO for rank display (not season-specific)
    # This ensures rank/role shows correctly even when viewing season stats
    rank_elo_for_role = highest_elo
    if season_id:
        # Use the player's current all-time highest ELO for rank display
        all_time_for_rank = await bot.db.get_player_stats(interaction.guild.id, user.id)
        if all_time_for_rank:
            at_played = []
            at_ds_g = await bot.db.get_position_games_played(interaction.guild.id, user.id, "Defense Specialist")
            at_fs_g = await bot.db.get_position_games_played(interaction.guild.id, user.id, "Front Spiker")
            at_s_g = await bot.db.get_position_games_played(interaction.guild.id, user.id, "Setter")
            at_l_g = await bot.db.get_position_games_played(interaction.guild.id, user.id, "Libero")
            if at_ds_g > 0 or all_time_for_rank[0] != current_starting_elo: at_played.append(all_time_for_rank[0])
            if at_fs_g > 0 or all_time_for_rank[1] != current_starting_elo: at_played.append(all_time_for_rank[1])
            if at_s_g > 0 or all_time_for_rank[2] != current_starting_elo: at_played.append(all_time_for_rank[2])
            if (at_l_g > 0 or all_time_for_rank[3] != current_starting_elo) and not user_is_5v5: at_played.append(all_time_for_rank[3])
            if at_played:
                rank_elo_for_role = max(at_played)

    rank_position, total_players = await bot.db.get_player_rank(interaction.guild.id, user.id, '6v6')
    role_id, rank_threshold, next_threshold = await _get_rank_role_info(bot, interaction.guild.id, rank_elo_for_role)
    rank_role_name = await _resolve_role_name(bot, interaction.guild.id, role_id)
    rank_role_color = await _resolve_role_color(bot, interaction.guild.id, role_id)

    # Avatar
    avatar_bytes = await _get_avatar_bytes(user)

    # 2v2 stats (with optional season, fall back to all-time so sections always show)
    effective_2v2_season = season_2v2_id if season_2v2_id is not None else season_id
    if effective_2v2_season:
        stats_2v2 = await bot.db.get_player_season_stats_simple(interaction.guild.id, user.id, '2v2', effective_2v2_season)
        if not stats_2v2 or (stats_2v2[1] == 0 and stats_2v2[0] in (current_starting_elo, 1000)):
            stats_2v2 = await bot.db.get_player_stats_simple(interaction.guild.id, user.id, '2v2')
    elif region:
        stats_2v2 = await bot.db.get_player_regional_stats_simple(interaction.guild.id, user.id, region, '2v2')
    else:
        stats_2v2 = await bot.db.get_player_stats_simple(interaction.guild.id, user.id, '2v2')
    if stats_2v2 and stats_2v2[1] == 0 and stats_2v2[0] in (current_starting_elo, 1000):
        stats_2v2 = None
    streaks_2v2 = None
    if stats_2v2:
        streaks_2v2 = await bot.db.get_player_streaks(interaction.guild.id, user.id, '2v2')

    # 3v3 stats (with optional season, fall back to all-time so sections always show)
    effective_3v3_season = season_3v3_id if season_3v3_id is not None else season_id
    if effective_3v3_season:
        stats_3v3 = await bot.db.get_player_season_stats_simple(interaction.guild.id, user.id, '3v3', effective_3v3_season)
        if not stats_3v3 or (stats_3v3[1] == 0 and stats_3v3[0] in (current_starting_elo, 1000)):
            stats_3v3 = await bot.db.get_player_stats_simple(interaction.guild.id, user.id, '3v3')
    elif region:
        stats_3v3 = await bot.db.get_player_regional_stats_simple(interaction.guild.id, user.id, region, '3v3')
    else:
        stats_3v3 = await bot.db.get_player_stats_simple(interaction.guild.id, user.id, '3v3')
    if stats_3v3 and stats_3v3[1] == 0 and stats_3v3[0] in (current_starting_elo, 1000):
        stats_3v3 = None
    streaks_3v3 = None
    if stats_3v3:
        streaks_3v3 = await bot.db.get_player_streaks(interaction.guild.id, user.id, '3v3')

    # High rank stats — show even if games_played == 0 so admin-set ELOs are visible
    # Fall back to all-time if season-specific data doesn't exist
    if season_id:
        hr_stats = await bot.db.get_player_season_stats_highrank(interaction.guild.id, user.id, season_id)
        if not hr_stats:
            hr_stats = await bot.db.get_player_stats_highrank(interaction.guild.id, user.id)
    else:
        hr_stats = await bot.db.get_player_stats_highrank(interaction.guild.id, user.id)

    # HR 2v2/3v3 (with optional season, fall back to all-time)
    if effective_2v2_season:
        hr_2v2 = await bot.db.get_player_season_stats_simple(interaction.guild.id, user.id, 'highrank_2v2', effective_2v2_season)
        if not hr_2v2:
            hr_2v2 = await bot.db.get_player_stats_simple(interaction.guild.id, user.id, 'highrank_2v2')
    else:
        hr_2v2 = await bot.db.get_player_stats_simple(interaction.guild.id, user.id, 'highrank_2v2')
    if effective_3v3_season:
        hr_3v3 = await bot.db.get_player_season_stats_simple(interaction.guild.id, user.id, 'highrank_3v3', effective_3v3_season)
        if not hr_3v3:
            hr_3v3 = await bot.db.get_player_stats_simple(interaction.guild.id, user.id, 'highrank_3v3')
    else:
        hr_3v3 = await bot.db.get_player_stats_simple(interaction.guild.id, user.id, 'highrank_3v3')

    # HR position games for per-position display
    hr_ds_games = await bot.db.get_position_games_played_highrank(interaction.guild.id, user.id, "Defense Specialist")
    hr_fs_games = await bot.db.get_position_games_played_highrank(interaction.guild.id, user.id, "Front Spiker")
    hr_s_games = await bot.db.get_position_games_played_highrank(interaction.guild.id, user.id, "Setter")
    hr_l_games = await bot.db.get_position_games_played_highrank(interaction.guild.id, user.id, "Libero")

    # HR streaks
    streaks_hr = await bot.db.get_player_streaks(interaction.guild.id, user.id, 'highrank')
    streaks_hr_2v2 = await bot.db.get_player_streaks(interaction.guild.id, user.id, 'highrank_2v2')
    streaks_hr_3v3 = await bot.db.get_player_streaks(interaction.guild.id, user.id, 'highrank_3v3')

    # Per-position W/L (with optional season, fall back to all-time if season has no data)
    ds_wl = await bot.db.get_position_wl(interaction.guild.id, user.id, "Defense Specialist", season_id)
    fs_wl = await bot.db.get_position_wl(interaction.guild.id, user.id, "Front Spiker", season_id)
    s_wl = await bot.db.get_position_wl(interaction.guild.id, user.id, "Setter", season_id)
    l_wl = await bot.db.get_position_wl(interaction.guild.id, user.id, "Libero", season_id)
    if season_id:
        # Fall back to all-time W/L for positions that fell back to all-time ELO
        if ds_wl == (0, 0) and ds_games > 0:
            ds_wl = await bot.db.get_position_wl(interaction.guild.id, user.id, "Defense Specialist")
        if fs_wl == (0, 0) and fs_games > 0:
            fs_wl = await bot.db.get_position_wl(interaction.guild.id, user.id, "Front Spiker")
        if s_wl == (0, 0) and s_games > 0:
            s_wl = await bot.db.get_position_wl(interaction.guild.id, user.id, "Setter")
        if l_wl == (0, 0) and l_games > 0:
            l_wl = await bot.db.get_position_wl(interaction.guild.id, user.id, "Libero")

    # High rank per-position W/L
    hr_ds_wl = await bot.db.get_position_wl_highrank(interaction.guild.id, user.id, "Defense Specialist")
    hr_fs_wl = await bot.db.get_position_wl_highrank(interaction.guild.id, user.id, "Front Spiker")
    hr_s_wl = await bot.db.get_position_wl_highrank(interaction.guild.id, user.id, "Setter")
    hr_l_wl = await bot.db.get_position_wl_highrank(interaction.guild.id, user.id, "Libero")

    # ELO history (all + separated by queue type, filtered by season if specified)
    elo_history = await bot.db.get_elo_history(interaction.guild.id, user.id, season_id=season_id)
    elo_history_regular = await bot.db.get_elo_history(interaction.guild.id, user.id, queue_type='6v6', season_id=season_id)
    elo_history_highrank = await bot.db.get_elo_history(interaction.guild.id, user.id, queue_type='highrank', season_id=season_id)
    elo_history_2v2 = await bot.db.get_elo_history(interaction.guild.id, user.id, queue_type='2v2', season_id=season_id)
    elo_history_3v3 = await bot.db.get_elo_history(interaction.guild.id, user.id, queue_type='3v3', season_id=season_id)
    elo_history_hr_2v2 = await bot.db.get_elo_history(interaction.guild.id, user.id, queue_type='highrank_2v2', season_id=season_id)
    elo_history_hr_3v3 = await bot.db.get_elo_history(interaction.guild.id, user.id, queue_type='highrank_3v3', season_id=season_id)

    # Per-position ELO history for detailed graph
    all_6v6_history = elo_history_regular or []
    elo_history_ds = [h for h in all_6v6_history if h[2] == 'Defense Specialist']
    elo_history_fs = [h for h in all_6v6_history if h[2] == 'Front Spiker']
    elo_history_s = [h for h in all_6v6_history if h[2] == 'Setter']
    elo_history_l = [h for h in all_6v6_history if h[2] == 'Libero']

    # Per-position high rank ELO history
    all_hr_history = elo_history_highrank or []
    elo_history_hr_ds = [h for h in all_hr_history if h[2] == 'Defense Specialist']
    elo_history_hr_fs = [h for h in all_hr_history if h[2] == 'Front Spiker']
    elo_history_hr_s = [h for h in all_hr_history if h[2] == 'Setter']
    elo_history_hr_l = [h for h in all_hr_history if h[2] == 'Libero']

    # Recent matches per queue type (filtered by season if specified)
    recent_matches = await _build_recent_matches(bot, interaction.guild.id, user.id, 5, queue_type='6v6', season_id=season_id)
    recent_matches_2v2 = await _build_recent_matches(bot, interaction.guild.id, user.id, 5, queue_type='2v2', season_id=season_id)
    recent_matches_3v3 = await _build_recent_matches(bot, interaction.guild.id, user.id, 5, queue_type='3v3', season_id=season_id)

    # Tier roles for progress bars
    tier_roles = await _build_tier_roles(bot, interaction.guild.id)

    return {
        "avatar_bytes": avatar_bytes,
        "ds_elo": ds_elo, "fs_elo": fs_elo, "s_elo": s_elo, "l_elo": l_elo,
        "games": games, "wins": wins, "losses": losses,
        "ds_games": ds_games, "fs_games": fs_games, "s_games": s_games, "l_games": l_games,
        "ws": ws, "ls": ls, "best_ws": best_ws, "best_ls": best_ls,
        "rank_position": rank_position, "total_players": total_players,
        "rank_role_name": rank_role_name,
        "rank_role_color": rank_role_color,
        "rank_threshold": rank_threshold, "next_threshold": next_threshold,
        "stats_2v2": stats_2v2, "stats_3v3": stats_3v3,
        "hr_stats": hr_stats, "hr_2v2": hr_2v2, "hr_3v3": hr_3v3,
        "hr_ds_games": hr_ds_games, "hr_fs_games": hr_fs_games,
        "hr_s_games": hr_s_games, "hr_l_games": hr_l_games,
        "ds_wl": ds_wl, "fs_wl": fs_wl, "s_wl": s_wl, "l_wl": l_wl,
        "hr_ds_wl": hr_ds_wl, "hr_fs_wl": hr_fs_wl, "hr_s_wl": hr_s_wl, "hr_l_wl": hr_l_wl,
        "elo_history": elo_history,
        "elo_history_regular": elo_history_regular,
        "elo_history_highrank": elo_history_highrank,
        "elo_history_ds": elo_history_ds,
        "elo_history_fs": elo_history_fs,
        "elo_history_s": elo_history_s,
        "elo_history_l": elo_history_l,
        "elo_history_2v2": elo_history_2v2,
        "elo_history_3v3": elo_history_3v3,
        "elo_history_hr_ds": elo_history_hr_ds,
        "elo_history_hr_fs": elo_history_hr_fs,
        "elo_history_hr_s": elo_history_hr_s,
        "elo_history_hr_l": elo_history_hr_l,
        "elo_history_hr_2v2": elo_history_hr_2v2,
        "elo_history_hr_3v3": elo_history_hr_3v3,
        "recent_matches": recent_matches,
        "recent_matches_2v2": recent_matches_2v2,
        "recent_matches_3v3": recent_matches_3v3,
        "is_5v5": user_is_5v5,
        "starting_elo": current_starting_elo,
        "streaks_2v2": streaks_2v2,
        "streaks_3v3": streaks_3v3,
        "streaks_hr": streaks_hr,
        "streaks_hr_2v2": streaks_hr_2v2,
        "streaks_hr_3v3": streaks_hr_3v3,
        "tier_roles": tier_roles,
        "region_label": display_region,
    }


class StatsCommands(commands.Cog):
    """Commands for viewing player statistics and leaderboards"""

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="stats", description="View your volleyball stats")
    @app_commands.describe(
        user="The user to view stats for (leave empty for yourself)",
        season="The season name to view (leave empty for current/all-time)",
        region="Region to view stats for (NA, EU, Asia, OCE)"
    )
    @app_commands.choices(region=[
        app_commands.Choice(name="NA", value="NA"),
        app_commands.Choice(name="EU", value="EU"),
        app_commands.Choice(name="Asia", value="Asia"),
        app_commands.Choice(name="OCE", value="OCE"),
    ])
    async def stats(self, interaction: discord.Interaction, user: Optional[discord.User] = None, season: Optional[str] = None, region: Optional[str] = None):
        if user is None:
            user = interaction.user

        # Determine which season to show
        season_id = None
        season_name = None
        season_2v2_id = None
        season_3v3_id = None

        if season:
            season_data = await self.bot.db.get_season_by_name(interaction.guild.id, season)
            if season_data:
                season_id = season_data[0]
                season_name = season_data[1]
            else:
                await interaction.response.send_message(
                    embed=create_error_embed(f"Season '{season}' not found!"),
                    ephemeral=True
                )
                return

            # Resolve per-queue-type season IDs for 2v2/3v3
            for qt_name in ("2v2", "3v3"):
                qt_season = await self.bot.db.get_season_by_name(interaction.guild.id, season, qt_name)
                qt_season_id = qt_season[0] if qt_season else None
                if qt_name == "2v2":
                    season_2v2_id = qt_season_id
                else:
                    season_3v3_id = qt_season_id

        await interaction.response.defer(ephemeral=True)

        # Gather all data
        stats_data = await _gather_stats_data(
            self.bot, interaction, user,
            region=region,
            season_id=season_id,
            season_2v2_id=season_2v2_id,
            season_3v3_id=season_3v3_id,
        )

        # Generate initial card (regular queue focus)
        display_name = f"{user.display_name} - {season_name}" if season_name else user.display_name
        image_buf = await generate_stats_card(
            username=display_name,
            avatar_bytes=stats_data["avatar_bytes"],
            ds_elo=stats_data["ds_elo"], fs_elo=stats_data["fs_elo"],
            s_elo=stats_data["s_elo"], l_elo=stats_data["l_elo"],
            games=stats_data["games"], wins=stats_data["wins"], losses=stats_data["losses"],
            ds_games=stats_data["ds_games"], fs_games=stats_data["fs_games"],
            s_games=stats_data["s_games"], l_games=stats_data["l_games"],
            win_streak=stats_data["ws"], loss_streak=stats_data["ls"],
            best_win_streak=stats_data["best_ws"], best_loss_streak=stats_data["best_ls"],
            rank_position=stats_data["rank_position"], total_players=stats_data["total_players"],
            rank_role_name=stats_data["rank_role_name"],
            rank_role_color=stats_data.get("rank_role_color"),
            rank_role_threshold=stats_data["rank_threshold"],
            next_rank_threshold=stats_data["next_threshold"],
            stats_2v2=stats_data["stats_2v2"], stats_3v3=stats_data["stats_3v3"],
            hr_stats=stats_data["hr_stats"], hr_2v2=stats_data["hr_2v2"], hr_3v3=stats_data["hr_3v3"],
            hr_ds_games=stats_data.get("hr_ds_games", 0), hr_fs_games=stats_data.get("hr_fs_games", 0),
            hr_s_games=stats_data.get("hr_s_games", 0), hr_l_games=stats_data.get("hr_l_games", 0),
            elo_history=stats_data["elo_history"],
            elo_history_regular=stats_data["elo_history_regular"],
            elo_history_highrank=stats_data["elo_history_highrank"],
            elo_history_2v2=stats_data.get("elo_history_2v2"),
            elo_history_3v3=stats_data.get("elo_history_3v3"),
            elo_history_ds=stats_data.get("elo_history_ds"),
            elo_history_fs=stats_data.get("elo_history_fs"),
            elo_history_s=stats_data.get("elo_history_s"),
            elo_history_l=stats_data.get("elo_history_l"),
            elo_history_hr_ds=stats_data.get("elo_history_hr_ds"),
            elo_history_hr_fs=stats_data.get("elo_history_hr_fs"),
            elo_history_hr_s=stats_data.get("elo_history_hr_s"),
            elo_history_hr_l=stats_data.get("elo_history_hr_l"),
            elo_history_hr_2v2=stats_data.get("elo_history_hr_2v2"),
            elo_history_hr_3v3=stats_data.get("elo_history_hr_3v3"),
            recent_matches=stats_data["recent_matches"],
            is_5v5=stats_data["is_5v5"],
            starting_elo=stats_data["starting_elo"],
            streaks_2v2=stats_data["streaks_2v2"],
            streaks_3v3=stats_data["streaks_3v3"],
            queue_focus="regular",
            tier_roles=stats_data["tier_roles"],
            region_label=stats_data.get("region_label"),
            ds_wl=stats_data.get("ds_wl"), fs_wl=stats_data.get("fs_wl"),
            s_wl=stats_data.get("s_wl"), l_wl=stats_data.get("l_wl"),
            hr_ds_wl=stats_data.get("hr_ds_wl"), hr_fs_wl=stats_data.get("hr_fs_wl"),
            hr_s_wl=stats_data.get("hr_s_wl"), hr_l_wl=stats_data.get("hr_l_wl"),
            streaks_hr=stats_data.get("streaks_hr"),
            streaks_hr_2v2=stats_data.get("streaks_hr_2v2"),
            streaks_hr_3v3=stats_data.get("streaks_hr_3v3"),
        )

        # Store overrides for StatsView
        if season_name:
            stats_data["_display_name_override"] = display_name
            stats_data["_season_name"] = season_name

        # Create embed with image and queue toggle buttons
        embed = discord.Embed(color=discord.Color.from_rgb(32, 34, 40))
        embed.set_image(url="attachment://stats.png")
        footer_parts = ["Viewing: REGULAR queue stats"]
        if season_name:
            footer_parts.insert(0, f"Season: {season_name}")
        region_suffix = f" [{region}]" if region else ""
        if region_suffix:
            footer_parts.append(region_suffix.strip())
        embed.set_footer(text=" | ".join(footer_parts))

        view = StatsView(self.bot, interaction.user, user, interaction.guild.id, stats_data)
        file = discord.File(image_buf, filename="stats.png")
        await interaction.followup.send(embed=embed, file=file, view=view, ephemeral=True)

    @app_commands.command(name="top", description="View top 5 players by ELO")
    @app_commands.describe(
        queue="Queue type to view (default: Regular 6v6)",
        position="Position to filter by (only for 6v6 queues)",
        region="Region to view (NA, EU, Asia, OCE)"
    )
    @app_commands.choices(
        queue=[
            app_commands.Choice(name="Regular 6v6", value="6v6"),
            app_commands.Choice(name="2v2", value="2v2"),
            app_commands.Choice(name="3v3", value="3v3"),
            app_commands.Choice(name="High Rank 6v6", value="highrank"),
            app_commands.Choice(name="High Rank 2v2", value="highrank_2v2"),
            app_commands.Choice(name="High Rank 3v3", value="highrank_3v3"),
        ],
        position=[
            app_commands.Choice(name="All (Average)", value="all"),
            app_commands.Choice(name="Defense Specialist", value="Defense Specialist"),
            app_commands.Choice(name="Front Spiker", value="Front Spiker"),
            app_commands.Choice(name="Setter", value="Setter"),
            app_commands.Choice(name="Libero", value="Libero"),
        ],
        region=[
            app_commands.Choice(name="NA", value="NA"),
            app_commands.Choice(name="EU", value="EU"),
            app_commands.Choice(name="Asia", value="Asia"),
            app_commands.Choice(name="OCE", value="OCE"),
        ],
    )
    async def top(self, interaction: discord.Interaction,
                  queue: Optional[str] = "6v6",
                  position: Optional[str] = "all",
                  region: Optional[str] = None):
        pos_filter = None if position == "all" else position

        # Determine which leaderboard to query
        if queue in ("2v2", "3v3"):
            rows = await self.bot.db.get_leaderboard_data_simple(interaction.guild.id, queue, 5, 0)
            queue_label = queue.upper()
            elo_label = "MMR"
        elif queue == "highrank":
            rows = await self.bot.db.get_leaderboard_data_highrank(interaction.guild.id, pos_filter, 5, 0)
            queue_label = "High Rank 6v6"
            elo_label = "ELO" if pos_filter else "avg ELO"
        elif queue in ("highrank_2v2", "highrank_3v3"):
            qt = queue.replace("highrank_", "")
            rows = await self.bot.db.get_leaderboard_data_highrank_simple(interaction.guild.id, qt, 5, 0)
            queue_label = f"High Rank {qt.upper()}"
            elo_label = "MMR"
        else:
            rows = await self.bot.db.get_leaderboard_data(interaction.guild.id, pos_filter, 5, 0)
            queue_label = "Regular 6v6"
            elo_label = "ELO" if pos_filter else "avg ELO"

        title = f"Top 5 Players — {queue_label}"
        if pos_filter:
            title += f" ({pos_filter})"
        if region:
            title += f" [{region}]"

        embed = discord.Embed(
            title=title,
            description=f"Ranked by {elo_label}",
            color=discord.Color.gold()
        )

        if not rows:
            embed.add_field(name="No Players", value="No ranked players yet!", inline=False)
        else:
            medals = ["#1", "#2", "#3", "#4", "#5"]
            for i, (user_id, avg_elo, games, wins) in enumerate(rows):
                win_rate = (wins / games * 100) if games > 0 else 0
                embed.add_field(
                    name=f"{medals[i]} <@{user_id}>",
                    value=f"**{avg_elo:.0f}** {elo_label} | {win_rate:.1f}% WR | {games} games",
                    inline=False
                )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="compare", description="Compare stats between two players")
    @app_commands.describe(
        player1="First player to compare",
        player2="Second player to compare",
        season="The season name to compare (leave empty for all-time)",
        region="Region to compare stats for (NA, EU, Asia, OCE)"
    )
    @app_commands.choices(region=[
        app_commands.Choice(name="NA", value="NA"),
        app_commands.Choice(name="EU", value="EU"),
        app_commands.Choice(name="Asia", value="Asia"),
        app_commands.Choice(name="OCE", value="OCE"),
    ])
    async def compare(self, interaction: discord.Interaction, player1: discord.User, player2: discord.User, season: Optional[str] = None, region: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)

        config = await self.bot.db.get_config(interaction.guild.id)
        current_starting_elo = config["starting_elo"]

        # Determine season (with per-queue-type season resolution like stats command)
        season_id = None
        season_name = None
        season_2v2_id = None
        season_3v3_id = None
        if season:
            season_data = await self.bot.db.get_season_by_name(interaction.guild.id, season)
            if season_data:
                season_id = season_data[0]
                season_name = season_data[1]
            else:
                await interaction.followup.send(
                    embed=create_error_embed(f"Season '{season}' not found!"),
                    ephemeral=True
                )
                return
            # Resolve per-queue-type season IDs
            for qt_name in ("2v2", "3v3"):
                qt_season = await self.bot.db.get_season_by_name(interaction.guild.id, season, qt_name)
                qt_season_id = qt_season[0] if qt_season else None
                if qt_name == "2v2":
                    season_2v2_id = qt_season_id
                else:
                    season_3v3_id = qt_season_id

        # Check 5v5 regions
        p1_region = region or await self.bot.db.get_player_region(interaction.guild.id, player1.id)
        p2_region = region or await self.bot.db.get_player_region(interaction.guild.id, player2.id)
        p1_is_5v5 = is_5v5_region(config, p1_region) if p1_region else False
        p2_is_5v5 = is_5v5_region(config, p2_region) if p2_region else False

        # Get stats (with optional season)
        p1_stats = await self.bot.db.get_player_stats(interaction.guild.id, player1.id, season_id)
        p2_stats = await self.bot.db.get_player_stats(interaction.guild.id, player2.id, season_id)

        if not p1_stats and not p2_stats:
            await interaction.followup.send(
                embed=create_error_embed("Neither player has stats yet."),
                ephemeral=True
            )
            return

        if not p1_stats:
            p1_stats = (current_starting_elo, current_starting_elo, current_starting_elo, current_starting_elo, 0, 0, 0)
        if not p2_stats:
            p2_stats = (current_starting_elo, current_starting_elo, current_starting_elo, current_starting_elo, 0, 0, 0)

        # Position games (with optional season)
        p1_ds = await self.bot.db.get_position_games_played(interaction.guild.id, player1.id, "Defense Specialist", season_id)
        p1_fs = await self.bot.db.get_position_games_played(interaction.guild.id, player1.id, "Front Spiker", season_id)
        p1_s = await self.bot.db.get_position_games_played(interaction.guild.id, player1.id, "Setter", season_id)
        p1_l = await self.bot.db.get_position_games_played(interaction.guild.id, player1.id, "Libero", season_id)
        p2_ds = await self.bot.db.get_position_games_played(interaction.guild.id, player2.id, "Defense Specialist", season_id)
        p2_fs = await self.bot.db.get_position_games_played(interaction.guild.id, player2.id, "Front Spiker", season_id)
        p2_s = await self.bot.db.get_position_games_played(interaction.guild.id, player2.id, "Setter", season_id)
        p2_l = await self.bot.db.get_position_games_played(interaction.guild.id, player2.id, "Libero", season_id)

        # For season stats: use all-time ELO for positions with 0 season games and default ELO
        if season_id:
            default_elos = {current_starting_elo, 1000}
            positions = ["Defense Specialist", "Front Spiker", "Setter", "Libero"]
            for pid, p_stats_ref, p_games in [
                (player1.id, 0, [p1_ds, p1_fs, p1_s, p1_l]),
                (player2.id, 1, [p2_ds, p2_fs, p2_s, p2_l]),
            ]:
                cur_stats = p1_stats if p_stats_ref == 0 else p2_stats
                all_time = await self.bot.db.get_player_stats(interaction.guild.id, pid)
                if all_time:
                    new_elos = list(cur_stats)
                    for j in range(4):
                        if p_games[j] == 0 and cur_stats[j] in default_elos:
                            new_elos[j] = all_time[j]
                            # Also use all-time position games so bars light up
                            at_gp = await self.bot.db.get_position_games_played(interaction.guild.id, pid, positions[j])
                            if at_gp > 0:
                                p_games[j] = at_gp
                    # If no season games at all, use all-time W/L
                    if cur_stats[4] == 0 and all_time[4] > 0:
                        new_elos[4] = all_time[4]
                        new_elos[5] = all_time[5]
                        new_elos[6] = all_time[6]
                    if p_stats_ref == 0:
                        p1_stats = tuple(new_elos)
                        p1_ds, p1_fs, p1_s, p1_l = p_games
                    else:
                        p2_stats = tuple(new_elos)
                        p2_ds, p2_fs, p2_s, p2_l = p_games

        # Ranks
        p1_rank = await self.bot.db.get_player_rank(interaction.guild.id, player1.id, '6v6')
        p2_rank = await self.bot.db.get_player_rank(interaction.guild.id, player2.id, '6v6')

        # Avatars
        p1_avatar = await _get_avatar_bytes(player1)
        p2_avatar = await _get_avatar_bytes(player2)

        # Queue stats (with optional season, using per-queue-type season IDs)
        effective_2v2_season = season_2v2_id if season_2v2_id is not None else season_id
        effective_3v3_season = season_3v3_id if season_3v3_id is not None else season_id
        if effective_2v2_season:
            p1_2v2 = await self.bot.db.get_player_season_stats_simple(interaction.guild.id, player1.id, '2v2', effective_2v2_season)
            p2_2v2 = await self.bot.db.get_player_season_stats_simple(interaction.guild.id, player2.id, '2v2', effective_2v2_season)
            if not p1_2v2 or (p1_2v2[1] == 0 and p1_2v2[0] in (current_starting_elo, 1000)):
                p1_2v2 = await self.bot.db.get_player_stats_simple(interaction.guild.id, player1.id, '2v2')
            if not p2_2v2 or (p2_2v2[1] == 0 and p2_2v2[0] in (current_starting_elo, 1000)):
                p2_2v2 = await self.bot.db.get_player_stats_simple(interaction.guild.id, player2.id, '2v2')
        else:
            p1_2v2 = await self.bot.db.get_player_stats_simple(interaction.guild.id, player1.id, '2v2')
            p2_2v2 = await self.bot.db.get_player_stats_simple(interaction.guild.id, player2.id, '2v2')
        if effective_3v3_season:
            p1_3v3 = await self.bot.db.get_player_season_stats_simple(interaction.guild.id, player1.id, '3v3', effective_3v3_season)
            p2_3v3 = await self.bot.db.get_player_season_stats_simple(interaction.guild.id, player2.id, '3v3', effective_3v3_season)
            if not p1_3v3 or (p1_3v3[1] == 0 and p1_3v3[0] in (current_starting_elo, 1000)):
                p1_3v3 = await self.bot.db.get_player_stats_simple(interaction.guild.id, player1.id, '3v3')
            if not p2_3v3 or (p2_3v3[1] == 0 and p2_3v3[0] in (current_starting_elo, 1000)):
                p2_3v3 = await self.bot.db.get_player_stats_simple(interaction.guild.id, player2.id, '3v3')
        else:
            p1_3v3 = await self.bot.db.get_player_stats_simple(interaction.guild.id, player1.id, '3v3')
            p2_3v3 = await self.bot.db.get_player_stats_simple(interaction.guild.id, player2.id, '3v3')

        # High rank (with optional season)
        if season_id:
            p1_hr = await self.bot.db.get_player_season_stats_highrank(interaction.guild.id, player1.id, season_id)
            p2_hr = await self.bot.db.get_player_season_stats_highrank(interaction.guild.id, player2.id, season_id)
            if not p1_hr:
                p1_hr = await self.bot.db.get_player_stats_highrank(interaction.guild.id, player1.id)
            if not p2_hr:
                p2_hr = await self.bot.db.get_player_stats_highrank(interaction.guild.id, player2.id)
        else:
            p1_hr = await self.bot.db.get_player_stats_highrank(interaction.guild.id, player1.id)
            p2_hr = await self.bot.db.get_player_stats_highrank(interaction.guild.id, player2.id)
        if effective_2v2_season:
            p1_hr_2v2 = await self.bot.db.get_player_season_stats_simple(interaction.guild.id, player1.id, 'highrank_2v2', effective_2v2_season)
            p2_hr_2v2 = await self.bot.db.get_player_season_stats_simple(interaction.guild.id, player2.id, 'highrank_2v2', effective_2v2_season)
            if not p1_hr_2v2:
                p1_hr_2v2 = await self.bot.db.get_player_stats_simple(interaction.guild.id, player1.id, 'highrank_2v2')
            if not p2_hr_2v2:
                p2_hr_2v2 = await self.bot.db.get_player_stats_simple(interaction.guild.id, player2.id, 'highrank_2v2')
        else:
            p1_hr_2v2 = await self.bot.db.get_player_stats_simple(interaction.guild.id, player1.id, 'highrank_2v2')
            p2_hr_2v2 = await self.bot.db.get_player_stats_simple(interaction.guild.id, player2.id, 'highrank_2v2')
        if effective_3v3_season:
            p1_hr_3v3 = await self.bot.db.get_player_season_stats_simple(interaction.guild.id, player1.id, 'highrank_3v3', effective_3v3_season)
            p2_hr_3v3 = await self.bot.db.get_player_season_stats_simple(interaction.guild.id, player2.id, 'highrank_3v3', effective_3v3_season)
            if not p1_hr_3v3:
                p1_hr_3v3 = await self.bot.db.get_player_stats_simple(interaction.guild.id, player1.id, 'highrank_3v3')
            if not p2_hr_3v3:
                p2_hr_3v3 = await self.bot.db.get_player_stats_simple(interaction.guild.id, player2.id, 'highrank_3v3')
        else:
            p1_hr_3v3 = await self.bot.db.get_player_stats_simple(interaction.guild.id, player1.id, 'highrank_3v3')
            p2_hr_3v3 = await self.bot.db.get_player_stats_simple(interaction.guild.id, player2.id, 'highrank_3v3')

        # HR position games for per-position display
        p1_hr_ds = await self.bot.db.get_position_games_played_highrank(interaction.guild.id, player1.id, "Defense Specialist")
        p1_hr_fs = await self.bot.db.get_position_games_played_highrank(interaction.guild.id, player1.id, "Front Spiker")
        p1_hr_s = await self.bot.db.get_position_games_played_highrank(interaction.guild.id, player1.id, "Setter")
        p1_hr_l = await self.bot.db.get_position_games_played_highrank(interaction.guild.id, player1.id, "Libero")
        p2_hr_ds = await self.bot.db.get_position_games_played_highrank(interaction.guild.id, player2.id, "Defense Specialist")
        p2_hr_fs = await self.bot.db.get_position_games_played_highrank(interaction.guild.id, player2.id, "Front Spiker")
        p2_hr_s = await self.bot.db.get_position_games_played_highrank(interaction.guild.id, player2.id, "Setter")
        p2_hr_l = await self.bot.db.get_position_games_played_highrank(interaction.guild.id, player2.id, "Libero")

        # Per-position W/L for both players (with optional season, fall back to all-time)
        p1_ds_wl = await self.bot.db.get_position_wl(interaction.guild.id, player1.id, "Defense Specialist", season_id)
        p1_fs_wl = await self.bot.db.get_position_wl(interaction.guild.id, player1.id, "Front Spiker", season_id)
        p1_s_wl = await self.bot.db.get_position_wl(interaction.guild.id, player1.id, "Setter", season_id)
        p1_l_wl = await self.bot.db.get_position_wl(interaction.guild.id, player1.id, "Libero", season_id)
        p2_ds_wl = await self.bot.db.get_position_wl(interaction.guild.id, player2.id, "Defense Specialist", season_id)
        p2_fs_wl = await self.bot.db.get_position_wl(interaction.guild.id, player2.id, "Front Spiker", season_id)
        p2_s_wl = await self.bot.db.get_position_wl(interaction.guild.id, player2.id, "Setter", season_id)
        p2_l_wl = await self.bot.db.get_position_wl(interaction.guild.id, player2.id, "Libero", season_id)
        if season_id:
            # Fall back to all-time W/L for positions that fell back to all-time ELO
            if p1_ds_wl == (0, 0) and p1_ds > 0:
                p1_ds_wl = await self.bot.db.get_position_wl(interaction.guild.id, player1.id, "Defense Specialist")
            if p1_fs_wl == (0, 0) and p1_fs > 0:
                p1_fs_wl = await self.bot.db.get_position_wl(interaction.guild.id, player1.id, "Front Spiker")
            if p1_s_wl == (0, 0) and p1_s > 0:
                p1_s_wl = await self.bot.db.get_position_wl(interaction.guild.id, player1.id, "Setter")
            if p1_l_wl == (0, 0) and p1_l > 0:
                p1_l_wl = await self.bot.db.get_position_wl(interaction.guild.id, player1.id, "Libero")
            if p2_ds_wl == (0, 0) and p2_ds > 0:
                p2_ds_wl = await self.bot.db.get_position_wl(interaction.guild.id, player2.id, "Defense Specialist")
            if p2_fs_wl == (0, 0) and p2_fs > 0:
                p2_fs_wl = await self.bot.db.get_position_wl(interaction.guild.id, player2.id, "Front Spiker")
            if p2_s_wl == (0, 0) and p2_s > 0:
                p2_s_wl = await self.bot.db.get_position_wl(interaction.guild.id, player2.id, "Setter")
            if p2_l_wl == (0, 0) and p2_l > 0:
                p2_l_wl = await self.bot.db.get_position_wl(interaction.guild.id, player2.id, "Libero")

        # High rank per-position W/L
        p1_hr_ds_wl = await self.bot.db.get_position_wl_highrank(interaction.guild.id, player1.id, "Defense Specialist")
        p1_hr_fs_wl = await self.bot.db.get_position_wl_highrank(interaction.guild.id, player1.id, "Front Spiker")
        p1_hr_s_wl = await self.bot.db.get_position_wl_highrank(interaction.guild.id, player1.id, "Setter")
        p1_hr_l_wl = await self.bot.db.get_position_wl_highrank(interaction.guild.id, player1.id, "Libero")
        p2_hr_ds_wl = await self.bot.db.get_position_wl_highrank(interaction.guild.id, player2.id, "Defense Specialist")
        p2_hr_fs_wl = await self.bot.db.get_position_wl_highrank(interaction.guild.id, player2.id, "Front Spiker")
        p2_hr_s_wl = await self.bot.db.get_position_wl_highrank(interaction.guild.id, player2.id, "Setter")
        p2_hr_l_wl = await self.bot.db.get_position_wl_highrank(interaction.guild.id, player2.id, "Libero")

        # ELO history (legacy + separated)
        p1_history = await self.bot.db.get_elo_history(interaction.guild.id, player1.id)
        p2_history = await self.bot.db.get_elo_history(interaction.guild.id, player2.id)
        p1_history_regular = await self.bot.db.get_elo_history(interaction.guild.id, player1.id, queue_type='6v6')
        p2_history_regular = await self.bot.db.get_elo_history(interaction.guild.id, player2.id, queue_type='6v6')
        p1_history_highrank = await self.bot.db.get_elo_history(interaction.guild.id, player1.id, queue_type='highrank')
        p2_history_highrank = await self.bot.db.get_elo_history(interaction.guild.id, player2.id, queue_type='highrank')

        # Recent matches per queue type
        p1_recent = await _build_recent_matches(self.bot, interaction.guild.id, player1.id, 5, queue_type='6v6')
        p2_recent = await _build_recent_matches(self.bot, interaction.guild.id, player2.id, 5, queue_type='6v6')
        p1_recent_2v2 = await _build_recent_matches(self.bot, interaction.guild.id, player1.id, 5, queue_type='2v2')
        p2_recent_2v2 = await _build_recent_matches(self.bot, interaction.guild.id, player2.id, 5, queue_type='2v2')
        p1_recent_3v3 = await _build_recent_matches(self.bot, interaction.guild.id, player1.id, 5, queue_type='3v3')
        p2_recent_3v3 = await _build_recent_matches(self.bot, interaction.guild.id, player2.id, 5, queue_type='3v3')

        # Streaks for all queue types (including high rank)
        p1_streaks_6v6 = await self.bot.db.get_player_streaks(interaction.guild.id, player1.id, '6v6')
        p2_streaks_6v6 = await self.bot.db.get_player_streaks(interaction.guild.id, player2.id, '6v6')
        p1_streaks_2v2 = await self.bot.db.get_player_streaks(interaction.guild.id, player1.id, '2v2')
        p2_streaks_2v2 = await self.bot.db.get_player_streaks(interaction.guild.id, player2.id, '2v2')
        p1_streaks_3v3 = await self.bot.db.get_player_streaks(interaction.guild.id, player1.id, '3v3')
        p2_streaks_3v3 = await self.bot.db.get_player_streaks(interaction.guild.id, player2.id, '3v3')
        p1_streaks_hr = await self.bot.db.get_player_streaks(interaction.guild.id, player1.id, 'highrank')
        p2_streaks_hr = await self.bot.db.get_player_streaks(interaction.guild.id, player2.id, 'highrank')
        p1_streaks_hr_2v2 = await self.bot.db.get_player_streaks(interaction.guild.id, player1.id, 'highrank_2v2')
        p2_streaks_hr_2v2 = await self.bot.db.get_player_streaks(interaction.guild.id, player2.id, 'highrank_2v2')
        p1_streaks_hr_3v3 = await self.bot.db.get_player_streaks(interaction.guild.id, player1.id, 'highrank_3v3')
        p2_streaks_hr_3v3 = await self.bot.db.get_player_streaks(interaction.guild.id, player2.id, 'highrank_3v3')

        # Rank role info for tier progress — always use all-time ELO for role display
        p1_played_elos = [p1_stats[j] for j in range(4) if (p1_ds, p1_fs, p1_s, p1_l)[j] > 0 or p1_stats[j] != current_starting_elo]
        p2_played_elos = [p2_stats[j] for j in range(4) if (p2_ds, p2_fs, p2_s, p2_l)[j] > 0 or p2_stats[j] != current_starting_elo]
        p1_highest_elo = max(p1_played_elos) if p1_played_elos else current_starting_elo
        p2_highest_elo = max(p2_played_elos) if p2_played_elos else current_starting_elo

        # Use all-time stats for rank role when viewing season data
        p1_rank_elo = p1_highest_elo
        p2_rank_elo = p2_highest_elo
        if season_id:
            for pid, idx_setter in [(player1.id, 0), (player2.id, 1)]:
                all_time = await self.bot.db.get_player_stats(interaction.guild.id, pid)
                if all_time:
                    at_played = []
                    at_ds_g = await self.bot.db.get_position_games_played(interaction.guild.id, pid, "Defense Specialist")
                    at_fs_g = await self.bot.db.get_position_games_played(interaction.guild.id, pid, "Front Spiker")
                    at_s_g = await self.bot.db.get_position_games_played(interaction.guild.id, pid, "Setter")
                    at_l_g = await self.bot.db.get_position_games_played(interaction.guild.id, pid, "Libero")
                    if at_ds_g > 0 or all_time[0] != current_starting_elo: at_played.append(all_time[0])
                    if at_fs_g > 0 or all_time[1] != current_starting_elo: at_played.append(all_time[1])
                    if at_s_g > 0 or all_time[2] != current_starting_elo: at_played.append(all_time[2])
                    p_is_5v5 = p1_is_5v5 if idx_setter == 0 else p2_is_5v5
                    if (at_l_g > 0 or all_time[3] != current_starting_elo) and not p_is_5v5: at_played.append(all_time[3])
                    if at_played:
                        if idx_setter == 0:
                            p1_rank_elo = max(at_played)
                        else:
                            p2_rank_elo = max(at_played)

        p1_role_id, p1_threshold, p1_next = await _get_rank_role_info(self.bot, interaction.guild.id, p1_rank_elo)
        p2_role_id, p2_threshold, p2_next = await _get_rank_role_info(self.bot, interaction.guild.id, p2_rank_elo)
        p1_role_name = await _resolve_role_name(self.bot, interaction.guild.id, p1_role_id)
        p2_role_name = await _resolve_role_name(self.bot, interaction.guild.id, p2_role_id)
        p1_role_color = await _resolve_role_color(self.bot, interaction.guild.id, p1_role_id)
        p2_role_color = await _resolve_role_color(self.bot, interaction.guild.id, p2_role_id)

        # Tier roles for progress bars
        tier_roles = await _build_tier_roles(self.bot, interaction.guild.id)

        # Build compare data dict for CompareView
        compare_data = {
            "player1_name": player1.display_name,
            "player2_name": player2.display_name,
            "player1_avatar": p1_avatar,
            "player2_avatar": p2_avatar,
            "p1_stats": p1_stats,
            "p2_stats": p2_stats,
            "p1_games_per_pos": (p1_ds, p1_fs, p1_s, p1_l),
            "p2_games_per_pos": (p2_ds, p2_fs, p2_s, p2_l),
            "p1_rank": p1_rank,
            "p2_rank": p2_rank,
            "p1_2v2": p1_2v2, "p2_2v2": p2_2v2,
            "p1_3v3": p1_3v3, "p2_3v3": p2_3v3,
            "p1_hr": p1_hr, "p2_hr": p2_hr,
            "p1_hr_2v2": p1_hr_2v2, "p2_hr_2v2": p2_hr_2v2,
            "p1_hr_3v3": p1_hr_3v3, "p2_hr_3v3": p2_hr_3v3,
            "p1_history": p1_history,
            "p2_history": p2_history,
            "p1_history_regular": p1_history_regular,
            "p2_history_regular": p2_history_regular,
            "p1_history_highrank": p1_history_highrank,
            "p2_history_highrank": p2_history_highrank,
            "p1_is_5v5": p1_is_5v5,
            "p2_is_5v5": p2_is_5v5,
            "starting_elo": current_starting_elo,
            "p1_recent": p1_recent,
            "p2_recent": p2_recent,
            "p1_recent_2v2": p1_recent_2v2,
            "p2_recent_2v2": p2_recent_2v2,
            "p1_recent_3v3": p1_recent_3v3,
            "p2_recent_3v3": p2_recent_3v3,
            "p1_rank_role": p1_role_name,
            "p2_rank_role": p2_role_name,
            "p1_rank_threshold": p1_threshold,
            "p2_rank_threshold": p2_threshold,
            "p1_next_threshold": p1_next,
            "p2_next_threshold": p2_next,
            "p1_streaks_6v6": p1_streaks_6v6,
            "p2_streaks_6v6": p2_streaks_6v6,
            "p1_streaks_2v2": p1_streaks_2v2,
            "p2_streaks_2v2": p2_streaks_2v2,
            "p1_streaks_3v3": p1_streaks_3v3,
            "p2_streaks_3v3": p2_streaks_3v3,
            "p1_role_color": p1_role_color,
            "p2_role_color": p2_role_color,
            "tier_roles": tier_roles,
            "p1_hr_games_per_pos": (p1_hr_ds, p1_hr_fs, p1_hr_s, p1_hr_l),
            "p2_hr_games_per_pos": (p2_hr_ds, p2_hr_fs, p2_hr_s, p2_hr_l),
            "p1_pos_wl": (p1_ds_wl or (0, 0), p1_fs_wl or (0, 0), p1_s_wl or (0, 0), p1_l_wl or (0, 0)),
            "p2_pos_wl": (p2_ds_wl or (0, 0), p2_fs_wl or (0, 0), p2_s_wl or (0, 0), p2_l_wl or (0, 0)),
            "p1_hr_pos_wl": (p1_hr_ds_wl or (0, 0), p1_hr_fs_wl or (0, 0), p1_hr_s_wl or (0, 0), p1_hr_l_wl or (0, 0)),
            "p2_hr_pos_wl": (p2_hr_ds_wl or (0, 0), p2_hr_fs_wl or (0, 0), p2_hr_s_wl or (0, 0), p2_hr_l_wl or (0, 0)),
            "p1_streaks_hr": p1_streaks_hr,
            "p2_streaks_hr": p2_streaks_hr,
            "p1_streaks_hr_2v2": p1_streaks_hr_2v2,
            "p2_streaks_hr_2v2": p2_streaks_hr_2v2,
            "p1_streaks_hr_3v3": p1_streaks_hr_3v3,
            "p2_streaks_hr_3v3": p2_streaks_hr_3v3,
            "_season_name": season_name,
            "_region": region,
        }

        # Generate initial comparison card (regular queue focus)
        # Exclude internal keys (prefixed with _) and per-queue recent match variants
        _card_exclude_keys = {"_season_name", "_region", "p1_recent_2v2", "p2_recent_2v2", "p1_recent_3v3", "p2_recent_3v3"}
        compare_data_for_card = {k: v for k, v in compare_data.items() if k not in _card_exclude_keys and not k.startswith("_")}
        image_buf = await generate_compare_card(
            **compare_data_for_card,
            queue_focus="regular",
        )

        embed = discord.Embed(color=discord.Color.from_rgb(32, 34, 40))
        embed.set_image(url="attachment://compare.png")
        footer_parts = ["Viewing: REGULAR queue comparison"]
        if season_name:
            footer_parts.append(f"Season: {season_name}")
        if region:
            footer_parts.append(f"[{region}]")
        embed.set_footer(text=" | ".join(footer_parts))

        view = CompareView(self.bot, interaction.user, compare_data)
        file = discord.File(image_buf, filename="compare.png")
        await interaction.followup.send(embed=embed, file=file, view=view, ephemeral=True)

    @app_commands.command(name="leaderboard", description="View the interactive leaderboard")
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        view = LeaderboardView(self.bot, interaction.guild.id)

        # Setup season options
        await view.setup_season_options()

        # Set initial select defaults
        view._update_select_defaults()

        # Get initial data
        rows = await self.bot.db.get_leaderboard_data(interaction.guild.id, None, 10, 0)
        total_count = await self.bot.db.get_player_count(interaction.guild.id)
        total_pages = max(1, (total_count - 1) // 10 + 1)

        # Update pagination buttons
        view.prev_button.disabled = True  # First page
        view.next_button.disabled = len(rows) < 10

        # Build leaderboard card image
        card_rows = []
        for i, (user_id, avg_elo, g, w) in enumerate(rows, 1):
            user = self.bot.get_user(user_id)
            username = user.name if user else f"User {user_id}"
            avatar_bytes = await view._get_avatar_bytes(user)
            win_rate = (w / g * 100) if g > 0 else 0
            value_text = f"{avg_elo:.0f} ELO"
            sub_text = f"{win_rate:.1f}% WR | {w}W/{g - w}L | {g} games"

            # Get streaks
            streaks = await self.bot.db.get_player_streaks(interaction.guild.id, user_id, '6v6')
            ws_val, ls_val = streaks[0], streaks[1]
            streak_text = ""
            if ws_val > 0:
                streak_text = f"{ws_val}W streak"
            elif ls_val > 0:
                streak_text = f"{ls_val}L streak"

            card_rows.append((i, username, value_text, sub_text, streak_text, avatar_bytes))

        image_buf = await generate_leaderboard_card(
            title="Volleyball Leaderboard",
            rows=card_rows if card_rows else None,
            page=0,
            total_pages=total_pages,
            subtitle="Top Players - Average ELO Rating (Current Season)",
            queue_label="Regular",
        )

        embed = discord.Embed(color=discord.Color.from_rgb(32, 34, 40))
        embed.set_image(url="attachment://leaderboard.png")

        file = discord.File(image_buf, filename="leaderboard.png")
        await interaction.followup.send(embed=embed, file=file, view=view, ephemeral=True)
