import sqlite3
import time
import logging
from pathlib import Path

_log = logging.getLogger("launcher")

_DEFAULT_DB = str(Path(__file__).parent.parent.parent / 'database' / 'user_database.db')
STARTING_BALANCE = 1000


class DatabaseManager:
    def __init__(self, db_path: str = _DEFAULT_DB, starting_balance: int = STARTING_BALANCE):
        self.db_path = db_path
        self.starting_balance = starting_balance
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_core_tables()

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute('PRAGMA foreign_keys = ON')
        return conn

    def _init_core_tables(self):
        with self._connect() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS casino (
                    user_id     INTEGER PRIMARY KEY,
                    balance     INTEGER NOT NULL DEFAULT 0,
                    total_won   INTEGER DEFAULT 0,
                    total_lost  INTEGER DEFAULT 0,
                    games_played INTEGER DEFAULT 0,
                    last_daily  REAL DEFAULT 0,
                    created_at  REAL DEFAULT (julianday('now'))
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS transactions (
                    transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id        INTEGER,
                    amount         INTEGER,
                    transaction_type TEXT,
                    timestamp      DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES casino (user_id)
                )
            ''')
        _log.info(f"✅ Database initialised: {self.db_path}")

    # ------------------------------------------------------------------ #
    # Extension point — any cog can register its own table               #
    # ------------------------------------------------------------------ #

    def register_table(self, create_sql: str):
        """Call this from a cog's setup() to ensure its table exists.

        Example:
            db_manager.register_table('''
                CREATE TABLE IF NOT EXISTS levels (
                    user_id INTEGER PRIMARY KEY,
                    xp      INTEGER DEFAULT 0
                )
            ''')
        """
        with self._connect() as conn:
            conn.execute(create_sql)

    def execute(self, sql: str, params: tuple = ()) -> list:
        """Run any SQL and return all rows.  Use for custom queries in new cogs."""
        with self._connect() as conn:
            cursor = conn.execute(sql, params)
            return cursor.fetchall()

    # ------------------------------------------------------------------ #
    # Casino / shared currency methods                                    #
    # ------------------------------------------------------------------ #

    def get_user_balance(self, user_id: int) -> int:
        with self._connect() as conn:
            row = conn.execute('SELECT balance FROM casino WHERE user_id = ?', (user_id,)).fetchone()
            if row is None:
                conn.execute(
                    'INSERT INTO casino (user_id, balance) VALUES (?, ?)',
                    (user_id, self.starting_balance)
                )
                return self.starting_balance
            return row[0]

    def update_balance(self, user_id: int, amount: int, won: bool = False):
        self.get_user_balance(user_id)  # ensure the row exists
        with self._connect() as conn:
            if won:
                conn.execute('''
                    UPDATE casino
                    SET balance = balance + ?,
                        total_won = total_won + ?,
                        games_played = games_played + 1
                    WHERE user_id = ?
                ''', (amount, amount, user_id))
            else:
                conn.execute('''
                    UPDATE casino
                    SET balance = balance - ?,
                        total_lost = total_lost + ?,
                        games_played = games_played + 1
                    WHERE user_id = ?
                ''', (amount, amount, user_id))

    def get_user_stats(self, user_id: int) -> dict | None:
        self.get_user_balance(user_id)  # ensure the row exists
        with self._connect() as conn:
            row = conn.execute(
                'SELECT balance, total_won, total_lost, games_played, last_daily FROM casino WHERE user_id = ?',
                (user_id,)
            ).fetchone()
        if row:
            return {
                'balance':      row[0],
                'total_won':    row[1],
                'total_lost':   row[2],
                'games_played': row[3],
                'last_daily':   row[4],
            }
        return None

    def claim_daily_bonus(self, user_id: int, bonus: int = 500, cooldown: int = 86400):
        """Returns (success, seconds_remaining).  bonus/cooldown can be overridden per-cog."""
        self.get_user_balance(user_id)  # ensure the row exists
        with self._connect() as conn:
            last = conn.execute('SELECT last_daily FROM casino WHERE user_id = ?', (user_id,)).fetchone()[0]
            now = time.time()
            elapsed = now - (last or 0)
            if elapsed < cooldown:
                return False, int(cooldown - elapsed)
            conn.execute(
                'UPDATE casino SET balance = balance + ?, last_daily = ? WHERE user_id = ?',
                (bonus, now, user_id)
            )
        return True, 0

    def get_leaderboard(self, count: int = 10) -> list:
        """Returns list of (user_id, balance, games_played) sorted by balance desc."""
        with self._connect() as conn:
            return conn.execute(
                'SELECT user_id, balance, games_played FROM casino ORDER BY balance DESC LIMIT ?',
                (count,)
            ).fetchall()


async def setup(bot):
    pass
