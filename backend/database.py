import os

from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from models import ChatMessage, Conversation, User

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB = os.getenv("MONGODB_DB", "gemini_agents")

_client: AsyncIOMotorClient | None = None


async def init_db() -> None:
    global _client
    _client = AsyncIOMotorClient(MONGODB_URI)
    await init_beanie(
        database=_client[MONGODB_DB],
        document_models=[User, Conversation, ChatMessage],
    )


async def close_db() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
