import os
import json
import aiosqlite
from datetime import datetime, date
from typing import Optional

DB_PATH = os.environ.get("LIPPERSHEY_DB", "/data/lippershey.db")


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS preferences (
                date TEXT PRIMARY KEY,
                interests_today TEXT,
                mood TEXT,
                time_budget INTEGER
            );

            CREATE TABLE IF NOT EXISTS feed_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT,
                title TEXT,
                link TEXT,
                summary TEXT,
                published TEXT,
                source_name TEXT,
                category TEXT,
                fetched_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_feed_cache_fetched ON feed_cache(fetched_at);
            CREATE INDEX IF NOT EXISTS idx_feed_cache_category ON feed_cache(category);

            CREATE TABLE IF NOT EXISTS krant_archive (
                date TEXT PRIMARY KEY,
                content_md TEXT,
                content_json TEXT,
                article_count INTEGER
            );

            CREATE TABLE IF NOT EXISTS sources (
                url TEXT PRIMARY KEY,
                name TEXT,
                category TEXT,
                priority_boost REAL DEFAULT 0.0,
                active INTEGER DEFAULT 1
            );
        """)
        await db.commit()


async def save_preferences(date_str: str, interests_today: str, mood: str, time_budget: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO preferences (date, interests_today, mood, time_budget)
               VALUES (?, ?, ?, ?)""",
            (date_str, interests_today, mood, time_budget)
        )
        await db.commit()


async def get_preferences(date_str: Optional[str] = None) -> Optional[dict]:
    if date_str is None:
        date_str = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM preferences WHERE date = ?", (date_str,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def cache_articles(articles: list[dict]):
    if not articles:
        return
    fetched_at = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany(
            """INSERT INTO feed_cache (url, title, link, summary, published, source_name, category, fetched_at)
               VALUES (:url, :title, :link, :summary, :published, :source_name, :category, :fetched_at)""",
            [{**a, "fetched_at": fetched_at} for a in articles]
        )
        await db.commit()


async def get_cached_articles(hours: int = 24, categories: Optional[list[str]] = None) -> list[dict]:
    cutoff = datetime.utcnow().isoformat()
    # Use a simple approach: fetch recent rows, filter in Python for simplicity
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if categories:
            placeholders = ",".join("?" * len(categories))
            async with db.execute(
                f"""SELECT * FROM feed_cache
                    WHERE fetched_at >= datetime('now', '-{int(hours)} hours')
                    AND category IN ({placeholders})
                    ORDER BY fetched_at DESC""",
                categories
            ) as cursor:
                rows = await cursor.fetchall()
        else:
            async with db.execute(
                f"""SELECT * FROM feed_cache
                    WHERE fetched_at >= datetime('now', '-{int(hours)} hours')
                    ORDER BY fetched_at DESC"""
            ) as cursor:
                rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def save_krant(date_str: str, content_md: str, content_json: str, article_count: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO krant_archive (date, content_md, content_json, article_count)
               VALUES (?, ?, ?, ?)""",
            (date_str, content_md, content_json, article_count)
        )
        await db.commit()


async def get_krant(date_str: Optional[str] = None) -> Optional[dict]:
    if date_str is None:
        date_str = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM krant_archive WHERE date = ?", (date_str,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_archive(days: int = 7) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"""SELECT date, article_count FROM krant_archive
                WHERE date >= date('now', '-{int(days)} days')
                ORDER BY date DESC"""
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_sources(active_only: bool = True) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = "SELECT * FROM sources"
        if active_only:
            query += " WHERE active = 1"
        query += " ORDER BY category, name"
        async with db.execute(query) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def add_source(url: str, name: str, category: str, priority_boost: float = 0.0):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO sources (url, name, category, priority_boost, active)
               VALUES (?, ?, ?, ?, 1)""",
            (url, name, category, priority_boost)
        )
        await db.commit()


async def seed_sources_from_config(feeds: list[dict]):
    async with aiosqlite.connect(DB_PATH) as db:
        # Only insert feeds that don't already exist
        for feed in feeds:
            await db.execute(
                """INSERT OR IGNORE INTO sources (url, name, category, priority_boost, active)
                   VALUES (?, ?, ?, ?, 1)""",
                (feed["url"], feed["name"], feed["category"], feed.get("priority_boost", 0.0))
            )
        await db.commit()
