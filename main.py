# main.py
"""
Volleyball ELO Bot - Main Entry Point

This bot manages volleyball matchmaking with ELO ratings for Discord servers.
"""

import os
from bot import VolleyballBot
from config import BOT_TOKEN, ALLOWED_GUILD_ID

def main():
    # Check if bot token is set
    if not BOT_TOKEN:
        print("ERROR: Bot token not found!")
        print("Please set the DISCORD_BOT_TOKEN environment variable.")
        print("Example: export DISCORD_BOT_TOKEN='your-bot-token-here'")
        return
    
    # Display guild restriction status
    if ALLOWED_GUILD_ID > 0:
        print(f"Guild restriction is ENABLED. Bot will only operate in guild ID: {ALLOWED_GUILD_ID}")
    else:
        print("Guild restriction is DISABLED. Bot will operate in all guilds it's added to.")
        print("To enable restriction, set the ALLOWED_GUILD_ID environment variable.")
        print("Example: export ALLOWED_GUILD_ID='your-guild-id-here'")
    
    # Create and run the bot
    bot = VolleyballBot()
    
    try:
        bot.run(BOT_TOKEN)
    except Exception as e:
        print(f"Error running bot: {e}")

if __name__ == "__main__":
    main()