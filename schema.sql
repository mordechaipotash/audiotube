-- AudioTube Database Schema
-- Run this on Railway PostgreSQL if not auto-initialized

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Magic link tokens
CREATE TABLE IF NOT EXISTS auth_tokens (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    token VARCHAR(64) UNIQUE NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    used BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- View history
CREATE TABLE IF NOT EXISTS view_history (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    video_id VARCHAR(20) NOT NULL,
    title VARCHAR(500),
    channel VARCHAR(255),
    duration INTEGER,
    viewed_at TIMESTAMP DEFAULT NOW()
);

-- Stream URL cache
CREATE TABLE IF NOT EXISTS stream_cache (
    video_id VARCHAR(20) PRIMARY KEY,
    audio_url TEXT NOT NULL,
    cached_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_history_user ON view_history(user_id, viewed_at DESC);
CREATE INDEX IF NOT EXISTS idx_tokens_lookup ON auth_tokens(token, expires_at);
CREATE INDEX IF NOT EXISTS idx_cache_age ON stream_cache(cached_at);
