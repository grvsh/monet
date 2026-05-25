"""Re-enqueue generate_assets for all media_files with processed_at IS NULL."""
import asyncio
import sys

sys.path.insert(0, "/app")

from arq.connections import RedisSettings, create_pool
from sqlalchemy import select

from app.config import settings
from app.database import async_session_factory
from app.models.db import MediaFile


async def main() -> None:
    redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))

    async with async_session_factory() as session:
        result = await session.execute(
            select(MediaFile.id).where(
                MediaFile.processed_at.is_(None),
                MediaFile.is_deleted == False,  # noqa: E712
            )
        )
        file_ids = [str(row[0]) for row in result.all()]

    print(f"Re-enqueueing {len(file_ids)} files...")
    for i, file_id in enumerate(file_ids):
        await redis.enqueue_job(
            "generate_assets",
            file_id,
            None,
            _queue_name="arq:asset-queue",
        )
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(file_ids)}")

    await redis.aclose()
    print("Done.")


asyncio.run(main())
