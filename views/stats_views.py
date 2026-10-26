# views/stats_views.py
"""
Interactive stats view with queue type toggle buttons.
Shows the stats card image inside a Discord embed with buttons to switch
between Regular (6v6), 2v2, and 3v3 queue views.
"""

import discord
import io


class StatsView(discord.ui.View):
    """View with buttons to toggle between queue types for the stats card."""

    def __init__(self, bot, interaction_user, target_user, guild_id, stats_data, timeout=120):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.interaction_user = interaction_user
        self.target_user = target_user
        self.guild_id = guild_id
        self.stats_data = stats_data  # dict with all pre-fetched data
        self.current_queue = "regular"  # regular, 2v2, 3v3
        self._update_button_styles()

    def _update_button_styles(self):
        """Highlight the active queue button."""
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                if child.custom_id == f"stats_queue_{self.current_queue}":
                    child.style = discord.ButtonStyle.primary
                elif child.custom_id and child.custom_id.startswith("stats_queue_"):
                    child.style = discord.ButtonStyle.secondary

    async def _generate_and_send(self, interaction: discord.Interaction):
        from stats_card import generate_stats_card
        data = self.stats_data
        display_name = data.get("_display_name_override", self.target_user.display_name)

        # Select recent matches for the current queue focus
        if self.current_queue == "2v2":
            focus_recent = data.get("recent_matches_2v2")
        elif self.current_queue == "3v3":
            focus_recent = data.get("recent_matches_3v3")
        else:
            focus_recent = data["recent_matches"]

        image_buf = await generate_stats_card(
            username=display_name,
            avatar_bytes=data["avatar_bytes"],
            ds_elo=data["ds_elo"], fs_elo=data["fs_elo"],
            s_elo=data["s_elo"], l_elo=data["l_elo"],
            games=data["games"], wins=data["wins"], losses=data["losses"],
            ds_games=data["ds_games"], fs_games=data["fs_games"],
            s_games=data["s_games"], l_games=data["l_games"],
            win_streak=data["ws"], loss_streak=data["ls"],
            best_win_streak=data["best_ws"], best_loss_streak=data["best_ls"],
            rank_position=data["rank_position"], total_players=data["total_players"],
            rank_role_name=data["rank_role_name"],
            rank_role_color=data.get("rank_role_color"),
            rank_role_threshold=data["rank_threshold"],
            next_rank_threshold=data["next_threshold"],
            stats_2v2=data["stats_2v2"], stats_3v3=data["stats_3v3"],
            hr_stats=data["hr_stats"], hr_2v2=data["hr_2v2"], hr_3v3=data["hr_3v3"],
            hr_ds_games=data.get("hr_ds_games", 0), hr_fs_games=data.get("hr_fs_games", 0),
            hr_s_games=data.get("hr_s_games", 0), hr_l_games=data.get("hr_l_games", 0),
            elo_history=data["elo_history"],
            elo_history_regular=data.get("elo_history_regular"),
            elo_history_highrank=data.get("elo_history_highrank"),
            elo_history_ds=data.get("elo_history_ds"),
            elo_history_fs=data.get("elo_history_fs"),
            elo_history_s=data.get("elo_history_s"),
            elo_history_l=data.get("elo_history_l"),
            elo_history_2v2=data.get("elo_history_2v2"),
            elo_history_3v3=data.get("elo_history_3v3"),
            elo_history_hr_ds=data.get("elo_history_hr_ds"),
            elo_history_hr_fs=data.get("elo_history_hr_fs"),
            elo_history_hr_s=data.get("elo_history_hr_s"),
            elo_history_hr_l=data.get("elo_history_hr_l"),
            elo_history_hr_2v2=data.get("elo_history_hr_2v2"),
            elo_history_hr_3v3=data.get("elo_history_hr_3v3"),
            recent_matches=focus_recent,
            is_5v5=data["is_5v5"],
            starting_elo=data["starting_elo"],
            streaks_2v2=data["streaks_2v2"],
            streaks_3v3=data["streaks_3v3"],
            queue_focus=self.current_queue,
            tier_roles=data.get("tier_roles"),
            region_label=data.get("region_label"),
            ds_wl=data.get("ds_wl"), fs_wl=data.get("fs_wl"),
            s_wl=data.get("s_wl"), l_wl=data.get("l_wl"),
            hr_ds_wl=data.get("hr_ds_wl"), hr_fs_wl=data.get("hr_fs_wl"),
            hr_s_wl=data.get("hr_s_wl"), hr_l_wl=data.get("hr_l_wl"),
            streaks_hr=data.get("streaks_hr"),
            streaks_hr_2v2=data.get("streaks_hr_2v2"),
            streaks_hr_3v3=data.get("streaks_hr_3v3"),
        )

        embed = discord.Embed(color=discord.Color.from_rgb(32, 34, 40))
        embed.set_image(url="attachment://stats.png")
        footer_parts = [f"Viewing: {self.current_queue.upper()} queue stats"]
        if data.get("_season_name"):
            footer_parts.insert(0, f"Season: {data['_season_name']}")
        if data.get("region_label"):
            footer_parts.append(f"[{data['region_label']}]")
        embed.set_footer(text=" | ".join(footer_parts))

        self._update_button_styles()
        file = discord.File(image_buf, filename="stats.png")
        await interaction.response.edit_message(embed=embed, attachments=[file], view=self)

    @discord.ui.button(label="Regular", style=discord.ButtonStyle.primary, custom_id="stats_queue_regular", emoji="\U0001f3d0", row=0)
    async def regular_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.interaction_user.id:
            await interaction.response.send_message("Only the command user can interact.", ephemeral=True)
            return
        self.current_queue = "regular"
        await self._generate_and_send(interaction)

    @discord.ui.button(label="2v2", style=discord.ButtonStyle.secondary, custom_id="stats_queue_2v2", emoji="\U0001f465", row=0)
    async def twov2_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.interaction_user.id:
            await interaction.response.send_message("Only the command user can interact.", ephemeral=True)
            return
        self.current_queue = "2v2"
        await self._generate_and_send(interaction)

    @discord.ui.button(label="3v3", style=discord.ButtonStyle.secondary, custom_id="stats_queue_3v3", emoji="\U0001f46a", row=0)
    async def threev3_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.interaction_user.id:
            await interaction.response.send_message("Only the command user can interact.", ephemeral=True)
            return
        self.current_queue = "3v3"
        await self._generate_and_send(interaction)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


