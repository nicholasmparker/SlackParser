from motor.motor_asyncio import AsyncIOMotorClient
from fastapi import Request
import os

MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://mongodb:27017")

def get_db() -> AsyncIOMotorClient:
    """Get MongoDB database client."""
    client = AsyncIOMotorClient(MONGODB_URL)
    return client["slack_db"]
