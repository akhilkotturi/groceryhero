from redis.asyncio import Redis, from_url
from app.core.config import settings

_redis: Redis | None = None


async def init_redis():
    global _redis
    _redis = await from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)


async def close_redis():
    global _redis
    if _redis:
        await _redis.aclose()


async def get_redis() -> Redis:
    if _redis is None:
        raise RuntimeError("Redis not initialized")
    return _redis
