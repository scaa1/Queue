import discord
import logging
from datetime import datetime, timedelta
from typing import List, Tuple, Optional

# Set up logging
logger = logging.getLogger('volleyball_bot')

def setup_logging():
    """Set up logging configuration"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('bot.log'),
            logging.StreamHandler()
        ]
    )
    return logger

def format_duration(seconds: int) -> str:
    """Convert seconds to human readable duration"""
    if seconds < 60:
        return f"{seconds} seconds"
    elif seconds < 3600:
        return f"{seconds // 60} minutes"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h {minutes}m"

def create_progress_bar(current: int, total: int, length: int = 10) -> str:
    """Create a text-based progress bar"""
    filled = int(length * current / total)
    bar = "█" * filled + "░" * (length - filled)
    percentage = (current / total) * 100
    return f"[{bar}] {percentage:.1f}%"

def validate_position(position: str) -> bool:
    """Validate if a position is valid"""
    from config import VALID_POSITIONS
    return position in VALID_POSITIONS

def calculate_team_average_elo(team_elos: List[int]) -> float:
    """Calculate average ELO for a team"""
    if not team_elos:
        return 0
    return sum(team_elos) / len(team_elos)

def create_match_summary_embed(
    match_id: int,
    team1_players: List[Tuple[int, str, int]],  # (user_id, position, elo)
    team2_players: List[Tuple[int, str, int]],
    team1_score: int = 0,
    team2_score: int = 0,
    winner: Optional[int] = None
) -> discord.Embed:
    """Create a formatted embed for match summary"""
    
    if winner:
        color = discord.Color.gold()
        title = f"🏆 Match #{match_id} - Completed"
    else:
        color = discord.Color.blue()
        title = f"🏐 Match #{match_id} - In Progress"
    
    embed = discord.Embed(title=title, color=color)
    
    # Add timestamp
    embed.timestamp = datetime.utcnow()
    
    # Team compositions
    team1_text = ""
    team2_text = ""
    
    for user_id, position, elo in team1_players:
        team1_text += f"<@{user_id}> - {position} ({elo} ELO)\n"
        
    for user_id, position, elo in team2_players:
        team2_text += f"<@{user_id}> - {position} ({elo} ELO)\n"
    
    embed.add_field(name="🔴 Team 1", value=team1_text or "No players", inline=True)
    embed.add_field(name="🔵 Team 2", value=team2_text or "No players", inline=True)
    
    # Average ELOs
    avg_elo1 = calculate_team_average_elo([p[2] for p in team1_players])
    avg_elo2 = calculate_team_average_elo([p[2] for p in team2_players])
    
    embed.add_field(
        name="📊 Team Statistics",
        value=f"Team 1 Avg: **{avg_elo1:.0f}** ELO\nTeam 2 Avg: **{avg_elo2:.0f}** ELO\nDifference: **{abs(avg_elo1 - avg_elo2):.0f}**",
        inline=False
    )
    
    # Score if available
    if team1_score > 0 or team2_score > 0:
        embed.add_field(
            name="📋 Score",
            value=f"Team 1: **{team1_score}**\nTeam 2: **{team2_score}**",
            inline=True
        )
        
    if winner:
        embed.add_field(
            name="🎉 Winner",
            value=f"**Team {winner}**",
            inline=True
        )
    
    return embed

def parse_user_id(user_input: str) -> Optional[int]:
    """Parse user ID from mention or raw ID"""
    # Remove mention formatting if present
    user_input = user_input.strip()
    if user_input.startswith('<@') and user_input.endswith('>'):
        user_input = user_input[2:-1]
        if user_input.startswith('!'):
            user_input = user_input[1:]
    
    try:
        return int(user_input)
    except ValueError:
        return None

def chunk_list(lst: List, chunk_size: int) -> List[List]:
    """Split a list into chunks of specified size"""
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]

def format_elo_change(elo_change: int) -> str:
    """Format ELO change with + or - sign"""
    if elo_change > 0:
        return f"+{elo_change}"
    return str(elo_change)

def get_position_emoji(position: str) -> str:
    """Get emoji for a position"""
    from config import POSITION_EMOJIS
    return POSITION_EMOJIS.get(position, "🏐")

def create_error_embed(error_message: str, title: str = "Error") -> discord.Embed:
    """Create a standardized error embed"""
    embed = discord.Embed(
        title=f"❌ {title}",
        description=error_message,
        color=discord.Color.red()
    )
    embed.timestamp = datetime.utcnow()
    return embed

def create_success_embed(message: str, title: str = "Success") -> discord.Embed:
    """Create a standardized success embed"""
    embed = discord.Embed(
        title=f"✅ {title}",
        description=message,
        color=discord.Color.green()
    )
    embed.timestamp = datetime.utcnow()
    return embed

def is_duo_queue_valid(team1_duos: List[Tuple[int, int]], team2_duos: List[Tuple[int, int]]) -> bool:
    """Check if duo queue distribution is balanced"""
    # Each team should have similar number of duos
    return abs(len(team1_duos) - len(team2_duos)) <= 1

def get_match_duration_estimate(num_players: int) -> int:
    """Estimate match duration in minutes based on number of players"""
    base_duration = 30  # 30 minutes base
    player_factor = num_players * 2  # More players = potentially longer matches
    return base_duration + player_factor