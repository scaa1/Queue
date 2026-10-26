# views/queue_views.py
"""
Views related to queue management and duo/trio queuing
"""

import discord
from discord import app_commands
import json
import asyncio
import time
from datetime import datetime, timedelta

from config import VALID_POSITIONS, is_5v5_region
import calendar


# ──────────────────────────────────────────────
#  QUEUE BAN CHECK HELPER
# ──────────────────────────────────────────────

async def handle_queue_result(interaction, result):
    """Handle add_to_queue result. Returns True if added, False if rejected (message already sent)."""
    if isinstance(result, tuple) and result[0] == "queue_banned":
        banned_until = result[1]
        # Convert to unix timestamp for Discord
        ban_ts = int(calendar.timegm(banned_until.timetuple()))
        await interaction.followup.send(
            f"You are queue banned until <t:{ban_ts}:R> for not readying up.",
            ephemeral=True
        )
        return False
    if isinstance(result, tuple) and result[0] == "in_active_match":
        await interaction.followup.send(
            "You cannot queue while you are in an active match! "
            "Please finish your current match first.",
            ephemeral=True
        )
        return False
    return result


# ──────────────────────────────────────────────
#  COOLDOWN HELPER
# ──────────────────────────────────────────────

# Per-user cooldown tracker: {user_id: last_interaction_timestamp}
_cooldowns: dict[int, float] = {}


async def check_cooldown(interaction: discord.Interaction, bot) -> bool:
    """Check if user is on cooldown. Returns True if OK, False if on cooldown."""
    config = await bot.db.get_config(interaction.guild_id)
    cooldown_seconds = config.get("queue_cooldown", 5)
    now = time.time()
    last = _cooldowns.get(interaction.user.id, 0)
    if now - last < cooldown_seconds:
        remaining = round(cooldown_seconds - (now - last), 1)
        await interaction.response.send_message(
            f"Please wait {remaining}s before using queue buttons again.",
            ephemeral=True
        )
        return False
    _cooldowns[interaction.user.id] = now
    return True


# ──────────────────────────────────────────────
#  REQUIRED ROLES CHECK HELPER
# ──────────────────────────────────────────────

async def check_required_roles(interaction: discord.Interaction, bot) -> bool:
    """Check if user has at least one required role. Returns True if OK, False if missing."""
    config = await bot.db.get_config(interaction.guild_id)
    required_roles = config.get("required_roles", [])
    if not required_roles:
        return True
    user_role_ids = {role.id for role in interaction.user.roles}
    if not user_role_ids.intersection(required_roles):
        role_mentions = ", ".join(f"<@&{rid}>" for rid in required_roles)
        await interaction.response.send_message(
            f"You need one of the following roles to queue: {role_mentions}",
            ephemeral=True
        )
        return False
    return True


async def check_required_roles_member(guild_id: int, member: discord.Member, bot) -> bool:
    """Check if a specific member has at least one required role. Returns True if OK."""
    config = await bot.db.get_config(guild_id)
    required_roles = config.get("required_roles", [])
    if not required_roles:
        return True
    user_role_ids = {role.id for role in member.roles}
    return bool(user_role_ids.intersection(required_roles))


# ──────────────────────────────────────────────
#  DM CHECK HELPER
# ──────────────────────────────────────────────

async def check_dms_enabled(interaction: discord.Interaction) -> bool:
    """Check if user has DMs enabled. Returns True if OK, False if DMs are off (message already sent)."""
    try:
        dm_check_msg = await interaction.user.send(
            "✅ DM check passed! You can receive match notifications."
        )
        try:
            await dm_check_msg.delete()
        except Exception:
            pass
        return True
    except (discord.Forbidden, discord.HTTPException):
        await interaction.response.send_message(
            "You must have DMs enabled to join the queue! "
            "The bot needs to DM you match notifications.\n\n"
            "**How to enable:** Server Settings > Privacy Settings > Direct Messages",
            ephemeral=True
        )
        return False


# ──────────────────────────────────────────────
#  6v6 QUEUE VIEW  (main queue)
# ──────────────────────────────────────────────

