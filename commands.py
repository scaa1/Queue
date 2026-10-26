# commands.py
"""
Main commands module that loads all command cogs
This file now simply serves as the entry point for loading
all the modularized command groups.
"""

async def setup(bot):
    """
    Load all command modules from the commands package.
    This function is called by bot.load_extension('commands') in bot.py
    """
    # Import the setup function from the commands package
    from commands import setup as commands_setup
    
    # Load all command cogs
    await commands_setup(bot)