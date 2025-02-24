import asyncio
import os
from motor.motor_asyncio import AsyncIOMotorClient
from app.embeddings import EmbeddingService
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get environment variables
MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongodb:27017")
MONGO_DB = os.getenv("MONGO_DB", "slack_data")

async def main():
    """Update Chroma embeddings for all messages"""
    try:
        # Initialize services
        client = AsyncIOMotorClient(MONGO_URL)
        db = client[MONGO_DB]
        service = EmbeddingService()
        
        # Count messages
        count = await db.messages.count_documents({})
        logger.info(f"Found {count} messages to process")
        
        # Update embeddings
        await service.update_chroma_embeddings(db)
        logger.info("Embeddings updated successfully")
        
    except Exception as e:
        logger.error(f"Error updating embeddings: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())
