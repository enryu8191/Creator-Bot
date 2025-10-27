import aiosqlite
import asyncio
from typing import Optional

class Database:
    def __init__(self, db_path: str = "engagement.db"):
        self.db_path = db_path

    async def connect(self):
        """Initialize database connection and create tables"""
        self.conn = await aiosqlite.connect(self.db_path)
        await self.create_tables()

    async def create_tables(self):
        """Create necessary database tables"""
        # Users table - tracks creator information
        await self.conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            total_points INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # Sessions table - tracks engagement sessions
        await self.conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            link TEXT NOT NULL,
            message_id INTEGER,
            submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            engaged BOOLEAN DEFAULT FALSE,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
        """)

        # Engagement table - tracks who engaged with whom
        await self.conn.execute("""
        CREATE TABLE IF NOT EXISTS engagements (
            engagement_id INTEGER PRIMARY KEY AUTOINCREMENT,
            engager_id INTEGER NOT NULL,
            target_session_id INTEGER NOT NULL,
            engaged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (engager_id) REFERENCES users (user_id),
            FOREIGN KEY (target_session_id) REFERENCES sessions (session_id)
        )
        """)
        await self.conn.commit()
        # Ensure sessions has channel_id column for multi-channel support
        try:
            await self.conn.execute("ALTER TABLE sessions ADD COLUMN channel_id INTEGER")
            await self.conn.commit()
        except Exception:
            # Column likely already exists; ignore
            pass

        # Config table - simple key/value store for runtime configuration
        await self.conn.execute("""
        CREATE TABLE IF NOT EXISTS configs (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """)
        await self.conn.commit()
    async def add_user(self, user_id: int, username: str):
        """Add a new user or update existing username"""
        await self.conn.execute("""
        INSERT INTO users (user_id, username)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET username=excluded.username
        """, (user_id, username))
        await self.conn.commit()

    async def add_session(self, user_id: int, link: str, message_id: int, channel_id: int):
        """Create a new engagement session"""
        cursor = await self.conn.execute("""
        INSERT INTO sessions (user_id, link, message_id, channel_id)
        VALUES (?, ?, ?, ?)
        """, (user_id, link, message_id, channel_id))
        await self.conn.commit()
        return cursor.lastrowid

    async def get_active_session(self, user_id: int) -> Optional[dict]:
        """Get user's current active session"""
        cursor = await self.conn.execute("""
        SELECT session_id, link, message_id, engaged, user_id, channel_id
        FROM sessions
        WHERE user_id = ?
        ORDER BY submitted_at DESC
        LIMIT 1
        """, (user_id,))
        row = await cursor.fetchone()
        if row:
            return {
                "session_id": row[0],
                "link": row[1],
                "message_id": row[2],
                "engaged": bool(row[3]),
                "user_id": row[4],
                "channel_id": row[5]
            }
        return None
    async def mark_engaged(self, user_id: int):
        """Mark user as having completed engagement"""
        await self.conn.execute("""
        UPDATE sessions
        SET engaged = TRUE
        WHERE user_id = ? AND session_id = (
            SELECT session_id FROM sessions
            WHERE user_id = ?
            ORDER BY submitted_at DESC
            LIMIT 1
        )
        """, (user_id, user_id))
        await self.conn.commit()

    async def has_engaged(self, engager_id: int, target_session_id: int) -> bool:
        """Check if user has already engaged with this session"""
        cursor = await self.conn.execute("""
        SELECT COUNT(*) FROM engagements
        WHERE engager_id = ? AND target_session_id = ?
        """, (engager_id, target_session_id))
        count = await cursor.fetchone()
        return count[0] > 0

    async def add_engagement(self, engager_id: int, target_session_id: int) -> bool:
        """Record an engagement action if it doesn't exist already"""
        if await self.has_engaged(engager_id, target_session_id):
            return False
            
        await self.conn.execute("""
        INSERT INTO engagements (engager_id, target_session_id)
        VALUES (?, ?)
        """, (engager_id, target_session_id))
        await self.conn.commit()
        return True

    async def add_point(self, user_id: int):
        """Add a point to user's total"""
        await self.conn.execute("""
        UPDATE users
        SET total_points = total_points + 1
        WHERE user_id = ?
        """, (user_id,))
        await self.conn.commit()

    async def get_leaderboard(self, limit: int = 10):
        """Get top users by points"""
        cursor = await self.conn.execute("""
        SELECT user_id, username, total_points
        FROM users
        ORDER BY total_points DESC
        LIMIT ?
        """, (limit,))
        return await cursor.fetchall()

    async def get_non_engaged_users(self):
        """Get users who have not engaged with every other user's most recent content link."""
        # Get all users with a current session
        cursor = await self.conn.execute('''
            SELECT user_id, session_id FROM (
                SELECT user_id, MAX(session_id) as session_id
                FROM sessions
                GROUP BY user_id
            )
        ''')
        user_sessions = await cursor.fetchall()
        user_ids = [row[0] for row in user_sessions]
        session_map = {row[0]: row[1] for row in user_sessions}

        non_engaged_users = []
        for user_id in user_ids:
            # For each user, check if they have engaged with every other user's most recent session
            missing = False
            for other_id in user_ids:
                if other_id == user_id:
                    continue
                # Check if user_id has engaged with other_id's latest session
                cursor = await self.conn.execute('''
                    SELECT COUNT(*) FROM engagements
                    WHERE engager_id = ? AND target_session_id = ?
                ''', (user_id, session_map[other_id]))
                count = await cursor.fetchone()
                if count[0] == 0:
                    missing = True
                    break
            if missing:
                # Get username
                cursor = await self.conn.execute('SELECT username FROM users WHERE user_id = ?', (user_id,))
                row = await cursor.fetchone()
                username = row[0] if row else str(user_id)
                non_engaged_users.append((user_id, username))
        return non_engaged_users

    async def reset_all_sessions(self):
        """Delete all session data for a fresh start"""
        await self.conn.execute("DELETE FROM sessions")
        await self.conn.execute("DELETE FROM engagements")
        await self.conn.commit()

    async def close(self):
        """Close database connection"""
        await self.conn.close()

    # ---------- Configuration Helpers ----------
    async def set_config(self, key: str, value: str):
        await self.conn.execute(
            """
            INSERT INTO configs (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (key, value),
        )
        await self.conn.commit()

    async def get_config(self, key: str) -> Optional[str]:
        cursor = await self.conn.execute("SELECT value FROM configs WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row[0] if row else None

    async def get_config_int(self, key: str) -> Optional[int]:
        val = await self.get_config(key)
        if val is None:
            return None
        try:
            return int(val)
        except ValueError:
            return None

    async def get_allowed_channel_ids(self) -> Optional[set[int]]:
        val = await self.get_config('allowed_channel_ids')
        if not val:
            return None
        parts = [p.strip() for p in val.split(',') if p.strip()]
        ids: set[int] = set()
        for p in parts:
            try:
                ids.add(int(p))
            except ValueError:
                continue
        return ids if ids else None

    async def set_allowed_channel_ids(self, ids: Optional[set[int]]):
        if not ids:
            # Remove config to indicate "all channels allowed"
            await self.conn.execute("DELETE FROM configs WHERE key = 'allowed_channel_ids'")
            await self.conn.commit()
            return
        csv = ",".join(str(i) for i in sorted(ids))
        await self.set_config('allowed_channel_ids', csv)

    # ---------- Engagement Status Helpers ----------
    async def get_latest_sessions_map(self) -> dict[int, int]:
        """Return mapping of user_id -> latest session_id for all users with at least one session."""
        cursor = await self.conn.execute(
            """
            SELECT user_id, MAX(session_id) AS latest_session
            FROM sessions
            GROUP BY user_id
            """
        )
        rows = await cursor.fetchall()
        return {row[0]: row[1] for row in rows}

    async def get_engagers_for_session(self, session_id: int) -> list[int]:
        """Return list of user_ids who engaged with the given session."""
        cursor = await self.conn.execute(
            """
            SELECT engager_id FROM engagements
            WHERE target_session_id = ?
            ORDER BY engaged_at ASC
            """,
            (session_id,),
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]
