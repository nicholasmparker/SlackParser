from motor.motor_asyncio import AsyncIOMotorClient
import os

# Get environment variables
MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongodb:27017")
MONGO_DB = os.getenv("MONGO_DB", "slack_data")

async def get_database():
    """Get MongoDB database connection"""
    client = AsyncIOMotorClient(MONGO_URL)
    return client[MONGO_DB]
