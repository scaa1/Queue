# commands/eloroles.py
"""
ELO role management is handled via /config.
This module is kept for backward compatibility but has no commands.
"""

import discord
from discord.ext import commands


class EloRoleCommands(commands.Cog):
    """ELO role commands (handled via /config)"""

    def __init__(self, bot):
        self.bot = bot


async def setup(bot):
    await bot.add_cog(EloRoleCommands(bot))
