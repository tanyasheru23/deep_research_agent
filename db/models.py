"""
Database — SQLAlchemy async with SQLite.
Switch to PostgreSQL by changing DATABASE_URL only.

Tables: users, reports
(search cache stays in cache.py with its own connection)
"""

from __future__ import annotations
from datetime import datetime
from sqlalchemy import String, Text, Integer, Float, DateTime, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# ── Models ────────────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id            : Mapped[str]   = mapped_column(String, primary_key=True)
    username      : Mapped[str]   = mapped_column(String, unique=True, nullable=False)
    email         : Mapped[str]   = mapped_column(String, nullable=False)
    password_hash : Mapped[str]   = mapped_column(String, nullable=False)
    created_at    : Mapped[float] = mapped_column(Float,  nullable=False)


class Report(Base):
    __tablename__ = "reports"

    id         : Mapped[str]      = mapped_column(String,  primary_key=True)
    user_id    : Mapped[str]      = mapped_column(String,  ForeignKey("users.id"), nullable=False)
    query      : Mapped[str]      = mapped_column(Text,    nullable=False)
    summary    : Mapped[str]      = mapped_column(Text,    nullable=True)
    markdown   : Mapped[str]      = mapped_column(Text,    nullable=False)
    word_count : Mapped[int]      = mapped_column(Integer, nullable=False)
    depth      : Mapped[str]      = mapped_column(String,  nullable=False)
    created_at : Mapped[float]    = mapped_column(Float,   nullable=False)
