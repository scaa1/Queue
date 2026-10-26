# views/match_views.py
"""
Views related to match management, ready checks, and results
"""

import discord
from discord import app_commands
import json
import time
from datetime import datetime
import asyncio

from config import VALID_POSITIONS, POSITION_EMOJIS
from utils import format_elo_change


class ReadyCheckView(discord.ui.View):
    def __init__(self, bot, match_id, team1_players, team2_players, timeout_seconds=300, match_type='6v6',
                 text_channel_id=None, voice_channel_id=None):
        super().__init__(timeout=timeout_seconds)
        self.bot = bot
        self.match_id = match_id
        self.team1_players = team1_players  # List of (user_id, position) tuples
        self.team2_players = team2_players
        self.ready_players = set()
        self.all_players = set([p[0] for p in team1_players] + [p[0] for p in team2_players])
        self.match_started = False
        self.timeout_seconds = timeout_seconds
        self.start_time = time.time()
        self.message = None  # Will be set after sending
        self._reminder_task = None
        self.match_type = match_type
        self.text_channel_id = text_channel_id
        self.voice_channel_id = voice_channel_id

    def _progress_bar(self, current, total, length=18):
        """Build a text progress bar."""
        filled = int(length * current / total) if total > 0 else 0
        bar = '\u2588' * filled + '\u2591' * (length - filled)
        pct = int(current / total * 100) if total > 0 else 0
        return f"`{bar}` **{pct}%**"

    async def build_ready_embed(self, guild_id=None):
        """Build the full ready check embed in the new layout."""
        if guild_id is None:
            # Try to get guild_id from stored channel
            if self.text_channel_id:
                ch = self.bot.get_channel(self.text_channel_id)
                guild_id = ch.guild.id if ch else None

        remaining = max(0, self.timeout_seconds - (time.time() - self.start_time))
        minutes = int(remaining // 60)
        seconds = int(remaining % 60)

        ready_count = len(self.ready_players)
        total_count = len(self.all_players)

        match_label = self.match_type.upper()
        if self.match_type == 'highrank':
            match_label = "HIGH RANK"
        elif self.match_type == 'highrank_2v2':
            match_label = "HIGH RANK 2V2"
        elif self.match_type == 'highrank_3v3':
            match_label = "HIGH RANK 3V3"

        vc = self.bot.get_channel(self.voice_channel_id) if self.voice_channel_id else None

        embed = discord.Embed(
            title=f"\u23f3 MATCH #{self.match_id} \u2022 {match_label} READY CHECK",
            description=(
                f"\u23f3 **{minutes:02d}:{seconds:02d}**\n"
                f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
            ),
            color=discord.Color.orange()
        )

        # Build team displays
        team1_lines = []
        for user_id, position in self.team1_players:
            user = self.bot.get_user(user_id)
            mention = user.mention if user else f'<@{user_id}>'
            elo = await self._get_elo(guild_id, user_id, position) if guild_id else 0
            status_emoji = "\U0001f7e2" if user_id in self.ready_players else "\U0001f7e1"

            if self.match_type in ('2v2', '3v3', 'highrank_2v2', 'highrank_3v3'):
                team1_lines.append(f"{status_emoji} {mention}\n\u2003**{elo}** MMR")
            else:
                team1_lines.append(f"{status_emoji} {mention}\n\u2003{position} \u2022 **{elo}** ELO")

        team2_lines = []
        for user_id, position in self.team2_players:
            user = self.bot.get_user(user_id)
            mention = user.mention if user else f'<@{user_id}>'
            elo = await self._get_elo(guild_id, user_id, position) if guild_id else 0
            status_emoji = "\U0001f7e2" if user_id in self.ready_players else "\U0001f7e1"

            if self.match_type in ('2v2', '3v3', 'highrank_2v2', 'highrank_3v3'):
                team2_lines.append(f"{status_emoji} {mention}\n\u2003**{elo}** MMR")
            else:
                team2_lines.append(f"{status_emoji} {mention}\n\u2003{position} \u2022 **{elo}** ELO")

        embed.add_field(
            name="\U0001f7e6 TEAM A",
            value="\n\n".join(team1_lines) if team1_lines else "Empty",
            inline=True
        )
        embed.add_field(
            name="\U0001f7e5 TEAM B",
            value="\n\n".join(team2_lines) if team2_lines else "Empty",
            inline=True
        )

        # Ready status with progress bar
        progress = self._progress_bar(ready_count, total_count)
        embed.add_field(
            name="READY STATUS",
            value=f"**{ready_count} / {total_count} READY**\n{progress}",
            inline=False
        )

        if vc:
            embed.set_footer(text=f"Voice: {vc.name} \u2022 Join VC to auto-ready!")

        return embed
        
    def start_reminder_task(self, message):
        """Start the background task that updates the timer and re-pings unready players."""
        self.message = message
        self._reminder_task = asyncio.create_task(self._reminder_loop())

    async def _reminder_loop(self):
        """Periodically update the timer on the embed and re-ping unready players."""
        try:
            reminder_interval = 60  # Re-ping every 60 seconds
            timer_update_interval = 15  # Update timer display every 15 seconds
            last_ping_time = self.start_time

            while not self.match_started:
                await asyncio.sleep(timer_update_interval)

                if self.match_started or self.message is None:
                    break

                elapsed = time.time() - self.start_time
                remaining = max(0, self.timeout_seconds - elapsed)

                if remaining <= 0:
                    break

                # Rebuild the embed with the updated timer
                try:
                    guild_id = self.message.guild.id if self.message.guild else None
                    embed = await self.build_ready_embed(guild_id)
                    await self.message.edit(embed=embed, view=self)
                except Exception:
                    pass

                # Re-ping unready players every reminder_interval
                now = time.time()
                if now - last_ping_time >= reminder_interval:
                    last_ping_time = now
                    not_ready = self.all_players - self.ready_players
                    if not_ready and not self.match_started:
                        mentions = " ".join([f"<@{uid}>" for uid in not_ready])
                        expire_ts = int(self.start_time + self.timeout_seconds)
                        try:
                            channel = self.message.channel
                            reminder_msg = await channel.send(
                                f"\u23f0 **Ready up!** {mentions} \u2014 Expires <t:{expire_ts}:R>!"
                            )
                            # Delete reminder after 30 seconds to reduce clutter
                            await asyncio.sleep(30)
                            try:
                                await reminder_msg.delete()
                            except Exception:
                                pass
                        except Exception:
                            pass
        except asyncio.CancelledError:
            pass

    @discord.ui.button(label="\u2705 I'M READY", style=discord.ButtonStyle.success)
    async def ready_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.all_players:
            await interaction.response.send_message("You're not in this match!", ephemeral=True)
            return

        if interaction.user.id in self.ready_players:
            await interaction.response.send_message("You're already marked as ready!", ephemeral=True)
            return

        self.ready_players.add(interaction.user.id)

        await interaction.response.defer()
        await self.update_embed(interaction)

        # Announce in chat
        try:
            ready_count = len(self.ready_players)
            total_count = len(self.all_players)
            channel = interaction.message.channel if interaction.message else interaction.channel
            await channel.send(
                f"\u2705 {interaction.user.mention} is ready! ({ready_count}/{total_count})"
            )
        except Exception:
            pass

        # Check if all players are ready
        if len(self.ready_players) == len(self.all_players):
            await self.start_match(interaction)

    @discord.ui.button(label="\u274c NOT READY", style=discord.ButtonStyle.danger)
    async def not_ready_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.all_players:
            await interaction.response.send_message("You're not in this match!", ephemeral=True)
            return

        if interaction.user.id not in self.ready_players:
            await interaction.response.send_message("You haven't marked yourself as ready yet!", ephemeral=True)
            return

        self.ready_players.remove(interaction.user.id)

        await interaction.response.defer()
        await self.update_embed(interaction)
        
    async def _get_elo(self, guild_id, user_id, position):
        """Get ELO using the correct function for the match type."""
        if self.match_type in ('2v2', '3v3'):
            return await self.bot.db.get_player_elo_simple(guild_id, user_id, self.match_type)
        elif self.match_type == 'highrank':
            return await self.bot.db.get_player_elo_highrank(guild_id, user_id, position)
        elif self.match_type in ('highrank_2v2', 'highrank_3v3'):
            return await self.bot.db.get_player_elo_simple(guild_id, user_id, self.match_type)
        else:
            return await self.bot.db.get_player_elo(guild_id, user_id, position)

    async def update_embed(self, interaction: discord.Interaction):
        # Handle both real interactions and fake ones from voice updates
        if hasattr(interaction, 'message'):
            message = interaction.message
        else:
            message = interaction.message

        guild_id = interaction.guild_id if hasattr(interaction, 'guild_id') else message.guild.id
        embed = await self.build_ready_embed(guild_id)
        await message.edit(embed=embed, view=self)
        
    async def start_match(self, interaction: discord.Interaction):
        self.match_started = True

        # Cancel the reminder task
        if self._reminder_task and not self._reminder_task.done():
            self._reminder_task.cancel()

        # Clean up from bot's ready check views
        if self.match_id in self.bot.ready_check_views:
            del self.bot.ready_check_views[self.match_id]
        
        # Disable all buttons
        for item in self.children:
            item.disabled = True
            
        # Handle both real and fake interactions
        if hasattr(interaction, 'message'):
            message = interaction.message
        else:
            message = interaction.message
            
        embed = message.embeds[0]
        embed.color = discord.Color.green()
        embed.title = f"🏐 Match #{self.match_id} - Started!"
        
        # Get voice channel info and move players
        match_channels = await self.bot.db.get_match_channels(self.match_id)
        voice_channel = None
        if match_channels and match_channels[1]:
            voice_channel = self.bot.get_channel(match_channels[1])
            if voice_channel:
                embed.add_field(
                    name="🎙️ Voice Channel",
                    value=f"Join: {voice_channel.mention}",
                    inline=False
                )
                
                # Move all players to the voice channel
                guild = voice_channel.guild
                moved_count = 0
                failed_moves = []
                
                for user_id in self.all_players:
                    member = guild.get_member(user_id)
                    if member and member.voice:  # Check if member is in a voice channel
                        try:
                            await member.move_to(voice_channel)
                            moved_count += 1
                        except discord.Forbidden:
                            failed_moves.append(member.name)
                        except discord.HTTPException:
                            failed_moves.append(member.name)
                
                # Add status about moving players
                if moved_count > 0:
                    move_status = f"✅ Moved {moved_count} player(s) to match voice channel"
                    if failed_moves:
                        move_status += f"\n⚠️ Could not move: {', '.join(failed_moves)}"
                    embed.add_field(name="🎙️ Voice Status", value=move_status, inline=False)
        
        await message.edit(embed=embed, view=self)
        
        # Send match result view
        result_view = MatchResultView(self.bot, self.match_id, self.team1_players, self.team2_players, match_type=self.match_type)
        
        result_embed = discord.Embed(
            title=f"🏐 Match #{self.match_id} - In Progress",
            description="Report the match results below once completed.",
            color=discord.Color.blue()
        )
        
        # Get the text channel to send the result view
        if match_channels and match_channels[0]:
            text_channel = self.bot.get_channel(match_channels[0])
            if text_channel:
                await text_channel.send(embed=result_embed, view=result_view)
        
    async def on_timeout(self):
        if not self.match_started:
            # Cancel the reminder task
            if self._reminder_task and not self._reminder_task.done():
                self._reminder_task.cancel()

            # Cancel the match if not all players were ready
            # Disable all buttons
            for child in self.children:
                child.disabled = True

            # Update the embed to show timeout
            if self.message:
                try:
                    embed = self.message.embeds[0] if self.message.embeds else None
                    if embed:
                        embed.color = discord.Color.red()
                        embed.title = f"❌ Match #{self.match_id} - Ready Check Failed"

                        not_ready = self.all_players - self.ready_players
                        not_ready_text = ""
                        for uid in not_ready:
                            user = self.bot.get_user(uid)
                            not_ready_text += f"❌ {user.mention if user else f'User {uid}'}\n"

                        if not_ready_text:
                            embed.add_field(
                                name="Players who didn't ready up",
                                value=not_ready_text,
                                inline=False
                            )

                        await self.message.edit(embed=embed, view=self)
                except Exception:
                    pass

            # Log who didn't ready up and apply penalties
            not_ready = self.all_players - self.ready_players
            guild_id = None
            match_channels = await self.bot.db.get_match_channels(self.match_id)

            if not_ready:
                not_ready_mentions = []
                for uid in not_ready:
                    user = self.bot.get_user(uid)
                    not_ready_mentions.append(user.mention if user else f"User {uid}")
                # Determine guild_id from match channels
                if match_channels and match_channels[0]:
                    ch = self.bot.get_channel(match_channels[0])
                    if ch and ch.guild:
                        guild_id = ch.guild.id
                if guild_id is None:
                    # Fallback: find guild from players
                    for uid in self.all_players:
                        for guild in self.bot.guilds:
                            if guild.get_member(uid):
                                guild_id = guild.id
                                break
                        if guild_id:
                            break
                if guild_id:
                    config = await self.bot.db.get_config(guild_id)
                    ban_duration = config.get("readyup_ban_duration", 600)
                    elo_penalty = config.get("readyup_elo_penalty", 10)

                    # Apply queue ban and ELO penalty to players who didn't ready up
                    penalty_lines = []
                    for uid in not_ready:
                        user = self.bot.get_user(uid)
                        name = user.mention if user else f"User {uid}"
                        # Apply queue ban
                        if ban_duration > 0:
                            await self.bot.db.add_queue_ban(guild_id, uid, ban_duration)
                        # Apply ELO penalty
                        if elo_penalty > 0:
                            # Find the player's position in this match
                            player_position = None
                            for pid, pos in self.team1_players + self.team2_players:
                                if pid == uid:
                                    player_position = pos
                                    break
                            if player_position:
                                match_type = self.match_type
                                starting_elo = config.get("starting_elo", 650)
                                if match_type in ('2v2', '3v3'):
                                    await self.bot.db.update_player_elo_simple(
                                        guild_id, uid, match_type,
                                        -elo_penalty, False, starting_elo
                                    )
                                elif match_type == 'highrank':
                                    await self.bot.db.update_player_elo_highrank(
                                        guild_id, uid, player_position,
                                        -elo_penalty, False, starting_elo
                                    )
                                elif match_type in ('highrank_2v2', 'highrank_3v3'):
                                    await self.bot.db.update_player_elo_simple(
                                        guild_id, uid, match_type,
                                        -elo_penalty, False, starting_elo
                                    )
                                else:
                                    await self.bot.db.update_player_elo(
                                        guild_id, uid, player_position,
                                        -elo_penalty, False, starting_elo
                                    )
                        penalty_parts = []
                        if ban_duration > 0:
                            penalty_parts.append(f"queue banned {ban_duration // 60}m")
                        if elo_penalty > 0:
                            penalty_parts.append(f"-{elo_penalty} ELO")
                        penalty_lines.append(f"{name} — {', '.join(penalty_parts)}" if penalty_parts else name)

                    # Send penalty info to the match channel
                    if self.message:
                        try:
                            penalty_text = "\n".join(penalty_lines)
                            penalty_embed = discord.Embed(
                                title="Penalties Applied",
                                description=penalty_text,
                                color=discord.Color.red()
                            )
                            await self.message.channel.send(embed=penalty_embed)
                        except Exception:
                            pass

                    # DM players who didn't ready up about their penalties
                    for uid in not_ready:
                        user = self.bot.get_user(uid)
                        if user:
                            try:
                                dm_parts = []
                                if ban_duration > 0:
                                    dm_parts.append(f"Queue banned for {ban_duration // 60} minutes")
                                if elo_penalty > 0:
                                    dm_parts.append(f"-{elo_penalty} ELO")
                                dm_embed = discord.Embed(
                                    title=f"❌ Ready Check Failed — Match #{self.match_id}",
                                    description=(
                                        "You did not ready up in time and the match has been cancelled.\n\n"
                                        + ("**Penalties:**\n" + "\n".join(f"• {p}" for p in dm_parts) if dm_parts else "")
                                    ),
                                    color=discord.Color.red()
                                )
                                await user.send(embed=dm_embed)
                            except discord.Forbidden:
                                pass
                            except Exception:
                                pass

                    await self.bot.log_action(
                        guild_id,
                        f"Ready Check Failed — Match #{self.match_id}",
                        f"**Players who didn't ready up:**\n" + "\n".join(not_ready_mentions),
                        color=discord.Color.red(),
                        log_type="readyup"
                    )

            # Clean up from bot's ready check views
            if self.match_id in self.bot.ready_check_views:
                del self.bot.ready_check_views[self.match_id]

            # Mark match as inactive
            await self.bot.db.set_match_inactive(self.match_id)

            # Delete match channels (text + voice)
            if match_channels is None:
                match_channels = await self.bot.db.get_match_channels(self.match_id)
            if match_channels:
                text_channel_id, voice_channel_id = match_channels
                if text_channel_id:
                    text_channel = self.bot.get_channel(text_channel_id)
                    if text_channel:
                        try:
                            # Small delay so players can see the timeout message
                            await asyncio.sleep(15)
                            await text_channel.delete(reason=f"Match #{self.match_id} ready check failed")
                        except Exception:
                            pass
                if voice_channel_id:
                    voice_channel = self.bot.get_channel(voice_channel_id)
                    if voice_channel:
                        try:
                            await voice_channel.delete(reason=f"Match #{self.match_id} ready check failed")
                        except Exception:
                            pass


class MatchResultView(discord.ui.View):
    def __init__(self, bot, match_id, team1_players, team2_players, match_type='6v6'):
        super().__init__(timeout=3600)  # 1 hour timeout
        self.bot = bot
        self.match_id = match_id
        self.team1_players = team1_players  # List of (user_id, position) tuples
        self.team2_players = team2_players
        self.votes = {"team1": set(), "team2": set()}
        self.team1_score = 0
        self.team2_score = 0
        self.result_reported = False
        self.match_type = match_type

        # Get all player IDs for validation
        self.all_players = set([p[0] for p in team1_players] + [p[0] for p in team2_players])
        
    async def has_mod_permissions(self, user: discord.Member) -> bool:
        """Check if user has staff permissions (senior or normal)"""
        if user.guild_permissions.administrator:
            return True

        config = await self.bot.db.get_config(user.guild.id)
        senior_roles = config.get("staff_senior_roles", [])
        normal_roles = config.get("staff_normal_roles", [])
        all_staff = senior_roles + normal_roles

        if all_staff:
            user_role_ids = [role.id for role in user.roles]
            return any(role_id in all_staff for role_id in user_role_ids)

        return False
        
    def get_required_votes(self):
        """Calculate required votes (majority of players)"""
        total_players = len(self.all_players)
        return (total_players // 2) + 1
        
    async def check_result_consensus(self):
        """Check if there's consensus on the result"""
        required = self.get_required_votes()
        
        if len(self.votes["team1"]) >= required:
            return 1
        elif len(self.votes["team2"]) >= required:
            return 2
        return None
        
    async def _get_elo(self, guild_id, user_id, position):
        """Get ELO using the correct function for the match type."""
        if self.match_type in ('2v2', '3v3'):
            return await self.bot.db.get_player_elo_simple(guild_id, user_id, self.match_type)
        elif self.match_type == 'highrank':
            return await self.bot.db.get_player_elo_highrank(guild_id, user_id, position)
        elif self.match_type in ('highrank_2v2', 'highrank_3v3'):
            return await self.bot.db.get_player_elo_simple(guild_id, user_id, self.match_type)
        else:
            return await self.bot.db.get_player_elo(guild_id, user_id, position)

    async def update_embed(self, interaction: discord.Interaction):
        """Update the match embed with current vote status"""
        embed = interaction.message.embeds[0]

        # Create team displays similar to queue format
        team1_text = ""
        team2_text = ""

        for user_id, position in self.team1_players:
            user = self.bot.get_user(user_id)
            elo = await self._get_elo(interaction.guild_id, user_id, position)
            if self.match_type in ('2v2', '3v3', 'highrank_2v2', 'highrank_3v3'):
                team1_text += f"🏐 {user.mention if user else f'User {user_id}'} ({elo} MMR)\n"
            else:
                emoji = POSITION_EMOJIS.get(position, "🏐")
                team1_text += f"{emoji} {user.mention if user else f'User {user_id}'} ({position}) - {elo} ELO\n"

        for user_id, position in self.team2_players:
            user = self.bot.get_user(user_id)
            elo = await self._get_elo(interaction.guild_id, user_id, position)
            if self.match_type in ('2v2', '3v3', 'highrank_2v2', 'highrank_3v3'):
                team2_text += f"🏐 {user.mention if user else f'User {user_id}'} ({elo} MMR)\n"
            else:
                emoji = POSITION_EMOJIS.get(position, "🏐")
                team2_text += f"{emoji} {user.mention if user else f'User {user_id}'} ({position}) - {elo} ELO\n"
        
        # Clear and re-add fields
        embed.clear_fields()
        embed.add_field(name="🔴 Team 1", value=team1_text.strip(), inline=True)
        embed.add_field(name="🔵 Team 2", value=team2_text.strip(), inline=True)
        
        # Add voting status
        vote_status = f"Team 1 votes: {len(self.votes['team1'])}\nTeam 2 votes: {len(self.votes['team2'])}\nRequired: {self.get_required_votes()}"
        embed.add_field(name="📊 Vote Status", value=vote_status, inline=False)
        
        await interaction.message.edit(embed=embed, view=self)
        
    @discord.ui.button(label="🔴 Team 1 Won", style=discord.ButtonStyle.danger, row=0)
    async def team1_won(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.all_players:
            await interaction.response.send_message("You're not in this match!", ephemeral=True)
            return

        if self.result_reported:
            await interaction.response.send_message("Result already reported!", ephemeral=True)
            return

        # Remove from other team's votes if present
        self.votes["team2"].discard(interaction.user.id)
        self.votes["team1"].add(interaction.user.id)

        await interaction.response.defer()

        # Check if we have consensus
        winner = await self.check_result_consensus()
        if winner:
            await self.finalize_result(interaction, winner)
        else:
            await self.update_embed(interaction)
            await interaction.followup.send(f"Vote recorded for Team 1! ({len(self.votes['team1'])}/{self.get_required_votes()} needed)", ephemeral=True)

    @discord.ui.button(label="🔵 Team 2 Won", style=discord.ButtonStyle.primary, row=0)
    async def team2_won(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.all_players:
            await interaction.response.send_message("You're not in this match!", ephemeral=True)
            return

        if self.result_reported:
            await interaction.response.send_message("Result already reported!", ephemeral=True)
            return

        # Remove from other team's votes if present
        self.votes["team1"].discard(interaction.user.id)
        self.votes["team2"].add(interaction.user.id)

        await interaction.response.defer()

        # Check if we have consensus
        winner = await self.check_result_consensus()
        if winner:
            await self.finalize_result(interaction, winner)
        else:
            await self.update_embed(interaction)
            await interaction.followup.send(f"Vote recorded for Team 2! ({len(self.votes['team2'])}/{self.get_required_votes()} needed)", ephemeral=True)
            
    @discord.ui.button(label="❌ Cancel Match", style=discord.ButtonStyle.secondary, row=1)
    async def cancel_match(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.all_players and not await self.has_mod_permissions(interaction.user):
            await interaction.response.send_message("Only match participants or moderators can cancel matches!", ephemeral=True)
            return
            
        # For players, require confirmation from majority
        if not await self.has_mod_permissions(interaction.user):
            # TODO: Implement player voting for cancellation
            await interaction.response.send_message("Match cancellation by players is not yet implemented. Please ask a moderator.", ephemeral=True)
            return
            
        await interaction.response.defer()
        
        # Mark match as inactive
        await self.bot.db.set_match_inactive(self.match_id)
        
        # Clean up ready check view
        if self.match_id in self.bot.ready_check_views:
            del self.bot.ready_check_views[self.match_id]
        
        # Clean up channels
        await self.cleanup_match_channels(interaction)
        
        # Update embed to show cancelled
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.red()
        embed.title = f"❌ Match #{self.match_id} - Cancelled"
        
        # Disable all buttons
        for item in self.children:
            item.disabled = True
            
        await interaction.message.edit(embed=embed, view=self)
        await interaction.followup.send("Match cancelled by administrator.", ephemeral=True)
        
    @discord.ui.button(label="🔨 Manual Select Winner", style=discord.ButtonStyle.danger, row=2, emoji="🛡️")
    async def manual_select(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Moderator-only button to manually select a winner"""
        if not await self.has_mod_permissions(interaction.user):
            await interaction.response.send_message("This action requires moderator permissions!", ephemeral=True)
            return
            
        if self.result_reported:
            await interaction.response.send_message("Result already reported! Use the Revert button first if you need to change it.", ephemeral=True)
            return
            
        # Create a view with team selection buttons
        select_view = ManualWinnerSelectView(self, interaction.user)
        
        embed = discord.Embed(
            title="🛡️ Manual Winner Selection",
            description="Select which team won this match:",
            color=discord.Color.orange()
        )
        
        embed.set_footer(text=f"Initiated by {interaction.user}")
        
        # Show team compositions
        team1_text = ""
        team2_text = ""
        
        for user_id, position in self.team1_players:
            user = self.bot.get_user(user_id)
            emoji = POSITION_EMOJIS.get(position, "🏐")
            team1_text += f"{emoji} {user.mention if user else f'User {user_id}'} ({position})\n"
            
        for user_id, position in self.team2_players:
            user = self.bot.get_user(user_id)
            emoji = POSITION_EMOJIS.get(position, "🏐")
            team2_text += f"{emoji} {user.mention if user else f'User {user_id}'} ({position})\n"
            
        embed.add_field(name="🔴 Team 1", value=team1_text, inline=True)
        embed.add_field(name="🔵 Team 2", value=team2_text, inline=True)
        
        await interaction.response.send_message(embed=embed, view=select_view, ephemeral=True)
        
    async def cleanup_match_channels(self, interaction: discord.Interaction):
        """Delete the match channels"""
        match_channels = await self.bot.db.get_match_channels(self.match_id)
        if match_channels:
            text_channel_id, voice_channel_id = match_channels
            
            # Delete text channel
            if text_channel_id:
                text_channel = self.bot.get_channel(text_channel_id)
                if text_channel:
                    try:
                        await text_channel.delete(reason=f"Match #{self.match_id} ended")
                    except:
                        pass
                        
            # Delete voice channel
            if voice_channel_id:
                voice_channel = self.bot.get_channel(voice_channel_id)
                if voice_channel:
                    try:
                        await voice_channel.delete(reason=f"Match #{self.match_id} ended")
                    except:
                        pass

    async def update_elo_roles(self, interaction: discord.Interaction, elo_changes):
        """Update ELO-based roles for players after a match"""
        # Get all ELO role mappings (v2 includes queue_type)
        all_mappings = await self.bot.db.get_all_elo_role_mappings_v2(interaction.guild.id)
        if not all_mappings:
            return  # No roles configured

        # Determine match type for filtering relevant mappings
        match_type = self.match_type

        # Map match_type to the queue_type used in elo_role_mappings
        if match_type == 'highrank':
            relevant_queue_type = 'highrank'
        elif match_type in ('highrank_2v2', 'highrank_3v3'):
            relevant_queue_type = match_type
        elif match_type in ('2v2', '3v3'):
            relevant_queue_type = match_type
        else:
            relevant_queue_type = '6v6'

        # Filter mappings for the relevant queue type
        mappings = [(pos, elo, role_id) for pos, elo, role_id, qt in all_mappings if qt == relevant_queue_type]
        if not mappings:
            return

        for user_id, position, change, old_elo, new_elo in elo_changes:
            member = interaction.guild.get_member(user_id)
            if not member:
                continue

            # Build position ELO map based on match type
            if match_type in ('2v2', '3v3', 'highrank_2v2', 'highrank_3v3'):
                # Singular MMR - only "all" position matters
                pos_elos = {"all": new_elo}
            elif match_type == 'highrank':
                # High rank 6v6 - per-position
                stats = await self.bot.db.get_player_stats_highrank(interaction.guild.id, user_id)
                if not stats:
                    continue
                ds_elo, fs_elo, s_elo, l_elo, games, wins, losses = stats
                ds_games = await self.bot.db.get_position_games_played_highrank(interaction.guild.id, user_id, "Defense Specialist")
                fs_games = await self.bot.db.get_position_games_played_highrank(interaction.guild.id, user_id, "Front Spiker")
                s_games = await self.bot.db.get_position_games_played_highrank(interaction.guild.id, user_id, "Setter")
                l_games = await self.bot.db.get_position_games_played_highrank(interaction.guild.id, user_id, "Libero")
                played = []
                if ds_games > 0: played.append(ds_elo)
                if fs_games > 0: played.append(fs_elo)
                if s_games > 0: played.append(s_elo)
                if l_games > 0: played.append(l_elo)
                avg = sum(played) / len(played) if played else 0
                pos_elos = {
                    "Defense Specialist": ds_elo if ds_games > 0 else 0,
                    "Front Spiker": fs_elo if fs_games > 0 else 0,
                    "Setter": s_elo if s_games > 0 else 0,
                    "Libero": l_elo if l_games > 0 else 0,
                    "all": avg
                }
            else:
                # Normal 6v6 - per-position
                stats = await self.bot.db.get_player_stats(interaction.guild.id, user_id)
                if not stats:
                    continue
                ds_elo, fs_elo, s_elo, l_elo, games, wins, losses = stats
                ds_games = await self.bot.db.get_position_games_played(interaction.guild.id, user_id, "Defense Specialist")
                fs_games = await self.bot.db.get_position_games_played(interaction.guild.id, user_id, "Front Spiker")
                s_games = await self.bot.db.get_position_games_played(interaction.guild.id, user_id, "Setter")
                l_games = await self.bot.db.get_position_games_played(interaction.guild.id, user_id, "Libero")
                played = []
                if ds_games > 0: played.append(ds_elo)
                if fs_games > 0: played.append(fs_elo)
                if s_games > 0: played.append(s_elo)
                if l_games > 0: played.append(l_elo)
                avg = sum(played) / len(played) if played else 0
                pos_elos = {
                    "Defense Specialist": ds_elo if ds_games > 0 else 0,
                    "Front Spiker": fs_elo if fs_games > 0 else 0,
                    "Setter": s_elo if s_games > 0 else 0,
                    "Libero": l_elo if l_games > 0 else 0,
                    "all": avg
                }

            to_add, to_remove = [], []
            for pos, elo_thresh, role_id in mappings:
                role = interaction.guild.get_role(role_id)
                if not role:
                    continue

                if pos_elos.get(pos, 0) >= elo_thresh:
                    if role not in member.roles:
                        to_add.append(role)
                else:
                    if role in member.roles:
                        to_remove.append(role)

            try:
                if to_add:
                    await member.add_roles(*to_add, reason="ELO role reward")
                if to_remove:
                    await member.remove_roles(*to_remove, reason="ELO role update")
            except Exception:
                pass
        
    async def finalize_result(self, interaction: discord.Interaction, winning_team: int):
        """Finalize the match result. winning_team: 1=team1, 2=team2, 0=tie"""
        self.result_reported = True

        # Disable all buttons, highlight the winning one
        for item in self.children:
            item.disabled = True
            if isinstance(item, discord.ui.Button):
                if winning_team == 1 and item.label and "Team 1" in item.label:
                    item.style = discord.ButtonStyle.success
                elif winning_team == 2 and item.label and "Team 2" in item.label:
                    item.style = discord.ButtonStyle.success
                elif winning_team == 0 and item.label and "Tie" in item.label:
                    item.style = discord.ButtonStyle.success

        # Get config
        config = await self.bot.db.get_config(interaction.guild_id)
        k_factor = config["k_factor"]
        starting_elo = config["starting_elo"]

        # Determine match type
        match_type = await self.bot.db.get_match_type(self.match_id)

        # Use high rank starting ELO for high rank matches
        if match_type and match_type.startswith("highrank"):
            starting_elo = config.get("high_rank_starting_elo", starting_elo)

        # Handle tie - no ELO changes, just mark match
        if winning_team == 0:
            self.team1_score, self.team2_score = 0, 0
            await self.bot.db.update_match_score(self.match_id, 0, 0)
            await self.bot.db.set_match_inactive(self.match_id)
            if self.match_id in self.bot.ready_check_views:
                del self.bot.ready_check_views[self.match_id]
            await self.bot.post_or_update_leaderboard(interaction.guild_id)

            tie_queue_display = match_type.upper() if match_type else "6V6"
            if match_type == 'highrank':
                tie_queue_display = "High Rank 6v6"
            elif match_type == 'highrank_2v2':
                tie_queue_display = "High Rank 2v2"
            elif match_type == 'highrank_3v3':
                tie_queue_display = "High Rank 3v3"

            embed = interaction.message.embeds[0]
            embed.color = discord.Color.light_grey()
            embed.title = f"🤝 Match #{self.match_id} - Tie ({tie_queue_display})"
            embed.add_field(name="Result", value="**Tie — No ELO changes**", inline=False)
            embed.set_footer(text="🛡️ Moderators can revert this result in the results channel if needed")
            await interaction.message.edit(embed=embed, view=self)

            await self.bot.log_action(
                interaction.guild_id,
                f"Match #{self.match_id} Result",
                f"**Result:** Tie — No ELO changes",
                user=interaction.user,
                color=discord.Color.light_grey()
            )

            if config["results_channel"]:
                channel = self.bot.get_channel(config["results_channel"])
                if channel:
                    result_embed = discord.Embed(
                        title=f"🤝 Match Result — Tie ({tie_queue_display})",
                        description=f"Match #{self.match_id}",
                        color=discord.Color.light_grey(),
                        timestamp=datetime.utcnow()
                    )
                    result_embed.add_field(name="Result", value="**Tie — No ELO changes**", inline=False)
                    result_view = ResultWithTranscriptView(self.bot, self.match_id, winning_team=0)
                    result_msg = await channel.send(embed=result_embed, view=result_view)
                    await self.bot.db.set_result_message_id(self.match_id, interaction.guild.id, result_msg.id)

            await self.cleanup_match_channels(interaction)
            return

        winners = self.team1_players if winning_team == 1 else self.team2_players
        losers = self.team2_players if winning_team == 1 else self.team1_players
        
        # Calculate and update Elo ratings
        elo_changes = []
        
        # First, get all current ELOs before any updates
        current_elos = {}
        for player_data in winners + losers:
            player_id = player_data[0]
            player_position = player_data[1]
            if match_type in ('2v2', '3v3'):
                current_elo = await self.bot.db.get_player_elo_simple(interaction.guild_id, player_id, match_type)
            elif match_type == 'highrank':
                current_elo = await self.bot.db.get_player_elo_highrank(interaction.guild_id, player_id, player_position)
            else:
                current_elo = await self.bot.db.get_player_elo(interaction.guild_id, player_id, player_position)
            current_elos[(player_id, player_position)] = current_elo
        
        # Get match region for regional ELO tracking
        match_region = await self.bot.db.get_match_region(self.match_id)

        # Calculate ELO changes for winners
        for winner_data in winners:
            winner_id = winner_data[0]
            winner_position = winner_data[1]
            
            total_change = 0
            for loser_data in losers:
                loser_id = loser_data[0]
                loser_position = loser_data[1]
                
                winner_elo = current_elos[(winner_id, winner_position)]
                loser_elo = current_elos[(loser_id, loser_position)]
                
                winner_change, loser_change = self.bot.calculate_elo_change(winner_elo, loser_elo, k_factor)
                total_change += winner_change / len(losers)  # Average the change
                
            # Update winner (global ELO)
            if match_type in ('2v2', '3v3'):
                await self.bot.db.update_player_elo_simple(
                    interaction.guild_id, winner_id, match_type,
                    int(total_change), True, starting_elo
                )
            elif match_type == 'highrank':
                await self.bot.db.update_player_elo_highrank(
                    interaction.guild_id, winner_id, winner_position,
                    int(total_change), True, starting_elo
                )
            else:
                await self.bot.db.update_player_elo(
                    interaction.guild_id, winner_id, winner_position,
                    int(total_change), True, starting_elo
                )

            # Also update regional ELO if match has a region
            if match_region:
                if match_type in ('2v2', '3v3'):
                    await self.bot.db.update_player_regional_elo_simple(
                        interaction.guild_id, winner_id, match_region, match_type,
                        int(total_change), True, starting_elo
                    )
                elif match_type not in ('highrank',):
                    await self.bot.db.update_player_regional_elo(
                        interaction.guild_id, winner_id, match_region, winner_position,
                        int(total_change), True, starting_elo
                    )

            old_elo = current_elos[(winner_id, winner_position)]
            new_elo = old_elo + int(total_change)
            elo_changes.append((winner_id, winner_position, int(total_change), old_elo, new_elo))

            # Record ELO history for stats card graph
            await self.bot.db.record_elo_history(
                interaction.guild_id, winner_id, self.match_id,
                match_type or '6v6', winner_position,
                old_elo, new_elo, int(total_change), True
            )

        # Calculate ELO changes for losers
        for loser_data in losers:
            loser_id = loser_data[0]
            loser_position = loser_data[1]
            
            total_change = 0
            for winner_data in winners:
                winner_id = winner_data[0]
                winner_position = winner_data[1]
                
                winner_elo = current_elos[(winner_id, winner_position)]
                loser_elo = current_elos[(loser_id, loser_position)]
                
                winner_change, loser_change = self.bot.calculate_elo_change(winner_elo, loser_elo, k_factor)
                total_change += loser_change / len(winners)  # Average the change
                
            # Update loser (global ELO)
            if match_type in ('2v2', '3v3'):
                await self.bot.db.update_player_elo_simple(
                    interaction.guild_id, loser_id, match_type,
                    int(total_change), False, starting_elo
                )
            elif match_type == 'highrank':
                await self.bot.db.update_player_elo_highrank(
                    interaction.guild_id, loser_id, loser_position,
                    int(total_change), False, starting_elo
                )
            else:
                await self.bot.db.update_player_elo(
                    interaction.guild_id, loser_id, loser_position,
                    int(total_change), False, starting_elo
                )

            # Also update regional ELO if match has a region
            if match_region:
                if match_type in ('2v2', '3v3'):
                    await self.bot.db.update_player_regional_elo_simple(
                        interaction.guild_id, loser_id, match_region, match_type,
                        int(total_change), False, starting_elo
                    )
                elif match_type not in ('highrank',):
                    await self.bot.db.update_player_regional_elo(
                        interaction.guild_id, loser_id, match_region, loser_position,
                        int(total_change), False, starting_elo
                    )

            old_elo = current_elos[(loser_id, loser_position)]
            new_elo = old_elo + int(total_change)
            elo_changes.append((loser_id, loser_position, int(total_change), old_elo, new_elo))

            # Record ELO history for stats card graph
            await self.bot.db.record_elo_history(
                interaction.guild_id, loser_id, self.match_id,
                match_type or '6v6', loser_position,
                old_elo, new_elo, int(total_change), False
            )

        # Set scores to indicate winner (1-0 format)
        if winning_team == 1:
            self.team1_score, self.team2_score = 1, 0
        else:
            self.team1_score, self.team2_score = 0, 1

        # Update match record
        await self.bot.db.update_match_score(self.match_id, self.team1_score, self.team2_score)
        await self.bot.db.set_match_inactive(self.match_id)

        # Clean up ready check view
        if self.match_id in self.bot.ready_check_views:
            del self.bot.ready_check_views[self.match_id]

        # Update leaderboard
        await self.bot.post_or_update_leaderboard(interaction.guild_id)

        # Log match result
        elo_summary = "\n".join([
            f"<@{uid}> ({pos}): {old} -> {new} ({'+' if change >= 0 else ''}{change})"
            for uid, pos, change, old, new in elo_changes
        ])
        await self.bot.log_action(
            interaction.guild_id,
            f"Match #{self.match_id} Result",
            f"**Winner:** Team {winning_team}\n\n**ELO Changes:**\n{elo_summary}",
            user=interaction.user,
            color=discord.Color.gold()
        )

        # Update the match embed
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.gold()
        queue_display = match_type.upper() if match_type else "6V6"
        if match_type == 'highrank':
            queue_display = "High Rank 6v6"
        elif match_type == 'highrank_2v2':
            queue_display = "High Rank 2v2"
        elif match_type == 'highrank_3v3':
            queue_display = "High Rank 3v3"
        embed.title = f"🏆 Match #{self.match_id} - Completed ({queue_display})"
        
        # Add winner field
        embed.add_field(
            name="🎉 Winner",
            value=f"**Team {winning_team}**",
            inline=True
        )
        
        # Add Elo changes field
        elo_text = "**Winners:**\n"
        for user_id, position, change, old_elo, new_elo in elo_changes:
            if (user_id, position) in winners:
                user = self.bot.get_user(user_id)
                pos_text = f" ({position})" if match_type not in ('2v2', '3v3') else ""
                elo_text += f"{user.mention if user else f'User {user_id}'}{pos_text}: **{old_elo}** → **{new_elo}** (+{change})\n"

        elo_text += "\n**Losers:**\n"
        for user_id, position, change, old_elo, new_elo in elo_changes:
            if (user_id, position) in losers:
                user = self.bot.get_user(user_id)
                pos_text = f" ({position})" if match_type not in ('2v2', '3v3') else ""
                elo_text += f"{user.mention if user else f'User {user_id}'}{pos_text}: **{old_elo}** → **{new_elo}** ({change})\n"
                
        embed.add_field(name="📊 ELO Changes", value=elo_text[:1024], inline=False)
        
        # Add note about reverting for moderators
        embed.set_footer(text="🛡️ Moderators can revert this result in the results channel if needed")
        
        await interaction.message.edit(embed=embed, view=self)

        # Send to results channel if configured (before cleanup deletes the match channel)
        if config["results_channel"]:
            channel = self.bot.get_channel(config["results_channel"])
            if channel:
                result_embed = discord.Embed(
                    title=f"🏆 Match Result ({queue_display})",
                    description=f"Match #{self.match_id}",
                    color=discord.Color.gold(),
                    timestamp=datetime.utcnow()
                )
                
                # Create team displays
                team1_result_text = ""
                team2_result_text = ""

                for user_id, position in self.team1_players:
                    user = self.bot.get_user(user_id)
                    pos_text = f" ({position})" if match_type not in ('2v2', '3v3') else ""
                    elo_info = next((e for e in elo_changes if e[0] == user_id and e[1] == position), None)
                    if elo_info:
                        _, _, change, old_elo, new_elo = elo_info
                        if winning_team == 1:
                            team1_result_text += f"{user.mention if user else f'User {user_id}'}{pos_text}: **{old_elo}** → **{new_elo}** (+{change})\n"
                        else:
                            team1_result_text += f"{user.mention if user else f'User {user_id}'}{pos_text}: **{old_elo}** → **{new_elo}** ({change})\n"
                    else:
                        team1_result_text += f"{user.mention if user else f'User {user_id}'}{pos_text}\n"

                for user_id, position in self.team2_players:
                    user = self.bot.get_user(user_id)
                    pos_text = f" ({position})" if match_type not in ('2v2', '3v3') else ""
                    elo_info = next((e for e in elo_changes if e[0] == user_id and e[1] == position), None)
                    if elo_info:
                        _, _, change, old_elo, new_elo = elo_info
                        if winning_team == 2:
                            team2_result_text += f"{user.mention if user else f'User {user_id}'}{pos_text}: **{old_elo}** → **{new_elo}** (+{change})\n"
                        else:
                            team2_result_text += f"{user.mention if user else f'User {user_id}'}{pos_text}: **{old_elo}** → **{new_elo}** ({change})\n"
                    else:
                        team2_result_text += f"{user.mention if user else f'User {user_id}'}{pos_text}\n"
                
                result_embed.add_field(
                    name=f"{'🏆 ' if winning_team == 1 else ''}🔴 Team 1",
                    value=team1_result_text.strip(),
                    inline=True
                )
                
                result_embed.add_field(
                    name=f"{'🏆 ' if winning_team == 2 else ''}🔵 Team 2",
                    value=team2_result_text.strip(),
                    inline=True
                )
                
                # Add revert + transcript buttons for moderators
                result_view = ResultWithTranscriptView(self.bot, self.match_id, winning_team=winning_team)
                result_msg = await channel.send(embed=result_embed, view=result_view)
                await self.bot.db.set_result_message_id(self.match_id, interaction.guild.id, result_msg.id)
                await self.update_elo_roles(interaction, elo_changes)

        # DM each player their personal match result
        guild = interaction.guild
        guild_name = guild.name if guild else "the server"
        winners_set = set(p[0] for p in winners)
        for user_id, position, change, old_elo, new_elo in elo_changes:
            try:
                user = self.bot.get_user(user_id)
                if not user:
                    continue

                won = user_id in winners_set
                result_str = "Won" if won else "Lost"
                result_emoji = "🏆" if won else "💔"

                queue_display = match_type.upper() if match_type else "6V6"
                if match_type == 'highrank':
                    queue_display = "High Rank 6v6"
                elif match_type == 'highrank_2v2':
                    queue_display = "High Rank 2v2"
                elif match_type == 'highrank_3v3':
                    queue_display = "High Rank 3v3"

                if match_type in ('2v2', '3v3', 'highrank_2v2', 'highrank_3v3'):
                    rating_line = f"**MMR:** {old_elo} → {new_elo} ({format_elo_change(change)})"
                else:
                    rating_line = f"**{position}:** {old_elo} → {new_elo} ({format_elo_change(change)})"

                dm_embed = discord.Embed(
                    title=f"{result_emoji} Match #{self.match_id} — {result_str}!",
                    description=(
                        f"Your **{queue_display}** match in **{guild_name}** has ended.\n\n"
                        f"{rating_line}"
                    ),
                    color=discord.Color.green() if won else discord.Color.red()
                )
                await user.send(embed=dm_embed)
            except (discord.Forbidden, discord.HTTPException):
                pass
            except Exception:
                pass

        # Clean up match channels immediately (save transcript then delete)
        asyncio.create_task(self._delayed_cleanup(0))

    async def _delayed_cleanup(self, delay):
        """Save transcript then delete match channels after a delay."""
        try:
            await asyncio.sleep(delay)
            match_channels = await self.bot.db.get_match_channels(self.match_id)
            if match_channels:
                text_channel_id, voice_channel_id = match_channels
                if text_channel_id:
                    text_channel = self.bot.get_channel(text_channel_id)
                    if text_channel:
                        # Collect transcript before deleting
                        try:
                            transcript_lines = []
                            async for msg in text_channel.history(limit=500, oldest_first=True):
                                ts = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
                                author = msg.author.display_name if msg.author else "Unknown"
                                content = msg.content or ""
                                if msg.embeds:
                                    for emb in msg.embeds:
                                        if emb.title:
                                            content += f" [Embed: {emb.title}]"
                                        if emb.description:
                                            content += f" {emb.description}"
                                if msg.attachments:
                                    content += " " + " ".join(a.url for a in msg.attachments)
                                transcript_lines.append(f"[{ts}] {author}: {content}")
                            if transcript_lines:
                                transcript = "\n".join(transcript_lines)
                                guild_id = text_channel.guild.id
                                await self.bot.db.save_match_transcript(self.match_id, guild_id, transcript)
                        except Exception:
                            pass

                        try:
                            await text_channel.delete(reason=f"Match #{self.match_id} ended")
                        except Exception:
                            pass
                if voice_channel_id:
                    voice_channel = self.bot.get_channel(voice_channel_id)
                    if voice_channel:
                        try:
                            await voice_channel.delete(reason=f"Match #{self.match_id} ended")
                        except Exception:
                            pass
        except Exception:
            pass


class ManualWinnerSelectView(discord.ui.View):
    def __init__(self, parent_view, moderator):
        super().__init__(timeout=60)
        self.parent_view = parent_view
        self.moderator = moderator
        
    @discord.ui.button(label="🔴 Team 1 Wins", style=discord.ButtonStyle.danger)
    async def team1_wins(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Disable all buttons
        for item in self.children:
            item.disabled = True
            
        await interaction.response.edit_message(view=self)
        
        # Set scores if not already set
        if self.parent_view.team1_score == 0 and self.parent_view.team2_score == 0:
            self.parent_view.team1_score = 25
            self.parent_view.team2_score = 20
            
        await self.parent_view.finalize_result(interaction, 1)
        
        # Log the manual selection
        match_channels = await self.parent_view.bot.db.get_match_channels(self.parent_view.match_id)
        if match_channels and match_channels[0]:
            text_channel = self.parent_view.bot.get_channel(match_channels[0])
            if text_channel:
                log_embed = discord.Embed(
                    title="🛡️ Manual Result Selection",
                    description=f"{self.moderator.mention} manually selected **Team 1** as the winner",
                    color=discord.Color.orange()
                )
                await text_channel.send(embed=log_embed)
        
        await interaction.followup.send("✅ Manually set Team 1 as winner", ephemeral=True)
        
    @discord.ui.button(label="🤝 Tie", style=discord.ButtonStyle.secondary)
    async def tie_result(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

        await self.parent_view.finalize_result(interaction, 0)

        match_channels = await self.parent_view.bot.db.get_match_channels(self.parent_view.match_id)
        if match_channels and match_channels[0]:
            text_channel = self.parent_view.bot.get_channel(match_channels[0])
            if text_channel:
                log_embed = discord.Embed(
                    title="🛡️ Manual Result Selection",
                    description=f"{self.moderator.mention} manually declared a **Tie**",
                    color=discord.Color.orange()
                )
                await text_channel.send(embed=log_embed)
        await interaction.followup.send("✅ Manually declared a Tie", ephemeral=True)

    @discord.ui.button(label="🔵 Team 2 Wins", style=discord.ButtonStyle.primary)
    async def team2_wins(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

        if self.parent_view.team1_score == 0 and self.parent_view.team2_score == 0:
            self.parent_view.team1_score = 20
            self.parent_view.team2_score = 25

        await self.parent_view.finalize_result(interaction, 2)

        match_channels = await self.parent_view.bot.db.get_match_channels(self.parent_view.match_id)
        if match_channels and match_channels[0]:
            text_channel = self.parent_view.bot.get_channel(match_channels[0])
            if text_channel:
                log_embed = discord.Embed(
                    title="🛡️ Manual Result Selection",
                    description=f"{self.moderator.mention} manually selected **Team 2** as the winner",
                    color=discord.Color.orange()
                )
                await text_channel.send(embed=log_embed)
        
        await interaction.followup.send("✅ Manually set Team 2 as winner", ephemeral=True)
        
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Disable all buttons
        for item in self.children:
            item.disabled = True
            
        await interaction.response.edit_message(content="Cancelled manual selection", embed=None, view=self)


class RevertResultView(discord.ui.View):
    """View shown after match completion for moderators to revert results"""
    def __init__(self, bot, match_id, winning_team=None):
        super().__init__(timeout=None)  # No timeout for persistent view
        self.bot = bot
        self.match_id = match_id
        self.winning_team = winning_team

    @discord.ui.button(label="Revert Result", style=discord.ButtonStyle.danger)
    async def revert_result(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check staff permissions
        config = await self.bot.db.get_config(interaction.guild.id)
        senior_roles = config.get("staff_senior_roles", [])
        normal_roles = config.get("staff_normal_roles", [])
        all_staff = senior_roles + normal_roles

        is_mod = interaction.user.guild_permissions.administrator
        if not is_mod and all_staff:
            user_role_ids = [role.id for role in interaction.user.roles]
            is_mod = any(role_id in all_staff for role_id in user_role_ids)

        if not is_mod:
            await interaction.response.send_message(
                "This action requires moderator permissions!",
                ephemeral=True
            )
            return

        # Confirm revert — pass the result message so it can be edited
        confirm_view = RevertConfirmView(
            self.bot, self.match_id, interaction.user,
            result_message=interaction.message,
            winning_team=self.winning_team
        )

        embed = discord.Embed(
            title="⚠️ Confirm Result Revert",
            description=f"Are you sure you want to revert the result of Match #{self.match_id}?\n\n"
                       "This will:\n"
                       "• Restore all player ELOs to pre-match values\n"
                       "• Remove win/loss records for this match\n"
                       "• Allow the match to be reported again\n\n"
                       "**This action cannot be undone!**",
            color=discord.Color.red()
        )

        await interaction.response.send_message(embed=embed, view=confirm_view, ephemeral=True)


class RevertConfirmView(discord.ui.View):
    def __init__(self, bot, match_id, moderator, result_message=None, winning_team=None):
        super().__init__(timeout=60)
        self.bot = bot
        self.match_id = match_id
        self.moderator = moderator
        self.result_message = result_message  # The original result message to edit
        self.winning_team = winning_team  # Which team won (1, 2, or 0 for tie)

    @discord.ui.button(label="✅ Confirm Revert", style=discord.ButtonStyle.danger)
    async def confirm_revert(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Disable buttons immediately
        for item in self.children:
            item.disabled = True

        # Try to defer and update the view in one go
        try:
            await interaction.response.edit_message(view=self)
        except discord.InteractionResponded:
            # If already responded, just defer
            await interaction.response.defer(ephemeral=True)

        # Revert the match
        success, message = await self.bot.db.revert_match_result(self.match_id, interaction.guild.id)

        if success:
            # Update leaderboard
            await self.bot.post_or_update_leaderboard(interaction.guild.id)

            # Edit the original result embed instead of sending a new one
            config = await self.bot.db.get_config(interaction.guild.id)
            result_msg = self.result_message
            if not result_msg and config.get("results_channel"):
                # Try to find the result message by ID
                msg_id = await self.bot.db.get_result_message_id(self.match_id, interaction.guild.id)
                if msg_id:
                    channel = self.bot.get_channel(config["results_channel"])
                    if channel:
                        try:
                            result_msg = await channel.fetch_message(msg_id)
                        except discord.NotFound:
                            result_msg = None

            if result_msg:
                # Edit the original result embed to show reverted status
                if result_msg.embeds:
                    reverted_embed = result_msg.embeds[0]
                    reverted_embed.title = f"🔄 Match #{self.match_id} — Result Reverted"
                    reverted_embed.color = discord.Color.orange()
                    reverted_embed.set_footer(text=f"Reverted by {self.moderator.display_name} — Match can be re-reported")
                else:
                    reverted_embed = discord.Embed(
                        title=f"🔄 Match #{self.match_id} — Result Reverted",
                        description=f"Result reverted by {self.moderator.mention}",
                        color=discord.Color.orange(),
                        timestamp=datetime.utcnow()
                    )

                # Create a re-vote view with buttons (all clickable except the original winner)
                revote_view = RevertedMatchView(self.bot, self.match_id, self.winning_team)
                try:
                    await result_msg.edit(embed=reverted_embed, view=revote_view)
                except discord.HTTPException:
                    pass
            else:
                # Fallback: send a new message if we can't find the original
                if config.get("results_channel"):
                    channel = self.bot.get_channel(config["results_channel"])
                    if channel:
                        log_embed = discord.Embed(
                            title="🔄 Match Result Reverted",
                            description=f"Match #{self.match_id} result has been reverted by {self.moderator.mention}",
                            color=discord.Color.orange(),
                            timestamp=datetime.utcnow()
                        )
                        await channel.send(embed=log_embed)

            await interaction.followup.send(f"✅ {message}", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ {message}", ephemeral=True)

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Disable buttons
        for item in self.children:
            item.disabled = True

        try:
            await interaction.response.edit_message(content="Revert cancelled", embed=None, view=self)
        except discord.InteractionResponded:
            await interaction.response.send_message("Revert cancelled", ephemeral=True)


class RevertedMatchView(discord.ui.View):
    """View shown on the result embed after a revert — allows re-voting for the correct result.
    All team buttons are enabled EXCEPT the team that originally won."""
    def __init__(self, bot, match_id, original_winning_team=None):
        super().__init__(timeout=None)
        self.bot = bot
        self.match_id = match_id
        self.original_winning_team = original_winning_team
        # Disable the button for the team that originally won
        if original_winning_team is not None:
            for child in self.children:
                if isinstance(child, discord.ui.Button):
                    if original_winning_team == 1 and child.label == "Team 1 Won":
                        child.disabled = True
                    elif original_winning_team == 2 and child.label == "Team 2 Won":
                        child.disabled = True
                    elif original_winning_team == 0 and child.label == "Tie":
                        child.disabled = True

    async def _has_mod_permissions(self, user: discord.Member) -> bool:
        if user.guild_permissions.administrator:
            return True
        config = await self.bot.db.get_config(user.guild.id)
        senior_roles = config.get("staff_senior_roles", [])
        normal_roles = config.get("staff_normal_roles", [])
        all_staff = senior_roles + normal_roles
        if all_staff:
            user_role_ids = [role.id for role in user.roles]
            return any(role_id in all_staff for role_id in user_role_ids)
        return False

    async def _report_new_result(self, interaction: discord.Interaction, winning_team: int):
        if not await self._has_mod_permissions(interaction.user):
            await interaction.response.send_message(
                "This action requires moderator permissions!", ephemeral=True)
            return

        # Disable buttons
        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(view=self)

        # Get match details
        match = await self.bot.db.get_full_match(self.match_id, interaction.guild.id)
        if not match:
            await interaction.followup.send("Match not found!", ephemeral=True)
            return

        import json as _json
        team1 = _json.loads(match[1])
        team2 = _json.loads(match[2])
        match_type = match[10]

        config = await self.bot.db.get_config(interaction.guild.id)
        k_factor = config["k_factor"]
        starting_elo = config["starting_elo"]

        if match_type and match_type.startswith("highrank"):
            starting_elo = config.get("high_rank_starting_elo", starting_elo)

        if winning_team == 0:
            # Tie — just update scores
            await self.bot.db.update_match_score(self.match_id, 0, 0)
            await self.bot.db.set_match_inactive(self.match_id)

            # Update all players game counts for tie
            for player_data in team1 + team2:
                pid, pos = player_data[0], player_data[1]
                if match_type in ('2v2', '3v3', 'highrank_2v2', 'highrank_3v3'):
                    await self.bot.db.update_player_elo_simple(interaction.guild.id, pid, match_type, 0, False, starting_elo)
                elif match_type == 'highrank':
                    await self.bot.db.update_player_elo_highrank(interaction.guild.id, pid, pos, 0, False, starting_elo)
                else:
                    await self.bot.db.update_player_elo(interaction.guild.id, pid, pos, 0, False, starting_elo)

            embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
            embed.title = f"🤝 Match #{self.match_id} — Tie (Re-reported)"
            embed.color = discord.Color.light_grey()
            embed.set_footer(text=f"Re-reported by {interaction.user.display_name}")
            await interaction.message.edit(embed=embed, view=ResultWithTranscriptView(self.bot, self.match_id, winning_team=0))
        else:
            # Team won — calculate and apply ELO
            winners = team1 if winning_team == 1 else team2
            losers = team2 if winning_team == 1 else team1

            t1_score = 1 if winning_team == 1 else 0
            t2_score = 0 if winning_team == 1 else 1
            await self.bot.db.update_match_score(self.match_id, t1_score, t2_score)
            await self.bot.db.set_match_inactive(self.match_id)

            # Get current ELOs
            current_elos = {}
            for player_data in winners + losers:
                pid, pos = player_data[0], player_data[1]
                if match_type in ('2v2', '3v3', 'highrank_2v2', 'highrank_3v3'):
                    elo = await self.bot.db.get_player_elo_simple(interaction.guild.id, pid, match_type)
                elif match_type == 'highrank':
                    elo = await self.bot.db.get_player_elo_highrank(interaction.guild.id, pid, pos)
                else:
                    elo = await self.bot.db.get_player_elo(interaction.guild.id, pid, pos)
                current_elos[(pid, pos)] = elo

            elo_changes = []

            for w_data in winners:
                w_id, w_pos = w_data[0], w_data[1]
                total_change = 0
                for l_data in losers:
                    l_id, l_pos = l_data[0], l_data[1]
                    w_elo = current_elos[(w_id, w_pos)]
                    l_elo = current_elos[(l_id, l_pos)]
                    wc, lc = self.bot.calculate_elo_change(w_elo, l_elo, k_factor)
                    total_change += wc / len(losers)
                if match_type in ('2v2', '3v3', 'highrank_2v2', 'highrank_3v3'):
                    await self.bot.db.update_player_elo_simple(interaction.guild.id, w_id, match_type, int(total_change), True, starting_elo)
                elif match_type == 'highrank':
                    await self.bot.db.update_player_elo_highrank(interaction.guild.id, w_id, w_pos, int(total_change), True, starting_elo)
                else:
                    await self.bot.db.update_player_elo(interaction.guild.id, w_id, w_pos, int(total_change), True, starting_elo)
                old_elo = current_elos[(w_id, w_pos)]
                new_elo = old_elo + int(total_change)
                elo_changes.append((w_id, w_pos, int(total_change), old_elo, new_elo))
                await self.bot.db.record_elo_history(interaction.guild.id, w_id, self.match_id, match_type or '6v6', w_pos, old_elo, new_elo, int(total_change), True)

            for l_data in losers:
                l_id, l_pos = l_data[0], l_data[1]
                total_change = 0
                for w_data in winners:
                    w_id, w_pos = w_data[0], w_data[1]
                    w_elo = current_elos[(w_id, w_pos)]
                    l_elo = current_elos[(l_id, l_pos)]
                    wc, lc = self.bot.calculate_elo_change(w_elo, l_elo, k_factor)
                    total_change += lc / len(winners)
                if match_type in ('2v2', '3v3', 'highrank_2v2', 'highrank_3v3'):
                    await self.bot.db.update_player_elo_simple(interaction.guild.id, l_id, match_type, int(total_change), False, starting_elo)
                elif match_type == 'highrank':
                    await self.bot.db.update_player_elo_highrank(interaction.guild.id, l_id, l_pos, int(total_change), False, starting_elo)
                else:
                    await self.bot.db.update_player_elo(interaction.guild.id, l_id, l_pos, int(total_change), False, starting_elo)
                old_elo = current_elos[(l_id, l_pos)]
                new_elo = old_elo + int(total_change)
                elo_changes.append((l_id, l_pos, int(total_change), old_elo, new_elo))
                await self.bot.db.record_elo_history(interaction.guild.id, l_id, self.match_id, match_type or '6v6', l_pos, old_elo, new_elo, int(total_change), False)

            # Build updated result embed
            result_embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
            queue_display = match_type.upper() if match_type else "6V6"
            if match_type == 'highrank':
                queue_display = "High Rank 6v6"
            elif match_type == 'highrank_2v2':
                queue_display = "High Rank 2v2"
            elif match_type == 'highrank_3v3':
                queue_display = "High Rank 3v3"

            result_embed.title = f"🏆 Match Result ({queue_display}) — Re-reported"
            result_embed.color = discord.Color.gold()

            # Rebuild team fields with new ELO changes
            result_embed.clear_fields()
            team1_text = ""
            team2_text = ""
            for user_id, position in team1:
                user = self.bot.get_user(user_id)
                pos_text = f" ({position})" if match_type not in ('2v2', '3v3') else ""
                elo_info = next((e for e in elo_changes if e[0] == user_id and e[1] == position), None)
                if elo_info:
                    _, _, change, old_elo, new_elo = elo_info
                    sign = "+" if change >= 0 else ""
                    team1_text += f"{user.mention if user else f'User {user_id}'}{pos_text}: **{old_elo}** → **{new_elo}** ({sign}{change})\n"
                else:
                    team1_text += f"{user.mention if user else f'User {user_id}'}{pos_text}\n"
            for user_id, position in team2:
                user = self.bot.get_user(user_id)
                pos_text = f" ({position})" if match_type not in ('2v2', '3v3') else ""
                elo_info = next((e for e in elo_changes if e[0] == user_id and e[1] == position), None)
                if elo_info:
                    _, _, change, old_elo, new_elo = elo_info
                    sign = "+" if change >= 0 else ""
                    team2_text += f"{user.mention if user else f'User {user_id}'}{pos_text}: **{old_elo}** → **{new_elo}** ({sign}{change})\n"
                else:
                    team2_text += f"{user.mention if user else f'User {user_id}'}{pos_text}\n"

            result_embed.add_field(
                name=f"{'🏆 ' if winning_team == 1 else ''}🔴 Team 1",
                value=team1_text.strip() or "—", inline=True)
            result_embed.add_field(
                name=f"{'🏆 ' if winning_team == 2 else ''}🔵 Team 2",
                value=team2_text.strip() or "—", inline=True)
            result_embed.set_footer(text=f"Re-reported by {interaction.user.display_name}")

            new_view = ResultWithTranscriptView(self.bot, self.match_id, winning_team=winning_team)
            await interaction.message.edit(embed=result_embed, view=new_view)

        await self.bot.post_or_update_leaderboard(interaction.guild.id)
        await interaction.followup.send(
            f"✅ Match #{self.match_id} result updated — Team {winning_team if winning_team else 'Tie'} {'wins' if winning_team else ''}",
            ephemeral=True)

    @discord.ui.button(label="Team 1 Won", style=discord.ButtonStyle.danger, emoji="🔴", row=0)
    async def team1_won(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._report_new_result(interaction, 1)

    @discord.ui.button(label="Tie", style=discord.ButtonStyle.secondary, emoji="🤝", row=0)
    async def tie_result(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._report_new_result(interaction, 0)

    @discord.ui.button(label="Team 2 Won", style=discord.ButtonStyle.primary, emoji="🔵", row=0)
    async def team2_won(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._report_new_result(interaction, 2)


import io as _io

class ResultWithTranscriptView(discord.ui.View):
    """View for results channel with result indicator buttons + revert + transcript."""
    def __init__(self, bot, match_id, winning_team=None):
        super().__init__(timeout=None)
        self.bot = bot
        self.match_id = match_id
        self.winning_team = winning_team  # 1, 2, or 0 (tie)

        # Add result indicator buttons (disabled, showing which team won)
        if winning_team is not None:
            team1_btn = discord.ui.Button(
                label="Team 1",
                style=discord.ButtonStyle.success if winning_team == 1 else discord.ButtonStyle.secondary,
                disabled=True,
                emoji="🔴",
                row=0
            )
            tie_btn = discord.ui.Button(
                label="Tie",
                style=discord.ButtonStyle.success if winning_team == 0 else discord.ButtonStyle.secondary,
                disabled=True,
                emoji="🤝",
                row=0
            )
            team2_btn = discord.ui.Button(
                label="Team 2",
                style=discord.ButtonStyle.success if winning_team == 2 else discord.ButtonStyle.secondary,
                disabled=True,
                emoji="🔵",
                row=0
            )
            self.add_item(team1_btn)
            self.add_item(tie_btn)
            self.add_item(team2_btn)

    @discord.ui.button(label="Revert Result", style=discord.ButtonStyle.danger, row=1)
    async def revert_result(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Same permission check as RevertResultView
        config = await self.bot.db.get_config(interaction.guild.id)
        senior_roles = config.get("staff_senior_roles", [])
        normal_roles = config.get("staff_normal_roles", [])
        all_staff = senior_roles + normal_roles

        is_mod = interaction.user.guild_permissions.administrator
        if not is_mod and all_staff:
            user_role_ids = [role.id for role in interaction.user.roles]
            is_mod = any(role_id in all_staff for role_id in user_role_ids)

        if not is_mod:
            await interaction.response.send_message(
                "This action requires moderator permissions!", ephemeral=True
            )
            return

        confirm_view = RevertConfirmView(
            self.bot, self.match_id, interaction.user,
            result_message=interaction.message,
            winning_team=self.winning_team
        )
        embed = discord.Embed(
            title="⚠️ Confirm Result Revert",
            description=f"Are you sure you want to revert the result of Match #{self.match_id}?\n\n"
                       "This will:\n"
                       "• Restore all player ELOs to pre-match values\n"
                       "• Remove win/loss records for this match\n"
                       "• Allow the match to be reported again\n\n"
                       "**This action cannot be undone!**",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, view=confirm_view, ephemeral=True)

    @discord.ui.button(label="Transcript", style=discord.ButtonStyle.secondary, emoji="\U0001f4dd", row=1)
    async def transcript_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        transcript = await self.bot.db.get_match_transcript(self.match_id, interaction.guild.id)
        if not transcript:
            await interaction.followup.send("No transcript available for this match.", ephemeral=True)
            return

        buf = _io.BytesIO(transcript.encode('utf-8'))
        file = discord.File(buf, filename=f"match_{self.match_id}_transcript.txt")
        await interaction.followup.send(
            f"Match #{self.match_id} chat transcript:",
            file=file, ephemeral=True
        )


class SwapPlayersModal(discord.ui.Modal, title="Swap Players"):
    def __init__(self, bot, match_id, player1, team1_players, team2_players):
        super().__init__(custom_id="modal_swap_players")
        self.bot = bot
        self.match_id = match_id
        self.player1 = player1
        self.team1_players = team1_players
        self.team2_players = team2_players
        
    player2_id = discord.ui.TextInput(
        label="Second Player ID",
        placeholder="Enter the ID of the player to swap with",
        max_length=20,
        required=True
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            player2_id = int(self.player2_id.value)
        except ValueError:
            await interaction.response.send_message(
                "Invalid player ID! Please enter a number.",
                ephemeral=True
            )
            return
            
        # Find both players
        player1_team = None
        player1_index = None
        player1_position = None
        player2_team = None
        player2_index = None
        player2_position = None
        
        # Find player 1
        for i, (pid, pos) in enumerate(self.team1_players):
            if pid == self.player1.id:
                player1_team = 1
                player1_index = i
                player1_position = pos
                break
                
        if player1_team is None:
            for i, (pid, pos) in enumerate(self.team2_players):
                if pid == self.player1.id:
                    player1_team = 2
                    player1_index = i
                    player1_position = pos
                    break
                    
        # Find player 2
        for i, (pid, pos) in enumerate(self.team1_players):
            if pid == player2_id:
                player2_team = 1
                player2_index = i
                player2_position = pos
                break
                
        if player2_team is None:
            for i, (pid, pos) in enumerate(self.team2_players):
                if pid == player2_id:
                    player2_team = 2
                    player2_index = i
                    player2_position = pos
                    break
                    
        # Validate players found
        if player1_team is None:
            await interaction.response.send_message(
                f"{self.player1.mention} is not in this match!",
                ephemeral=True
            )
            return
            
        if player2_team is None:
            await interaction.response.send_message(
                f"Player with ID {player2_id} is not in this match!",
                ephemeral=True
            )
            return
            
        if player1_team == player2_team:
            await interaction.response.send_message(
                "Both players are on the same team! Cannot swap.",
                ephemeral=True
            )
            return
            
        # Perform the swap
        if player1_team == 1:
            # Player 1 is on team 1, player 2 is on team 2
            self.team1_players[player1_index] = [player2_id, player2_position]
            self.team2_players[player2_index] = [self.player1.id, player1_position]
        else:
            # Player 1 is on team 2, player 2 is on team 1
            self.team2_players[player1_index] = [player2_id, player2_position]
            self.team1_players[player2_index] = [self.player1.id, player1_position]
            
        # Update database
        await self.bot.db.db.execute(
            'UPDATE matches SET team1_players = ?, team2_players = ? WHERE id = ?',
            (json.dumps(self.team1_players), json.dumps(self.team2_players), self.match_id)
        )
        await self.bot.db.db.commit()
        
        player2 = self.bot.get_user(player2_id)
        
        embed = discord.Embed(
            title="✅ Players Swapped",
            description=f"Swapped {self.player1.mention} (Team {player1_team}) with "
                       f"{player2.mention if player2 else f'User {player2_id}'} (Team {player2_team})",
            color=discord.Color.green()
        )
        
        # Add current team compositions
        match_type = await self.bot.db.get_match_type(self.match_id)
        team1_text = ""
        team2_text = ""

        for player_id, position in self.team1_players:
            player = self.bot.get_user(player_id)
            if match_type in ('2v2', '3v3'):
                elo = await self.bot.db.get_player_elo_simple(interaction.guild.id, player_id, match_type)
            elif match_type == 'highrank':
                elo = await self.bot.db.get_player_elo_highrank(interaction.guild.id, player_id, position)
            else:
                elo = await self.bot.db.get_player_elo(interaction.guild.id, player_id, position)
            team1_text += f"{player.mention if player else f'User {player_id}'} ({position}) - {elo} ELO\n"

        for player_id, position in self.team2_players:
            player = self.bot.get_user(player_id)
            if match_type in ('2v2', '3v3'):
                elo = await self.bot.db.get_player_elo_simple(interaction.guild.id, player_id, match_type)
            elif match_type == 'highrank':
                elo = await self.bot.db.get_player_elo_highrank(interaction.guild.id, player_id, position)
            else:
                elo = await self.bot.db.get_player_elo(interaction.guild.id, player_id, position)
            team2_text += f"{player.mention if player else f'User {player_id}'} ({position}) - {elo} ELO\n"
            
        embed.add_field(name="🔴 Team 1", value=team1_text or "Empty", inline=True)
        embed.add_field(name="🔵 Team 2", value=team2_text or "Empty", inline=True)
        
        await interaction.response.send_message(embed=embed)