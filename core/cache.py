"""
Simple SQLite-backed cache for search results.

Keys are SHA-256 hashes of the search query string.
Results are stored as JSON and expire after `ttl_hours` hours.
"""

import hashlib
import json
import sqlite3
import time
from pathlib import Path

DB_PATH = Path.home() / ".deep_research_cache.db"
DEFAULT_TTL_HOURS = 24


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS search_cache (
            key        TEXT PRIMARY KEY,
            query      TEXT,
            result     TEXT,
            created_at REAL
        )
        """
    )
    conn.commit()
    return conn


def _hash(query: str) -> str:
    return hashlib.sha256(query.strip().lower().encode()).hexdigest()


def get_cached(query: str, ttl_hours: int = DEFAULT_TTL_HOURS) -> dict | None:
    """Return cached result dict for query, or None if missing/expired."""
    key = _hash(query)
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT result, created_at FROM search_cache WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        result_json, created_at = row
        age_hours = (time.time() - created_at) / 3600
        if age_hours > ttl_hours:
            conn.execute("DELETE FROM search_cache WHERE key = ?", (key,))
            conn.commit()
            return None
        return json.loads(result_json)
    finally:
        conn.close()


def set_cached(query: str, result: dict) -> None:
    """Store result dict for query."""
    key = _hash(query)
    conn = _get_conn()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO search_cache (key, query, result, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (key, query, json.dumps(result), time.time()),
        )
        conn.commit()
    finally:
        conn.close()


def clear_cache() -> int:
    """Delete all cached entries. Returns number of rows deleted."""
    conn = _get_conn()
    try:
        cursor = conn.execute("DELETE FROM search_cache")
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def cache_stats() -> dict:
    """Return basic stats about the cache."""
    conn = _get_conn()
    try:
        total = conn.execute("SELECT COUNT(*) FROM search_cache").fetchone()[0]
        oldest = conn.execute("SELECT MIN(created_at) FROM search_cache").fetchone()[0]
        return {
            "total_entries": total,
            "oldest_entry_hours_ago": round((time.time() - oldest) / 3600, 1) if oldest else None,
            "db_path": str(DB_PATH),
        }
    finally:
        conn.close()