class QueueView(discord.ui.View):
    def __init__(self, bot, config=None):
        super().__init__(timeout=None)
        self.bot = bot

        # Hide buttons that are disabled in config
        if config is not None:
            items_to_remove = []
            for item in self.children:
                if not isinstance(item, discord.ui.Button):
                    continue
                cid = item.custom_id
                if cid == "volleyball_duo_queue" and not config.get("duo_queue_enabled", True):
                    items_to_remove.append(item)
                elif cid == "volleyball_trio_queue" and not config.get("trio_queue_enabled", True):
                    items_to_remove.append(item)
                elif cid == "volleyball_highrank_queue" and not (config.get("high_rank_enabled", False) and config.get("high_rank_solo_enabled", False)):
                    items_to_remove.append(item)
                elif cid == "volleyball_duo_highrank" and not (config.get("high_rank_enabled", False) and config.get("high_rank_duo_enabled", True)):
                    items_to_remove.append(item)
                elif cid == "volleyball_trio_highrank" and not (config.get("high_rank_enabled", False) and config.get("high_rank_trio_enabled", False)):
                    items_to_remove.append(item)
            for item in items_to_remove:
                self.remove_item(item)

    @discord.ui.select(
        placeholder="Select your position",
        custom_id="volleyball_position_select",
        options=[
            discord.SelectOption(label="Defense Specialist"),
            discord.SelectOption(label="Front Spiker"),
            discord.SelectOption(label="Setter"),
            discord.SelectOption(label="Libero")
        ]
    )
    async def position_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if not await check_cooldown(interaction, self.bot):
            return
        if not await check_required_roles(interaction, self.bot):
            return
        if not await check_dms_enabled(interaction):
            return

        current_season = await self.bot.db.get_current_season(interaction.guild.id, '6v6')
        if not current_season:
            embed = discord.Embed(
                title="No Active Season",
                description="Cannot join queue - no active 6v6 season!\n\n"
                           "An administrator must start a new season from /config.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Check region role requirement
        region = await self.bot.db.get_player_region(interaction.guild.id, interaction.user.id)
        if not region:
            await interaction.response.send_message(
                "You must select a region before joining the queue! Use the region selection channel to pick your region.",
                ephemeral=True
            )
            return

        # Block Libero for 5v5 regions
        position = select.values[0]
        if position == "Libero":
            config = await self.bot.db.get_config(interaction.guild.id)
            if is_5v5_region(config, region):
                await interaction.response.send_message(
                    "Libero is not available in your region's 5v5 format. Only **Defense Specialist** is queueable for the defensive role.",
                    ephemeral=True
                )
                return

        blacklist_role = await self.bot.get_blacklist_role(interaction.guild)
        if blacklist_role and blacklist_role in interaction.user.roles:
            await interaction.response.send_message("You are blacklisted and cannot join the queue!", ephemeral=True)
            return

        reason = await self.bot.db.is_blacklisted(interaction.guild.id, interaction.user.id)
        if reason is not None:
            await interaction.response.send_message(
                f"You are blacklisted and cannot join the queue!\nReason: {reason or 'No reason provided'}",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        result = await self.bot.add_to_queue(interaction.guild.id, interaction.user.id, position)
        success = await handle_queue_result(interaction, result)
        if success is True:
            await interaction.followup.send(f"Added to queue as {position}!", ephemeral=True)
            await self.bot.update_queue_embed(interaction.guild.id)
        elif success is False and not isinstance(result, tuple):
            await interaction.followup.send("You're already in the queue!", ephemeral=True)

    @discord.ui.button(label="Leave Queue", style=discord.ButtonStyle.danger, custom_id="volleyball_leave_queue")
    async def leave_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await check_cooldown(interaction, self.bot):
            return
        await interaction.response.defer(ephemeral=True)
        removed = await self.bot.remove_from_queue(interaction.guild.id, interaction.user.id)
        if removed:
            await interaction.followup.send("You have left the queue.", ephemeral=True)
            await self.bot.update_queue_embed(interaction.guild.id)
        else:
            await interaction.followup.send("You're not in the queue!", ephemeral=True)

    @discord.ui.button(label="Duo Queue", style=discord.ButtonStyle.primary, custom_id="volleyball_duo_queue")
    async def duo_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await check_cooldown(interaction, self.bot):
            return
        if not await check_required_roles(interaction, self.bot):
            return
        if not await check_dms_enabled(interaction):
            return

        config = await self.bot.db.get_config(interaction.guild.id)
        if not config.get("duo_queue_enabled", True):
            await interaction.response.send_message("Duo queue is currently disabled.", ephemeral=True)
            return

        current_season = await self.bot.db.get_current_season(interaction.guild.id)
        if not current_season:
            embed = discord.Embed(
                title="No Active Season",
                description="Cannot join queue - no active season!",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Check region role requirement
        region = await self.bot.db.get_player_region(interaction.guild.id, interaction.user.id)
        if not region:
            await interaction.response.send_message(
                "You must select a region before joining the queue! Use the region selection channel to pick your region.",
                ephemeral=True
            )
            return

        blacklist_role = await self.bot.get_blacklist_role(interaction.guild)
        if blacklist_role and blacklist_role in interaction.user.roles:
            await interaction.response.send_message("You are blacklisted and cannot join the queue!", ephemeral=True)
            return

        reason = await self.bot.db.is_blacklisted(interaction.guild.id, interaction.user.id)
        if reason is not None:
            await interaction.response.send_message(
                f"You are blacklisted!\nReason: {reason or 'No reason provided'}",
                ephemeral=True
            )
            return


        view = DuoQueueView(self.bot)
        embed = discord.Embed(
            title="Duo Queue Setup",
            description="Select your partner and positions to queue together!",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="How it works",
            value="Your partner must accept the invitation\n"
                  "Both players must not already be in queue\n"
                  "You'll both be on the same team when matched",
            inline=False
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Trio Queue", style=discord.ButtonStyle.success, custom_id="volleyball_trio_queue")
    async def trio_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await check_cooldown(interaction, self.bot):
            return
        if not await check_required_roles(interaction, self.bot):
            return
        if not await check_dms_enabled(interaction):
            return

        config = await self.bot.db.get_config(interaction.guild.id)
        if not config.get("trio_queue_enabled", True):
            await interaction.response.send_message("Trio queue is currently disabled.", ephemeral=True)
            return

        current_season = await self.bot.db.get_current_season(interaction.guild.id)
        if not current_season:
            embed = discord.Embed(
                title="No Active Season",
                description="Cannot join queue - no active season!",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Check region role requirement
        region = await self.bot.db.get_player_region(interaction.guild.id, interaction.user.id)
        if not region:
            await interaction.response.send_message(
                "You must select a region before joining the queue! Use the region selection channel to pick your region.",
                ephemeral=True
            )
            return

        blacklist_role = await self.bot.get_blacklist_role(interaction.guild)
        if blacklist_role and blacklist_role in interaction.user.roles:
            await interaction.response.send_message("You are blacklisted!", ephemeral=True)
            return

        reason = await self.bot.db.is_blacklisted(interaction.guild.id, interaction.user.id)
        if reason is not None:
            await interaction.response.send_message(
                f"You are blacklisted!\nReason: {reason or 'No reason provided'}",
                ephemeral=True
            )
            return


        view = TrioQueueView(self.bot)
        embed = discord.Embed(
            title="Trio Queue Setup",
            description="Select your two partners and positions to queue together!",
            color=discord.Color.green()
        )
        embed.add_field(
            name="How it works",
            value="Both partners must accept the invitation\n"
                  "All players must not already be in queue\n"
                  "You'll all be on the same team when matched",
            inline=False
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Solo HR", style=discord.ButtonStyle.secondary, custom_id="volleyball_highrank_queue")
    async def highrank_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await check_cooldown(interaction, self.bot):
            return
        if not await check_required_roles(interaction, self.bot):
            return
        if not await check_dms_enabled(interaction):
            return

        config = await self.bot.db.get_config(interaction.guild.id)
        if not config.get("high_rank_enabled", False):
            await interaction.response.send_message("High rank queue is currently disabled.", ephemeral=True)
            return

        if not config.get("high_rank_solo_enabled", False):
            await interaction.response.send_message(
                "Solo high rank queue is disabled. Use **Duo HR** to queue for high rank.",
                ephemeral=True
            )
            return

        current_season = await self.bot.db.get_current_season(interaction.guild.id, '6v6')
        if not current_season:
            await interaction.response.send_message("No active 6v6 season!", ephemeral=True)
            return

        # Check region role requirement
        region = await self.bot.db.get_player_region(interaction.guild.id, interaction.user.id)
        if not region:
            await interaction.response.send_message(
                "You must select a region before joining the queue! Use the region selection channel to pick your region.",
                ephemeral=True
            )
            return

        mmr_limit = config.get("high_rank_mmr_limit", 1000)

        blacklist_role = await self.bot.get_blacklist_role(interaction.guild)
        if blacklist_role and blacklist_role in interaction.user.roles:
            await interaction.response.send_message("You are blacklisted!", ephemeral=True)
            return

        reason = await self.bot.db.is_blacklisted(interaction.guild.id, interaction.user.id)
        if reason is not None:
            await interaction.response.send_message(f"You are blacklisted!\nReason: {reason or 'No reason provided'}", ephemeral=True)
            return


        view = HighRankPositionView(self.bot, mmr_limit)
        embed = discord.Embed(
            title="High Rank Queue",
            description=f"Select your position for high rank 6v6.\nMMR requirement: **{mmr_limit}+** per position",
            color=discord.Color.purple()
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Duo HR", style=discord.ButtonStyle.secondary, custom_id="volleyball_duo_highrank")
    async def duo_highrank_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await check_cooldown(interaction, self.bot):
            return
        if not await check_required_roles(interaction, self.bot):
            return
        if not await check_dms_enabled(interaction):
            return

        config = await self.bot.db.get_config(interaction.guild.id)
        if not config.get("high_rank_enabled", False):
            await interaction.response.send_message("High rank queue is currently disabled.", ephemeral=True)
            return

        if not config.get("high_rank_duo_enabled", True):
            await interaction.response.send_message("Duo high rank queue is currently disabled.", ephemeral=True)
            return

        current_season = await self.bot.db.get_current_season(interaction.guild.id, '6v6')
        if not current_season:
            await interaction.response.send_message("No active 6v6 season!", ephemeral=True)
            return

        region = await self.bot.db.get_player_region(interaction.guild.id, interaction.user.id)
        if not region:
            await interaction.response.send_message(
                "You must select a region before joining the queue! Use the region selection channel to pick your region.",
                ephemeral=True
            )
            return

        blacklist_role = await self.bot.get_blacklist_role(interaction.guild)
        if blacklist_role and blacklist_role in interaction.user.roles:
            await interaction.response.send_message("You are blacklisted!", ephemeral=True)
            return

        reason = await self.bot.db.is_blacklisted(interaction.guild.id, interaction.user.id)
        if reason is not None:
            await interaction.response.send_message(f"You are blacklisted!\nReason: {reason or 'No reason provided'}", ephemeral=True)
            return


        mmr_limit = config.get("high_rank_mmr_limit", 1000)
        view = DuoHighRankView(self.bot, mmr_limit)
        embed = discord.Embed(
            title="Duo High Rank Queue Setup",
            description=f"Select your partner and positions for high rank duo queue!\nMMR requirement: **{mmr_limit}+** per position",
            color=discord.Color.purple()
        )
        embed.add_field(
            name="How it works",
            value="Your partner must accept the invitation\n"
                  "Both players need the required MMR per position\n"
                  "You'll both be on the same team when matched",
            inline=False
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Trio HR", style=discord.ButtonStyle.secondary, custom_id="volleyball_trio_highrank")
    async def trio_highrank_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await check_cooldown(interaction, self.bot):
            return
        if not await check_required_roles(interaction, self.bot):
            return
        if not await check_dms_enabled(interaction):
            return

        config = await self.bot.db.get_config(interaction.guild.id)
        if not config.get("high_rank_enabled", False):
            await interaction.response.send_message("High rank queue is currently disabled.", ephemeral=True)
            return

        if not config.get("high_rank_trio_enabled", False):
            await interaction.response.send_message("Trio high rank queue is currently disabled.", ephemeral=True)
            return

        current_season = await self.bot.db.get_current_season(interaction.guild.id, '6v6')
        if not current_season:
            await interaction.response.send_message("No active 6v6 season!", ephemeral=True)
            return

        region = await self.bot.db.get_player_region(interaction.guild.id, interaction.user.id)
        if not region:
            await interaction.response.send_message(
                "You must select a region before joining the queue! Use the region selection channel to pick your region.",
                ephemeral=True
            )
            return

        blacklist_role = await self.bot.get_blacklist_role(interaction.guild)
        if blacklist_role and blacklist_role in interaction.user.roles:
            await interaction.response.send_message("You are blacklisted!", ephemeral=True)
            return

        reason = await self.bot.db.is_blacklisted(interaction.guild.id, interaction.user.id)
        if reason is not None:
            await interaction.response.send_message(f"You are blacklisted!\nReason: {reason or 'No reason provided'}", ephemeral=True)
            return


        mmr_limit = config.get("high_rank_mmr_limit", 1000)
        view = TrioHighRankView(self.bot, mmr_limit)
        embed = discord.Embed(
            title="Trio High Rank Queue Setup",
            description=f"Select your two partners and positions for high rank trio queue!\nMMR requirement: **{mmr_limit}+** per position",
            color=discord.Color.purple()
        )
        embed.add_field(
            name="How it works",
            value="Both partners must accept the invitation\n"
                  "All players need the required MMR per position\n"
                  "You'll all be on the same team when matched",
            inline=False
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class HighRankPositionView(discord.ui.View):
    """Position select for high rank queue."""
    def __init__(self, bot, mmr_limit=1000):
        super().__init__(timeout=60)
        self.bot = bot
        self.mmr_limit = mmr_limit

    @discord.ui.select(
        placeholder="Select your position",
        options=[
            discord.SelectOption(label="Defense Specialist"),
            discord.SelectOption(label="Front Spiker"),
            discord.SelectOption(label="Setter"),
            discord.SelectOption(label="Libero")
        ]
    )
    async def position_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        position = select.values[0]

        # Block Libero for 5v5 regions
        if position == "Libero":
            region = await self.bot.db.get_player_region(interaction.guild.id, interaction.user.id)
            if region:
                config = await self.bot.db.get_config(interaction.guild.id)
                if is_5v5_region(config, region):
                    await interaction.response.send_message(
                        "Libero is not available in your region's 5v5 format. Only **Defense Specialist** is queueable for the defensive role.",
                        ephemeral=True
                    )
                    return

        # Check per-position ELO for MMR requirement
        position_elo = await self.bot.db.get_player_elo(interaction.guild.id, interaction.user.id, position)
        if position_elo < self.mmr_limit:
            await interaction.response.send_message(
                f"You need at least **{self.mmr_limit}** ELO in **{position}** to join high rank queue.\n"
                f"Your current {position} ELO: **{int(position_elo)}**",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        result = await self.bot.add_to_queue(interaction.guild.id, interaction.user.id, position, queue_type='highrank')
        success = await handle_queue_result(interaction, result)
        if success is True:
            await interaction.followup.send(f"Added to high rank queue as {position}!", ephemeral=True)
            await self.bot.update_queue_embed(interaction.guild.id)
        elif success is False and not isinstance(result, tuple):
            await interaction.followup.send("You're already in a queue!", ephemeral=True)


# ──────────────────────────────────────────────
#  2v2 QUEUE VIEW  (singular MMR, no positions)
# ──────────────────────────────────────────────

class Queue2v2View(discord.ui.View):
    def __init__(self, bot, config=None):
        super().__init__(timeout=None)
        self.bot = bot

        # Hide buttons that are disabled in config
        if config is not None:
            items_to_remove = []
            for item in self.children:
                if not isinstance(item, discord.ui.Button):
                    continue
                cid = item.custom_id
                if cid == "volleyball_duo_2v2" and not config.get("duo_2v2_enabled", True):
                    items_to_remove.append(item)
                elif cid == "volleyball_highrank_2v2" and not config.get("high_rank_2v2_enabled", False):
                    items_to_remove.append(item)
                elif cid == "volleyball_duo_highrank_2v2" and not (config.get("high_rank_2v2_enabled", False) and config.get("duo_2v2_enabled", True)):
                    items_to_remove.append(item)
            for item in items_to_remove:
                self.remove_item(item)

    @discord.ui.button(label="Join 2v2 Queue", style=discord.ButtonStyle.primary, custom_id="volleyball_join_2v2")
    async def join_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await check_cooldown(interaction, self.bot):
            return
        if not await check_required_roles(interaction, self.bot):
            return
        if not await check_dms_enabled(interaction):
            return

        config = await self.bot.db.get_config(interaction.guild.id)

        # Check if duo party is required for 2v2
        if config.get("require_duo_2v2", False):
            await interaction.response.send_message(
                "2v2 queue requires a duo party! Use the **Duo 2v2** button to queue with a partner.",
                ephemeral=True
            )
            return

        current_season = await self.bot.db.get_current_season(interaction.guild.id, '2v2')
        if not current_season:
            await interaction.response.send_message("No active 2v2 season!", ephemeral=True)
            return

        # Check region role requirement
        region = await self.bot.db.get_player_region(interaction.guild.id, interaction.user.id)
        if not region:
            await interaction.response.send_message(
                "You must select a region before joining the queue! Use the region selection channel to pick your region.",
                ephemeral=True
            )
            return

        blacklist_role = await self.bot.get_blacklist_role(interaction.guild)
        if blacklist_role and blacklist_role in interaction.user.roles:
            await interaction.response.send_message("You are blacklisted!", ephemeral=True)
            return

        reason = await self.bot.db.is_blacklisted(interaction.guild.id, interaction.user.id)
        if reason is not None:
            await interaction.response.send_message(f"You are blacklisted!\nReason: {reason or 'No reason provided'}", ephemeral=True)
            return


        await interaction.response.defer(ephemeral=True)
        result = await self.bot.add_to_queue(interaction.guild.id, interaction.user.id, "Player", queue_type='2v2')
        success = await handle_queue_result(interaction, result)
        if success is True:
            await interaction.followup.send("Added to 2v2 queue!", ephemeral=True)
            await self.bot.update_queue_embed_2v2(interaction.guild.id)
        elif success is False and not isinstance(result, tuple):
            await interaction.followup.send("You're already in a queue!", ephemeral=True)

    @discord.ui.button(label="Duo 2v2", style=discord.ButtonStyle.success, custom_id="volleyball_duo_2v2")
    async def duo_2v2(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Queue as a duo party for 2v2"""
        if not await check_cooldown(interaction, self.bot):
            return
        if not await check_required_roles(interaction, self.bot):
            return
        if not await check_dms_enabled(interaction):
            return

        config = await self.bot.db.get_config(interaction.guild.id)
        if not config.get("duo_2v2_enabled", True):
            await interaction.response.send_message("Duo queue for 2v2 is currently disabled.", ephemeral=True)
            return

        current_season = await self.bot.db.get_current_season(interaction.guild.id, '2v2')
        if not current_season:
            await interaction.response.send_message("No active 2v2 season!", ephemeral=True)
            return

        # Check region role requirement
        region = await self.bot.db.get_player_region(interaction.guild.id, interaction.user.id)
        if not region:
            await interaction.response.send_message(
                "You must select a region before joining the queue! Use the region selection channel to pick your region.",
                ephemeral=True
            )
            return

        blacklist_role = await self.bot.get_blacklist_role(interaction.guild)
        if blacklist_role and blacklist_role in interaction.user.roles:
            await interaction.response.send_message("You are blacklisted!", ephemeral=True)
            return

        reason = await self.bot.db.is_blacklisted(interaction.guild.id, interaction.user.id)
        if reason is not None:
            await interaction.response.send_message(f"You are blacklisted!\nReason: {reason or 'No reason provided'}", ephemeral=True)
            return


        view = Duo2v2SetupView(self.bot)
        embed = discord.Embed(
            title="2v2 Duo Party Setup",
            description="Select your partner to queue together as a team in 2v2!",
            color=discord.Color.green()
        )
        embed.add_field(
            name="How it works",
            value="Your partner must accept the invitation\n"
                  "You'll both be on the same team in the 2v2 match",
            inline=False
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="High Rank 2v2", style=discord.ButtonStyle.secondary, custom_id="volleyball_highrank_2v2")
    async def highrank_2v2(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await check_cooldown(interaction, self.bot):
            return
        if not await check_required_roles(interaction, self.bot):
            return
        if not await check_dms_enabled(interaction):
            return

        config = await self.bot.db.get_config(interaction.guild.id)
        if not config.get("high_rank_2v2_enabled", False):
            await interaction.response.send_message("High rank 2v2 queue is currently disabled.", ephemeral=True)
            return

        current_season = await self.bot.db.get_current_season(interaction.guild.id, '2v2')
        if not current_season:
            await interaction.response.send_message("No active 2v2 season!", ephemeral=True)
            return

        # Check region role requirement
        region = await self.bot.db.get_player_region(interaction.guild.id, interaction.user.id)
        if not region:
            await interaction.response.send_message(
                "You must select a region before joining the queue! Use the region selection channel to pick your region.",
                ephemeral=True
            )
            return

        # Check if player meets MMR requirement
        player_stats = await self.bot.db.get_player_stats_simple(interaction.guild.id, interaction.user.id, '2v2')
        current_elo = player_stats[0] if player_stats else config.get("starting_elo", 650)
        mmr_limit = config.get("high_rank_2v2_mmr_limit", 1000)

        if current_elo < mmr_limit:
            await interaction.response.send_message(
                f"You need at least **{mmr_limit}** MMR in normal 2v2 to unlock high rank 2v2.\n"
                f"Your current 2v2 MMR: **{current_elo}**",
                ephemeral=True
            )
            return

        blacklist_role = await self.bot.get_blacklist_role(interaction.guild)
        if blacklist_role and blacklist_role in interaction.user.roles:
            await interaction.response.send_message("You are blacklisted!", ephemeral=True)
            return

        reason = await self.bot.db.is_blacklisted(interaction.guild.id, interaction.user.id)
        if reason is not None:
            await interaction.response.send_message(f"You are blacklisted!\nReason: {reason or 'No reason provided'}", ephemeral=True)
            return


        await interaction.response.defer(ephemeral=True)
        result = await self.bot.add_to_queue(interaction.guild.id, interaction.user.id, "Player", queue_type='highrank_2v2')
        success = await handle_queue_result(interaction, result)
        if success is True:
            await interaction.followup.send("Added to high rank 2v2 queue!", ephemeral=True)
            await self.bot.update_queue_embed_2v2(interaction.guild.id)
        elif success is False and not isinstance(result, tuple):
            await interaction.followup.send("You're already in a queue!", ephemeral=True)

    @discord.ui.button(label="Duo HR 2v2", style=discord.ButtonStyle.secondary, custom_id="volleyball_duo_highrank_2v2")
    async def duo_highrank_2v2(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Queue as a duo party for high rank 2v2"""
        if not await check_cooldown(interaction, self.bot):
            return
        if not await check_required_roles(interaction, self.bot):
            return
        if not await check_dms_enabled(interaction):
            return

        config = await self.bot.db.get_config(interaction.guild.id)
        if not config.get("high_rank_2v2_enabled", False):
            await interaction.response.send_message("High rank 2v2 queue is currently disabled.", ephemeral=True)
            return

        if not config.get("duo_2v2_enabled", True):
            await interaction.response.send_message("Duo queue for 2v2 is currently disabled.", ephemeral=True)
            return

        current_season = await self.bot.db.get_current_season(interaction.guild.id, '2v2')
        if not current_season:
            await interaction.response.send_message("No active 2v2 season!", ephemeral=True)
            return

        region = await self.bot.db.get_player_region(interaction.guild.id, interaction.user.id)
        if not region:
            await interaction.response.send_message(
                "You must select a region before joining the queue! Use the region selection channel to pick your region.",
                ephemeral=True
            )
            return

        # Check MMR requirement
        player_stats = await self.bot.db.get_player_stats_simple(interaction.guild.id, interaction.user.id, '2v2')
        current_elo = player_stats[0] if player_stats else config.get("starting_elo", 650)
        mmr_limit = config.get("high_rank_2v2_mmr_limit", 1000)

        if current_elo < mmr_limit:
            await interaction.response.send_message(
                f"You need at least **{mmr_limit}** MMR in normal 2v2 to unlock high rank 2v2.\n"
                f"Your current 2v2 MMR: **{current_elo}**",
                ephemeral=True
            )
            return

        blacklist_role = await self.bot.get_blacklist_role(interaction.guild)
        if blacklist_role and blacklist_role in interaction.user.roles:
            await interaction.response.send_message("You are blacklisted!", ephemeral=True)
            return

        reason = await self.bot.db.is_blacklisted(interaction.guild.id, interaction.user.id)
        if reason is not None:
            await interaction.response.send_message(f"You are blacklisted!\nReason: {reason or 'No reason provided'}", ephemeral=True)
            return


        view = DuoHighRank2v2SetupView(self.bot, mmr_limit)
        embed = discord.Embed(
            title="High Rank 2v2 Duo Party Setup",
            description=f"Select your partner for high rank 2v2 duo queue!\nBoth players need **{mmr_limit}+** MMR in normal 2v2.",
            color=discord.Color.purple()
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Leave Queue", style=discord.ButtonStyle.danger, custom_id="volleyball_leave_2v2")
    async def leave_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await check_cooldown(interaction, self.bot):
            return
        await interaction.response.defer(ephemeral=True)
        removed = await self.bot.remove_from_queue(interaction.guild.id, interaction.user.id)
        if removed:
            await interaction.followup.send("You have left the 2v2 queue.", ephemeral=True)
            await self.bot.update_queue_embed_2v2(interaction.guild.id)
        else:
            await interaction.followup.send("You're not in the queue!", ephemeral=True)


# ──────────────────────────────────────────────
#  3v3 QUEUE VIEW  (singular MMR, no positions)
# ──────────────────────────────────────────────

class Queue3v3View(discord.ui.View):
    def __init__(self, bot, config=None):
        super().__init__(timeout=None)
        self.bot = bot

        # Hide buttons that are disabled in config
        if config is not None:
            items_to_remove = []
            for item in self.children:
                if not isinstance(item, discord.ui.Button):
                    continue
                cid = item.custom_id
                if cid == "volleyball_duo_3v3" and not config.get("duo_3v3_enabled", True):
                    items_to_remove.append(item)
                elif cid == "volleyball_trio_3v3" and not config.get("trio_3v3_enabled", True):
                    items_to_remove.append(item)
                elif cid == "volleyball_highrank_3v3" and not config.get("high_rank_3v3_enabled", False):
                    items_to_remove.append(item)
                elif cid == "volleyball_duo_highrank_3v3" and not (config.get("high_rank_3v3_enabled", False) and config.get("duo_3v3_enabled", True)):
                    items_to_remove.append(item)
                elif cid == "volleyball_trio_highrank_3v3" and not (config.get("high_rank_3v3_enabled", False) and config.get("trio_3v3_enabled", True)):
                    items_to_remove.append(item)
            for item in items_to_remove:
                self.remove_item(item)

    @discord.ui.button(label="Join 3v3 Queue", style=discord.ButtonStyle.primary, custom_id="volleyball_join_3v3")
    async def join_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await check_cooldown(interaction, self.bot):
            return
        if not await check_required_roles(interaction, self.bot):
            return
        if not await check_dms_enabled(interaction):
            return

        config = await self.bot.db.get_config(interaction.guild.id)

        # Check if trio party is required for 3v3
        if config.get("require_trio_3v3", False):
            await interaction.response.send_message(
                "3v3 queue requires a trio party! Use the **Trio 3v3** button to queue with partners.",
                ephemeral=True
            )
            return

        current_season = await self.bot.db.get_current_season(interaction.guild.id, '3v3')
        if not current_season:
            await interaction.response.send_message("No active 3v3 season!", ephemeral=True)
            return

        # Check region role requirement
        region = await self.bot.db.get_player_region(interaction.guild.id, interaction.user.id)
        if not region:
            await interaction.response.send_message(
                "You must select a region before joining the queue! Use the region selection channel to pick your region.",
                ephemeral=True
            )
            return

        blacklist_role = await self.bot.get_blacklist_role(interaction.guild)
        if blacklist_role and blacklist_role in interaction.user.roles:
            await interaction.response.send_message("You are blacklisted!", ephemeral=True)
            return

        reason = await self.bot.db.is_blacklisted(interaction.guild.id, interaction.user.id)
        if reason is not None:
            await interaction.response.send_message(f"You are blacklisted!\nReason: {reason or 'No reason provided'}", ephemeral=True)
            return


        await interaction.response.defer(ephemeral=True)
        result = await self.bot.add_to_queue(interaction.guild.id, interaction.user.id, "Player", queue_type='3v3')
        success = await handle_queue_result(interaction, result)
        if success is True:
            await interaction.followup.send("Added to 3v3 queue!", ephemeral=True)
            await self.bot.update_queue_embed_3v3(interaction.guild.id)
        elif success is False and not isinstance(result, tuple):
            await interaction.followup.send("You're already in a queue!", ephemeral=True)

    @discord.ui.button(label="Duo 3v3", style=discord.ButtonStyle.primary, custom_id="volleyball_duo_3v3")
    async def duo_3v3(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Queue as a duo party for 3v3"""
        if not await check_cooldown(interaction, self.bot):
            return
        if not await check_required_roles(interaction, self.bot):
            return
        if not await check_dms_enabled(interaction):
            return

        config = await self.bot.db.get_config(interaction.guild.id)
        if not config.get("duo_3v3_enabled", True):
            await interaction.response.send_message("Duo queue for 3v3 is currently disabled.", ephemeral=True)
            return

        current_season = await self.bot.db.get_current_season(interaction.guild.id, '3v3')
        if not current_season:
            await interaction.response.send_message("No active 3v3 season!", ephemeral=True)
            return

        # Check region role requirement
        region = await self.bot.db.get_player_region(interaction.guild.id, interaction.user.id)
        if not region:
            await interaction.response.send_message(
                "You must select a region before joining the queue! Use the region selection channel to pick your region.",
                ephemeral=True
            )
            return

        blacklist_role = await self.bot.get_blacklist_role(interaction.guild)
        if blacklist_role and blacklist_role in interaction.user.roles:
            await interaction.response.send_message("You are blacklisted!", ephemeral=True)
            return

        reason = await self.bot.db.is_blacklisted(interaction.guild.id, interaction.user.id)
        if reason is not None:
            await interaction.response.send_message(f"You are blacklisted!\nReason: {reason or 'No reason provided'}", ephemeral=True)
            return


        view = Duo3v3SetupView(self.bot)
        embed = discord.Embed(
            title="3v3 Duo Party Setup",
            description="Select your partner to queue together as a duo in 3v3!",
            color=discord.Color.orange()
        )
        embed.add_field(
            name="How it works",
            value="Your partner must accept the invitation\n"
                  "You'll both be on the same team in the 3v3 match",
            inline=False
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Trio 3v3", style=discord.ButtonStyle.success, custom_id="volleyball_trio_3v3")
    async def trio_3v3(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Queue as a trio party for 3v3"""
        if not await check_cooldown(interaction, self.bot):
            return
        if not await check_required_roles(interaction, self.bot):
            return
        if not await check_dms_enabled(interaction):
            return

        config = await self.bot.db.get_config(interaction.guild.id)
        if not config.get("trio_3v3_enabled", True):
            await interaction.response.send_message("Trio queue for 3v3 is currently disabled.", ephemeral=True)
            return

        current_season = await self.bot.db.get_current_season(interaction.guild.id, '3v3')
        if not current_season:
            await interaction.response.send_message("No active 3v3 season!", ephemeral=True)
            return

        # Check region role requirement
        region = await self.bot.db.get_player_region(interaction.guild.id, interaction.user.id)
        if not region:
            await interaction.response.send_message(
                "You must select a region before joining the queue! Use the region selection channel to pick your region.",
                ephemeral=True
            )
            return

        blacklist_role = await self.bot.get_blacklist_role(interaction.guild)
        if blacklist_role and blacklist_role in interaction.user.roles:
            await interaction.response.send_message("You are blacklisted!", ephemeral=True)
            return

        reason = await self.bot.db.is_blacklisted(interaction.guild.id, interaction.user.id)
        if reason is not None:
            await interaction.response.send_message(f"You are blacklisted!\nReason: {reason or 'No reason provided'}", ephemeral=True)
            return


        view = Trio3v3SetupView(self.bot)
        embed = discord.Embed(
            title="3v3 Trio Party Setup",
            description="Select your two partners to queue together as a team in 3v3!",
            color=discord.Color.orange()
        )
        embed.add_field(
            name="How it works",
            value="Both partners must accept the invitation\n"
                  "You'll all be on the same team in the 3v3 match",
            inline=False
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="High Rank 3v3", style=discord.ButtonStyle.secondary, custom_id="volleyball_highrank_3v3")
    async def highrank_3v3(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await check_cooldown(interaction, self.bot):
            return
        if not await check_required_roles(interaction, self.bot):
            return
        if not await check_dms_enabled(interaction):
            return

        config = await self.bot.db.get_config(interaction.guild.id)
        if not config.get("high_rank_3v3_enabled", False):
            await interaction.response.send_message("High rank 3v3 queue is currently disabled.", ephemeral=True)
            return

        current_season = await self.bot.db.get_current_season(interaction.guild.id, '3v3')
        if not current_season:
            await interaction.response.send_message("No active 3v3 season!", ephemeral=True)
            return

        # Check region role requirement
        region = await self.bot.db.get_player_region(interaction.guild.id, interaction.user.id)
        if not region:
            await interaction.response.send_message(
                "You must select a region before joining the queue! Use the region selection channel to pick your region.",
                ephemeral=True
            )
            return

        player_stats = await self.bot.db.get_player_stats_simple(interaction.guild.id, interaction.user.id, '3v3')
        current_elo = player_stats[0] if player_stats else config.get("starting_elo", 650)
        mmr_limit = config.get("high_rank_3v3_mmr_limit", 1000)

        if current_elo < mmr_limit:
            await interaction.response.send_message(
                f"You need at least **{mmr_limit}** MMR in normal 3v3 to unlock high rank 3v3.\n"
                f"Your current 3v3 MMR: **{current_elo}**",
                ephemeral=True
            )
            return

        blacklist_role = await self.bot.get_blacklist_role(interaction.guild)
        if blacklist_role and blacklist_role in interaction.user.roles:
            await interaction.response.send_message("You are blacklisted!", ephemeral=True)
            return

        reason = await self.bot.db.is_blacklisted(interaction.guild.id, interaction.user.id)
        if reason is not None:
            await interaction.response.send_message(f"You are blacklisted!\nReason: {reason or 'No reason provided'}", ephemeral=True)
            return


        await interaction.response.defer(ephemeral=True)
        result = await self.bot.add_to_queue(interaction.guild.id, interaction.user.id, "Player", queue_type='highrank_3v3')
        success = await handle_queue_result(interaction, result)
        if success is True:
            await interaction.followup.send("Added to high rank 3v3 queue!", ephemeral=True)
            await self.bot.update_queue_embed_3v3(interaction.guild.id)
        elif success is False and not isinstance(result, tuple):
            await interaction.followup.send("You're already in a queue!", ephemeral=True)

    @discord.ui.button(label="Duo HR 3v3", style=discord.ButtonStyle.secondary, custom_id="volleyball_duo_highrank_3v3")
    async def duo_highrank_3v3(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Queue as a duo party for high rank 3v3"""
        if not await check_cooldown(interaction, self.bot):
            return
        if not await check_required_roles(interaction, self.bot):
            return
        if not await check_dms_enabled(interaction):
            return

        config = await self.bot.db.get_config(interaction.guild.id)
        if not config.get("high_rank_3v3_enabled", False):
            await interaction.response.send_message("High rank 3v3 queue is currently disabled.", ephemeral=True)
            return

        if not config.get("duo_3v3_enabled", True):
            await interaction.response.send_message("Duo queue for 3v3 is currently disabled.", ephemeral=True)
            return

        current_season = await self.bot.db.get_current_season(interaction.guild.id, '3v3')
        if not current_season:
            await interaction.response.send_message("No active 3v3 season!", ephemeral=True)
            return

        region = await self.bot.db.get_player_region(interaction.guild.id, interaction.user.id)
        if not region:
            await interaction.response.send_message(
                "You must select a region before joining the queue! Use the region selection channel to pick your region.",
                ephemeral=True
            )
            return

        player_stats = await self.bot.db.get_player_stats_simple(interaction.guild.id, interaction.user.id, '3v3')
        current_elo = player_stats[0] if player_stats else config.get("starting_elo", 650)
        mmr_limit = config.get("high_rank_3v3_mmr_limit", 1000)

        if current_elo < mmr_limit:
            await interaction.response.send_message(
                f"You need at least **{mmr_limit}** MMR in normal 3v3 to unlock high rank 3v3.\n"
                f"Your current 3v3 MMR: **{current_elo}**",
                ephemeral=True
            )
            return

        blacklist_role = await self.bot.get_blacklist_role(interaction.guild)
        if blacklist_role and blacklist_role in interaction.user.roles:
            await interaction.response.send_message("You are blacklisted!", ephemeral=True)
            return

        reason = await self.bot.db.is_blacklisted(interaction.guild.id, interaction.user.id)
        if reason is not None:
            await interaction.response.send_message(f"You are blacklisted!\nReason: {reason or 'No reason provided'}", ephemeral=True)
            return


        view = DuoHighRank3v3SetupView(self.bot, mmr_limit)
        embed = discord.Embed(
            title="High Rank 3v3 Duo Party Setup",
            description=f"Select your partner for high rank 3v3 duo queue!\nBoth players need **{mmr_limit}+** MMR in normal 3v3.",
            color=discord.Color.purple()
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Trio HR 3v3", style=discord.ButtonStyle.secondary, custom_id="volleyball_trio_highrank_3v3")
    async def trio_highrank_3v3(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Queue as a trio party for high rank 3v3"""
        if not await check_cooldown(interaction, self.bot):
            return
        if not await check_required_roles(interaction, self.bot):
            return
        if not await check_dms_enabled(interaction):
            return

        config = await self.bot.db.get_config(interaction.guild.id)
        if not config.get("high_rank_3v3_enabled", False):
            await interaction.response.send_message("High rank 3v3 queue is currently disabled.", ephemeral=True)
            return

        if not config.get("trio_3v3_enabled", True):
            await interaction.response.send_message("Trio queue for 3v3 is currently disabled.", ephemeral=True)
            return

        current_season = await self.bot.db.get_current_season(interaction.guild.id, '3v3')
        if not current_season:
            await interaction.response.send_message("No active 3v3 season!", ephemeral=True)
            return

        region = await self.bot.db.get_player_region(interaction.guild.id, interaction.user.id)
        if not region:
            await interaction.response.send_message(
                "You must select a region before joining the queue! Use the region selection channel to pick your region.",
                ephemeral=True
            )
            return

        player_stats = await self.bot.db.get_player_stats_simple(interaction.guild.id, interaction.user.id, '3v3')
        current_elo = player_stats[0] if player_stats else config.get("starting_elo", 650)
        mmr_limit = config.get("high_rank_3v3_mmr_limit", 1000)

        if current_elo < mmr_limit:
            await interaction.response.send_message(
                f"You need at least **{mmr_limit}** MMR in normal 3v3 to unlock high rank 3v3.\n"
                f"Your current 3v3 MMR: **{current_elo}**",
                ephemeral=True
            )
            return

        blacklist_role = await self.bot.get_blacklist_role(interaction.guild)
        if blacklist_role and blacklist_role in interaction.user.roles:
            await interaction.response.send_message("You are blacklisted!", ephemeral=True)
            return

        reason = await self.bot.db.is_blacklisted(interaction.guild.id, interaction.user.id)
        if reason is not None:
            await interaction.response.send_message(f"You are blacklisted!\nReason: {reason or 'No reason provided'}", ephemeral=True)
            return


        view = TrioHighRank3v3SetupView(self.bot, mmr_limit)
        embed = discord.Embed(
            title="High Rank 3v3 Trio Party Setup",
            description=f"Select two partners for high rank 3v3 trio queue!\nAll players need **{mmr_limit}+** MMR in normal 3v3.",
            color=discord.Color.purple()
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Leave Queue", style=discord.ButtonStyle.danger, custom_id="volleyball_leave_3v3")
    async def leave_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await check_cooldown(interaction, self.bot):
            return
        await interaction.response.defer(ephemeral=True)
        removed = await self.bot.remove_from_queue(interaction.guild.id, interaction.user.id)
        if removed:
            await interaction.followup.send("You have left the 3v3 queue.", ephemeral=True)
            await self.bot.update_queue_embed_3v3(interaction.guild.id)
        else:
            await interaction.followup.send("You're not in the queue!", ephemeral=True)


# ──────────────────────────────────────────────
#  DUO / TRIO QUEUE VIEWS  (for 6v6)
# ──────────────────────────────────────────────

class DuoQueueView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=60)
        self.bot = bot
        self.partner = None
        self.your_position = None
        self.partner_position = None

    @discord.ui.select(
        cls=discord.ui.UserSelect,
        placeholder="Select your duo partner",
        min_values=1, max_values=1
    )
    async def partner_select(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        self.partner = select.values[0]
        if self.partner.id == interaction.user.id:
            await interaction.response.send_message("You cannot duo queue with yourself!", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await self.check_ready(interaction)

    @discord.ui.select(
        placeholder="Select YOUR position",
        options=[
            discord.SelectOption(label="Defense Specialist", value="Defense Specialist"),
            discord.SelectOption(label="Front Spiker", value="Front Spiker"),
            discord.SelectOption(label="Setter", value="Setter"),
            discord.SelectOption(label="Libero", value="Libero")
        ],
        row=1
    )
    async def your_position_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.your_position = select.values[0]
        await interaction.response.defer(ephemeral=True)
        await self.check_ready(interaction)

    @discord.ui.select(
        placeholder="Select PARTNER'S position",
        options=[
            discord.SelectOption(label="Defense Specialist", value="Defense Specialist"),
            discord.SelectOption(label="Front Spiker", value="Front Spiker"),
            discord.SelectOption(label="Setter", value="Setter"),
            discord.SelectOption(label="Libero", value="Libero")
        ],
        row=2
    )
    async def partner_position_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.partner_position = select.values[0]
        await interaction.response.defer(ephemeral=True)
        await self.check_ready(interaction)

    async def check_ready(self, interaction: discord.Interaction):
        if self.partner and self.your_position and self.partner_position:
            # Block Libero for 5v5 regions
            config = await self.bot.db.get_config(interaction.guild.id)
            initiator_region = await self.bot.db.get_player_region(interaction.guild.id, interaction.user.id)
            if initiator_region and is_5v5_region(config, initiator_region):
                if self.your_position == "Libero":
                    await interaction.followup.send(
                        "Libero is not available in your region's 5v5 format. Only **Defense Specialist** is queueable for the defensive role.",
                        ephemeral=True
                    )
                    return
                if self.partner_position == "Libero":
                    await interaction.followup.send(
                        "Libero is not available in your region's 5v5 format. Only **Defense Specialist** is queueable for the defensive role.",
                        ephemeral=True
                    )
                    return
            if self.partner:
                partner_region = await self.bot.db.get_player_region(interaction.guild.id, self.partner.id)
                if partner_region and is_5v5_region(config, partner_region) and self.partner_position == "Libero":
                    await interaction.followup.send(
                        f"Libero is not available in {self.partner.mention}'s region's 5v5 format. Only **Defense Specialist** is queueable for the defensive role.",
                        ephemeral=True
                    )
                    return

            # Duo position restrictions: can't double up on Setter or Libero
            if self.your_position == self.partner_position and self.your_position in ("Setter", "Libero"):
                await interaction.followup.send(
                    f"Duo queue cannot have both players as **{self.your_position}**. Please pick different positions.",
                    ephemeral=True
                )
                return

            # Check partner blacklist
            blacklist_role = await self.bot.get_blacklist_role(interaction.guild)
            if blacklist_role and blacklist_role in self.partner.roles:
                await interaction.followup.send(f"{self.partner.mention} is blacklisted!", ephemeral=True)
                return

            reason = await self.bot.db.is_blacklisted(interaction.guild.id, self.partner.id)
            if reason is not None:
                await interaction.followup.send(f"{self.partner.mention} is blacklisted!", ephemeral=True)
                return

            # Check partner has required role
            if not await check_required_roles_member(interaction.guild.id, self.partner, self.bot):
                await interaction.followup.send(
                    f"{self.partner.mention} does not have the required role to queue!",
                    ephemeral=True
                )
                return

            # Check if either player is in an active match
            if await self.bot.db.is_user_in_active_match(interaction.guild.id, interaction.user.id):
                await interaction.followup.send(
                    "You cannot send invites while in an active match! Please finish your current match first.",
                    ephemeral=True
                )
                return
            if await self.bot.db.is_user_in_active_match(interaction.guild.id, self.partner.id):
                await interaction.followup.send(
                    f"{self.partner.mention} is currently in an active match!",
                    ephemeral=True
                )
                return

            queue = await self.bot.db.get_queue(interaction.guild.id)
            queued_players = [q[0] for q in queue]

            if interaction.user.id in queued_players:
                await interaction.followup.send("You are already in the queue! Leave first.", ephemeral=True)
                return
            if self.partner.id in queued_players:
                await interaction.followup.send(f"{self.partner.mention} is already in the queue!", ephemeral=True)
                return

            invitation_id = f"duo_{interaction.guild.id}_{interaction.user.id}_{self.partner.id}_{datetime.utcnow().timestamp()}"
            invitation_data = {
                'type': 'duo',
                'initiator': interaction.user.id,
                'guild_id': interaction.guild.id,
                'players': {
                    interaction.user.id: {'position': self.your_position, 'accepted': True},
                    self.partner.id: {'position': self.partner_position, 'accepted': False}
                },
                'created_at': datetime.utcnow(),
                'expires_at': datetime.utcnow() + timedelta(minutes=5)
            }
            self.bot.pending_group_invites[invitation_id] = invitation_data

            try:
                partner_embed = discord.Embed(
                    title="Duo Queue Invitation",
                    description=f"{interaction.user.mention} wants to queue with you as a duo!",
                    color=discord.Color.blue()
                )
                partner_embed.add_field(
                    name="Queue Details",
                    value=f"**{interaction.user.name}:** {self.your_position}\n**You:** {self.partner_position}",
                    inline=False
                )
                partner_embed.add_field(name="Expires", value="5 minutes", inline=False)

                dm_sent = False
                try:
                    dm_view = GroupInviteView(self.bot, invitation_id, 'duo')
                    await self.partner.send(embed=partner_embed, view=dm_view)
                    dm_sent = True
                except (discord.Forbidden, discord.HTTPException):
                    pass

                config = await self.bot.db.get_config(interaction.guild.id)
                channel_sent = False
                invite_ch_id = config.get("invite_channel") or config.get("queue_channel")
                if invite_ch_id:
                    channel = self.bot.get_channel(invite_ch_id)
                    if channel:
                        try:
                            ch_view = GroupInviteView(self.bot, invitation_id, 'duo')
                            channel_embed = partner_embed.copy()
                            channel_embed.description = f"{self.partner.mention}, duo queue invitation from {interaction.user.mention}!"
                            await channel.send(embed=channel_embed, view=ch_view)
                            channel_sent = True
                        except (discord.Forbidden, discord.HTTPException):
                            pass

                if not dm_sent and not channel_sent:
                    await interaction.followup.send(f"Failed to send invitation to {self.partner.mention}!", ephemeral=True)
                    if invitation_id in self.bot.pending_group_invites:
                        del self.bot.pending_group_invites[invitation_id]
                    return

                embed = discord.Embed(
                    title="Duo Invitation Sent!",
                    description=f"Invitation sent to {self.partner.mention}",
                    color=discord.Color.green()
                )
                embed.add_field(
                    name="Queue Details",
                    value=f"**You:** {self.your_position}\n**{self.partner.name}:** {self.partner_position}",
                    inline=False
                )
                embed.set_footer(text="Invitation expires in 5 minutes")
                await interaction.followup.send(embed=embed, ephemeral=True)

                for child in self.children:
                    child.disabled = True
                try:
                    await interaction.edit_original_response(view=self)
                except:
                    pass

                asyncio.create_task(self.expire_invitation(invitation_id))
            except Exception as e:
                await interaction.followup.send(f"Failed to send invitation: {e}", ephemeral=True)
                if invitation_id in self.bot.pending_group_invites:
                    del self.bot.pending_group_invites[invitation_id]

    async def expire_invitation(self, invitation_id):
        await asyncio.sleep(300)
        if invitation_id in self.bot.pending_group_invites:
            del self.bot.pending_group_invites[invitation_id]


class TrioQueueView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=60)
        self.bot = bot
        self.partner1 = None
        self.partner2 = None
        self.your_position = None
        self.partner1_position = None
        self.partner2_position = None

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Select your first partner", min_values=1, max_values=1, row=0)
    async def partner1_select(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        self.partner1 = select.values[0]
        if self.partner1.id == interaction.user.id:
            await interaction.response.send_message("You cannot trio queue with yourself!", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await self.check_ready(interaction)

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Select your second partner", min_values=1, max_values=1, row=1)
    async def partner2_select(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        self.partner2 = select.values[0]
        if self.partner2.id == interaction.user.id:
            await interaction.response.send_message("You cannot trio queue with yourself!", ephemeral=True)
            return
        if self.partner1 and self.partner2.id == self.partner1.id:
            await interaction.response.send_message("Both partners must be different!", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await self.check_ready(interaction)

    @discord.ui.select(placeholder="Select YOUR position", options=[
        discord.SelectOption(label="Defense Specialist", value="Defense Specialist"),
        discord.SelectOption(label="Front Spiker", value="Front Spiker"),
        discord.SelectOption(label="Setter", value="Setter"),
        discord.SelectOption(label="Libero", value="Libero")
    ], row=2)
    async def your_position_select(self, interaction, select):
        self.your_position = select.values[0]
        await interaction.response.defer(ephemeral=True)
        await self.check_ready(interaction)

    @discord.ui.select(placeholder="Select FIRST PARTNER'S position", options=[
        discord.SelectOption(label="Defense Specialist", value="Defense Specialist"),
        discord.SelectOption(label="Front Spiker", value="Front Spiker"),
        discord.SelectOption(label="Setter", value="Setter"),
        discord.SelectOption(label="Libero", value="Libero")
    ], row=3)
    async def partner1_position_select(self, interaction, select):
        self.partner1_position = select.values[0]
        await interaction.response.defer(ephemeral=True)
        await self.check_ready(interaction)

    @discord.ui.select(placeholder="Select SECOND PARTNER'S position", options=[
        discord.SelectOption(label="Defense Specialist", value="Defense Specialist"),
        discord.SelectOption(label="Front Spiker", value="Front Spiker"),
        discord.SelectOption(label="Setter", value="Setter"),
        discord.SelectOption(label="Libero", value="Libero")
    ], row=4)
    async def partner2_position_select(self, interaction, select):
        self.partner2_position = select.values[0]
        await interaction.response.defer(ephemeral=True)
        await self.check_ready(interaction)

    async def check_ready(self, interaction: discord.Interaction):
        if not all([self.partner1, self.partner2, self.your_position, self.partner1_position, self.partner2_position]):
            return

        # Block Libero for 5v5 regions
        config = await self.bot.db.get_config(interaction.guild.id)
        players_and_positions = [
            (interaction.user, self.your_position),
            (self.partner1, self.partner1_position),
            (self.partner2, self.partner2_position),
        ]
        for player, pos in players_and_positions:
            if pos == "Libero":
                player_region = await self.bot.db.get_player_region(interaction.guild.id, player.id)
                if player_region and is_5v5_region(config, player_region):
                    name = "You" if player.id == interaction.user.id else player.mention
                    await interaction.followup.send(
                        f"Libero is not available for {name} in the 5v5 format. Only **Defense Specialist** is queueable for the defensive role.",
                        ephemeral=True
                    )
                    return

        # Trio position restrictions: can't triple up on DS or FS
        trio_positions = [self.your_position, self.partner1_position, self.partner2_position]
        for restricted_pos in ("Defense Specialist", "Front Spiker"):
            if trio_positions.count(restricted_pos) >= 3:
                await interaction.followup.send(
                    f"Trio queue cannot have all three players as **{restricted_pos}**. Please pick different positions.",
                    ephemeral=True
                )
                return

        blacklist_role = await self.bot.get_blacklist_role(interaction.guild)

        for partner in [self.partner1, self.partner2]:
            if blacklist_role and blacklist_role in partner.roles:
                await interaction.followup.send(f"{partner.mention} is blacklisted!", ephemeral=True)
                return
            reason = await self.bot.db.is_blacklisted(interaction.guild.id, partner.id)
            if reason is not None:
                await interaction.followup.send(f"{partner.mention} is blacklisted!", ephemeral=True)
                return

        # Check partners have required roles
        for partner in [self.partner1, self.partner2]:
            if not await check_required_roles_member(interaction.guild.id, partner, self.bot):
                await interaction.followup.send(
                    f"{partner.mention} does not have the required role to queue!",
                    ephemeral=True
                )
                return

        # Check if any player is in an active match
        in_match = []
        for player in [interaction.user, self.partner1, self.partner2]:
            if await self.bot.db.is_user_in_active_match(interaction.guild.id, player.id):
                in_match.append("You" if player.id == interaction.user.id else player.mention)
        if in_match:
            await interaction.followup.send(
                f"{', '.join(in_match)} {'is' if len(in_match) == 1 else 'are'} currently in an active match!",
                ephemeral=True
            )
            return

        queue = await self.bot.db.get_queue(interaction.guild.id)
        queued_players = [q[0] for q in queue]
        already_queued = []
        if interaction.user.id in queued_players:
            already_queued.append("You")
        if self.partner1.id in queued_players:
            already_queued.append(self.partner1.name)
        if self.partner2.id in queued_players:
            already_queued.append(self.partner2.name)

        if already_queued:
            await interaction.followup.send(
                f"Already in queue: {', '.join(already_queued)}\nAll must leave first.",
                ephemeral=True
            )
            return

        invitation_id = f"trio_{interaction.guild.id}_{interaction.user.id}_{datetime.utcnow().timestamp()}"
        invitation_data = {
            'type': 'trio',
            'initiator': interaction.user.id,
            'guild_id': interaction.guild.id,
            'players': {
                interaction.user.id: {'position': self.your_position, 'accepted': True},
                self.partner1.id: {'position': self.partner1_position, 'accepted': False},
                self.partner2.id: {'position': self.partner2_position, 'accepted': False}
            },
            'created_at': datetime.utcnow(),
            'expires_at': datetime.utcnow() + timedelta(minutes=5)
        }
        self.bot.pending_group_invites[invitation_id] = invitation_data

        config = await self.bot.db.get_config(interaction.guild.id)
        invite_ch_id = config.get("invite_channel") or config.get("queue_channel")
        queue_channel = self.bot.get_channel(invite_ch_id) if invite_ch_id else None

        invitations_sent = 0
        failed_partners = []

        for partner, partner_pos in [(self.partner1, self.partner1_position), (self.partner2, self.partner2_position)]:
            try:
                other_partner = self.partner2 if partner == self.partner1 else self.partner1
                other_pos = self.partner2_position if partner == self.partner1 else self.partner1_position

                partner_embed = discord.Embed(
                    title="Trio Queue Invitation",
                    description=f"{interaction.user.mention} wants to queue with you in a trio!",
                    color=discord.Color.green()
                )
                partner_embed.add_field(
                    name="Queue Details",
                    value=f"**{interaction.user.name}:** {self.your_position}\n"
                          f"**You:** {partner_pos}\n"
                          f"**{other_partner.name}:** {other_pos}",
                    inline=False
                )
                partner_embed.add_field(name="Expires", value="5 minutes", inline=False)

                sent = False
                try:
                    dm_view = GroupInviteView(self.bot, invitation_id, 'trio')
                    await partner.send(embed=partner_embed, view=dm_view)
                    sent = True
                except (discord.Forbidden, discord.HTTPException):
                    if queue_channel:
                        try:
                            ch_view = GroupInviteView(self.bot, invitation_id, 'trio')
                            ch_embed = partner_embed.copy()
                            ch_embed.description = f"{partner.mention}, trio invitation from {interaction.user.mention}!"
                            await queue_channel.send(embed=ch_embed, view=ch_view)
                            sent = True
                        except (discord.Forbidden, discord.HTTPException):
                            pass
                if sent:
                    invitations_sent += 1
                else:
                    failed_partners.append(partner.name)
            except:
                failed_partners.append(partner.name)

        if invitations_sent < 2:
            await interaction.followup.send("Failed to send invitations to all partners. Trio cancelled.", ephemeral=True)
            if invitation_id in self.bot.pending_group_invites:
                del self.bot.pending_group_invites[invitation_id]
            return

        embed = discord.Embed(
            title="Trio Invitations Sent!",
            description=f"Invitations sent to {self.partner1.mention} and {self.partner2.mention}",
            color=discord.Color.green()
        )
        embed.set_footer(text="Invitation expires in 5 minutes")
        await interaction.followup.send(embed=embed, ephemeral=True)

        for child in self.children:
            child.disabled = True
        try:
            await interaction.edit_original_response(view=self)
        except:
            pass

        asyncio.create_task(self.expire_invitation(invitation_id))

    async def expire_invitation(self, invitation_id):
        await asyncio.sleep(300)
        if invitation_id in self.bot.pending_group_invites:
            del self.bot.pending_group_invites[invitation_id]


# ──────────────────────────────────────────────
#  GROUP INVITE VIEW
# ──────────────────────────────────────────────

class GroupInviteView(discord.ui.View):
    def __init__(self, bot, invitation_id, invite_type):
        super().__init__(timeout=300)
        self.bot = bot
        self.invitation_id = invitation_id
        self.invite_type = invite_type

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success)
    async def accept_invite(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.invitation_id not in self.bot.pending_group_invites:
            await interaction.response.send_message("This invitation has expired or been cancelled.", ephemeral=True)
            return

        invitation = self.bot.pending_group_invites[self.invitation_id]

        # Only the intended recipients (non-initiator players) can accept
        if interaction.user.id not in invitation['players'] or interaction.user.id == invitation.get('initiator'):
            await interaction.response.send_message("This invitation is not for you!", ephemeral=True)
            return

        invitation['players'][interaction.user.id]['accepted'] = True
        all_accepted = all(p['accepted'] for p in invitation['players'].values())

        if all_accepted:
            # Check if any player is now in an active match before adding to queue
            guild_id = invitation['guild_id']
            for pid in invitation['players']:
                if await self.bot.db.is_user_in_active_match(guild_id, pid):
                    user = self.bot.get_user(pid)
                    name = user.mention if user else f"User {pid}"
                    await interaction.response.send_message(
                        f"{name} is currently in an active match! Cannot join queue.",
                        ephemeral=True
                    )
                    del self.bot.pending_group_invites[self.invitation_id]
                    for child in self.children:
                        child.disabled = True
                    return

            success = True
            queue_type = invitation.get('queue_type', '6v6')

            if self.invite_type in ('duo', 'duo2v2', 'duo3v3', 'duo_hr2v2', 'duo_hr3v3'):
                player_ids = list(invitation['players'].keys())
                if self.invite_type == 'duo2v2':
                    try:
                        await self.bot.db.db.execute(
                            'INSERT INTO queue (guild_id, user_id, position, duo_partner, queue_type) VALUES (?, ?, ?, ?, ?)',
                            (invitation['guild_id'], player_ids[0], 'Player', str(player_ids[1]), '2v2')
                        )
                        await self.bot.db.db.execute(
                            'INSERT INTO queue (guild_id, user_id, position, duo_partner, queue_type) VALUES (?, ?, ?, ?, ?)',
                            (invitation['guild_id'], player_ids[1], 'Player', str(player_ids[0]), '2v2')
                        )
                        await self.bot.db.db.commit()
                        for pid in player_ids:
                            await self.bot._send_queue_join_dm(invitation['guild_id'], pid, 'Player', '2v2')
                        await self.bot.check_match_ready(invitation['guild_id'], '2v2')
                    except:
                        success = False
                elif self.invite_type == 'duo3v3':
                    try:
                        await self.bot.db.db.execute(
                            'INSERT INTO queue (guild_id, user_id, position, duo_partner, queue_type) VALUES (?, ?, ?, ?, ?)',
                            (invitation['guild_id'], player_ids[0], 'Player', str(player_ids[1]), '3v3')
                        )
                        await self.bot.db.db.execute(
                            'INSERT INTO queue (guild_id, user_id, position, duo_partner, queue_type) VALUES (?, ?, ?, ?, ?)',
                            (invitation['guild_id'], player_ids[1], 'Player', str(player_ids[0]), '3v3')
                        )
                        await self.bot.db.db.commit()
                        for pid in player_ids:
                            await self.bot._send_queue_join_dm(invitation['guild_id'], pid, 'Player', '3v3')
                        await self.bot.check_match_ready(invitation['guild_id'], '3v3')
                    except:
                        success = False
                elif self.invite_type == 'duo_hr2v2':
                    try:
                        await self.bot.db.db.execute(
                            'INSERT INTO queue (guild_id, user_id, position, duo_partner, queue_type) VALUES (?, ?, ?, ?, ?)',
                            (invitation['guild_id'], player_ids[0], 'Player', str(player_ids[1]), 'highrank_2v2')
                        )
                        await self.bot.db.db.execute(
                            'INSERT INTO queue (guild_id, user_id, position, duo_partner, queue_type) VALUES (?, ?, ?, ?, ?)',
                            (invitation['guild_id'], player_ids[1], 'Player', str(player_ids[0]), 'highrank_2v2')
                        )
                        await self.bot.db.db.commit()
                        for pid in player_ids:
                            await self.bot._send_queue_join_dm(invitation['guild_id'], pid, 'Player', 'highrank_2v2')
                        await self.bot.check_match_ready(invitation['guild_id'], 'highrank_2v2')
                    except:
                        success = False
                elif self.invite_type == 'duo_hr3v3':
                    try:
                        await self.bot.db.db.execute(
                            'INSERT INTO queue (guild_id, user_id, position, duo_partner, queue_type) VALUES (?, ?, ?, ?, ?)',
                            (invitation['guild_id'], player_ids[0], 'Player', str(player_ids[1]), 'highrank_3v3')
                        )
                        await self.bot.db.db.execute(
                            'INSERT INTO queue (guild_id, user_id, position, duo_partner, queue_type) VALUES (?, ?, ?, ?, ?)',
                            (invitation['guild_id'], player_ids[1], 'Player', str(player_ids[0]), 'highrank_3v3')
                        )
                        await self.bot.db.db.commit()
                        for pid in player_ids:
                            await self.bot._send_queue_join_dm(invitation['guild_id'], pid, 'Player', 'highrank_3v3')
                        await self.bot.check_match_ready(invitation['guild_id'], 'highrank_3v3')
                    except:
                        success = False
                else:
                    success = await self.bot.add_duo_to_queue(
                        invitation['guild_id'],
                        player_ids[0], player_ids[1],
                        invitation['players'][player_ids[0]]['position'],
                        invitation['players'][player_ids[1]]['position']
                    )
            elif self.invite_type in ('trio3v3', 'trio_hr3v3'):
                player_ids = list(invitation['players'].keys())
                hr_queue_type = 'highrank_3v3' if self.invite_type == 'trio_hr3v3' else '3v3'
                try:
                    trio_data = json.dumps({'trio': player_ids})
                    for pid in player_ids:
                        await self.bot.db.db.execute(
                            'INSERT INTO queue (guild_id, user_id, position, duo_partner, queue_type) VALUES (?, ?, ?, ?, ?)',
                            (invitation['guild_id'], pid, 'Player', trio_data, hr_queue_type)
                        )
                    await self.bot.db.db.commit()
                    for pid in player_ids:
                        await self.bot._send_queue_join_dm(invitation['guild_id'], pid, 'Player', hr_queue_type)
                    await self.bot.check_match_ready(invitation['guild_id'], hr_queue_type)
                except:
                    success = False
            else:
                player_ids = list(invitation['players'].keys())
                success = await self.bot.add_trio_to_queue(
                    invitation['guild_id'],
                    player_ids[0], player_ids[1], player_ids[2],
                    invitation['players'][player_ids[0]]['position'],
                    invitation['players'][player_ids[1]]['position'],
                    invitation['players'][player_ids[2]]['position']
                )

            if success:
                display_type = self.invite_type.replace('2v2', ' 2v2').replace('3v3', ' 3v3').title()
                embed = discord.Embed(
                    title=f"{display_type} Queue Success!",
                    description="All players accepted! You've been added to the queue.",
                    color=discord.Color.green()
                )
                composition = ""
                for pid, pdata in invitation['players'].items():
                    user = self.bot.get_user(pid)
                    composition += f"{user.mention if user else f'User {pid}'}\n"
                embed.add_field(name="Group Composition", value=composition, inline=False)

                # Update appropriate queue embed
                if queue_type in ('2v2', 'highrank_2v2'):
                    await self.bot.update_queue_embed_2v2(invitation['guild_id'])
                elif queue_type in ('3v3', 'highrank_3v3'):
                    await self.bot.update_queue_embed_3v3(invitation['guild_id'])
                else:
                    await self.bot.update_queue_embed(invitation['guild_id'])

                config = await self.bot.db.get_config(invitation['guild_id'])
                notify_channel_key = {
                    '2v2': 'queue_2v2_channel',
                    '3v3': 'queue_3v3_channel',
                    'highrank_2v2': 'queue_2v2_channel',
                    'highrank_3v3': 'queue_3v3_channel',
                }.get(queue_type, 'queue_channel')
                ch_id = config.get(notify_channel_key) or config.get("queue_channel")
                if ch_id:
                    channel = self.bot.get_channel(ch_id)
                    if channel:
                        await channel.send(embed=embed)

                del self.bot.pending_group_invites[self.invitation_id]

                for child in self.children:
                    child.disabled = True
                await interaction.response.edit_message(content="You accepted! All players have accepted.", view=self)
            else:
                await interaction.response.send_message("Failed to add group to queue.", ephemeral=True)
                del self.bot.pending_group_invites[self.invitation_id]
        else:
            status_text = ""
            for pid, pdata in invitation['players'].items():
                user = self.bot.get_user(pid)
                status = "Accepted" if pdata['accepted'] else "Pending"
                status_text += f"{status} - {user.name if user else f'User {pid}'}\n"

            embed = discord.Embed(
                title="Invitation Status",
                description=f"You accepted! Waiting for other players...\n\n{status_text}",
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline_invite(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.invitation_id not in self.bot.pending_group_invites:
            await interaction.response.send_message("This invitation has expired or been cancelled.", ephemeral=True)
            return

        invitation = self.bot.pending_group_invites[self.invitation_id]

        # Only the intended recipients (non-initiator players) can decline
        if interaction.user.id not in invitation['players'] or interaction.user.id == invitation.get('initiator'):
            await interaction.response.send_message("This invitation is not for you!", ephemeral=True)
            return

        initiator = self.bot.get_user(invitation['initiator'])
        if initiator:
            try:
                decline_embed = discord.Embed(
                    title=f"{self.invite_type.title()} Invitation Declined",
                    description=f"{interaction.user.mention} declined your {self.invite_type} queue invitation.",
                    color=discord.Color.red()
                )
                await initiator.send(embed=decline_embed)
            except:
                config = await self.bot.db.get_config(invitation['guild_id'])
                ch_id = config.get("invite_channel") or config.get("queue_channel")
                if ch_id:
                    channel = self.bot.get_channel(ch_id)
                    if channel:
                        await channel.send(f"{initiator.mention}", embed=decline_embed)

        del self.bot.pending_group_invites[self.invitation_id]

        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="You declined the invitation.", view=self)

    async def on_timeout(self):
        if self.invitation_id in self.bot.pending_group_invites:
            del self.bot.pending_group_invites[self.invitation_id]


# ──────────────────────────────────────────────
#  DUO 2v2 / TRIO 3v3 PARTY SETUP VIEWS
# ──────────────────────────────────────────────

class Duo2v2SetupView(discord.ui.View):
    """Setup view for queuing as a duo party in 2v2."""
    def __init__(self, bot):
        super().__init__(timeout=60)
        self.bot = bot
        self.partner = None

    @discord.ui.select(
        cls=discord.ui.UserSelect,
        placeholder="Select your 2v2 partner",
        min_values=1, max_values=1
    )
    async def partner_select(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        self.partner = select.values[0]
        if self.partner.id == interaction.user.id:
            await interaction.response.send_message("You cannot duo with yourself!", ephemeral=True)
            return

        # Check partner blacklist
        blacklist_role = await self.bot.get_blacklist_role(interaction.guild)
        if blacklist_role and blacklist_role in self.partner.roles:
            await interaction.response.send_message(f"{self.partner.mention} is blacklisted!", ephemeral=True)
            return

        reason = await self.bot.db.is_blacklisted(interaction.guild.id, self.partner.id)
        if reason is not None:
            await interaction.response.send_message(f"{self.partner.mention} is blacklisted!", ephemeral=True)
            return

        # Check partner has required role
        if not await check_required_roles_member(interaction.guild.id, self.partner, self.bot):
            await interaction.response.send_message(
                f"{self.partner.mention} does not have the required role to queue!",
                ephemeral=True
            )
            return

        # Check if either player is in an active match
        if await self.bot.db.is_user_in_active_match(interaction.guild.id, interaction.user.id):
            await interaction.response.send_message(
                "You cannot send invites while in an active match! Please finish your current match first.",
                ephemeral=True
            )
            return
        if await self.bot.db.is_user_in_active_match(interaction.guild.id, self.partner.id):
            await interaction.response.send_message(
                f"{self.partner.mention} is currently in an active match!",
                ephemeral=True
            )
            return

        # Check if already in queue
        queue = await self.bot.db.get_queue(interaction.guild.id, '2v2')
        queued_ids = [q[0] for q in queue]
        if interaction.user.id in queued_ids:
            await interaction.response.send_message("You are already in the 2v2 queue! Leave first.", ephemeral=True)
            return
        if self.partner.id in queued_ids:
            await interaction.response.send_message(f"{self.partner.mention} is already in the 2v2 queue!", ephemeral=True)
            return

        # Send invitation
        invitation_id = f"duo2v2_{interaction.guild.id}_{interaction.user.id}_{self.partner.id}_{datetime.utcnow().timestamp()}"
        invitation_data = {
            'type': 'duo2v2',
            'initiator': interaction.user.id,
            'guild_id': interaction.guild.id,
            'queue_type': '2v2',
            'players': {
                interaction.user.id: {'position': 'Player', 'accepted': True},
                self.partner.id: {'position': 'Player', 'accepted': False}
            },
            'created_at': datetime.utcnow(),
            'expires_at': datetime.utcnow() + timedelta(minutes=5)
        }
        self.bot.pending_group_invites[invitation_id] = invitation_data

        partner_embed = discord.Embed(
            title="2v2 Duo Party Invitation",
            description=f"{interaction.user.mention} wants to duo queue with you in 2v2!",
            color=discord.Color.green()
        )
        partner_embed.add_field(name="Expires", value="5 minutes", inline=False)

        dm_sent = False
        try:
            dm_view = GroupInviteView(self.bot, invitation_id, 'duo2v2')
            await self.partner.send(embed=partner_embed, view=dm_view)
            dm_sent = True
        except (discord.Forbidden, discord.HTTPException):
            pass

        config = await self.bot.db.get_config(interaction.guild.id)
        channel_sent = False
        ch_id = config.get("invite_channel") or config.get("queue_2v2_channel") or config.get("queue_channel")
        if ch_id:
            channel = self.bot.get_channel(ch_id)
            if channel:
                try:
                    ch_view = GroupInviteView(self.bot, invitation_id, 'duo2v2')
                    ch_embed = partner_embed.copy()
                    ch_embed.description = f"{self.partner.mention}, 2v2 duo invitation from {interaction.user.mention}!"
                    await channel.send(embed=ch_embed, view=ch_view)
                    channel_sent = True
                except (discord.Forbidden, discord.HTTPException):
                    pass

        if not dm_sent and not channel_sent:
            await interaction.response.send_message(f"Failed to send invitation to {self.partner.mention}!", ephemeral=True)
            if invitation_id in self.bot.pending_group_invites:
                del self.bot.pending_group_invites[invitation_id]
            return

        await interaction.response.send_message(
            f"Duo 2v2 invitation sent to {self.partner.mention}! Expires in 5 minutes.",
            ephemeral=True
        )

        for child in self.children:
            child.disabled = True
        try:
            await interaction.edit_original_response(view=self)
        except:
            pass

        asyncio.create_task(self._expire(invitation_id))

    async def _expire(self, invitation_id):
        await asyncio.sleep(300)
        if invitation_id in self.bot.pending_group_invites:
            del self.bot.pending_group_invites[invitation_id]


class Trio3v3SetupView(discord.ui.View):
    """Setup view for queuing as a trio party in 3v3."""
    def __init__(self, bot):
        super().__init__(timeout=60)
        self.bot = bot
        self.partner1 = None
        self.partner2 = None

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Select first partner", min_values=1, max_values=1, row=0)
    async def partner1_select(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        self.partner1 = select.values[0]
        if self.partner1.id == interaction.user.id:
            await interaction.response.send_message("You cannot trio with yourself!", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await self._check_ready(interaction)

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Select second partner", min_values=1, max_values=1, row=1)
    async def partner2_select(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        self.partner2 = select.values[0]
        if self.partner2.id == interaction.user.id:
            await interaction.response.send_message("You cannot trio with yourself!", ephemeral=True)
            return
        if self.partner1 and self.partner2.id == self.partner1.id:
            await interaction.response.send_message("Both partners must be different!", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await self._check_ready(interaction)

    async def _check_ready(self, interaction: discord.Interaction):
        if not self.partner1 or not self.partner2:
            return

        blacklist_role = await self.bot.get_blacklist_role(interaction.guild)
        for partner in [self.partner1, self.partner2]:
            if blacklist_role and blacklist_role in partner.roles:
                await interaction.followup.send(f"{partner.mention} is blacklisted!", ephemeral=True)
                return
            reason = await self.bot.db.is_blacklisted(interaction.guild.id, partner.id)
            if reason is not None:
                await interaction.followup.send(f"{partner.mention} is blacklisted!", ephemeral=True)
                return

        # Check partners have required roles
        for partner in [self.partner1, self.partner2]:
            if not await check_required_roles_member(interaction.guild.id, partner, self.bot):
                await interaction.followup.send(
                    f"{partner.mention} does not have the required role to queue!",
                    ephemeral=True
                )
                return

        # Check if any player is in an active match
        in_match = []
        for player in [interaction.user, self.partner1, self.partner2]:
            if await self.bot.db.is_user_in_active_match(interaction.guild.id, player.id):
                in_match.append("You" if player.id == interaction.user.id else player.mention)
        if in_match:
            await interaction.followup.send(
                f"{', '.join(in_match)} {'is' if len(in_match) == 1 else 'are'} currently in an active match!",
                ephemeral=True
            )
            return

        queue = await self.bot.db.get_queue(interaction.guild.id, '3v3')
        queued_ids = [q[0] for q in queue]
        already = []
        if interaction.user.id in queued_ids:
            already.append("You")
        if self.partner1.id in queued_ids:
            already.append(self.partner1.name)
        if self.partner2.id in queued_ids:
            already.append(self.partner2.name)
        if already:
            await interaction.followup.send(f"Already in 3v3 queue: {', '.join(already)}", ephemeral=True)
            return

        invitation_id = f"trio3v3_{interaction.guild.id}_{interaction.user.id}_{datetime.utcnow().timestamp()}"
        invitation_data = {
            'type': 'trio3v3',
            'initiator': interaction.user.id,
            'guild_id': interaction.guild.id,
            'queue_type': '3v3',
            'players': {
                interaction.user.id: {'position': 'Player', 'accepted': True},
                self.partner1.id: {'position': 'Player', 'accepted': False},
                self.partner2.id: {'position': 'Player', 'accepted': False}
            },
            'created_at': datetime.utcnow(),
            'expires_at': datetime.utcnow() + timedelta(minutes=5)
        }
        self.bot.pending_group_invites[invitation_id] = invitation_data

        config = await self.bot.db.get_config(interaction.guild.id)
        ch_id = config.get("invite_channel") or config.get("queue_3v3_channel") or config.get("queue_channel")
        queue_channel = self.bot.get_channel(ch_id) if ch_id else None

        for partner in [self.partner1, self.partner2]:
            embed = discord.Embed(
                title="3v3 Trio Party Invitation",
                description=f"{interaction.user.mention} wants to trio queue with you in 3v3!",
                color=discord.Color.orange()
            )
            embed.add_field(name="Expires", value="5 minutes", inline=False)
            try:
                dm_view = GroupInviteView(self.bot, invitation_id, 'trio3v3')
                await partner.send(embed=embed, view=dm_view)
            except (discord.Forbidden, discord.HTTPException):
                if queue_channel:
                    try:
                        ch_view = GroupInviteView(self.bot, invitation_id, 'trio3v3')
                        ch_embed = embed.copy()
                        ch_embed.description = f"{partner.mention}, 3v3 trio invitation from {interaction.user.mention}!"
                        await queue_channel.send(embed=ch_embed, view=ch_view)
                    except (discord.Forbidden, discord.HTTPException):
                        pass

        await interaction.followup.send(
            f"Trio 3v3 invitations sent to {self.partner1.mention} and {self.partner2.mention}!",
            ephemeral=True
        )

        for child in self.children:
            child.disabled = True
        try:
            await interaction.edit_original_response(view=self)
        except:
            pass

        asyncio.create_task(self._expire(invitation_id))

    async def _expire(self, invitation_id):
        await asyncio.sleep(300)
        if invitation_id in self.bot.pending_group_invites:
            del self.bot.pending_group_invites[invitation_id]


class Duo3v3SetupView(discord.ui.View):
    """Setup view for queuing as a duo party in 3v3."""
    def __init__(self, bot):
        super().__init__(timeout=60)
        self.bot = bot
        self.partner = None

    @discord.ui.select(
        cls=discord.ui.UserSelect,
        placeholder="Select your 3v3 duo partner",
        min_values=1, max_values=1
    )
    async def partner_select(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        self.partner = select.values[0]
        if self.partner.id == interaction.user.id:
            await interaction.response.send_message("You cannot duo with yourself!", ephemeral=True)
            return

        # Check partner blacklist
        blacklist_role = await self.bot.get_blacklist_role(interaction.guild)
        if blacklist_role and blacklist_role in self.partner.roles:
            await interaction.response.send_message(f"{self.partner.mention} is blacklisted!", ephemeral=True)
            return

        reason = await self.bot.db.is_blacklisted(interaction.guild.id, self.partner.id)
        if reason is not None:
            await interaction.response.send_message(f"{self.partner.mention} is blacklisted!", ephemeral=True)
            return

        # Check partner has required role
        if not await check_required_roles_member(interaction.guild.id, self.partner, self.bot):
            await interaction.response.send_message(
                f"{self.partner.mention} does not have the required role to queue!",
                ephemeral=True
            )
            return

        # Check if either player is in an active match
        if await self.bot.db.is_user_in_active_match(interaction.guild.id, interaction.user.id):
            await interaction.response.send_message(
                "You cannot send invites while in an active match! Please finish your current match first.",
                ephemeral=True
            )
            return
        if await self.bot.db.is_user_in_active_match(interaction.guild.id, self.partner.id):
            await interaction.response.send_message(
                f"{self.partner.mention} is currently in an active match!",
                ephemeral=True
            )
            return

        # Check if already in queue
        queue = await self.bot.db.get_queue(interaction.guild.id, '3v3')
        queued_ids = [q[0] for q in queue]
        if interaction.user.id in queued_ids:
            await interaction.response.send_message("You are already in the 3v3 queue! Leave first.", ephemeral=True)
            return
        if self.partner.id in queued_ids:
            await interaction.response.send_message(f"{self.partner.mention} is already in the 3v3 queue!", ephemeral=True)
            return

        # Send invitation
        invitation_id = f"duo3v3_{interaction.guild.id}_{interaction.user.id}_{self.partner.id}_{datetime.utcnow().timestamp()}"
        invitation_data = {
            'type': 'duo3v3',
            'initiator': interaction.user.id,
            'guild_id': interaction.guild.id,
            'queue_type': '3v3',
            'players': {
                interaction.user.id: {'position': 'Player', 'accepted': True},
                self.partner.id: {'position': 'Player', 'accepted': False}
            },
            'created_at': datetime.utcnow(),
            'expires_at': datetime.utcnow() + timedelta(minutes=5)
        }
        self.bot.pending_group_invites[invitation_id] = invitation_data

        partner_embed = discord.Embed(
            title="3v3 Duo Party Invitation",
            description=f"{interaction.user.mention} wants to duo queue with you in 3v3!",
            color=discord.Color.orange()
        )
        partner_embed.add_field(name="Expires", value="5 minutes", inline=False)

        dm_sent = False
        try:
            dm_view = GroupInviteView(self.bot, invitation_id, 'duo3v3')
            await self.partner.send(embed=partner_embed, view=dm_view)
            dm_sent = True
        except (discord.Forbidden, discord.HTTPException):
            pass

        config = await self.bot.db.get_config(interaction.guild.id)
        channel_sent = False
        ch_id = config.get("invite_channel") or config.get("queue_3v3_channel") or config.get("queue_channel")
        if ch_id:
            channel = self.bot.get_channel(ch_id)
            if channel:
                try:
                    ch_view = GroupInviteView(self.bot, invitation_id, 'duo3v3')
                    ch_embed = partner_embed.copy()
                    ch_embed.description = f"{self.partner.mention}, 3v3 duo invitation from {interaction.user.mention}!"
                    await channel.send(embed=ch_embed, view=ch_view)
                    channel_sent = True
                except (discord.Forbidden, discord.HTTPException):
                    pass

        if not dm_sent and not channel_sent:
            await interaction.response.send_message(f"Failed to send invitation to {self.partner.mention}!", ephemeral=True)
            if invitation_id in self.bot.pending_group_invites:
                del self.bot.pending_group_invites[invitation_id]
            return

        await interaction.response.send_message(
            f"Duo 3v3 invitation sent to {self.partner.mention}! Expires in 5 minutes.",
            ephemeral=True
        )

        for child in self.children:
            child.disabled = True
        try:
            await interaction.edit_original_response(view=self)
        except:
            pass

        asyncio.create_task(self._expire_invite(invitation_id))

    async def _expire_invite(self, invitation_id):
        await asyncio.sleep(300)
        if invitation_id in self.bot.pending_group_invites:
            del self.bot.pending_group_invites[invitation_id]


# ──────────────────────────────────────────────
#  HIGH RANK DUO/TRIO SETUP VIEWS
# ──────────────────────────────────────────────

class DuoHighRank2v2SetupView(discord.ui.View):
    """Setup view for queuing as a duo party in high rank 2v2."""
    def __init__(self, bot, mmr_limit):
        super().__init__(timeout=60)
        self.bot = bot
        self.mmr_limit = mmr_limit

    @discord.ui.select(
        cls=discord.ui.UserSelect,
        placeholder="Select your high rank 2v2 partner",
        min_values=1, max_values=1
    )
    async def partner_select(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        partner = select.values[0]
        if partner.id == interaction.user.id:
            await interaction.response.send_message("You cannot duo with yourself!", ephemeral=True)
            return

        blacklist_role = await self.bot.get_blacklist_role(interaction.guild)
        if blacklist_role and blacklist_role in partner.roles:
            await interaction.response.send_message(f"{partner.mention} is blacklisted!", ephemeral=True)
            return
        reason = await self.bot.db.is_blacklisted(interaction.guild.id, partner.id)
        if reason is not None:
            await interaction.response.send_message(f"{partner.mention} is blacklisted!", ephemeral=True)
            return

        # Check partner has required role
        if not await check_required_roles_member(interaction.guild.id, partner, self.bot):
            await interaction.response.send_message(
                f"{partner.mention} does not have the required role to queue!",
                ephemeral=True
            )
            return

        # Check partner MMR requirement
        partner_stats = await self.bot.db.get_player_stats_simple(interaction.guild.id, partner.id, '2v2')
        partner_elo = partner_stats[0] if partner_stats else 0
        if partner_elo < self.mmr_limit:
            await interaction.response.send_message(
                f"{partner.mention} needs at least **{self.mmr_limit}** MMR in normal 2v2 for high rank.\n"
                f"Their current 2v2 MMR: **{partner_elo}**",
                ephemeral=True
            )
            return

        # Check if either player is in an active match
        if await self.bot.db.is_user_in_active_match(interaction.guild.id, interaction.user.id):
            await interaction.response.send_message(
                "You cannot send invites while in an active match! Please finish your current match first.",
                ephemeral=True
            )
            return
        if await self.bot.db.is_user_in_active_match(interaction.guild.id, partner.id):
            await interaction.response.send_message(
                f"{partner.mention} is currently in an active match!",
                ephemeral=True
            )
            return

        # Check if already in queue
        queue = await self.bot.db.get_queue(interaction.guild.id, 'highrank_2v2')
        queued_ids = [q[0] for q in queue]
        if interaction.user.id in queued_ids:
            await interaction.response.send_message("You are already in the high rank 2v2 queue!", ephemeral=True)
            return
        if partner.id in queued_ids:
            await interaction.response.send_message(f"{partner.mention} is already in the high rank 2v2 queue!", ephemeral=True)
            return

        invitation_id = f"duo_hr2v2_{interaction.guild.id}_{interaction.user.id}_{partner.id}_{datetime.utcnow().timestamp()}"
        invitation_data = {
            'type': 'duo_hr2v2',
            'initiator': interaction.user.id,
            'guild_id': interaction.guild.id,
            'queue_type': 'highrank_2v2',
            'players': {
                interaction.user.id: {'position': 'Player', 'accepted': True},
                partner.id: {'position': 'Player', 'accepted': False}
            },
            'created_at': datetime.utcnow(),
            'expires_at': datetime.utcnow() + timedelta(minutes=5)
        }
        self.bot.pending_group_invites[invitation_id] = invitation_data

        partner_embed = discord.Embed(
            title="High Rank 2v2 Duo Invitation",
            description=f"{interaction.user.mention} wants to duo queue with you in **high rank 2v2**!",
            color=discord.Color.purple()
        )
        partner_embed.add_field(name="Expires", value="5 minutes", inline=False)

        dm_sent = False
        try:
            dm_view = GroupInviteView(self.bot, invitation_id, 'duo_hr2v2')
            await partner.send(embed=partner_embed, view=dm_view)
            dm_sent = True
        except (discord.Forbidden, discord.HTTPException):
            pass

        config = await self.bot.db.get_config(interaction.guild.id)
        channel_sent = False
        ch_id = config.get("invite_channel") or config.get("queue_2v2_channel") or config.get("queue_channel")
        if ch_id:
            channel = self.bot.get_channel(ch_id)
            if channel:
                try:
                    ch_view = GroupInviteView(self.bot, invitation_id, 'duo_hr2v2')
                    ch_embed = partner_embed.copy()
                    ch_embed.description = f"{partner.mention}, high rank 2v2 duo invitation from {interaction.user.mention}!"
                    await channel.send(embed=ch_embed, view=ch_view)
                    channel_sent = True
                except (discord.Forbidden, discord.HTTPException):
                    pass

        if not dm_sent and not channel_sent:
            await interaction.response.send_message(f"Failed to send invitation to {partner.mention}!", ephemeral=True)
            if invitation_id in self.bot.pending_group_invites:
                del self.bot.pending_group_invites[invitation_id]
            return

        await interaction.response.send_message(
            f"High rank 2v2 duo invitation sent to {partner.mention}! Expires in 5 minutes.",
            ephemeral=True
        )

        for child in self.children:
            child.disabled = True
        try:
            await interaction.edit_original_response(view=self)
        except:
            pass

        asyncio.create_task(self._expire(invitation_id))

    async def _expire(self, invitation_id):
        await asyncio.sleep(300)
        if invitation_id in self.bot.pending_group_invites:
            del self.bot.pending_group_invites[invitation_id]


class DuoHighRank3v3SetupView(discord.ui.View):
    """Setup view for queuing as a duo party in high rank 3v3."""
    def __init__(self, bot, mmr_limit):
        super().__init__(timeout=60)
        self.bot = bot
        self.mmr_limit = mmr_limit

    @discord.ui.select(
        cls=discord.ui.UserSelect,
        placeholder="Select your high rank 3v3 duo partner",
        min_values=1, max_values=1
    )
    async def partner_select(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        partner = select.values[0]
        if partner.id == interaction.user.id:
            await interaction.response.send_message("You cannot duo with yourself!", ephemeral=True)
            return

        blacklist_role = await self.bot.get_blacklist_role(interaction.guild)
        if blacklist_role and blacklist_role in partner.roles:
            await interaction.response.send_message(f"{partner.mention} is blacklisted!", ephemeral=True)
            return
        reason = await self.bot.db.is_blacklisted(interaction.guild.id, partner.id)
        if reason is not None:
            await interaction.response.send_message(f"{partner.mention} is blacklisted!", ephemeral=True)
            return

        # Check partner has required role
        if not await check_required_roles_member(interaction.guild.id, partner, self.bot):
            await interaction.response.send_message(
                f"{partner.mention} does not have the required role to queue!",
                ephemeral=True
            )
            return

        # Check partner MMR requirement
        partner_stats = await self.bot.db.get_player_stats_simple(interaction.guild.id, partner.id, '3v3')
        partner_elo = partner_stats[0] if partner_stats else 0
        if partner_elo < self.mmr_limit:
            await interaction.response.send_message(
                f"{partner.mention} needs at least **{self.mmr_limit}** MMR in normal 3v3 for high rank.\n"
                f"Their current 3v3 MMR: **{partner_elo}**",
                ephemeral=True
            )
            return

        # Check if either player is in an active match
        if await self.bot.db.is_user_in_active_match(interaction.guild.id, interaction.user.id):
            await interaction.response.send_message(
                "You cannot send invites while in an active match! Please finish your current match first.",
                ephemeral=True
            )
            return
        if await self.bot.db.is_user_in_active_match(interaction.guild.id, partner.id):
            await interaction.response.send_message(
                f"{partner.mention} is currently in an active match!",
                ephemeral=True
            )
            return

        queue = await self.bot.db.get_queue(interaction.guild.id, 'highrank_3v3')
        queued_ids = [q[0] for q in queue]
        if interaction.user.id in queued_ids:
            await interaction.response.send_message("You are already in the high rank 3v3 queue!", ephemeral=True)
            return
        if partner.id in queued_ids:
            await interaction.response.send_message(f"{partner.mention} is already in the high rank 3v3 queue!", ephemeral=True)
            return

        invitation_id = f"duo_hr3v3_{interaction.guild.id}_{interaction.user.id}_{partner.id}_{datetime.utcnow().timestamp()}"
        invitation_data = {
            'type': 'duo_hr3v3',
            'initiator': interaction.user.id,
            'guild_id': interaction.guild.id,
            'queue_type': 'highrank_3v3',
            'players': {
                interaction.user.id: {'position': 'Player', 'accepted': True},
                partner.id: {'position': 'Player', 'accepted': False}
            },
            'created_at': datetime.utcnow(),
            'expires_at': datetime.utcnow() + timedelta(minutes=5)
        }
        self.bot.pending_group_invites[invitation_id] = invitation_data

        partner_embed = discord.Embed(
            title="High Rank 3v3 Duo Invitation",
            description=f"{interaction.user.mention} wants to duo queue with you in **high rank 3v3**!",
            color=discord.Color.purple()
        )
        partner_embed.add_field(name="Expires", value="5 minutes", inline=False)

        dm_sent = False
        try:
            dm_view = GroupInviteView(self.bot, invitation_id, 'duo_hr3v3')
            await partner.send(embed=partner_embed, view=dm_view)
            dm_sent = True
        except (discord.Forbidden, discord.HTTPException):
            pass

        config = await self.bot.db.get_config(interaction.guild.id)
        channel_sent = False
        ch_id = config.get("invite_channel") or config.get("queue_3v3_channel") or config.get("queue_channel")
        if ch_id:
            channel = self.bot.get_channel(ch_id)
            if channel:
                try:
                    ch_view = GroupInviteView(self.bot, invitation_id, 'duo_hr3v3')
                    ch_embed = partner_embed.copy()
                    ch_embed.description = f"{partner.mention}, high rank 3v3 duo invitation from {interaction.user.mention}!"
                    await channel.send(embed=ch_embed, view=ch_view)
                    channel_sent = True
                except (discord.Forbidden, discord.HTTPException):
                    pass

        if not dm_sent and not channel_sent:
            await interaction.response.send_message(f"Failed to send invitation to {partner.mention}!", ephemeral=True)
            if invitation_id in self.bot.pending_group_invites:
                del self.bot.pending_group_invites[invitation_id]
            return

        await interaction.response.send_message(
            f"High rank 3v3 duo invitation sent to {partner.mention}! Expires in 5 minutes.",
            ephemeral=True
        )

        for child in self.children:
            child.disabled = True
        try:
            await interaction.edit_original_response(view=self)
        except:
            pass

        asyncio.create_task(self._expire(invitation_id))

    async def _expire(self, invitation_id):
        await asyncio.sleep(300)
        if invitation_id in self.bot.pending_group_invites:
            del self.bot.pending_group_invites[invitation_id]


class TrioHighRank3v3SetupView(discord.ui.View):
    """Setup view for queuing as a trio party in high rank 3v3."""
    def __init__(self, bot, mmr_limit):
        super().__init__(timeout=60)
        self.bot = bot
        self.mmr_limit = mmr_limit
        self.partner1 = None
        self.partner2 = None

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Select first partner", min_values=1, max_values=1, row=0)
    async def partner1_select(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        self.partner1 = select.values[0]
        if self.partner1.id == interaction.user.id:
            await interaction.response.send_message("You cannot trio with yourself!", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await self._check_ready(interaction)

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Select second partner", min_values=1, max_values=1, row=1)
    async def partner2_select(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        self.partner2 = select.values[0]
        if self.partner2.id == interaction.user.id:
            await interaction.response.send_message("You cannot trio with yourself!", ephemeral=True)
            return
        if self.partner1 and self.partner2.id == self.partner1.id:
            await interaction.response.send_message("Both partners must be different!", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await self._check_ready(interaction)

    async def _check_ready(self, interaction: discord.Interaction):
        if not self.partner1 or not self.partner2:
            return

        blacklist_role = await self.bot.get_blacklist_role(interaction.guild)
        for partner in [self.partner1, self.partner2]:
            if blacklist_role and blacklist_role in partner.roles:
                await interaction.followup.send(f"{partner.mention} is blacklisted!", ephemeral=True)
                return
            reason = await self.bot.db.is_blacklisted(interaction.guild.id, partner.id)
            if reason is not None:
                await interaction.followup.send(f"{partner.mention} is blacklisted!", ephemeral=True)
                return

        # Check partners have required roles
        for partner in [self.partner1, self.partner2]:
            if not await check_required_roles_member(interaction.guild.id, partner, self.bot):
                await interaction.followup.send(
                    f"{partner.mention} does not have the required role to queue!",
                    ephemeral=True
                )
                return

        # Check MMR for both partners
        for partner in [self.partner1, self.partner2]:
            partner_stats = await self.bot.db.get_player_stats_simple(interaction.guild.id, partner.id, '3v3')
            partner_elo = partner_stats[0] if partner_stats else 0
            if partner_elo < self.mmr_limit:
                await interaction.followup.send(
                    f"{partner.mention} needs at least **{self.mmr_limit}** MMR in normal 3v3 for high rank.\n"
                    f"Their current 3v3 MMR: **{partner_elo}**",
                    ephemeral=True
                )
                return

        # Check if any player is in an active match
        in_match = []
        for player in [interaction.user, self.partner1, self.partner2]:
            if await self.bot.db.is_user_in_active_match(interaction.guild.id, player.id):
                in_match.append("You" if player.id == interaction.user.id else player.mention)
        if in_match:
            await interaction.followup.send(
                f"{', '.join(in_match)} {'is' if len(in_match) == 1 else 'are'} currently in an active match!",
                ephemeral=True
            )
            return

        queue = await self.bot.db.get_queue(interaction.guild.id, 'highrank_3v3')
        queued_ids = [q[0] for q in queue]
        already = []
        if interaction.user.id in queued_ids:
            already.append("You")
        if self.partner1.id in queued_ids:
            already.append(self.partner1.name)
        if self.partner2.id in queued_ids:
            already.append(self.partner2.name)
        if already:
            await interaction.followup.send(f"Already in high rank 3v3 queue: {', '.join(already)}", ephemeral=True)
            return

        invitation_id = f"trio_hr3v3_{interaction.guild.id}_{interaction.user.id}_{datetime.utcnow().timestamp()}"
        invitation_data = {
            'type': 'trio_hr3v3',
            'initiator': interaction.user.id,
            'guild_id': interaction.guild.id,
            'queue_type': 'highrank_3v3',
            'players': {
                interaction.user.id: {'position': 'Player', 'accepted': True},
                self.partner1.id: {'position': 'Player', 'accepted': False},
                self.partner2.id: {'position': 'Player', 'accepted': False}
            },
            'created_at': datetime.utcnow(),
            'expires_at': datetime.utcnow() + timedelta(minutes=5)
        }
        self.bot.pending_group_invites[invitation_id] = invitation_data

        config = await self.bot.db.get_config(interaction.guild.id)
        ch_id = config.get("invite_channel") or config.get("queue_3v3_channel") or config.get("queue_channel")
        queue_channel = self.bot.get_channel(ch_id) if ch_id else None

        for partner in [self.partner1, self.partner2]:
            embed = discord.Embed(
                title="High Rank 3v3 Trio Invitation",
                description=f"{interaction.user.mention} wants to trio queue with you in **high rank 3v3**!",
                color=discord.Color.purple()
            )
            embed.add_field(name="Expires", value="5 minutes", inline=False)
            try:
                dm_view = GroupInviteView(self.bot, invitation_id, 'trio_hr3v3')
                await partner.send(embed=embed, view=dm_view)
            except (discord.Forbidden, discord.HTTPException):
                if queue_channel:
                    try:
                        ch_view = GroupInviteView(self.bot, invitation_id, 'trio_hr3v3')
                        ch_embed = embed.copy()
                        ch_embed.description = f"{partner.mention}, high rank 3v3 trio invitation from {interaction.user.mention}!"
                        await queue_channel.send(embed=ch_embed, view=ch_view)
                    except (discord.Forbidden, discord.HTTPException):
                        pass

        await interaction.followup.send(
            f"High rank 3v3 trio invitations sent to {self.partner1.mention} and {self.partner2.mention}!",
            ephemeral=True
        )

        for child in self.children:
            child.disabled = True
        try:
            await interaction.edit_original_response(view=self)
        except:
            pass

        asyncio.create_task(self._expire(invitation_id))

    async def _expire(self, invitation_id):
        await asyncio.sleep(300)
        if invitation_id in self.bot.pending_group_invites:
            del self.bot.pending_group_invites[invitation_id]


# ──────────────────────────────────────────────
#  HIGH RANK 6v6 DUO/TRIO SETUP VIEWS
# ──────────────────────────────────────────────

class DuoHighRankView(discord.ui.View):
    """Duo queue setup for high rank 6v6."""
    def __init__(self, bot, mmr_limit=1000):
        super().__init__(timeout=60)
        self.bot = bot
        self.mmr_limit = mmr_limit
        self.partner = None
        self.your_position = None
        self.partner_position = None

    @discord.ui.select(
        cls=discord.ui.UserSelect,
        placeholder="Select your duo partner",
        min_values=1, max_values=1
    )
    async def partner_select(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        self.partner = select.values[0]
        if self.partner.id == interaction.user.id:
            await interaction.response.send_message("You cannot duo queue with yourself!", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await self.check_ready(interaction)

    @discord.ui.select(
        placeholder="Select YOUR position",
        options=[
            discord.SelectOption(label="Defense Specialist", value="Defense Specialist"),
            discord.SelectOption(label="Front Spiker", value="Front Spiker"),
            discord.SelectOption(label="Setter", value="Setter"),
            discord.SelectOption(label="Libero", value="Libero")
        ],
        row=1
    )
    async def your_position_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.your_position = select.values[0]
        await interaction.response.defer(ephemeral=True)
        await self.check_ready(interaction)

    @discord.ui.select(
        placeholder="Select PARTNER'S position",
        options=[
            discord.SelectOption(label="Defense Specialist", value="Defense Specialist"),
            discord.SelectOption(label="Front Spiker", value="Front Spiker"),
            discord.SelectOption(label="Setter", value="Setter"),
            discord.SelectOption(label="Libero", value="Libero")
        ],
        row=2
    )
    async def partner_position_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.partner_position = select.values[0]
        await interaction.response.defer(ephemeral=True)
        await self.check_ready(interaction)

    async def check_ready(self, interaction: discord.Interaction):
        if not (self.partner and self.your_position and self.partner_position):
            return

        config = await self.bot.db.get_config(interaction.guild.id)

        # Block Libero for 5v5 regions
        initiator_region = await self.bot.db.get_player_region(interaction.guild.id, interaction.user.id)
        if initiator_region and is_5v5_region(config, initiator_region):
            if self.your_position == "Libero":
                await interaction.followup.send(
                    "Libero is not available in your region's 5v5 format. Only **Defense Specialist** is queueable for the defensive role.",
                    ephemeral=True
                )
                return
            if self.partner_position == "Libero":
                await interaction.followup.send(
                    "Libero is not available in your region's 5v5 format. Only **Defense Specialist** is queueable for the defensive role.",
                    ephemeral=True
                )
                return
        if self.partner:
            partner_region = await self.bot.db.get_player_region(interaction.guild.id, self.partner.id)
            if partner_region and is_5v5_region(config, partner_region) and self.partner_position == "Libero":
                await interaction.followup.send(
                    f"Libero is not available in {self.partner.mention}'s region's 5v5 format. Only **Defense Specialist** is queueable for the defensive role.",
                    ephemeral=True
                )
                return

        # Duo position restrictions: can't double up on Setter or Libero
        if self.your_position == self.partner_position and self.your_position in ("Setter", "Libero"):
            await interaction.followup.send(
                f"Duo queue cannot have both players as **{self.your_position}**. Please pick different positions.",
                ephemeral=True
            )
            return

        # Check MMR requirements
        your_elo = await self.bot.db.get_player_elo(interaction.guild.id, interaction.user.id, self.your_position)
        if your_elo < self.mmr_limit:
            await interaction.followup.send(
                f"You need at least **{self.mmr_limit}** ELO in **{self.your_position}** to join high rank queue.\n"
                f"Your current {self.your_position} ELO: **{int(your_elo)}**",
                ephemeral=True
            )
            return

        partner_elo = await self.bot.db.get_player_elo(interaction.guild.id, self.partner.id, self.partner_position)
        if partner_elo < self.mmr_limit:
            await interaction.followup.send(
                f"{self.partner.mention} needs at least **{self.mmr_limit}** ELO in **{self.partner_position}** to join high rank queue.\n"
                f"Their current {self.partner_position} ELO: **{int(partner_elo)}**",
                ephemeral=True
            )
            return

        # Check blacklist
        blacklist_role = await self.bot.get_blacklist_role(interaction.guild)
        if blacklist_role and blacklist_role in self.partner.roles:
            await interaction.followup.send(f"{self.partner.mention} is blacklisted!", ephemeral=True)
            return
        reason = await self.bot.db.is_blacklisted(interaction.guild.id, self.partner.id)
        if reason is not None:
            await interaction.followup.send(f"{self.partner.mention} is blacklisted!", ephemeral=True)
            return

        # Check partner has required role
        if not await check_required_roles_member(interaction.guild.id, self.partner, self.bot):
            await interaction.followup.send(
                f"{self.partner.mention} does not have the required role to queue!",
                ephemeral=True
            )
            return

        # Check if either player is in an active match
        if await self.bot.db.is_user_in_active_match(interaction.guild.id, interaction.user.id):
            await interaction.followup.send(
                "You cannot send invites while in an active match! Please finish your current match first.",
                ephemeral=True
            )
            return
        if await self.bot.db.is_user_in_active_match(interaction.guild.id, self.partner.id):
            await interaction.followup.send(
                f"{self.partner.mention} is currently in an active match!",
                ephemeral=True
            )
            return

        # Check if already in queue
        queue = await self.bot.db.get_queue(interaction.guild.id)
        hr_queue = await self.bot.db.get_queue(interaction.guild.id, 'highrank')
        queued_players = [q[0] for q in queue] + [q[0] for q in hr_queue]
        if interaction.user.id in queued_players:
            await interaction.followup.send("You are already in a queue! Leave first.", ephemeral=True)
            return
        if self.partner.id in queued_players:
            await interaction.followup.send(f"{self.partner.mention} is already in a queue!", ephemeral=True)
            return

        invitation_id = f"duo_hr_{interaction.guild.id}_{interaction.user.id}_{self.partner.id}_{datetime.utcnow().timestamp()}"
        invitation_data = {
            'type': 'duo',
            'queue_type': 'highrank',
            'initiator': interaction.user.id,
            'guild_id': interaction.guild.id,
            'players': {
                interaction.user.id: {'position': self.your_position, 'accepted': True},
                self.partner.id: {'position': self.partner_position, 'accepted': False}
            },
            'created_at': datetime.utcnow(),
            'expires_at': datetime.utcnow() + timedelta(minutes=5)
        }
        self.bot.pending_group_invites[invitation_id] = invitation_data

        try:
            partner_embed = discord.Embed(
                title="High Rank Duo Queue Invitation",
                description=f"{interaction.user.mention} wants to duo queue with you in **high rank**!",
                color=discord.Color.purple()
            )
            partner_embed.add_field(
                name="Queue Details",
                value=f"**{interaction.user.name}:** {self.your_position}\n**You:** {self.partner_position}",
                inline=False
            )
            partner_embed.add_field(name="Expires", value="5 minutes", inline=False)

            dm_sent = False
            try:
                dm_view = GroupInviteView(self.bot, invitation_id, 'duo')
                await self.partner.send(embed=partner_embed, view=dm_view)
                dm_sent = True
            except (discord.Forbidden, discord.HTTPException):
                pass

            channel_sent = False
            invite_ch_id = config.get("invite_channel") or config.get("queue_channel")
            if invite_ch_id:
                channel = self.bot.get_channel(invite_ch_id)
                if channel:
                    try:
                        ch_view = GroupInviteView(self.bot, invitation_id, 'duo')
                        channel_embed = partner_embed.copy()
                        channel_embed.description = f"{self.partner.mention}, high rank duo invitation from {interaction.user.mention}!"
                        await channel.send(embed=channel_embed, view=ch_view)
                        channel_sent = True
                    except (discord.Forbidden, discord.HTTPException):
                        pass

            if not dm_sent and not channel_sent:
                await interaction.followup.send(f"Failed to send invitation to {self.partner.mention}!", ephemeral=True)
                if invitation_id in self.bot.pending_group_invites:
                    del self.bot.pending_group_invites[invitation_id]
                return

            await interaction.followup.send(
                f"High rank duo invitation sent to {self.partner.mention}! Expires in 5 minutes.",
                ephemeral=True
            )

            for child in self.children:
                child.disabled = True
            try:
                await interaction.edit_original_response(view=self)
            except:
                pass

            asyncio.create_task(self._expire_duo_hr(invitation_id))
        except Exception as e:
            await interaction.followup.send(f"Failed to send invitation: {e}", ephemeral=True)
            if invitation_id in self.bot.pending_group_invites:
                del self.bot.pending_group_invites[invitation_id]

    async def _expire_duo_hr(self, invitation_id):
        await asyncio.sleep(300)
        if invitation_id in self.bot.pending_group_invites:
            del self.bot.pending_group_invites[invitation_id]


class TrioHighRankView(discord.ui.View):
    """Trio queue setup for high rank 6v6."""
    def __init__(self, bot, mmr_limit=1000):
        super().__init__(timeout=60)
        self.bot = bot
        self.mmr_limit = mmr_limit
        self.partner1 = None
        self.partner2 = None
        self.your_position = None
        self.partner1_position = None
        self.partner2_position = None

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Select your first partner", min_values=1, max_values=1, row=0)
    async def partner1_select(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        self.partner1 = select.values[0]
        if self.partner1.id == interaction.user.id:
            await interaction.response.send_message("You cannot trio queue with yourself!", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await self.check_ready(interaction)

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Select your second partner", min_values=1, max_values=1, row=1)
    async def partner2_select(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        self.partner2 = select.values[0]
        if self.partner2.id == interaction.user.id:
            await interaction.response.send_message("You cannot trio queue with yourself!", ephemeral=True)
            return
        if self.partner1 and self.partner2.id == self.partner1.id:
            await interaction.response.send_message("Both partners must be different!", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await self.check_ready(interaction)

    @discord.ui.select(placeholder="Select YOUR position", options=[
        discord.SelectOption(label="Defense Specialist", value="Defense Specialist"),
        discord.SelectOption(label="Front Spiker", value="Front Spiker"),
        discord.SelectOption(label="Setter", value="Setter"),
        discord.SelectOption(label="Libero", value="Libero")
    ], row=2)
    async def your_position_select(self, interaction, select):
        self.your_position = select.values[0]
        await interaction.response.defer(ephemeral=True)
        await self.check_ready(interaction)

    @discord.ui.select(placeholder="Select FIRST PARTNER'S position", options=[
        discord.SelectOption(label="Defense Specialist", value="Defense Specialist"),
        discord.SelectOption(label="Front Spiker", value="Front Spiker"),
        discord.SelectOption(label="Setter", value="Setter"),
        discord.SelectOption(label="Libero", value="Libero")
    ], row=3)
    async def partner1_position_select(self, interaction, select):
        self.partner1_position = select.values[0]
        await interaction.response.defer(ephemeral=True)
        await self.check_ready(interaction)

    @discord.ui.select(placeholder="Select SECOND PARTNER'S position", options=[
        discord.SelectOption(label="Defense Specialist", value="Defense Specialist"),
        discord.SelectOption(label="Front Spiker", value="Front Spiker"),
        discord.SelectOption(label="Setter", value="Setter"),
        discord.SelectOption(label="Libero", value="Libero")
    ], row=4)
    async def partner2_position_select(self, interaction, select):
        self.partner2_position = select.values[0]
        await interaction.response.defer(ephemeral=True)
        await self.check_ready(interaction)

    async def check_ready(self, interaction: discord.Interaction):
        if not all([self.partner1, self.partner2, self.your_position, self.partner1_position, self.partner2_position]):
            return

        config = await self.bot.db.get_config(interaction.guild.id)

        # Block Libero for 5v5 regions
        players_and_positions = [
            (interaction.user, self.your_position),
            (self.partner1, self.partner1_position),
            (self.partner2, self.partner2_position),
        ]
        for player, pos in players_and_positions:
            if pos == "Libero":
                player_region = await self.bot.db.get_player_region(interaction.guild.id, player.id)
                if player_region and is_5v5_region(config, player_region):
                    name = "You" if player.id == interaction.user.id else player.mention
                    await interaction.followup.send(
                        f"Libero is not available for {name} in the 5v5 format. Only **Defense Specialist** is queueable for the defensive role.",
                        ephemeral=True
                    )
                    return

        # Trio position restrictions: can't triple up on DS or FS
        trio_positions = [self.your_position, self.partner1_position, self.partner2_position]
        for restricted_pos in ("Defense Specialist", "Front Spiker"):
            if trio_positions.count(restricted_pos) >= 3:
                await interaction.followup.send(
                    f"Trio queue cannot have all three players as **{restricted_pos}**. Please pick different positions.",
                    ephemeral=True
                )
                return

        # Check MMR for all players
        for player, pos in players_and_positions:
            elo = await self.bot.db.get_player_elo(interaction.guild.id, player.id, pos)
            if elo < self.mmr_limit:
                name = "You" if player.id == interaction.user.id else player.mention
                await interaction.followup.send(
                    f"{name} need{'s' if player.id != interaction.user.id else ''} at least **{self.mmr_limit}** ELO in **{pos}** for high rank queue.\n"
                    f"Current {pos} ELO: **{int(elo)}**",
                    ephemeral=True
                )
                return

        # Check blacklist
        blacklist_role = await self.bot.get_blacklist_role(interaction.guild)
        for partner in [self.partner1, self.partner2]:
            if blacklist_role and blacklist_role in partner.roles:
                await interaction.followup.send(f"{partner.mention} is blacklisted!", ephemeral=True)
                return
            reason = await self.bot.db.is_blacklisted(interaction.guild.id, partner.id)
            if reason is not None:
                await interaction.followup.send(f"{partner.mention} is blacklisted!", ephemeral=True)
                return

        # Check partners have required roles
        for partner in [self.partner1, self.partner2]:
            if not await check_required_roles_member(interaction.guild.id, partner, self.bot):
                await interaction.followup.send(
                    f"{partner.mention} does not have the required role to queue!",
                    ephemeral=True
                )
                return

        # Check if any player is in an active match
        in_match = []
        for player in [interaction.user, self.partner1, self.partner2]:
            if await self.bot.db.is_user_in_active_match(interaction.guild.id, player.id):
                in_match.append("You" if player.id == interaction.user.id else player.mention)
        if in_match:
            await interaction.followup.send(
                f"{', '.join(in_match)} {'is' if len(in_match) == 1 else 'are'} currently in an active match!",
                ephemeral=True
            )
            return

        # Check if already in queue
        queue = await self.bot.db.get_queue(interaction.guild.id)
        hr_queue = await self.bot.db.get_queue(interaction.guild.id, 'highrank')
        queued_players = [q[0] for q in queue] + [q[0] for q in hr_queue]
        already_queued = []
        if interaction.user.id in queued_players:
            already_queued.append("You")
        if self.partner1.id in queued_players:
            already_queued.append(self.partner1.name)
        if self.partner2.id in queued_players:
            already_queued.append(self.partner2.name)
        if already_queued:
            await interaction.followup.send(f"{', '.join(already_queued)} already in a queue!", ephemeral=True)
            return

        trio_members = [interaction.user.id, self.partner1.id, self.partner2.id]
        invitation_id = f"trio_hr6_{interaction.guild.id}_{interaction.user.id}_{datetime.utcnow().timestamp()}"
        invitation_data = {
            'type': 'trio',
            'queue_type': 'highrank',
            'initiator': interaction.user.id,
            'guild_id': interaction.guild.id,
            'players': {
                interaction.user.id: {'position': self.your_position, 'accepted': True},
                self.partner1.id: {'position': self.partner1_position, 'accepted': False},
                self.partner2.id: {'position': self.partner2_position, 'accepted': False}
            },
            'trio_members': trio_members,
            'created_at': datetime.utcnow(),
            'expires_at': datetime.utcnow() + timedelta(minutes=5)
        }
        self.bot.pending_group_invites[invitation_id] = invitation_data

        try:
            for partner in [self.partner1, self.partner2]:
                partner_embed = discord.Embed(
                    title="High Rank Trio Queue Invitation",
                    description=f"{interaction.user.mention} wants to trio queue with you in **high rank**!",
                    color=discord.Color.purple()
                )
                partner_embed.add_field(
                    name="Queue Details",
                    value=(
                        f"**{interaction.user.name}:** {self.your_position}\n"
                        f"**{self.partner1.name}:** {self.partner1_position}\n"
                        f"**{self.partner2.name}:** {self.partner2_position}"
                    ),
                    inline=False
                )
                partner_embed.add_field(name="Expires", value="5 minutes", inline=False)

                try:
                    dm_view = GroupInviteView(self.bot, invitation_id, 'trio')
                    await partner.send(embed=partner_embed, view=dm_view)
                except (discord.Forbidden, discord.HTTPException):
                    pass

                invite_ch_id = config.get("invite_channel") or config.get("queue_channel")
                if invite_ch_id:
                    channel = self.bot.get_channel(invite_ch_id)
                    if channel:
                        try:
                            ch_view = GroupInviteView(self.bot, invitation_id, 'trio')
                            ch_embed = partner_embed.copy()
                            ch_embed.description = f"{partner.mention}, high rank trio invitation from {interaction.user.mention}!"
                            await channel.send(embed=ch_embed, view=ch_view)
                        except (discord.Forbidden, discord.HTTPException):
                            pass

            await interaction.followup.send(
                f"High rank trio invitations sent to {self.partner1.mention} and {self.partner2.mention}!",
                ephemeral=True
            )

            for child in self.children:
                child.disabled = True
            try:
                await interaction.edit_original_response(view=self)
            except:
                pass

            asyncio.create_task(self._expire_trio_hr6(invitation_id))
        except Exception as e:
            await interaction.followup.send(f"Failed to send invitation: {e}", ephemeral=True)
            if invitation_id in self.bot.pending_group_invites:
                del self.bot.pending_group_invites[invitation_id]

    async def _expire_trio_hr6(self, invitation_id):
        await asyncio.sleep(300)
        if invitation_id in self.bot.pending_group_invites:
            del self.bot.pending_group_invites[invitation_id]
