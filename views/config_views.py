# views/config_views.py
"""
Unified configuration UI for the volleyball bot.
All server settings accessible through /config with a tabbed navigation interface.
"""

import discord
from datetime import datetime
from typing import Optional

from config import VALID_POSITIONS, VALID_REGIONS, POSITION_EMOJIS, is_5v5_region
from utils import format_elo_change


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  HELPER FUNCTIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def check_senior_staff(interaction, bot):
    """Check if the user has senior staff role or administrator permission.
    Returns True if authorized, False otherwise (sends error message)."""
    if interaction.user.guild_permissions.administrator:
        return True
    config = await bot.db.get_config(interaction.guild_id)
    senior_roles = config.get("staff_senior_roles", [])
    if senior_roles:
        user_role_ids = [role.id for role in interaction.user.roles]
        if any(role_id in senior_roles for role_id in user_role_ids):
            return True
    await interaction.response.send_message(
        "This section requires **Senior Staff** or **Administrator** permissions.",
        ephemeral=True
    )
    return False


async def check_admin_permission(interaction, bot):
    """Check if the user has the Discord administrator permission.
    Returns True if authorized, False otherwise (sends error message)."""
    if interaction.user.guild_permissions.administrator:
        return True
    await interaction.response.send_message(
        "This section requires **Administrator** permissions.",
        ephemeral=True
    )
    return False


async def build_hub_embed(bot, guild_id, guild):
    """Build the main config hub embed with a quick status overview."""
    config = await bot.db.get_config(guild_id)

    embed = discord.Embed(
        title="⚙️ Server Configuration",
        description="Select a category below to manage your server settings.",
        color=discord.Color.blurple()
    )

    queue_ch = f"<#{config['queue_channel']}>" if config.get("queue_channel") else "❌ Not set"
    results_ch = f"<#{config['results_channel']}>" if config.get("results_channel") else "❌ Not set"
    lb_ch = f"<#{config['leaderboard_channel']}>" if config.get("leaderboard_channel") else "❌ Not set"

    senior_roles = config.get("staff_senior_roles", [])
    normal_roles = config.get("staff_normal_roles", [])
    staff_count = len(senior_roles) + len(normal_roles)

    s_6v6 = await bot.db.get_current_season(guild_id, '6v6')
    s_2v2 = await bot.db.get_current_season(guild_id, '2v2')
    s_3v3 = await bot.db.get_current_season(guild_id, '3v3')
    season_parts = []
    if s_6v6:
        season_parts.append(f"Queues: **{s_6v6[1]}**")
    if s_2v2:
        season_parts.append(f"2v2: **{s_2v2[1]}**")
    if s_3v3:
        season_parts.append(f"3v3: **{s_3v3[1]}**")
    season_text = "\n".join(season_parts) if season_parts else "No active seasons"

    mappings = await bot.db.get_all_elo_role_mappings(guild_id)
    elo_role_count = len(mappings)

    embed.add_field(
        name="📋 General Settings",
        value=f"Queue: {queue_ch}\nResults: {results_ch}\nLeaderboard: {lb_ch}",
        inline=True
    )
    embed.add_field(
        name="Staff Roles",
        value=f"**{staff_count}** role{'s' if staff_count != 1 else ''} configured",
        inline=True
    )
    embed.add_field(
        name="📅 Seasons",
        value=season_text,
        inline=True
    )
    embed.add_field(
        name="🎖️ ELO Roles",
        value=f"**{elo_role_count}** reward{'s' if elo_role_count != 1 else ''} configured",
        inline=True
    )
    region_roles = config.get("region_roles", {})
    region_count = sum(1 for v in region_roles.values() if v)
    embed.add_field(
        name="Region Roles",
        value=f"**{region_count}/{len(VALID_REGIONS)}** regions configured",
        inline=True
    )

    duo_enabled = config.get("duo_queue_enabled", True)
    trio_enabled = config.get("trio_queue_enabled", True)
    embed.add_field(
        name="🎮 Queue Settings",
        value=(
            f"**Duo Queue:** {'Enabled' if duo_enabled else 'Disabled'}\n"
            f"**Trio Queue:** {'Enabled' if trio_enabled else 'Disabled'}"
        ),
        inline=True
    )

    hr_parts = []
    if config.get("high_rank_enabled", False):
        hr_parts.append("Queues")
    if config.get("high_rank_2v2_enabled", False):
        hr_parts.append("2v2")
    if config.get("high_rank_3v3_enabled", False):
        hr_parts.append("3v3")
    hr_text = ", ".join(hr_parts) if hr_parts else "None enabled"
    embed.add_field(
        name="High Rank",
        value=hr_text,
        inline=True
    )

    embed.add_field(
        name="🔧 Admin Tools",
        value="Players, ELO, blacklist, matches",
        inline=True
    )

    embed.set_footer(text="Use the dropdown below to navigate between sections")
    return embed


async def navigate_to_hub(interaction, bot, guild_id):
    """Navigate back to the main config hub."""
    embed = await build_hub_embed(bot, guild_id, interaction.guild)
    view = ConfigHubView(bot, guild_id)
    await interaction.response.edit_message(embed=embed, view=view)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MAIN CONFIG HUB
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ConfigHubView(discord.ui.View):
    """Main navigation hub for all configuration categories."""

    def __init__(self, bot, guild_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id

    @discord.ui.select(
        cls=discord.ui.Select,
        placeholder="📂 Select a category to configure...",
        options=[
            discord.SelectOption(
                label="General Settings",
                description="Channels, ELO settings, match cleanup",
                emoji="📋",
                value="general"
            ),
            discord.SelectOption(
                label="Staff Roles",
                description="Configure staff permissions (Senior / Normal)",
                value="staffroles"
            ),
            discord.SelectOption(
                label="Season Management",
                description="Start, end, and manage seasons",
                emoji="📅",
                value="seasons"
            ),
            discord.SelectOption(
                label="ELO Role Rewards",
                description="Automatic role rewards based on ELO",
                emoji="🎖️",
                value="eloroles"
            ),
            discord.SelectOption(
                label="Region Roles",
                description="Configure region role selection channel",
                value="regionroles"
            ),
            discord.SelectOption(
                label="Queue Settings",
                description="Duo/trio toggle, party requirements",
                emoji="🎮",
                value="queuesettings"
            ),
            discord.SelectOption(
                label="High Rank Settings",
                description="Configure high rank queue (6v6 only)",
                value="highrank"
            ),
            discord.SelectOption(
                label="Admin Tools",
                description="Players, blacklist, matches, ELO, queue",
                value="admintools"
            ),
        ],
        row=0
    )
    async def category_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        category = select.values[0]

        # Staff roles requires administrator permission
        if category == "staffroles":
            if not await check_admin_permission(interaction, self.bot):
                return

        # These sections require senior staff or administrator
        senior_staff_sections = ("general", "seasons", "eloroles", "regionroles", "queuesettings", "highrank")
        if category in senior_staff_sections:
            if not await check_senior_staff(interaction, self.bot):
                return

        if category == "general":
            await navigate_to_general(interaction, self.bot, self.guild_id)
        elif category == "staffroles":
            await navigate_to_staffroles(interaction, self.bot, self.guild_id)
        elif category == "seasons":
            await navigate_to_seasons(interaction, self.bot, self.guild_id)
        elif category == "eloroles":
            await navigate_to_eloroles(interaction, self.bot, self.guild_id)
        elif category == "regionroles":
            await navigate_to_regionroles(interaction, self.bot, self.guild_id)
        elif category == "queuesettings":
            await navigate_to_queuesettings(interaction, self.bot, self.guild_id)
        elif category == "highrank":
            await navigate_to_highrank(interaction, self.bot, self.guild_id)
        elif category == "admintools":
            await navigate_to_admintools(interaction, self.bot, self.guild_id)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GENERAL SETTINGS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def build_general_embed(config, guild):
    """Build embed showing current general settings."""
    embed = discord.Embed(
        title="📋 General Settings",
        description="Configure channels and core bot settings.\nUse the dropdowns to set channels and buttons for other settings.",
        color=discord.Color.blue()
    )

    queue_ch = f"<#{config['queue_channel']}>" if config.get("queue_channel") else "Not set"
    results_ch = f"<#{config['results_channel']}>" if config.get("results_channel") else "Not set"
    lb_ch = f"<#{config['leaderboard_channel']}>" if config.get("leaderboard_channel") else "Not set"

    match_cat = "Not set"
    if config.get("match_category"):
        category = guild.get_channel(config["match_category"])
        if category and isinstance(category, discord.CategoryChannel):
            match_cat = category.name
        else:
            match_cat = f"Invalid (ID: {config['match_category']})"

    cleanup_seconds = config.get("match_channel_timeout", 3600)
    if cleanup_seconds >= 3600:
        cleanup_text = f"{cleanup_seconds / 3600:.1f} hours"
    else:
        cleanup_text = f"{cleanup_seconds / 60:.0f} minutes"

    embed.add_field(
        name="📡 Channels",
        value=(
            f"**Queue:** {queue_ch}\n"
            f"**Results:** {results_ch}\n"
            f"**Leaderboard:** {lb_ch}\n"
            f"**Match Category:** {match_cat}"
        ),
        inline=True
    )
    afk_seconds = config.get("afk_timer", 1800)
    if afk_seconds == 0:
        afk_text = "Disabled"
    elif afk_seconds >= 3600:
        afk_text = f"{afk_seconds / 3600:.1f} hours"
    else:
        afk_text = f"{afk_seconds / 60:.0f} minutes"

    log_ch = f"<#{config['log_channel']}>" if config.get("log_channel") else "Not set"
    log_readyup_ch = f"<#{config['log_channel_readyup']}>" if config.get("log_channel_readyup") else "Not set"
    log_admin_ch = f"<#{config['log_channel_admin']}>" if config.get("log_channel_admin") else "Not set"

    embed.add_field(
        name="🎯 ELO & Cleanup",
        value=(
            f"**Starting ELO:** {config.get('starting_elo', 650)}\n"
            f"**K-Factor:** {config.get('k_factor', 32)}\n"
            f"**Cleanup:** {cleanup_text}"
        ),
        inline=True
    )
    invite_ch = f"<#{config['invite_channel']}>" if config.get("invite_channel") else "Not set"

    embed.add_field(
        name="⏱️ AFK & Logging",
        value=(
            f"**AFK Timer:** {afk_text}\n"
            f"**General Log:** {log_ch}\n"
            f"**Ready-Up Log:** {log_readyup_ch}\n"
            f"**Admin Log:** {log_admin_ch}"
        ),
        inline=True
    )
    embed.add_field(
        name="🔗 Invite",
        value=f"**Invite Channel:** {invite_ch}",
        inline=True
    )
    embed.set_footer(text="Settings update in real-time as you make changes")
    return embed


async def navigate_to_general(interaction, bot, guild_id):
    config = await bot.db.get_config(guild_id)
    embed = build_general_embed(config, interaction.guild)
    view = GeneralSettingsView(bot, guild_id)
    await interaction.response.edit_message(embed=embed, view=view)


class GeneralSettingsView(discord.ui.View):
    """Channel selection and core setting buttons."""

    def __init__(self, bot, guild_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="📢 Select Queue Channel",
        channel_types=[discord.ChannelType.text],
        min_values=1, max_values=1, row=0
    )
    async def queue_channel_select(self, interaction: discord.Interaction, select):
        channel = select.values[0]
        config = await self.bot.db.get_config(self.guild_id)

        # Delete old queue message in previous channel
        old_channel_id = config.get("queue_channel")
        old_message_id = self.bot.queue_message_ids.get(self.guild_id)
        if old_channel_id and old_message_id:
            try:
                old_ch = self.bot.get_channel(old_channel_id)
                if old_ch:
                    old_msg = await old_ch.fetch_message(old_message_id)
                    await old_msg.delete()
            except Exception:
                pass
        self.bot.queue_message_ids.pop(self.guild_id, None)

        config["queue_channel"] = channel.id
        await self.bot.db.update_config(self.guild_id, config)
        config = await self.bot.db.get_config(self.guild_id)
        embed = build_general_embed(config, interaction.guild)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="📊 Select Results Channel",
        channel_types=[discord.ChannelType.text],
        min_values=1, max_values=1, row=1
    )
    async def results_channel_select(self, interaction: discord.Interaction, select):
        channel = select.values[0]
        config = await self.bot.db.get_config(self.guild_id)
        config["results_channel"] = channel.id
        await self.bot.db.update_config(self.guild_id, config)
        config = await self.bot.db.get_config(self.guild_id)
        embed = build_general_embed(config, interaction.guild)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="🏆 Select Leaderboard Channel",
        channel_types=[discord.ChannelType.text],
        min_values=1, max_values=1, row=2
    )
    async def leaderboard_channel_select(self, interaction: discord.Interaction, select):
        channel = select.values[0]
        config = await self.bot.db.get_config(self.guild_id)
        old_channel = config.get("leaderboard_channel")
        old_message_id = config.get("leaderboard_message_id")

        if old_channel and old_message_id:
            try:
                old_ch = self.bot.get_channel(old_channel)
                if old_ch:
                    old_msg = await old_ch.fetch_message(old_message_id)
                    await old_msg.delete()
            except Exception:
                pass

        config["leaderboard_channel"] = channel.id
        config["leaderboard_message_id"] = None
        await self.bot.db.update_config(self.guild_id, config)
        await self.bot.post_or_update_leaderboard(self.guild_id)

        config = await self.bot.db.get_config(self.guild_id)
        embed = build_general_embed(config, interaction.guild)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Match Category", emoji="📁", style=discord.ButtonStyle.primary, row=3)
    async def match_category_btn(self, interaction: discord.Interaction, button):
        modal = MatchCategoryModal(self.bot, self.guild_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="ELO Settings", emoji="🎯", style=discord.ButtonStyle.primary, row=3)
    async def elo_settings_btn(self, interaction: discord.Interaction, button):
        config = await self.bot.db.get_config(self.guild_id)
        modal = EloSettingsModal(self.bot, self.guild_id)
        modal.starting_elo.default = str(config.get("starting_elo", 1000))
        modal.k_factor.default = str(config.get("k_factor", 32))
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Cleanup Time", emoji="🧹", style=discord.ButtonStyle.primary, row=3)
    async def cleanup_btn(self, interaction: discord.Interaction, button):
        config = await self.bot.db.get_config(self.guild_id)
        current_hours = config.get("match_channel_timeout", 3600) / 3600
        modal = MatchCleanupModal(self.bot, self.guild_id, current_hours)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="AFK Timer", emoji="⏱️", style=discord.ButtonStyle.primary, row=3)
    async def afk_timer_btn(self, interaction: discord.Interaction, button):
        modal = AfkTimerModal(self.bot, self.guild_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="2v2/3v3 Channels", style=discord.ButtonStyle.primary, row=4)
    async def queue_channels_btn(self, interaction: discord.Interaction, button):
        """Open sub-view for 2v2 and 3v3 queue channel configuration"""
        config = await self.bot.db.get_config(self.guild_id)
        ch_2v2 = f"<#{config['queue_2v2_channel']}>" if config.get("queue_2v2_channel") else "Not set"
        ch_3v3 = f"<#{config['queue_3v3_channel']}>" if config.get("queue_3v3_channel") else "Not set"
        embed = discord.Embed(
            title="2v2 / 3v3 Queue Channels",
            description=f"**2v2 Queue:** {ch_2v2}\n**3v3 Queue:** {ch_3v3}",
            color=discord.Color.blue()
        )
        view = QueueChannelsView(self.bot, self.guild_id)
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Invite Channel", emoji="🔗", style=discord.ButtonStyle.primary, row=4)
    async def invite_channel_btn(self, interaction: discord.Interaction, button):
        """Open sub-view for party invite channel configuration"""
        config = await self.bot.db.get_config(self.guild_id)
        invite_ch = f"<#{config['invite_channel']}>" if config.get("invite_channel") else "Not set"
        embed = discord.Embed(
            title="🔗 Party Invite Channel",
            description=(
                f"**Current Invite Channel:** {invite_ch}\n\n"
                "Set a channel or thread where duo/trio party invitations are posted.\n"
                "When players send duo/trio queue invites, they'll appear here.\n"
                "Supports both regular channels and threads."
            ),
            color=discord.Color.blue()
        )
        view = InviteChannelView(self.bot, self.guild_id)
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Log Channels", emoji="📝", style=discord.ButtonStyle.primary, row=4)
    async def log_channel_btn(self, interaction: discord.Interaction, button):
        """Open sub-view for log channel configuration"""
        config = await self.bot.db.get_config(self.guild_id)
        log_ch = f"<#{config['log_channel']}>" if config.get("log_channel") else "Not set"
        log_readyup = f"<#{config['log_channel_readyup']}>" if config.get("log_channel_readyup") else "Not set"
        log_admin = f"<#{config['log_channel_admin']}>" if config.get("log_channel_admin") else "Not set"
        embed = discord.Embed(
            title="📝 Log Channels",
            description=(
                f"**General Log:** {log_ch}\n"
                f"Logs all command usage, button clicks, and interactions.\n\n"
                f"**Ready-Up Log:** {log_readyup}\n"
                f"Logs who didn't ready up when matches time out.\n\n"
                f"**Admin Log:** {log_admin}\n"
                f"Logs admin actions (ELO edits, blacklist, config changes)."
            ),
            color=discord.Color.blue()
        )
        view = LogChannelView(self.bot, self.guild_id)
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=4)
    async def back_btn(self, interaction: discord.Interaction, button):
        await navigate_to_hub(interaction, self.bot, self.guild_id)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class QueueChannelsView(discord.ui.View):
    """Channel selection for 2v2 and 3v3 queues."""

    def __init__(self, bot, guild_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="Select 2v2 Queue Channel",
        channel_types=[discord.ChannelType.text],
        min_values=0, max_values=1, row=0
    )
    async def queue_2v2_select(self, interaction: discord.Interaction, select):
        config = await self.bot.db.get_config(self.guild_id)

        # Delete old queue message in previous channel
        old_channel_id = config.get("queue_2v2_channel")
        old_message_id = self.bot.queue_2v2_message_ids.get(self.guild_id)
        if old_channel_id and old_message_id:
            try:
                old_ch = self.bot.get_channel(old_channel_id)
                if old_ch:
                    old_msg = await old_ch.fetch_message(old_message_id)
                    await old_msg.delete()
            except Exception:
                pass
        self.bot.queue_2v2_message_ids.pop(self.guild_id, None)

        config["queue_2v2_channel"] = select.values[0].id if select.values else None
        await self.bot.db.update_config(self.guild_id, config)
        ch = f"<#{config['queue_2v2_channel']}>" if config.get("queue_2v2_channel") else "Not set"
        await interaction.response.send_message(f"2v2 queue channel set to {ch}", ephemeral=True)

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="Select 3v3 Queue Channel",
        channel_types=[discord.ChannelType.text],
        min_values=0, max_values=1, row=1
    )
    async def queue_3v3_select(self, interaction: discord.Interaction, select):
        config = await self.bot.db.get_config(self.guild_id)

        # Delete old queue message in previous channel
        old_channel_id = config.get("queue_3v3_channel")
        old_message_id = self.bot.queue_3v3_message_ids.get(self.guild_id)
        if old_channel_id and old_message_id:
            try:
                old_ch = self.bot.get_channel(old_channel_id)
                if old_ch:
                    old_msg = await old_ch.fetch_message(old_message_id)
                    await old_msg.delete()
            except Exception:
                pass
        self.bot.queue_3v3_message_ids.pop(self.guild_id, None)

        config["queue_3v3_channel"] = select.values[0].id if select.values else None
        await self.bot.db.update_config(self.guild_id, config)
        ch = f"<#{config['queue_3v3_channel']}>" if config.get("queue_3v3_channel") else "Not set"
        await interaction.response.send_message(f"3v3 queue channel set to {ch}", ephemeral=True)

    @discord.ui.button(label="Back to General", style=discord.ButtonStyle.secondary, row=2)
    async def back_btn(self, interaction: discord.Interaction, button):
        config = await self.bot.db.get_config(self.guild_id)
        embed = build_general_embed(config, interaction.guild)
        view = GeneralSettingsView(self.bot, self.guild_id)
        await interaction.response.edit_message(embed=embed, view=view)


class InviteChannelView(discord.ui.View):
    """Channel/thread selection for party invitations."""

    def __init__(self, bot, guild_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="Select invite channel or thread",
        channel_types=[
            discord.ChannelType.text,
            discord.ChannelType.public_thread,
            discord.ChannelType.private_thread,
        ],
        min_values=0, max_values=1, row=0
    )
    async def invite_channel_select(self, interaction: discord.Interaction, select):
        config = await self.bot.db.get_config(self.guild_id)
        config["invite_channel"] = select.values[0].id if select.values else None
        await self.bot.db.update_config(self.guild_id, config)
        ch = f"<#{config['invite_channel']}>" if config.get("invite_channel") else "Not set"
        await interaction.response.send_message(f"Party invite channel set to {ch}", ephemeral=True)

    @discord.ui.button(label="Clear Invite Channel", style=discord.ButtonStyle.danger, row=1)
    async def clear_btn(self, interaction: discord.Interaction, button):
        config = await self.bot.db.get_config(self.guild_id)
        config["invite_channel"] = None
        await self.bot.db.update_config(self.guild_id, config)
        await interaction.response.send_message("Invite channel cleared. Invites will use queue channel as fallback.", ephemeral=True)

    @discord.ui.button(label="Back to General", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, interaction: discord.Interaction, button):
        config = await self.bot.db.get_config(self.guild_id)
        embed = build_general_embed(config, interaction.guild)
        view = GeneralSettingsView(self.bot, self.guild_id)
        await interaction.response.edit_message(embed=embed, view=view)


class AfkTimerModal(discord.ui.Modal, title="Set AFK Queue Timer"):
    def __init__(self, bot, guild_id):
        super().__init__(custom_id="modal_afk_timer")
        self.bot = bot
        self.guild_id = guild_id

    timer_minutes = discord.ui.TextInput(
        label="AFK Timer (minutes)",
        placeholder="e.g., 30 (default), 15, 60... 0 to disable",
        max_length=5
    )

    async def on_submit(self, interaction):
        try:
            minutes = float(self.timer_minutes.value.strip())
            if minutes < 0 or minutes > 1440:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("Enter a number between 0 and 1440!", ephemeral=True)
            return
        config = await self.bot.db.get_config(self.guild_id)
        config["afk_timer"] = int(minutes * 60) if minutes > 0 else 0
        await self.bot.db.update_config(self.guild_id, config)
        if minutes > 0:
            await interaction.response.send_message(f"AFK timer set to **{minutes:.0f} minutes**.", ephemeral=True)
        else:
            await interaction.response.send_message("AFK timer **disabled**.", ephemeral=True)


