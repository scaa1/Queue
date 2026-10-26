# commands/admin.py
"""
Admin commands for the volleyball bot.
All administration is handled through the unified /config UI.
"""

import discord
from discord import app_commands
from discord.ext import commands

from views.config_views import ConfigHubView, build_hub_embed, build_admintools_hub_embed, AdminToolsHubView


class AdminCommands(commands.Cog):
    """Administrative commands for server management"""

    def __init__(self, bot):
        self.bot = bot

    async def _check_staff(self, interaction: discord.Interaction) -> bool:
        """Check if user has admin or staff permissions."""
        if interaction.user.guild_permissions.administrator:
            return True
        config = await self.bot.db.get_config(interaction.guild.id)
        senior_roles = config.get("staff_senior_roles", [])
        normal_roles = config.get("staff_normal_roles", [])
        staff_roles = senior_roles + normal_roles
        user_role_ids = [role.id for role in interaction.user.roles]
        return any(role_id in staff_roles for role_id in user_role_ids)

    @app_commands.command(name="config", description="Configure the volleyball bot — all settings in one place")
    async def config(self, interaction: discord.Interaction):
        if not await self._check_staff(interaction):
            await interaction.response.send_message(
                "This command requires **Administrator**, **Senior Staff**, or **Staff** permissions.",
                ephemeral=True
            )
            return

        embed = await build_hub_embed(self.bot, interaction.guild.id, interaction.guild)
        view = ConfigHubView(self.bot, interaction.guild.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="admintool", description="Quick access to admin tools — manage players, blacklist, matches")
    async def admintool(self, interaction: discord.Interaction):
        if not await self._check_staff(interaction):
            await interaction.response.send_message(
                "This command requires **Administrator**, **Senior Staff**, or **Staff** permissions.",
                ephemeral=True
            )
            return

        embed = await build_admintools_hub_embed(self.bot, interaction.guild.id)
        view = AdminToolsHubView(self.bot, interaction.guild.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
