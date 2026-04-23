"""One-time migration: enable pgvector extension and add embedding column to deals."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

import asyncpg

DATABASE_URL = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://").replace("@postgres:", "@localhost:")


async def run() -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        print("✓ pgvector extension enabled")

        await conn.execute(
            "ALTER TABLE deals ADD COLUMN IF NOT EXISTS embedding vector(384);"
        )
        print("✓ embedding column added to deals table")

        await conn.execute(
            "CREATE INDEX IF NOT EXISTS deals_embedding_ivfflat_idx "
            "ON deals USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);"
        )
        print("✓ IVFFlat index created (lists=100)")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run())
