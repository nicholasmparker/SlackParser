import asyncio
import os
from motor.motor_asyncio import AsyncIOMotorClient
from embeddings import EmbeddingService
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def migrate():
    client = AsyncIOMotorClient(os.getenv('MONGODB_URL'))
    db = client.slack_db
    service = EmbeddingService()
    
    messages = await db.messages.find().limit(5).to_list(5)
    logger.info(f"Found {len(messages)} messages")
    
    await service.add_messages(messages)
    logger.info("Added messages to vector store")

if __name__ == "__main__":
    asyncio.run(migrate())
