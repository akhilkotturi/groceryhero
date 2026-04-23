"""Backfill script: generate embeddings for all deals where embedding IS NULL."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

import asyncpg
from app.services.embeddings import embed_batch, build_embed_text

DATABASE_URL = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
BATCH_SIZE = 64


async def run() -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await conn.fetch(
            "SELECT id, normalized_name, raw_title, category, brand, raw_description "
            "FROM deals WHERE embedding IS NULL"
        )
        total = len(rows)
        print(f"Found {total} deals to embed")
        if total == 0:
            print("Nothing to do.")
            return

        processed = 0
        for i in range(0, total, BATCH_SIZE):
            batch = rows[i : i + BATCH_SIZE]
            texts = [build_embed_text(dict(r)) for r in batch]
            embeddings = await embed_batch(texts)

            for row, emb in zip(batch, embeddings):
                emb_str = "[" + ",".join(f"{x:.8f}" for x in emb) + "]"
                await conn.execute(
                    "UPDATE deals SET embedding = $1::vector WHERE id = $2",
                    emb_str,
                    row["id"],
                )
            processed += len(batch)
            print(f"  {processed}/{total} embedded")

        print("Backfill complete.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run())
