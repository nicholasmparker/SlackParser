from motor.motor_asyncio import AsyncIOMotorClient
import asyncio
import os
from embeddings import EmbeddingService
import logging

MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongodb:27017")
MONGO_DB = os.getenv("MONGO_DB", "slack_data")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def migrate():
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[MONGO_DB]
    service = EmbeddingService()
    
    messages = await db.messages.find().limit(5).to_list(5)
    logger.info(f"Found {len(messages)} messages")
    
    await service.add_messages(messages)
    logger.info("Added messages to vector store")

if __name__ == "__main__":
    asyncio.run(migrate())