class LogChannelView(discord.ui.View):
    """Channel selection for all log channels (general, ready-up, admin)."""

    def __init__(self, bot, guild_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="General Log Channel (commands, buttons)",
        channel_types=[discord.ChannelType.text],
        min_values=0, max_values=1, row=0
    )
    async def log_channel_select(self, interaction: discord.Interaction, select):
        config = await self.bot.db.get_config(self.guild_id)
        config["log_channel"] = select.values[0].id if select.values else None
        await self.bot.db.update_config(self.guild_id, config)
        ch = f"<#{config['log_channel']}>" if config.get("log_channel") else "Not set"
        await interaction.response.send_message(f"General log channel set to {ch}", ephemeral=True)

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="Ready-Up Log Channel (who didn't ready)",
        channel_types=[discord.ChannelType.text],
        min_values=0, max_values=1, row=1
    )
    async def log_readyup_select(self, interaction: discord.Interaction, select):
        config = await self.bot.db.get_config(self.guild_id)
        config["log_channel_readyup"] = select.values[0].id if select.values else None
        await self.bot.db.update_config(self.guild_id, config)
        ch = f"<#{config['log_channel_readyup']}>" if config.get("log_channel_readyup") else "Not set"
        await interaction.response.send_message(f"Ready-up log channel set to {ch}", ephemeral=True)

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="Admin Log Channel (admin actions)",
        channel_types=[discord.ChannelType.text],
        min_values=0, max_values=1, row=2
    )
    async def log_admin_select(self, interaction: discord.Interaction, select):
        config = await self.bot.db.get_config(self.guild_id)
        config["log_channel_admin"] = select.values[0].id if select.values else None
        await self.bot.db.update_config(self.guild_id, config)
        ch = f"<#{config['log_channel_admin']}>" if config.get("log_channel_admin") else "Not set"
        await interaction.response.send_message(f"Admin log channel set to {ch}", ephemeral=True)

    @discord.ui.button(label="Back to General", style=discord.ButtonStyle.secondary, row=3)
    async def back_btn(self, interaction: discord.Interaction, button):
        config = await self.bot.db.get_config(self.guild_id)
        embed = build_general_embed(config, interaction.guild)
        view = GeneralSettingsView(self.bot, self.guild_id)
        await interaction.response.edit_message(embed=embed, view=view)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STAFF ROLES (Senior / Normal)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def navigate_to_staffroles(interaction, bot, guild_id):
    config = await bot.db.get_config(guild_id)
    senior_roles = config.get("staff_senior_roles", [])
    normal_roles = config.get("staff_normal_roles", [])

    embed = discord.Embed(
        title="Staff Roles",
        description=(
            "Configure staff permissions.\n"
            "**Senior Staff** - Full access (blacklist, edit ELO, config, etc.)\n"
            "**Normal Staff** - Basic access (match management, queue removal)"
        ),
        color=discord.Color.blue()
    )

    if senior_roles:
        mentions = [f"<@&{rid}>" for rid in senior_roles if interaction.guild.get_role(rid)]
        embed.add_field(name="Senior Staff", value="\n".join(mentions) if mentions else "None (roles may have been deleted)", inline=True)
    else:
        embed.add_field(name="Senior Staff", value="None configured", inline=True)

    if normal_roles:
        mentions = [f"<@&{rid}>" for rid in normal_roles if interaction.guild.get_role(rid)]
        embed.add_field(name="Normal Staff", value="\n".join(mentions) if mentions else "None (roles may have been deleted)", inline=True)
    else:
        embed.add_field(name="Normal Staff", value="None configured", inline=True)

    embed.add_field(
        name="Tips",
        value=(
            "Administrators always have access regardless\n"
            "Select up to 5 roles per tier below"
        ),
        inline=False
    )
    embed.set_footer(text="Use the dropdowns below to configure staff roles")

    view = StaffRolesSettingsView(bot, guild_id, senior_roles, normal_roles)
    await view.setup(interaction.guild)
    await interaction.response.edit_message(embed=embed, view=view)


class StaffRolesSettingsView(discord.ui.View):
    """Role selects for configuring senior and normal staff roles."""

    def __init__(self, bot, guild_id, senior_roles, normal_roles):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.senior_roles = senior_roles
        self.normal_roles = normal_roles

    async def setup(self, guild):
        roles = [
            r for r in guild.roles
            if not r.is_bot_managed()
            and r != guild.default_role
            and not r.is_premium_subscriber()
        ]
        roles.sort(key=lambda r: r.position, reverse=True)

        # Senior staff select
        senior_options = []
        for role in roles[:25]:
            senior_options.append(discord.SelectOption(
                label=role.name,
                value=str(role.id),
                description=f"{len(role.members)} members",
                default=(role.id in self.senior_roles)
            ))
        if not senior_options:
            senior_options = [discord.SelectOption(label="No roles available", value="none")]

        max_sel = min(5, len(senior_options)) if senior_options[0].value != "none" else 1
        senior_select = discord.ui.Select(
            placeholder="Select Senior Staff roles...",
            min_values=0, max_values=max_sel,
            options=senior_options, row=0
        )
        senior_select.callback = self.on_senior_select
        self.add_item(senior_select)
        self._senior_select = senior_select

        # Normal staff select
        normal_options = []
        for role in roles[:25]:
            normal_options.append(discord.SelectOption(
                label=role.name,
                value=str(role.id),
                description=f"{len(role.members)} members",
                default=(role.id in self.normal_roles)
            ))
        if not normal_options:
            normal_options = [discord.SelectOption(label="No roles available", value="none")]

        max_sel_n = min(5, len(normal_options)) if normal_options[0].value != "none" else 1
        normal_select = discord.ui.Select(
            placeholder="Select Normal Staff roles...",
            min_values=0, max_values=max_sel_n,
            options=normal_options, row=1
        )
        normal_select.callback = self.on_normal_select
        self.add_item(normal_select)
        self._normal_select = normal_select

    async def on_senior_select(self, interaction: discord.Interaction):
        if self._senior_select.values and self._senior_select.values[0] == "none":
            await interaction.response.send_message("No roles available.", ephemeral=True)
            return
        selected = [int(v) for v in self._senior_select.values] if self._senior_select.values else []
        config = await self.bot.db.get_config(self.guild_id)
        config["staff_senior_roles"] = selected
        await self.bot.db.update_config(self.guild_id, config)
        if selected:
            mentions = [f"<@&{rid}>" for rid in selected]
            await interaction.response.send_message(f"Senior Staff updated: {', '.join(mentions)}", ephemeral=True)
        else:
            await interaction.response.send_message("Senior Staff roles cleared.", ephemeral=True)

    async def on_normal_select(self, interaction: discord.Interaction):
        if self._normal_select.values and self._normal_select.values[0] == "none":
            await interaction.response.send_message("No roles available.", ephemeral=True)
            return
        selected = [int(v) for v in self._normal_select.values] if self._normal_select.values else []
        config = await self.bot.db.get_config(self.guild_id)
        config["staff_normal_roles"] = selected
        await self.bot.db.update_config(self.guild_id, config)
        if selected:
            mentions = [f"<@&{rid}>" for rid in selected]
            await interaction.response.send_message(f"Normal Staff updated: {', '.join(mentions)}", ephemeral=True)
        else:
            await interaction.response.send_message("Normal Staff roles cleared.", ephemeral=True)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=2)
    async def back_btn(self, interaction: discord.Interaction, button):
        await navigate_to_hub(interaction, self.bot, self.guild_id)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  BLACKLIST MANAGEMENT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def build_blacklist_embed(bot, guild_id):
    blacklist = await bot.db.get_blacklist(guild_id)
    config = await bot.db.get_config(guild_id)

    embed = discord.Embed(
        title="🚫 Blacklist Management",
        description=f"**{len(blacklist)}** user{'s' if len(blacklist) != 1 else ''} currently blacklisted",
        color=discord.Color.red() if blacklist else discord.Color.blue()
    )

    # Show configured blacklist role
    role_id = config.get("blacklist_role_id")
    role_text = "Auto-created 'Blacklisted'" if not role_id else f"<@&{role_id}>"
    embed.add_field(name="Blacklist Role", value=role_text, inline=False)

    if blacklist:
        entries = []
        for entry in blacklist[:5]:
            user_id = entry[0]
            reason = entry[2]
            expires_at = entry[4] if len(entry) > 4 else None
            user = bot.get_user(user_id)
            user_text = user.mention if user else f"User `{user_id}`"
            reason_text = reason or "No reason"
            expires_text = ""
            if expires_at:
                try:
                    exp_ts = int(datetime.fromisoformat(expires_at).timestamp())
                    expires_text = f" (expires <t:{exp_ts}:R>)"
                except:
                    pass
            else:
                expires_text = " (permanent)"
            entries.append(f"• {user_text} — {reason_text}{expires_text}")
        text = "\n".join(entries)
        if len(blacklist) > 5:
            text += f"\n*...and {len(blacklist) - 5} more*"
        embed.add_field(name="Recent Entries", value=text, inline=False)
    else:
        embed.add_field(name="✨ All Clear", value="No users are blacklisted", inline=False)

    embed.add_field(
        name="📖 How to use",
        value=(
            "1️⃣ Select a user from the dropdown\n"
            "2️⃣ Click **Add** or **Remove** to manage\n"
            "3️⃣ Click **Set Role** to choose a custom blacklist role\n"
            "4️⃣ Click **View All** for the full list"
        ),
        inline=False
    )
    embed.set_footer(text="Select a user, then use the action buttons")
    return embed


async def navigate_to_blacklist(interaction, bot, guild_id):
    embed = await build_blacklist_embed(bot, guild_id)
    view = BlacklistManageView(bot, guild_id)
    await interaction.response.edit_message(embed=embed, view=view)