class CompareView(discord.ui.View):
    """View with buttons to toggle between queue types for the compare card."""

    def __init__(self, bot, interaction_user, compare_data, timeout=120):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.interaction_user = interaction_user
        self.compare_data = compare_data  # dict with all pre-fetched data
        self.current_queue = "regular"  # regular, 2v2, 3v3
        self._update_button_styles()

    def _update_button_styles(self):
        """Highlight the active queue button."""
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                if child.custom_id == f"compare_queue_{self.current_queue}":
                    child.style = discord.ButtonStyle.primary
                elif child.custom_id and child.custom_id.startswith("compare_queue_"):
                    child.style = discord.ButtonStyle.secondary

    async def _generate_and_send(self, interaction: discord.Interaction):
        from stats_card import generate_compare_card
        d = self.compare_data

        # Select recent matches for the current queue focus
        if self.current_queue == "2v2":
            p1_focus_recent = d.get("p1_recent_2v2")
            p2_focus_recent = d.get("p2_recent_2v2")
        elif self.current_queue == "3v3":
            p1_focus_recent = d.get("p1_recent_3v3")
            p2_focus_recent = d.get("p2_recent_3v3")
        else:
            p1_focus_recent = d["p1_recent"]
            p2_focus_recent = d["p2_recent"]

        image_buf = await generate_compare_card(
            player1_name=d["player1_name"],
            player2_name=d["player2_name"],
            player1_avatar=d["player1_avatar"],
            player2_avatar=d["player2_avatar"],
            p1_stats=d["p1_stats"],
            p2_stats=d["p2_stats"],
            p1_games_per_pos=d["p1_games_per_pos"],
            p2_games_per_pos=d["p2_games_per_pos"],
            p1_rank=d["p1_rank"],
            p2_rank=d["p2_rank"],
            p1_2v2=d["p1_2v2"], p2_2v2=d["p2_2v2"],
            p1_3v3=d["p1_3v3"], p2_3v3=d["p2_3v3"],
            p1_hr=d["p1_hr"], p2_hr=d["p2_hr"],
            p1_hr_2v2=d["p1_hr_2v2"], p2_hr_2v2=d["p2_hr_2v2"],
            p1_hr_3v3=d["p1_hr_3v3"], p2_hr_3v3=d["p2_hr_3v3"],
            p1_history=d["p1_history"],
            p2_history=d["p2_history"],
            p1_history_regular=d["p1_history_regular"],
            p2_history_regular=d["p2_history_regular"],
            p1_history_highrank=d["p1_history_highrank"],
            p2_history_highrank=d["p2_history_highrank"],
            p1_is_5v5=d["p1_is_5v5"],
            p2_is_5v5=d["p2_is_5v5"],
            starting_elo=d["starting_elo"],
            p1_recent=p1_focus_recent,
            p2_recent=p2_focus_recent,
            p1_rank_role=d["p1_rank_role"],
            p2_rank_role=d["p2_rank_role"],
            p1_rank_threshold=d["p1_rank_threshold"],
            p2_rank_threshold=d["p2_rank_threshold"],
            p1_next_threshold=d["p1_next_threshold"],
            p2_next_threshold=d["p2_next_threshold"],
            queue_focus=self.current_queue,
            p1_streaks_6v6=d.get("p1_streaks_6v6"),
            p2_streaks_6v6=d.get("p2_streaks_6v6"),
            p1_streaks_2v2=d.get("p1_streaks_2v2"),
            p2_streaks_2v2=d.get("p2_streaks_2v2"),
            p1_streaks_3v3=d.get("p1_streaks_3v3"),
            p2_streaks_3v3=d.get("p2_streaks_3v3"),
            p1_role_color=d.get("p1_role_color"),
            p2_role_color=d.get("p2_role_color"),
            tier_roles=d.get("tier_roles"),
            p1_hr_games_per_pos=d.get("p1_hr_games_per_pos"),
            p2_hr_games_per_pos=d.get("p2_hr_games_per_pos"),
            p1_pos_wl=d.get("p1_pos_wl"),
            p2_pos_wl=d.get("p2_pos_wl"),
            p1_hr_pos_wl=d.get("p1_hr_pos_wl"),
            p2_hr_pos_wl=d.get("p2_hr_pos_wl"),
            p1_streaks_hr=d.get("p1_streaks_hr"),
            p2_streaks_hr=d.get("p2_streaks_hr"),
            p1_streaks_hr_2v2=d.get("p1_streaks_hr_2v2"),
            p2_streaks_hr_2v2=d.get("p2_streaks_hr_2v2"),
            p1_streaks_hr_3v3=d.get("p1_streaks_hr_3v3"),
            p2_streaks_hr_3v3=d.get("p2_streaks_hr_3v3"),
        )

        embed = discord.Embed(color=discord.Color.from_rgb(32, 34, 40))
        embed.set_image(url="attachment://compare.png")
        footer_parts = [f"Viewing: {self.current_queue.upper()} queue comparison"]
        if d.get("_season_name"):
            footer_parts.append(f"Season: {d['_season_name']}")
        if d.get("_region"):
            footer_parts.append(f"[{d['_region']}]")
        embed.set_footer(text=" | ".join(footer_parts))

        self._update_button_styles()
        file = discord.File(image_buf, filename="compare.png")
        await interaction.response.edit_message(embed=embed, attachments=[file], view=self)

    @discord.ui.button(label="Regular", style=discord.ButtonStyle.primary, custom_id="compare_queue_regular", emoji="\U0001f3d0", row=0)
    async def regular_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.interaction_user.id:
            await interaction.response.send_message("Only the command user can interact.", ephemeral=True)
            return
        self.current_queue = "regular"
        await self._generate_and_send(interaction)

    @discord.ui.button(label="2v2", style=discord.ButtonStyle.secondary, custom_id="compare_queue_2v2", emoji="\U0001f465", row=0)
    async def twov2_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.interaction_user.id:
            await interaction.response.send_message("Only the command user can interact.", ephemeral=True)
            return
        self.current_queue = "2v2"
        await self._generate_and_send(interaction)

    @discord.ui.button(label="3v3", style=discord.ButtonStyle.secondary, custom_id="compare_queue_3v3", emoji="\U0001f46a", row=0)
    async def threev3_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.interaction_user.id:
            await interaction.response.send_message("Only the command user can interact.", ephemeral=True)
            return
        self.current_queue = "3v3"
        await self._generate_and_send(interaction)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
