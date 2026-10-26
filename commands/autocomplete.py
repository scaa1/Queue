# commands/autocomplete.py
"""
Shared autocomplete functions for commands
"""

import json
from typing import List
import discord
from discord import app_commands
from config import POSITION_EMOJIS, VALID_POSITIONS


async def match_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[int]]:
    """Autocomplete for active match IDs"""
    bot = interaction.client
    matches = await bot.db.get_active_matches(interaction.guild.id)
    choices = []
    
    for match_id, text_channel_id, voice_channel_id in matches[:25]:
        # Get match details
        match_data = await bot.db.get_match(match_id, interaction.guild.id)
        if match_data:
            team1 = json.loads(match_data[0])
            team2 = json.loads(match_data[1])
            
            # Create descriptive name
            t1_size = len(team1)
            t2_size = len(team2)
            
            # Get first player from each team for context
            t1_player = bot.get_user(team1[0][0]) if team1 else None
            t2_player = bot.get_user(team2[0][0]) if team2 else None
            
            name = f"Match #{match_id} - {t1_size}v{t2_size}"
            if t1_player and t2_player:
                name += f" ({t1_player.name} vs {t2_player.name}...)"
            
            if str(match_id).startswith(current) or current.lower() in name.lower():
                choices.append(app_commands.Choice(name=name[:100], value=match_id))
                
    return choices


async def position_autocomplete_for_user(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    """Autocomplete for positions showing only those the user has played"""
    bot = interaction.client
    
    # Get the user parameter from the interaction
    user = None
    for option in interaction.data.get("options", []):
        if option["name"] == "user":
            user_id = int(option["value"])
            user = bot.get_user(user_id)
            break
            
    if not user:
        # If no user selected yet, show all positions
        return [
            app_commands.Choice(name=f"{POSITION_EMOJIS.get(pos, '🏐')} {pos}", value=pos)
            for pos in VALID_POSITIONS
            if current.lower() in pos.lower()
        ]
        
    # Get positions the user has played
    choices = []
    for position in VALID_POSITIONS:
        games = await bot.db.get_position_games_played(interaction.guild.id, user.id, position)
        elo = await bot.db.get_player_elo(interaction.guild.id, user.id, position)
        
        emoji = POSITION_EMOJIS.get(position, "🏐")
        if games > 0:
            name = f"{emoji} {position} (ELO: {elo}, Games: {games})"
        else:
            name = f"{emoji} {position} (ELO: {elo}, Never played)"
            
        if current.lower() in position.lower():
            choices.append(app_commands.Choice(name=name[:100], value=position))
            
    # Sort by games played (most played first)
    choices.sort(key=lambda x: int(x.name.split("Games: ")[1].split(")")[0]) if "Games:" in x.name else -1, reverse=True)
    
    return choices[:25]