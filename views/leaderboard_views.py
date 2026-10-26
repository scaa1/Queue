# views/leaderboard_views.py
"""
Views related to leaderboard display and navigation.
Now generates image-based leaderboard cards.
"""

import discord
from discord import app_commands

from config import POSITION_EMOJIS
from stats_card import generate_leaderboard_card


class LeaderboardView(discord.ui.View):
    def __init__(self, bot, guild_id):
        super().__init__(timeout=None)  # Make persistent
        self.bot = bot
        self.guild_id = guild_id
        self.current_position = "all"
        self.current_queue_type = "6v6"  # 6v6, 2v2, 3v3
        self.current_season_id = None  # None means all-time
        self.current_stat = "elo"  # elo, wins, losses, winrate, games
        self.current_region = "all"  # all, NA, EU, Asia, OCE
        self.page = 0
        self.per_page = 10

    async def _get_data(self, position, stat, actual_season_id):
        """Fetch leaderboard data respecting region filter."""
        if self.current_region != "all":
            return await self._get_regional_data(position, stat, actual_season_id)
        return await self._get_global_data(position, stat, actual_season_id)

    def _db_queue_type(self):
        """Map display queue types to database queue types."""
        return self.current_queue_type

    def _queue_label(self):
        """Get display label for the current queue type."""
        labels = {
            '6v6': 'Regular',
            'highrank_6v6': 'High Rank',
        }
        return labels.get(self.current_queue_type, self.current_queue_type.upper())

    async def _get_global_data(self, position, stat, actual_season_id):
        """Fetch global (non-regional) leaderboard data."""
        if stat in ("win_streak", "loss_streak"):
            streak_type = "win" if stat == "win_streak" else "loss"
            qt = self._db_queue_type()
            if qt == 'highrank_6v6':
                qt = 'highrank'
            rows = await self.bot.db.get_streak_leaderboard(
                self.guild_id, qt, streak_type,
                self.per_page, self.page * self.per_page
            )
            total_count = len(rows)  # approximate
            return rows, total_count
        elif stat == "elo":
            pos = None if position == "all" else position
            rows = await self.bot.db.get_leaderboard_data(
                self.guild_id, pos, self.per_page, self.page * self.per_page,
                actual_season_id
            )
            total_count = await self.bot.db.get_player_count(
                self.guild_id, actual_season_id
            )
            return rows, total_count
        else:
            rows = await self.bot.db.get_stats_leaderboard(
                self.guild_id, position, stat,
                self.per_page, self.page * self.per_page,
                actual_season_id
            )
            total_count = await self.bot.db.get_player_count(
                self.guild_id, actual_season_id
            )
            return rows, total_count

    async def _get_regional_data(self, position, stat, actual_season_id):
        """Fetch regional leaderboard data."""
        region = self.current_region
        if stat == "elo":
            pos = None if position == "all" else position
            rows = await self.bot.db.get_regional_leaderboard_data(
                self.guild_id, region, pos, self.per_page, self.page * self.per_page,
                actual_season_id
            )
            total_count = await self.bot.db.get_regional_player_count(
                self.guild_id, region, actual_season_id
            )
            return rows, total_count
        else:
            rows = await self.bot.db.get_regional_stats_leaderboard(
                self.guild_id, region, position, stat,
                self.per_page, self.page * self.per_page,
                actual_season_id
            )
            total_count = await self.bot.db.get_regional_player_count(
                self.guild_id, region, actual_season_id
            )
            return rows, total_count

    async def _resolve_user(self, user_id):
        """Resolve a user ID to a User object, trying cache first then API."""
        user = self.bot.get_user(user_id)
        if user:
            return user
        try:
            user = await self.bot.fetch_user(user_id)
            return user
        except Exception:
            return None

    async def _get_avatar_bytes(self, user):
        """Download a user's avatar as bytes for leaderboard."""
        if not user:
            return None
        try:
            asset = user.display_avatar.with_size(64).with_format('png')
            return await asset.read()
        except Exception:
            return None

    async def _build_card_rows(self, rows, stat):
        """Build card row data from raw database rows (with avatar bytes)."""
        card_rows = []

        if stat in ("win_streak", "loss_streak"):
            streak_label = "Win Streak" if stat == "win_streak" else "Loss Streak"
            for i, (user_id, streak_val, games, wins, losses) in enumerate(rows, 1 + self.page * self.per_page):
                user = await self._resolve_user(user_id)
                username = user.name if user else f"User {user_id}"
                avatar_bytes = await self._get_avatar_bytes(user)
                win_rate = (wins / games * 100) if games > 0 else 0
                value_text = f"{streak_val} {streak_label}"
                sub_text = f"{win_rate:.1f}% WR | {wins}W/{losses}L"
                card_rows.append((i, username, value_text, sub_text, "", avatar_bytes))
        elif stat == "elo":
            for i, (user_id, elo_val, games, wins) in enumerate(rows, 1 + self.page * self.per_page):
                user = await self._resolve_user(user_id)
                username = user.name if user else f"User {user_id}"
                avatar_bytes = await self._get_avatar_bytes(user)
                losses = games - wins
                win_rate = (wins / games * 100) if games > 0 else 0
                value_text = f"{elo_val:.0f} ELO"
                sub_text = f"{win_rate:.1f}% WR | {wins}W/{losses}L | {games} games"

                db_qt = self._db_queue_type()
                streaks = await self.bot.db.get_player_streaks(self.guild_id, user_id, db_qt if db_qt != 'highrank_6v6' else 'highrank')
                ws, ls = streaks[0], streaks[1]
                streak_text = ""
                if ws > 0:
                    streak_text = f"{ws}W streak"
                elif ls > 0:
                    streak_text = f"{ls}L streak"
                card_rows.append((i, username, value_text, sub_text, streak_text, avatar_bytes))
        else:
            for i, (user_id, value, games, wins, losses) in enumerate(rows, 1 + self.page * self.per_page):
                user = await self._resolve_user(user_id)
                username = user.name if user else f"User {user_id}"
                avatar_bytes = await self._get_avatar_bytes(user)
                win_rate = (wins / games * 100) if games > 0 else 0

                if stat == "winrate":
                    value_text = f"{value:.1f}%"
                elif stat == "wins":
                    value_text = f"{value} wins"
                elif stat == "losses":
                    value_text = f"{value} losses"
                elif stat == "games":
                    value_text = f"{value} games"
                else:
                    value_text = str(value)
                sub_text = f"{win_rate:.1f}% WR | {wins}W/{losses}L"
                card_rows.append((i, username, value_text, sub_text, "", avatar_bytes))

        return card_rows

    async def _send_card_update(self, interaction, card_rows, title, subtitle, queue_label, total_count, raw_row_count=None):
        """Generate and send leaderboard card image."""
        total_pages = max(1, (total_count - 1) // self.per_page + 1)
        actual_rows = raw_row_count if raw_row_count is not None else len(card_rows)

        self.prev_button.disabled = self.page == 0
        self.next_button.disabled = actual_rows < self.per_page

        self._update_select_defaults()

        image_buf = await generate_leaderboard_card(
            title=title,
            rows=card_rows if card_rows else None,
            page=self.page,
            total_pages=total_pages,
            subtitle=subtitle,
            queue_label=queue_label,
        )

        embed = discord.Embed(color=discord.Color.from_rgb(32, 34, 40))
        embed.set_image(url="attachment://leaderboard.png")

        file = discord.File(image_buf, filename="leaderboard.png")
        await interaction.response.edit_message(embed=embed, attachments=[file], view=self)

    async def update_embed(self, interaction: discord.Interaction):
        # Handle high rank 6v6 per-position leaderboard
        if self.current_queue_type == 'highrank_6v6':
            return await self._update_embed_highrank_6v6(interaction)

        # Handle 2v2/3v3/highrank leaderboard separately
        if self.current_queue_type in ('2v2', '3v3', 'highrank_2v2', 'highrank_3v3'):
            return await self._update_embed_simple(interaction)

        # Get season info
        season_text = "All-Time"
        actual_season_id = None

        if self.current_season_id == "current":
            current_season = await self.bot.db.get_current_season(self.guild_id, '6v6')
            if current_season:
                actual_season_id = current_season[0]
                season_text = f"Season: {current_season[1]}"
            else:
                season_text = "No Active Season"
                actual_season_id = None
                self.current_season_id = None
        elif self.current_season_id and self.current_season_id != "current":
            async with self.bot.db.db.execute(
                'SELECT name FROM seasons WHERE id = ?',
                (self.current_season_id,)
            ) as cursor:
                result = await cursor.fetchone()
                if result:
                    season_text = f"Past Season: {result[0]}"
                    actual_season_id = self.current_season_id
                else:
                    season_text = "All-Time"
                    actual_season_id = None
                    self.current_season_id = None

        # Region label
        region_text = ""
        if self.current_region != "all":
            region_text = f" | {self.current_region}"

        # Stat names
        stat_names = {
            "elo": "ELO Rating", "wins": "Total Wins", "losses": "Total Losses",
            "winrate": "Win Rate", "games": "Games Played",
            "win_streak": "Win Streak", "loss_streak": "Loss Streak"
        }

        # Fetch data
        rows, total_count = await self._get_data(
            self.current_position, self.current_stat, actual_season_id
        )

        # Build subtitle
        q_label = self._queue_label()
        if self.current_stat == "elo":
            if self.current_position == "all":
                subtitle = f"{q_label} Top Players - Average {stat_names[self.current_stat]} ({season_text}{region_text})"
            else:
                emoji = POSITION_EMOJIS.get(self.current_position, "")
                subtitle = f"{q_label} {emoji} {self.current_position} Rankings ({season_text}{region_text})"
        else:
            position_text = f"{POSITION_EMOJIS.get(self.current_position, '')} {self.current_position}" if self.current_position != "all" else "All Positions"
            subtitle = f"{q_label} {position_text} - {stat_names[self.current_stat]} ({season_text}{region_text})"

        card_rows = await self._build_card_rows(rows, self.current_stat)
        await self._send_card_update(
            interaction, card_rows,
            "Volleyball Leaderboard", subtitle, q_label, total_count,
            raw_row_count=len(rows)
        )

    async def _update_embed_highrank_6v6(self, interaction):
        """Update embed for high rank 6v6 leaderboard (per-position)."""
        position = self.current_position
        hr_label = self._queue_label()

        if self.current_stat in ("win_streak", "loss_streak"):
            streak_type = "win" if self.current_stat == "win_streak" else "loss"
            rows = await self.bot.db.get_streak_leaderboard(
                self.guild_id, 'highrank', streak_type,
                self.per_page, self.page * self.per_page
            )
            card_rows = await self._build_card_rows(rows, self.current_stat)
            streak_label = "Win Streak" if self.current_stat == "win_streak" else "Loss Streak"
            await self._send_card_update(
                interaction, card_rows,
                "Volleyball Leaderboard",
                f"{hr_label} - {streak_label}",
                hr_label, len(rows),
                raw_row_count=len(rows)
            )
            return

        rows = await self.bot.db.get_leaderboard_data_highrank(
            self.guild_id, None if position == "all" else position,
            self.per_page, self.page * self.per_page
        )
        total_count = await self.bot.db.get_player_count_highrank(self.guild_id)

        if position == "all":
            subtitle = f"{hr_label} - Average ELO Rating"
        else:
            emoji = POSITION_EMOJIS.get(position, "")
            subtitle = f"{emoji} {hr_label} - {position} Rankings"

        card_rows = await self._build_card_rows(rows, "elo")
        await self._send_card_update(
            interaction, card_rows,
            "Volleyball Leaderboard", subtitle, hr_label, total_count,
            raw_row_count=len(rows)
        )

    async def _update_embed_simple(self, interaction):
        """Update embed for 2v2/3v3/highrank leaderboards (simple MMR, no positions)."""
        qt = self.current_queue_type
        is_highrank = qt.startswith('highrank_')
        base_qt = qt.replace('highrank_', '') if is_highrank else qt
        qt_label = f"High Rank {base_qt.upper()}" if is_highrank else base_qt.upper()

        if self.current_stat in ("win_streak", "loss_streak"):
            streak_type = "win" if self.current_stat == "win_streak" else "loss"
            rows = await self.bot.db.get_streak_leaderboard(
                self.guild_id, qt, streak_type,
                self.per_page, self.page * self.per_page
            )
            card_rows = await self._build_card_rows(rows, self.current_stat)
            streak_label = "Win Streak" if self.current_stat == "win_streak" else "Loss Streak"
            await self._send_card_update(
                interaction, card_rows,
                "Volleyball Leaderboard",
                f"{qt_label} Leaderboard - {streak_label}",
                qt_label, len(rows),
                raw_row_count=len(rows)
            )
            return

        # Get season info for this queue type
        current_season = await self.bot.db.get_current_season(self.guild_id, base_qt)
        season_text = f"{current_season[1]}" if current_season else "No Active Season"

        if is_highrank:
            rows = await self.bot.db.get_leaderboard_data_highrank_simple(
                self.guild_id, base_qt, self.per_page, self.page * self.per_page
            )
            total_count = await self.bot.db.get_player_count_highrank_simple(self.guild_id, base_qt)
        else:
            rows = await self.bot.db.get_leaderboard_data_simple(
                self.guild_id, qt, self.per_page, self.page * self.per_page
            )
            total_count = await self.bot.db.get_player_count_simple(self.guild_id, qt)

        subtitle = f"{qt_label} Leaderboard - MMR Rankings ({season_text})"

        # Build card rows for simple leaderboard
        card_rows = []
        for i, (user_id, elo, g, w) in enumerate(rows, 1 + self.page * self.per_page):
            user = await self._resolve_user(user_id)
            username = user.name if user else f"User {user_id}"
            avatar_bytes = await self._get_avatar_bytes(user)
            losses = g - w
            win_rate = (w / g * 100) if g > 0 else 0
            value_text = f"{elo} MMR"
            sub_text = f"{win_rate:.1f}% WR | {w}W/{losses}L | {g} games"

            streaks = await self.bot.db.get_player_streaks(self.guild_id, user_id, qt)
            ws, ls = streaks[0], streaks[1]
            streak_text = ""
            if ws > 0:
                streak_text = f"{ws}W streak"
            elif ls > 0:
                streak_text = f"{ls}L streak"
            card_rows.append((i, username, value_text, sub_text, streak_text, avatar_bytes))

        await self._send_card_update(
            interaction, card_rows,
            "Volleyball Leaderboard", subtitle, qt_label, total_count,
            raw_row_count=len(rows)
        )

    def _update_select_defaults(self):
        """Update select menu default values."""
        for child in self.children:
            if isinstance(child, discord.ui.Select):
                if child.custom_id == "leaderboard_position_select":
                    for option in child.options:
                        if self.current_queue_type == 'highrank_6v6':
                            hr_reverse = {
                                "all": "highrank_6v6_all",
                                "Defense Specialist": "highrank_6v6_defense",
                                "Front Spiker": "highrank_6v6_spiker",
                                "Setter": "highrank_6v6_setter",
                                "Libero": "highrank_6v6_libero",
                            }
                            option.default = option.value == hr_reverse.get(self.current_position, "")
                        elif self.current_queue_type in ('2v2', '3v3', 'highrank_2v2', 'highrank_3v3'):
                            option.default = option.value == self.current_queue_type
                        else:
                            option.default = (
                                (option.value == "all" and self.current_position == "all") or
                                (option.value == "defense" and self.current_position == "Defense Specialist") or
                                (option.value == "spiker" and self.current_position == "Front Spiker") or
                                (option.value == "setter" and self.current_position == "Setter") or
                                (option.value == "libero" and self.current_position == "Libero")
                            )
                elif child.custom_id == "leaderboard_stat_select":
                    for option in child.options:
                        option.default = option.value == self.current_stat
                elif child.custom_id == "leaderboard_region_select":
                    for option in child.options:
                        option.default = option.value == self.current_region

    @discord.ui.select(
        placeholder="Select queue type / position",
        custom_id="leaderboard_position_select",
        options=[
            discord.SelectOption(label="Regular - All Positions", value="all", emoji="\U0001f3c6"),
            discord.SelectOption(label="Regular - Defense Specialist", value="defense", emoji="\U0001f6e1\ufe0f"),
            discord.SelectOption(label="Regular - Front Spiker", value="spiker", emoji="\u26a1"),
            discord.SelectOption(label="Regular - Setter", value="setter", emoji="\U0001f3d0"),
            discord.SelectOption(label="Regular - Libero", value="libero", emoji="\U0001f3af"),
            discord.SelectOption(label="2v2 Leaderboard", value="2v2", emoji="\U0001f465"),
            discord.SelectOption(label="3v3 Leaderboard", value="3v3", emoji="\U0001f465"),
            discord.SelectOption(label="High Rank - All", value="highrank_6v6_all", emoji="\U0001f525"),
            discord.SelectOption(label="HR - Defense Specialist", value="highrank_6v6_defense", emoji="\U0001f6e1\ufe0f"),
            discord.SelectOption(label="HR - Front Spiker", value="highrank_6v6_spiker", emoji="\u26a1"),
            discord.SelectOption(label="HR - Setter", value="highrank_6v6_setter", emoji="\U0001f3d0"),
            discord.SelectOption(label="HR - Libero", value="highrank_6v6_libero", emoji="\U0001f3af"),
            discord.SelectOption(label="2v2 High Rank", value="highrank_2v2", emoji="\U0001f525"),
            discord.SelectOption(label="3v3 High Rank", value="highrank_3v3", emoji="\U0001f525"),
        ],
        row=0
    )
    async def position_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        value = select.values[0]
        if value.startswith('highrank_6v6_'):
            self.current_queue_type = 'highrank_6v6'
            hr_position_map = {
                "highrank_6v6_all": "all",
                "highrank_6v6_defense": "Defense Specialist",
                "highrank_6v6_spiker": "Front Spiker",
                "highrank_6v6_setter": "Setter",
                "highrank_6v6_libero": "Libero",
            }
            self.current_position = hr_position_map[value]
        elif value in ('2v2', '3v3', 'highrank_2v2', 'highrank_3v3'):
            self.current_queue_type = value
            self.current_position = "all"
        else:
            self.current_queue_type = "6v6"
            position_map = {
                "all": "all",
                "defense": "Defense Specialist",
                "spiker": "Front Spiker",
                "setter": "Setter",
                "libero": "Libero"
            }
            self.current_position = position_map[value]
        self.page = 0
        await self.update_embed(interaction)

    @discord.ui.select(
        placeholder="Select season",
        custom_id="leaderboard_season_select",
        options=[
            discord.SelectOption(label="Loading...", value="loading")
        ],
        row=1
    )
    async def season_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        value = select.values[0]
        if value == "all_time":
            self.current_season_id = None
        elif value == "current":
            self.current_season_id = "current"
        else:
            self.current_season_id = int(value)
        self.page = 0
        await self.update_embed(interaction)

    @discord.ui.select(
        placeholder="Select stat to display",
        custom_id="leaderboard_stat_select",
        options=[
            discord.SelectOption(label="ELO Rating", value="elo", emoji="📊", description="Sort by ELO rating"),
            discord.SelectOption(label="Total Wins", value="wins", emoji="🏆", description="Sort by number of wins"),
            discord.SelectOption(label="Total Losses", value="losses", emoji="💔", description="Sort by number of losses"),
            discord.SelectOption(label="Win Rate", value="winrate", emoji="📈", description="Sort by win percentage"),
            discord.SelectOption(label="Games Played", value="games", emoji="🎮", description="Sort by total games"),
            discord.SelectOption(label="Win Streak", value="win_streak", emoji="🔥", description="Current win streak"),
            discord.SelectOption(label="Loss Streak", value="loss_streak", emoji="💀", description="Current loss streak"),
        ],
        row=2
    )
    async def stat_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.current_stat = select.values[0]
        self.page = 0
        await self.update_embed(interaction)

    @discord.ui.select(
        placeholder="Select region",
        custom_id="leaderboard_region_select",
        options=[
            discord.SelectOption(label="All Regions", value="all"),
            discord.SelectOption(label="NA (North America)", value="NA"),
            discord.SelectOption(label="EU (Europe)", value="EU"),
            discord.SelectOption(label="Asia", value="Asia"),
            discord.SelectOption(label="OCE (Oceania)", value="OCE"),
        ],
        row=3
    )
    async def region_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.current_region = select.values[0]
        self.page = 0
        await self.update_embed(interaction)

    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.secondary, row=4)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_embed(interaction)

    @discord.ui.button(label="◀️ Previous", style=discord.ButtonStyle.secondary, row=4)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
            await self.update_embed(interaction)

    @discord.ui.button(label="▶️ Next", style=discord.ButtonStyle.secondary, row=4)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        await self.update_embed(interaction)

    async def setup_season_options(self):
        """Setup season select options (includes all queue types)"""
        seasons = await self.bot.db.get_all_seasons(self.guild_id)
        current_season_6v6 = await self.bot.db.get_current_season(self.guild_id, '6v6')

        options = [
            discord.SelectOption(
                label="All-Time",
                value="all_time",
                emoji="📊",
                description="View all-time statistics across all seasons",
                default=(self.current_season_id is None)
            )
        ]

        if current_season_6v6:
            options.append(
                discord.SelectOption(
                    label=f"Current Season: {current_season_6v6[1]}",
                    value="current",
                    emoji="🏅",
                    description="View current season statistics",
                    default=(self.current_season_id == "current" or self.current_season_id == current_season_6v6[0])
                )
            )

        for season_id, name, start_date, end_date, is_active in seasons:
            if not is_active:
                options.append(
                    discord.SelectOption(
                        label=f"Past: {name}",
                        value=str(season_id),
                        emoji="📅",
                        default=(self.current_season_id == season_id)
                    )
                )

        for child in self.children:
            if isinstance(child, discord.ui.Select) and child.custom_id == "leaderboard_season_select":
                child.options = options[:25]
                break
