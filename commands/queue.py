# commands/queue.py
"""
Queue management commands for the volleyball bot
"""

import discord
from discord import app_commands
from discord.ext import commands
from config import get_region_role_limits, get_region_team_size


class QueueCommands(commands.Cog):
    """Commands for viewing and managing the match queue"""

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="queue", description="View current queue status")
    async def queue_status(self, interaction: discord.Interaction):
        config = await self.bot.db.get_config(interaction.guild.id)
        guild_id = interaction.guild.id

        # --- 6v6 Queue ---
        queue = await self.bot.db.get_queue(guild_id, '6v6')

        # Build per-region counts for 6v6 with region-specific totals
        region_counts = {}
        for user_id, position, partner_info in queue:
            player_region = await self.bot.db.get_player_region(guild_id, user_id)
            r = player_region or "Unknown"
            region_counts[r] = region_counts.get(r, 0) + 1

        region_lines = []
        for region, count in sorted(region_counts.items()):
            region_role_limits = get_region_role_limits(config, region)
            region_total = sum(region_role_limits.values())
            team_size_label = get_region_team_size(config, region)
            ready_marker = " **READY**" if count >= region_total else ""
            region_lines.append(f"{region} [{team_size_label}]: {count}/{region_total}{ready_marker}")

        region_summary = "\n".join(region_lines) if region_lines else "No players"

        embed = discord.Embed(
            title="🏐 Current Queue Status",
            color=discord.Color.blue()
        )

        embed.add_field(
            name=f"Queues ({len(queue)} players)",
            value=region_summary,
            inline=False
        )

        # 6v6 positions breakdown
        if queue:
            positions_dict = {}
            for user_id, position, duo_partner in queue:
                if position not in positions_dict:
                    positions_dict[position] = 0
                positions_dict[position] += 1

            pos_lines = []
            for position, count in positions_dict.items():
                limit = config["role_limits"].get(position, 0)
                pos_lines.append(f"{position}: {count}/{limit}")
            embed.add_field(name="Positions", value="\n".join(pos_lines), inline=True)

        # --- High Rank 6v6 Queue ---
        if config.get("high_rank_enabled", False):
            hr_queue = await self.bot.db.get_queue(guild_id, 'highrank')
            mmr_limit = config.get('high_rank_mmr_limit', 1000)

            hr_region_counts = {}
            for user_id, _, _ in hr_queue:
                player_region = await self.bot.db.get_player_region(guild_id, user_id)
                r = player_region or "Unknown"
                hr_region_counts[r] = hr_region_counts.get(r, 0) + 1

            hr_region_lines = []
            for region, count in sorted(hr_region_counts.items()):
                region_role_limits = get_region_role_limits(config, region)
                region_total = sum(region_role_limits.values())
                team_size_label = get_region_team_size(config, region)
                ready_marker = " **READY**" if count >= region_total else ""
                hr_region_lines.append(f"{region} [{team_size_label}]: {count}/{region_total}{ready_marker}")

            hr_region_summary = "\n".join(hr_region_lines) if hr_region_lines else "No players"

            embed.add_field(
                name=f"High Rank ({len(hr_queue)} players)",
                value=f"MMR requirement: {mmr_limit}+\n{hr_region_summary}",
                inline=False
            )

        # --- 2v2 Queue ---
        queue_2v2 = await self.bot.db.get_queue(guild_id, '2v2')
        region_counts_2v2 = {}
        for user_id, _, _ in queue_2v2:
            player_region = await self.bot.db.get_player_region(guild_id, user_id)
            r = player_region or "Unknown"
            region_counts_2v2[r] = region_counts_2v2.get(r, 0) + 1

        region_lines_2v2 = []
        for region, count in sorted(region_counts_2v2.items()):
            ready_marker = " **READY**" if count >= 4 else ""
            region_lines_2v2.append(f"{region}: {count}/4{ready_marker}")

        region_summary_2v2 = "\n".join(region_lines_2v2) if region_lines_2v2 else "No players"

        embed.add_field(
            name=f"2v2 Queue ({len(queue_2v2)} players)",
            value=region_summary_2v2,
            inline=False
        )

        # High Rank 2v2
        if config.get("high_rank_2v2_enabled", False):
            hr_2v2 = await self.bot.db.get_queue(guild_id, 'highrank_2v2')
            mmr_limit_2v2 = config.get("high_rank_2v2_mmr_limit", 1000)

            hr_2v2_region_counts = {}
            for user_id, _, _ in hr_2v2:
                player_region = await self.bot.db.get_player_region(guild_id, user_id)
                r = player_region or "Unknown"
                hr_2v2_region_counts[r] = hr_2v2_region_counts.get(r, 0) + 1

            hr_2v2_region_lines = []
            for region, count in sorted(hr_2v2_region_counts.items()):
                ready_marker = " **READY**" if count >= 4 else ""
                hr_2v2_region_lines.append(f"{region}: {count}/4{ready_marker}")

            hr_2v2_summary = "\n".join(hr_2v2_region_lines) if hr_2v2_region_lines else "No players"

            embed.add_field(
                name=f"High Rank 2v2 ({len(hr_2v2)} players)",
                value=f"MMR requirement: {mmr_limit_2v2}+\n{hr_2v2_summary}",
                inline=False
            )

        # --- 3v3 Queue ---
        queue_3v3 = await self.bot.db.get_queue(guild_id, '3v3')
        region_counts_3v3 = {}
        for user_id, _, _ in queue_3v3:
            player_region = await self.bot.db.get_player_region(guild_id, user_id)
            r = player_region or "Unknown"
            region_counts_3v3[r] = region_counts_3v3.get(r, 0) + 1

        region_lines_3v3 = []
        for region, count in sorted(region_counts_3v3.items()):
            ready_marker = " **READY**" if count >= 6 else ""
            region_lines_3v3.append(f"{region}: {count}/6{ready_marker}")

        region_summary_3v3 = "\n".join(region_lines_3v3) if region_lines_3v3 else "No players"

        embed.add_field(
            name=f"3v3 Queue ({len(queue_3v3)} players)",
            value=region_summary_3v3,
            inline=False
        )

        # High Rank 3v3
        if config.get("high_rank_3v3_enabled", False):
            hr_3v3 = await self.bot.db.get_queue(guild_id, 'highrank_3v3')
            mmr_limit_3v3 = config.get("high_rank_3v3_mmr_limit", 1000)

            hr_3v3_region_counts = {}
            for user_id, _, _ in hr_3v3:
                player_region = await self.bot.db.get_player_region(guild_id, user_id)
                r = player_region or "Unknown"
                hr_3v3_region_counts[r] = hr_3v3_region_counts.get(r, 0) + 1

            hr_3v3_region_lines = []
            for region, count in sorted(hr_3v3_region_counts.items()):
                ready_marker = " **READY**" if count >= 6 else ""
                hr_3v3_region_lines.append(f"{region}: {count}/6{ready_marker}")

            hr_3v3_summary = "\n".join(hr_3v3_region_lines) if hr_3v3_region_lines else "No players"

            embed.add_field(
                name=f"High Rank 3v3 ({len(hr_3v3)} players)",
                value=f"MMR requirement: {mmr_limit_3v3}+\n{hr_3v3_summary}",
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)
