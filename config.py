# config.py
import os
from enum import Enum

# Try to load from .env file if it exists
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # python-dotenv not installed, will use system environment variables
    pass

# Bot Token - Store in environment variable for security
# WARNING: The token below appears to be exposed. You should regenerate it and store it securely!
BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN', 'MTM1OTYxNDM0MDAwMDM4MzE2OA.GchHme.W52w0-KTxWNInAeA9qMwpIZ6CARQGeYsE5RLoY')

# Guild restriction - Set to 0 to disable, or a guild ID to restrict to that guild only
ALLOWED_GUILD_ID = int(os.getenv('ALLOWED_GUILD_ID', 1472335258400718953))

# Database
DATABASE_NAME = 'volleyball_elo.db'

# Default Configuration
VALID_POSITIONS = ["Defense Specialist", "Front Spiker", "Setter", "Libero"]

# Position emojis (used in leaderboards, match results, etc. - not in queue)
POSITION_EMOJIS = {
    "Defense Specialist": "\U0001f6e1\ufe0f",
    "Front Spiker": "\u2694\ufe0f",
    "Setter": "\U0001f3af",
    "Libero": "\U0001f525"
}

# Queue types
VALID_QUEUE_TYPES = ["6v6", "3v3", "2v2"]

# Valid regions for role selection
VALID_REGIONS = ["NA", "EU", "Asia", "OCE"]

# Default team size per region (configurable per guild)
DEFAULT_REGION_TEAM_SIZES = {
    "NA": "6v6",
    "EU": "6v6",
    "Asia": "5v5",
    "OCE": "5v5"
}


def get_region_team_size(config, region):
    """Get the team size format for a region ('5v5' or '6v6')."""
    team_sizes = config.get("region_team_sizes", DEFAULT_REGION_TEAM_SIZES)
    return team_sizes.get(region, "6v6")


def is_5v5_region(config, region):
    """Check if a region uses 5v5 format."""
    return get_region_team_size(config, region) == "5v5"


def get_region_role_limits(config, region):
    """Get the role_limits appropriate for a region's team size."""
    if is_5v5_region(config, region):
        return config.get("role_limits_5v5", {
            "Defense Specialist": 4,
            "Front Spiker": 4,
            "Setter": 2
        })
    return config["role_limits"]

# Default configuration for new guilds
DEFAULT_CONFIG = {
    "queue_channel": None,
    "queue_2v2_channel": None,
    "queue_3v3_channel": None,
    "results_channel": None,
    "leaderboard_channel": None,
    "leaderboard_message_id": None,
    "match_category": None,
    "min_players": 12,
    "starting_elo": 650,
    "k_factor": 32,
    "queue_timeout": 3600,  # 1 hour
    "ready_check_timeout": 300,  # 5 minutes
    "match_channel_timeout": 3600,  # 1 hour (in seconds)
    "queue_cooldown": 5,  # seconds between interactions per user
    "role_limits": {
        "Defense Specialist": 4,
        "Front Spiker": 4,
        "Setter": 2,
        "Libero": 2
    },
    "role_limits_5v5": {
        "Defense Specialist": 4,
        "Front Spiker": 4,
        "Setter": 2
    },
    "region_team_sizes": {
        "NA": "6v6",
        "EU": "6v6",
        "Asia": "5v5",
        "OCE": "5v5"
    },
    "staff_senior_roles": [],  # Full mod permissions
    "staff_normal_roles": [],  # Basic mod permissions
    "region_roles_channel": None,
    "region_roles_message_id": None,
    "region_roles": {},
    # High rank settings
    "high_rank_enabled": False,
    "high_rank_mmr_limit": 1000,  # Minimum average MMR to enter high rank 6v6 queue
    "high_rank_solo_enabled": False,  # Solo queue for high rank 6v6 (disabled = duo only)
    "high_rank_duo_enabled": True,   # Duo queue for high rank 6v6
    "high_rank_trio_enabled": False,  # Trio queue for high rank 6v6
    "high_rank_2v2_enabled": False,
    "high_rank_2v2_mmr_limit": 1000,  # Minimum MMR to enter high rank 2v2 queue
    "high_rank_3v3_enabled": False,
    "high_rank_3v3_mmr_limit": 1000,  # Minimum MMR to enter high rank 3v3 queue
    "high_rank_starting_elo": 650,  # Starting ELO for high rank queues (separate from normal)
    # Queue toggle settings
    "duo_queue_enabled": True,
    "trio_queue_enabled": True,
    "duo_2v2_enabled": True,       # Enable/disable duo queue button in 2v2
    "duo_3v3_enabled": True,       # Enable/disable duo queue button in 3v3
    "trio_3v3_enabled": True,      # Enable/disable trio queue button in 3v3
    # 2v2/3v3 party requirements (require_duo_2v2 means 2v2 requires duo party, etc.)
    "require_duo_2v2": False,
    "require_trio_3v3": False,
    # Party invite channel (channel or thread for posting duo/trio queue invitations)
    "invite_channel": None,
    # Blacklist settings
    "blacklist_role_id": None,  # Custom role ID for blacklist (None = auto-create "Blacklisted")
    # AFK queue timer (seconds) - removes players from queue after this duration of inactivity
    "afk_timer": 1800,  # 30 minutes default
    # Bot action log channels
    "log_channel": None,  # General log (commands, buttons, all interactions)
    "log_channel_readyup": None,  # Ready-up failures (who didn't ready up)
    "log_channel_admin": None,  # Admin action logs
    # Ready-up penalty settings
    "readyup_ban_duration": 600,  # Queue ban duration in seconds (10 minutes default)
    "readyup_elo_penalty": 10,  # ELO lost when not readying up
    # Required roles - users must have at least one of these Discord roles to queue
    "required_roles": [],
    # Starting ELO role - assigned to new players when they select a region
    "starting_elo_role_id": None,
}
