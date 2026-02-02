import json
import redis.asyncio as redis
from config import REDIS_URL, REDIS_CHANNELS


class RedisManager:
    def __init__(self):
        self.redis: redis.Redis = None
        self.pubsub: redis.client.PubSub = None

    async def connect(self):
        """Connect to Redis Cloud"""
        self.redis = redis.from_url(REDIS_URL, decode_responses=True)
        await self.redis.ping()
        print("Connected to Redis")

    async def close(self):
        """Close Redis connection"""
        if self.pubsub:
            await self.pubsub.aclose()
        if self.redis:
            await self.redis.aclose()
        print("Redis connection closed")

    async def publish(self, channel: str, message: dict):
        """Publish message to channel"""
        await self.redis.publish(channel, json.dumps(message, default=str))

    async def subscribe(self, channels: list = None) -> redis.client.PubSub:
        """Subscribe to channels and return pubsub instance"""
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(*(channels or REDIS_CHANNELS))
        return pubsub


redis_manager = RedisManager()
