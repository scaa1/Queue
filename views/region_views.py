# views/region_views.py
"""
Views for region role selection (reaction-role style embed)
"""

import discord

from config import VALID_REGIONS


class RegionRoleView(discord.ui.View):
    """Persistent view for selecting a region role."""

    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.select(
        placeholder="Select your region",
        custom_id="volleyball_region_select",
        options=[
            discord.SelectOption(label="NA (North America)", value="NA"),
            discord.SelectOption(label="EU (Europe)", value="EU"),
            discord.SelectOption(label="Asia", value="Asia"),
            discord.SelectOption(label="OCE (Oceania)", value="OCE"),
        ]
    )
    async def region_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        # Check DMs are enabled before allowing region selection
        try:
            dm_check_msg = await interaction.user.send(
                "✅ DM check passed! You can now select your region and receive match notifications."
            )
            try:
                await dm_check_msg.delete()
            except Exception:
                pass
        except (discord.Forbidden, discord.HTTPException):
            await interaction.response.send_message(
                "You must have DMs enabled to select a region! "
                "The bot needs to DM you match notifications.\n\n"
                "**How to enable:** Server Settings > Privacy Settings > Direct Messages",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        # Check if user is currently in any queue
        in_queue = await self.bot.db.is_user_in_queue(interaction.guild.id, interaction.user.id)
        if in_queue:
            await interaction.followup.send(
                "You cannot change your region while you are in a queue! "
                "Please leave the queue first, then change your region.",
                ephemeral=True
            )
            return

        # Check if user is in an active match
        in_match = await self.bot.db.is_user_in_active_match(interaction.guild.id, interaction.user.id)
        if in_match:
            await interaction.followup.send(
                "You cannot change your region while you are in an active match! "
                "Please finish your current match first.",
                ephemeral=True
            )
            return

        region = select.values[0]
        config = await self.bot.db.get_config(interaction.guild.id)
        region_roles = config.get("region_roles", {})

        role_id = region_roles.get(region)
        if not role_id:
            await interaction.followup.send(
                f"The **{region}** region role has not been configured yet. Please ask an admin to set it up.",
                ephemeral=True
            )
            return

        role = interaction.guild.get_role(role_id)
        if not role:
            await interaction.followup.send(
                f"The role for **{region}** no longer exists. Please ask an admin to reconfigure it.",
                ephemeral=True
            )
            return

        member = interaction.guild.get_member(interaction.user.id)
        if not member:
            await interaction.followup.send("Could not find your member data.", ephemeral=True)
            return

        # Remove all other region roles first
        roles_to_remove = []
        for r_name, r_id in region_roles.items():
            if r_name != region and r_id:
                existing_role = interaction.guild.get_role(r_id)
                if existing_role and existing_role in member.roles:
                    roles_to_remove.append(existing_role)

        roles_to_add = []
        if role not in member.roles:
            roles_to_add.append(role)

        # Auto-assign starting ELO rank role if they don't have one yet
        starting_elo_role = await self._get_starting_elo_role(interaction.guild)
        if starting_elo_role and starting_elo_role not in member.roles:
            has_elo_role = await self._has_any_elo_role(interaction.guild, member)
            if not has_elo_role:
                roles_to_add.append(starting_elo_role)

        try:
            if roles_to_remove:
                await member.remove_roles(*roles_to_remove, reason="Region role change")
            if roles_to_add:
                await member.add_roles(*roles_to_add, reason=f"Selected region: {region}")
        except discord.Forbidden:
            await interaction.followup.send(
                "I don't have permission to manage roles. Please check my role hierarchy.",
                ephemeral=True
            )
            return

        # Store region in database
        await self.bot.db.set_player_region(interaction.guild.id, interaction.user.id, region)

        msg = f"Your region has been set to **{region}**! Role {role.mention} assigned."
        if starting_elo_role and starting_elo_role in roles_to_add:
            msg += f"\nStarting ELO rank role {starting_elo_role.mention} also assigned."

        await interaction.followup.send(msg, ephemeral=True)

        # Send DM confirming region selection
        try:
            guild_name = interaction.guild.name
            dm_embed = discord.Embed(
                title="🌍 Region Selected!",
                description=(
                    f"Your region has been set to **{region}** in **{guild_name}**!\n\n"
                    f"You'll be matched with other **{region}** players in queue.\n"
                    f"You can change your region at any time from the region selection channel."
                ),
                color=discord.Color.blue()
            )
            await interaction.user.send(embed=dm_embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def _get_starting_elo_role(self, guild):
        """Get the starting ELO role from config, or fall back to lowest threshold role."""
        config = await self.bot.db.get_config(guild.id)
        starting_role_id = config.get("starting_elo_role_id")
        if starting_role_id:
            role = guild.get_role(starting_role_id)
            if role:
                return role

        # Fallback: lowest ELO threshold role
        mappings = await self.bot.db.get_all_elo_role_mappings(guild.id)
        if not mappings:
            return None

        lowest = None
        for pos, elo_thresh, role_id in mappings:
            if lowest is None or elo_thresh < lowest[0]:
                lowest = (elo_thresh, role_id)

        if lowest:
            return guild.get_role(lowest[1])
        return None

    async def _has_any_elo_role(self, guild, member):
        """Check if the member already has any ELO role."""
        mappings = await self.bot.db.get_all_elo_role_mappings(guild.id)
        for pos, elo_thresh, role_id in mappings:
            role = guild.get_role(role_id)
            if role and role in member.roles:
                return True
        return False


def build_region_embed():
    """Build the region role selection embed."""
    embed = discord.Embed(
        title="Select Your Region",
        description="Choose your region below to get the corresponding role.\nThis helps us organize regional matchmaking and leaderboards.",
        color=discord.Color.blue()
    )

    region_text = ""
    for region in VALID_REGIONS:
        region_text += f"**{region}**\n"

    embed.add_field(
        name="Available Regions",
        value=region_text,
        inline=False
    )
    embed.set_footer(text="You can change your region at any time by selecting a different one")
    return embed
