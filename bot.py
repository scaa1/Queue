import discord
from discord.ext import commands, tasks
import asyncio
import json
import time

from stats_card import generate_leaderboard_card
from typing import Dict, List, Optional, Tuple
import math
from datetime import datetime, timedelta

from config import BOT_TOKEN, DEFAULT_CONFIG, VALID_POSITIONS, ALLOWED_GUILD_ID, get_region_role_limits, get_region_team_size, is_5v5_region
from database import Database
from utils import format_duration, format_elo_change
from views import QueueView, Queue2v2View, Queue3v3View, LeaderboardView, MatchResultView, ReadyCheckView, RevertResultView, ResultWithTranscriptView, RegionRoleView, build_region_embed


class VolleyballBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix='!', intents=intents)
        self.db = Database()
        self.queues = {}  # guild_id -> list of queued players
        self.duo_queues = {}  # guild_id -> list of duo pairs
        self.trio_queues = {}  # guild_id -> list of trio groups
        self.queue_message_ids = {}  # guild_id -> message_id (6v6)
        self.queue_2v2_message_ids = {}  # guild_id -> message_id (2v2)
        self.queue_3v3_message_ids = {}  # guild_id -> message_id (3v3)
        self.ready_check_views = {}  # match_id -> ReadyCheckView
        self.pending_group_invites = {}  # invitation_id -> invitation_data
        self._queue_embed_locks = {}  # guild_id -> asyncio.Lock (prevents overlapping embed updates)
        
    def _get_queue_embed_lock(self, guild_id):
        """Get or create an asyncio.Lock for a guild's queue embed updates."""
        if guild_id not in self._queue_embed_locks:
            self._queue_embed_locks[guild_id] = asyncio.Lock()
        return self._queue_embed_locks[guild_id]

    async def setup_hook(self):
        await self.db.connect()
        self.update_queue_embeds.start()
        self.check_queue_timeouts.start()
        self.update_leaderboards.start()
        self.cleanup_old_channels.start()
        self.check_afk_timer.start()
        
        # Add persistent views
        self.add_view(QueueView(self))
        self.add_view(Queue2v2View(self))
        self.add_view(Queue3v3View(self))
        self.add_view(RegionRoleView(self))
        
        # Load commands cog
        await self.load_extension('commands')
        
        # Sync slash commands
        try:
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} command(s)")
        except Exception as e:
            print(f"Failed to sync commands: {e}")
            
    async def on_ready(self):
        print(f'{self.user} has connected to Discord!')
        
        # Check guild restriction
        if ALLOWED_GUILD_ID > 0:
            print(f"Guild restriction enabled. Allowed guild ID: {ALLOWED_GUILD_ID}")
            
            # Leave any guilds that aren't the allowed one
            for guild in self.guilds:
                if guild.id != ALLOWED_GUILD_ID:
                    print(f"Leaving unauthorized guild: {guild.name} (ID: {guild.id})")
                    try:
                        await guild.leave()
                    except Exception as e:
                        print(f"Error leaving guild {guild.name}: {e}")
                else:
                    print(f"Authorized guild found: {guild.name} (ID: {guild.id})")
                    
            # Check if we're in the allowed guild
            allowed_guild = self.get_guild(ALLOWED_GUILD_ID)
            if not allowed_guild:
                print(f"WARNING: Bot is not in the allowed guild (ID: {ALLOWED_GUILD_ID})")
                print("The bot will automatically join when invited to the correct guild.")
        
        # Restore persistent views for each guild
        for guild in self.guilds:
            if ALLOWED_GUILD_ID == 0 or guild.id == ALLOWED_GUILD_ID:
                # Restore leaderboard
                await self.restore_leaderboard(guild.id)

                # Restore region role embed
                await self.restore_region_embed(guild.id)

                # Restore revert buttons in results channel
                await self.restore_revert_buttons(guild.id)
            
        # Restore queue messages on startup
        for guild in self.guilds:
            if ALLOWED_GUILD_ID == 0 or guild.id == ALLOWED_GUILD_ID:
                config = await self.db.get_config(guild.id)
                if config.get("queue_channel"):
                    channel = self.get_channel(config["queue_channel"])
                    if channel:
                        try:
                            # Collect all matching queue messages to clean up duplicates
                            found_messages = []
                            async for message in channel.history(limit=50):
                                if message.author == self.user and message.embeds:
                                    if message.embeds[0].title and "Volleyball Queue" in message.embeds[0].title:
                                        found_messages.append(message)

                            if found_messages:
                                # Keep the most recent one, delete the rest
                                keep = found_messages[0]
                                for dup in found_messages[1:]:
                                    try:
                                        await dup.delete()
                                    except Exception:
                                        pass

                                self.queue_message_ids[guild.id] = keep.id
                                view = QueueView(self, config)
                                await keep.edit(view=view)
                                await self.update_queue_embed(guild.id)
                        except Exception:
                            pass

                # Restore 2v2 queue message
                if config.get("queue_2v2_channel"):
                    channel_2v2 = self.get_channel(config["queue_2v2_channel"])
                    if channel_2v2:
                        try:
                            found_messages = []
                            async for message in channel_2v2.history(limit=50):
                                if message.author == self.user and message.embeds:
                                    if message.embeds[0].title and "2v2 Queue" in message.embeds[0].title:
                                        found_messages.append(message)

                            if found_messages:
                                keep = found_messages[0]
                                for dup in found_messages[1:]:
                                    try:
                                        await dup.delete()
                                    except Exception:
                                        pass

                                self.queue_2v2_message_ids[guild.id] = keep.id
                                view = Queue2v2View(self, config)
                                await keep.edit(view=view)
                                await self.update_queue_embed_2v2(guild.id)
                        except Exception:
                            pass

                # Restore 3v3 queue message
                if config.get("queue_3v3_channel"):
                    channel_3v3 = self.get_channel(config["queue_3v3_channel"])
                    if channel_3v3:
                        try:
                            found_messages = []
                            async for message in channel_3v3.history(limit=50):
                                if message.author == self.user and message.embeds:
                                    if message.embeds[0].title and "3v3 Queue" in message.embeds[0].title:
                                        found_messages.append(message)

                            if found_messages:
                                keep = found_messages[0]
                                for dup in found_messages[1:]:
                                    try:
                                        await dup.delete()
                                    except Exception:
                                        pass

                                self.queue_3v3_message_ids[guild.id] = keep.id
                                view = Queue3v3View(self, config)
                                await keep.edit(view=view)
                                await self.update_queue_embed_3v3(guild.id)
                        except Exception:
                            pass
                            
    async def restore_revert_buttons(self, guild_id):
        """Restore revert button views in the results channel"""
        config = await self.db.get_config(guild_id)
        results_channel_id = config.get("results_channel")
        
        if not results_channel_id:
            return
            
        channel = self.get_channel(results_channel_id)
        if not channel:
            return
            
        print(f"Restoring revert buttons in guild {guild_id}...")
        
        try:
            # Look through recent messages in results channel
            async for message in channel.history(limit=100):
                if message.author == self.user and message.embeds:
                    # Check if this is a match result message
                    if len(message.embeds) > 0:
                        embed = message.embeds[0]
                        if embed.title and "Match Result" in embed.title:
                            # Extract match ID from description
                            if embed.description and "Match #" in embed.description:
                                try:
                                    match_id_str = embed.description.split("Match #")[1].strip()
                                    # Handle case where there might be more text after the ID
                                    match_id = int(match_id_str.split()[0])
                                    
                                    # Check if this match exists and has a result
                                    match_data = await self.db.get_match(match_id, guild_id)
                                    if match_data:
                                        # Determine winning team from scores
                                        scores = await self.db.get_match_scores(match_id)
                                        wt = None
                                        if scores:
                                            s1, s2 = scores
                                            if s1 is not None and s2 is not None:
                                                wt = 1 if s1 > s2 else 2 if s2 > s1 else 0
                                        # Re-add the revert + transcript view with result buttons
                                        view = ResultWithTranscriptView(self, match_id, winning_team=wt)
                                        await message.edit(view=view)
                                        print(f"Restored result buttons for match #{match_id}")
                                except (ValueError, IndexError) as e:
                                    # Couldn't parse match ID, skip this message
                                    continue
        except Exception as e:
            print(f"Error restoring revert buttons: {e}")
                            
    async def get_blacklist_role(self, guild):
        """Get the configured blacklist role for a guild, or fall back to 'Blacklisted' name."""
        config = await self.db.get_config(guild.id)
        role_id = config.get("blacklist_role_id")
        if role_id:
            role = guild.get_role(role_id)
            if role:
                return role
        # Fallback to name-based lookup
        return discord.utils.get(guild.roles, name="Blacklisted")

    async def on_guild_member_join(self, member):
        """Check if rejoining member was blacklisted"""
        reason = await self.db.is_blacklisted(member.guild.id, member.id)
        if reason is not None:
            blacklist_role = await self.get_blacklist_role(member.guild)
            if not blacklist_role:
                try:
                    blacklist_role = await member.guild.create_role(
                        name="Blacklisted",
                        color=discord.Color.dark_gray(),
                        reason="Created for blacklist system"
                    )
                except:
                    return

            if blacklist_role:
                try:
                    await member.add_roles(blacklist_role, reason="User is blacklisted")
                except:
                    pass
                            
    # Mapping of custom_ids to friendly button labels for logging (fallback)
    BUTTON_LABELS = {
        "volleyball_position_select": "Position Select (6v6)",
        "volleyball_leave_queue": "Leave Queue (6v6)",
        "volleyball_duo_queue": "Duo Queue (6v6)",
        "volleyball_trio_queue": "Trio Queue (6v6)",
        "volleyball_highrank_queue": "High Rank Queue (6v6)",
        "volleyball_join_2v2": "Join 2v2 Queue",
        "volleyball_duo_2v2": "Duo 2v2",
        "volleyball_highrank_2v2": "High Rank 2v2",
        "volleyball_leave_2v2": "Leave Queue (2v2)",
        "volleyball_join_3v3": "Join 3v3 Queue",
        "volleyball_duo_3v3": "Duo 3v3",
        "volleyball_trio_3v3": "Trio 3v3",
        "volleyball_highrank_3v3": "High Rank 3v3",
        "volleyball_leave_3v3": "Leave Queue (3v3)",
    }

    # Mapping of modal custom_ids to friendly names for logging
    MODAL_LABELS = {
        "modal_force_start": "Force Start Match",
        "modal_afk_timer": "Set AFK Timer",
        "modal_blacklist_reason": "Blacklist User",
        "modal_season_start": "Start New Season",
        "modal_season_remove": "Remove Season",
        "modal_add_elo_role": "Add ELO Role Reward",
        "modal_remove_elo_role": "Remove ELO Role Reward",
        "modal_highrank_mmr": "Set High Rank MMR Limit",
        "modal_set_elo": "Set ELO",
        "modal_adjust_elo": "Adjust ELO",
        "modal_match_id_input": "Manage Match",
        "modal_cancel_match": "Cancel Active Match",
        "modal_edit_match_id": "Edit Match",
        "modal_add_player_match": "Add Player to Match",
        "modal_remove_player_match": "Remove Player from Match",
        "modal_swap_players_match": "Swap Players Between Teams",
        "modal_edit_streaks": "Edit Player Streaks",
        "modal_edit_elo": "Edit Player ELO",
        "modal_adjust_elo_full": "Adjust Player ELO",
        "modal_edit_record": "Edit Player Record",
        "modal_match_category": "Set Match Category",
        "modal_elo_settings": "ELO Settings",
        "modal_match_cleanup": "Match Cleanup Settings",
        "modal_swap_players": "Swap Players",
        "modal_simple_set_elo": "Set ELO",
        "modal_simple_adjust_elo": "Adjust ELO",
    }

    def _get_component_label(self, interaction, custom_id):
        """Try to extract the button/select label from the message components."""
        try:
            if interaction.message:
                for action_row in interaction.message.components:
                    for component in action_row.children:
                        if hasattr(component, 'custom_id') and component.custom_id == custom_id:
                            if hasattr(component, 'label') and component.label:
                                return component.label
                            if hasattr(component, 'placeholder') and component.placeholder:
                                return component.placeholder
        except Exception:
            pass
        return None

    async def on_interaction(self, interaction: discord.Interaction):
        """Log all interactions (commands, buttons, selects) to the general log channel."""
        if not interaction.guild:
            return

        try:
            if interaction.type == discord.InteractionType.application_command:
                # Slash command
                cmd_name = interaction.data.get("name", "unknown")
                options = interaction.data.get("options", [])
                opts_text = " ".join(f"{o['name']}={o.get('value', '')}" for o in options) if options else ""
                desc = f"Used command **/{cmd_name}**" + (f" {opts_text}" if opts_text else "")
                await self.log_interaction(interaction, desc)
            elif interaction.type == discord.InteractionType.component:
                # Button or select menu
                custom_id = interaction.data.get("custom_id", "unknown")
                component_type = interaction.data.get("component_type", 0)
                values = interaction.data.get("values", [])
                # Try to get label from message components first, then fallback to mapping
                friendly_name = (
                    self._get_component_label(interaction, custom_id)
                    or self.BUTTON_LABELS.get(custom_id)
                    or custom_id
                )
                if component_type == 3:  # Select menu
                    desc = f"Used select menu **{friendly_name}** with values: {', '.join(values)}"
                else:  # Button
                    desc = f"Clicked button **{friendly_name}**"
                await self.log_interaction(interaction, desc)
            elif interaction.type == discord.InteractionType.modal_submit:
                custom_id = interaction.data.get("custom_id", "unknown")
                friendly_name = self.MODAL_LABELS.get(custom_id, custom_id)
                desc = f"Submitted modal **{friendly_name}**"
                await self.log_interaction(interaction, desc)
        except Exception:
            pass

    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """Handle voice channel events for automatic ready check"""
        # Check if member joined a voice channel
        if after.channel and not before.channel:
            # Check if this is a match voice channel
            active_matches = await self.db.get_active_matches(member.guild.id)
            
            for match_id, text_channel_id, voice_channel_id in active_matches:
                if voice_channel_id == after.channel.id:
                    # Member joined a match voice channel
                    # Check if we have a ready check view for this match
                    if match_id in self.ready_check_views:
                        view = self.ready_check_views[match_id]
                        
                        # Mark player as ready if they're in the match
                        if member.id in view.all_players and member.id not in view.ready_players:
                            view.ready_players.add(member.id)
                            
                            # Find and update the message
                            if text_channel_id:
                                text_channel = self.get_channel(text_channel_id)
                                if text_channel:
                                    try:
                                        # Look for the ready check message
                                        async for message in text_channel.history(limit=20):
                                            if message.author == self.user and message.embeds:
                                                if len(message.embeds) > 0 and f"Match #{match_id}" in message.embeds[0].title and "Ready Check" in message.embeds[0].title:
                                                    # Create a fake interaction for the update
                                                    class FakeInteraction:
                                                        def __init__(self, msg):
                                                            self.message = msg
                                                            self.guild_id = msg.guild.id
                                                            
                                                        async def response(self):
                                                            return self
                                                            
                                                        async def defer(self):
                                                            pass
                                                            
                                                        async def followup(self):
                                                            return self
                                                            
                                                        async def send(self, *args, **kwargs):
                                                            pass
                                                    
                                                    fake_interaction = FakeInteraction(message)
                                                    await view.update_embed(fake_interaction)
                                                    
                                                    # Send notification
                                                    await text_channel.send(f"✅ {member.mention} automatically marked as ready (joined voice channel)")
                                                    
                                                    # Check if all players are ready
                                                    if len(view.ready_players) == len(view.all_players) and not view.match_started:
                                                        await view.start_match(fake_interaction)
                                                    break
                                    except Exception as e:
                                        print(f"Error in voice state update: {e}")
                    break
                    
    async def on_guild_join(self, guild):
        """Called when the bot joins a new guild"""
        if ALLOWED_GUILD_ID > 0 and guild.id != ALLOWED_GUILD_ID:
            print(f"Joined unauthorized guild: {guild.name} (ID: {guild.id}). Leaving immediately...")
            
            # Try to send a message to the system channel before leaving
            try:
                if guild.system_channel:
                    await guild.system_channel.send(
                        f"⚠️ This bot is configured to only operate in a specific guild (ID: {ALLOWED_GUILD_ID}). "
                        f"I will now leave this server. If you are the intended user, please update the ALLOWED_GUILD_ID "
                        f"environment variable to {guild.id} and restart the bot."
                    )
            except:
                pass
                
            # Leave the guild
            try:
                await guild.leave()
                print(f"Successfully left unauthorized guild: {guild.name}")
            except Exception as e:
                print(f"Error leaving guild {guild.name}: {e}")
        else:
            print(f"Joined authorized guild: {guild.name} (ID: {guild.id})")
                        
    async def restore_leaderboard(self, guild_id):
        config = await self.db.get_config(guild_id)
        if config.get("leaderboard_channel") and config.get("leaderboard_message_id"):
            try:
                channel = self.get_channel(config["leaderboard_channel"])
                if channel:
                    message = await channel.fetch_message(config["leaderboard_message_id"])
                    view = LeaderboardView(self, guild_id)
                    await view.setup_season_options()
                    await message.edit(view=view)
            except:
                # Message doesn't exist, post a new one
                await self.post_or_update_leaderboard(guild_id)
                

    async def post_or_update_leaderboard(self, guild_id):
            """Post or update the leaderboard in the configured channel"""
            config = await self.db.get_config(guild_id)
            channel_id = config.get("leaderboard_channel")
            message_id = config.get("leaderboard_message_id")

            if not channel_id:
                return

            channel = self.get_channel(channel_id)
            if not channel:
                return

            # Create or update the leaderboard view
            view = LeaderboardView(self, guild_id)
            await view.setup_season_options()
            view._update_select_defaults()

            # Get initial data (top 10 average elo)
            rows = await self.db.get_leaderboard_data(guild_id, None, 10, 0)
            total_count = await self.db.get_player_count(guild_id)
            total_pages = max(1, (total_count - 1) // 10 + 1)

            view.prev_button.disabled = True
            view.next_button.disabled = len(rows) < 10

            # Build card rows
            card_rows = []
            for i, (user_id, avg_elo, g, w) in enumerate(rows, 1):
                user = self.get_user(user_id)
                username = user.name if user else f"User {user_id}"
                win_rate = (w / g * 100) if g > 0 else 0
                value_text = f"{avg_elo:.0f} ELO"
                sub_text = f"{win_rate:.1f}% WR | {w}W/{g - w}L | {g} games"

                streaks = await self.db.get_player_streaks(guild_id, user_id, '6v6')
                ws_val, ls_val = streaks[0], streaks[1]
                streak_text = ""
                if ws_val > 0:
                    streak_text = f"{ws_val}W streak"
                elif ls_val > 0:
                    streak_text = f"{ls_val}L streak"

                card_rows.append((i, username, value_text, sub_text, streak_text))

            image_buf = await generate_leaderboard_card(
                title="Volleyball Leaderboard",
                rows=card_rows if card_rows else None,
                page=0,
                total_pages=total_pages,
                subtitle="Top Players - Average ELO Rating (Current Season)",
                queue_label="Regular",
            )

            embed = discord.Embed(color=discord.Color.from_rgb(32, 34, 40))
            embed.set_image(url="attachment://leaderboard.png")
            file = discord.File(image_buf, filename="leaderboard.png")

            # Try to update existing message or create new one
            if message_id:
                try:
                    message = await channel.fetch_message(message_id)
                    await message.edit(embed=embed, attachments=[file], view=view)
                except discord.NotFound:
                    # Message was deleted, create new one
                    message = await channel.send(embed=embed, file=file, view=view)
                    config["leaderboard_message_id"] = message.id
                    await self.db.update_config(guild_id, config)
                except Exception:
                    # Transient error — don't create a duplicate
                    return
            else:
                # No message ID stored, create new message
                message = await channel.send(embed=embed, file=file, view=view)
                config["leaderboard_message_id"] = message.id
                await self.db.update_config(guild_id, config)
        
    async def restore_region_embed(self, guild_id):
        """Restore the region role selection embed on bot startup."""
        config = await self.db.get_config(guild_id)
        if config.get("region_roles_channel") and config.get("region_roles_message_id"):
            try:
                channel = self.get_channel(config["region_roles_channel"])
                if channel:
                    message = await channel.fetch_message(config["region_roles_message_id"])
                    view = RegionRoleView(self)
                    await message.edit(view=view)
            except Exception:
                pass

    async def post_or_update_region_embed(self, guild_id):
        """Post or update the region role selection embed in the configured channel."""
        config = await self.db.get_config(guild_id)
        channel_id = config.get("region_roles_channel")
        message_id = config.get("region_roles_message_id")

        if not channel_id:
            return

        channel = self.get_channel(channel_id)
        if not channel:
            return

        embed = build_region_embed()
        view = RegionRoleView(self)

        if message_id:
            try:
                message = await channel.fetch_message(message_id)
                await message.edit(embed=embed, view=view)
            except discord.NotFound:
                message = await channel.send(embed=embed, view=view)
                config["region_roles_message_id"] = message.id
                await self.db.update_config(guild_id, config)
            except Exception:
                return
        else:
            message = await channel.send(embed=embed, view=view)
            config["region_roles_message_id"] = message.id
            await self.db.update_config(guild_id, config)

    async def update_queue_embed(self, guild_id):
        async with self._get_queue_embed_lock(guild_id):
            await self._update_queue_embed_inner(guild_id)

    async def _update_queue_embed_inner(self, guild_id):
        config = await self.db.get_config(guild_id)
        if not config["queue_channel"]:
            return

        channel = self.get_channel(config["queue_channel"])
        if not channel:
            return

        # 6v6 queue
        queue = await self.db.get_queue(guild_id, '6v6')

        # Also get highrank queue entries for display
        hr_queue = await self.db.get_queue(guild_id, 'highrank')

        current_season = await self.db.get_current_season(guild_id)
        if current_season:
            season_name = current_season[1]
            title = f"Volleyball Queue - {season_name}"
        else:
            title = "Volleyball Queue - No Active Season"

        # Build per-region queue counts with region-specific totals
        region_counts = {}
        for user_id, position, partner_info in queue:
            player_region = await self.db.get_player_region(guild_id, user_id)
            r = player_region or "Unknown"
            region_counts[r] = region_counts.get(r, 0) + 1

        region_lines = []
        for region, count in sorted(region_counts.items()):
            region_role_limits = get_region_role_limits(config, region)
            region_total = sum(region_role_limits.values())
            team_size_label = get_region_team_size(config, region)
            ready_marker = " **READY**" if count >= region_total else ""
            region_lines.append(f"{region} [{team_size_label}]: {count}/{region_total}{ready_marker}")

        region_summary = "\n".join(region_lines) if region_lines else "No players in queue"

        embed = discord.Embed(
            title=title,
            description=f"**Queue by Region** ({len(queue)} total)\n{region_summary}",
            color=discord.Color.blue()
        )

        positions_dict = {
            "Defense Specialist": [],
            "Front Spiker": [],
            "Setter": [],
            "Libero": []
        }

        for user_id, position, partner_info in queue:
            user = self.get_user(user_id)
            group_text = ""

            if partner_info:
                try:
                    partner_data = json.loads(partner_info) if isinstance(partner_info, str) else partner_info
                    if isinstance(partner_data, dict) and 'trio' in partner_data:
                        trio_members = partner_data['trio']
                        other_members = [m for m in trio_members if m != user_id]
                        partner_names = []
                        for pid in other_members:
                            p = self.get_user(pid)
                            partner_names.append(p.name if p else 'Unknown')
                        group_text = f" (Trio with {', '.join(partner_names)})"
                    else:
                        duo_partner_id = int(partner_data) if not isinstance(partner_data, int) else partner_data
                        p = self.get_user(duo_partner_id)
                        group_text = f" (Duo with {p.name if p else 'Unknown'})"
                except:
                    duo_partner_id = partner_info
                    p = self.get_user(duo_partner_id)
                    group_text = f" (Duo with {p.name if p else 'Unknown'})"

            player_region = await self.db.get_player_region(guild_id, user_id)
            region_tag = f" [{player_region}]" if player_region else ""
            player_text = f"{user.mention if user else f'User {user_id}'}{region_tag}{group_text}"
            if position in positions_dict:
                positions_dict[position].append(player_text)

        for position, players in positions_dict.items():
            limit = config["role_limits"].get(position, 0)
            current = len(players)
            status = "Filled" if current >= limit else f"{current}/{limit}"

            field_name = f"{position} ({status})"
            field_value = "\n".join(players) if players else "Empty"
            embed.add_field(name=field_name, value=field_value[:1024], inline=False)

        # Show high rank queue separately below regular queue
        if config.get("high_rank_enabled", False):
            hr_count = len(hr_queue)
            mmr_limit = config.get('high_rank_mmr_limit', 1000)

            # Build per-region counts for high rank queue
            hr_region_counts = {}
            for user_id, position, partner_info in hr_queue:
                player_region = await self.db.get_player_region(guild_id, user_id)
                r = player_region or "Unknown"
                hr_region_counts[r] = hr_region_counts.get(r, 0) + 1

            hr_region_lines = []
            for region, count in sorted(hr_region_counts.items()):
                region_role_limits = get_region_role_limits(config, region)
                region_total = sum(region_role_limits.values())
                team_size_label = get_region_team_size(config, region)
                ready_marker = " **READY**" if count >= region_total else ""
                hr_region_lines.append(f"{region} [{team_size_label}]: {count}/{region_total}{ready_marker}")

            hr_region_summary = "\n".join(hr_region_lines) if hr_region_lines else "No players"

            embed.add_field(
                name="\u200b",
                value=f"**━━━ High Rank Queue ({hr_count} players) ━━━**\nMMR requirement: {mmr_limit}+\n{hr_region_summary}",
                inline=False
            )

            if hr_queue:
                hr_positions = {
                    "Defense Specialist": [],
                    "Front Spiker": [],
                    "Setter": [],
                    "Libero": []
                }

                for user_id, position, partner_info in hr_queue:
                    user = self.get_user(user_id)
                    player_region = await self.db.get_player_region(guild_id, user_id)
                    region_tag = f" [{player_region}]" if player_region else ""
                    group_text = ""
                    if partner_info:
                        try:
                            partner_data = json.loads(partner_info) if isinstance(partner_info, str) else partner_info
                            if isinstance(partner_data, dict) and 'trio' in partner_data:
                                trio_members = partner_data['trio']
                                other_members = [m for m in trio_members if m != user_id]
                                partner_names = []
                                for pid in other_members:
                                    p = self.get_user(pid)
                                    partner_names.append(p.name if p else 'Unknown')
                                group_text = f" (Trio with {', '.join(partner_names)})"
                            else:
                                duo_partner_id = int(partner_data) if not isinstance(partner_data, int) else partner_data
                                p = self.get_user(duo_partner_id)
                                group_text = f" (Duo with {p.name if p else 'Unknown'})"
                        except:
                            pass

                    player_text = f"{user.mention if user else f'User {user_id}'}{region_tag}{group_text}"
                    if position in hr_positions:
                        hr_positions[position].append(player_text)

                for position, players in hr_positions.items():
                    hr_limit = config["role_limits"].get(position, 0)
                    hr_current = len(players)
                    hr_status = "Filled" if hr_current >= hr_limit else f"{hr_current}/{hr_limit}"
                    field_value = "\n".join(players) if players else "Empty"
                    embed.add_field(name=f"{position} ({hr_status})", value=field_value[:1024], inline=False)
            else:
                embed.add_field(name="High Rank Players", value="No players in high rank queue", inline=False)

        view = QueueView(self, config)
        message_id = self.queue_message_ids.get(guild_id)
        if message_id:
            try:
                message = await channel.fetch_message(message_id)
                await message.edit(embed=embed, view=view)
                return
            except discord.NotFound:
                # Message was deleted, clear the stale ID and send a new one below
                self.queue_message_ids.pop(guild_id, None)
            except Exception:
                # Transient error (rate limit, network, etc.) — don't create a duplicate
                return

        message = await channel.send(embed=embed, view=view)
        self.queue_message_ids[guild_id] = message.id

    async def update_queue_embed_2v2(self, guild_id):
        """Update the 2v2 queue embed."""
        async with self._get_queue_embed_lock(guild_id):
            await self._update_queue_embed_2v2_inner(guild_id)

    async def _update_queue_embed_2v2_inner(self, guild_id):
        config = await self.db.get_config(guild_id)
        channel_id = config.get("queue_2v2_channel")
        if not channel_id:
            return

        channel = self.get_channel(channel_id)
        if not channel:
            return

        queue = await self.db.get_queue(guild_id, '2v2')
        required = 4

        current_season = await self.db.get_current_season(guild_id, '2v2')
        season_text = f" - {current_season[1]}" if current_season else " - No Active Season"

        # Build per-region queue counts for 2v2
        region_counts_2v2 = {}
        for user_id, _, _ in queue:
            player_region = await self.db.get_player_region(guild_id, user_id)
            r = player_region or "Unknown"
            region_counts_2v2[r] = region_counts_2v2.get(r, 0) + 1

        region_lines_2v2 = []
        for region, count in sorted(region_counts_2v2.items()):
            ready_marker = " **READY**" if count >= required else ""
            region_lines_2v2.append(f"{region}: {count}/{required}{ready_marker}")

        region_summary_2v2 = "\n".join(region_lines_2v2) if region_lines_2v2 else "No players in queue"

        embed = discord.Embed(
            title=f"2v2 Queue{season_text}",
            description=f"**Queue by Region** ({len(queue)} total)\n{region_summary_2v2}",
            color=discord.Color.green()
        )

        if queue:
            player_lines = []
            for user_id, _, _ in queue:
                user = self.get_user(user_id)
                elo = await self.db.get_player_elo_simple(guild_id, user_id, '2v2')
                region = await self.db.get_player_region(guild_id, user_id)
                region_tag = f" [{region}]" if region else ""
                player_lines.append(f"{user.mention if user else f'User {user_id}'}{region_tag} - {elo} MMR")
            embed.add_field(name="Players", value="\n".join(player_lines)[:1024], inline=False)
        else:
            embed.add_field(name="Players", value="No players in queue", inline=False)

        # Show high rank 2v2 queue separately if enabled
        if config.get("high_rank_2v2_enabled", False):
            hr_queue = await self.db.get_queue(guild_id, 'highrank_2v2')
            hr_mmr_limit = config.get("high_rank_2v2_mmr_limit", 1000)

            # Build per-region counts for high rank 2v2
            hr_region_counts = {}
            for user_id, _, _ in hr_queue:
                player_region = await self.db.get_player_region(guild_id, user_id)
                r = player_region or "Unknown"
                hr_region_counts[r] = hr_region_counts.get(r, 0) + 1

            hr_region_lines = []
            for region, count in sorted(hr_region_counts.items()):
                ready_marker = " **READY**" if count >= 4 else ""
                hr_region_lines.append(f"{region}: {count}/4{ready_marker}")

            hr_region_summary = "\n".join(hr_region_lines) if hr_region_lines else "No players"

            embed.add_field(
                name="\u200b",
                value=f"**━━━ High Rank 2v2 ({len(hr_queue)} players) ━━━**\nMMR requirement: {hr_mmr_limit}+\n{hr_region_summary}",
                inline=False
            )
            if hr_queue:
                hr_lines = []
                for user_id, _, _ in hr_queue:
                    user = self.get_user(user_id)
                    elo = await self.db.get_player_elo_simple(guild_id, user_id, 'highrank_2v2')
                    region = await self.db.get_player_region(guild_id, user_id)
                    region_tag = f" [{region}]" if region else ""
                    hr_lines.append(f"{user.mention if user else f'User {user_id}'}{region_tag} - {elo} MMR")
                embed.add_field(name="High Rank Players", value="\n".join(hr_lines)[:1024], inline=False)
            else:
                embed.add_field(name="High Rank Players", value="No players in high rank 2v2 queue", inline=False)

        view = Queue2v2View(self, config)
        message_id = self.queue_2v2_message_ids.get(guild_id)
        if message_id:
            try:
                message = await channel.fetch_message(message_id)
                await message.edit(embed=embed, view=view)
                return
            except discord.NotFound:
                self.queue_2v2_message_ids.pop(guild_id, None)
            except Exception:
                return

        message = await channel.send(embed=embed, view=view)
        self.queue_2v2_message_ids[guild_id] = message.id

    async def update_queue_embed_3v3(self, guild_id):
        """Update the 3v3 queue embed."""
        async with self._get_queue_embed_lock(guild_id):
            await self._update_queue_embed_3v3_inner(guild_id)

    async def _update_queue_embed_3v3_inner(self, guild_id):
        config = await self.db.get_config(guild_id)
        channel_id = config.get("queue_3v3_channel")
        if not channel_id:
            return

        channel = self.get_channel(channel_id)
        if not channel:
            return

        queue = await self.db.get_queue(guild_id, '3v3')
        required = 6

        current_season = await self.db.get_current_season(guild_id, '3v3')
        season_text = f" - {current_season[1]}" if current_season else " - No Active Season"

        # Build per-region queue counts for 3v3
        region_counts_3v3 = {}
        for user_id, _, _ in queue:
            player_region = await self.db.get_player_region(guild_id, user_id)
            r = player_region or "Unknown"
            region_counts_3v3[r] = region_counts_3v3.get(r, 0) + 1

        region_lines_3v3 = []
        for region, count in sorted(region_counts_3v3.items()):
            ready_marker = " **READY**" if count >= required else ""
            region_lines_3v3.append(f"{region}: {count}/{required}{ready_marker}")

        region_summary_3v3 = "\n".join(region_lines_3v3) if region_lines_3v3 else "No players in queue"

        embed = discord.Embed(
            title=f"3v3 Queue{season_text}",
            description=f"**Queue by Region** ({len(queue)} total)\n{region_summary_3v3}",
            color=discord.Color.orange()
        )

        if queue:
            player_lines = []
            for user_id, _, partner_info in queue:
                user = self.get_user(user_id)
                elo = await self.db.get_player_elo_simple(guild_id, user_id, '3v3')
                region = await self.db.get_player_region(guild_id, user_id)
                region_tag = f" [{region}]" if region else ""
                group_text = ""
                if partner_info:
                    try:
                        parsed = json.loads(partner_info) if isinstance(partner_info, str) else partner_info
                        if isinstance(parsed, dict) and 'trio' in parsed:
                            trio_members = parsed['trio']
                            other_members = [m for m in trio_members if m != user_id]
                            partner_names = []
                            for pid in other_members:
                                p = self.get_user(pid)
                                partner_names.append(p.name if p else 'Unknown')
                            group_text = f" (Trio with {', '.join(partner_names)})"
                        else:
                            duo_partner_id = int(parsed) if not isinstance(parsed, int) else parsed
                            p = self.get_user(duo_partner_id)
                            group_text = f" (Duo with {p.name if p else 'Unknown'})"
                    except:
                        pass
                player_lines.append(f"{user.mention if user else f'User {user_id}'}{region_tag}{group_text} - {elo} MMR")
            embed.add_field(name="Players", value="\n".join(player_lines)[:1024], inline=False)
        else:
            embed.add_field(name="Players", value="No players in queue", inline=False)

        # Show high rank 3v3 queue separately if enabled
        if config.get("high_rank_3v3_enabled", False):
            hr_queue = await self.db.get_queue(guild_id, 'highrank_3v3')
            hr_mmr_limit = config.get("high_rank_3v3_mmr_limit", 1000)

            # Build per-region counts for high rank 3v3
            hr_region_counts = {}
            for user_id, _, partner_info in hr_queue:
                player_region = await self.db.get_player_region(guild_id, user_id)
                r = player_region or "Unknown"
                hr_region_counts[r] = hr_region_counts.get(r, 0) + 1

            hr_region_lines = []
            for region, count in sorted(hr_region_counts.items()):
                ready_marker = " **READY**" if count >= 6 else ""
                hr_region_lines.append(f"{region}: {count}/6{ready_marker}")

            hr_region_summary = "\n".join(hr_region_lines) if hr_region_lines else "No players"

            embed.add_field(
                name="\u200b",
                value=f"**━━━ High Rank 3v3 ({len(hr_queue)} players) ━━━**\nMMR requirement: {hr_mmr_limit}+\n{hr_region_summary}",
                inline=False
            )
            if hr_queue:
                hr_lines = []
                for user_id, _, partner_info in hr_queue:
                    user = self.get_user(user_id)
                    elo = await self.db.get_player_elo_simple(guild_id, user_id, 'highrank_3v3')
                    region = await self.db.get_player_region(guild_id, user_id)
                    region_tag = f" [{region}]" if region else ""
                    hr_lines.append(f"{user.mention if user else f'User {user_id}'}{region_tag} - {elo} MMR")
                embed.add_field(name="High Rank Players", value="\n".join(hr_lines)[:1024], inline=False)
            else:
                embed.add_field(name="High Rank Players", value="No players in high rank 3v3 queue", inline=False)

        view = Queue3v3View(self, config)
        message_id = self.queue_3v3_message_ids.get(guild_id)
        if message_id:
            try:
                message = await channel.fetch_message(message_id)
                await message.edit(embed=embed, view=view)
                return
            except discord.NotFound:
                self.queue_3v3_message_ids.pop(guild_id, None)
            except Exception:
                return

        message = await channel.send(embed=embed, view=view)
        self.queue_3v3_message_ids[guild_id] = message.id

    async def add_to_queue(self, guild_id, user_id, position, queue_type='6v6'):
        # Check if user is blacklisted (role first, then database)
        guild = self.get_guild(guild_id)
        if guild:
            member = guild.get_member(user_id)
            if member:
                blacklist_role = await self.get_blacklist_role(guild)
                if blacklist_role and blacklist_role in member.roles:
                    return False

        if await self.db.is_blacklisted(guild_id, user_id) is not None:
            return False

        # Check if user is queue banned
        ban = await self.db.get_queue_ban(guild_id, user_id)
        if ban:
            return "queue_banned", ban[0], ban[1]

        # Check if user is in an active match
        if await self.db.is_user_in_active_match(guild_id, user_id):
            return ("in_active_match",)

        success = await self.db.add_to_queue(guild_id, user_id, position, queue_type)
        if success:
            await self._send_queue_join_dm(guild_id, user_id, position, queue_type)
            await self.check_match_ready(guild_id, queue_type)
        return success

    async def add_duo_to_queue(self, guild_id, user1_id, user2_id, pos1, pos2):
        # Check if either user is blacklisted
        guild = self.get_guild(guild_id)
        if guild:
            blacklist_role = await self.get_blacklist_role(guild)
            if blacklist_role:
                for user_id in [user1_id, user2_id]:
                    member = guild.get_member(user_id)
                    if member and blacklist_role in member.roles:
                        return False

        # Check database
        for user_id in [user1_id, user2_id]:
            if await self.db.is_blacklisted(guild_id, user_id) is not None:
                return False

        # Check if either user is in an active match
        for user_id in [user1_id, user2_id]:
            if await self.db.is_user_in_active_match(guild_id, user_id):
                return ("in_active_match",)

        success = await self.db.add_duo_to_queue(guild_id, user1_id, user2_id, pos1, pos2, '6v6')
        if success:
            await self._send_queue_join_dm(guild_id, user1_id, pos1, '6v6')
            await self._send_queue_join_dm(guild_id, user2_id, pos2, '6v6')
            await self.check_match_ready(guild_id, '6v6')
        return success
        
    async def add_trio_to_queue(self, guild_id, user1_id, user2_id, user3_id, pos1, pos2, pos3):
        """Add a trio to the queue"""
        # Check if any user is blacklisted
        guild = self.get_guild(guild_id)
        if guild:
            blacklist_role = await self.get_blacklist_role(guild)
            if blacklist_role:
                for user_id in [user1_id, user2_id, user3_id]:
                    member = guild.get_member(user_id)
                    if member and blacklist_role in member.roles:
                        return False

        # Check database
        for user_id in [user1_id, user2_id, user3_id]:
            if await self.db.is_blacklisted(guild_id, user_id) is not None:
                return False

        # Check if any user is in an active match
        for user_id in [user1_id, user2_id, user3_id]:
            if await self.db.is_user_in_active_match(guild_id, user_id):
                return ("in_active_match",)
        
        try:
            await self.db.db.execute('BEGIN')
            
            # Create trio data
            trio_data = json.dumps({'trio': [user1_id, user2_id, user3_id]})
            
            # Add all three players
            await self.db.db.execute(
                'INSERT INTO queue (guild_id, user_id, position, duo_partner, queue_type) VALUES (?, ?, ?, ?, ?)',
                (guild_id, user1_id, pos1, trio_data, '6v6')
            )
            await self.db.db.execute(
                'INSERT INTO queue (guild_id, user_id, position, duo_partner, queue_type) VALUES (?, ?, ?, ?, ?)',
                (guild_id, user2_id, pos2, trio_data, '6v6')
            )
            await self.db.db.execute(
                'INSERT INTO queue (guild_id, user_id, position, duo_partner, queue_type) VALUES (?, ?, ?, ?, ?)',
                (guild_id, user3_id, pos3, trio_data, '6v6')
            )

            await self.db.db.commit()
            await self._send_queue_join_dm(guild_id, user1_id, pos1, '6v6')
            await self._send_queue_join_dm(guild_id, user2_id, pos2, '6v6')
            await self._send_queue_join_dm(guild_id, user3_id, pos3, '6v6')
            await self.check_match_ready(guild_id, '6v6')
            return True
        except:
            await self.db.db.rollback()
            return False
            
    async def _send_queue_join_dm(self, guild_id, user_id, position, queue_type='6v6'):
        """Send a DM to a player when they join a queue."""
        try:
            user = self.get_user(user_id)
            if not user:
                return

            config = await self.db.get_config(guild_id)
            guild = self.get_guild(guild_id)
            guild_name = guild.name if guild else "the server"

            # Get current queue count for their position
            queue = await self.db.get_queue(guild_id, queue_type)
            queue_count = len(queue)

            # Get player's region and determine team size label
            region = await self.db.get_player_region(guild_id, user_id)
            team_size_label = get_region_team_size(config, region) if region else "6v6"

            # Determine display name for queue type
            queue_display = queue_type.upper()
            if queue_type == 'highrank':
                queue_display = "High Rank"
            elif queue_type == 'highrank_2v2':
                queue_display = "High Rank 2v2"
            elif queue_type == 'highrank_3v3':
                queue_display = "High Rank 3v3"
            elif queue_type == '6v6':
                queue_display = "Regular"

            # Build position text
            if queue_type in ('2v2', '3v3', 'highrank_2v2', 'highrank_3v3'):
                pos_text = ""
            else:
                pos_text = f"**Position:** {position}\n"

            # Get AFK timer info
            afk_timer = config.get("afk_timer", 1800)
            if afk_timer > 0:
                afk_text = f"**AFK Timer:** {format_duration(afk_timer)} — you'll be removed if idle."
            else:
                afk_text = "**AFK Timer:** Disabled"

            region_text = f"**Region:** {region}\n" if region else ""

            # Build per-region queue breakdown
            region_counts = {}
            for uid, _, _ in queue:
                pr = await self.db.get_player_region(guild_id, uid)
                r = pr or "Unknown"
                region_counts[r] = region_counts.get(r, 0) + 1

            region_breakdown_lines = []
            for r, count in sorted(region_counts.items()):
                if queue_type in ('2v2', 'highrank_2v2'):
                    total = 4
                elif queue_type in ('3v3', 'highrank_3v3'):
                    total = 6
                else:
                    rlimits = get_region_role_limits(config, r)
                    total = sum(rlimits.values())
                ts_label = get_region_team_size(config, r) if queue_type in ('6v6', 'highrank') else ""
                ts_tag = f" [{ts_label}]" if ts_label else ""
                ready_marker = " READY" if count >= total else ""
                region_breakdown_lines.append(f"{r}{ts_tag}: {count}/{total}{ready_marker}")

            region_breakdown = "\n".join(region_breakdown_lines) if region_breakdown_lines else "No other players"

            dm_embed = discord.Embed(
                title="🏐 Joined Queue!",
                description=(
                    f"You've joined the **{queue_display}** queue in **{guild_name}**!\n\n"
                    f"{pos_text}"
                    f"{region_text}"
                    f"**Players in queue:** {queue_count}\n"
                    f"{region_breakdown}\n\n"
                    f"{afk_text}"
                ),
                color=discord.Color.green()
            )
            await user.send(embed=dm_embed)
        except (discord.Forbidden, discord.HTTPException):
            pass
        except Exception:
            pass

    async def remove_from_queue(self, guild_id, user_id):
        # Check if user has partners (duo or trio)
        async with self.db.db.execute(
            'SELECT duo_partner FROM queue WHERE guild_id = ? AND user_id = ?',
            (guild_id, user_id)
        ) as cursor:
            row = await cursor.fetchone()
            if row and row[0]:
                partner_data = row[0]
                try:
                    # Try to parse as JSON (trio)
                    parsed = json.loads(partner_data) if isinstance(partner_data, str) else partner_data
                    if isinstance(parsed, dict) and 'trio' in parsed:
                        # Remove all trio members
                        trio_members = parsed['trio']
                        placeholders = ','.join('?' for _ in trio_members)
                        await self.db.db.execute(
                            f'DELETE FROM queue WHERE guild_id = ? AND user_id IN ({placeholders})',
                            (guild_id, *trio_members)
                        )
                    else:
                        # Remove duo
                        await self.db.db.execute(
                            'DELETE FROM queue WHERE guild_id = ? AND (user_id = ? OR user_id = ?)',
                            (guild_id, user_id, int(parsed))
                        )
                except:
                    # Old format duo
                    await self.db.db.execute(
                        'DELETE FROM queue WHERE guild_id = ? AND (user_id = ? OR user_id = ?)',
                        (guild_id, user_id, partner_data)
                    )
            else:
                # Remove solo player
                await self.db.db.execute(
                    'DELETE FROM queue WHERE guild_id = ? AND user_id = ?',
                    (guild_id, user_id)
                )
        
        await self.db.db.commit()
        return True
            
    async def check_match_ready(self, guild_id, queue_type='6v6'):
        config = await self.db.get_config(guild_id)
        queue = await self.db.get_queue(guild_id, queue_type)

        # Group queued players by region
        regional_queues = {}
        for user_id, position, partner_info in queue:
            region = await self.db.get_player_region(guild_id, user_id)
            if region is None:
                region = "__none__"
            if region not in regional_queues:
                regional_queues[region] = []
            regional_queues[region].append((user_id, position, partner_info))

        # Check each region for enough players
        for region, region_queue in regional_queues.items():
            match_region = region if region != "__none__" else None

            # Determine required players based on queue type and region
            if queue_type == '2v2':
                total_required = 4
            elif queue_type == '3v3':
                total_required = 6
            else:
                # 6v6 and highrank use region-specific role_limits
                region_role_limits = get_region_role_limits(config, region)
                total_required = sum(region_role_limits.values())

            if len(region_queue) >= total_required:
                if queue_type in ('2v2', '3v3'):
                    # No position requirements for 2v2/3v3
                    await self.create_match(guild_id, region_queue[:total_required], match_type=queue_type, region=match_region)
                    break
                else:
                    # 6v6/highrank: select players atomically (never split parties)
                    selected = self._select_match_players(region_queue, region_role_limits)
                    if selected:
                        await self.create_match(guild_id, selected, match_type=queue_type, region=match_region)
                        break

    def _select_match_players(self, region_queue, role_limits):
        """Select players for a match, keeping parties atomic.

        Iterates through the queue in FIFO order. Groups (duos/trios) are
        treated as indivisible units: either every member fits the remaining
        role slots or the entire group is skipped. Solo players are added
        individually if their position still has capacity.

        Returns a list of (user_id, position, partner_info) if a valid
        match can be formed, otherwise None.
        """
        total_required = sum(role_limits.values())
        selected = []
        position_counts = {pos: 0 for pos in role_limits}
        processed_users = set()
        seen_groups = set()

        # Build a lookup of queue entries for finding group members
        queue_by_user = {uid: (uid, pos, pi) for uid, pos, pi in region_queue}

        for user_id, position, partner_info in region_queue:
            if user_id in processed_users:
                continue
            if len(selected) >= total_required:
                break

            # Determine if this player is part of a group
            group_members = None
            if partner_info:
                try:
                    parsed = json.loads(partner_info) if isinstance(partner_info, str) else partner_info
                    if isinstance(parsed, dict) and 'trio' in parsed:
                        group_key = tuple(sorted(parsed['trio']))
                        if group_key in seen_groups:
                            continue
                        seen_groups.add(group_key)
                        # Collect all trio members from the queue
                        group_members = []
                        for mid in parsed['trio']:
                            if mid in queue_by_user:
                                group_members.append(queue_by_user[mid])
                        if len(group_members) != len(parsed['trio']):
                            continue  # Not all trio members in this region queue
                    else:
                        duo_partner = int(parsed) if not isinstance(parsed, int) else parsed
                        group_key = tuple(sorted([user_id, duo_partner]))
                        if group_key in seen_groups:
                            continue
                        seen_groups.add(group_key)
                        if duo_partner in queue_by_user:
                            group_members = [
                                queue_by_user[user_id],
                                queue_by_user[duo_partner]
                            ]
                        else:
                            continue  # Partner not in this region queue
                except (json.JSONDecodeError, ValueError, TypeError):
                    pass

            if group_members:
                # Check if ALL group members' positions fit within remaining limits
                can_fit = True
                temp_counts = dict(position_counts)
                for _, gpos, _ in group_members:
                    current = temp_counts.get(gpos, 0)
                    limit = role_limits.get(gpos, 0)
                    if current >= limit:
                        can_fit = False
                        break
                    temp_counts[gpos] = current + 1

                if can_fit and len(selected) + len(group_members) <= total_required:
                    for member in group_members:
                        selected.append(member)
                        position_counts[member[1]] = position_counts.get(member[1], 0) + 1
                        processed_users.add(member[0])
                # If can't fit, skip the entire group (they stay in queue)
            else:
                # Solo player
                current = position_counts.get(position, 0)
                limit = role_limits.get(position, 0)
                if current < limit:
                    selected.append((user_id, position, partner_info))
                    position_counts[position] = current + 1
                    processed_users.add(user_id)

        # Verify all positions are fully filled
        if len(selected) == total_required:
            all_filled = all(
                position_counts.get(pos, 0) >= limit
                for pos, limit in role_limits.items()
            )
            if all_filled:
                return selected

        return None
                
    async def create_match(self, guild_id, players, match_type='6v6', region=None):
        # Get ELO for each player based on match type
        sorted_players = []
        player_positions = {}
        group_info = {}

        for user_id, position, partner_info in players:
            if match_type in ('2v2', '3v3'):
                elo = await self.db.get_player_elo_simple(guild_id, user_id, match_type)
            elif match_type == 'highrank':
                elo = await self.db.get_player_elo_highrank(guild_id, user_id, position)
            else:
                elo = await self.db.get_player_elo(guild_id, user_id, position)
            sorted_players.append((user_id, position, elo, partner_info))
            player_positions[user_id] = position

            # Parse group info
            if partner_info:
                try:
                    parsed = json.loads(partner_info) if isinstance(partner_info, str) else partner_info
                    if isinstance(parsed, dict) and 'trio' in parsed:
                        for member in parsed['trio']:
                            group_info[member] = ('trio', parsed['trio'])
                    else:
                        duo_partner = int(parsed) if not isinstance(parsed, int) else parsed
                        group_info[user_id] = ('duo', [user_id, duo_partner])
                        group_info[duo_partner] = ('duo', [user_id, duo_partner])
                except:
                    duo_partner = partner_info
                    group_info[user_id] = ('duo', [user_id, duo_partner])
                    group_info[duo_partner] = ('duo', [user_id, duo_partner])

        # Balance teams
        if match_type in ('2v2', '3v3'):
            team_size = 2 if match_type == '2v2' else 3
            # Simple balancing by MMR for non-position queues
            sorted_players.sort(key=lambda x: x[2], reverse=True)
            team1 = []
            team2 = []
            for player in sorted_players:
                team1_elo = sum(p[2] for p in team1) if team1 else 0
                team2_elo = sum(p[2] for p in team2) if team2 else 0
                if len(team1) < team_size and (len(team2) >= team_size or team1_elo <= team2_elo):
                    team1.append(player)
                else:
                    team2.append(player)
        else:
            # Position-based balancing for 6v6 and highrank
            team1 = []
            team2 = []
            processed = set()

            # First, place trios
            for player in sorted_players:
                user_id, position, elo, _ = player
                if user_id in processed:
                    continue
                if user_id in group_info and group_info[user_id][0] == 'trio':
                    trio_members = group_info[user_id][1]
                    trio_players = [p for p in sorted_players if p[0] in trio_members]
                    if len(team1) + len(trio_players) <= 6:
                        team1.extend(trio_players)
                    elif len(team2) + len(trio_players) <= 6:
                        team2.extend(trio_players)
                    else:
                        continue
                    for member in trio_members:
                        processed.add(member)

            # Then, place duos
            for player in sorted_players:
                user_id, position, elo, _ = player
                if user_id in processed:
                    continue
                if user_id in group_info and group_info[user_id][0] == 'duo':
                    duo_members = group_info[user_id][1]
                    duo_players = [p for p in sorted_players if p[0] in duo_members]
                    if len(team1) <= len(team2):
                        team1.extend(duo_players)
                    else:
                        team2.extend(duo_players)
                    for member in duo_members:
                        processed.add(member)

            # Then place remaining players
            sorted_players.sort(key=lambda x: x[2], reverse=True)
            for player in sorted_players:
                user_id = player[0]
                if user_id not in processed:
                    if len(team1) <= len(team2):
                        team1.append(player)
                    else:
                        team2.append(player)

        # Get guild and config
        guild = self.get_guild(guild_id)
        config = await self.db.get_config(guild_id)

        # Create match channels
        text_channel = None
        voice_channel = None

        if guild and config.get("match_category"):
            category = guild.get_channel(config["match_category"])
            if category and isinstance(category, discord.CategoryChannel):
                channel_name = f"match-{match_type}-{len(team1)+len(team2)}p"
                text_channel = await guild.create_text_channel(
                    channel_name,
                    category=category,
                    topic=f"{match_type.upper()} Match - Team sizes: {len(team1)} vs {len(team2)}"
                )
                voice_channel = await guild.create_voice_channel(
                    f"Match {match_type.upper()} {len(team1)}v{len(team2)}",
                    category=category,
                    user_limit=len(team1) + len(team2)
                )

                all_players = [p[0] for p in team1 + team2]
                # Text channel: hidden from everyone, visible to match players
                await text_channel.set_permissions(guild.default_role, view_channel=False)
                for player_id in all_players:
                    member = guild.get_member(player_id)
                    if member:
                        await text_channel.set_permissions(member, view_channel=True)

                # Voice channel: visible but not joinable for everyone, joinable for match players
                await voice_channel.set_permissions(guild.default_role, view_channel=True, connect=False)
                for player_id in all_players:
                    member = guild.get_member(player_id)
                    if member:
                        await voice_channel.set_permissions(member, view_channel=True, connect=True)

        # Remove players from queue
        player_ids = [p[0] for p in team1 + team2]
        for player_id in player_ids:
            await self.db.remove_from_queue(guild_id, player_id)

        # Store match data
        match_data = {
            "team1": [(p[0], p[1]) for p in team1],
            "team2": [(p[0], p[1]) for p in team2]
        }
        match_id = await self.db.create_match(
            guild_id,
            match_data["team1"],
            match_data["team2"],
            text_channel.id if text_channel else None,
            voice_channel.id if voice_channel else None,
            match_type=match_type,
            region=region
        )

        # Log match creation
        player_list = ", ".join([f"<@{p[0]}>" for p in team1 + team2])
        region_text = f" ({region})" if region else ""
        await self.log_action(
            guild_id,
            f"Match #{match_id} Created",
            f"**Type:** {match_type.upper()}{region_text}\n**Players:** {player_list}",
            color=discord.Color.green()
        )

        # DM all players that their match has been found
        guild = self.get_guild(guild_id)
        guild_name = guild.name if guild else "the server"
        for player_id, position, elo, _ in team1 + team2:
            try:
                user = self.get_user(player_id)
                if user:
                    channel_lines = ""
                    if text_channel:
                        channel_lines += f"\n**Text Channel:** {text_channel.mention}"
                    if voice_channel:
                        channel_lines += f"\n**Voice Channel:** {voice_channel.mention}"
                    dm_embed = discord.Embed(
                        title="\U0001f3d0 Match Found!",
                        description=(
                            f"Your **{match_type.upper()}** match has been found in **{guild_name}**!\n\n"
                            f"**Match #{match_id}**{region_text}"
                            f"{channel_lines}\n\n"
                            f"Please head to the match channel and ready up."
                        ),
                        color=discord.Color.green()
                    )
                    await user.send(embed=dm_embed)
            except Exception:
                pass

        # Create ready check embed
        if text_channel:
            player_mentions = " ".join([f"<@{p[0]}>" for p in team1 + team2])

            ready_view = ReadyCheckView(
                self,
                match_id,
                match_data["team1"],
                match_data["team2"],
                config.get("ready_check_timeout", 300),
                match_type=match_type,
                text_channel_id=text_channel.id,
                voice_channel_id=voice_channel.id if voice_channel else None
            )
            self.ready_check_views[match_id] = ready_view

            embed = await ready_view.build_ready_embed(guild_id)

            await text_channel.send(player_mentions)
            ready_msg = await text_channel.send(embed=embed, view=ready_view)
            ready_view.start_reminder_task(ready_msg)
        else:
            # If no text channel, create match directly in queue channel
            config = await self.db.get_config(guild_id)
            queue_channel_key = "queue_channel"
            if match_type == '2v2':
                queue_channel_key = "queue_2v2_channel"
            elif match_type == '3v3':
                queue_channel_key = "queue_3v3_channel"

            channel_id = config.get(queue_channel_key) or config.get("queue_channel")
            if channel_id:
                channel = self.get_channel(channel_id)
                if channel:
                    embed = discord.Embed(
                        title=f"Match Created! ({match_type.upper()})",
                        description="Teams have been balanced based on ELO ratings",
                        color=discord.Color.green()
                    )

                    team1_text = ""
                    team2_text = ""

                    for user_id, position, elo, _ in team1:
                        user = self.get_user(user_id)
                        if match_type in ('2v2', '3v3'):
                            team1_text += f"{user.mention if user else f'User {user_id}'} ({elo} MMR)\n"
                        else:
                            team1_text += f"{user.mention if user else f'User {user_id}'} - {position} ({elo} ELO)\n"

                    for user_id, position, elo, _ in team2:
                        user = self.get_user(user_id)
                        if match_type in ('2v2', '3v3'):
                            team2_text += f"{user.mention if user else f'User {user_id}'} ({elo} MMR)\n"
                        else:
                            team2_text += f"{user.mention if user else f'User {user_id}'} - {position} ({elo} ELO)\n"

                    embed.add_field(name="Team 1", value=team1_text or "Empty", inline=True)
                    embed.add_field(name="Team 2", value=team2_text or "Empty", inline=True)

                    avg_elo_team1 = sum(p[2] for p in team1) / len(team1)
                    avg_elo_team2 = sum(p[2] for p in team2) / len(team2)
                    embed.add_field(
                        name="Average ELO",
                        value=f"Team 1: {avg_elo_team1:.0f}\nTeam 2: {avg_elo_team2:.0f}",
                        inline=False
                    )

                    embed.set_footer(text=f"Match ID: {match_id}")

                    view = MatchResultView(
                        self,
                        match_id,
                        match_data["team1"],
                        match_data["team2"],
                        match_type=match_type
                    )

                    await channel.send(embed=embed, view=view)

        return match_id
        
    def calculate_elo_change(self, winner_elo, loser_elo, k_factor):
        expected_winner = 1 / (1 + 10 ** ((loser_elo - winner_elo) / 400))
        expected_loser = 1 - expected_winner
        
        winner_change = k_factor * (1 - expected_winner)
        loser_change = k_factor * (0 - expected_loser)
        
        return int(winner_change), int(loser_change)
        
    async def log_action(self, guild_id, action_title, description, user=None, color=None, log_type="general"):
        """Log a bot action to the configured log channel.

        log_type: 'general' (default), 'readyup', or 'admin'
        """
        config = await self.db.get_config(guild_id)

        # Determine which channel(s) to log to
        channel_ids = []
        if log_type == "readyup":
            ch = config.get("log_channel_readyup")
            if ch:
                channel_ids.append(ch)
            else:
                # Fall back to general log
                ch = config.get("log_channel")
                if ch:
                    channel_ids.append(ch)
        elif log_type == "admin":
            ch = config.get("log_channel_admin")
            if ch:
                channel_ids.append(ch)
            else:
                # Fall back to general log
                ch = config.get("log_channel")
                if ch:
                    channel_ids.append(ch)
        else:
            ch = config.get("log_channel")
            if ch:
                channel_ids.append(ch)

        if not channel_ids:
            return

        if color is None:
            color = discord.Color.blue()

        embed = discord.Embed(
            title=action_title,
            description=description,
            color=color,
            timestamp=datetime.utcnow()
        )

        if user is not None:
            embed.set_footer(text=f"Performed by {user}", icon_url=user.display_avatar.url if hasattr(user, 'display_avatar') else None)

        for log_channel_id in channel_ids:
            channel = self.get_channel(log_channel_id)
            if not channel:
                continue
            try:
                await channel.send(embed=embed)
            except Exception as e:
                print(f"Failed to send log message to channel {log_channel_id}: {e}")

    async def log_interaction(self, interaction: discord.Interaction, action_desc: str):
        """Log any command or button interaction to the general log channel."""
        config = await self.db.get_config(interaction.guild.id)
        log_channel_id = config.get("log_channel")
        if not log_channel_id:
            return

        channel = self.get_channel(log_channel_id)
        if not channel:
            return

        embed = discord.Embed(
            description=f"{interaction.user.mention} — {action_desc}",
            color=discord.Color.light_grey(),
            timestamp=datetime.utcnow()
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url if hasattr(interaction.user, 'display_avatar') else None)

        try:
            await channel.send(embed=embed)
        except Exception:
            pass

    @tasks.loop(seconds=30)
    async def update_queue_embeds(self):
        for guild in self.guilds:
            if ALLOWED_GUILD_ID == 0 or guild.id == ALLOWED_GUILD_ID:
                await self.update_queue_embed(guild.id)
                await self.update_queue_embed_2v2(guild.id)
                await self.update_queue_embed_3v3(guild.id)
            
    @tasks.loop(minutes=5)
    async def check_queue_timeouts(self):
        # Remove players who have been in queue too long
        for guild in self.guilds:
            if ALLOWED_GUILD_ID == 0 or guild.id == ALLOWED_GUILD_ID:
                config = await self.db.get_config(guild.id)
                timeout = config["queue_timeout"]
                
                await self.db.remove_old_queue_entries(guild.id, timeout)
            
    @tasks.loop(minutes=5)
    async def update_leaderboards(self):
        for guild in self.guilds:
            if ALLOWED_GUILD_ID == 0 or guild.id == ALLOWED_GUILD_ID:
                await self.post_or_update_leaderboard(guild.id)
                
    @tasks.loop(minutes=30)
    async def cleanup_old_channels(self):
        """Clean up match channels that have been inactive for too long"""
        for guild in self.guilds:
            if ALLOWED_GUILD_ID == 0 or guild.id == ALLOWED_GUILD_ID:
                config = await self.db.get_config(guild.id)
                timeout = config.get("match_channel_timeout", 3600)  # Use config value
                
                # Get all active matches
                active_matches = await self.db.get_active_matches(guild.id)
                
                for match_id, text_channel_id, voice_channel_id in active_matches:
                    # Check if channels still exist and are empty
                    should_cleanup = False
                    
                    if voice_channel_id:
                        voice_channel = self.get_channel(voice_channel_id)
                        if voice_channel and isinstance(voice_channel, discord.VoiceChannel):
                            if len(voice_channel.members) == 0:
                                # Check last message time in text channel
                                if text_channel_id:
                                    text_channel = self.get_channel(text_channel_id)
                                    if text_channel:
                                        try:
                                            last_message = await text_channel.fetch_message(text_channel.last_message_id)
                                            if (discord.utils.utcnow() - last_message.created_at).total_seconds() > timeout:
                                                should_cleanup = True
                                        except:
                                            should_cleanup = True
                                    else:
                                        should_cleanup = True
                                else:
                                    should_cleanup = True
                        else:
                            # Voice channel doesn't exist, clean up
                            should_cleanup = True
                            
                    if should_cleanup:
                        # Clean up channels
                        if text_channel_id:
                            text_channel = self.get_channel(text_channel_id)
                            if text_channel:
                                try:
                                    await text_channel.delete(reason="Match inactive")
                                except:
                                    pass
                                    
                        if voice_channel_id:
                            voice_channel = self.get_channel(voice_channel_id)
                            if voice_channel:
                                try:
                                    await voice_channel.delete(reason="Match inactive")
                                except:
                                    pass
                                    
                        # Mark match as inactive
                        await self.db.set_match_inactive(match_id)
                        
                        # Clean up ready check view
                        if match_id in self.ready_check_views:
                            del self.ready_check_views[match_id]

    @tasks.loop(minutes=1)
    async def check_afk_timer(self):
        """Remove players from queue who have been idle beyond the AFK timer."""
        for guild in self.guilds:
            if ALLOWED_GUILD_ID == 0 or guild.id == ALLOWED_GUILD_ID:
                config = await self.db.get_config(guild.id)
                afk_timer = config.get("afk_timer", 1800)  # Default 30 minutes

                afk_entries = await self.db.get_afk_queue_entries(guild.id, afk_timer)

                if not afk_entries:
                    continue

                for entry in afk_entries:
                    user_id = entry[0]
                    await self.remove_from_queue(guild.id, user_id)

                    # DM the player about the removal
                    try:
                        user = self.get_user(user_id)
                        if user:
                            afk_embed = discord.Embed(
                                title="Removed from Queue - AFK",
                                description=(
                                    f"You have been removed from the queue in **{guild.name}** "
                                    f"due to inactivity (AFK for more than {afk_timer // 60} minutes).\n\n"
                                    f"You can rejoin the queue at any time."
                                ),
                                color=discord.Color.orange()
                            )
                            await user.send(embed=afk_embed)
                    except Exception:
                        pass

                # Update queue embeds after removals
                await self.update_queue_embed(guild.id)
                await self.update_queue_embed_2v2(guild.id)
                await self.update_queue_embed_3v3(guild.id)

    async def close(self):
        await self.db.close()
        await super().close()


# Create and run the bot
if __name__ == "__main__":
    bot = VolleyballBot()
    bot.run(BOT_TOKEN)