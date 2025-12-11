import os
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager

DATABASE_URL = os.environ.get('DATABASE_URL')

@contextmanager
def get_db():
    """Context manager for database connections"""
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    """Initialize database schema"""
    with get_db() as conn:
        cur = conn.cursor()

        # Users table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # Magic link tokens
        cur.execute("""
            CREATE TABLE IF NOT EXISTS auth_tokens (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) NOT NULL,
                token VARCHAR(64) UNIQUE NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                used BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # View history
        cur.execute("""
            CREATE TABLE IF NOT EXISTS view_history (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                video_id VARCHAR(20) NOT NULL,
                title VARCHAR(500),
                channel VARCHAR(255),
                duration INTEGER,
                viewed_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # Stream URL cache
        cur.execute("""
            CREATE TABLE IF NOT EXISTS stream_cache (
                video_id VARCHAR(20) PRIMARY KEY,
                audio_url TEXT NOT NULL,
                cached_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # Create indexes
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_history_user
            ON view_history(user_id, viewed_at DESC)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_tokens_lookup
            ON auth_tokens(token, expires_at)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_cache_age
            ON stream_cache(cached_at)
        """)

# User operations
def get_or_create_user(email):
    """Get existing user or create new one"""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, email FROM users WHERE email = %s", (email,))
        user = cur.fetchone()
        if user:
            return dict(user)

        cur.execute(
            "INSERT INTO users (email) VALUES (%s) RETURNING id, email",
            (email,)
        )
        return dict(cur.fetchone())

def get_user_by_id(user_id):
    """Get user by ID"""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, email, created_at FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        return dict(row) if row else None

# Token operations
def create_auth_token(email, token, expires_at):
    """Store a magic link token"""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO auth_tokens (email, token, expires_at) VALUES (%s, %s, %s)",
            (email, token, expires_at)
        )

def verify_auth_token(token):
    """Verify and consume a magic link token"""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT email FROM auth_tokens
            WHERE token = %s AND expires_at > NOW() AND used = FALSE
        """, (token,))
        row = cur.fetchone()

        if row:
            cur.execute("UPDATE auth_tokens SET used = TRUE WHERE token = %s", (token,))
            return row['email']
        return None

def cleanup_expired_tokens():
    """Remove expired tokens"""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM auth_tokens WHERE expires_at < NOW() OR used = TRUE")

# History operations
def add_to_history(user_id, video_id, title, channel, duration):
    """Add a video to user's history"""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO view_history (user_id, video_id, title, channel, duration)
            VALUES (%s, %s, %s, %s, %s)
        """, (user_id, video_id, title, channel, duration))

def get_user_history(user_id, limit=50):
    """Get user's view history"""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT video_id, title, channel, duration, viewed_at
            FROM view_history
            WHERE user_id = %s
            ORDER BY viewed_at DESC
            LIMIT %s
        """, (user_id, limit))
        return [dict(row) for row in cur.fetchall()]

# Cache operations
def get_cached_stream(video_id, max_age_hours=4):
    """Get cached stream URL if fresh"""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT audio_url FROM stream_cache
            WHERE video_id = %s
            AND cached_at > NOW() - INTERVAL '%s hours'
        """, (video_id, max_age_hours))
        row = cur.fetchone()
        return row['audio_url'] if row else None

def cache_stream(video_id, audio_url):
    """Cache a stream URL"""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO stream_cache (video_id, audio_url, cached_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (video_id) DO UPDATE SET audio_url = %s, cached_at = NOW()
        """, (video_id, audio_url, audio_url))

def cleanup_old_cache(max_age_hours=6):
    """Remove old cache entries"""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            DELETE FROM stream_cache
            WHERE cached_at < NOW() - INTERVAL '%s hours'
        """, (max_age_hours,))
