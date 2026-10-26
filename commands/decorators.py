# commands/decorators.py
"""
Shared decorators and checks for commands
"""

import discord
from discord import app_commands
from utils import create_error_embed


def has_staff():
    """Check if user has any staff role (senior or normal) or is administrator"""
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True

        config = await interaction.client.db.get_config(interaction.guild_id)
        senior_roles = config.get("staff_senior_roles", [])
        normal_roles = config.get("staff_normal_roles", [])
        all_staff_roles = senior_roles + normal_roles

        if not all_staff_roles:
            await interaction.response.send_message(
                embed=create_error_embed("This command requires administrator permissions or a configured staff role."),
                ephemeral=True
            )
            return False

        user_role_ids = [role.id for role in interaction.user.roles]
        has_role = any(role_id in all_staff_roles for role_id in user_role_ids)

        if not has_role:
            role_mentions = [f"<@&{role_id}>" for role_id in all_staff_roles]
            await interaction.response.send_message(
                embed=create_error_embed(f"This command requires one of these roles: {', '.join(role_mentions)}"),
                ephemeral=True
            )
            return False

        return True

    return app_commands.check(predicate)


def has_senior_staff():
    """Check if user has senior staff role or is administrator"""
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True

        config = await interaction.client.db.get_config(interaction.guild_id)
        senior_roles = config.get("staff_senior_roles", [])

        if not senior_roles:
            await interaction.response.send_message(
                embed=create_error_embed("This command requires administrator permissions or a Senior Staff role."),
                ephemeral=True
            )
            return False

        user_role_ids = [role.id for role in interaction.user.roles]
        has_role = any(role_id in senior_roles for role_id in user_role_ids)

        if not has_role:
            role_mentions = [f"<@&{role_id}>" for role_id in senior_roles]
            await interaction.response.send_message(
                embed=create_error_embed(f"This command requires one of these roles: {', '.join(role_mentions)}"),
                ephemeral=True
            )
            return False

        return True

    return app_commands.check(predicate)


# Keep backward compatibility alias
has_mod_role = has_staff
