"""MongoDB database connection module."""

from motor.motor_asyncio import AsyncIOMotorClient
from app.config import MONGO_URL, MONGO_DB

def get_database():
    """Get MongoDB database connection."""
    client = AsyncIOMotorClient(MONGO_URL)
    return client[MONGO_DB]
