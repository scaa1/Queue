# commands/__init__.py
"""
Command module initialization
Loads all command cogs for the volleyball bot
"""

from .admin import AdminCommands
from .match import MatchCommands
from .stats import StatsCommands
from .queue import QueueCommands
from .eloroles import EloRoleCommands

async def setup(bot):
    """Load all command cogs"""
    await bot.add_cog(AdminCommands(bot))
    await bot.add_cog(MatchCommands(bot))
    await bot.add_cog(StatsCommands(bot))
    await bot.add_cog(QueueCommands(bot))
    await bot.add_cog(EloRoleCommands(bot))