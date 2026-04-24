"""Pytest bootstrap for test-safe environment defaults.

These defaults prevent Settings() import-time validation from failing when local
developer env vars are not set. Individual tests can still override as needed.
"""
import os


os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
