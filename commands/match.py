# commands/match.py
"""
Match-related commands for the volleyball bot.
Note: matchedit, report, and forcestart have been moved to Admin Tools in /config.
"""

import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional
import json
from datetime import datetime


class MatchCommands(commands.Cog):
    """Commands for viewing match history"""

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="recent", description="View recent matches")
    @app_commands.describe(
        user="View matches for specific user (leave empty for all)",
        limit="Number of matches to show (default 5, max 10)"
    )
    async def recent(self, interaction: discord.Interaction, user: Optional[discord.User] = None, limit: int = 5):
        if limit < 1 or limit > 10:
            limit = 5

        matches = await self.bot.db.get_recent_matches(interaction.guild.id, user.id if user else None, limit)

        embed = discord.Embed(
            title=f"Recent Matches{f' for {user.name}' if user else ''}",
            color=discord.Color.blue()
        )

        if not matches:
            embed.description = "No matches found"
        else:
            for match_id, team1_json, team2_json, score1, score2, timestamp in matches:
                team1 = json.loads(team1_json)
                team2 = json.loads(team2_json)

                # Determine winner (handle None scores from in-progress/cancelled matches)
                s1 = score1 or 0
                s2 = score2 or 0
                winner = 1 if s1 > s2 else 2 if s2 > s1 else 0

                # Create player lists
                team1_players = []
                team2_players = []

                for user_id, position in team1:
                    u = self.bot.get_user(user_id)
                    team1_players.append(f"{u.name if u else f'User{user_id}'}")

                for user_id, position in team2:
                    u = self.bot.get_user(user_id)
                    team2_players.append(f"{u.name if u else f'User{user_id}'}")

                # Format timestamp
                match_time = datetime.fromisoformat(timestamp)
                time_ago = datetime.utcnow() - match_time
                if time_ago.days > 0:
                    time_str = f"{time_ago.days}d ago"
                elif time_ago.seconds > 3600:
                    time_str = f"{time_ago.seconds // 3600}h ago"
                else:
                    time_str = f"{time_ago.seconds // 60}m ago"

                embed.add_field(
                    name=f"Match #{match_id} - {time_str}",
                    value=f"{'🏆 ' if winner == 1 else ''}Team 1: {', '.join(team1_players[:3])}{'...' if len(team1_players) > 3 else ''}\n"
                          f"{'🏆 ' if winner == 2 else ''}Team 2: {', '.join(team2_players[:3])}{'...' if len(team2_players) > 3 else ''}\n"
                          f"Score: **{s1}** - **{s2}**",
                    inline=False
                )

        await interaction.response.send_message(embed=embed, ephemeral=True)
