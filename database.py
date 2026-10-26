# database.py
import aiosqlite
import json
from datetime import datetime, timedelta
from config import DEFAULT_CONFIG, DATABASE_NAME

class Database:
    def __init__(self):
        self.db = None
        
    async def connect(self):
        self.db = await aiosqlite.connect(DATABASE_NAME)
        await self.initialize_database()
        
    async def close(self):
        if self.db:
            await self.db.close()
            
    async def initialize_database(self):
        # ── 6v6 per-position players ──
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS players (
                guild_id INTEGER,
                user_id INTEGER,
                defense_specialist_elo INTEGER DEFAULT 1000,
                front_spiker_elo INTEGER DEFAULT 1000,
                setter_elo INTEGER DEFAULT 1000,
                libero_elo INTEGER DEFAULT 1000,
                games_played INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        ''')

        # ── 2v2 singular MMR ──
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS players_2v2 (
                guild_id INTEGER,
                user_id INTEGER,
                elo INTEGER DEFAULT 1000,
                games_played INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        ''')

        # ── 3v3 singular MMR ──
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS players_3v3 (
                guild_id INTEGER,
                user_id INTEGER,
                elo INTEGER DEFAULT 1000,
                games_played INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        ''')

        # ── High rank per-position players (separate from normal 6v6) ──
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS players_highrank (
                guild_id INTEGER,
                user_id INTEGER,
                defense_specialist_elo INTEGER DEFAULT 1000,
                front_spiker_elo INTEGER DEFAULT 1000,
                setter_elo INTEGER DEFAULT 1000,
                libero_elo INTEGER DEFAULT 1000,
                games_played INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        ''')

        # ── High rank players for 2v2 (singular MMR) ──
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS players_highrank_2v2 (
                guild_id INTEGER,
                user_id INTEGER,
                elo INTEGER DEFAULT 1000,
                games_played INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        ''')

        # ── High rank players for 3v3 (singular MMR) ──
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS players_highrank_3v3 (
                guild_id INTEGER,
                user_id INTEGER,
                elo INTEGER DEFAULT 1000,
                games_played INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        ''')

        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS elo_role_mappings (
                guild_id INTEGER,
                position TEXT,
                elo_threshold INTEGER,
                role_id INTEGER,
                PRIMARY KEY (guild_id, position, elo_threshold)
            )
        ''')

        
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                team1_players TEXT,
                team2_players TEXT,
                team1_score INTEGER,
                team2_score INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                season_id INTEGER,
                text_channel_id INTEGER,
                voice_channel_id INTEGER,
                is_active INTEGER DEFAULT 1,
                match_type TEXT DEFAULT '6v6'
            )
        ''')
        
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS guild_config (
                guild_id INTEGER PRIMARY KEY,
                config TEXT
            )
        ''')
        
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS queue (
                guild_id INTEGER,
                user_id INTEGER,
                position TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                duo_partner INTEGER,
                queue_type TEXT DEFAULT '6v6',
                PRIMARY KEY (guild_id, user_id)
            )
        ''')
        
        # Add position-specific game tracking
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS position_stats (
                guild_id INTEGER,
                user_id INTEGER,
                position TEXT,
                games_played INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id, position)
            )
        ''')
        
        # New season tables
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS seasons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                name TEXT,
                start_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                end_date DATETIME,
                is_active INTEGER DEFAULT 1,
                queue_type TEXT DEFAULT '6v6'
            )
        ''')
        
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS season_stats (
                guild_id INTEGER,
                user_id INTEGER,
                season_id INTEGER,
                defense_specialist_elo INTEGER DEFAULT 1000,
                front_spiker_elo INTEGER DEFAULT 1000,
                setter_elo INTEGER DEFAULT 1000,
                libero_elo INTEGER DEFAULT 1000,
                games_played INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id, season_id)
            )
        ''')
        
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS season_position_stats (
                guild_id INTEGER,
                user_id INTEGER,
                season_id INTEGER,
                position TEXT,
                games_played INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id, season_id, position)
            )
        ''')
        
        # High rank position stats (separate tracking)
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS position_stats_highrank (
                guild_id INTEGER,
                user_id INTEGER,
                position TEXT,
                games_played INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id, position)
            )
        ''')

        # Season stats for 2v2
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS season_stats_2v2 (
                guild_id INTEGER,
                user_id INTEGER,
                season_id INTEGER,
                elo INTEGER DEFAULT 1000,
                games_played INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id, season_id)
            )
        ''')

        # Season stats for 3v3
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS season_stats_3v3 (
                guild_id INTEGER,
                user_id INTEGER,
                season_id INTEGER,
                elo INTEGER DEFAULT 1000,
                games_played INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id, season_id)
            )
        ''')

        # Season stats for high rank
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS season_stats_highrank (
                guild_id INTEGER,
                user_id INTEGER,
                season_id INTEGER,
                defense_specialist_elo INTEGER DEFAULT 1000,
                front_spiker_elo INTEGER DEFAULT 1000,
                setter_elo INTEGER DEFAULT 1000,
                libero_elo INTEGER DEFAULT 1000,
                games_played INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id, season_id)
            )
        ''')

        # Season stats for high rank 2v2
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS season_stats_highrank_2v2 (
                guild_id INTEGER,
                user_id INTEGER,
                season_id INTEGER,
                elo INTEGER DEFAULT 1000,
                games_played INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id, season_id)
            )
        ''')

        # Season stats for high rank 3v3
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS season_stats_highrank_3v3 (
                guild_id INTEGER,
                user_id INTEGER,
                season_id INTEGER,
                elo INTEGER DEFAULT 1000,
                games_played INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id, season_id)
            )
        ''')

        # Player regions table
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS player_regions (
                guild_id INTEGER,
                user_id INTEGER,
                region TEXT,
                PRIMARY KEY (guild_id, user_id)
            )
        ''')

        # Blacklist table
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS blacklist (
                guild_id INTEGER,
                user_id INTEGER,
                blacklisted_by INTEGER,
                reason TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME,
                PRIMARY KEY (guild_id, user_id)
            )
        ''')
        
        # Add columns to matches table if they don't exist
        try:
            await self.db.execute('ALTER TABLE matches ADD COLUMN season_id INTEGER')
        except:
            pass
            
        try:
            await self.db.execute('ALTER TABLE matches ADD COLUMN text_channel_id INTEGER')
        except:
            pass
            
        try:
            await self.db.execute('ALTER TABLE matches ADD COLUMN voice_channel_id INTEGER')
        except:
            pass
            
        try:
            await self.db.execute('ALTER TABLE matches ADD COLUMN is_active INTEGER DEFAULT 1')
        except:
            pass

        try:
            await self.db.execute("ALTER TABLE matches ADD COLUMN match_type TEXT DEFAULT '6v6'")
        except:
            pass

        try:
            await self.db.execute("ALTER TABLE queue ADD COLUMN queue_type TEXT DEFAULT '6v6'")
        except:
            pass

        try:
            await self.db.execute("ALTER TABLE seasons ADD COLUMN queue_type TEXT DEFAULT '6v6'")
        except:
            pass

        try:
            await self.db.execute("ALTER TABLE blacklist ADD COLUMN expires_at DATETIME")
        except:
            pass

        # Add region column to matches table
        try:
            await self.db.execute("ALTER TABLE matches ADD COLUMN region TEXT")
        except:
            pass

        # Add result_message_id column to matches table for tracking result embeds
        try:
            await self.db.execute("ALTER TABLE matches ADD COLUMN result_message_id INTEGER")
        except:
            pass

        # Add streak columns to all player tables
        for table in ['players', 'players_highrank']:
            for col in ['win_streak', 'loss_streak', 'best_win_streak', 'best_loss_streak']:
                try:
                    await self.db.execute(f"ALTER TABLE {table} ADD COLUMN {col} INTEGER DEFAULT 0")
                except:
                    pass

        for table in ['players_2v2', 'players_3v3', 'players_highrank_2v2', 'players_highrank_3v3']:
            for col in ['win_streak', 'loss_streak', 'best_win_streak', 'best_loss_streak']:
                try:
                    await self.db.execute(f"ALTER TABLE {table} ADD COLUMN {col} INTEGER DEFAULT 0")
                except:
                    pass

        # Add queue_type column to elo_role_mappings for 2v2/3v3 support
        try:
            await self.db.execute("ALTER TABLE elo_role_mappings ADD COLUMN queue_type TEXT DEFAULT '6v6'")
        except:
            pass

        # ── Match transcripts ──
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS match_transcripts (
                match_id INTEGER,
                guild_id INTEGER,
                transcript TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (match_id, guild_id)
            )
        ''')

        # ── ELO history for rating graphs ──
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS elo_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                user_id INTEGER,
                match_id INTEGER,
                queue_type TEXT,
                position TEXT,
                elo_before INTEGER,
                elo_after INTEGER,
                elo_change INTEGER,
                is_winner INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # ── Per-region ELO tables ──
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS players_regional (
                guild_id INTEGER,
                user_id INTEGER,
                region TEXT,
                defense_specialist_elo INTEGER DEFAULT 1000,
                front_spiker_elo INTEGER DEFAULT 1000,
                setter_elo INTEGER DEFAULT 1000,
                libero_elo INTEGER DEFAULT 1000,
                games_played INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                win_streak INTEGER DEFAULT 0,
                loss_streak INTEGER DEFAULT 0,
                best_win_streak INTEGER DEFAULT 0,
                best_loss_streak INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id, region)
            )
        ''')

        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS players_regional_2v2 (
                guild_id INTEGER,
                user_id INTEGER,
                region TEXT,
                elo INTEGER DEFAULT 1000,
                games_played INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                win_streak INTEGER DEFAULT 0,
                loss_streak INTEGER DEFAULT 0,
                best_win_streak INTEGER DEFAULT 0,
                best_loss_streak INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id, region)
            )
        ''')

        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS players_regional_3v3 (
                guild_id INTEGER,
                user_id INTEGER,
                region TEXT,
                elo INTEGER DEFAULT 1000,
                games_played INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                win_streak INTEGER DEFAULT 0,
                loss_streak INTEGER DEFAULT 0,
                best_win_streak INTEGER DEFAULT 0,
                best_loss_streak INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id, region)
            )
        ''')

        # Queue bans table (for players who don't ready up)
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS queue_bans (
                guild_id INTEGER,
                user_id INTEGER,
                banned_until DATETIME,
                reason TEXT,
                PRIMARY KEY (guild_id, user_id)
            )
        ''')

        await self.db.commit()

    async def get_config(self, guild_id):
        async with self.db.execute('SELECT config FROM guild_config WHERE guild_id = ?', (guild_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                config = json.loads(row[0])
                # Migrate old moderator_roles to new staff roles
                if "moderator_roles" in config and "staff_senior_roles" not in config:
                    config["staff_senior_roles"] = config.pop("moderator_roles")
                    config["staff_normal_roles"] = []
                    await self.update_config(guild_id, config)
                # Ensure all defaults exist
                merged = DEFAULT_CONFIG.copy()
                merged.update(config)
                return merged
            return DEFAULT_CONFIG.copy()
            
    async def update_config(self, guild_id, config):
        await self.db.execute(
            'INSERT OR REPLACE INTO guild_config (guild_id, config) VALUES (?, ?)',
            (guild_id, json.dumps(config))
        )
        await self.db.commit()
        
    async def is_user_in_queue(self, guild_id, user_id):
        """Check if a user is currently in any queue."""
        async with self.db.execute(
            'SELECT 1 FROM queue WHERE guild_id = ? AND user_id = ?',
            (guild_id, user_id)
        ) as cursor:
            return await cursor.fetchone() is not None

    async def is_user_in_active_match(self, guild_id, user_id):
        """Check if a user is currently in an active match."""
        async with self.db.execute(
            'SELECT team1_players, team2_players FROM matches WHERE guild_id = ? AND is_active = 1',
            (guild_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            for team1_json, team2_json in rows:
                team1 = json.loads(team1_json)
                team2 = json.loads(team2_json)
                # Players stored as list of [user_id, position] pairs
                for team in (team1, team2):
                    if isinstance(team, list):
                        for entry in team:
                            if isinstance(entry, (list, tuple)) and len(entry) >= 1:
                                if int(entry[0]) == user_id:
                                    return True
                            elif isinstance(entry, int) and entry == user_id:
                                return True
            return False

    async def add_to_queue(self, guild_id, user_id, position, queue_type='6v6'):
        try:
            await self.db.execute(
                'INSERT INTO queue (guild_id, user_id, position, queue_type) VALUES (?, ?, ?, ?)',
                (guild_id, user_id, position, queue_type)
            )
            await self.db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False
            
    async def add_duo_to_queue(self, guild_id, user1_id, user2_id, pos1, pos2, queue_type='6v6'):
        try:
            await self.db.execute('BEGIN')
            await self.db.execute(
                'INSERT INTO queue (guild_id, user_id, position, duo_partner, queue_type) VALUES (?, ?, ?, ?, ?)',
                (guild_id, user1_id, pos1, user2_id, queue_type)
            )
            await self.db.execute(
                'INSERT INTO queue (guild_id, user_id, position, duo_partner, queue_type) VALUES (?, ?, ?, ?, ?)',
                (guild_id, user2_id, pos2, user1_id, queue_type)
            )
            await self.db.commit()
            return True
        except aiosqlite.IntegrityError:
            await self.db.rollback()
            return False
            
    async def remove_from_queue(self, guild_id, user_id):
        # Check if user has a duo partner
        async with self.db.execute(
            'SELECT duo_partner FROM queue WHERE guild_id = ? AND user_id = ?',
            (guild_id, user_id)
        ) as cursor:
            row = await cursor.fetchone()
            if row and row[0]:
                # Remove both duo partners
                await self.db.execute(
                    'DELETE FROM queue WHERE guild_id = ? AND (user_id = ? OR user_id = ?)',
                    (guild_id, user_id, row[0])
                )
            else:
                # Remove solo player
                await self.db.execute(
                    'DELETE FROM queue WHERE guild_id = ? AND user_id = ?',
                    (guild_id, user_id)
                )
        await self.db.commit()
        return True

    async def add_queue_ban(self, guild_id, user_id, duration_seconds, reason="Did not ready up"):
        """Ban a player from queuing for a duration."""
        banned_until = datetime.utcnow() + timedelta(seconds=duration_seconds)
        await self.db.execute(
            'INSERT OR REPLACE INTO queue_bans (guild_id, user_id, banned_until, reason) VALUES (?, ?, ?, ?)',
            (guild_id, user_id, banned_until.isoformat(), reason)
        )
        await self.db.commit()

    async def get_queue_ban(self, guild_id, user_id):
        """Check if a player is queue banned. Returns (banned_until, reason) or None."""
        async with self.db.execute(
            'SELECT banned_until, reason FROM queue_bans WHERE guild_id = ? AND user_id = ?',
            (guild_id, user_id)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                banned_until = datetime.fromisoformat(row[0])
                if banned_until > datetime.utcnow():
                    return (banned_until, row[1])
                else:
                    # Ban expired, clean it up
                    await self.db.execute(
                        'DELETE FROM queue_bans WHERE guild_id = ? AND user_id = ?',
                        (guild_id, user_id)
                    )
                    await self.db.commit()
            return None

    async def remove_queue_ban(self, guild_id, user_id):
        """Remove a queue ban."""
        await self.db.execute(
            'DELETE FROM queue_bans WHERE guild_id = ? AND user_id = ?',
            (guild_id, user_id)
        )
        await self.db.commit()

    async def get_queue(self, guild_id, queue_type='6v6'):
        async with self.db.execute(
            'SELECT user_id, position, duo_partner FROM queue WHERE guild_id = ? AND queue_type = ? ORDER BY timestamp',
            (guild_id, queue_type)
        ) as cursor:
            return await cursor.fetchall()
            
    async def get_player_elo(self, guild_id, user_id, position):
        """Get player's ELO for a position, returning current starting ELO if no record exists"""
        position_column = position.lower().replace(" ", "_") + "_elo"

        # Get config for current starting ELO
        config = await self.get_config(guild_id)
        current_starting_elo = config["starting_elo"]

        # Check if player exists
        async with self.db.execute(
            f'SELECT {position_column} FROM players WHERE guild_id = ? AND user_id = ?',
            (guild_id, user_id)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return row[0]  # Return stored ELO (may have been set by admin)
            else:
                # New player, return current starting ELO
                return current_starting_elo
                
    async def get_player_elo_for_leaderboard(self, guild_id, user_id, position, season_id=None):
        """Get player's ELO for leaderboard display (returns stored value even if unplayed)"""
        position_column = position.lower().replace(" ", "_") + "_elo"
        
        if season_id is None:
            # Current season leaderboard
            async with self.db.execute(
                f'SELECT {position_column} FROM players WHERE guild_id = ? AND user_id = ?',
                (guild_id, user_id)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0
        else:
            # Season-specific leaderboard
            async with self.db.execute(
                f'SELECT {position_column} FROM season_stats WHERE guild_id = ? AND user_id = ? AND season_id = ?',
                (guild_id, user_id, season_id)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0
                
    async def update_player_elo(self, guild_id, user_id, position, elo_change, is_winner, starting_elo):
        position_column = position.lower().replace(" ", "_") + "_elo"
        
        # Get current season
        season_id = await self.get_current_season_id(guild_id)
        
        # Update current season stats
        await self.db.execute('''
            INSERT INTO position_stats (guild_id, user_id, position, games_played, wins, losses)
            VALUES (?, ?, ?, 1, ?, ?)
            ON CONFLICT(guild_id, user_id, position)
            DO UPDATE SET
                games_played = games_played + 1,
                wins = wins + ?,
                losses = losses + ?
        ''', (guild_id, user_id, position, 1 if is_winner else 0, 0 if is_winner else 1,
              1 if is_winner else 0, 0 if is_winner else 1))
        
        # Update season position stats if season exists
        if season_id:
            await self.db.execute('''
                INSERT INTO season_position_stats (guild_id, user_id, season_id, position, games_played, wins, losses)
                VALUES (?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(guild_id, user_id, season_id, position)
                DO UPDATE SET
                    games_played = games_played + 1,
                    wins = wins + ?,
                    losses = losses + ?
            ''', (guild_id, user_id, season_id, position, 1 if is_winner else 0, 0 if is_winner else 1,
                  1 if is_winner else 0, 0 if is_winner else 1))
        
        # Update current season player stats
        # First check if player exists
        async with self.db.execute(
            'SELECT * FROM players WHERE guild_id = ? AND user_id = ?',
            (guild_id, user_id)
        ) as cursor:
            player_exists = await cursor.fetchone() is not None
        
        if not player_exists:
            # Create new player with starting ELO for ALL positions
            await self.db.execute(f'''
                INSERT INTO players (guild_id, user_id, 
                    defense_specialist_elo, front_spiker_elo, setter_elo, libero_elo,
                    games_played, wins, losses)
                VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0)
            ''', (guild_id, user_id, starting_elo, starting_elo, starting_elo, starting_elo))
        
        # Now update for the specific game result (including streaks)
        if is_winner:
            await self.db.execute(f'''
                UPDATE players SET
                    {position_column} = {position_column} + ?,
                    games_played = games_played + 1,
                    wins = wins + 1,
                    win_streak = win_streak + 1,
                    loss_streak = 0,
                    best_win_streak = MAX(best_win_streak, win_streak + 1)
                WHERE guild_id = ? AND user_id = ?
            ''', (elo_change, guild_id, user_id))
        else:
            await self.db.execute(f'''
                UPDATE players SET
                    {position_column} = {position_column} + ?,
                    games_played = games_played + 1,
                    losses = losses + 1,
                    loss_streak = loss_streak + 1,
                    win_streak = 0,
                    best_loss_streak = MAX(best_loss_streak, loss_streak + 1)
                WHERE guild_id = ? AND user_id = ?
            ''', (elo_change, guild_id, user_id))

        # Update season stats if season exists
        if season_id:
            # Check if player has season stats record
            async with self.db.execute(
                'SELECT * FROM season_stats WHERE guild_id = ? AND user_id = ? AND season_id = ?',
                (guild_id, user_id, season_id)
            ) as cursor:
                season_record_exists = await cursor.fetchone() is not None
            
            # Get current season ELO or use starting ELO
            async with self.db.execute(
                f'SELECT {position_column} FROM season_stats WHERE guild_id = ? AND user_id = ? AND season_id = ?',
                (guild_id, user_id, season_id)
            ) as cursor:
                row = await cursor.fetchone()
                current_season_elo = row[0] if row else starting_elo
            
            if not season_record_exists:
                # First time playing in this season - create record with all positions at starting ELO
                await self.db.execute(f'''
                    INSERT INTO season_stats (guild_id, user_id, season_id, 
                        defense_specialist_elo, front_spiker_elo, setter_elo, libero_elo,
                        games_played, wins, losses)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 0)
                ''', (guild_id, user_id, season_id, 
                      starting_elo, starting_elo, starting_elo, starting_elo))
                
            # Now update for this specific game
            if is_winner:
                await self.db.execute(f'''
                    UPDATE season_stats SET
                        {position_column} = {position_column} + ?,
                        games_played = games_played + 1,
                        wins = wins + 1
                    WHERE guild_id = ? AND user_id = ? AND season_id = ?
                ''', (elo_change, guild_id, user_id, season_id))
            else:
                await self.db.execute(f'''
                    UPDATE season_stats SET
                        {position_column} = {position_column} + ?,
                        games_played = games_played + 1,
                        losses = losses + 1
                    WHERE guild_id = ? AND user_id = ? AND season_id = ?
                ''', (elo_change, guild_id, user_id, season_id))
                    
    # Blacklist methods
    async def add_to_blacklist(self, guild_id, user_id, blacklisted_by, reason=None, duration_hours=None):
        """Add a user to the blacklist. duration_hours=None means permanent."""
        expires_at = None
        if duration_hours is not None:
            from datetime import timedelta
            expires_at = (datetime.utcnow() + timedelta(hours=duration_hours)).isoformat()
        await self.db.execute(
            'INSERT OR REPLACE INTO blacklist (guild_id, user_id, blacklisted_by, reason, expires_at) VALUES (?, ?, ?, ?, ?)',
            (guild_id, user_id, blacklisted_by, reason, expires_at)
        )
        await self.db.commit()

    async def remove_from_blacklist(self, guild_id, user_id):
        """Remove a user from the blacklist"""
        await self.db.execute(
            'DELETE FROM blacklist WHERE guild_id = ? AND user_id = ?',
            (guild_id, user_id)
        )
        await self.db.commit()

    async def is_blacklisted(self, guild_id, user_id):
        """Check if a user is blacklisted. Auto-removes expired bans. Returns reason or None."""
        async with self.db.execute(
            'SELECT reason, expires_at FROM blacklist WHERE guild_id = ? AND user_id = ?',
            (guild_id, user_id)
        ) as cursor:
            result = await cursor.fetchone()
            if not result:
                return None
            reason, expires_at = result
            if expires_at:
                expiry = datetime.fromisoformat(expires_at)
                if datetime.utcnow() >= expiry:
                    # Ban expired, remove it
                    await self.remove_from_blacklist(guild_id, user_id)
                    return None
            return reason if reason else ""

    async def get_blacklist(self, guild_id):
        """Get all blacklisted users for a guild (excluding expired)"""
        # Clean up expired entries first
        await self.db.execute(
            "DELETE FROM blacklist WHERE guild_id = ? AND expires_at IS NOT NULL AND datetime(expires_at) <= datetime('now')",
            (guild_id,)
        )
        await self.db.commit()
        async with self.db.execute(
            'SELECT user_id, blacklisted_by, reason, timestamp, expires_at FROM blacklist WHERE guild_id = ?',
            (guild_id,)
        ) as cursor:
            return await cursor.fetchall()
            
    async def create_match(self, guild_id, team1_players, team2_players, text_channel_id=None, voice_channel_id=None, match_type='6v6', region=None):
        season_id = await self.get_current_season_id(guild_id)
        await self.db.execute(
            'INSERT INTO matches (guild_id, team1_players, team2_players, season_id, text_channel_id, voice_channel_id, match_type, region) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (guild_id, json.dumps(team1_players), json.dumps(team2_players), season_id, text_channel_id, voice_channel_id, match_type, region)
        )
        await self.db.commit()

        # Get the match ID we just created
        async with self.db.execute('SELECT last_insert_rowid()') as cursor:
            match_id = (await cursor.fetchone())[0]
        return match_id

    async def get_match_type(self, match_id):
        async with self.db.execute(
            'SELECT match_type FROM matches WHERE id = ?',
            (match_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else '6v6'

    async def get_match_region(self, match_id):
        async with self.db.execute(
            'SELECT region FROM matches WHERE id = ?',
            (match_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None
        
    async def get_match(self, match_id, guild_id):
        async with self.db.execute(
            'SELECT team1_players, team2_players FROM matches WHERE id = ? AND guild_id = ?',
            (match_id, guild_id)
        ) as cursor:
            return await cursor.fetchone()
            
    async def get_match_scores(self, match_id):
        """Get team1_score and team2_score for a match."""
        async with self.db.execute(
            'SELECT team1_score, team2_score FROM matches WHERE id = ?',
            (match_id,)
        ) as cursor:
            return await cursor.fetchone()

    async def update_match_score(self, match_id, team1_score, team2_score):
        await self.db.execute(
            'UPDATE matches SET team1_score = ?, team2_score = ? WHERE id = ?',
            (team1_score, team2_score, match_id)
        )
        await self.db.commit()
        
    async def set_match_inactive(self, match_id):
        await self.db.execute(
            'UPDATE matches SET is_active = 0 WHERE id = ?',
            (match_id,)
        )
        await self.db.commit()

    async def set_result_message_id(self, match_id, guild_id, message_id):
        """Store the result channel message ID for a match."""
        await self.db.execute(
            'UPDATE matches SET result_message_id = ? WHERE id = ? AND guild_id = ?',
            (message_id, match_id, guild_id)
        )
        await self.db.commit()

    async def get_result_message_id(self, match_id, guild_id):
        """Get the result channel message ID for a match."""
        async with self.db.execute(
            'SELECT result_message_id FROM matches WHERE id = ? AND guild_id = ?',
            (match_id, guild_id)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

    async def get_match_channels(self, match_id):
        async with self.db.execute(
            'SELECT text_channel_id, voice_channel_id FROM matches WHERE id = ?',
            (match_id,)
        ) as cursor:
            return await cursor.fetchone()

    async def save_match_transcript(self, match_id, guild_id, transcript):
        """Save a match chat transcript."""
        await self.db.execute(
            'INSERT OR REPLACE INTO match_transcripts (match_id, guild_id, transcript) VALUES (?, ?, ?)',
            (match_id, guild_id, transcript)
        )
        await self.db.commit()

    async def get_match_transcript(self, match_id, guild_id):
        """Get a match chat transcript."""
        async with self.db.execute(
            'SELECT transcript FROM match_transcripts WHERE match_id = ? AND guild_id = ?',
            (match_id, guild_id)
        ) as cursor:
            result = await cursor.fetchone()
            return result[0] if result else None

    async def get_active_matches(self, guild_id):
        async with self.db.execute(
            'SELECT id, text_channel_id, voice_channel_id FROM matches WHERE guild_id = ? AND is_active = 1',
            (guild_id,)
        ) as cursor:
            return await cursor.fetchall()
        
    async def get_leaderboard_data(self, guild_id, position=None, limit=10, offset=0, season_id=None):
        if season_id is None:
            # Current season leaderboard
            if position is None:
                # Get average elo - average positions played or admin-set
                async with self.db.execute('''
                    SELECT p.user_id,
                           COALESCE(
                               (SELECT AVG(
                                   CASE ps.position
                                       WHEN 'Defense Specialist' THEN p.defense_specialist_elo
                                       WHEN 'Front Spiker' THEN p.front_spiker_elo
                                       WHEN 'Setter' THEN p.setter_elo
                                       WHEN 'Libero' THEN p.libero_elo
                                   END
                               ) FROM position_stats ps
                               WHERE ps.guild_id = p.guild_id AND ps.user_id = p.user_id),
                               (p.defense_specialist_elo + p.front_spiker_elo + p.setter_elo + p.libero_elo) / 4.0
                           ) as avg_elo,
                           p.games_played, p.wins
                    FROM players p
                    WHERE p.guild_id = ? AND p.games_played > 0
                    ORDER BY avg_elo DESC
                    LIMIT ? OFFSET ?
                ''', (guild_id, limit, offset)) as cursor:
                    return await cursor.fetchall()
            else:
                # Get specific position elo - only include players who have played in that position
                position_column = position.lower().replace(" ", "_") + "_elo"
                async with self.db.execute(f'''
                    SELECT p.user_id, p.{position_column}, p.games_played, p.wins
                    FROM players p
                    INNER JOIN position_stats ps ON p.guild_id = ps.guild_id AND p.user_id = ps.user_id
                    WHERE p.guild_id = ? AND ps.position = ? AND ps.games_played > 0
                    ORDER BY p.{position_column} DESC
                    LIMIT ? OFFSET ?
                ''', (guild_id, position, limit, offset)) as cursor:
                    return await cursor.fetchall()
        else:
            # Season-specific leaderboard - only show players who played in the season
            if position is None:
                # Get average elo for season - average positions played or admin-set
                async with self.db.execute('''
                    SELECT ss.user_id,
                           COALESCE(
                               (SELECT AVG(
                                   CASE sps.position
                                       WHEN 'Defense Specialist' THEN ss.defense_specialist_elo
                                       WHEN 'Front Spiker' THEN ss.front_spiker_elo
                                       WHEN 'Setter' THEN ss.setter_elo
                                       WHEN 'Libero' THEN ss.libero_elo
                                   END
                               ) FROM season_position_stats sps
                               WHERE sps.guild_id = ss.guild_id AND sps.user_id = ss.user_id
                                   AND sps.season_id = ss.season_id),
                               (ss.defense_specialist_elo + ss.front_spiker_elo + ss.setter_elo + ss.libero_elo) / 4.0
                           ) as avg_elo,
                           ss.games_played, ss.wins
                    FROM season_stats ss
                    WHERE ss.guild_id = ? AND ss.season_id = ? AND ss.games_played > 0
                    ORDER BY avg_elo DESC
                    LIMIT ? OFFSET ?
                ''', (guild_id, season_id, limit, offset)) as cursor:
                    return await cursor.fetchall()
            else:
                # Get specific position elo for season - only if played in that position
                position_column = position.lower().replace(" ", "_") + "_elo"
                async with self.db.execute(f'''
                    SELECT ss.user_id, ss.{position_column}, ss.games_played, ss.wins
                    FROM season_stats ss
                    INNER JOIN season_position_stats sps ON ss.guild_id = sps.guild_id
                        AND ss.user_id = sps.user_id AND ss.season_id = sps.season_id
                    WHERE ss.guild_id = ? AND ss.season_id = ? AND sps.position = ? AND sps.games_played > 0
                    ORDER BY ss.{position_column} DESC
                    LIMIT ? OFFSET ?
                ''', (guild_id, season_id, position, limit, offset)) as cursor:
                    return await cursor.fetchall()
                    
    async def get_stats_leaderboard(self, guild_id, position, stat_type, limit=10, offset=0, season_id=None):
        """Get leaderboard sorted by specific stats"""
        # Determine which table to use
        table = "players" if season_id is None else "season_stats"
        season_clause = "" if season_id is None else f" AND season_id = {season_id}"
        
        # For position-specific stats
        if position != "all":
            pos_table = "position_stats" if season_id is None else "season_position_stats"
            
            if stat_type == "wins":
                query = f'''
                    SELECT ps.user_id, ps.wins as value, ps.games_played, ps.wins, ps.losses
                    FROM {pos_table} ps
                    WHERE ps.guild_id = ? AND ps.position = ? AND ps.games_played > 0 {season_clause}
                    ORDER BY ps.wins DESC, ps.games_played ASC
                    LIMIT ? OFFSET ?
                '''
                params = (guild_id, position, limit, offset) if season_id is None else (guild_id, position, limit, offset)
            elif stat_type == "losses":
                query = f'''
                    SELECT ps.user_id, ps.losses as value, ps.games_played, ps.wins, ps.losses
                    FROM {pos_table} ps
                    WHERE ps.guild_id = ? AND ps.position = ? AND ps.games_played > 0 {season_clause}
                    ORDER BY ps.losses DESC, ps.games_played DESC
                    LIMIT ? OFFSET ?
                '''
                params = (guild_id, position, limit, offset)
            elif stat_type == "winrate":
                query = f'''
                    SELECT ps.user_id, 
                           CASE WHEN ps.games_played > 0 THEN CAST(ps.wins AS REAL) / ps.games_played * 100 ELSE 0 END as value,
                           ps.games_played, ps.wins, ps.losses
                    FROM {pos_table} ps
                    WHERE ps.guild_id = ? AND ps.position = ? AND ps.games_played > 0 {season_clause}
                    ORDER BY value DESC, ps.games_played DESC
                    LIMIT ? OFFSET ?
                '''
                params = (guild_id, position, limit, offset)
            elif stat_type == "games":
                query = f'''
                    SELECT ps.user_id, ps.games_played as value, ps.games_played, ps.wins, ps.losses
                    FROM {pos_table} ps
                    WHERE ps.guild_id = ? AND ps.position = ? AND ps.games_played > 0 {season_clause}
                    ORDER BY ps.games_played DESC
                    LIMIT ? OFFSET ?
                '''
                params = (guild_id, position, limit, offset)
        else:
            # All positions
            if stat_type == "wins":
                query = f'''
                    SELECT user_id, wins as value, games_played, wins, losses
                    FROM {table}
                    WHERE guild_id = ? AND games_played > 0 {season_clause}
                    ORDER BY wins DESC, games_played ASC
                    LIMIT ? OFFSET ?
                '''
            elif stat_type == "losses":
                query = f'''
                    SELECT user_id, losses as value, games_played, wins, losses
                    FROM {table}
                    WHERE guild_id = ? AND games_played > 0 {season_clause}
                    ORDER BY losses DESC, games_played DESC
                    LIMIT ? OFFSET ?
                '''
            elif stat_type == "winrate":
                query = f'''
                    SELECT user_id, 
                           CASE WHEN games_played > 0 THEN CAST(wins AS REAL) / games_played * 100 ELSE 0 END as value,
                           games_played, wins, losses
                    FROM {table}
                    WHERE guild_id = ? AND games_played > 0 {season_clause}
                    ORDER BY value DESC, games_played DESC
                    LIMIT ? OFFSET ?
                '''
            elif stat_type == "games":
                query = f'''
                    SELECT user_id, games_played as value, games_played, wins, losses
                    FROM {table}
                    WHERE guild_id = ? AND games_played > 0 {season_clause}
                    ORDER BY games_played DESC
                    LIMIT ? OFFSET ?
                '''
            params = (guild_id, limit, offset)
            
        async with self.db.execute(query, params) as cursor:
            return await cursor.fetchall()
                
    async def get_player_count(self, guild_id, season_id=None):
        if season_id is None:
            async with self.db.execute(
                'SELECT COUNT(*) FROM players WHERE guild_id = ? AND games_played > 0',
                (guild_id,)
            ) as cursor:
                return (await cursor.fetchone())[0]
        else:
            async with self.db.execute(
                'SELECT COUNT(*) FROM season_stats WHERE guild_id = ? AND season_id = ? AND games_played > 0',
                (guild_id, season_id)
            ) as cursor:
                return (await cursor.fetchone())[0]
            
    async def get_player_stats(self, guild_id, user_id, season_id=None):
        if season_id is None:
            async with self.db.execute(
                '''SELECT defense_specialist_elo, front_spiker_elo, setter_elo, libero_elo,
                   games_played, wins, losses
                   FROM players WHERE guild_id = ? AND user_id = ?''',
                (guild_id, user_id)
            ) as cursor:
                return await cursor.fetchone()
        else:
            async with self.db.execute(
                '''SELECT defense_specialist_elo, front_spiker_elo, setter_elo, libero_elo,
                   games_played, wins, losses
                   FROM season_stats WHERE guild_id = ? AND user_id = ? AND season_id = ?''',
                (guild_id, user_id, season_id)
            ) as cursor:
                return await cursor.fetchone()
            
    async def remove_old_queue_entries(self, guild_id, timeout):
        await self.db.execute(
            'DELETE FROM queue WHERE guild_id = ? AND datetime("now") - datetime(timestamp) > ?',
            (guild_id, timeout)
        )
        await self.db.commit()
        
    async def set_player_elo(self, guild_id, user_id, position, new_elo):
        """Directly set a player's ELO for a specific position"""
        position_column = position.lower().replace(" ", "_") + "_elo"

        # Check if player exists
        async with self.db.execute(
            'SELECT * FROM players WHERE guild_id = ? AND user_id = ?',
            (guild_id, user_id)
        ) as cursor:
            player_exists = await cursor.fetchone()

        config = await self.get_config(guild_id)
        starting_elo = config["starting_elo"]

        if not player_exists:
            # Create new player with starting ELO for all positions
            await self.db.execute(f'''
                INSERT INTO players (guild_id, user_id,
                    defense_specialist_elo, front_spiker_elo, setter_elo, libero_elo,
                    games_played, wins, losses)
                VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0)
            ''', (guild_id, user_id, starting_elo, starting_elo, starting_elo, starting_elo))

        # Now update the specific position
        await self.db.execute(f'''
            UPDATE players
            SET {position_column} = ?
            WHERE guild_id = ? AND user_id = ?
        ''', (new_elo, guild_id, user_id))

        # Ensure position_stats entry exists so avg ELO calculation includes this position
        await self.db.execute('''
            INSERT INTO position_stats (guild_id, user_id, position, games_played, wins, losses)
            VALUES (?, ?, ?, 0, 0, 0)
            ON CONFLICT(guild_id, user_id, position) DO NOTHING
        ''', (guild_id, user_id, position))

        # Also update the active season's stats so /stats with season reflects the adjustment
        season = await self.get_current_season(guild_id, '6v6')
        if season:
            season_id = season[0]
            # Ensure season_stats row exists
            await self.db.execute(f'''
                INSERT INTO season_stats (guild_id, user_id, season_id,
                    defense_specialist_elo, front_spiker_elo, setter_elo, libero_elo,
                    games_played, wins, losses)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 0)
                ON CONFLICT(guild_id, user_id, season_id) DO NOTHING
            ''', (guild_id, user_id, season_id, starting_elo, starting_elo, starting_elo, starting_elo))
            # Update the specific position in season stats
            await self.db.execute(f'''
                UPDATE season_stats
                SET {position_column} = ?
                WHERE guild_id = ? AND user_id = ? AND season_id = ?
            ''', (new_elo, guild_id, user_id, season_id))

            # Ensure season_position_stats entry exists
            await self.db.execute('''
                INSERT INTO season_position_stats (guild_id, user_id, season_id, position, games_played, wins, losses)
                VALUES (?, ?, ?, ?, 0, 0, 0)
                ON CONFLICT(guild_id, user_id, season_id, position) DO NOTHING
            ''', (guild_id, user_id, season_id, position))

        await self.db.commit()
        
    async def adjust_player_elo(self, guild_id, user_id, position, elo_change):
        """Add or subtract ELO for a specific position"""
        position_column = position.lower().replace(" ", "_") + "_elo"
        
        # Get current ELO
        current_elo = await self.get_player_elo(guild_id, user_id, position)
        new_elo = max(0, current_elo + elo_change)  # Ensure ELO doesn't go below 0
        
        await self.set_player_elo(guild_id, user_id, position, new_elo)
        return current_elo, new_elo
        
    async def reset_player_stats(self, guild_id, user_id):
        """Reset all stats for a player"""
        config = await self.get_config(guild_id)
        starting_elo = config["starting_elo"]
        
        await self.db.execute('''
            INSERT INTO players (guild_id, user_id, 
                defense_specialist_elo, front_spiker_elo, setter_elo, libero_elo,
                games_played, wins, losses)
            VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0)
            ON CONFLICT(guild_id, user_id)
            DO UPDATE SET
                defense_specialist_elo = ?,
                front_spiker_elo = ?,
                setter_elo = ?,
                libero_elo = ?,
                games_played = 0,
                wins = 0,
                losses = 0
        ''', (guild_id, user_id, starting_elo, starting_elo, starting_elo, starting_elo,
              starting_elo, starting_elo, starting_elo, starting_elo))
        await self.db.commit()
        
    async def clear_queue(self, guild_id, queue_type=None):
        """Clear all players from queue, optionally filtered by type"""
        if queue_type:
            await self.db.execute('DELETE FROM queue WHERE guild_id = ? AND queue_type = ?', (guild_id, queue_type))
        else:
            await self.db.execute('DELETE FROM queue WHERE guild_id = ?', (guild_id,))
        await self.db.commit()
        
    async def get_recent_matches(self, guild_id, user_id=None, limit=5):
        """Get recent matches, optionally filtered by user"""
        if user_id:
            query = '''
                SELECT id, team1_players, team2_players, team1_score, team2_score, timestamp
                FROM matches
                WHERE guild_id = ? AND 
                    (team1_players LIKE ? OR team2_players LIKE ?)
                ORDER BY timestamp DESC
                LIMIT ?
            '''
            user_pattern = f'%{user_id}%'
            params = (guild_id, user_pattern, user_pattern, limit)
        else:
            query = '''
                SELECT id, team1_players, team2_players, team1_score, team2_score, timestamp
                FROM matches
                WHERE guild_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            '''
            params = (guild_id, limit)
            
        async with self.db.execute(query, params) as cursor:
            return await cursor.fetchall()
            
    async def update_starting_elo_for_unplayed_positions(self, guild_id, old_starting_elo, new_starting_elo):
        """Update ELO for all positions where players haven't played any games"""
        positions = ['defense_specialist', 'front_spiker', 'setter', 'libero']
        
        # Get all players in this guild
        async with self.db.execute(
            'SELECT user_id FROM players WHERE guild_id = ?',
            (guild_id,)
        ) as cursor:
            players = await cursor.fetchall()
            
        for (user_id,) in players:
            # Check each position
            for position in positions:
                position_name = position.replace('_', ' ').title()
                
                # Check if player has played games in this position
                async with self.db.execute(
                    'SELECT games_played FROM position_stats WHERE guild_id = ? AND user_id = ? AND position = ?',
                    (guild_id, user_id, position_name)
                ) as cursor:
                    result = await cursor.fetchone()
                    
                if not result or result[0] == 0:  # No games played in this position
                    # Update ELO to new starting ELO regardless of current value
                    position_column = position + "_elo"
                    await self.db.execute(f'''
                        UPDATE players 
                        SET {position_column} = ?
                        WHERE guild_id = ? AND user_id = ?
                    ''', (new_starting_elo, guild_id, user_id))
                    
        await self.db.commit()
        
    async def get_position_games_played(self, guild_id, user_id, position, season_id=None):
        """Get number of games played in a specific position"""
        if season_id is None:
            async with self.db.execute(
                'SELECT games_played FROM position_stats WHERE guild_id = ? AND user_id = ? AND position = ?',
                (guild_id, user_id, position)
            ) as cursor:
                result = await cursor.fetchone()
                return result[0] if result else 0
        else:
            async with self.db.execute(
                'SELECT games_played FROM season_position_stats WHERE guild_id = ? AND user_id = ? AND season_id = ? AND position = ?',
                (guild_id, user_id, season_id, position)
            ) as cursor:
                result = await cursor.fetchone()
                return result[0] if result else 0

    async def get_position_wl(self, guild_id, user_id, position, season_id=None):
        """Get wins and losses for a specific position"""
        if season_id is None:
            async with self.db.execute(
                'SELECT wins, losses FROM position_stats WHERE guild_id = ? AND user_id = ? AND position = ?',
                (guild_id, user_id, position)
            ) as cursor:
                result = await cursor.fetchone()
                return (result[0], result[1]) if result else (0, 0)
        else:
            async with self.db.execute(
                'SELECT wins, losses FROM season_position_stats WHERE guild_id = ? AND user_id = ? AND season_id = ? AND position = ?',
                (guild_id, user_id, season_id, position)
            ) as cursor:
                result = await cursor.fetchone()
                return (result[0], result[1]) if result else (0, 0)
                
    async def revert_match_result(self, match_id, guild_id):
        """Revert a match result and restore ELOs"""
        # Get match details
        async with self.db.execute(
            'SELECT team1_players, team2_players, team1_score, team2_score, season_id, match_type FROM matches WHERE id = ? AND guild_id = ?',
            (match_id, guild_id)
        ) as cursor:
            match_data = await cursor.fetchone()

        if not match_data:
            return False, "Match not found"

        team1_players = json.loads(match_data[0])
        team2_players = json.loads(match_data[1])
        team1_score = match_data[2]
        team2_score = match_data[3]
        season_id = match_data[4]
        match_type = match_data[5] or '6v6'
        
        if team1_score is None and team2_score is None:
            return False, "Match has no recorded result to revert"
            
        config = await self.get_config(guild_id)
        k_factor = config["k_factor"]
        
        # Handle different match outcomes
        if team1_score > team2_score:
            # Team 1 won
            winners = team1_players
            losers = team2_players
            is_tie = False
        elif team2_score > team1_score:
            # Team 2 won
            winners = team2_players
            losers = team1_players
            is_tie = False
        else:
            # It's a tie - no ELO changes, just revert game counts
            is_tie = True
            
        # Use elo_history table for accurate reversion instead of estimating
        all_players = team1_players + team2_players

        # Determine the correct table for this match type
        is_simple_queue = match_type in ('2v2', '3v3', 'highrank_2v2', 'highrank_3v3')
        is_highrank_6v6 = match_type == 'highrank'

        if is_tie:
            # Revert tie match - only game counts, no ELO changes
            for player_data in all_players:
                player_id = player_data[0]
                player_position = player_data[1]

                if is_simple_queue:
                    table = f"players_{match_type}"
                    await self.db.execute(f'''
                        UPDATE {table} SET games_played = games_played - 1
                        WHERE guild_id = ? AND user_id = ?
                    ''', (guild_id, player_id))
                elif is_highrank_6v6:
                    await self.db.execute('''
                        UPDATE players_highrank SET games_played = games_played - 1
                        WHERE guild_id = ? AND user_id = ?
                    ''', (guild_id, player_id))
                    await self.db.execute('''
                        UPDATE position_stats_highrank SET games_played = games_played - 1
                        WHERE guild_id = ? AND user_id = ? AND position = ?
                    ''', (guild_id, player_id, player_position))
                else:
                    await self.db.execute('''
                        UPDATE players SET games_played = games_played - 1
                        WHERE guild_id = ? AND user_id = ?
                    ''', (guild_id, player_id))
                    await self.db.execute('''
                        UPDATE position_stats SET games_played = games_played - 1
                        WHERE guild_id = ? AND user_id = ? AND position = ?
                    ''', (guild_id, player_id, player_position))

                if season_id:
                    if is_simple_queue:
                        season_table = f"season_stats_{match_type}"
                        await self.db.execute(f'''
                            UPDATE {season_table} SET games_played = games_played - 1
                            WHERE guild_id = ? AND user_id = ? AND season_id = ?
                        ''', (guild_id, player_id, season_id))
                    elif is_highrank_6v6:
                        await self.db.execute('''
                            UPDATE season_stats_highrank SET games_played = games_played - 1
                            WHERE guild_id = ? AND user_id = ? AND season_id = ?
                        ''', (guild_id, player_id, season_id))
                    else:
                        await self.db.execute('''
                            UPDATE season_stats SET games_played = games_played - 1
                            WHERE guild_id = ? AND user_id = ? AND season_id = ?
                        ''', (guild_id, player_id, season_id))
                        await self.db.execute('''
                            UPDATE season_position_stats SET games_played = games_played - 1
                            WHERE guild_id = ? AND user_id = ? AND season_id = ? AND position = ?
                        ''', (guild_id, player_id, season_id, player_position))
        else:
            # Use elo_history for exact ELO reversion
            for player_data in all_players:
                player_id = player_data[0]
                player_position = player_data[1]
                position_column = player_position.lower().replace(" ", "_") + "_elo"

                # Look up the exact ELO change from elo_history
                async with self.db.execute('''
                    SELECT elo_before, elo_after, elo_change, is_winner
                    FROM elo_history
                    WHERE guild_id = ? AND user_id = ? AND match_id = ?
                    ORDER BY timestamp DESC LIMIT 1
                ''', (guild_id, player_id, match_id)) as cursor:
                    history_row = await cursor.fetchone()

                if history_row:
                    elo_before, elo_after, elo_change, was_winner = history_row
                    # Restore to elo_before by subtracting the change
                    actual_change = elo_after - elo_before
                else:
                    # Fallback: no history entry for this player
                    actual_change = 0
                    was_winner = (player_data in winners) if not is_tie else False

                is_winner = bool(was_winner)

                # Revert ELO and stats based on match type
                if is_simple_queue:
                    table = f"players_{match_type}"
                    await self.db.execute(f'''
                        UPDATE {table} SET
                            elo = elo - ?,
                            games_played = games_played - 1,
                            wins = CASE WHEN ? THEN wins - 1 ELSE wins END,
                            losses = CASE WHEN ? THEN losses ELSE losses - 1 END
                        WHERE guild_id = ? AND user_id = ?
                    ''', (actual_change, is_winner, is_winner, guild_id, player_id))
                elif is_highrank_6v6:
                    await self.db.execute(f'''
                        UPDATE players_highrank SET
                            {position_column} = {position_column} - ?,
                            games_played = games_played - 1,
                            wins = CASE WHEN ? THEN wins - 1 ELSE wins END,
                            losses = CASE WHEN ? THEN losses ELSE losses - 1 END
                        WHERE guild_id = ? AND user_id = ?
                    ''', (actual_change, is_winner, is_winner, guild_id, player_id))
                    await self.db.execute('''
                        UPDATE position_stats_highrank SET
                            games_played = games_played - 1,
                            wins = CASE WHEN ? THEN wins - 1 ELSE wins END,
                            losses = CASE WHEN ? THEN losses ELSE losses - 1 END
                        WHERE guild_id = ? AND user_id = ? AND position = ?
                    ''', (is_winner, is_winner, guild_id, player_id, player_position))
                else:
                    await self.db.execute(f'''
                        UPDATE players SET
                            {position_column} = {position_column} - ?,
                            games_played = games_played - 1,
                            wins = CASE WHEN ? THEN wins - 1 ELSE wins END,
                            losses = CASE WHEN ? THEN losses ELSE losses - 1 END
                        WHERE guild_id = ? AND user_id = ?
                    ''', (actual_change, is_winner, is_winner, guild_id, player_id))
                    await self.db.execute('''
                        UPDATE position_stats SET
                            games_played = games_played - 1,
                            wins = CASE WHEN ? THEN wins - 1 ELSE wins END,
                            losses = CASE WHEN ? THEN losses ELSE losses - 1 END
                        WHERE guild_id = ? AND user_id = ? AND position = ?
                    ''', (is_winner, is_winner, guild_id, player_id, player_position))

                if season_id:
                    if is_simple_queue:
                        season_table = f"season_stats_{match_type}"
                        await self.db.execute(f'''
                            UPDATE {season_table} SET
                                elo = elo - ?,
                                games_played = games_played - 1,
                                wins = CASE WHEN ? THEN wins - 1 ELSE wins END,
                                losses = CASE WHEN ? THEN losses ELSE losses - 1 END
                            WHERE guild_id = ? AND user_id = ? AND season_id = ?
                        ''', (actual_change, is_winner, is_winner, guild_id, player_id, season_id))
                    elif is_highrank_6v6:
                        await self.db.execute(f'''
                            UPDATE season_stats_highrank SET
                                {position_column} = {position_column} - ?,
                                games_played = games_played - 1,
                                wins = CASE WHEN ? THEN wins - 1 ELSE wins END,
                                losses = CASE WHEN ? THEN losses ELSE losses - 1 END
                            WHERE guild_id = ? AND user_id = ? AND season_id = ?
                        ''', (actual_change, is_winner, is_winner, guild_id, player_id, season_id))
                    else:
                        await self.db.execute(f'''
                            UPDATE season_stats SET
                                {position_column} = {position_column} - ?,
                                games_played = games_played - 1,
                                wins = CASE WHEN ? THEN wins - 1 ELSE wins END,
                                losses = CASE WHEN ? THEN losses ELSE losses - 1 END
                            WHERE guild_id = ? AND user_id = ? AND season_id = ?
                        ''', (actual_change, is_winner, is_winner, guild_id, player_id, season_id))
                        await self.db.execute('''
                            UPDATE season_position_stats SET
                                games_played = games_played - 1,
                                wins = CASE WHEN ? THEN wins - 1 ELSE wins END,
                                losses = CASE WHEN ? THEN losses ELSE losses - 1 END
                            WHERE guild_id = ? AND user_id = ? AND season_id = ? AND position = ?
                        ''', (is_winner, is_winner, guild_id, player_id, season_id, player_position))

                # Delete elo_history entry for this match
                await self.db.execute('''
                    DELETE FROM elo_history
                    WHERE guild_id = ? AND user_id = ? AND match_id = ?
                ''', (guild_id, player_id, match_id))
        
        # Clear match scores and mark as active again
        await self.db.execute(
            'UPDATE matches SET team1_score = NULL, team2_score = NULL, is_active = 1 WHERE id = ?',
            (match_id,)
        )
        
        await self.db.commit()
        
        if is_tie:
            return True, "Tie match successfully reverted (game counts restored)"
        else:
            return True, "Match result successfully reverted (ELOs and stats restored)"
                
    # Season-specific methods
    async def create_season(self, guild_id, name, queue_type='6v6'):
        """Create a new season for a specific queue type and end the current one for that type"""
        # Check if there's a current season for this queue type
        current_season = await self.get_current_season(guild_id, queue_type)

        # End current season for this queue type if exists
        await self.db.execute(
            'UPDATE seasons SET is_active = 0, end_date = CURRENT_TIMESTAMP WHERE guild_id = ? AND is_active = 1 AND queue_type = ?',
            (guild_id, queue_type)
        )

        # If there was a previous season for this queue type, wipe relevant stats
        if current_season:
            config = await self.get_config(guild_id)
            starting_elo = config["starting_elo"]

            if queue_type == '6v6':
                async with self.db.execute(
                    'SELECT DISTINCT user_id FROM players WHERE guild_id = ?',
                    (guild_id,)
                ) as cursor:
                    all_players = await cursor.fetchall()

                await self.db.execute('DELETE FROM players WHERE guild_id = ?', (guild_id,))
                await self.db.execute('DELETE FROM position_stats WHERE guild_id = ?', (guild_id,))
                await self.db.execute('DELETE FROM players_highrank WHERE guild_id = ?', (guild_id,))
                await self.db.execute('DELETE FROM position_stats_highrank WHERE guild_id = ?', (guild_id,))

                for (user_id,) in all_players:
                    await self.db.execute('''
                        INSERT INTO players (guild_id, user_id,
                            defense_specialist_elo, front_spiker_elo, setter_elo, libero_elo,
                            games_played, wins, losses)
                        VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0)
                    ''', (guild_id, user_id, starting_elo, starting_elo, starting_elo, starting_elo))
            elif queue_type == '2v2':
                await self.db.execute('DELETE FROM players_2v2 WHERE guild_id = ?', (guild_id,))
            elif queue_type == '3v3':
                await self.db.execute('DELETE FROM players_3v3 WHERE guild_id = ?', (guild_id,))

        # Create new season
        await self.db.execute(
            'INSERT INTO seasons (guild_id, name, queue_type) VALUES (?, ?, ?)',
            (guild_id, name, queue_type)
        )
        await self.db.commit()

        async with self.db.execute('SELECT last_insert_rowid()') as cursor:
            return (await cursor.fetchone())[0]

    async def end_season(self, guild_id, queue_type='6v6'):
        """End the current season for a specific queue type and wipe its stats"""
        await self.db.execute(
            'UPDATE seasons SET is_active = 0, end_date = CURRENT_TIMESTAMP WHERE guild_id = ? AND is_active = 1 AND queue_type = ?',
            (guild_id, queue_type)
        )

        config = await self.get_config(guild_id)
        starting_elo = config["starting_elo"]

        if queue_type == '6v6':
            async with self.db.execute(
                'SELECT DISTINCT user_id FROM players WHERE guild_id = ?',
                (guild_id,)
            ) as cursor:
                all_players = await cursor.fetchall()

            await self.db.execute('DELETE FROM players WHERE guild_id = ?', (guild_id,))
            await self.db.execute('DELETE FROM position_stats WHERE guild_id = ?', (guild_id,))
            await self.db.execute('DELETE FROM players_highrank WHERE guild_id = ?', (guild_id,))
            await self.db.execute('DELETE FROM position_stats_highrank WHERE guild_id = ?', (guild_id,))

            for (user_id,) in all_players:
                await self.db.execute('''
                    INSERT INTO players (guild_id, user_id,
                        defense_specialist_elo, front_spiker_elo, setter_elo, libero_elo,
                        games_played, wins, losses)
                    VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0)
                ''', (guild_id, user_id, starting_elo, starting_elo, starting_elo, starting_elo))
        elif queue_type == '2v2':
            await self.db.execute('DELETE FROM players_2v2 WHERE guild_id = ?', (guild_id,))
        elif queue_type == '3v3':
            await self.db.execute('DELETE FROM players_3v3 WHERE guild_id = ?', (guild_id,))

        await self.db.commit()
        
    async def delete_season(self, guild_id, season_id):
        """Delete a season and all associated data"""
        await self.db.execute('DELETE FROM season_stats WHERE guild_id = ? AND season_id = ?', (guild_id, season_id))
        await self.db.execute('DELETE FROM season_position_stats WHERE guild_id = ? AND season_id = ?', (guild_id, season_id))
        await self.db.execute('DELETE FROM season_stats_2v2 WHERE guild_id = ? AND season_id = ?', (guild_id, season_id))
        await self.db.execute('DELETE FROM season_stats_3v3 WHERE guild_id = ? AND season_id = ?', (guild_id, season_id))
        await self.db.execute('DELETE FROM season_stats_highrank WHERE guild_id = ? AND season_id = ?', (guild_id, season_id))
        await self.db.execute('UPDATE matches SET season_id = NULL WHERE guild_id = ? AND season_id = ?', (guild_id, season_id))
        await self.db.execute('DELETE FROM seasons WHERE id = ? AND guild_id = ?', (season_id, guild_id))
        await self.db.commit()
        
    async def get_current_season(self, guild_id, queue_type='6v6'):
        """Get the current active season for a specific queue type"""
        async with self.db.execute(
            'SELECT id, name, start_date FROM seasons WHERE guild_id = ? AND is_active = 1 AND queue_type = ?',
            (guild_id, queue_type)
        ) as cursor:
            return await cursor.fetchone()

    async def get_current_season_any(self, guild_id):
        """Get any active season (for backward compat - returns first found, preferring 6v6)"""
        for qt in ('6v6', '2v2', '3v3'):
            result = await self.get_current_season(guild_id, qt)
            if result:
                return result
        return None

    async def get_current_season_id(self, guild_id, queue_type='6v6'):
        """Get just the ID of the current season for a queue type"""
        season = await self.get_current_season(guild_id, queue_type)
        return season[0] if season else None

    async def get_all_seasons(self, guild_id, queue_type=None):
        """Get all seasons for a guild, optionally filtered by queue type"""
        if queue_type:
            async with self.db.execute(
                'SELECT id, name, start_date, end_date, is_active FROM seasons WHERE guild_id = ? AND queue_type = ? ORDER BY start_date DESC',
                (guild_id, queue_type)
            ) as cursor:
                return await cursor.fetchall()
        else:
            async with self.db.execute(
                'SELECT id, name, start_date, end_date, is_active FROM seasons WHERE guild_id = ? ORDER BY start_date DESC',
                (guild_id,)
            ) as cursor:
                return await cursor.fetchall()

    async def get_season_by_name(self, guild_id, name, queue_type=None):
        """Get a season by its name, optionally filtered by queue type"""
        if queue_type:
            async with self.db.execute(
                'SELECT id, name, start_date, end_date, is_active FROM seasons WHERE guild_id = ? AND name = ? AND queue_type = ?',
                (guild_id, name, queue_type)
            ) as cursor:
                return await cursor.fetchone()
        else:
            async with self.db.execute(
                'SELECT id, name, start_date, end_date, is_active FROM seasons WHERE guild_id = ? AND name = ?',
                (guild_id, name)
            ) as cursor:
                return await cursor.fetchone()
            
    async def reset_season_elo(self, guild_id, season_id):
        """Initialize season records only for players as they play - DO NOT pre-initialize"""
        # This function is now effectively a no-op since we create season stats on demand
        # when players actually play matches (in update_player_elo)
        await self.db.commit()

    async def add_elo_role_mapping(self, guild_id, position, elo_threshold, role_id):
        """Add an ELO-based role mapping"""
        await self.db.execute(
            'INSERT OR REPLACE INTO elo_role_mappings (guild_id, position, elo_threshold, role_id) VALUES (?, ?, ?, ?)',
            (guild_id, position, elo_threshold, role_id)
        )
        await self.db.commit()
        
    async def remove_elo_role_mapping(self, guild_id, position, elo_threshold):
        """Remove an ELO-based role mapping"""
        result = await self.db.execute(
            'DELETE FROM elo_role_mappings WHERE guild_id = ? AND position = ? AND elo_threshold = ?',
            (guild_id, position, elo_threshold)
        )
        await self.db.commit()
        return result.rowcount > 0
        
    async def get_elo_role_mapping(self, guild_id, position, elo_threshold):
        """Get a specific ELO role mapping"""
        async with self.db.execute(
            'SELECT role_id FROM elo_role_mappings WHERE guild_id = ? AND position = ? AND elo_threshold = ?',
            (guild_id, position, elo_threshold)
        ) as cursor:
            result = await cursor.fetchone()
            return result[0] if result else None
            
    async def get_all_elo_role_mappings(self, guild_id):
        """Get all ELO role mappings for a guild"""
        async with self.db.execute(
            'SELECT position, elo_threshold, role_id FROM elo_role_mappings WHERE guild_id = ? ORDER BY position, elo_threshold',
            (guild_id,)
        ) as cursor:
            return await cursor.fetchall()
            
    async def get_all_players(self, guild_id):
        """Get all players in a guild with their ELOs"""
        async with self.db.execute(
            'SELECT user_id, defense_specialist_elo, front_spiker_elo, setter_elo, libero_elo, games_played FROM players WHERE guild_id = ?',
            (guild_id,)
        ) as cursor:
            return await cursor.fetchall()

    # ──────────────────────────────────────────────
    #  2v2 / 3v3 SINGULAR MMR
    # ──────────────────────────────────────────────

    async def get_player_elo_simple(self, guild_id, user_id, queue_type):
        """Get player's singular ELO for 2v2 or 3v3"""
        table = f"players_{queue_type}"
        config = await self.get_config(guild_id)
        if queue_type.startswith("highrank"):
            starting_elo = config.get("high_rank_starting_elo", config["starting_elo"])
        else:
            starting_elo = config["starting_elo"]

        async with self.db.execute(
            f'SELECT elo FROM {table} WHERE guild_id = ? AND user_id = ?',
            (guild_id, user_id)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return row[0]
            return starting_elo

    async def update_player_elo_simple(self, guild_id, user_id, queue_type, elo_change, is_winner, starting_elo):
        """Update player's singular ELO for 2v2 or 3v3"""
        table = f"players_{queue_type}"
        season_table = f"season_stats_{queue_type}"
        # High rank queues use their base type's season
        season_queue_type = queue_type
        if queue_type == 'highrank_2v2':
            season_queue_type = '2v2'
        elif queue_type == 'highrank_3v3':
            season_queue_type = '3v3'
        season_id = await self.get_current_season_id(guild_id, season_queue_type)

        # Ensure player exists
        async with self.db.execute(
            f'SELECT * FROM {table} WHERE guild_id = ? AND user_id = ?',
            (guild_id, user_id)
        ) as cursor:
            if not await cursor.fetchone():
                await self.db.execute(
                    f'INSERT INTO {table} (guild_id, user_id, elo, games_played, wins, losses) VALUES (?, ?, ?, 0, 0, 0)',
                    (guild_id, user_id, starting_elo)
                )

        if is_winner:
            await self.db.execute(f'''
                UPDATE {table} SET elo = elo + ?, games_played = games_played + 1, wins = wins + 1,
                    win_streak = win_streak + 1, loss_streak = 0,
                    best_win_streak = MAX(best_win_streak, win_streak + 1)
                WHERE guild_id = ? AND user_id = ?
            ''', (elo_change, guild_id, user_id))
        else:
            await self.db.execute(f'''
                UPDATE {table} SET elo = elo + ?, games_played = games_played + 1, losses = losses + 1,
                    loss_streak = loss_streak + 1, win_streak = 0,
                    best_loss_streak = MAX(best_loss_streak, loss_streak + 1)
                WHERE guild_id = ? AND user_id = ?
            ''', (elo_change, guild_id, user_id))

        # Season stats
        if season_id:
            async with self.db.execute(
                f'SELECT * FROM {season_table} WHERE guild_id = ? AND user_id = ? AND season_id = ?',
                (guild_id, user_id, season_id)
            ) as cursor:
                if not await cursor.fetchone():
                    await self.db.execute(
                        f'INSERT INTO {season_table} (guild_id, user_id, season_id, elo, games_played, wins, losses) VALUES (?, ?, ?, ?, 0, 0, 0)',
                        (guild_id, user_id, season_id, starting_elo)
                    )

            if is_winner:
                await self.db.execute(f'''
                    UPDATE {season_table} SET elo = elo + ?, games_played = games_played + 1, wins = wins + 1
                    WHERE guild_id = ? AND user_id = ? AND season_id = ?
                ''', (elo_change, guild_id, user_id, season_id))
            else:
                await self.db.execute(f'''
                    UPDATE {season_table} SET elo = elo + ?, games_played = games_played + 1, losses = losses + 1
                    WHERE guild_id = ? AND user_id = ? AND season_id = ?
                ''', (elo_change, guild_id, user_id, season_id))

    async def get_player_stats_simple(self, guild_id, user_id, queue_type):
        """Get player stats for 2v2/3v3"""
        table = f"players_{queue_type}"
        async with self.db.execute(
            f'SELECT elo, games_played, wins, losses FROM {table} WHERE guild_id = ? AND user_id = ?',
            (guild_id, user_id)
        ) as cursor:
            return await cursor.fetchone()

    async def get_player_season_stats_simple(self, guild_id, user_id, queue_type, season_id):
        """Get player season stats for 2v2/3v3/highrank_2v2/highrank_3v3"""
        table = f"season_stats_{queue_type}"
        async with self.db.execute(
            f'SELECT elo, games_played, wins, losses FROM {table} WHERE guild_id = ? AND user_id = ? AND season_id = ?',
            (guild_id, user_id, season_id)
        ) as cursor:
            return await cursor.fetchone()

    async def get_leaderboard_data_simple(self, guild_id, queue_type, limit=10, offset=0):
        """Get leaderboard data for 2v2 or 3v3"""
        table = f"players_{queue_type}"
        async with self.db.execute(f'''
            SELECT user_id, elo, games_played, wins
            FROM {table}
            WHERE guild_id = ? AND games_played > 0
            ORDER BY elo DESC
            LIMIT ? OFFSET ?
        ''', (guild_id, limit, offset)) as cursor:
            return await cursor.fetchall()

    async def get_player_count_simple(self, guild_id, queue_type):
        """Get the number of players with games in 2v2/3v3"""
        table = f"players_{queue_type}"
        async with self.db.execute(
            f'SELECT COUNT(*) FROM {table} WHERE guild_id = ? AND games_played > 0',
            (guild_id,)
        ) as cursor:
            return (await cursor.fetchone())[0]

    async def set_player_elo_simple(self, guild_id, user_id, queue_type, new_elo):
        """Directly set a player's ELO for 2v2, 3v3, highrank_2v2, or highrank_3v3."""
        table = f"players_{queue_type}"

        config = await self.get_config(guild_id)
        if queue_type.startswith("highrank"):
            starting_elo = config.get("high_rank_starting_elo", config["starting_elo"])
        else:
            starting_elo = config["starting_elo"]

        async with self.db.execute(
            f'SELECT * FROM {table} WHERE guild_id = ? AND user_id = ?',
            (guild_id, user_id)
        ) as cursor:
            if not await cursor.fetchone():
                await self.db.execute(
                    f'INSERT INTO {table} (guild_id, user_id, elo, games_played, wins, losses) VALUES (?, ?, ?, 0, 0, 0)',
                    (guild_id, user_id, starting_elo)
                )

        await self.db.execute(
            f'UPDATE {table} SET elo = ? WHERE guild_id = ? AND user_id = ?',
            (new_elo, guild_id, user_id)
        )

        # Also update the active season's stats so /stats with season reflects the adjustment
        if queue_type in ('2v2', '3v3'):
            season = await self.get_current_season(guild_id, queue_type)
            if season:
                season_id = season[0]
                season_table = f"season_stats_{queue_type}"
                await self.db.execute(f'''
                    INSERT INTO {season_table} (guild_id, user_id, season_id, elo, games_played, wins, losses)
                    VALUES (?, ?, ?, ?, 0, 0, 0)
                    ON CONFLICT(guild_id, user_id, season_id) DO NOTHING
                ''', (guild_id, user_id, season_id, starting_elo))
                await self.db.execute(f'''
                    UPDATE {season_table} SET elo = ?
                    WHERE guild_id = ? AND user_id = ? AND season_id = ?
                ''', (new_elo, guild_id, user_id, season_id))
        elif queue_type in ('highrank_2v2', 'highrank_3v3'):
            base_qt = queue_type.replace("highrank_", "")
            season = await self.get_current_season(guild_id, base_qt)
            if season:
                season_id = season[0]
                season_table = f"season_stats_{queue_type}"
                await self.db.execute(f'''
                    INSERT INTO {season_table} (guild_id, user_id, season_id, elo, games_played, wins, losses)
                    VALUES (?, ?, ?, ?, 0, 0, 0)
                    ON CONFLICT(guild_id, user_id, season_id) DO NOTHING
                ''', (guild_id, user_id, season_id, starting_elo))
                await self.db.execute(f'''
                    UPDATE {season_table} SET elo = ?
                    WHERE guild_id = ? AND user_id = ? AND season_id = ?
                ''', (new_elo, guild_id, user_id, season_id))

        await self.db.commit()

    # ──────────────────────────────────────────────
    #  HIGH RANK ELO (per-position, separate)
    # ──────────────────────────────────────────────

    async def get_player_elo_highrank(self, guild_id, user_id, position):
        """Get player's high rank ELO for a position"""
        position_column = position.lower().replace(" ", "_") + "_elo"
        config = await self.get_config(guild_id)
        starting_elo = config.get("high_rank_starting_elo", config["starting_elo"])

        async with self.db.execute(
            f'SELECT {position_column} FROM players_highrank WHERE guild_id = ? AND user_id = ?',
            (guild_id, user_id)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return row[0]  # Return stored ELO (may have been set by admin)
            return starting_elo

    async def set_player_elo_highrank(self, guild_id, user_id, position, new_elo):
        """Directly set a player's high rank ELO for a specific position."""
        position_column = position.lower().replace(" ", "_") + "_elo"
        config = await self.get_config(guild_id)
        starting_elo = config.get("high_rank_starting_elo", config["starting_elo"])

        async with self.db.execute(
            'SELECT * FROM players_highrank WHERE guild_id = ? AND user_id = ?',
            (guild_id, user_id)
        ) as cursor:
            if not await cursor.fetchone():
                await self.db.execute('''
                    INSERT INTO players_highrank (guild_id, user_id,
                        defense_specialist_elo, front_spiker_elo, setter_elo, libero_elo,
                        games_played, wins, losses)
                    VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0)
                ''', (guild_id, user_id, starting_elo, starting_elo, starting_elo, starting_elo))

        await self.db.execute(f'''
            UPDATE players_highrank SET {position_column} = ?
            WHERE guild_id = ? AND user_id = ?
        ''', (new_elo, guild_id, user_id))

        # Ensure position_stats_highrank entry exists so avg ELO calculation includes this position
        await self.db.execute('''
            INSERT INTO position_stats_highrank (guild_id, user_id, position, games_played, wins, losses)
            VALUES (?, ?, ?, 0, 0, 0)
            ON CONFLICT(guild_id, user_id, position) DO NOTHING
        ''', (guild_id, user_id, position))

        # Also update the active season's highrank stats
        season = await self.get_current_season(guild_id, '6v6')
        if season:
            season_id = season[0]
            await self.db.execute(f'''
                INSERT INTO season_stats_highrank (guild_id, user_id, season_id,
                    defense_specialist_elo, front_spiker_elo, setter_elo, libero_elo,
                    games_played, wins, losses)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 0)
                ON CONFLICT(guild_id, user_id, season_id) DO NOTHING
            ''', (guild_id, user_id, season_id, starting_elo, starting_elo, starting_elo, starting_elo))
            await self.db.execute(f'''
                UPDATE season_stats_highrank
                SET {position_column} = ?
                WHERE guild_id = ? AND user_id = ? AND season_id = ?
            ''', (new_elo, guild_id, user_id, season_id))

        await self.db.commit()

    async def get_player_stats_highrank(self, guild_id, user_id):
        """Get player's high rank stats (all positions)."""
        async with self.db.execute(
            '''SELECT defense_specialist_elo, front_spiker_elo, setter_elo, libero_elo,
               games_played, wins, losses
               FROM players_highrank WHERE guild_id = ? AND user_id = ?''',
            (guild_id, user_id)
        ) as cursor:
            return await cursor.fetchone()

    async def get_player_season_stats_highrank(self, guild_id, user_id, season_id):
        """Get player's high rank stats for a specific season."""
        async with self.db.execute(
            '''SELECT defense_specialist_elo, front_spiker_elo, setter_elo, libero_elo,
               games_played, wins, losses
               FROM season_stats_highrank WHERE guild_id = ? AND user_id = ? AND season_id = ?''',
            (guild_id, user_id, season_id)
        ) as cursor:
            return await cursor.fetchone()

    async def get_position_games_played_highrank(self, guild_id, user_id, position):
        async with self.db.execute(
            'SELECT games_played FROM position_stats_highrank WHERE guild_id = ? AND user_id = ? AND position = ?',
            (guild_id, user_id, position)
        ) as cursor:
            result = await cursor.fetchone()
            return result[0] if result else 0

    async def get_position_wl_highrank(self, guild_id, user_id, position):
        """Get wins and losses for a specific high rank position"""
        async with self.db.execute(
            'SELECT wins, losses FROM position_stats_highrank WHERE guild_id = ? AND user_id = ? AND position = ?',
            (guild_id, user_id, position)
        ) as cursor:
            result = await cursor.fetchone()
            return (result[0], result[1]) if result else (0, 0)

    async def update_player_elo_highrank(self, guild_id, user_id, position, elo_change, is_winner, starting_elo):
        """Update player's high rank ELO"""
        position_column = position.lower().replace(" ", "_") + "_elo"
        season_id = await self.get_current_season_id(guild_id, '6v6')

        # Update position stats
        await self.db.execute('''
            INSERT INTO position_stats_highrank (guild_id, user_id, position, games_played, wins, losses)
            VALUES (?, ?, ?, 1, ?, ?)
            ON CONFLICT(guild_id, user_id, position)
            DO UPDATE SET
                games_played = games_played + 1,
                wins = wins + ?,
                losses = losses + ?
        ''', (guild_id, user_id, position, 1 if is_winner else 0, 0 if is_winner else 1,
              1 if is_winner else 0, 0 if is_winner else 1))

        # Ensure player exists in highrank table
        async with self.db.execute(
            'SELECT * FROM players_highrank WHERE guild_id = ? AND user_id = ?',
            (guild_id, user_id)
        ) as cursor:
            if not await cursor.fetchone():
                await self.db.execute('''
                    INSERT INTO players_highrank (guild_id, user_id,
                        defense_specialist_elo, front_spiker_elo, setter_elo, libero_elo,
                        games_played, wins, losses)
                    VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0)
                ''', (guild_id, user_id, starting_elo, starting_elo, starting_elo, starting_elo))

        if is_winner:
            await self.db.execute(f'''
                UPDATE players_highrank SET
                    {position_column} = {position_column} + ?,
                    games_played = games_played + 1, wins = wins + 1,
                    win_streak = win_streak + 1, loss_streak = 0,
                    best_win_streak = MAX(best_win_streak, win_streak + 1)
                WHERE guild_id = ? AND user_id = ?
            ''', (elo_change, guild_id, user_id))
        else:
            await self.db.execute(f'''
                UPDATE players_highrank SET
                    {position_column} = {position_column} + ?,
                    games_played = games_played + 1, losses = losses + 1,
                    loss_streak = loss_streak + 1, win_streak = 0,
                    best_loss_streak = MAX(best_loss_streak, loss_streak + 1)
                WHERE guild_id = ? AND user_id = ?
            ''', (elo_change, guild_id, user_id))

        # Season stats for high rank
        if season_id:
            async with self.db.execute(
                'SELECT * FROM season_stats_highrank WHERE guild_id = ? AND user_id = ? AND season_id = ?',
                (guild_id, user_id, season_id)
            ) as cursor:
                if not await cursor.fetchone():
                    await self.db.execute('''
                        INSERT INTO season_stats_highrank (guild_id, user_id, season_id,
                            defense_specialist_elo, front_spiker_elo, setter_elo, libero_elo,
                            games_played, wins, losses)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 0)
                    ''', (guild_id, user_id, season_id, starting_elo, starting_elo, starting_elo, starting_elo))

            if is_winner:
                await self.db.execute(f'''
                    UPDATE season_stats_highrank SET
                        {position_column} = {position_column} + ?,
                        games_played = games_played + 1, wins = wins + 1
                    WHERE guild_id = ? AND user_id = ? AND season_id = ?
                ''', (elo_change, guild_id, user_id, season_id))
            else:
                await self.db.execute(f'''
                    UPDATE season_stats_highrank SET
                        {position_column} = {position_column} + ?,
                        games_played = games_played + 1, losses = losses + 1
                    WHERE guild_id = ? AND user_id = ? AND season_id = ?
                ''', (elo_change, guild_id, user_id, season_id))

    # ──────────────────────────────────────────────
    #  HIGH RANK ELO for 2v2/3v3 (singular MMR, separate from normal)
    # ──────────────────────────────────────────────

    async def get_player_elo_highrank_simple(self, guild_id, user_id, queue_type):
        """Get player's high rank ELO for 2v2 or 3v3"""
        table = f"players_highrank_{queue_type}"
        config = await self.get_config(guild_id)
        starting_elo = config.get("high_rank_starting_elo", config["starting_elo"])
        async with self.db.execute(
            f'SELECT elo FROM {table} WHERE guild_id = ? AND user_id = ?',
            (guild_id, user_id)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else starting_elo

    async def update_player_elo_highrank_simple(self, guild_id, user_id, queue_type, elo_change, is_winner, starting_elo):
        """Update player's high rank ELO for 2v2 or 3v3"""
        table = f"players_highrank_{queue_type}"

        async with self.db.execute(
            f'SELECT * FROM {table} WHERE guild_id = ? AND user_id = ?',
            (guild_id, user_id)
        ) as cursor:
            if not await cursor.fetchone():
                await self.db.execute(f'''
                    INSERT INTO {table} (guild_id, user_id, elo, games_played, wins, losses)
                    VALUES (?, ?, ?, 0, 0, 0)
                ''', (guild_id, user_id, starting_elo))

        if is_winner:
            await self.db.execute(f'''
                UPDATE {table} SET elo = elo + ?, games_played = games_played + 1, wins = wins + 1,
                    win_streak = win_streak + 1, loss_streak = 0,
                    best_win_streak = MAX(best_win_streak, win_streak + 1)
                WHERE guild_id = ? AND user_id = ?
            ''', (elo_change, guild_id, user_id))
        else:
            await self.db.execute(f'''
                UPDATE {table} SET elo = elo + ?, games_played = games_played + 1, losses = losses + 1,
                    loss_streak = loss_streak + 1, win_streak = 0,
                    best_loss_streak = MAX(best_loss_streak, loss_streak + 1)
                WHERE guild_id = ? AND user_id = ?
            ''', (elo_change, guild_id, user_id))

        await self.db.commit()

    async def get_leaderboard_data_highrank_simple(self, guild_id, queue_type, limit=10, offset=0):
        """Get high rank leaderboard data for 2v2 or 3v3"""
        table = f"players_highrank_{queue_type}"
        async with self.db.execute(f'''
            SELECT user_id, elo, games_played, wins
            FROM {table}
            WHERE guild_id = ? AND games_played > 0
            ORDER BY elo DESC
            LIMIT ? OFFSET ?
        ''', (guild_id, limit, offset)) as cursor:
            return await cursor.fetchall()

    async def get_player_count_highrank_simple(self, guild_id, queue_type):
        """Get player count for high rank 2v2/3v3"""
        table = f"players_highrank_{queue_type}"
        async with self.db.execute(
            f'SELECT COUNT(*) FROM {table} WHERE guild_id = ? AND games_played > 0',
            (guild_id,)
        ) as cursor:
            return (await cursor.fetchone())[0]

    async def get_player_average_elo(self, guild_id, user_id):
        """Get player's average 6v6 ELO (across played or admin-set positions)"""
        stats = await self.get_player_stats(guild_id, user_id)
        if not stats:
            config = await self.get_config(guild_id)
            return config["starting_elo"]

        ds_elo, fs_elo, s_elo, l_elo, games, wins, losses = stats
        config = await self.get_config(guild_id)
        starting_elo = config["starting_elo"]

        played_elos = []
        for pos_name, elo in [("Defense Specialist", ds_elo), ("Front Spiker", fs_elo),
                               ("Setter", s_elo), ("Libero", l_elo)]:
            pg = await self.get_position_games_played(guild_id, user_id, pos_name)
            if pg > 0 or elo != starting_elo:
                played_elos.append(elo)

        return sum(played_elos) / len(played_elos) if played_elos else starting_elo

    # Region methods
    async def set_player_region(self, guild_id, user_id, region):
        """Set a player's region"""
        await self.db.execute(
            'INSERT OR REPLACE INTO player_regions (guild_id, user_id, region) VALUES (?, ?, ?)',
            (guild_id, user_id, region)
        )
        await self.db.commit()

    async def get_player_region(self, guild_id, user_id):
        """Get a player's region"""
        async with self.db.execute(
            'SELECT region FROM player_regions WHERE guild_id = ? AND user_id = ?',
            (guild_id, user_id)
        ) as cursor:
            result = await cursor.fetchone()
            return result[0] if result else None

    async def remove_player_region(self, guild_id, user_id):
        """Remove a player's region"""
        await self.db.execute(
            'DELETE FROM player_regions WHERE guild_id = ? AND user_id = ?',
            (guild_id, user_id)
        )
        await self.db.commit()

    async def get_regional_leaderboard_data(self, guild_id, region, position=None, limit=10, offset=0, season_id=None):
        """Get leaderboard data filtered by region"""
        if season_id is None:
            if position is None:
                async with self.db.execute('''
                    SELECT p.user_id,
                           COALESCE(
                               (SELECT AVG(
                                   CASE ps.position
                                       WHEN 'Defense Specialist' THEN p.defense_specialist_elo
                                       WHEN 'Front Spiker' THEN p.front_spiker_elo
                                       WHEN 'Setter' THEN p.setter_elo
                                       WHEN 'Libero' THEN p.libero_elo
                                   END
                               ) FROM position_stats ps
                               WHERE ps.guild_id = p.guild_id AND ps.user_id = p.user_id),
                               (p.defense_specialist_elo + p.front_spiker_elo + p.setter_elo + p.libero_elo) / 4.0
                           ) as avg_elo,
                           p.games_played, p.wins
                    FROM players p
                    INNER JOIN player_regions pr ON p.guild_id = pr.guild_id AND p.user_id = pr.user_id
                    WHERE p.guild_id = ? AND pr.region = ? AND p.games_played > 0
                    ORDER BY avg_elo DESC
                    LIMIT ? OFFSET ?
                ''', (guild_id, region, limit, offset)) as cursor:
                    return await cursor.fetchall()
            else:
                position_column = position.lower().replace(" ", "_") + "_elo"
                async with self.db.execute(f'''
                    SELECT p.user_id, p.{position_column}, p.games_played, p.wins
                    FROM players p
                    INNER JOIN player_regions pr ON p.guild_id = pr.guild_id AND p.user_id = pr.user_id
                    INNER JOIN position_stats ps ON p.guild_id = ps.guild_id AND p.user_id = ps.user_id
                    WHERE p.guild_id = ? AND pr.region = ? AND ps.position = ? AND ps.games_played > 0
                    ORDER BY p.{position_column} DESC
                    LIMIT ? OFFSET ?
                ''', (guild_id, region, position, limit, offset)) as cursor:
                    return await cursor.fetchall()
        else:
            if position is None:
                async with self.db.execute('''
                    SELECT ss.user_id,
                           COALESCE(
                               (SELECT AVG(
                                   CASE sps.position
                                       WHEN 'Defense Specialist' THEN ss.defense_specialist_elo
                                       WHEN 'Front Spiker' THEN ss.front_spiker_elo
                                       WHEN 'Setter' THEN ss.setter_elo
                                       WHEN 'Libero' THEN ss.libero_elo
                                   END
                               ) FROM season_position_stats sps
                               WHERE sps.guild_id = ss.guild_id AND sps.user_id = ss.user_id
                                   AND sps.season_id = ss.season_id),
                               (ss.defense_specialist_elo + ss.front_spiker_elo + ss.setter_elo + ss.libero_elo) / 4.0
                           ) as avg_elo,
                           ss.games_played, ss.wins
                    FROM season_stats ss
                    INNER JOIN player_regions pr ON ss.guild_id = pr.guild_id AND ss.user_id = pr.user_id
                    WHERE ss.guild_id = ? AND ss.season_id = ? AND pr.region = ? AND ss.games_played > 0
                    ORDER BY avg_elo DESC
                    LIMIT ? OFFSET ?
                ''', (guild_id, season_id, region, limit, offset)) as cursor:
                    return await cursor.fetchall()
            else:
                position_column = position.lower().replace(" ", "_") + "_elo"
                async with self.db.execute(f'''
                    SELECT ss.user_id, ss.{position_column}, ss.games_played, ss.wins
                    FROM season_stats ss
                    INNER JOIN player_regions pr ON ss.guild_id = pr.guild_id AND ss.user_id = pr.user_id
                    INNER JOIN season_position_stats sps ON ss.guild_id = sps.guild_id
                        AND ss.user_id = sps.user_id AND ss.season_id = sps.season_id
                    WHERE ss.guild_id = ? AND ss.season_id = ? AND pr.region = ? AND sps.position = ? AND sps.games_played > 0
                    ORDER BY ss.{position_column} DESC
                    LIMIT ? OFFSET ?
                ''', (guild_id, season_id, region, position, limit, offset)) as cursor:
                    return await cursor.fetchall()

    async def get_regional_player_count(self, guild_id, region, season_id=None):
        """Get count of players in a specific region"""
        if season_id is None:
            async with self.db.execute('''
                SELECT COUNT(*) FROM players p
                INNER JOIN player_regions pr ON p.guild_id = pr.guild_id AND p.user_id = pr.user_id
                WHERE p.guild_id = ? AND pr.region = ? AND p.games_played > 0
            ''', (guild_id, region)) as cursor:
                return (await cursor.fetchone())[0]
        else:
            async with self.db.execute('''
                SELECT COUNT(*) FROM season_stats ss
                INNER JOIN player_regions pr ON ss.guild_id = pr.guild_id AND ss.user_id = pr.user_id
                WHERE ss.guild_id = ? AND ss.season_id = ? AND pr.region = ? AND ss.games_played > 0
            ''', (guild_id, season_id, region)) as cursor:
                return (await cursor.fetchone())[0]

    # ──────────────────────────────────────────────
    #  HIGH RANK 6v6 LEADERBOARD (per-position)
    # ──────────────────────────────────────────────

    async def get_leaderboard_data_highrank(self, guild_id, position=None, limit=10, offset=0):
        """Get high rank 6v6 leaderboard data (per-position or average)."""
        if position is None:
            async with self.db.execute('''
                SELECT p.user_id,
                       COALESCE(
                           (SELECT AVG(
                               CASE ps.position
                                   WHEN 'Defense Specialist' THEN p.defense_specialist_elo
                                   WHEN 'Front Spiker' THEN p.front_spiker_elo
                                   WHEN 'Setter' THEN p.setter_elo
                                   WHEN 'Libero' THEN p.libero_elo
                               END
                           ) FROM position_stats_highrank ps
                           WHERE ps.guild_id = p.guild_id AND ps.user_id = p.user_id),
                           (p.defense_specialist_elo + p.front_spiker_elo + p.setter_elo + p.libero_elo) / 4.0
                       ) as avg_elo,
                       p.games_played, p.wins
                FROM players_highrank p
                WHERE p.guild_id = ? AND p.games_played > 0
                ORDER BY avg_elo DESC
                LIMIT ? OFFSET ?
            ''', (guild_id, limit, offset)) as cursor:
                return await cursor.fetchall()
        else:
            position_column = position.lower().replace(" ", "_") + "_elo"
            async with self.db.execute(f'''
                SELECT p.user_id, p.{position_column}, p.games_played, p.wins
                FROM players_highrank p
                INNER JOIN position_stats_highrank ps ON p.guild_id = ps.guild_id AND p.user_id = ps.user_id
                WHERE p.guild_id = ? AND ps.position = ? AND ps.games_played > 0
                ORDER BY p.{position_column} DESC
                LIMIT ? OFFSET ?
            ''', (guild_id, position, limit, offset)) as cursor:
                return await cursor.fetchall()

    async def get_player_count_highrank(self, guild_id):
        """Get the number of high rank 6v6 players with games."""
        async with self.db.execute(
            'SELECT COUNT(*) FROM players_highrank WHERE guild_id = ? AND games_played > 0',
            (guild_id,)
        ) as cursor:
            return (await cursor.fetchone())[0]

    # ──────────────────────────────────────────────
    #  MATCH MANAGEMENT HELPERS
    # ──────────────────────────────────────────────

    async def get_full_match(self, match_id, guild_id):
        """Get full match data including scores, timestamps, etc."""
        async with self.db.execute(
            '''SELECT id, team1_players, team2_players, team1_score, team2_score,
                      timestamp, season_id, text_channel_id, voice_channel_id, is_active, match_type
               FROM matches WHERE id = ? AND guild_id = ?''',
            (match_id, guild_id)
        ) as cursor:
            return await cursor.fetchone()

    async def delete_match(self, match_id, guild_id):
        """Delete a match entirely from the database."""
        await self.db.execute(
            'DELETE FROM matches WHERE id = ? AND guild_id = ?',
            (match_id, guild_id)
        )
        await self.db.commit()

    async def get_recent_matches_all(self, guild_id, limit=20):
        """Get recent matches with full data for admin match browser."""
        async with self.db.execute(
            '''SELECT id, team1_players, team2_players, team1_score, team2_score,
                      timestamp, is_active, match_type
               FROM matches WHERE guild_id = ?
               ORDER BY id DESC
               LIMIT ?''',
            (guild_id, limit)
        ) as cursor:
            return await cursor.fetchall()

    async def get_regional_stats_leaderboard(self, guild_id, region, position, stat_type, limit=10, offset=0, season_id=None):
        """Get stats leaderboard filtered by region"""
        table = "players" if season_id is None else "season_stats"
        season_clause = "" if season_id is None else f" AND {table[0]}s.season_id = {season_id}" if season_id else ""

        # Simplified: reuse logic from get_stats_leaderboard but with region join
        if position != "all":
            pos_table = "position_stats" if season_id is None else "season_position_stats"
            season_pos_clause = "" if season_id is None else f" AND ps.season_id = {season_id}"

            stat_column_map = {
                "wins": ("ps.wins", "ps.wins DESC, ps.games_played ASC"),
                "losses": ("ps.losses", "ps.losses DESC, ps.games_played DESC"),
                "winrate": ("CASE WHEN ps.games_played > 0 THEN CAST(ps.wins AS REAL) / ps.games_played * 100 ELSE 0 END", "value DESC, ps.games_played DESC"),
                "games": ("ps.games_played", "ps.games_played DESC"),
            }
            value_expr, order_clause = stat_column_map.get(stat_type, ("ps.wins", "ps.wins DESC"))

            query = f'''
                SELECT ps.user_id, {value_expr} as value, ps.games_played, ps.wins, ps.losses
                FROM {pos_table} ps
                INNER JOIN player_regions pr ON ps.guild_id = pr.guild_id AND ps.user_id = pr.user_id
                WHERE ps.guild_id = ? AND ps.position = ? AND pr.region = ? AND ps.games_played > 0 {season_pos_clause}
                ORDER BY {order_clause}
                LIMIT ? OFFSET ?
            '''
            params = (guild_id, position, region, limit, offset)
        else:
            stat_column_map = {
                "wins": ("t.wins", "t.wins DESC, t.games_played ASC"),
                "losses": ("t.losses", "t.losses DESC, t.games_played DESC"),
                "winrate": ("CASE WHEN t.games_played > 0 THEN CAST(t.wins AS REAL) / t.games_played * 100 ELSE 0 END", "value DESC, t.games_played DESC"),
                "games": ("t.games_played", "t.games_played DESC"),
            }
            value_expr, order_clause = stat_column_map.get(stat_type, ("t.wins", "t.wins DESC"))
            season_t_clause = "" if season_id is None else f" AND t.season_id = {season_id}"

            query = f'''
                SELECT t.user_id, {value_expr} as value, t.games_played, t.wins, t.losses
                FROM {table} t
                INNER JOIN player_regions pr ON t.guild_id = pr.guild_id AND t.user_id = pr.user_id
                WHERE t.guild_id = ? AND pr.region = ? AND t.games_played > 0 {season_t_clause}
                ORDER BY {order_clause}
                LIMIT ? OFFSET ?
            '''
            params = (guild_id, region, limit, offset)

        async with self.db.execute(query, params) as cursor:
            return await cursor.fetchall()

    # ──────────────────────────────────────────────
    #  STREAK METHODS
    # ──────────────────────────────────────────────

    async def get_player_streaks(self, guild_id, user_id, queue_type='6v6'):
        """Get a player's current and best streaks. Returns (win_streak, loss_streak, best_win_streak, best_loss_streak)."""
        if queue_type == '6v6':
            table = 'players'
        elif queue_type in ('2v2', '3v3', 'highrank_2v2', 'highrank_3v3'):
            table = f'players_{queue_type}'
        elif queue_type == 'highrank':
            table = 'players_highrank'
        else:
            table = 'players'

        async with self.db.execute(
            f'SELECT win_streak, loss_streak, best_win_streak, best_loss_streak FROM {table} WHERE guild_id = ? AND user_id = ?',
            (guild_id, user_id)
        ) as cursor:
            row = await cursor.fetchone()
            return row if row else (0, 0, 0, 0)

    async def set_player_streaks(self, guild_id, user_id, queue_type, win_streak, loss_streak, best_win_streak=None, best_loss_streak=None):
        """Directly set a player's streak values."""
        if queue_type == '6v6':
            table = 'players'
        elif queue_type in ('2v2', '3v3', 'highrank_2v2', 'highrank_3v3'):
            table = f'players_{queue_type}'
        elif queue_type == 'highrank':
            table = 'players_highrank'
        else:
            table = 'players'

        if best_win_streak is not None and best_loss_streak is not None:
            await self.db.execute(f'''
                UPDATE {table} SET win_streak = ?, loss_streak = ?, best_win_streak = ?, best_loss_streak = ?
                WHERE guild_id = ? AND user_id = ?
            ''', (win_streak, loss_streak, best_win_streak, best_loss_streak, guild_id, user_id))
        else:
            await self.db.execute(f'''
                UPDATE {table} SET win_streak = ?, loss_streak = ?
                WHERE guild_id = ? AND user_id = ?
            ''', (win_streak, loss_streak, guild_id, user_id))
        await self.db.commit()

    async def get_streak_leaderboard(self, guild_id, queue_type='6v6', streak_type='win', limit=10, offset=0):
        """Get leaderboard sorted by current streak."""
        if queue_type == '6v6':
            table = 'players'
        elif queue_type in ('2v2', '3v3', 'highrank_2v2', 'highrank_3v3'):
            table = f'players_{queue_type}'
        elif queue_type == 'highrank':
            table = 'players_highrank'
        else:
            table = 'players'

        col = 'win_streak' if streak_type == 'win' else 'loss_streak'
        async with self.db.execute(f'''
            SELECT user_id, {col}, games_played, wins, losses
            FROM {table}
            WHERE guild_id = ? AND games_played > 0 AND {col} > 0
            ORDER BY {col} DESC
            LIMIT ? OFFSET ?
        ''', (guild_id, limit, offset)) as cursor:
            return await cursor.fetchall()

    # ──────────────────────────────────────────────
    #  ELO ROLE MAPPINGS (with queue_type)
    # ──────────────────────────────────────────────

    async def add_elo_role_mapping_v2(self, guild_id, queue_type, position, elo_threshold, role_id):
        """Add an ELO-based role mapping with queue type support."""
        await self.db.execute(
            'INSERT OR REPLACE INTO elo_role_mappings (guild_id, position, elo_threshold, role_id, queue_type) VALUES (?, ?, ?, ?, ?)',
            (guild_id, position, elo_threshold, role_id, queue_type)
        )
        await self.db.commit()

    async def get_all_elo_role_mappings_v2(self, guild_id):
        """Get all ELO role mappings including queue_type."""
        async with self.db.execute(
            "SELECT position, elo_threshold, role_id, COALESCE(queue_type, '6v6') FROM elo_role_mappings WHERE guild_id = ? ORDER BY queue_type, position, elo_threshold",
            (guild_id,)
        ) as cursor:
            return await cursor.fetchall()

    async def remove_elo_role_mapping_v2(self, guild_id, queue_type, position, elo_threshold):
        """Remove an ELO-based role mapping with queue type."""
        result = await self.db.execute(
            "DELETE FROM elo_role_mappings WHERE guild_id = ? AND position = ? AND elo_threshold = ? AND COALESCE(queue_type, '6v6') = ?",
            (guild_id, position, elo_threshold, queue_type)
        )
        await self.db.commit()
        return result.rowcount > 0

    # ──────────────────────────────────────────────
    #  AFK TIMER (queue timestamps)
    # ──────────────────────────────────────────────

    async def get_afk_queue_entries(self, guild_id, max_age_seconds):
        """Get queue entries older than max_age_seconds."""
        async with self.db.execute(
            "SELECT user_id, position, queue_type FROM queue WHERE guild_id = ? AND timestamp < datetime('now', ?)",
            (guild_id, f'-{max_age_seconds} seconds')
        ) as cursor:
            return await cursor.fetchall()

    async def refresh_queue_timestamp(self, guild_id, user_id):
        """Refresh a player's queue timestamp (when they interact)."""
        await self.db.execute(
            'UPDATE queue SET timestamp = CURRENT_TIMESTAMP WHERE guild_id = ? AND user_id = ?',
            (guild_id, user_id)
        )
        await self.db.commit()

    # ──────────────────────────────────────────────
    #  PER-REGION ELO
    # ──────────────────────────────────────────────

    async def get_player_regional_elo(self, guild_id, user_id, region, position, starting_elo=650):
        """Get a player's ELO for a specific region and position (6v6)."""
        position_column = position.lower().replace(" ", "_") + "_elo"
        async with self.db.execute(
            f'SELECT {position_column} FROM players_regional WHERE guild_id = ? AND user_id = ? AND region = ?',
            (guild_id, user_id, region)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else starting_elo

    async def get_player_regional_elo_simple(self, guild_id, user_id, region, queue_type, starting_elo=650):
        """Get a player's ELO for a specific region (2v2/3v3)."""
        table = f'players_regional_{queue_type}'
        async with self.db.execute(
            f'SELECT elo FROM {table} WHERE guild_id = ? AND user_id = ? AND region = ?',
            (guild_id, user_id, region)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else starting_elo

    async def get_player_regional_stats(self, guild_id, user_id, region):
        """Get a player's full regional 6v6 stats."""
        async with self.db.execute(
            'SELECT defense_specialist_elo, front_spiker_elo, setter_elo, libero_elo, games_played, wins, losses, win_streak, loss_streak, best_win_streak, best_loss_streak FROM players_regional WHERE guild_id = ? AND user_id = ? AND region = ?',
            (guild_id, user_id, region)
        ) as cursor:
            return await cursor.fetchone()

    async def get_player_regional_stats_simple(self, guild_id, user_id, region, queue_type):
        """Get a player's regional stats for 2v2/3v3 (elo, games, wins, losses)."""
        table = f'players_regional_{queue_type}'
        async with self.db.execute(
            f'SELECT elo, games_played, wins, losses FROM {table} WHERE guild_id = ? AND user_id = ? AND region = ?',
            (guild_id, user_id, region)
        ) as cursor:
            return await cursor.fetchone()

    async def update_player_regional_elo(self, guild_id, user_id, region, position, elo_change, is_winner, starting_elo):
        """Update a player's regional ELO (6v6 position-based)."""
        position_column = position.lower().replace(" ", "_") + "_elo"

        # Ensure player record exists
        async with self.db.execute(
            'SELECT 1 FROM players_regional WHERE guild_id = ? AND user_id = ? AND region = ?',
            (guild_id, user_id, region)
        ) as cursor:
            exists = await cursor.fetchone() is not None

        if not exists:
            await self.db.execute('''
                INSERT INTO players_regional (guild_id, user_id, region,
                    defense_specialist_elo, front_spiker_elo, setter_elo, libero_elo,
                    games_played, wins, losses)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 0)
            ''', (guild_id, user_id, region, starting_elo, starting_elo, starting_elo, starting_elo))

        if is_winner:
            await self.db.execute(f'''
                UPDATE players_regional SET
                    {position_column} = {position_column} + ?,
                    games_played = games_played + 1, wins = wins + 1,
                    win_streak = win_streak + 1, loss_streak = 0,
                    best_win_streak = MAX(best_win_streak, win_streak + 1)
                WHERE guild_id = ? AND user_id = ? AND region = ?
            ''', (elo_change, guild_id, user_id, region))
        else:
            await self.db.execute(f'''
                UPDATE players_regional SET
                    {position_column} = {position_column} + ?,
                    games_played = games_played + 1, losses = losses + 1,
                    loss_streak = loss_streak + 1, win_streak = 0,
                    best_loss_streak = MAX(best_loss_streak, loss_streak + 1)
                WHERE guild_id = ? AND user_id = ? AND region = ?
            ''', (elo_change, guild_id, user_id, region))
        await self.db.commit()

    async def update_player_regional_elo_simple(self, guild_id, user_id, region, queue_type, elo_change, is_winner, starting_elo):
        """Update a player's regional ELO (2v2/3v3 simple)."""
        table = f'players_regional_{queue_type}'

        async with self.db.execute(
            f'SELECT 1 FROM {table} WHERE guild_id = ? AND user_id = ? AND region = ?',
            (guild_id, user_id, region)
        ) as cursor:
            exists = await cursor.fetchone() is not None

        if not exists:
            await self.db.execute(f'''
                INSERT INTO {table} (guild_id, user_id, region, elo, games_played, wins, losses)
                VALUES (?, ?, ?, ?, 0, 0, 0)
            ''', (guild_id, user_id, region, starting_elo))

        if is_winner:
            await self.db.execute(f'''
                UPDATE {table} SET elo = elo + ?, games_played = games_played + 1, wins = wins + 1,
                    win_streak = win_streak + 1, loss_streak = 0,
                    best_win_streak = MAX(best_win_streak, win_streak + 1)
                WHERE guild_id = ? AND user_id = ? AND region = ?
            ''', (elo_change, guild_id, user_id, region))
        else:
            await self.db.execute(f'''
                UPDATE {table} SET elo = elo + ?, games_played = games_played + 1, losses = losses + 1,
                    loss_streak = loss_streak + 1, win_streak = 0,
                    best_loss_streak = MAX(best_loss_streak, loss_streak + 1)
                WHERE guild_id = ? AND user_id = ? AND region = ?
            ''', (elo_change, guild_id, user_id, region))
        await self.db.commit()

    async def get_player_regional_average_elo(self, guild_id, user_id, region, starting_elo=650):
        """Get a player's average ELO across all positions for a specific region."""
        async with self.db.execute(
            'SELECT defense_specialist_elo, front_spiker_elo, setter_elo, libero_elo FROM players_regional WHERE guild_id = ? AND user_id = ? AND region = ?',
            (guild_id, user_id, region)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return starting_elo
            return sum(row) / len(row)

    async def get_all_player_regions_with_elo(self, guild_id, user_id):
        """Get all regions a player has ELO data for."""
        regions = {}
        async with self.db.execute(
            'SELECT region, defense_specialist_elo, front_spiker_elo, setter_elo, libero_elo, games_played, wins, losses FROM players_regional WHERE guild_id = ? AND user_id = ?',
            (guild_id, user_id)
        ) as cursor:
            async for row in cursor:
                region, ds, fs, s, l, gp, w, lo = row
                avg = (ds + fs + s + l) / 4
                regions[region] = {
                    'avg_elo': avg, 'games': gp, 'wins': w, 'losses': lo,
                    'ds_elo': ds, 'fs_elo': fs, 's_elo': s, 'l_elo': l
                }
        return regions

    async def set_player_regional_elo(self, guild_id, user_id, region, position, new_elo, starting_elo=650):
        """Directly set a player's regional ELO for a specific position (6v6)."""
        position_column = position.lower().replace(" ", "_") + "_elo"

        # Ensure player record exists
        async with self.db.execute(
            'SELECT 1 FROM players_regional WHERE guild_id = ? AND user_id = ? AND region = ?',
            (guild_id, user_id, region)
        ) as cursor:
            exists = await cursor.fetchone() is not None

        if not exists:
            await self.db.execute('''
                INSERT INTO players_regional (guild_id, user_id, region,
                    defense_specialist_elo, front_spiker_elo, setter_elo, libero_elo,
                    games_played, wins, losses)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 0)
            ''', (guild_id, user_id, region, starting_elo, starting_elo, starting_elo, starting_elo))

        await self.db.execute(f'''
            UPDATE players_regional SET {position_column} = ?
            WHERE guild_id = ? AND user_id = ? AND region = ?
        ''', (new_elo, guild_id, user_id, region))
        await self.db.commit()

    async def set_player_regional_elo_simple(self, guild_id, user_id, region, queue_type, new_elo, starting_elo=650):
        """Directly set a player's regional ELO for 2v2/3v3."""
        table = f'players_regional_{queue_type}'

        async with self.db.execute(
            f'SELECT 1 FROM {table} WHERE guild_id = ? AND user_id = ? AND region = ?',
            (guild_id, user_id, region)
        ) as cursor:
            exists = await cursor.fetchone() is not None

        if not exists:
            await self.db.execute(f'''
                INSERT INTO {table} (guild_id, user_id, region, elo, games_played, wins, losses)
                VALUES (?, ?, ?, ?, 0, 0, 0)
            ''', (guild_id, user_id, region, starting_elo))

        await self.db.execute(f'''
            UPDATE {table} SET elo = ?
            WHERE guild_id = ? AND user_id = ? AND region = ?
        ''', (new_elo, guild_id, user_id, region))
        await self.db.commit()

    # ── ELO History Methods ──

    async def record_elo_history(self, guild_id, user_id, match_id, queue_type, position, elo_before, elo_after, elo_change, is_winner):
        """Record an ELO change for the rating history graph."""
        await self.db.execute('''
            INSERT INTO elo_history (guild_id, user_id, match_id, queue_type, position, elo_before, elo_after, elo_change, is_winner)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (guild_id, user_id, match_id, queue_type, position, elo_before, elo_after, elo_change, 1 if is_winner else 0))
        await self.db.commit()

    async def get_elo_history(self, guild_id, user_id, queue_type=None, limit=50, latest=False, season_id=None):
        """Get ELO history for a player, optionally filtered by queue type and season.
        If latest=True, returns the most recent `limit` entries in chronological order.
        If season_id is provided, filters history to the season's date range.
        """
        order = "DESC" if latest else "ASC"

        # Build season date filter if needed
        season_filter = ""
        params = [guild_id, user_id]

        if season_id:
            season_filter = " AND timestamp >= (SELECT start_date FROM seasons WHERE id = ?) AND (timestamp <= (SELECT COALESCE(end_date, datetime('now')) FROM seasons WHERE id = ?))"
            params.extend([season_id, season_id])

        if queue_type:
            params.append(queue_type)
            params.append(limit)
            async with self.db.execute(f'''
                SELECT match_id, queue_type, position, elo_before, elo_after, elo_change, is_winner, timestamp
                FROM elo_history
                WHERE guild_id = ? AND user_id = ?{season_filter} AND queue_type = ?
                ORDER BY timestamp {order}
                LIMIT ?
            ''', tuple(params)) as cursor:
                rows = await cursor.fetchall()
        else:
            params.append(limit)
            async with self.db.execute(f'''
                SELECT match_id, queue_type, position, elo_before, elo_after, elo_change, is_winner, timestamp
                FROM elo_history
                WHERE guild_id = ? AND user_id = ?{season_filter}
                ORDER BY timestamp {order}
                LIMIT ?
            ''', tuple(params)) as cursor:
                rows = await cursor.fetchall()
        # When fetching latest, reverse to return in chronological order
        if latest:
            rows = list(reversed(rows))
        return rows

    def _avg_elo_subquery(self, table_alias, pos_stats_table):
        """Build a SQL subquery that computes avg ELO over played/set positions only."""
        return f'''COALESCE(
            (SELECT AVG(
                CASE ps.position
                    WHEN 'Defense Specialist' THEN {table_alias}.defense_specialist_elo
                    WHEN 'Front Spiker' THEN {table_alias}.front_spiker_elo
                    WHEN 'Setter' THEN {table_alias}.setter_elo
                    WHEN 'Libero' THEN {table_alias}.libero_elo
                END
            ) FROM {pos_stats_table} ps
            WHERE ps.guild_id = {table_alias}.guild_id AND ps.user_id = {table_alias}.user_id),
            ({table_alias}.defense_specialist_elo + {table_alias}.front_spiker_elo + {table_alias}.setter_elo + {table_alias}.libero_elo) / 4.0
        )'''

    async def get_player_rank(self, guild_id, user_id, queue_type='6v6'):
        """Get a player's rank position and total player count for a queue type."""
        if queue_type == '6v6':
            avg_sql = self._avg_elo_subquery('p', 'position_stats')
            async with self.db.execute(f'''
                SELECT COUNT(*) + 1 FROM players p
                WHERE p.guild_id = ? AND p.games_played > 0
                AND {avg_sql} > (
                    SELECT {self._avg_elo_subquery('p2', 'position_stats')}
                    FROM players p2 WHERE p2.guild_id = ? AND p2.user_id = ?
                )
            ''', (guild_id, guild_id, user_id)) as cursor:
                rank = (await cursor.fetchone())[0]
            total = await self.get_player_count(guild_id)
            return rank, total
        elif queue_type in ('2v2', '3v3', 'highrank_2v2', 'highrank_3v3'):
            table = {
                '2v2': 'players_2v2', '3v3': 'players_3v3',
                'highrank_2v2': 'players_highrank_2v2', 'highrank_3v3': 'players_highrank_3v3'
            }[queue_type]
            async with self.db.execute(f'''
                SELECT COUNT(*) + 1 FROM {table}
                WHERE guild_id = ? AND games_played > 0
                AND elo > (SELECT elo FROM {table} WHERE guild_id = ? AND user_id = ?)
            ''', (guild_id, guild_id, user_id)) as cursor:
                rank = (await cursor.fetchone())[0]
            async with self.db.execute(f'SELECT COUNT(*) FROM {table} WHERE guild_id = ? AND games_played > 0', (guild_id,)) as cursor:
                total = (await cursor.fetchone())[0]
            return rank, total
        elif queue_type == 'highrank':
            avg_sql = self._avg_elo_subquery('p', 'position_stats_highrank')
            async with self.db.execute(f'''
                SELECT COUNT(*) + 1 FROM players_highrank p
                WHERE p.guild_id = ? AND p.games_played > 0
                AND {avg_sql} > (
                    SELECT {self._avg_elo_subquery('p2', 'position_stats_highrank')}
                    FROM players_highrank p2 WHERE p2.guild_id = ? AND p2.user_id = ?
                )
            ''', (guild_id, guild_id, user_id)) as cursor:
                rank = (await cursor.fetchone())[0]
            total = await self.get_player_count_highrank(guild_id)
            return rank, total
        return 0, 0