class BlacklistManageView(discord.ui.View):
    """User select + action buttons for blacklist management."""

    def __init__(self, bot, guild_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.selected_user = None

    @discord.ui.select(
        cls=discord.ui.UserSelect,
        placeholder="👤 Select a user...",
        min_values=1, max_values=1, row=0
    )
    async def user_select(self, interaction: discord.Interaction, select):
        self.selected_user = select.values[0]
        reason = await self.bot.db.is_blacklisted(self.guild_id, self.selected_user.id)
        if reason is not None:
            status = f"🚫 **{self.selected_user.display_name}** is blacklisted — Reason: {reason or 'None'}"
        else:
            status = f"✅ **{self.selected_user.display_name}** is not blacklisted"
        await interaction.response.send_message(status, ephemeral=True)

    @discord.ui.button(label="Add to Blacklist", emoji="🚫", style=discord.ButtonStyle.danger, row=1)
    async def add_blacklist_btn(self, interaction: discord.Interaction, button):
        if not self.selected_user:
            await interaction.response.send_message("⚠️ Select a user first!", ephemeral=True)
            return

        existing = await self.bot.db.is_blacklisted(self.guild_id, self.selected_user.id)
        if existing is not None:
            await interaction.response.send_message(
                f"⚠️ {self.selected_user.mention} is already blacklisted!",
                ephemeral=True
            )
            return

        modal = BlacklistReasonModal(self.bot, self.guild_id, self.selected_user)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Remove", emoji="✅", style=discord.ButtonStyle.success, row=1)
    async def remove_blacklist_btn(self, interaction: discord.Interaction, button):
        if not self.selected_user:
            await interaction.response.send_message("⚠️ Select a user first!", ephemeral=True)
            return

        reason = await self.bot.db.is_blacklisted(self.guild_id, self.selected_user.id)
        if reason is None:
            member = interaction.guild.get_member(self.selected_user.id)
            if member:
                blacklist_role = await self.bot.get_blacklist_role(interaction.guild)
                if blacklist_role and blacklist_role in member.roles:
                    try:
                        await member.remove_roles(blacklist_role, reason=f"Unblacklisted by {interaction.user}")
                    except Exception:
                        pass
            await interaction.response.send_message(
                f"⚠️ {self.selected_user.mention} is not blacklisted!",
                ephemeral=True
            )
            return

        await self.bot.db.remove_from_blacklist(self.guild_id, self.selected_user.id)

        member = interaction.guild.get_member(self.selected_user.id)
        role_status = ""
        if member:
            blacklist_role = await self.bot.get_blacklist_role(interaction.guild)
            if blacklist_role and blacklist_role in member.roles:
                try:
                    await member.remove_roles(blacklist_role, reason=f"Unblacklisted by {interaction.user}")
                    role_status = "\n🏷️ Blacklisted role removed"
                except discord.Forbidden:
                    role_status = "\n⚠️ Could not remove role (missing permissions)"

        await interaction.response.send_message(
            f"✅ **{self.selected_user.display_name}** has been removed from the blacklist!{role_status}",
            ephemeral=True
        )
        await self.bot.log_action(
            self.guild_id,
            "Admin: Blacklist Remove",
            f"{interaction.user.mention} removed {self.selected_user.mention} from the blacklist",
            user=interaction.user, log_type="admin"
        )

    @discord.ui.button(label="View All", emoji="📋", style=discord.ButtonStyle.primary, row=1)
    async def view_all_btn(self, interaction: discord.Interaction, button):
        blacklist = await self.bot.db.get_blacklist(self.guild_id)

        embed = discord.Embed(
            title="🚫 Full Blacklist",
            description=f"Total: **{len(blacklist)}** user{'s' if len(blacklist) != 1 else ''}",
            color=discord.Color.red()
        )

        if blacklist:
            text = ""
            for entry in blacklist[:15]:
                user_id, by_id, reason, timestamp = entry[0], entry[1], entry[2], entry[3]
                expires_at = entry[4] if len(entry) > 4 else None
                user = self.bot.get_user(user_id)
                by_user = self.bot.get_user(by_id)
                user_text = user.mention if user else f"User `{user_id}`"
                by_text = by_user.name if by_user else f"User `{by_id}`"
                ts = ""
                try:
                    ts = f" <t:{int(datetime.fromisoformat(timestamp).timestamp())}:R>"
                except Exception:
                    pass
                expires_text = ""
                if expires_at:
                    try:
                        exp_ts = int(datetime.fromisoformat(expires_at).timestamp())
                        expires_text = f" | Expires <t:{exp_ts}:R>"
                    except:
                        pass
                else:
                    expires_text = " | Permanent"
                text += f"• {user_text}\n  └ By: {by_text} | Reason: {reason or 'None'}{ts}{expires_text}\n"

            embed.add_field(name="Blacklisted Users", value=text[:1024], inline=False)
            if len(blacklist) > 15:
                embed.set_footer(text=f"Showing 15 of {len(blacklist)}")
        else:
            embed.add_field(name="Empty", value="No users are blacklisted", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.select(
        cls=discord.ui.RoleSelect,
        placeholder="🏷️ Set blacklist role...",
        min_values=0, max_values=1, row=2
    )
    async def blacklist_role_select(self, interaction: discord.Interaction, select):
        config = await self.bot.db.get_config(self.guild_id)
        if select.values:
            role = select.values[0]
            config["blacklist_role_id"] = role.id
            await self.bot.db.update_config(self.guild_id, config)
            await interaction.response.send_message(
                f"Blacklist role set to {role.mention}",
                ephemeral=True
            )
        else:
            config["blacklist_role_id"] = None
            await self.bot.db.update_config(self.guild_id, config)
            await interaction.response.send_message(
                "Blacklist role reset to auto-created 'Blacklisted'",
                ephemeral=True
            )

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=3)
    async def back_btn(self, interaction: discord.Interaction, button):
        await navigate_to_hub(interaction, self.bot, self.guild_id)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class BlacklistReasonModal(discord.ui.Modal, title="Blacklist User"):
    """Modal to enter a reason and optional duration when blacklisting a user."""

    def __init__(self, bot, guild_id, user):
        super().__init__(custom_id="modal_blacklist_reason")
        self.bot = bot
        self.guild_id = guild_id
        self.target_user = user

    reason = discord.ui.TextInput(
        label="Reason (optional)",
        placeholder="Enter the reason for blacklisting...",
        required=False,
        max_length=200,
        style=discord.TextStyle.short
    )

    duration = discord.ui.TextInput(
        label="Duration in hours (empty = permanent)",
        placeholder="e.g., 1, 24, 168 (1 week), empty = permanent",
        required=False,
        max_length=10,
        style=discord.TextStyle.short
    )

    async def on_submit(self, interaction: discord.Interaction):
        reason_text = self.reason.value.strip() or None

        duration_hours = None
        if self.duration.value.strip():
            try:
                duration_hours = float(self.duration.value.strip())
                if duration_hours <= 0 or duration_hours > 87600:  # Max ~10 years
                    await interaction.response.send_message(
                        "Duration must be between 0 and 87600 hours!",
                        ephemeral=True
                    )
                    return
            except ValueError:
                await interaction.response.send_message(
                    "Invalid duration! Enter a number of hours (e.g., 24 for 1 day).",
                    ephemeral=True
                )
                return

        await self.bot.db.add_to_blacklist(
            self.guild_id, self.target_user.id, interaction.user.id, reason_text, duration_hours
        )

        member = interaction.guild.get_member(self.target_user.id)
        role_status = ""
        if member:
            blacklist_role = await self.bot.get_blacklist_role(interaction.guild)
            if not blacklist_role:
                try:
                    blacklist_role = await interaction.guild.create_role(
                        name="Blacklisted",
                        color=discord.Color.dark_gray(),
                        reason="Created for blacklist system"
                    )
                except discord.Forbidden:
                    pass

            if blacklist_role:
                try:
                    await member.add_roles(blacklist_role, reason=f"Blacklisted by {interaction.user}")
                    role_status = "\n🏷️ Blacklisted role added"
                except discord.Forbidden:
                    role_status = "\n⚠️ Could not add role (missing permissions)"

        await self.bot.remove_from_queue(self.guild_id, self.target_user.id)
        await self.bot.update_queue_embed(self.guild_id)

        reason_display = f"\n📝 Reason: {reason_text}" if reason_text else ""
        if duration_hours:
            if duration_hours >= 24:
                dur_text = f"{duration_hours / 24:.1f} day(s)"
            else:
                dur_text = f"{duration_hours:.1f} hour(s)"
            duration_display = f"\n⏰ Duration: {dur_text}"
        else:
            duration_display = "\n⏰ Duration: Permanent"
        await interaction.response.send_message(
            f"🚫 **{self.target_user.display_name}** has been blacklisted!{reason_display}{duration_display}{role_status}",
            ephemeral=True
        )
        await self.bot.log_action(
            self.guild_id,
            "Admin: Blacklist Add",
            f"{interaction.user.mention} blacklisted {self.target_user.mention}{reason_display}{duration_display}",
            user=interaction.user, log_type="admin"
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SEASON MANAGEMENT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def build_seasons_embed(bot, guild_id):
    embed = discord.Embed(
        title="📅 Season Management",
        description="Manage competitive seasons per queue type. Each queue type (Queues, 2v2, 3v3) has independent seasons.",
        color=discord.Color.blue()
    )

    for qt, label in [('6v6', 'Queues'), ('2v2', '2v2'), ('3v3', '3v3')]:
        current = await bot.db.get_current_season(guild_id, qt)
        if current:
            season_id, name, start_date = current
            start_ts = int(datetime.fromisoformat(start_date).timestamp())
            embed.add_field(
                name=f"🟢 {label} Season",
                value=f"**{name}**\nStarted <t:{start_ts}:R>",
                inline=True
            )
        else:
            embed.add_field(
                name=f"📭 {label} Season",
                value="No active season",
                inline=True
            )

    seasons = await bot.db.get_all_seasons(guild_id)
    past = [s for s in seasons if not s[4]] if seasons else []
    if past:
        past_text = ""
        for sid, name, start, end, active in past[:5]:
            start_ts = int(datetime.fromisoformat(start).timestamp())
            past_text += f"• **{name}** — Started <t:{start_ts}:D>\n"
        if len(past) > 5:
            past_text += f"*...and {len(past) - 5} more*"
        embed.add_field(name="📚 Past Seasons", value=past_text, inline=False)

    embed.set_footer(text="Select a queue type, then start or end a season")
    return embed


async def navigate_to_seasons(interaction, bot, guild_id):
    embed = await build_seasons_embed(bot, guild_id)
    view = SeasonManageView(bot, guild_id)
    await interaction.response.edit_message(embed=embed, view=view)


class SeasonManageView(discord.ui.View):
    """Season management with queue type selection."""

    def __init__(self, bot, guild_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.selected_queue_type = '6v6'

    @discord.ui.select(
        placeholder="Select queue type for season action",
        options=[
            discord.SelectOption(label="Queues", value="6v6", emoji="🏐", description="Regular queues season"),
            discord.SelectOption(label="2v2 Queue", value="2v2", emoji="👥", description="2v2 season"),
            discord.SelectOption(label="3v3 Queue", value="3v3", emoji="👥", description="3v3 season"),
        ],
        row=0
    )
    async def queue_type_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.selected_queue_type = select.values[0]
        current = await self.bot.db.get_current_season(self.guild_id, self.selected_queue_type)
        status = f"**{current[1]}** (active)" if current else "No active season"
        await interaction.response.send_message(
            f"Selected **{self.selected_queue_type}** queue. Current status: {status}",
            ephemeral=True
        )

    @discord.ui.button(label="Start Season", emoji="▶️", style=discord.ButtonStyle.success, row=1)
    async def start_btn(self, interaction: discord.Interaction, button):
        current = await self.bot.db.get_current_season(self.guild_id, self.selected_queue_type)
        if current:
            await interaction.response.send_message(
                f"⚠️ {self.selected_queue_type} season **{current[1]}** is still active! End it first.",
                ephemeral=True
            )
            return
        modal = SeasonStartModal(self.bot, self.guild_id, self.selected_queue_type)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="End Season", emoji="⏹️", style=discord.ButtonStyle.danger, row=1)
    async def end_btn(self, interaction: discord.Interaction, button):
        current = await self.bot.db.get_current_season(self.guild_id, self.selected_queue_type)
        if not current:
            await interaction.response.send_message(
                f"⚠️ No active {self.selected_queue_type} season to end!",
                ephemeral=True
            )
            return
        view = SeasonEndConfirmView(self.bot, self.guild_id, current[1], self.selected_queue_type)
        await interaction.response.send_message(
            f"⚠️ Are you sure you want to end the {self.selected_queue_type} season **{current[1]}**?\n"
            f"This will **reset {self.selected_queue_type} player stats** and archive the season data.",
            view=view,
            ephemeral=True
        )

    @discord.ui.button(label="View Current", emoji="📊", style=discord.ButtonStyle.primary, row=1)
    async def view_current_btn(self, interaction: discord.Interaction, button):
        current = await self.bot.db.get_current_season(self.guild_id, self.selected_queue_type)
        if not current:
            await interaction.response.send_message(
                f"No active {self.selected_queue_type} season.",
                ephemeral=True
            )
            return

        season_id, name, start_date = current
        embed = discord.Embed(title=f"🏅 {name} ({self.selected_queue_type})", color=discord.Color.green())
        embed.add_field(
            name="📅 Started",
            value=f"<t:{int(datetime.fromisoformat(start_date).timestamp())}:R>",
            inline=True
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="List All", emoji="📋", style=discord.ButtonStyle.primary, row=2)
    async def list_btn(self, interaction: discord.Interaction, button):
        seasons = await self.bot.db.get_all_seasons(self.guild_id)

        embed = discord.Embed(title="📅 All Seasons", color=discord.Color.blue())

        if not seasons:
            embed.description = "No seasons created yet."
        else:
            for sid, name, start, end, active in seasons[:10]:
                status = "🟢 Active" if active else "🔴 Ended"
                # Get queue type from DB
                async with self.bot.db.db.execute(
                    'SELECT queue_type FROM seasons WHERE id = ?', (sid,)
                ) as cursor:
                    row = await cursor.fetchone()
                    qt = row[0] if row else '6v6'
                duration = ""
                if end:
                    days = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days
                    duration = f" ({days} days)"
                elif active:
                    days = (datetime.utcnow() - datetime.fromisoformat(start)).days
                    duration = f" ({days}d so far)"
                embed.add_field(
                    name=f"[{qt}] {name} {status}",
                    value=f"Started <t:{int(datetime.fromisoformat(start).timestamp())}:D>{duration}",
                    inline=True
                )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Remove Season", emoji="🗑️", style=discord.ButtonStyle.danger, row=2)
    async def remove_btn(self, interaction: discord.Interaction, button):
        modal = SeasonRemoveModal(self.bot, self.guild_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=3)
    async def back_btn(self, interaction: discord.Interaction, button):
        await navigate_to_hub(interaction, self.bot, self.guild_id)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class SeasonStartModal(discord.ui.Modal, title="Start New Season"):
    """Modal to name a new season for a specific queue type."""

    def __init__(self, bot, guild_id, queue_type='6v6'):
        super().__init__(custom_id="modal_season_start")
        self.bot = bot
        self.guild_id = guild_id
        self.queue_type = queue_type

    season_name = discord.ui.TextInput(
        label="Season Name",
        placeholder="e.g., Season 1, Spring 2024...",
        max_length=50
    )

    async def on_submit(self, interaction: discord.Interaction):
        name = self.season_name.value.strip()

        existing = await self.bot.db.get_season_by_name(self.guild_id, name, self.queue_type)
        if existing:
            await interaction.response.send_message(
                f"⚠️ A {self.queue_type} season named **{name}** already exists!",
                ephemeral=True
            )
            return

        await self.bot.db.create_season(self.guild_id, name, self.queue_type)
        config = await self.bot.db.get_config(self.guild_id)
        await self.bot.post_or_update_leaderboard(self.guild_id)

        embed = discord.Embed(
            title=f"🏅 {self.queue_type} Season Started!",
            description=f"**{name}** has begun for {self.queue_type}!",
            color=discord.Color.green()
        )
        embed.add_field(
            name="ℹ️ Info",
            value=(
                f"• Queue type: **{self.queue_type}**\n"
                f"• Starting ELO: **{config['starting_elo']}**\n"
                "• End with the **End Season** button"
            ),
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class SeasonEndConfirmView(discord.ui.View):
    """Confirmation buttons for ending a season."""

    def __init__(self, bot, guild_id, season_name, queue_type='6v6'):
        super().__init__(timeout=30)
        self.bot = bot
        self.guild_id = guild_id
        self.season_name = season_name
        self.queue_type = queue_type

    @discord.ui.button(label="Yes, End Season", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button):
        current = await self.bot.db.get_current_season(self.guild_id, self.queue_type)
        if not current:
            await interaction.response.edit_message(content="⚠️ No active season.", view=None)
            return

        season_id = current[0]

        config = await self.bot.db.get_config(self.guild_id)
        await self.bot.db.end_season(self.guild_id, self.queue_type)

        embed = discord.Embed(
            title=f"🏁 {self.queue_type} Season Ended",
            description=f"**{self.season_name}** ({self.queue_type}) has concluded!",
            color=discord.Color.orange()
        )
        embed.add_field(
            name="⚠️ Stats Reset",
            value=f"{self.queue_type} ELOs reset to **{config['starting_elo']}**. Past data archived.",
            inline=False
        )

        await self.bot.post_or_update_leaderboard(self.guild_id)
        await interaction.response.edit_message(content=None, embed=embed, view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button):
        await interaction.response.edit_message(content="Cancelled.", view=None)


class SeasonRemoveModal(discord.ui.Modal, title="Remove Season"):
    """Modal to enter the name of a past season to delete."""

    def __init__(self, bot, guild_id):
        super().__init__(custom_id="modal_season_remove")
        self.bot = bot
        self.guild_id = guild_id

    season_name = discord.ui.TextInput(
        label="Season Name",
        placeholder="Enter the exact name of the season to remove",
        max_length=50
    )

    async def on_submit(self, interaction: discord.Interaction):
        name = self.season_name.value.strip()

        season_data = await self.bot.db.get_season_by_name(self.guild_id, name)
        if not season_data:
            await interaction.response.send_message(f"⚠️ Season **{name}** not found!", ephemeral=True)
            return

        season_id, season_name, start, end, is_active = season_data
        if is_active:
            await interaction.response.send_message(
                "⚠️ Cannot remove the active season! End it first.",
                ephemeral=True
            )
            return

        await self.bot.db.delete_season(self.guild_id, season_id)
        await self.bot.post_or_update_leaderboard(self.guild_id)

        await interaction.response.send_message(
            f"🗑️ Season **{season_name}** has been removed!",
            ephemeral=True
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ELO ROLE REWARDS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def build_eloroles_embed(bot, guild_id, guild):
    mappings = await bot.db.get_all_elo_role_mappings_v2(guild_id)

    embed = discord.Embed(
        title="🎖️ ELO Role Rewards",
        description="Players automatically receive roles when reaching ELO thresholds after matches.\nRewards are grouped by queue type.",
        color=discord.Color.gold() if mappings else discord.Color.blue()
    )

    if mappings:
        # Group by queue_type
        qt_map = {}
        for pos, elo, role_id, queue_type in mappings:
            if queue_type not in qt_map:
                qt_map[queue_type] = []
            qt_map[queue_type].append((elo, role_id))

        for qt in sorted(qt_map.keys()):
            qt_map[qt].sort(key=lambda x: x[0])
            text = ""
            for elo, rid in qt_map[qt]:
                role = guild.get_role(rid)
                text += f"**{elo}** ELO → {role.mention if role else '*Deleted role*'}\n"

            qt_label = qt.upper() if qt in ('2v2', '3v3') else qt.replace('_', ' ').title()
            embed.add_field(name=f"🎖️ {qt_label}", value=text, inline=True)

        # Show starting role
        config = await bot.db.get_config(guild_id)
        starting_role_id = config.get("starting_elo_role_id")
        if starting_role_id:
            starting_role = guild.get_role(starting_role_id)
            starting_text = starting_role.mention if starting_role else "*Deleted role*"
        else:
            starting_text = "*Not set*"

        embed.add_field(
            name="📝 Notes",
            value=(
                f"**Starting Role:** {starting_text}\n"
                "• Roles update automatically after matches\n"
                "• Use **Sync** to manually update all players\n"
                "• Select a queue type below before adding/removing"
            ),
            inline=False
        )
    else:
        embed.add_field(
            name="No rewards configured",
            value="Select a queue type below, then click **Add Reward** to create ELO-based role rewards!",
            inline=False
        )

    embed.set_footer(text="Select queue type, then use the buttons to manage rewards")
    return embed


async def navigate_to_eloroles(interaction, bot, guild_id):
    embed = await build_eloroles_embed(bot, guild_id, interaction.guild)
    view = EloRolesManageView(bot, guild_id)
    await interaction.response.edit_message(embed=embed, view=view)


class EloRolesManageView(discord.ui.View):
    """Buttons for adding, removing, and syncing ELO role rewards."""

    def __init__(self, bot, guild_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.selected_queue_type = '6v6'

    @discord.ui.select(
        placeholder="Select queue type for ELO rewards",
        options=[
            discord.SelectOption(label="Queues", value="6v6", emoji="🏐", description="Per-position ELO rewards"),
            discord.SelectOption(label="2v2 Queue", value="2v2", emoji="👥", description="Singular MMR rewards"),
            discord.SelectOption(label="3v3 Queue", value="3v3", emoji="👥", description="Singular MMR rewards"),
            discord.SelectOption(label="High Rank", value="highrank", emoji="⭐", description="High rank per-position ELO rewards"),
            discord.SelectOption(label="High Rank 2v2", value="highrank_2v2", emoji="⭐", description="High rank 2v2 singular MMR rewards"),
            discord.SelectOption(label="High Rank 3v3", value="highrank_3v3", emoji="⭐", description="High rank 3v3 singular MMR rewards"),
        ],
        row=0
    )
    async def queue_type_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.selected_queue_type = select.values[0]
        note = f"Selected **{self.selected_queue_type}** — add/remove ELO rewards for this queue type."
        await interaction.response.send_message(note, ephemeral=True)

    @discord.ui.button(label="Add Reward", emoji="➕", style=discord.ButtonStyle.success, row=1)
    async def add_btn(self, interaction: discord.Interaction, button):
        modal = AddEloRoleModal(self.bot, self.guild_id, self.selected_queue_type)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Remove Reward", emoji="➖", style=discord.ButtonStyle.danger, row=1)
    async def remove_btn(self, interaction: discord.Interaction, button):
        modal = RemoveEloRoleModal(self.bot, self.guild_id, self.selected_queue_type)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Sync All Players", emoji="🔄", style=discord.ButtonStyle.primary, row=1)
    async def sync_btn(self, interaction: discord.Interaction, button):
        mappings = await self.bot.db.get_all_elo_role_mappings(self.guild_id)
        config = await self.bot.db.get_config(self.guild_id)
        starting_role_id = config.get("starting_elo_role_id")
        starting_role = interaction.guild.get_role(starting_role_id) if starting_role_id else None

        if not mappings and not starting_role:
            await interaction.response.send_message("⚠️ No rewards configured!", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        players = await self.bot.db.get_all_players(self.guild_id)
        updated = 0
        errors = []

        for user_id, ds_elo, fs_elo, s_elo, l_elo, games in players:
            member = interaction.guild.get_member(user_id)
            if not member:
                continue

            try:
                # Players with 0 games get the starting role only
                if games == 0:
                    if starting_role and starting_role not in member.roles:
                        await member.add_roles(starting_role, reason="ELO role sync - starting role")
                        updated += 1
                    continue

                ds_games = await self.bot.db.get_position_games_played(self.guild_id, user_id, "Defense Specialist")
                fs_games = await self.bot.db.get_position_games_played(self.guild_id, user_id, "Front Spiker")
                s_games = await self.bot.db.get_position_games_played(self.guild_id, user_id, "Setter")
                l_games = await self.bot.db.get_position_games_played(self.guild_id, user_id, "Libero")

                played = []
                if ds_games > 0:
                    played.append(ds_elo)
                if fs_games > 0:
                    played.append(fs_elo)
                if s_games > 0:
                    played.append(s_elo)
                if l_games > 0:
                    played.append(l_elo)
                avg = sum(played) / len(played) if played else 0

                pos_elos = {
                    "Defense Specialist": ds_elo if ds_games > 0 else 0,
                    "Front Spiker": fs_elo if fs_games > 0 else 0,
                    "Setter": s_elo if s_games > 0 else 0,
                    "Libero": l_elo if l_games > 0 else 0,
                    "all": avg
                }

                to_add, to_remove = [], []
                earned_any_role = False
                for pos, elo_thresh, role_id in mappings:
                    role = interaction.guild.get_role(role_id)
                    if not role:
                        continue

                    if pos != "all":
                        pg = await self.bot.db.get_position_games_played(self.guild_id, user_id, pos)
                        if pg == 0:
                            if role in member.roles:
                                to_remove.append(role)
                            continue

                    if pos_elos.get(pos, 0) >= elo_thresh:
                        earned_any_role = True
                        if role not in member.roles:
                            to_add.append(role)
                    else:
                        if role in member.roles:
                            to_remove.append(role)

                # Handle starting role: assign if no earned roles, remove if they've earned higher
                if starting_role:
                    if earned_any_role:
                        if starting_role in member.roles and starting_role not in to_remove:
                            to_remove.append(starting_role)
                    else:
                        if starting_role not in member.roles:
                            to_add.append(starting_role)

                if to_add:
                    await member.add_roles(*to_add, reason="ELO role sync")
                    updated += 1
                if to_remove:
                    await member.remove_roles(*to_remove, reason="ELO role sync")
                    updated += 1
            except Exception as e:
                errors.append(str(e))

        msg = f"✅ Synced roles for **{updated}** player{'s' if updated != 1 else ''}!"
        if errors:
            msg += f"\n⚠️ {len(errors)} error(s) occurred."
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="Set Starting Role", emoji="🏁", style=discord.ButtonStyle.secondary, row=2)
    async def starting_role_btn(self, interaction: discord.Interaction, button):
        view = StartingRoleSelectView(self.bot, self.guild_id)
        await interaction.response.send_message(
            "Select the role to assign to new players when they pick a region (or leave empty to clear):",
            view=view, ephemeral=True
        )

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=2)
    async def back_btn(self, interaction: discord.Interaction, button):
        await navigate_to_hub(interaction, self.bot, self.guild_id)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class StartingRoleSelectView(discord.ui.View):
    """Select the starting ELO role for new players."""

    def __init__(self, bot, guild_id):
        super().__init__(timeout=60)
        self.bot = bot
        self.guild_id = guild_id

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="Select starting role...", min_values=0, max_values=1)
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        config = await self.bot.db.get_config(self.guild_id)
        if select.values:
            role = select.values[0]
            config["starting_elo_role_id"] = role.id
            await self.bot.db.update_config(self.guild_id, config)
            msg = f"✅ Starting role set to {role.mention}"
        else:
            config["starting_elo_role_id"] = None
            await self.bot.db.update_config(self.guild_id, config)
            msg = "✅ Starting role cleared"

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content=msg, view=self)


# Position name aliases for modal text inputs
POSITION_ALIASES = {
    "defense": "Defense Specialist",
    "defense specialist": "Defense Specialist",
    "ds": "Defense Specialist",
    "spiker": "Front Spiker",
    "front spiker": "Front Spiker",
    "fs": "Front Spiker",
    "setter": "Setter",
    "s": "Setter",
    "libero": "Libero",
    "l": "Libero",
    "lib": "Libero",
    "all": "all",
    "average": "all",
    "avg": "all",
}


class AddEloRoleModal(discord.ui.Modal, title="Add ELO Role Reward"):
    """Modal to add a new ELO-based role reward (step 1: elo threshold)."""

    def __init__(self, bot, guild_id, queue_type='6v6'):
        super().__init__(custom_id="modal_add_elo_role")
        self.bot = bot
        self.guild_id = guild_id
        self.queue_type = queue_type

    elo_threshold = discord.ui.TextInput(
        label="ELO Threshold",
        placeholder="e.g., 800, 1000, 1200...",
        max_length=5
    )

    async def on_submit(self, interaction: discord.Interaction):
        position = "all"

        # Parse ELO
        try:
            elo = int(self.elo_threshold.value.strip())
            if elo < 0 or elo > 5000:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "ELO must be a number between 0 and 5000!",
                ephemeral=True
            )
            return

        # Step 2: Show role select view
        view = EloRoleSelectView(self.bot, self.guild_id, position, elo, self.queue_type)
        embed = discord.Embed(
            title="Select Role",
            description=f"Pick the role to assign for **[{self.queue_type}]** at **{elo}** ELO:",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class EloRoleSelectView(discord.ui.View):
    """Step 2: Role select for ELO role reward."""

    def __init__(self, bot, guild_id, position, elo, queue_type='6v6'):
        super().__init__(timeout=60)
        self.bot = bot
        self.guild_id = guild_id
        self.position = position
        self.elo = elo
        self.queue_type = queue_type

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="Select a role...", min_values=1, max_values=1)
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        role = select.values[0]
        await self.bot.db.add_elo_role_mapping_v2(self.guild_id, self.queue_type, self.position, self.elo, role.id)

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(
            content=f"✅ Added: **[{self.queue_type}]** at **{self.elo}** ELO → {role.mention}",
            embed=None,
            view=self
        )


class RemoveEloRoleModal(discord.ui.Modal, title="Remove ELO Role Reward"):
    """Modal to remove an existing ELO role reward."""

    def __init__(self, bot, guild_id, queue_type='6v6'):
        super().__init__(custom_id="modal_remove_elo_role")
        self.bot = bot
        self.guild_id = guild_id
        self.queue_type = queue_type

    elo_threshold = discord.ui.TextInput(
        label="ELO Threshold",
        placeholder="The exact ELO value to remove",
        max_length=5
    )

    async def on_submit(self, interaction: discord.Interaction):
        position = "all"

        try:
            elo = int(self.elo_threshold.value.strip())
        except ValueError:
            await interaction.response.send_message("⚠️ Enter a valid number!", ephemeral=True)
            return

        success = await self.bot.db.remove_elo_role_mapping_v2(self.guild_id, self.queue_type, position, elo)
        if success:
            await interaction.response.send_message(
                f"✅ Removed [{self.queue_type}] reward at **{elo}** ELO",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"⚠️ No [{self.queue_type}] reward found at **{elo}** ELO",
                ephemeral=True
            )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  QUEUE SETTINGS (Duo/Trio toggle, party requirements)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def navigate_to_queuesettings(interaction, bot, guild_id):
    config = await bot.db.get_config(guild_id)

    embed = discord.Embed(
        title="🎮 Queue Settings",
        description="Configure duo/trio queue availability, party requirements, and ready-up penalties.",
        color=discord.Color.blue()
    )

    duo_enabled = config.get("duo_queue_enabled", True)
    trio_enabled = config.get("trio_queue_enabled", True)
    duo_2v2_enabled = config.get("duo_2v2_enabled", True)
    duo_3v3_enabled = config.get("duo_3v3_enabled", True)
    trio_3v3_enabled = config.get("trio_3v3_enabled", True)
    require_duo_2v2 = config.get("require_duo_2v2", False)
    require_trio_3v3 = config.get("require_trio_3v3", False)

    ban_duration = config.get("readyup_ban_duration", 600)
    elo_penalty = config.get("readyup_elo_penalty", 10)
    ban_text = f"{ban_duration // 60} minutes" if ban_duration > 0 else "Disabled"

    embed.add_field(
        name="Queue Modes",
        value=(
            f"**Duo Queue:** {'Enabled' if duo_enabled else 'Disabled'}\n"
            f"**Trio Queue:** {'Enabled' if trio_enabled else 'Disabled'}"
        ),
        inline=True
    )
    embed.add_field(
        name="2v2 / 3v3 Queue Modes",
        value=(
            f"**2v2 Duo Queue:** {'Enabled' if duo_2v2_enabled else 'Disabled'}\n"
            f"**3v3 Duo Queue:** {'Enabled' if duo_3v3_enabled else 'Disabled'}\n"
            f"**3v3 Trio Queue:** {'Enabled' if trio_3v3_enabled else 'Disabled'}"
        ),
        inline=True
    )
    embed.add_field(
        name="Party Requirements",
        value=(
            f"**2v2 Requires Duo Party:** {'Yes' if require_duo_2v2 else 'No'}\n"
            f"**3v3 Requires Trio Party:** {'Yes' if require_trio_3v3 else 'No'}"
        ),
        inline=True
    )
    embed.add_field(
        name="Ready-Up Penalties",
        value=(
            f"**Queue Ban:** {ban_text}\n"
            f"**ELO Penalty:** -{elo_penalty} ELO" if elo_penalty > 0 else f"**Queue Ban:** {ban_text}\n**ELO Penalty:** Disabled"
        ),
        inline=True
    )
    # Region team sizes
    from config import DEFAULT_REGION_TEAM_SIZES
    region_team_sizes = config.get("region_team_sizes", DEFAULT_REGION_TEAM_SIZES)
    rts_lines = []
    for region in ["NA", "EU", "Asia", "OCE"]:
        size = region_team_sizes.get(region, "6v6")
        rts_lines.append(f"**{region}:** {size}")
    embed.add_field(
        name="Region Team Sizes",
        value="\n".join(rts_lines),
        inline=True
    )

    # Required roles
    required_roles = config.get("required_roles", [])
    if required_roles:
        role_mentions = ", ".join(f"<@&{rid}>" for rid in required_roles)
        req_text = role_mentions
    else:
        req_text = "None (anyone can queue)"
    embed.add_field(
        name="Required Roles",
        value=req_text,
        inline=True
    )

    embed.add_field(
        name="ℹ️ Info",
        value=(
            "• **Duo/Trio Toggle (6v6)** controls the 6v6 queue's duo/trio buttons\n"
            "• **2v2/3v3 Toggles** control duo/trio buttons in those queues\n"
            "• **Party Requirements** force players to use the party button\n"
            "• **Ready-Up Penalties** applied when players fail to ready up\n"
            "• **Region Team Sizes** toggle between 5v5 (no Libero) and 6v6\n"
            "• **Required Roles** restrict queueing to users with specific roles"
        ),
        inline=False
    )

    view = QueueSettingsView(bot, guild_id)
    await interaction.response.edit_message(embed=embed, view=view)


class QueueSettingsView(discord.ui.View):
    def __init__(self, bot, guild_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id

    @discord.ui.button(label="Toggle Duo Queue", style=discord.ButtonStyle.primary, row=0)
    async def toggle_duo(self, interaction: discord.Interaction, button):
        config = await self.bot.db.get_config(self.guild_id)
        config["duo_queue_enabled"] = not config.get("duo_queue_enabled", True)
        await self.bot.db.update_config(self.guild_id, config)
        state = "enabled" if config["duo_queue_enabled"] else "disabled"
        await interaction.response.send_message(f"Duo queue {state}.", ephemeral=True)

    @discord.ui.button(label="Toggle Trio Queue", style=discord.ButtonStyle.primary, row=0)
    async def toggle_trio(self, interaction: discord.Interaction, button):
        config = await self.bot.db.get_config(self.guild_id)
        config["trio_queue_enabled"] = not config.get("trio_queue_enabled", True)
        await self.bot.db.update_config(self.guild_id, config)
        state = "enabled" if config["trio_queue_enabled"] else "disabled"
        await interaction.response.send_message(f"Trio queue {state}.", ephemeral=True)

    @discord.ui.button(label="Toggle 2v2 Duo", style=discord.ButtonStyle.primary, row=1)
    async def toggle_duo_2v2(self, interaction: discord.Interaction, button):
        config = await self.bot.db.get_config(self.guild_id)
        config["duo_2v2_enabled"] = not config.get("duo_2v2_enabled", True)
        await self.bot.db.update_config(self.guild_id, config)
        state = "enabled" if config["duo_2v2_enabled"] else "disabled"
        await interaction.response.send_message(f"2v2 duo queue {state}.", ephemeral=True)

    @discord.ui.button(label="Toggle 3v3 Duo", style=discord.ButtonStyle.primary, row=1)
    async def toggle_duo_3v3(self, interaction: discord.Interaction, button):
        config = await self.bot.db.get_config(self.guild_id)
        config["duo_3v3_enabled"] = not config.get("duo_3v3_enabled", True)
        await self.bot.db.update_config(self.guild_id, config)
        state = "enabled" if config["duo_3v3_enabled"] else "disabled"
        await interaction.response.send_message(f"3v3 duo queue {state}.", ephemeral=True)

    @discord.ui.button(label="Toggle 3v3 Trio", style=discord.ButtonStyle.primary, row=1)
    async def toggle_trio_3v3(self, interaction: discord.Interaction, button):
        config = await self.bot.db.get_config(self.guild_id)
        config["trio_3v3_enabled"] = not config.get("trio_3v3_enabled", True)
        await self.bot.db.update_config(self.guild_id, config)
        state = "enabled" if config["trio_3v3_enabled"] else "disabled"
        await interaction.response.send_message(f"3v3 trio queue {state}.", ephemeral=True)

    @discord.ui.button(label="Required Roles", style=discord.ButtonStyle.secondary, row=2)
    async def required_roles_btn(self, interaction: discord.Interaction, button):
        config = await self.bot.db.get_config(self.guild_id)
        current_roles = config.get("required_roles", [])

        desc = "Select the Discord roles required to join any queue.\nPlayers must have **at least one** of these roles to queue."
        if current_roles:
            role_mentions = ", ".join(f"<@&{rid}>" for rid in current_roles)
            desc += f"\n\n**Current required roles:** {role_mentions}"
        else:
            desc += "\n\nNo required roles set (anyone can queue)."

        embed = discord.Embed(
            title="Required Roles",
            description=desc,
            color=discord.Color.blue()
        )
        view = RequiredRolesView(self.bot, self.guild_id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Toggle 2v2 Duo Requirement", style=discord.ButtonStyle.secondary, row=2)
    async def toggle_require_duo_2v2(self, interaction: discord.Interaction, button):
        config = await self.bot.db.get_config(self.guild_id)
        config["require_duo_2v2"] = not config.get("require_duo_2v2", False)
        await self.bot.db.update_config(self.guild_id, config)
        state = "required" if config["require_duo_2v2"] else "not required"
        await interaction.response.send_message(f"Duo party for 2v2 is now {state}.", ephemeral=True)

    @discord.ui.button(label="Toggle 3v3 Trio Requirement", style=discord.ButtonStyle.secondary, row=2)
    async def toggle_require_trio_3v3(self, interaction: discord.Interaction, button):
        config = await self.bot.db.get_config(self.guild_id)
        config["require_trio_3v3"] = not config.get("require_trio_3v3", False)
        await self.bot.db.update_config(self.guild_id, config)
        state = "required" if config["require_trio_3v3"] else "not required"
        await interaction.response.send_message(f"Trio party for 3v3 is now {state}.", ephemeral=True)

    @discord.ui.button(label="Ready-Up Ban Duration", style=discord.ButtonStyle.danger, row=3)
    async def readyup_ban_btn(self, interaction: discord.Interaction, button):
        config = await self.bot.db.get_config(self.guild_id)
        modal = ReadyUpBanModal(self.bot, self.guild_id)
        modal.ban_duration.default = str(config.get("readyup_ban_duration", 600) // 60)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Ready-Up ELO Penalty", style=discord.ButtonStyle.danger, row=3)
    async def readyup_elo_btn(self, interaction: discord.Interaction, button):
        config = await self.bot.db.get_config(self.guild_id)
        modal = ReadyUpEloPenaltyModal(self.bot, self.guild_id)
        modal.elo_penalty.default = str(config.get("readyup_elo_penalty", 10))
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Region Team Sizes", style=discord.ButtonStyle.success, row=3)
    async def region_team_sizes_btn(self, interaction: discord.Interaction, button):
        await navigate_to_region_team_sizes(interaction, self.bot, self.guild_id)

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=4)
    async def back_btn(self, interaction: discord.Interaction, button):
        await navigate_to_hub(interaction, self.bot, self.guild_id)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class RequiredRolesView(discord.ui.View):
    """View for selecting required Discord roles to queue."""
    def __init__(self, bot, guild_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id

    @discord.ui.select(
        cls=discord.ui.RoleSelect,
        placeholder="Select required roles...",
        min_values=0, max_values=10
    )
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        config = await self.bot.db.get_config(self.guild_id)
        config["required_roles"] = [role.id for role in select.values]
        await self.bot.db.update_config(self.guild_id, config)
        if select.values:
            role_mentions = ", ".join(role.mention for role in select.values)
            await interaction.response.send_message(
                f"Required roles set to: {role_mentions}\nPlayers must have at least one of these roles to queue.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "Required roles cleared. Anyone can queue.",
                ephemeral=True
            )

    @discord.ui.button(label="Clear All Required Roles", style=discord.ButtonStyle.danger)
    async def clear_btn(self, interaction: discord.Interaction, button):
        config = await self.bot.db.get_config(self.guild_id)
        config["required_roles"] = []
        await self.bot.db.update_config(self.guild_id, config)
        await interaction.response.send_message(
            "Required roles cleared. Anyone can queue.",
            ephemeral=True
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class ReadyUpBanModal(discord.ui.Modal, title="Ready-Up Queue Ban Duration"):
    def __init__(self, bot, guild_id):
        super().__init__()
        self.bot = bot
        self.guild_id = guild_id

    ban_duration = discord.ui.TextInput(
        label="Queue ban duration (minutes, 0 to disable)",
        placeholder="10",
        max_length=5,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            minutes = int(self.ban_duration.value)
            if minutes < 0:
                await interaction.response.send_message("Duration cannot be negative!", ephemeral=True)
                return
            config = await self.bot.db.get_config(self.guild_id)
            config["readyup_ban_duration"] = minutes * 60
            await self.bot.db.update_config(self.guild_id, config)
            if minutes == 0:
                await interaction.response.send_message("Ready-up queue ban disabled.", ephemeral=True)
            else:
                await interaction.response.send_message(f"Ready-up queue ban set to **{minutes} minutes**.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("Please enter a valid number!", ephemeral=True)


class ReadyUpEloPenaltyModal(discord.ui.Modal, title="Ready-Up ELO Penalty"):
    def __init__(self, bot, guild_id):
        super().__init__()
        self.bot = bot
        self.guild_id = guild_id

    elo_penalty = discord.ui.TextInput(
        label="ELO penalty for not readying up (0 to disable)",
        placeholder="10",
        max_length=5,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            penalty = int(self.elo_penalty.value)
            if penalty < 0:
                await interaction.response.send_message("Penalty cannot be negative!", ephemeral=True)
                return
            config = await self.bot.db.get_config(self.guild_id)
            config["readyup_elo_penalty"] = penalty
            await self.bot.db.update_config(self.guild_id, config)
            if penalty == 0:
                await interaction.response.send_message("Ready-up ELO penalty disabled.", ephemeral=True)
            else:
                await interaction.response.send_message(f"Ready-up ELO penalty set to **-{penalty}**.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("Please enter a valid number!", ephemeral=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  REGION TEAM SIZES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def navigate_to_region_team_sizes(interaction, bot, guild_id):
    from config import DEFAULT_REGION_TEAM_SIZES
    config = await bot.db.get_config(guild_id)
    region_team_sizes = config.get("region_team_sizes", DEFAULT_REGION_TEAM_SIZES)

    embed = discord.Embed(
        title="Region Team Sizes",
        description=(
            "Configure whether each region uses **5v5** or **6v6** format.\n\n"
            "**5v5** = 10 players (no Libero, Defense Specialist only)\n"
            "**6v6** = 12 players (includes Libero)"
        ),
        color=discord.Color.blue()
    )

    for region in ["NA", "EU", "Asia", "OCE"]:
        size = region_team_sizes.get(region, "6v6")
        embed.add_field(name=region, value=f"**{size}**", inline=True)

    view = RegionTeamSizesView(bot, guild_id)
    await interaction.response.edit_message(embed=embed, view=view)


class RegionTeamSizesView(discord.ui.View):
    def __init__(self, bot, guild_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id

    async def _toggle_region(self, interaction, region):
        from config import DEFAULT_REGION_TEAM_SIZES
        config = await self.bot.db.get_config(self.guild_id)
        region_team_sizes = config.get("region_team_sizes", dict(DEFAULT_REGION_TEAM_SIZES))
        current = region_team_sizes.get(region, "6v6")
        new_size = "5v5" if current == "6v6" else "6v6"
        region_team_sizes[region] = new_size
        config["region_team_sizes"] = region_team_sizes
        await self.bot.db.update_config(self.guild_id, config)
        await navigate_to_region_team_sizes(interaction, self.bot, self.guild_id)

    @discord.ui.button(label="Toggle NA", style=discord.ButtonStyle.primary, row=0)
    async def toggle_na(self, interaction: discord.Interaction, button):
        await self._toggle_region(interaction, "NA")

    @discord.ui.button(label="Toggle EU", style=discord.ButtonStyle.primary, row=0)
    async def toggle_eu(self, interaction: discord.Interaction, button):
        await self._toggle_region(interaction, "EU")

    @discord.ui.button(label="Toggle Asia", style=discord.ButtonStyle.primary, row=0)
    async def toggle_asia(self, interaction: discord.Interaction, button):
        await self._toggle_region(interaction, "Asia")

    @discord.ui.button(label="Toggle OCE", style=discord.ButtonStyle.primary, row=0)
    async def toggle_oce(self, interaction: discord.Interaction, button):
        await self._toggle_region(interaction, "OCE")

    @discord.ui.button(label="◀ Back to Queue Settings", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, interaction: discord.Interaction, button):
        await navigate_to_queuesettings(interaction, self.bot, self.guild_id)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  HIGH RANK SETTINGS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def navigate_to_highrank(interaction, bot, guild_id):
    config = await bot.db.get_config(guild_id)

    embed = discord.Embed(
        title="High Rank Queue Settings",
        description=(
            "High rank queues are separate queues for top players.\n"
            "Players must reach the MMR limit in normal queue to unlock high rank.\n"
            "High rank has its own separate ELO."
        ),
        color=discord.Color.purple()
    )
    hr_starting_elo = config.get("high_rank_starting_elo", config.get("starting_elo", 650))

    hr_solo = config.get("high_rank_solo_enabled", False)
    hr_duo = config.get("high_rank_duo_enabled", True)
    hr_trio = config.get("high_rank_trio_enabled", False)
    embed.add_field(
        name="Queues High Rank",
        value=(
            f"**Enabled:** {'Yes' if config.get('high_rank_enabled', False) else 'No'}\n"
            f"**MMR Limit:** {config.get('high_rank_mmr_limit', 1000)}\n"
            f"**Solo:** {'Yes' if hr_solo else 'No'} | **Duo:** {'Yes' if hr_duo else 'No'} | **Trio:** {'Yes' if hr_trio else 'No'}\n"
            "Separate per-position ELO"
        ),
        inline=True
    )
    embed.add_field(
        name="2v2 High Rank",
        value=(
            f"**Enabled:** {'Yes' if config.get('high_rank_2v2_enabled', False) else 'No'}\n"
            f"**MMR Limit:** {config.get('high_rank_2v2_mmr_limit', 1000)}\n"
            "Separate singular ELO"
        ),
        inline=True
    )
    embed.add_field(
        name="3v3 High Rank",
        value=(
            f"**Enabled:** {'Yes' if config.get('high_rank_3v3_enabled', False) else 'No'}\n"
            f"**MMR Limit:** {config.get('high_rank_3v3_mmr_limit', 1000)}\n"
            "Separate singular ELO"
        ),
        inline=True
    )
    embed.add_field(
        name="Starting ELO",
        value=f"**High Rank Starting ELO:** {hr_starting_elo}",
        inline=False
    )

    view = HighRankSettingsView(bot, guild_id)
    await interaction.response.edit_message(embed=embed, view=view)


class HighRankSettingsView(discord.ui.View):
    def __init__(self, bot, guild_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.selected_type = '6v6'

    @discord.ui.select(
        placeholder="Select queue type for high rank settings",
        options=[
            discord.SelectOption(label="Queues High Rank", value="6v6", emoji="🏐"),
            discord.SelectOption(label="2v2 High Rank", value="2v2", emoji="👥"),
            discord.SelectOption(label="3v3 High Rank", value="3v3", emoji="👥"),
        ],
        row=0
    )
    async def type_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.selected_type = select.values[0]
        config = await self.bot.db.get_config(self.guild_id)
        if self.selected_type == '6v6':
            enabled = config.get("high_rank_enabled", False)
            limit = config.get("high_rank_mmr_limit", 1000)
        elif self.selected_type == '2v2':
            enabled = config.get("high_rank_2v2_enabled", False)
            limit = config.get("high_rank_2v2_mmr_limit", 1000)
        else:
            enabled = config.get("high_rank_3v3_enabled", False)
            limit = config.get("high_rank_3v3_mmr_limit", 1000)
        await interaction.response.send_message(
            f"Selected **{self.selected_type}** high rank. Enabled: {enabled}, Limit: {limit}",
            ephemeral=True
        )

    @discord.ui.button(label="Toggle On/Off", style=discord.ButtonStyle.primary, row=1)
    async def toggle_btn(self, interaction: discord.Interaction, button):
        config = await self.bot.db.get_config(self.guild_id)
        if self.selected_type == '6v6':
            config["high_rank_enabled"] = not config.get("high_rank_enabled", False)
            state = "enabled" if config["high_rank_enabled"] else "disabled"
        elif self.selected_type == '2v2':
            config["high_rank_2v2_enabled"] = not config.get("high_rank_2v2_enabled", False)
            state = "enabled" if config["high_rank_2v2_enabled"] else "disabled"
        else:
            config["high_rank_3v3_enabled"] = not config.get("high_rank_3v3_enabled", False)
            state = "enabled" if config["high_rank_3v3_enabled"] else "disabled"
        await self.bot.db.update_config(self.guild_id, config)
        await interaction.response.send_message(f"{self.selected_type} high rank queue {state}.", ephemeral=True)

    @discord.ui.button(label="Set MMR Limit", style=discord.ButtonStyle.secondary, row=1)
    async def mmr_limit_btn(self, interaction: discord.Interaction, button):
        modal = HighRankMmrModal(self.bot, self.guild_id, self.selected_type)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Set Starting ELO", style=discord.ButtonStyle.secondary, row=1)
    async def starting_elo_btn(self, interaction: discord.Interaction, button):
        modal = HighRankStartingEloModal(self.bot, self.guild_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Toggle HR Solo", style=discord.ButtonStyle.primary, row=2)
    async def toggle_hr_solo(self, interaction: discord.Interaction, button):
        config = await self.bot.db.get_config(self.guild_id)
        config["high_rank_solo_enabled"] = not config.get("high_rank_solo_enabled", False)
        await self.bot.db.update_config(self.guild_id, config)
        state = "enabled" if config["high_rank_solo_enabled"] else "disabled"
        await interaction.response.send_message(f"High rank solo queue {state}.", ephemeral=True)

    @discord.ui.button(label="Toggle HR Duo", style=discord.ButtonStyle.primary, row=2)
    async def toggle_hr_duo(self, interaction: discord.Interaction, button):
        config = await self.bot.db.get_config(self.guild_id)
        config["high_rank_duo_enabled"] = not config.get("high_rank_duo_enabled", True)
        await self.bot.db.update_config(self.guild_id, config)
        state = "enabled" if config["high_rank_duo_enabled"] else "disabled"
        await interaction.response.send_message(f"High rank duo queue {state}.", ephemeral=True)

    @discord.ui.button(label="Toggle HR Trio", style=discord.ButtonStyle.primary, row=2)
    async def toggle_hr_trio(self, interaction: discord.Interaction, button):
        config = await self.bot.db.get_config(self.guild_id)
        config["high_rank_trio_enabled"] = not config.get("high_rank_trio_enabled", False)
        await self.bot.db.update_config(self.guild_id, config)
        state = "enabled" if config["high_rank_trio_enabled"] else "disabled"
        await interaction.response.send_message(f"High rank trio queue {state}.", ephemeral=True)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=3)
    async def back_btn(self, interaction: discord.Interaction, button):
        await navigate_to_hub(interaction, self.bot, self.guild_id)


class HighRankMmrModal(discord.ui.Modal, title="Set High Rank MMR Limit"):
    def __init__(self, bot, guild_id, queue_type='6v6'):
        super().__init__(custom_id="modal_highrank_mmr")
        self.bot = bot
        self.guild_id = guild_id
        self.queue_type = queue_type

    mmr_limit = discord.ui.TextInput(
        label="Minimum MMR to unlock high rank",
        placeholder="e.g., 1000",
        max_length=5
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            limit = int(self.mmr_limit.value.strip())
            if limit < 0 or limit > 5000:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("Enter a valid number between 0 and 5000.", ephemeral=True)
            return

        config = await self.bot.db.get_config(self.guild_id)
        if self.queue_type == '6v6':
            config["high_rank_mmr_limit"] = limit
        elif self.queue_type == '2v2':
            config["high_rank_2v2_mmr_limit"] = limit
        else:
            config["high_rank_3v3_mmr_limit"] = limit
        await self.bot.db.update_config(self.guild_id, config)
        await interaction.response.send_message(
            f"{self.queue_type} high rank MMR limit set to **{limit}**.",
            ephemeral=True
        )


class HighRankStartingEloModal(discord.ui.Modal, title="Set High Rank Starting ELO"):
    def __init__(self, bot, guild_id):
        super().__init__(custom_id="modal_highrank_starting_elo")
        self.bot = bot
        self.guild_id = guild_id

    starting_elo = discord.ui.TextInput(
        label="Starting ELO for all high rank queues",
        placeholder="e.g., 650",
        max_length=5
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            elo = int(self.starting_elo.value.strip())
            if elo < 0 or elo > 5000:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("Enter a valid number between 0 and 5000.", ephemeral=True)
            return

        config = await self.bot.db.get_config(self.guild_id)
        config["high_rank_starting_elo"] = elo
        await self.bot.db.update_config(self.guild_id, config)
        await interaction.response.send_message(
            f"High rank starting ELO set to **{elo}** for all high rank queues.",
            ephemeral=True
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ADMIN TOOLS (Hub with Player, Blacklist, Match tabs)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def navigate_to_admintools(interaction, bot, guild_id):
    embed = await build_admintools_hub_embed(bot, guild_id)
    view = AdminToolsHubView(bot, guild_id)
    await interaction.response.edit_message(embed=embed, view=view)


async def build_admintools_hub_embed(bot, guild_id):
    """Build the admin tools hub embed with overview."""
    blacklist = await bot.db.get_blacklist(guild_id)
    active_matches = await bot.db.get_active_matches(guild_id)

    embed = discord.Embed(
        title="🔧 Admin Tools",
        description="Manage players, blacklist, matches, and queue from one place.",
        color=discord.Color.orange()
    )
    embed.add_field(
        name="👤 Players & Queue",
        value="Edit ELO, adjust ELO, reset stats\nClear queue, remove players",
        inline=True
    )
    embed.add_field(
        name="🚫 Blacklist",
        value=f"**{len(blacklist)}** user{'s' if len(blacklist) != 1 else ''} blacklisted\nAdd, remove, view all",
        inline=True
    )
    embed.add_field(
        name="🏐 Matches",
        value=f"**{len(active_matches)}** active match{'es' if len(active_matches) != 1 else ''}\nReport, edit, delete, change winner",
        inline=True
    )
    embed.set_footer(text="Select a tab below to manage")
    return embed


class AdminToolsHubView(discord.ui.View):
    """Admin tools hub with tab navigation."""

    def __init__(self, bot, guild_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id

    @discord.ui.button(label="Players & Queue", emoji="👤", style=discord.ButtonStyle.primary, row=0)
    async def players_tab(self, interaction: discord.Interaction, button):
        embed = build_admin_players_embed()
        view = AdminPlayersView(self.bot, self.guild_id)
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Blacklist", emoji="🚫", style=discord.ButtonStyle.danger, row=0)
    async def blacklist_tab(self, interaction: discord.Interaction, button):
        embed = await build_admin_blacklist_embed(self.bot, self.guild_id)
        view = AdminBlacklistView(self.bot, self.guild_id)
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Matches", emoji="🏐", style=discord.ButtonStyle.success, row=0)
    async def matches_tab(self, interaction: discord.Interaction, button):
        embed = await build_admin_matches_embed(self.bot, self.guild_id)
        view = AdminMatchesView(self.bot, self.guild_id)
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, interaction: discord.Interaction, button):
        await navigate_to_hub(interaction, self.bot, self.guild_id)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ── ADMIN: PLAYERS & QUEUE TAB ──

def build_admin_players_embed():
    embed = discord.Embed(
        title="🔧 Admin Tools — Players & Queue",
        description="Select a user, then choose an action.\nUse the dropdowns to pick queue type easily.",
        color=discord.Color.orange()
    )
    embed.add_field(
        name="👤 Player Actions",
        value="**Set ELO** — Pick queue type, enter value (optionally set region)\n**Adjust ELO** — Add/subtract ELO (optionally per region)\n**Reset** — Wipe all stats",
        inline=True
    )
    embed.add_field(
        name="📋 Queue Actions",
        value="**Clear Queue** — Remove everyone\n**Remove** — Kick one user",
        inline=True
    )
    embed.set_footer(text="1. Select a user  2. Pick queue type  3. Click action")
    return embed


class AdminPlayersView(discord.ui.View):
    """Simplified player management + queue controls with dropdown-based queue type."""

    def __init__(self, bot, guild_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.selected_user = None
        self.selected_queue_type = "6v6"
        self.selected_position = None  # Only for 6v6/highrank

    @discord.ui.select(
        cls=discord.ui.UserSelect,
        placeholder="👤 Select a player...",
        min_values=1, max_values=1, row=0
    )
    async def user_select(self, interaction: discord.Interaction, select):
        self.selected_user = select.values[0]
        lines = []

        # 6v6 stats
        stats = await self.bot.db.get_player_stats(self.guild_id, self.selected_user.id)
        if stats:
            ds_elo, fs_elo, s_elo, l_elo, games, wins, losses = stats
            played = []
            for pos, elo in [("DS", ds_elo), ("FS", fs_elo), ("S", s_elo), ("L", l_elo)]:
                played.append(f"{pos}: **{elo}**")
            lines.append(f"**Queues:** {games}G | " + " | ".join(played))

        # 2v2 stats
        stats_2v2 = await self.bot.db.get_player_stats_simple(self.guild_id, self.selected_user.id, '2v2')
        if stats_2v2:
            elo_2v2, g2, w2, l2 = stats_2v2
            lines.append(f"**2v2:** {g2}G ({w2}W/{l2}L) | ELO: **{elo_2v2}**")

        # 3v3 stats
        stats_3v3 = await self.bot.db.get_player_stats_simple(self.guild_id, self.selected_user.id, '3v3')
        if stats_3v3:
            elo_3v3, g3, w3, l3 = stats_3v3
            lines.append(f"**3v3:** {g3}G ({w3}W/{l3}L) | ELO: **{elo_3v3}**")

        # High Rank 6v6 stats
        hr_stats = await self.bot.db.get_player_stats_highrank(self.guild_id, self.selected_user.id)
        if hr_stats:
            hr_ds, hr_fs, hr_s, hr_l, hr_g, hr_w, hr_l2 = hr_stats
            if hr_g > 0:
                hr_played = []
                for pos, elo in [("DS", hr_ds), ("FS", hr_fs), ("S", hr_s), ("L", hr_l)]:
                    hr_played.append(f"{pos}: **{elo}**")
                lines.append(f"**HR:** {hr_g}G | " + " | ".join(hr_played))

        # High Rank 2v2 stats
        hr2v2 = await self.bot.db.get_player_stats_simple(self.guild_id, self.selected_user.id, 'highrank_2v2')
        if hr2v2:
            hr_e2, hr_g2, hr_w2, hr_l2 = hr2v2
            if hr_g2 > 0:
                lines.append(f"**HR 2v2:** {hr_g2}G ({hr_w2}W/{hr_l2}L) | ELO: **{hr_e2}**")

        # High Rank 3v3 stats
        hr3v3 = await self.bot.db.get_player_stats_simple(self.guild_id, self.selected_user.id, 'highrank_3v3')
        if hr3v3:
            hr_e3, hr_g3, hr_w3, hr_l3 = hr3v3
            if hr_g3 > 0:
                lines.append(f"**HR 3v3:** {hr_g3}G ({hr_w3}W/{hr_l3}L) | ELO: **{hr_e3}**")

        if lines:
            await interaction.response.send_message(
                f"Selected **{self.selected_user.display_name}**\n" + "\n".join(lines),
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"Selected **{self.selected_user.display_name}** — No stats yet",
                ephemeral=True
            )

    @discord.ui.select(
        placeholder="Queue type & position...",
        options=[
            discord.SelectOption(label="Queues — Defense Specialist", value="6v6_Defense Specialist", emoji="🛡️"),
            discord.SelectOption(label="Queues — Front Spiker", value="6v6_Front Spiker", emoji="⚡"),
            discord.SelectOption(label="Queues — Setter", value="6v6_Setter", emoji="🏐"),
            discord.SelectOption(label="Queues — Libero", value="6v6_Libero", emoji="🎯"),
            discord.SelectOption(label="2v2", value="2v2", emoji="👥"),
            discord.SelectOption(label="3v3", value="3v3", emoji="👥"),
            discord.SelectOption(label="HR — Defense Specialist", value="highrank_Defense Specialist", emoji="🛡️"),
            discord.SelectOption(label="HR — Front Spiker", value="highrank_Front Spiker", emoji="⚡"),
            discord.SelectOption(label="HR — Setter", value="highrank_Setter", emoji="🏐"),
            discord.SelectOption(label="HR — Libero", value="highrank_Libero", emoji="🎯"),
            discord.SelectOption(label="HR 2v2", value="highrank_2v2", emoji="🔥"),
            discord.SelectOption(label="HR 3v3", value="highrank_3v3", emoji="🔥"),
        ],
        row=1
    )
    async def queue_type_select(self, interaction: discord.Interaction, select):
        value = select.values[0]
        if "_" in value and value.split("_", 1)[1] in ("Defense Specialist", "Front Spiker", "Setter", "Libero"):
            parts = value.split("_", 1)
            self.selected_queue_type = parts[0]
            self.selected_position = parts[1]
        else:
            self.selected_queue_type = value
            self.selected_position = None
        label = value.replace("_", " — ", 1) if self.selected_position else value
        await interaction.response.send_message(f"Selected queue type: **{label}**", ephemeral=True)

    @discord.ui.button(label="Set ELO", emoji="✏️", style=discord.ButtonStyle.primary, row=2)
    async def set_elo_btn(self, interaction: discord.Interaction, button):
        if not self.selected_user:
            await interaction.response.send_message("⚠️ Select a player first!", ephemeral=True)
            return
        modal = SimpleSetEloModal(self.bot, self.guild_id, self.selected_user, self.selected_queue_type, self.selected_position)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Adjust ELO", emoji="📊", style=discord.ButtonStyle.primary, row=2)
    async def adjust_elo_btn(self, interaction: discord.Interaction, button):
        if not self.selected_user:
            await interaction.response.send_message("⚠️ Select a player first!", ephemeral=True)
            return
        modal = SimpleAdjustEloModal(self.bot, self.guild_id, self.selected_user, self.selected_queue_type, self.selected_position)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Reset Player", emoji="🗑️", style=discord.ButtonStyle.danger, row=2)
    async def reset_player_btn(self, interaction: discord.Interaction, button):
        if not self.selected_user:
            await interaction.response.send_message("⚠️ Select a player first!", ephemeral=True)
            return
        view = ResetPlayerConfirmView(self.bot, self.guild_id, self.selected_user)
        await interaction.response.send_message(
            f"⚠️ Are you sure you want to **reset all stats** for {self.selected_user.mention}?\n"
            "This cannot be undone.",
            view=view,
            ephemeral=True
        )

    @discord.ui.button(label="Clear Queue", emoji="🧹", style=discord.ButtonStyle.danger, row=3)
    async def clear_queue_btn(self, interaction: discord.Interaction, button):
        if not await check_senior_staff(interaction, self.bot):
            return
        await self.bot.db.clear_queue(self.guild_id)
        await self.bot.update_queue_embed(self.guild_id)
        await interaction.response.send_message("✅ Queue has been cleared!", ephemeral=True)

    @discord.ui.button(label="Remove from Queue", emoji="👋", style=discord.ButtonStyle.secondary, row=3)
    async def remove_from_queue_btn(self, interaction: discord.Interaction, button):
        if not await check_senior_staff(interaction, self.bot):
            return
        if not self.selected_user:
            await interaction.response.send_message("⚠️ Select a player first!", ephemeral=True)
            return
        removed = await self.bot.remove_from_queue(self.guild_id, self.selected_user.id)
        if removed:
            await self.bot.update_queue_embed(self.guild_id)
            await interaction.response.send_message(
                f"✅ Removed {self.selected_user.mention} from the queue",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"⚠️ {self.selected_user.mention} was not in the queue",
                ephemeral=True
            )

    @discord.ui.button(label="◀ Admin Hub", style=discord.ButtonStyle.secondary, row=4)
    async def back_btn(self, interaction: discord.Interaction, button):
        embed = await build_admintools_hub_embed(self.bot, self.guild_id)
        view = AdminToolsHubView(self.bot, self.guild_id)
        await interaction.response.edit_message(embed=embed, view=view)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class SimpleSetEloModal(discord.ui.Modal, title="Set ELO"):
    """Simple modal - just enter the new ELO value. Queue type/position already selected."""

    def __init__(self, bot, guild_id, user, queue_type, position):
        super().__init__(custom_id="modal_simple_set_elo")
        self.bot = bot
        self.guild_id = guild_id
        self.target_user = user
        self.queue_type = queue_type
        self.position = position

    new_elo = discord.ui.TextInput(
        label="New ELO Value",
        placeholder="e.g., 800, 1000, 1200...",
        max_length=5
    )

    region_input = discord.ui.TextInput(
        label="Region (optional: NA, EU, Asia, OCE)",
        placeholder="Leave blank for player's current region",
        required=False,
        max_length=5
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            elo = int(self.new_elo.value.strip())
            if elo < 0 or elo > 5000:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("⚠️ ELO must be a number between 0 and 5000!", ephemeral=True)
            return

        # Parse region — default to player's current region if not specified
        region = self.region_input.value.strip() if self.region_input.value else None
        if region:
            region = region.upper() if region.upper() in ("NA", "EU", "OCE") else region.capitalize()
            if region not in ("NA", "EU", "Asia", "OCE"):
                await interaction.response.send_message("⚠️ Invalid region! Use: NA, EU, Asia, or OCE", ephemeral=True)
                return
        else:
            # Auto-detect player's current region
            region = await self.bot.db.get_player_region(self.guild_id, self.target_user.id)

        qt = self.queue_type
        pos = self.position
        config = await self.bot.db.get_config(self.guild_id)
        starting_elo = config["starting_elo"]

        if region:
            # Regional ELO set — also update global table to keep in sync
            if qt in ('2v2', '3v3'):
                current_elo = await self.bot.db.get_player_regional_elo_simple(self.guild_id, self.target_user.id, region, qt, starting_elo)
                await self.bot.db.set_player_regional_elo_simple(self.guild_id, self.target_user.id, region, qt, elo, starting_elo)
                await self.bot.db.set_player_elo_simple(self.guild_id, self.target_user.id, qt, elo)
                label = f"{qt} [{region}]"
            elif qt in ('highrank_2v2', 'highrank_3v3'):
                current_elo = await self.bot.db.get_player_elo_simple(self.guild_id, self.target_user.id, qt)
                await self.bot.db.set_player_elo_simple(self.guild_id, self.target_user.id, qt, elo)
                label = f"{qt} [{region}]"
            elif qt == 'highrank' and pos:
                current_elo = await self.bot.db.get_player_elo_highrank(self.guild_id, self.target_user.id, pos)
                await self.bot.db.set_player_elo_highrank(self.guild_id, self.target_user.id, pos, elo)
                label = f"HR {pos} [{region}]"
            elif pos:
                current_elo = await self.bot.db.get_player_regional_elo(self.guild_id, self.target_user.id, region, pos, starting_elo)
                await self.bot.db.set_player_regional_elo(self.guild_id, self.target_user.id, region, pos, elo, starting_elo)
                await self.bot.db.set_player_elo(self.guild_id, self.target_user.id, pos, elo)
                label = f"Queues {pos} [{region}]"
            else:
                await interaction.response.send_message("⚠️ Please select a queue type and position first!", ephemeral=True)
                return
        else:
            # No region found — global ELO set
            if qt in ('2v2', '3v3', 'highrank_2v2', 'highrank_3v3'):
                current_elo = await self.bot.db.get_player_elo_simple(self.guild_id, self.target_user.id, qt)
                await self.bot.db.set_player_elo_simple(self.guild_id, self.target_user.id, qt, elo)
                label = qt
            elif qt == 'highrank' and pos:
                current_elo = await self.bot.db.get_player_elo_highrank(self.guild_id, self.target_user.id, pos)
                await self.bot.db.set_player_elo_highrank(self.guild_id, self.target_user.id, pos, elo)
                label = f"HR {pos}"
            elif pos:
                current_elo = await self.bot.db.get_player_elo(self.guild_id, self.target_user.id, pos)
                await self.bot.db.set_player_elo(self.guild_id, self.target_user.id, pos, elo)
                label = f"Queues {pos}"
            else:
                await interaction.response.send_message("⚠️ Please select a queue type and position first!", ephemeral=True)
                return

        await self.bot.post_or_update_leaderboard(self.guild_id)
        await interaction.response.send_message(
            f"✅ Set {self.target_user.mention}'s **{label}** ELO: **{current_elo}** → **{elo}**",
            ephemeral=True
        )
        await self.bot.log_action(
            self.guild_id,
            "Admin: Set ELO",
            f"{interaction.user.mention} set {self.target_user.mention}'s **{label}** ELO: **{current_elo}** → **{elo}**",
            user=interaction.user, log_type="admin"
        )


class SimpleAdjustEloModal(discord.ui.Modal, title="Adjust ELO"):
    """Simple modal - just enter the amount. Queue type/position already selected."""

    def __init__(self, bot, guild_id, user, queue_type, position):
        super().__init__(custom_id="modal_simple_adjust_elo")
        self.bot = bot
        self.guild_id = guild_id
        self.target_user = user
        self.queue_type = queue_type
        self.position = position

    amount = discord.ui.TextInput(
        label="Amount (positive=add, negative=subtract)",
        placeholder="e.g., 50, -30, 100...",
        max_length=5
    )

    region_input = discord.ui.TextInput(
        label="Region (optional: NA, EU, Asia, OCE)",
        placeholder="Leave blank for player's current region",
        required=False,
        max_length=5
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            adj = int(self.amount.value.strip())
            if adj > 1000 or adj < -1000:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("⚠️ Amount must be between -1000 and 1000!", ephemeral=True)
            return

        # Parse region — default to player's current region if not specified
        region = self.region_input.value.strip() if self.region_input.value else None
        if region:
            region = region.upper() if region.upper() in ("NA", "EU", "OCE") else region.capitalize()
            if region not in ("NA", "EU", "Asia", "OCE"):
                await interaction.response.send_message("⚠️ Invalid region! Use: NA, EU, Asia, or OCE", ephemeral=True)
                return
        else:
            # Auto-detect player's current region
            region = await self.bot.db.get_player_region(self.guild_id, self.target_user.id)

        qt = self.queue_type
        pos = self.position
        config = await self.bot.db.get_config(self.guild_id)
        starting_elo = config["starting_elo"]

        if region:
            # Regional ELO adjust — also update global table to keep in sync
            if qt in ('2v2', '3v3'):
                old_elo = await self.bot.db.get_player_regional_elo_simple(self.guild_id, self.target_user.id, region, qt, starting_elo)
                new_elo_val = max(0, old_elo + adj)
                await self.bot.db.set_player_regional_elo_simple(self.guild_id, self.target_user.id, region, qt, new_elo_val, starting_elo)
                await self.bot.db.set_player_elo_simple(self.guild_id, self.target_user.id, qt, new_elo_val)
                label = f"{qt} [{region}]"
            elif qt in ('highrank_2v2', 'highrank_3v3'):
                old_elo = await self.bot.db.get_player_elo_simple(self.guild_id, self.target_user.id, qt)
                new_elo_val = max(0, old_elo + adj)
                await self.bot.db.set_player_elo_simple(self.guild_id, self.target_user.id, qt, new_elo_val)
                label = f"{qt} [{region}]"
            elif qt == 'highrank' and pos:
                old_elo = await self.bot.db.get_player_elo_highrank(self.guild_id, self.target_user.id, pos)
                new_elo_val = max(0, old_elo + adj)
                await self.bot.db.set_player_elo_highrank(self.guild_id, self.target_user.id, pos, new_elo_val)
                label = f"HR {pos} [{region}]"
            elif pos:
                old_elo = await self.bot.db.get_player_regional_elo(self.guild_id, self.target_user.id, region, pos, starting_elo)
                new_elo_val = max(0, old_elo + adj)
                await self.bot.db.set_player_regional_elo(self.guild_id, self.target_user.id, region, pos, new_elo_val, starting_elo)
                await self.bot.db.set_player_elo(self.guild_id, self.target_user.id, pos, new_elo_val)
                label = f"Queues {pos} [{region}]"
            else:
                await interaction.response.send_message("⚠️ Please select a queue type and position first!", ephemeral=True)
                return
        else:
            # No region found — global ELO adjust
            if qt in ('2v2', '3v3', 'highrank_2v2', 'highrank_3v3'):
                old_elo = await self.bot.db.get_player_elo_simple(self.guild_id, self.target_user.id, qt)
                new_elo_val = max(0, old_elo + adj)
                await self.bot.db.set_player_elo_simple(self.guild_id, self.target_user.id, qt, new_elo_val)
                label = qt
            elif qt == 'highrank' and pos:
                old_elo = await self.bot.db.get_player_elo_highrank(self.guild_id, self.target_user.id, pos)
                new_elo_val = max(0, old_elo + adj)
                await self.bot.db.set_player_elo_highrank(self.guild_id, self.target_user.id, pos, new_elo_val)
                label = f"HR {pos}"
            elif pos:
                old_elo, new_elo_val = await self.bot.db.adjust_player_elo(
                    self.guild_id, self.target_user.id, pos, adj
                )
                label = f"Queues {pos}"
            else:
                await interaction.response.send_message("⚠️ Please select a queue type and position first!", ephemeral=True)
                return

        await self.bot.post_or_update_leaderboard(self.guild_id)
        change_str = f"+{adj}" if adj > 0 else str(adj)
        await interaction.response.send_message(
            f"✅ Adjusted {self.target_user.mention}'s **{label}** ELO by **{change_str}**: **{old_elo}** → **{new_elo_val}**",
            ephemeral=True
        )
        await self.bot.log_action(
            self.guild_id,
            "Admin: Adjust ELO",
            f"{interaction.user.mention} adjusted {self.target_user.mention}'s **{label}** ELO by **{change_str}**: **{old_elo}** → **{new_elo_val}**",
            user=interaction.user, log_type="admin"
        )


# ── ADMIN: BLACKLIST TAB ──

async def build_admin_blacklist_embed(bot, guild_id):
    """Build the admin blacklist management embed."""
    blacklist = await bot.db.get_blacklist(guild_id)
    config = await bot.db.get_config(guild_id)

    embed = discord.Embed(
        title="🔧 Admin Tools — Blacklist",
        description=f"**{len(blacklist)}** user{'s' if len(blacklist) != 1 else ''} currently blacklisted",
        color=discord.Color.red() if blacklist else discord.Color.orange()
    )

    role_id = config.get("blacklist_role_id")
    role_text = "Auto-created 'Blacklisted'" if not role_id else f"<@&{role_id}>"
    embed.add_field(name="Blacklist Role", value=role_text, inline=False)

    if blacklist:
        entries = []
        for entry in blacklist[:5]:
            user_id = entry[0]
            reason = entry[2]
            expires_at = entry[4] if len(entry) > 4 else None
            user = bot.get_user(user_id)
            user_text = user.mention if user else f"User `{user_id}`"
            reason_text = reason or "No reason"
            expires_text = ""
            if expires_at:
                try:
                    exp_ts = int(datetime.fromisoformat(expires_at).timestamp())
                    expires_text = f" (expires <t:{exp_ts}:R>)"
                except Exception:
                    pass
            else:
                expires_text = " (permanent)"
            entries.append(f"• {user_text} — {reason_text}{expires_text}")
        text = "\n".join(entries)
        if len(blacklist) > 5:
            text += f"\n*...and {len(blacklist) - 5} more*"
        embed.add_field(name="Recent Entries", value=text, inline=False)
    else:
        embed.add_field(name="✨ All Clear", value="No users are blacklisted", inline=False)

    embed.set_footer(text="Select a user, then add/remove from blacklist")
    return embed


class AdminBlacklistView(discord.ui.View):
    """Blacklist management within admin tools."""

    def __init__(self, bot, guild_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.selected_user = None

    @discord.ui.select(
        cls=discord.ui.UserSelect,
        placeholder="👤 Select a user...",
        min_values=1, max_values=1, row=0
    )
    async def user_select(self, interaction: discord.Interaction, select):
        self.selected_user = select.values[0]
        reason = await self.bot.db.is_blacklisted(self.guild_id, self.selected_user.id)
        if reason is not None:
            status = f"🚫 **{self.selected_user.display_name}** is blacklisted — Reason: {reason or 'None'}"
        else:
            status = f"✅ **{self.selected_user.display_name}** is not blacklisted"
        await interaction.response.send_message(status, ephemeral=True)

    @discord.ui.button(label="Add to Blacklist", emoji="🚫", style=discord.ButtonStyle.danger, row=1)
    async def add_blacklist_btn(self, interaction: discord.Interaction, button):
        if not self.selected_user:
            await interaction.response.send_message("⚠️ Select a user first!", ephemeral=True)
            return
        existing = await self.bot.db.is_blacklisted(self.guild_id, self.selected_user.id)
        if existing is not None:
            await interaction.response.send_message(
                f"⚠️ {self.selected_user.mention} is already blacklisted!",
                ephemeral=True
            )
            return
        modal = BlacklistReasonModal(self.bot, self.guild_id, self.selected_user)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Remove", emoji="✅", style=discord.ButtonStyle.success, row=1)
    async def remove_blacklist_btn(self, interaction: discord.Interaction, button):
        if not self.selected_user:
            await interaction.response.send_message("⚠️ Select a user first!", ephemeral=True)
            return

        reason = await self.bot.db.is_blacklisted(self.guild_id, self.selected_user.id)
        if reason is None:
            member = interaction.guild.get_member(self.selected_user.id)
            if member:
                blacklist_role = await self.bot.get_blacklist_role(interaction.guild)
                if blacklist_role and blacklist_role in member.roles:
                    try:
                        await member.remove_roles(blacklist_role, reason=f"Unblacklisted by {interaction.user}")
                    except Exception:
                        pass
            await interaction.response.send_message(
                f"⚠️ {self.selected_user.mention} is not blacklisted!",
                ephemeral=True
            )
            return

        await self.bot.db.remove_from_blacklist(self.guild_id, self.selected_user.id)

        member = interaction.guild.get_member(self.selected_user.id)
        role_status = ""
        if member:
            blacklist_role = await self.bot.get_blacklist_role(interaction.guild)
            if blacklist_role and blacklist_role in member.roles:
                try:
                    await member.remove_roles(blacklist_role, reason=f"Unblacklisted by {interaction.user}")
                    role_status = "\n🏷️ Blacklisted role removed"
                except discord.Forbidden:
                    role_status = "\n⚠️ Could not remove role (missing permissions)"

        await interaction.response.send_message(
            f"✅ **{self.selected_user.display_name}** has been removed from the blacklist!{role_status}",
            ephemeral=True
        )
        await self.bot.log_action(
            self.guild_id,
            "Admin: Blacklist Remove",
            f"{interaction.user.mention} removed {self.selected_user.mention} from the blacklist",
            user=interaction.user, log_type="admin"
        )

    @discord.ui.button(label="View All", emoji="📋", style=discord.ButtonStyle.primary, row=1)
    async def view_all_btn(self, interaction: discord.Interaction, button):
        blacklist = await self.bot.db.get_blacklist(self.guild_id)

        embed = discord.Embed(
            title="🚫 Full Blacklist",
            description=f"Total: **{len(blacklist)}** user{'s' if len(blacklist) != 1 else ''}",
            color=discord.Color.red()
        )

        if blacklist:
            text = ""
            for entry in blacklist[:15]:
                user_id, by_id, reason, timestamp = entry[0], entry[1], entry[2], entry[3]
                expires_at = entry[4] if len(entry) > 4 else None
                user = self.bot.get_user(user_id)
                by_user = self.bot.get_user(by_id)
                user_text = user.mention if user else f"User `{user_id}`"
                by_text = by_user.name if by_user else f"User `{by_id}`"
                ts = ""
                try:
                    ts = f" <t:{int(datetime.fromisoformat(timestamp).timestamp())}:R>"
                except Exception:
                    pass
                expires_text = ""
                if expires_at:
                    try:
                        exp_ts = int(datetime.fromisoformat(expires_at).timestamp())
                        expires_text = f" | Expires <t:{exp_ts}:R>"
                    except Exception:
                        pass
                else:
                    expires_text = " | Permanent"
                text += f"• {user_text}\n  └ By: {by_text} | Reason: {reason or 'None'}{ts}{expires_text}\n"

            embed.add_field(name="Blacklisted Users", value=text[:1024], inline=False)
            if len(blacklist) > 15:
                embed.set_footer(text=f"Showing 15 of {len(blacklist)}")
        else:
            embed.add_field(name="Empty", value="No users are blacklisted", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.select(
        cls=discord.ui.RoleSelect,
        placeholder="🏷️ Set blacklist role...",
        min_values=0, max_values=1, row=2
    )
    async def blacklist_role_select(self, interaction: discord.Interaction, select):
        config = await self.bot.db.get_config(self.guild_id)
        if select.values:
            role = select.values[0]
            config["blacklist_role_id"] = role.id
            await self.bot.db.update_config(self.guild_id, config)
            await interaction.response.send_message(f"Blacklist role set to {role.mention}", ephemeral=True)
        else:
            config["blacklist_role_id"] = None
            await self.bot.db.update_config(self.guild_id, config)
            await interaction.response.send_message("Blacklist role reset to auto-created 'Blacklisted'", ephemeral=True)

    @discord.ui.button(label="◀ Admin Hub", style=discord.ButtonStyle.secondary, row=3)
    async def back_btn(self, interaction: discord.Interaction, button):
        embed = await build_admintools_hub_embed(self.bot, self.guild_id)
        view = AdminToolsHubView(self.bot, self.guild_id)
        await interaction.response.edit_message(embed=embed, view=view)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ── ADMIN: MATCHES TAB ──

async def build_admin_matches_embed(bot, guild_id):
    """Build the admin match management embed showing recent matches."""
    import json as _json
    matches = await bot.db.get_recent_matches_all(guild_id, limit=10)
    active_matches = await bot.db.get_active_matches(guild_id)

    embed = discord.Embed(
        title="🔧 Admin Tools — Matches",
        description=f"**{len(active_matches)}** active | Showing last 10 matches",
        color=discord.Color.orange()
    )

    if matches:
        text = ""
        for match in matches[:10]:
            match_id, t1_json, t2_json, s1, s2, ts, is_active, match_type = match
            team1 = _json.loads(t1_json)
            team2 = _json.loads(t2_json)

            status = "🟢 Active" if is_active else "⚫ Ended"

            # Determine result
            result_text = "No result"
            if s1 is not None and s2 is not None:
                if s1 > s2:
                    result_text = "Team 1 won"
                elif s2 > s1:
                    result_text = "Team 2 won"
                else:
                    result_text = "Tie"

            text += f"**#{match_id}** [{match_type}] {status} | {len(team1)}v{len(team2)} | {result_text}\n"

        embed.add_field(name="Recent Matches", value=text[:1024], inline=False)
    else:
        embed.add_field(name="No Matches", value="No matches found", inline=False)

    embed.add_field(
        name="📖 Actions",
        value=(
            "**Enter ID** — Type a match ID to manage it\n"
            "**Revert** — Undo a completed match result\n"
            "**Delete** — Permanently remove a match"
        ),
        inline=False
    )
    embed.set_footer(text="Use the buttons below to manage matches")
    return embed


class AdminMatchesView(discord.ui.View):
    """Match management within admin tools."""

    def __init__(self, bot, guild_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id

    @discord.ui.button(label="Manage Match by ID", emoji="🔍", style=discord.ButtonStyle.primary, row=0)
    async def manage_match_btn(self, interaction: discord.Interaction, button):
        modal = MatchIdInputModal(self.bot, self.guild_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Cancel Active Match", emoji="❌", style=discord.ButtonStyle.danger, row=0)
    async def cancel_active_btn(self, interaction: discord.Interaction, button):
        modal = CancelMatchIdModal(self.bot, self.guild_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Edit Match", emoji="✏️", style=discord.ButtonStyle.primary, row=0)
    async def edit_match_btn(self, interaction: discord.Interaction, button):
        modal = EditMatchIdModal(self.bot, self.guild_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Force Start", emoji="⚡", style=discord.ButtonStyle.success, row=1)
    async def force_start_btn(self, interaction: discord.Interaction, button):
        if not await check_senior_staff(interaction, self.bot):
            return
        modal = ForceStartModal(self.bot, self.guild_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, row=2)
    async def refresh_btn(self, interaction: discord.Interaction, button):
        embed = await build_admin_matches_embed(self.bot, self.guild_id)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="◀ Admin Hub", style=discord.ButtonStyle.secondary, row=2)
    async def back_btn(self, interaction: discord.Interaction, button):
        embed = await build_admintools_hub_embed(self.bot, self.guild_id)
        view = AdminToolsHubView(self.bot, self.guild_id)
        await interaction.response.edit_message(embed=embed, view=view)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class MatchIdInputModal(discord.ui.Modal, title="Manage Match"):
    """Enter a match ID to view and manage it."""

    def __init__(self, bot, guild_id):
        super().__init__(custom_id="modal_match_id_input")
        self.bot = bot
        self.guild_id = guild_id

    match_id_input = discord.ui.TextInput(
        label="Match ID",
        placeholder="Enter the match ID number",
        max_length=10,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        import json as _json
        try:
            match_id = int(self.match_id_input.value.strip())
        except ValueError:
            await interaction.response.send_message("⚠️ Invalid match ID!", ephemeral=True)
            return

        match = await self.bot.db.get_full_match(match_id, self.guild_id)
        if not match:
            await interaction.response.send_message(f"⚠️ Match #{match_id} not found!", ephemeral=True)
            return

        mid, t1_json, t2_json, s1, s2, ts, season_id, text_ch, voice_ch, is_active, match_type = match
        team1 = _json.loads(t1_json)
        team2 = _json.loads(t2_json)

        embed = discord.Embed(
            title=f"🏐 Match #{match_id} — {'Active' if is_active else 'Completed'}",
            color=discord.Color.green() if is_active else discord.Color.greyple()
        )
        embed.add_field(name="Type", value=match_type.upper(), inline=True)

        if s1 is not None and s2 is not None:
            if s1 > s2:
                embed.add_field(name="Result", value="Team 1 Won", inline=True)
            elif s2 > s1:
                embed.add_field(name="Result", value="Team 2 Won", inline=True)
            else:
                embed.add_field(name="Result", value="Tie", inline=True)
        else:
            embed.add_field(name="Result", value="Not reported", inline=True)

        # Show teams
        team1_text = ""
        for player_id, position in team1:
            user = self.bot.get_user(player_id)
            if match_type in ('2v2', '3v3'):
                team1_text += f"{user.mention if user else f'User {player_id}'}\n"
            else:
                team1_text += f"{user.mention if user else f'User {player_id}'} ({position})\n"

        team2_text = ""
        for player_id, position in team2:
            user = self.bot.get_user(player_id)
            if match_type in ('2v2', '3v3'):
                team2_text += f"{user.mention if user else f'User {player_id}'}\n"
            else:
                team2_text += f"{user.mention if user else f'User {player_id}'} ({position})\n"

        embed.add_field(name="🔴 Team 1", value=team1_text.strip() or "Empty", inline=True)
        embed.add_field(name="🔵 Team 2", value=team2_text.strip() or "Empty", inline=True)

        try:
            embed.add_field(name="Timestamp", value=f"<t:{int(datetime.fromisoformat(ts).timestamp())}:R>", inline=False)
        except Exception:
            pass

        view = MatchDetailView(self.bot, self.guild_id, match_id, is_active, s1 is not None)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class CancelMatchIdModal(discord.ui.Modal, title="Cancel Active Match"):
    """Enter a match ID to cancel it."""

    def __init__(self, bot, guild_id):
        super().__init__(custom_id="modal_cancel_match")
        self.bot = bot
        self.guild_id = guild_id

    match_id_input = discord.ui.TextInput(
        label="Match ID",
        placeholder="Enter the match ID to cancel",
        max_length=10,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            match_id = int(self.match_id_input.value.strip())
        except ValueError:
            await interaction.response.send_message("⚠️ Invalid match ID!", ephemeral=True)
            return

        match = await self.bot.db.get_full_match(match_id, self.guild_id)
        if not match:
            await interaction.response.send_message(f"⚠️ Match #{match_id} not found!", ephemeral=True)
            return

        is_active = match[9]
        if not is_active:
            await interaction.response.send_message(f"⚠️ Match #{match_id} is already ended!", ephemeral=True)
            return

        await self.bot.db.set_match_inactive(match_id)

        # Clean up channels
        text_ch_id, voice_ch_id = match[7], match[8]
        for ch_id in [text_ch_id, voice_ch_id]:
            if ch_id:
                ch = self.bot.get_channel(ch_id)
                if ch:
                    try:
                        await ch.delete(reason=f"Match #{match_id} cancelled by admin")
                    except Exception:
                        pass

        if match_id in self.bot.ready_check_views:
            del self.bot.ready_check_views[match_id]

        await interaction.response.send_message(f"✅ Match #{match_id} has been cancelled!", ephemeral=True)


class MatchDetailView(discord.ui.View):
    """Actions for a specific match (report, revert, delete, change winner)."""

    def __init__(self, bot, guild_id, match_id, is_active, has_result):
        super().__init__(timeout=120)
        self.bot = bot
        self.guild_id = guild_id
        self.match_id = match_id

        # Conditionally show buttons
        if not has_result:
            # No result yet — can report winner (whether active or not)
            self.report_t1_btn.disabled = False
            self.report_t2_btn.disabled = False
            self.revert_btn.disabled = True
        else:
            # Has result — can revert or change winner
            self.report_t1_btn.label = "Change → Team 1"
            self.report_t2_btn.label = "Change → Team 2"
            self.revert_btn.disabled = False

    @discord.ui.button(label="Report Team 1 Win", emoji="🔴", style=discord.ButtonStyle.danger, row=0)
    async def report_t1_btn(self, interaction: discord.Interaction, button):
        await self._report_or_change_winner(interaction, 1)

    @discord.ui.button(label="Report Team 2 Win", emoji="🔵", style=discord.ButtonStyle.primary, row=0)
    async def report_t2_btn(self, interaction: discord.Interaction, button):
        await self._report_or_change_winner(interaction, 2)

    @discord.ui.button(label="Revert Result", emoji="🔄", style=discord.ButtonStyle.secondary, row=1)
    async def revert_btn(self, interaction: discord.Interaction, button):
        success, message = await self.bot.db.revert_match_result(self.match_id, self.guild_id)
        if success:
            await self.bot.post_or_update_leaderboard(self.guild_id)
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(
                content=f"✅ Match #{self.match_id} result reverted! {message}",
                embed=None,
                view=self
            )
        else:
            await interaction.response.send_message(f"❌ {message}", ephemeral=True)

    @discord.ui.button(label="Delete Match", emoji="🗑️", style=discord.ButtonStyle.danger, row=1)
    async def delete_btn(self, interaction: discord.Interaction, button):
        view = DeleteMatchConfirmView(self.bot, self.guild_id, self.match_id)
        await interaction.response.send_message(
            f"⚠️ Are you sure you want to **permanently delete** Match #{self.match_id}?\n"
            "This will NOT revert ELO changes. Use 'Revert Result' first if needed.",
            view=view,
            ephemeral=True
        )

    async def _report_or_change_winner(self, interaction, winning_team):
        """Report a winner or change the winner of an existing match."""
        import json as _json

        # Defer immediately to avoid Discord's 3-second interaction timeout
        await interaction.response.defer()

        match = await self.bot.db.get_full_match(self.match_id, self.guild_id)
        if not match:
            await interaction.followup.send("⚠️ Match not found!", ephemeral=True)
            return

        s1, s2 = match[3], match[4]
        has_existing_result = s1 is not None and s2 is not None

        # If changing winner, first revert the old result
        if has_existing_result:
            success, msg = await self.bot.db.revert_match_result(self.match_id, self.guild_id)
            if not success:
                await interaction.followup.send(f"❌ Could not revert old result: {msg}", ephemeral=True)
                return

        # Now apply the new result
        team1 = _json.loads(match[1])
        team2 = _json.loads(match[2])
        match_type = match[10]

        config = await self.bot.db.get_config(self.guild_id)
        k_factor = config["k_factor"]
        starting_elo = config["starting_elo"]

        # Use high rank starting ELO for high rank matches
        if match_type and match_type.startswith("highrank"):
            starting_elo = config.get("high_rank_starting_elo", starting_elo)

        winners = team1 if winning_team == 1 else team2
        losers = team2 if winning_team == 1 else team1

        # Get current ELOs
        current_elos = {}
        for player_data in winners + losers:
            pid, pos = player_data[0], player_data[1]
            if match_type in ('2v2', '3v3', 'highrank_2v2', 'highrank_3v3'):
                elo = await self.bot.db.get_player_elo_simple(self.guild_id, pid, match_type)
            elif match_type == 'highrank':
                elo = await self.bot.db.get_player_elo_highrank(self.guild_id, pid, pos)
            else:
                elo = await self.bot.db.get_player_elo(self.guild_id, pid, pos)
            current_elos[(pid, pos)] = elo

        # Calculate and apply ELO changes for winners
        elo_changes = []
        for w_data in winners:
            w_id, w_pos = w_data[0], w_data[1]
            total_change = 0
            for l_data in losers:
                l_id, l_pos = l_data[0], l_data[1]
                w_elo = current_elos[(w_id, w_pos)]
                l_elo = current_elos[(l_id, l_pos)]
                wc, lc = self.bot.calculate_elo_change(w_elo, l_elo, k_factor)
                total_change += wc / len(losers)

            if match_type in ('2v2', '3v3', 'highrank_2v2', 'highrank_3v3'):
                await self.bot.db.update_player_elo_simple(self.guild_id, w_id, match_type, int(total_change), True, starting_elo)
            elif match_type == 'highrank':
                await self.bot.db.update_player_elo_highrank(self.guild_id, w_id, w_pos, int(total_change), True, starting_elo)
            else:
                await self.bot.db.update_player_elo(self.guild_id, w_id, w_pos, int(total_change), True, starting_elo)

            old_elo = current_elos[(w_id, w_pos)]
            new_elo = old_elo + int(total_change)
            elo_changes.append((w_id, w_pos, int(total_change), old_elo, new_elo, True))

            # Record ELO history for stats card graph
            await self.bot.db.record_elo_history(
                self.guild_id, w_id, self.match_id,
                match_type or '6v6', w_pos,
                old_elo, new_elo, int(total_change), True
            )

        # Calculate and apply ELO changes for losers
        for l_data in losers:
            l_id, l_pos = l_data[0], l_data[1]
            total_change = 0
            for w_data in winners:
                w_id, w_pos = w_data[0], w_data[1]
                w_elo = current_elos[(w_id, w_pos)]
                l_elo = current_elos[(l_id, l_pos)]
                wc, lc = self.bot.calculate_elo_change(w_elo, l_elo, k_factor)
                total_change += lc / len(winners)

            if match_type in ('2v2', '3v3', 'highrank_2v2', 'highrank_3v3'):
                await self.bot.db.update_player_elo_simple(self.guild_id, l_id, match_type, int(total_change), False, starting_elo)
            elif match_type == 'highrank':
                await self.bot.db.update_player_elo_highrank(self.guild_id, l_id, l_pos, int(total_change), False, starting_elo)
            else:
                await self.bot.db.update_player_elo(self.guild_id, l_id, l_pos, int(total_change), False, starting_elo)

            old_elo = current_elos[(l_id, l_pos)]
            new_elo = old_elo + int(total_change)
            elo_changes.append((l_id, l_pos, int(total_change), old_elo, new_elo, False))

            # Record ELO history for stats card graph
            await self.bot.db.record_elo_history(
                self.guild_id, l_id, self.match_id,
                match_type or '6v6', l_pos,
                old_elo, new_elo, int(total_change), False
            )

        # Set scores: 1-0 to indicate winner (no actual score tracking)
        if winning_team == 1:
            t1_score, t2_score = 1, 0
        else:
            t1_score, t2_score = 0, 1
        await self.bot.db.update_match_score(self.match_id, t1_score, t2_score)
        await self.bot.db.set_match_inactive(self.match_id)

        await self.bot.post_or_update_leaderboard(self.guild_id)

        # DM each player their match result
        guild = interaction.guild
        guild_name = guild.name if guild else "the server"
        for user_id, position, change, old_elo, new_elo, won in elo_changes:
            try:
                user = self.bot.get_user(user_id)
                if not user:
                    continue

                result_str = "Won" if won else "Lost"
                result_emoji = "🏆" if won else "💔"

                queue_display = match_type.upper() if match_type else "QUEUES"
                if match_type == 'highrank':
                    queue_display = "High Rank"
                elif match_type == 'highrank_2v2':
                    queue_display = "High Rank 2v2"
                elif match_type == 'highrank_3v3':
                    queue_display = "High Rank 3v3"

                if match_type in ('2v2', '3v3', 'highrank_2v2', 'highrank_3v3'):
                    rating_line = f"**MMR:** {old_elo} → {new_elo} ({format_elo_change(change)})"
                else:
                    rating_line = f"**{position}:** {old_elo} → {new_elo} ({format_elo_change(change)})"

                dm_embed = discord.Embed(
                    title=f"{result_emoji} Match #{self.match_id} — {result_str}!",
                    description=(
                        f"Your **{queue_display}** match in **{guild_name}** has ended.\n\n"
                        f"{rating_line}"
                    ),
                    color=discord.Color.green() if won else discord.Color.red()
                )
                await user.send(embed=dm_embed)
            except (discord.Forbidden, discord.HTTPException):
                pass
            except Exception:
                pass

        action = "Changed winner to" if has_existing_result else "Reported"
        for item in self.children:
            item.disabled = True
        await interaction.edit_original_response(
            content=f"✅ {action} **Team {winning_team}** for Match #{self.match_id}!",
            embed=None,
            view=self
        )


class DeleteMatchConfirmView(discord.ui.View):
    """Confirmation for deleting a match."""

    def __init__(self, bot, guild_id, match_id):
        super().__init__(timeout=30)
        self.bot = bot
        self.guild_id = guild_id
        self.match_id = match_id

    @discord.ui.button(label="Yes, Delete Match", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button):
        await self.bot.db.delete_match(self.match_id, self.guild_id)
        await interaction.response.edit_message(
            content=f"✅ Match #{self.match_id} has been permanently deleted.",
            view=None
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button):
        await interaction.response.edit_message(content="Cancelled.", view=None)


# ── ADMIN: MATCH EDIT (Add/Remove/Swap players) ──

class EditMatchIdModal(discord.ui.Modal, title="Edit Match"):
    """Enter a match ID to edit its players."""

    def __init__(self, bot, guild_id):
        super().__init__(custom_id="modal_edit_match_id")
        self.bot = bot
        self.guild_id = guild_id

    match_id_input = discord.ui.TextInput(
        label="Match ID",
        placeholder="Enter the match ID to edit",
        max_length=10,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        import json as _json
        try:
            match_id = int(self.match_id_input.value.strip())
        except ValueError:
            await interaction.response.send_message("Invalid match ID!", ephemeral=True)
            return

        match = await self.bot.db.get_full_match(match_id, self.guild_id)
        if not match:
            await interaction.response.send_message(f"Match #{match_id} not found!", ephemeral=True)
            return

        mid, t1_json, t2_json, s1, s2, ts, season_id, text_ch, voice_ch, is_active, match_type = match
        team1 = _json.loads(t1_json)
        team2 = _json.loads(t2_json)

        # Get match region for 5v5 handling
        match_region = await self.bot.db.get_match_region(match_id)
        config = await self.bot.db.get_config(self.guild_id)
        match_is_5v5 = is_5v5_region(config, match_region) if match_region else False

        embed = discord.Embed(
            title=f"Edit Match #{match_id} [{match_type}]",
            description="Use the buttons below to add, remove, or swap players.",
            color=discord.Color.orange()
        )

        team1_text = ""
        for player_id, position in team1:
            user = self.bot.get_user(player_id)
            name = user.mention if user else f"User {player_id}"
            team1_text += f"{name} ({position})\n" if match_type == '6v6' else f"{name}\n"

        team2_text = ""
        for player_id, position in team2:
            user = self.bot.get_user(player_id)
            name = user.mention if user else f"User {player_id}"
            team2_text += f"{name} ({position})\n" if match_type == '6v6' else f"{name}\n"

        embed.add_field(name="Team 1", value=team1_text.strip() or "Empty", inline=True)
        embed.add_field(name="Team 2", value=team2_text.strip() or "Empty", inline=True)

        view = AdminMatchEditView(self.bot, self.guild_id, match_id, team1, team2, match_type, match_is_5v5=match_is_5v5)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class AdminMatchEditView(discord.ui.View):
    """View for editing match players with user-friendly dropdowns."""

    def __init__(self, bot, guild_id, match_id, team1, team2, match_type='6v6', match_is_5v5=False):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.match_id = match_id
        self.team1 = team1
        self.team2 = team2
        self.match_type = match_type
        self.match_is_5v5 = match_is_5v5
        self.selected_user = None
        self.selected_team = "1"
        self.selected_position = "Player" if match_type in ('2v2', '3v3') else None

        # For 2v2/3v3: only show team selection (no positions)
        if match_type in ('2v2', '3v3'):
            self.team_position_select.options = [
                discord.SelectOption(label="Team 1", value="1", emoji="🔴"),
                discord.SelectOption(label="Team 2", value="2", emoji="🔵"),
            ]
            self.team_position_select.placeholder = "Select Team..."
            self.remove_item(self.change_position_btn)
        elif match_is_5v5:
            # For 5v5 region matches: remove Libero from position options
            self.team_position_select.options = [
                discord.SelectOption(label="Team 1", value="1", emoji="\U0001f534"),
                discord.SelectOption(label="Team 2", value="2", emoji="\U0001f535"),
                discord.SelectOption(label="Team 1 \u2014 Defense Specialist", value="1_Defense Specialist", emoji="\U0001f6e1\ufe0f"),
                discord.SelectOption(label="Team 1 \u2014 Front Spiker", value="1_Front Spiker", emoji="\u26a1"),
                discord.SelectOption(label="Team 1 \u2014 Setter", value="1_Setter", emoji="\U0001f3d0"),
                discord.SelectOption(label="Team 2 \u2014 Defense Specialist", value="2_Defense Specialist", emoji="\U0001f6e1\ufe0f"),
                discord.SelectOption(label="Team 2 \u2014 Front Spiker", value="2_Front Spiker", emoji="\u26a1"),
                discord.SelectOption(label="Team 2 \u2014 Setter", value="2_Setter", emoji="\U0001f3d0"),
            ]

    async def _refresh_match_data(self):
        """Re-read match data from DB."""
        import json as _json
        match = await self.bot.db.get_full_match(self.match_id, self.guild_id)
        if match:
            self.team1 = _json.loads(match[1])
            self.team2 = _json.loads(match[2])

    async def _build_embed(self):
        """Build the current match edit embed."""
        if self.match_type in ('2v2', '3v3'):
            desc = (
                "**1.** Select a user with the dropdown\n"
                "**2.** Pick a team\n"
                "**3.** Use the action buttons below"
            )
        else:
            desc = (
                "**1.** Select a user with the dropdown\n"
                "**2.** Pick a team and position\n"
                "**3.** Use the action buttons below"
            )
        embed = discord.Embed(
            title=f"✏️ Edit Match #{self.match_id} [{self.match_type.upper()}]",
            description=desc,
            color=discord.Color.orange()
        )

        team1_text = ""
        for player_id, position in self.team1:
            user = self.bot.get_user(player_id)
            name = user.mention if user else f"User {player_id}"
            if self.match_type in ('2v2', '3v3'):
                team1_text += f"{name}\n"
            else:
                team1_text += f"{name} ({position})\n"

        team2_text = ""
        for player_id, position in self.team2:
            user = self.bot.get_user(player_id)
            name = user.mention if user else f"User {player_id}"
            if self.match_type in ('2v2', '3v3'):
                team2_text += f"{name}\n"
            else:
                team2_text += f"{name} ({position})\n"

        embed.add_field(name="🔴 Team 1", value=team1_text.strip() or "Empty", inline=True)
        embed.add_field(name="🔵 Team 2", value=team2_text.strip() or "Empty", inline=True)

        # Show current selection
        sel_parts = []
        if self.selected_user:
            sel_parts.append(f"**User:** {self.selected_user.mention}")
        sel_parts.append(f"**Team:** {self.selected_team}")
        if self.selected_position and self.match_type not in ('2v2', '3v3'):
            sel_parts.append(f"**Position:** {self.selected_position}")
        embed.add_field(name="🎯 Current Selection", value="\n".join(sel_parts), inline=False)

        return embed

    @discord.ui.select(
        cls=discord.ui.UserSelect,
        placeholder="👤 Select a substitute...",
        min_values=1, max_values=1, row=0
    )
    async def user_select(self, interaction: discord.Interaction, select):
        self.selected_user = select.values[0]
        await interaction.response.send_message(
            f"Selected **{self.selected_user.display_name}**",
            ephemeral=True
        )

    @discord.ui.select(
        placeholder="Team & Position...",
        options=[
            discord.SelectOption(label="Team 1", value="1", emoji="🔴"),
            discord.SelectOption(label="Team 2", value="2", emoji="🔵"),
            discord.SelectOption(label="Team 1 — Defense Specialist", value="1_Defense Specialist", emoji="🛡️"),
            discord.SelectOption(label="Team 1 — Front Spiker", value="1_Front Spiker", emoji="⚡"),
            discord.SelectOption(label="Team 1 — Setter", value="1_Setter", emoji="🏐"),
            discord.SelectOption(label="Team 1 — Libero", value="1_Libero", emoji="🎯"),
            discord.SelectOption(label="Team 2 — Defense Specialist", value="2_Defense Specialist", emoji="🛡️"),
            discord.SelectOption(label="Team 2 — Front Spiker", value="2_Front Spiker", emoji="⚡"),
            discord.SelectOption(label="Team 2 — Setter", value="2_Setter", emoji="🏐"),
            discord.SelectOption(label="Team 2 — Libero", value="2_Libero", emoji="🎯"),
        ],
        row=1
    )
    async def team_position_select(self, interaction: discord.Interaction, select):
        value = select.values[0]
        if "_" in value:
            parts = value.split("_", 1)
            self.selected_team = parts[0]
            self.selected_position = parts[1]
        else:
            self.selected_team = value
            if self.match_type in ('2v2', '3v3'):
                self.selected_position = "Player"
        label = f"Team {self.selected_team}"
        if self.selected_position and self.match_type not in ('2v2', '3v3'):
            label += f" — {self.selected_position}"
        await interaction.response.send_message(f"Selected **{label}**", ephemeral=True)

    @discord.ui.button(label="Add to Match", emoji="➕", style=discord.ButtonStyle.success, row=2)
    async def add_player_btn(self, interaction: discord.Interaction, button):
        import json as _json

        if not self.selected_user:
            await interaction.response.send_message("⚠️ Select a player first!", ephemeral=True)
            return

        position = self.selected_position or "Player"
        user_id = self.selected_user.id

        # Check if already in the match
        await self._refresh_match_data()
        all_ids = [p[0] for p in self.team1 + self.team2]
        if user_id in all_ids:
            await interaction.response.send_message(
                f"⚠️ {self.selected_user.mention} is already in this match!",
                ephemeral=True
            )
            return

        new_entry = [user_id, position]
        if self.selected_team == '1':
            self.team1.append(new_entry)
        else:
            self.team2.append(new_entry)

        await self.bot.db.db.execute(
            'UPDATE matches SET team1_players = ?, team2_players = ? WHERE id = ? AND guild_id = ?',
            (_json.dumps(self.team1), _json.dumps(self.team2), self.match_id, self.guild_id)
        )
        await self.bot.db.db.commit()

        # Grant channel permissions
        match = await self.bot.db.get_full_match(self.match_id, self.guild_id)
        if match:
            text_ch_id, voice_ch_id = match[7], match[8]
            member = interaction.guild.get_member(user_id)
            if member:
                if text_ch_id:
                    channel = self.bot.get_channel(text_ch_id)
                    if channel:
                        try:
                            await channel.set_permissions(member, view_channel=True, send_messages=True)
                        except Exception:
                            pass
                if voice_ch_id:
                    vc = self.bot.get_channel(voice_ch_id)
                    if vc:
                        try:
                            await vc.set_permissions(member, view_channel=True, connect=True)
                        except Exception:
                            pass

        embed = await self._build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Remove from Match", emoji="➖", style=discord.ButtonStyle.danger, row=2)
    async def remove_player_btn(self, interaction: discord.Interaction, button):
        import json as _json

        if not self.selected_user:
            await interaction.response.send_message("⚠️ Select a player first!", ephemeral=True)
            return

        await self._refresh_match_data()
        user_id = self.selected_user.id

        found = False
        self.team1 = [p for p in self.team1 if p[0] != user_id or not (found := True) and False]
        if not found:
            old_len = len(self.team2)
            self.team2 = [p for p in self.team2 if p[0] != user_id]
            found = len(self.team2) < old_len
        else:
            # Re-do properly since the walrus trick above is tricky
            pass

        # Do it cleanly
        await self._refresh_match_data()
        t1_new = [p for p in self.team1 if p[0] != user_id]
        t2_new = [p for p in self.team2 if p[0] != user_id]
        found = (len(t1_new) < len(self.team1)) or (len(t2_new) < len(self.team2))
        self.team1 = t1_new
        self.team2 = t2_new

        if not found:
            await interaction.response.send_message(
                f"⚠️ {self.selected_user.mention} is not in this match!",
                ephemeral=True
            )
            return

        await self.bot.db.db.execute(
            'UPDATE matches SET team1_players = ?, team2_players = ? WHERE id = ? AND guild_id = ?',
            (_json.dumps(self.team1), _json.dumps(self.team2), self.match_id, self.guild_id)
        )
        await self.bot.db.db.commit()

        # Remove channel permissions
        match = await self.bot.db.get_full_match(self.match_id, self.guild_id)
        if match:
            text_ch_id, voice_ch_id = match[7], match[8]
            member = interaction.guild.get_member(user_id)
            if member:
                for ch_id in [text_ch_id, voice_ch_id]:
                    if ch_id:
                        ch = self.bot.get_channel(ch_id)
                        if ch:
                            try:
                                await ch.set_permissions(member, overwrite=None)
                            except Exception:
                                pass

        embed = await self._build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def _update_result_channel_embed(self, interaction, match, winning_team, elo_changes):
        """Update the result embed in the results channel after admin adjustment."""
        import json as _json
        from datetime import datetime as _datetime

        config = await self.bot.db.get_config(self.guild_id)
        results_channel_id = config.get("results_channel")
        if not results_channel_id:
            return

        channel = self.bot.get_channel(results_channel_id)
        if not channel:
            return

        result_message_id = await self.bot.db.get_result_message_id(self.match_id, self.guild_id)
        if not result_message_id:
            return

        try:
            result_msg = await channel.fetch_message(result_message_id)
        except (discord.NotFound, discord.HTTPException):
            return

        match_type = match[10]
        team1 = _json.loads(match[1])
        team2 = _json.loads(match[2])

        if winning_team == 0:
            # Tie
            result_embed = discord.Embed(
                title="🤝 Match Result — Tie (Adjusted)",
                description=f"Match #{self.match_id}",
                color=discord.Color.light_grey(),
                timestamp=_datetime.utcnow()
            )
            result_embed.add_field(name="Result", value="**Tie — No ELO changes**", inline=False)
        else:
            result_embed = discord.Embed(
                title="🏆 Match Result (Adjusted)",
                description=f"Match #{self.match_id}",
                color=discord.Color.gold(),
                timestamp=_datetime.utcnow()
            )

            team1_text = ""
            team2_text = ""
            winners_set = set(p[0] for p in (team1 if winning_team == 1 else team2))

            for user_id, position in team1:
                user = self.bot.get_user(user_id)
                pos_text = f" ({position})" if match_type not in ('2v2', '3v3', 'highrank_2v2', 'highrank_3v3') else ""
                elo_info = next((e for e in elo_changes if e[0] == user_id and e[1] == position), None)
                if elo_info:
                    _, _, change, old_elo, new_elo = elo_info
                    sign = "+" if change >= 0 else ""
                    team1_text += f"{user.mention if user else f'User {user_id}'}{pos_text}: **{old_elo}** → **{new_elo}** ({sign}{change})\n"
                else:
                    team1_text += f"{user.mention if user else f'User {user_id}'}{pos_text}\n"

            for user_id, position in team2:
                user = self.bot.get_user(user_id)
                pos_text = f" ({position})" if match_type not in ('2v2', '3v3', 'highrank_2v2', 'highrank_3v3') else ""
                elo_info = next((e for e in elo_changes if e[0] == user_id and e[1] == position), None)
                if elo_info:
                    _, _, change, old_elo, new_elo = elo_info
                    sign = "+" if change >= 0 else ""
                    team2_text += f"{user.mention if user else f'User {user_id}'}{pos_text}: **{old_elo}** → **{new_elo}** ({sign}{change})\n"
                else:
                    team2_text += f"{user.mention if user else f'User {user_id}'}{pos_text}\n"

            result_embed.add_field(
                name=f"{'🏆 ' if winning_team == 1 else ''}🔴 Team 1",
                value=team1_text.strip() or "—",
                inline=True
            )
            result_embed.add_field(
                name=f"{'🏆 ' if winning_team == 2 else ''}🔵 Team 2",
                value=team2_text.strip() or "—",
                inline=True
            )

        result_embed.set_footer(text="🔧 Adjusted by admin")

        try:
            await result_msg.edit(embed=result_embed)
        except discord.HTTPException:
            pass

    async def _recalibrate_concluded_match(self, interaction):
        """If the match has a concluded result, revert ELO, re-apply with updated teams."""
        import json as _json

        match = await self.bot.db.get_full_match(self.match_id, self.guild_id)
        if not match:
            return
        s1, s2 = match[3], match[4]
        is_active = match[9]

        # Only recalibrate if match has a recorded result
        if s1 is None or s2 is None:
            return

        # Determine which team won
        if s1 > s2:
            winning_team = 1
        elif s2 > s1:
            winning_team = 2
        else:
            # Tie — revert old result (game counts only), re-set scores
            success, msg = await self.bot.db.revert_match_result(self.match_id, self.guild_id)
            if success:
                await self.bot.db.update_match_score(self.match_id, s1, s2)
                await self.bot.db.set_match_inactive(self.match_id)
                # Update result embed in results channel
                await self._update_result_channel_embed(interaction, match, winning_team=0, elo_changes=[])
            return

        # Revert old result
        success, msg = await self.bot.db.revert_match_result(self.match_id, self.guild_id)
        if not success:
            return

        # Re-read the updated teams
        match = await self.bot.db.get_full_match(self.match_id, self.guild_id)
        team1 = _json.loads(match[1])
        team2 = _json.loads(match[2])
        match_type = match[10]

        config = await self.bot.db.get_config(self.guild_id)
        k_factor = config["k_factor"]
        starting_elo = config["starting_elo"]

        if match_type and match_type.startswith("highrank"):
            starting_elo = config.get("high_rank_starting_elo", starting_elo)

        winners = team1 if winning_team == 1 else team2
        losers = team2 if winning_team == 1 else team1

        # Get current ELOs
        current_elos = {}
        for player_data in winners + losers:
            pid, pos = player_data[0], player_data[1]
            if match_type in ('2v2', '3v3', 'highrank_2v2', 'highrank_3v3'):
                elo = await self.bot.db.get_player_elo_simple(self.guild_id, pid, match_type)
            elif match_type == 'highrank':
                elo = await self.bot.db.get_player_elo_highrank(self.guild_id, pid, pos)
            else:
                elo = await self.bot.db.get_player_elo(self.guild_id, pid, pos)
            current_elos[(pid, pos)] = elo

        # Track ELO changes for result embed update
        elo_changes = []

        # Apply ELO changes for winners
        for w_data in winners:
            w_id, w_pos = w_data[0], w_data[1]
            total_change = 0
            for l_data in losers:
                l_id, l_pos = l_data[0], l_data[1]
                w_elo = current_elos[(w_id, w_pos)]
                l_elo = current_elos[(l_id, l_pos)]
                wc, lc = self.bot.calculate_elo_change(w_elo, l_elo, k_factor)
                total_change += wc / len(losers)
            if match_type in ('2v2', '3v3', 'highrank_2v2', 'highrank_3v3'):
                await self.bot.db.update_player_elo_simple(self.guild_id, w_id, match_type, int(total_change), True, starting_elo)
            elif match_type == 'highrank':
                await self.bot.db.update_player_elo_highrank(self.guild_id, w_id, w_pos, int(total_change), True, starting_elo)
            else:
                await self.bot.db.update_player_elo(self.guild_id, w_id, w_pos, int(total_change), True, starting_elo)
            old_elo = current_elos[(w_id, w_pos)]
            new_elo = old_elo + int(total_change)
            elo_changes.append((w_id, w_pos, int(total_change), old_elo, new_elo))
            await self.bot.db.record_elo_history(self.guild_id, w_id, self.match_id, match_type or '6v6', w_pos, old_elo, new_elo, int(total_change), True)

        # Apply ELO changes for losers
        for l_data in losers:
            l_id, l_pos = l_data[0], l_data[1]
            total_change = 0
            for w_data in winners:
                w_id, w_pos = w_data[0], w_data[1]
                w_elo = current_elos[(w_id, w_pos)]
                l_elo = current_elos[(l_id, l_pos)]
                wc, lc = self.bot.calculate_elo_change(w_elo, l_elo, k_factor)
                total_change += lc / len(winners)
            if match_type in ('2v2', '3v3', 'highrank_2v2', 'highrank_3v3'):
                await self.bot.db.update_player_elo_simple(self.guild_id, l_id, match_type, int(total_change), False, starting_elo)
            elif match_type == 'highrank':
                await self.bot.db.update_player_elo_highrank(self.guild_id, l_id, l_pos, int(total_change), False, starting_elo)
            else:
                await self.bot.db.update_player_elo(self.guild_id, l_id, l_pos, int(total_change), False, starting_elo)
            old_elo = current_elos[(l_id, l_pos)]
            new_elo = old_elo + int(total_change)
            elo_changes.append((l_id, l_pos, int(total_change), old_elo, new_elo))
            await self.bot.db.record_elo_history(self.guild_id, l_id, self.match_id, match_type or '6v6', l_pos, old_elo, new_elo, int(total_change), False)

        # Re-set the scores
        await self.bot.db.update_match_score(self.match_id, s1, s2)
        await self.bot.db.set_match_inactive(self.match_id)

        # Update result embed in results channel
        await self._update_result_channel_embed(interaction, match, winning_team, elo_changes)

    @discord.ui.button(label="Swap to Other Team", emoji="🔄", style=discord.ButtonStyle.primary, row=2)
    async def swap_player_btn(self, interaction: discord.Interaction, button):
        """Move the selected player to the other team (keeps their position)."""
        import json as _json

        if not self.selected_user:
            await interaction.response.send_message("⚠️ Select a player first!", ephemeral=True)
            return

        await self._refresh_match_data()
        user_id = self.selected_user.id

        # Find which team the player is on
        from_team = None
        entry = None
        entry_idx = None
        for i, p in enumerate(self.team1):
            if p[0] == user_id:
                from_team = 1
                entry = p
                entry_idx = i
                break
        if from_team is None:
            for i, p in enumerate(self.team2):
                if p[0] == user_id:
                    from_team = 2
                    entry = p
                    entry_idx = i
                    break

        if from_team is None:
            await interaction.response.send_message(
                f"⚠️ {self.selected_user.mention} is not in this match! Use 'Add to Match' instead.",
                ephemeral=True
            )
            return

        # Move to the other team
        if from_team == 1:
            self.team1.pop(entry_idx)
            self.team2.append(entry)
        else:
            self.team2.pop(entry_idx)
            self.team1.append(entry)

        await self.bot.db.db.execute(
            'UPDATE matches SET team1_players = ?, team2_players = ? WHERE id = ? AND guild_id = ?',
            (_json.dumps(self.team1), _json.dumps(self.team2), self.match_id, self.guild_id)
        )
        await self.bot.db.db.commit()

        # Recalibrate ELO if match was already concluded
        await self._recalibrate_concluded_match(interaction)

        to_team = 2 if from_team == 1 else 1
        embed = await self._build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Change Position", emoji="🎯", style=discord.ButtonStyle.secondary, row=3)
    async def change_position_btn(self, interaction: discord.Interaction, button):
        """Change the position of the selected player in the match."""
        import json as _json

        if self.match_type in ('2v2', '3v3'):
            await interaction.response.send_message("⚠️ Positions don't apply to 2v2/3v3!", ephemeral=True)
            return

        if not self.selected_user:
            await interaction.response.send_message("⚠️ Select a player first!", ephemeral=True)
            return

        if not self.selected_position:
            await interaction.response.send_message(
                "⚠️ Select a position from the Team & Position dropdown first!",
                ephemeral=True
            )
            return

        await self._refresh_match_data()
        user_id = self.selected_user.id
        new_position = self.selected_position

        found = False
        for p in self.team1:
            if p[0] == user_id:
                old_pos = p[1]
                p[1] = new_position
                found = True
                break
        if not found:
            for p in self.team2:
                if p[0] == user_id:
                    old_pos = p[1]
                    p[1] = new_position
                    found = True
                    break

        if not found:
            await interaction.response.send_message(
                f"⚠️ {self.selected_user.mention} is not in this match!",
                ephemeral=True
            )
            return

        await self.bot.db.db.execute(
            'UPDATE matches SET team1_players = ?, team2_players = ? WHERE id = ? AND guild_id = ?',
            (_json.dumps(self.team1), _json.dumps(self.team2), self.match_id, self.guild_id)
        )
        await self.bot.db.db.commit()

        # Recalibrate ELO if match was already concluded
        await self._recalibrate_concluded_match(interaction)

        embed = await self._build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Replace Player", emoji="👤", style=discord.ButtonStyle.secondary, row=3)
    async def replace_player_btn(self, interaction: discord.Interaction, button):
        """Replace a player in the match with the selected user, taking their spot and position."""
        if not self.selected_user:
            await interaction.response.send_message("⚠️ Select the NEW player with the user dropdown first!", ephemeral=True)
            return

        await self._refresh_match_data()

        if not self.team1 and not self.team2:
            await interaction.response.send_message("⚠️ No players in this match to replace!", ephemeral=True)
            return

        view = ReplacePlayerSelectView(self.bot, self.guild_id, self.match_id, self.selected_user, self)
        await interaction.response.send_message(
            f"Select the player to replace with **{self.selected_user.display_name}**:",
            view=view,
            ephemeral=True
        )

    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, row=4)
    async def refresh_btn(self, interaction: discord.Interaction, button):
        await self._refresh_match_data()
        embed = await self._build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class ReplacePlayerSelectView(discord.ui.View):
    """Select which player to replace from the current match roster."""

    def __init__(self, bot, guild_id, match_id, new_player, parent_view):
        super().__init__(timeout=60)
        self.bot = bot
        self.guild_id = guild_id
        self.match_id = match_id
        self.new_player = new_player
        self.parent_view = parent_view

        # Build options from current match players
        options = []
        for player_id, position in parent_view.team1:
            user = bot.get_user(player_id)
            name = user.display_name if user else f"User {player_id}"
            label = f"Team 1 — {name}"
            if position and position != "Player":
                label += f" ({position})"
            options.append(discord.SelectOption(
                label=label[:100],
                value=str(player_id),
                emoji="🔴"
            ))
        for player_id, position in parent_view.team2:
            user = bot.get_user(player_id)
            name = user.display_name if user else f"User {player_id}"
            label = f"Team 2 — {name}"
            if position and position != "Player":
                label += f" ({position})"
            options.append(discord.SelectOption(
                label=label[:100],
                value=str(player_id),
                emoji="🔵"
            ))

        select = discord.ui.Select(
            placeholder="Select player to replace...",
            options=options if options else [discord.SelectOption(label="No players", value="0")],
            row=0
        )
        select.callback = self.on_player_select
        self.add_item(select)

    async def on_player_select(self, interaction: discord.Interaction):
        import json as _json

        old_user_id = int(interaction.data['values'][0])
        if old_user_id == 0:
            await interaction.response.edit_message(content="⚠️ No players to replace.", view=None)
            return

        await self.parent_view._refresh_match_data()
        team1 = self.parent_view.team1
        team2 = self.parent_view.team2
        new_id = self.new_player.id

        # Check the new player isn't already in the match
        all_ids = [p[0] for p in team1 + team2]
        if new_id in all_ids:
            await interaction.response.edit_message(
                content=f"⚠️ {self.new_player.mention} is already in this match!",
                view=None
            )
            return

        # Find and replace the old player
        found = False
        old_position = None
        for p in team1:
            if p[0] == old_user_id:
                old_position = p[1]
                p[0] = new_id
                found = True
                break
        if not found:
            for p in team2:
                if p[0] == old_user_id:
                    old_position = p[1]
                    p[0] = new_id
                    found = True
                    break

        if not found:
            await interaction.response.edit_message(
                content=f"⚠️ That player is no longer in this match!",
                view=None
            )
            return

        self.parent_view.team1 = team1
        self.parent_view.team2 = team2

        await self.bot.db.db.execute(
            'UPDATE matches SET team1_players = ?, team2_players = ? WHERE id = ? AND guild_id = ?',
            (_json.dumps(team1), _json.dumps(team2), self.match_id, self.guild_id)
        )
        await self.bot.db.db.commit()

        # Update channel permissions
        match = await self.bot.db.get_full_match(self.match_id, self.guild_id)
        if match:
            text_ch_id, voice_ch_id = match[7], match[8]
            old_member = interaction.guild.get_member(old_user_id)
            new_member = interaction.guild.get_member(new_id)

            for ch_id in [text_ch_id, voice_ch_id]:
                if ch_id:
                    ch = self.bot.get_channel(ch_id)
                    if ch:
                        try:
                            if old_member:
                                await ch.set_permissions(old_member, overwrite=None)
                            if new_member:
                                if isinstance(ch, discord.VoiceChannel):
                                    await ch.set_permissions(new_member, view_channel=True, connect=True)
                                else:
                                    await ch.set_permissions(new_member, view_channel=True, send_messages=True)
                        except Exception:
                            pass

        # Recalibrate ELO if match was already concluded
        await self.parent_view._recalibrate_concluded_match(interaction)

        old_user = self.bot.get_user(old_user_id)
        old_text = old_user.mention if old_user else f"User {old_user_id}"
        pos_text = f" ({old_position})" if old_position and old_position != "Player" else ""
        await interaction.response.edit_message(
            content=f"✅ Replaced {old_text}{pos_text} with {self.new_player.mention} in Match #{self.match_id}.",
            view=None
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=1)
    async def cancel_btn(self, interaction: discord.Interaction, button):
        await interaction.response.edit_message(content="Cancelled.", view=None)


# ── ADMIN: FORCE START ──

class ForceStartModal(discord.ui.Modal, title="Force Start Match"):
    """Modal to force start a match from queued players."""

    def __init__(self, bot, guild_id):
        super().__init__(custom_id="modal_force_start")
        self.bot = bot
        self.guild_id = guild_id

    region_input = discord.ui.TextInput(
        label="Region",
        placeholder="NA / EU / Asia / OCE",
        max_length=10
    )
    queue_type_input = discord.ui.TextInput(
        label="Queue Type",
        placeholder="6v6 / 2v2 / 3v3",
        default="6v6",
        max_length=5
    )

    async def on_submit(self, interaction: discord.Interaction):
        region = self.region_input.value.strip()
        queue_type = self.queue_type_input.value.strip().lower()

        if region not in VALID_REGIONS:
            await interaction.response.send_message(
                f"Invalid region! Valid: {', '.join(VALID_REGIONS)}",
                ephemeral=True
            )
            return

        if queue_type not in ('6v6', '2v2', '3v3'):
            await interaction.response.send_message(
                "Invalid queue type! Use: 6v6, 2v2, or 3v3",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            # Get all queued players for this queue type
            queue = await self.bot.db.get_queue(self.guild_id, queue_type)

            # Filter players by the specified region
            region_players = []
            for user_id, position, partner_info in queue:
                player_region = await self.bot.db.get_player_region(self.guild_id, user_id)
                if player_region == region:
                    region_players.append((user_id, position, partner_info))

            # Determine minimum players needed for force start
            force_start_minimum = 2
            if len(region_players) < force_start_minimum:
                await interaction.followup.send(
                    f"Not enough players in **{region}** {queue_type} queue "
                    f"({len(region_players)}/{force_start_minimum} players). "
                    f"Need {force_start_minimum - len(region_players)} more.",
                    ephemeral=True
                )
                return

            # Force start — use all available players, skip position checks
            match_id = await self.bot.create_match(
                self.guild_id,
                region_players,
                match_type=queue_type,
                region=region
            )
            if match_id:
                await interaction.followup.send(
                    f"Match **#{match_id}** force-started for **{region}** ({queue_type}) "
                    f"with {len(region_players)} players!",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"Could not force start — match creation failed.",
                    ephemeral=True
                )
        except Exception as e:
            await interaction.followup.send(
                f"Error force-starting match: {e}",
                ephemeral=True
            )


# ── ADMIN: STREAK EDITING ──

class EditStreaksModal(discord.ui.Modal, title="Edit Player Streaks"):
    """Modal to edit a player's win/loss streaks."""

    def __init__(self, bot, guild_id, user):
        super().__init__(custom_id="modal_edit_streaks")
        self.bot = bot
        self.guild_id = guild_id
        self.target_user = user

    queue_type = discord.ui.TextInput(
        label="Queue Type",
        placeholder="6v6 / 2v2 / 3v3",
        default="6v6",
        max_length=5
    )
    win_streak = discord.ui.TextInput(
        label="Current Win Streak",
        placeholder="e.g., 5",
        required=False,
        max_length=5
    )
    loss_streak = discord.ui.TextInput(
        label="Current Loss Streak",
        placeholder="e.g., 0",
        required=False,
        max_length=5
    )
    best_win = discord.ui.TextInput(
        label="Best Win Streak",
        placeholder="e.g., 10",
        required=False,
        max_length=5
    )
    best_loss = discord.ui.TextInput(
        label="Best Loss Streak",
        placeholder="leave empty to keep",
        required=False,
        max_length=5
    )

    async def on_submit(self, interaction: discord.Interaction):
        qt = self.queue_type.value.strip().lower()
        if qt not in ('6v6', '2v2', '3v3'):
            await interaction.response.send_message(
                "Queue type must be `6v6`, `2v2`, or `3v3`",
                ephemeral=True
            )
            return

        updates = {}
        for field, col_name in [
            (self.win_streak, 'current_win_streak'),
            (self.loss_streak, 'current_loss_streak'),
            (self.best_win, 'best_win_streak'),
            (self.best_loss, 'best_loss_streak'),
        ]:
            if field.value and field.value.strip():
                try:
                    val = int(field.value.strip())
                    if val < 0:
                        raise ValueError
                    updates[col_name] = val
                except ValueError:
                    await interaction.response.send_message(
                        f"Invalid value for {col_name}! Must be a non-negative number.",
                        ephemeral=True
                    )
                    return

        if not updates:
            await interaction.response.send_message("No changes specified!", ephemeral=True)
            return

        if qt == '6v6':
            table = 'players'
        else:
            table = f'players_{qt}'

        set_clauses = ', '.join(f'{k} = ?' for k in updates.keys())
        values = list(updates.values()) + [self.guild_id, self.target_user.id]

        try:
            await self.bot.db.db.execute(
                f'UPDATE {table} SET {set_clauses} WHERE guild_id = ? AND user_id = ?',
                values
            )
            await self.bot.db.db.commit()

            changes = ', '.join(f"**{k}**: {v}" for k, v in updates.items())
            await interaction.response.send_message(
                f"Updated {self.target_user.mention}'s {qt} streaks: {changes}",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"Error updating streaks: {e}",
                ephemeral=True
            )


# ── ADMIN: SHARED MODALS (ELO editing, Reset) ──

class EditEloModal(discord.ui.Modal, title="Edit Player ELO"):
    """Set a player's ELO to a specific value. Supports all queue types."""

    def __init__(self, bot, guild_id, user):
        super().__init__(custom_id="modal_edit_elo")
        self.bot = bot
        self.guild_id = guild_id
        self.target_user = user

    queue_type = discord.ui.TextInput(
        label="Queue Type",
        placeholder="6v6 / 2v2 / 3v3 / highrank / hr2v2 / hr3v3",
        max_length=20,
        default="6v6"
    )
    position = discord.ui.TextInput(
        label="Position (6v6/highrank only, skip 2v2)",
        placeholder="defense / spiker / setter / libero (skip for 2v2/3v3)",
        max_length=20,
        required=False
    )
    new_elo = discord.ui.TextInput(
        label="New ELO Value",
        placeholder="e.g., 800, 1000, 1200...",
        max_length=5
    )

    async def on_submit(self, interaction: discord.Interaction):
        qt = self.queue_type.value.strip().lower()
        qt_map = {
            '6v6': '6v6', '2v2': '2v2', '3v3': '3v3',
            'highrank': 'highrank', 'hr': 'highrank',
            'hr2v2': 'highrank_2v2', 'highrank2v2': 'highrank_2v2', 'highrank_2v2': 'highrank_2v2',
            'hr3v3': 'highrank_3v3', 'highrank3v3': 'highrank_3v3', 'highrank_3v3': 'highrank_3v3',
        }
        queue_type = qt_map.get(qt)
        if not queue_type:
            await interaction.response.send_message(
                "⚠️ Invalid queue type! Use: `6v6`, `2v2`, `3v3`, `highrank`, `hr2v2`, or `hr3v3`",
                ephemeral=True
            )
            return

        try:
            elo = int(self.new_elo.value.strip())
            if elo < 0 or elo > 5000:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "⚠️ ELO must be a number between 0 and 5000!",
                ephemeral=True
            )
            return

        if queue_type in ('2v2', '3v3', 'highrank_2v2', 'highrank_3v3'):
            # Simple ELO (no position)
            if queue_type in ('highrank_2v2', 'highrank_3v3'):
                current_elo = await self.bot.db.get_player_elo_simple(self.guild_id, self.target_user.id, queue_type)
                await self.bot.db.set_player_elo_simple(self.guild_id, self.target_user.id, queue_type, elo)
            else:
                current_elo = await self.bot.db.get_player_elo_simple(self.guild_id, self.target_user.id, queue_type)
                await self.bot.db.set_player_elo_simple(self.guild_id, self.target_user.id, queue_type, elo)
            await self.bot.post_or_update_leaderboard(self.guild_id)
            await interaction.response.send_message(
                f"✅ Updated {self.target_user.mention}'s **{queue_type}** ELO: **{current_elo}** → **{elo}**",
                ephemeral=True
            )
            await self.bot.log_action(
                self.guild_id,
                "Admin: Edit ELO",
                f"{interaction.user.mention} set {self.target_user.mention}'s **{queue_type}** ELO: **{current_elo}** → **{elo}**",
                user=interaction.user, log_type="admin"
            )
        else:
            # Position-based ELO (6v6 or highrank)
            pos_input = self.position.value.strip().lower() if self.position.value else ""
            position = POSITION_ALIASES.get(pos_input)
            if not position or position == "all":
                await interaction.response.send_message(
                    "⚠️ Position required for 6v6/highrank! Use: `defense`, `spiker`, `setter`, or `libero`",
                    ephemeral=True
                )
                return

            if queue_type == 'highrank':
                current_elo = await self.bot.db.get_player_elo_highrank(self.guild_id, self.target_user.id, position)
                await self.bot.db.set_player_elo_highrank(self.guild_id, self.target_user.id, position, elo)
            else:
                current_elo = await self.bot.db.get_player_elo(self.guild_id, self.target_user.id, position)
                await self.bot.db.set_player_elo(self.guild_id, self.target_user.id, position, elo)
            await self.bot.post_or_update_leaderboard(self.guild_id)
            await interaction.response.send_message(
                f"✅ Updated {self.target_user.mention}'s **{queue_type} {position}** ELO: **{current_elo}** → **{elo}**",
                ephemeral=True
            )
            await self.bot.log_action(
                self.guild_id,
                "Admin: Edit ELO",
                f"{interaction.user.mention} set {self.target_user.mention}'s **{queue_type} {position}** ELO: **{current_elo}** → **{elo}**",
                user=interaction.user, log_type="admin"
            )


class AdjustEloModal(discord.ui.Modal, title="Adjust Player ELO"):
    """Add or subtract ELO from a player. Supports all queue types."""

    def __init__(self, bot, guild_id, user):
        super().__init__(custom_id="modal_adjust_elo_full")
        self.bot = bot
        self.guild_id = guild_id
        self.target_user = user

    queue_type = discord.ui.TextInput(
        label="Queue Type",
        placeholder="6v6 / 2v2 / 3v3 / highrank / hr2v2 / hr3v3",
        max_length=20,
        default="6v6"
    )
    position = discord.ui.TextInput(
        label="Position (6v6/highrank only, skip 2v2)",
        placeholder="defense / spiker / setter / libero (skip for 2v2/3v3)",
        max_length=20,
        required=False
    )
    amount = discord.ui.TextInput(
        label="Amount (positive=add, negative=subtract)",
        placeholder="e.g., 50, -30, 100...",
        max_length=5
    )

    async def on_submit(self, interaction: discord.Interaction):
        qt = self.queue_type.value.strip().lower()
        qt_map = {
            '6v6': '6v6', '2v2': '2v2', '3v3': '3v3',
            'highrank': 'highrank', 'hr': 'highrank',
            'hr2v2': 'highrank_2v2', 'highrank2v2': 'highrank_2v2', 'highrank_2v2': 'highrank_2v2',
            'hr3v3': 'highrank_3v3', 'highrank3v3': 'highrank_3v3', 'highrank_3v3': 'highrank_3v3',
        }
        queue_type = qt_map.get(qt)
        if not queue_type:
            await interaction.response.send_message(
                "⚠️ Invalid queue type! Use: `6v6`, `2v2`, `3v3`, `highrank`, `hr2v2`, or `hr3v3`",
                ephemeral=True
            )
            return

        try:
            adj = int(self.amount.value.strip())
            if adj > 1000 or adj < -1000:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "⚠️ Amount must be between -1000 and 1000!",
                ephemeral=True
            )
            return

        if queue_type in ('2v2', '3v3', 'highrank_2v2', 'highrank_3v3'):
            # Simple ELO (no position)
            old_elo = await self.bot.db.get_player_elo_simple(self.guild_id, self.target_user.id, queue_type)
            new_elo_val = max(0, old_elo + adj)
            await self.bot.db.set_player_elo_simple(self.guild_id, self.target_user.id, queue_type, new_elo_val)
            await self.bot.post_or_update_leaderboard(self.guild_id)
            change_str = f"+{adj}" if adj > 0 else str(adj)
            await interaction.response.send_message(
                f"✅ Adjusted {self.target_user.mention}'s **{queue_type}** ELO by **{change_str}**\n"
                f"**{old_elo}** → **{new_elo_val}**",
                ephemeral=True
            )
            await self.bot.log_action(
                self.guild_id,
                "Admin: Adjust ELO",
                f"{interaction.user.mention} adjusted {self.target_user.mention}'s **{queue_type}** ELO by **{change_str}**: **{old_elo}** → **{new_elo_val}**",
                user=interaction.user, log_type="admin"
            )
        else:
            # Position-based ELO (6v6 or highrank)
            pos_input = self.position.value.strip().lower() if self.position.value else ""
            position = POSITION_ALIASES.get(pos_input)
            if not position or position == "all":
                await interaction.response.send_message(
                    "⚠️ Position required for 6v6/highrank! Use: `defense`, `spiker`, `setter`, or `libero`",
                    ephemeral=True
                )
                return

            if queue_type == 'highrank':
                old_elo = await self.bot.db.get_player_elo_highrank(self.guild_id, self.target_user.id, position)
                new_elo_val = max(0, old_elo + adj)
                await self.bot.db.set_player_elo_highrank(self.guild_id, self.target_user.id, position, new_elo_val)
            else:
                old_elo, new_elo_val = await self.bot.db.adjust_player_elo(
                    self.guild_id, self.target_user.id, position, adj
                )
            await self.bot.post_or_update_leaderboard(self.guild_id)
            change_str = f"+{adj}" if adj > 0 else str(adj)
            await interaction.response.send_message(
                f"✅ Adjusted {self.target_user.mention}'s **{queue_type} {position}** ELO by **{change_str}**\n"
                f"**{old_elo}** → **{new_elo_val}**",
                ephemeral=True
            )
            await self.bot.log_action(
                self.guild_id,
                "Admin: Adjust ELO",
                f"{interaction.user.mention} adjusted {self.target_user.mention}'s **{queue_type} {position}** ELO by **{change_str}**: **{old_elo}** → **{new_elo_val}**",
                user=interaction.user, log_type="admin"
            )


class EditRecordModal(discord.ui.Modal, title="Edit Player Record"):
    """Edit a player's wins, losses, and games played for any queue type."""

    def __init__(self, bot, guild_id, user):
        super().__init__(custom_id="modal_edit_record")
        self.bot = bot
        self.guild_id = guild_id
        self.target_user = user

    queue_type = discord.ui.TextInput(
        label="Queue Type",
        placeholder="6v6 / 2v2 / 3v3",
        max_length=10,
        default="6v6"
    )
    wins_input = discord.ui.TextInput(
        label="Wins",
        placeholder="New wins count",
        max_length=5,
        required=False
    )
    losses_input = discord.ui.TextInput(
        label="Losses",
        placeholder="New losses count",
        max_length=5,
        required=False
    )
    games_input = discord.ui.TextInput(
        label="Games Played",
        placeholder="New total games count",
        max_length=5,
        required=False
    )

    async def on_submit(self, interaction: discord.Interaction):
        qt = self.queue_type.value.strip().lower()
        if qt not in ('6v6', '2v2', '3v3'):
            await interaction.response.send_message(
                "⚠️ Queue type must be `6v6`, `2v2`, or `3v3`",
                ephemeral=True
            )
            return

        updates = {}
        for field, name in [(self.wins_input, 'wins'), (self.losses_input, 'losses'), (self.games_input, 'games_played')]:
            if field.value and field.value.strip():
                try:
                    val = int(field.value.strip())
                    if val < 0:
                        raise ValueError
                    updates[name] = val
                except ValueError:
                    await interaction.response.send_message(
                        f"⚠️ {name.title()} must be a non-negative number!",
                        ephemeral=True
                    )
                    return

        if not updates:
            await interaction.response.send_message("⚠️ No changes specified!", ephemeral=True)
            return

        if qt == '6v6':
            table = 'players'
        else:
            table = f'players_{qt}'

        set_clauses = ', '.join(f'{k} = ?' for k in updates.keys())
        values = list(updates.values()) + [self.guild_id, self.target_user.id]

        await self.bot.db.db.execute(
            f'UPDATE {table} SET {set_clauses} WHERE guild_id = ? AND user_id = ?',
            values
        )
        await self.bot.db.db.commit()
        await self.bot.post_or_update_leaderboard(self.guild_id)

        changes = ', '.join(f"**{k}**: {v}" for k, v in updates.items())
        await interaction.response.send_message(
            f"✅ Updated {self.target_user.mention}'s {qt} record: {changes}",
            ephemeral=True
        )
        await self.bot.log_action(
            self.guild_id,
            "Admin: Edit Record",
            f"{interaction.user.mention} edited {self.target_user.mention}'s **{qt}** record: {changes}",
            user=interaction.user, log_type="admin"
        )


class ResetPlayerConfirmView(discord.ui.View):
    """Confirmation for resetting a player's stats."""

    def __init__(self, bot, guild_id, user):
        super().__init__(timeout=30)
        self.bot = bot
        self.guild_id = guild_id
        self.target_user = user

    @discord.ui.button(label="Yes, Reset Stats", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button):
        await self.bot.db.reset_player_stats(self.guild_id, self.target_user.id)
        await self.bot.db.db.execute(
            'DELETE FROM position_stats WHERE guild_id = ? AND user_id = ?',
            (self.guild_id, self.target_user.id)
        )
        await self.bot.db.db.commit()
        await self.bot.post_or_update_leaderboard(self.guild_id)

        await interaction.response.edit_message(
            content=f"✅ All stats reset for {self.target_user.mention}",
            view=None
        )
        await self.bot.log_action(
            self.guild_id,
            "Admin: Reset Player",
            f"{interaction.user.mention} reset all stats for {self.target_user.mention}",
            user=interaction.user, log_type="admin"
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button):
        await interaction.response.edit_message(content="Cancelled.", view=None)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  REGION ROLES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def build_regionroles_embed(bot, guild_id, guild):
    config = await bot.db.get_config(guild_id)
    region_roles = config.get("region_roles", {})
    region_channel = config.get("region_roles_channel")

    embed = discord.Embed(
        title="Region Role Configuration",
        description="Configure region roles and the channel for the region selection embed.",
        color=discord.Color.blue()
    )

    channel_text = f"<#{region_channel}>" if region_channel else "Not set"
    embed.add_field(name="Region Channel", value=channel_text, inline=False)

    roles_text = ""
    for region in VALID_REGIONS:
        role_id = region_roles.get(region)
        if role_id:
            role = guild.get_role(role_id)
            role_text = role.mention if role else f"*Deleted role (ID: {role_id})*"
        else:
            role_text = "Not set"
        roles_text += f"**{region}**: {role_text}\n"

    embed.add_field(name="Region Role Mappings", value=roles_text, inline=False)
    embed.add_field(
        name="How it works",
        value=(
            "1. Set the channel where the region selection embed will appear\n"
            "2. Map each region to a Discord role\n"
            "3. Click **Post Embed** to send the selection embed\n"
            "4. Players select their region and get the role automatically"
        ),
        inline=False
    )
    embed.set_footer(text="Use the controls below to configure regions")
    return embed


async def navigate_to_regionroles(interaction, bot, guild_id):
    embed = await build_regionroles_embed(bot, guild_id, interaction.guild)
    view = RegionRolesConfigView(bot, guild_id)
    await interaction.response.edit_message(embed=embed, view=view)


class RegionRolesConfigView(discord.ui.View):
    """Configuration view for region roles."""

    def __init__(self, bot, guild_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="Select Region Roles Channel",
        channel_types=[discord.ChannelType.text],
        min_values=1, max_values=1, row=0
    )
    async def channel_select(self, interaction: discord.Interaction, select):
        channel = select.values[0]
        config = await self.bot.db.get_config(self.guild_id)
        config["region_roles_channel"] = channel.id
        await self.bot.db.update_config(self.guild_id, config)

        embed = await build_regionroles_embed(self.bot, self.guild_id, interaction.guild)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Set Region Role", style=discord.ButtonStyle.success, row=1)
    async def set_role_btn(self, interaction: discord.Interaction, button):
        view = SetRegionRoleStepView(self.bot, self.guild_id)
        embed = discord.Embed(
            title="Set Region Role",
            description="1. Select a region from the dropdown\n2. Select the Discord role to assign",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Post Embed", style=discord.ButtonStyle.primary, row=1)
    async def post_embed_btn(self, interaction: discord.Interaction, button):
        config = await self.bot.db.get_config(self.guild_id)
        channel_id = config.get("region_roles_channel")
        if not channel_id:
            await interaction.response.send_message(
                "Set a region roles channel first!", ephemeral=True
            )
            return

        channel = self.bot.get_channel(channel_id)
        if not channel:
            await interaction.response.send_message(
                "Region roles channel not found!", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        await self.bot.post_or_update_region_embed(self.guild_id)
        await interaction.followup.send(
            f"Region selection embed posted/updated in <#{channel_id}>!",
            ephemeral=True
        )

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=2)
    async def back_btn(self, interaction: discord.Interaction, button):
        await navigate_to_hub(interaction, self.bot, self.guild_id)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class SetRegionRoleStepView(discord.ui.View):
    """Two-dropdown view: select region, then select role."""

    def __init__(self, bot, guild_id):
        super().__init__(timeout=120)
        self.bot = bot
        self.guild_id = guild_id
        self.selected_region = None

    @discord.ui.select(
        placeholder="Select a region...",
        options=[
            discord.SelectOption(label="NA (North America)", value="NA"),
            discord.SelectOption(label="EU (Europe)", value="EU"),
            discord.SelectOption(label="Asia", value="Asia"),
            discord.SelectOption(label="OCE (Oceania)", value="OCE"),
        ],
        row=0
    )
    async def region_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.selected_region = select.values[0]
        await interaction.response.send_message(
            f"Selected region: **{self.selected_region}**. Now select the role below.",
            ephemeral=True
        )

    @discord.ui.select(
        cls=discord.ui.RoleSelect,
        placeholder="Select the Discord role for this region...",
        min_values=1, max_values=1,
        row=1
    )
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        if not self.selected_region:
            await interaction.response.send_message(
                "Please select a region first!", ephemeral=True
            )
            return

        role = select.values[0]
        config = await self.bot.db.get_config(self.guild_id)
        if "region_roles" not in config:
            config["region_roles"] = {}
        config["region_roles"][self.selected_region] = role.id
        await self.bot.db.update_config(self.guild_id, config)

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            content=f"**{self.selected_region}** region mapped to {role.mention}",
            embed=None,
            view=self
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  EXISTING MODALS (used by GeneralSettingsView)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class MatchCategoryModal(discord.ui.Modal, title="Set Match Category"):
    def __init__(self, bot, guild_id):
        super().__init__(custom_id="modal_match_category")
        self.bot = bot
        self.guild_id = guild_id

    category_name = discord.ui.TextInput(
        label="Category Name or ID",
        placeholder="Enter the name or ID of the category for match channels",
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        category_input = self.category_name.value.strip()
        category = None

        try:
            category_id = int(category_input)
            category = interaction.guild.get_channel(category_id)
            if category and not isinstance(category, discord.CategoryChannel):
                category = None
        except ValueError:
            category = discord.utils.get(interaction.guild.categories, name=category_input)

        if not category:
            for cat in interaction.guild.categories:
                if cat.name.lower() == category_input.lower():
                    category = cat
                    break

        if not category:
            await interaction.response.send_message(
                f"❌ Category '{category_input}' not found!\n\n"
                f"Available categories: {', '.join([f'`{cat.name}`' for cat in interaction.guild.categories[:10]])}",
                ephemeral=True
            )
            return

        config = await self.bot.db.get_config(self.guild_id)
        config["match_category"] = category.id
        await self.bot.db.update_config(self.guild_id, config)

        await interaction.response.send_message(
            f"✅ Match category set to **{category.name}**",
            ephemeral=True
        )


class EloSettingsModal(discord.ui.Modal, title="ELO Settings"):
    def __init__(self, bot, guild_id):
        super().__init__(custom_id="modal_elo_settings")
        self.bot = bot
        self.guild_id = guild_id

    starting_elo = discord.ui.TextInput(
        label="Starting ELO",
        placeholder="Default: 1000",
        default="1000",
        max_length=4
    )
    k_factor = discord.ui.TextInput(
        label="K-Factor (ELO sensitivity)",
        placeholder="Default: 32",
        default="32",
        max_length=3
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            config = await self.bot.db.get_config(self.guild_id)
            old_starting_elo = config.get("starting_elo", 1000)
            new_starting_elo = int(self.starting_elo.value)
            new_k_factor = int(self.k_factor.value)

            config["starting_elo"] = new_starting_elo
            config["k_factor"] = new_k_factor
            await self.bot.db.update_config(self.guild_id, config)

            if old_starting_elo != new_starting_elo:
                await interaction.response.defer(ephemeral=True)
                await self.bot.db.update_starting_elo_for_unplayed_positions(
                    self.guild_id, old_starting_elo, new_starting_elo
                )
                await self.bot.post_or_update_leaderboard(self.guild_id)

                await interaction.followup.send(
                    f"✅ ELO settings updated!\n\n"
                    f"Starting ELO: {old_starting_elo} → {new_starting_elo}\n"
                    f"K-Factor: {new_k_factor}\n\n"
                    f"Unplayed positions updated to new starting ELO.",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"✅ ELO settings updated!\n\n"
                    f"Starting ELO: {new_starting_elo}\n"
                    f"K-Factor: {new_k_factor}",
                    ephemeral=True
                )
        except ValueError:
            await interaction.response.send_message(
                "Invalid values! Please enter numbers only.",
                ephemeral=True
            )


class MatchCleanupModal(discord.ui.Modal, title="Match Cleanup Settings"):
    def __init__(self, bot, guild_id, current_hours=1.0):
        super().__init__(custom_id="modal_match_cleanup")
        self.bot = bot
        self.guild_id = guild_id

        self.timeout_hours = discord.ui.TextInput(
            label="Channel Cleanup Time (hours)",
            placeholder="Examples: 0.5 (30 min), 1 (1 hour), 24 (1 day)",
            default=f"{current_hours:.1f}",
            max_length=5
        )
        self.add_item(self.timeout_hours)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            hours = float(self.timeout_hours.value)
            if hours < 0.1 or hours > 168:
                await interaction.response.send_message(
                    "Cleanup time must be between 0.1 hours (6 min) and 168 hours (1 week)!",
                    ephemeral=True
                )
                return

            config = await self.bot.db.get_config(self.guild_id)
            config["match_channel_timeout"] = int(hours * 3600)
            await self.bot.db.update_config(self.guild_id, config)

            if hours >= 1:
                time_display = f"{hours:.1f} hour{'s' if hours != 1 else ''}"
            else:
                minutes = int(hours * 60)
                time_display = f"{minutes} minute{'s' if minutes != 1 else ''}"

            await interaction.response.send_message(
                f"✅ Match channels will be cleaned up after **{time_display}** of inactivity",
                ephemeral=True
            )
        except ValueError:
            await interaction.response.send_message("Please enter a valid number!", ephemeral=True)
