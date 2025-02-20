import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from app.embeddings import EmbeddingService
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB connection
MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")

async def get_sample_messages(client, limit=1000):
    """Get a sample of messages from MongoDB"""
    db = client.slack_db
    # Get messages with non-empty text, sorted by timestamp
    cursor = db.messages.find(
        {"text": {"$exists": True, "$ne": ""}},
        {"_id": 1, "text": 1, "user": 1, "conversation_id": 1, "timestamp": 1, "ts": 1}
    ).sort("timestamp", -1).limit(limit)
    
    return await cursor.to_list(length=None)

async def main():
    # Initialize MongoDB client
    client = AsyncIOMotorClient(MONGODB_URL)
    
    # Initialize embedding service
    embedding_service = EmbeddingService()
    
    try:
        # Get sample messages
        logger.info("Fetching sample messages from MongoDB...")
        messages = await get_sample_messages(client, limit=1000)
        logger.info(f"Got {len(messages)} messages")
        
        # Clear existing embeddings
        logger.info("Clearing existing embeddings...")
        await embedding_service.delete_all()
        
        # Add messages to ChromaDB
        logger.info("Generating embeddings and adding to ChromaDB...")
        await embedding_service.add_messages(messages)
        
        logger.info("Successfully trained embeddings on sample data")
        
    except Exception as e:
        logger.error(f"Error training embeddings: {str(e)}", exc_info=True)
        raise
    finally:
        client.close()

if __name__ == "__main__":
    asyncio.run(main())
