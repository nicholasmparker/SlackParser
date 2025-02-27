import os
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from app.embeddings import EmbeddingService
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get environment variables
MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongodb:27017")
MONGO_DB = os.getenv("MONGO_DB", "slack_data")

async def migrate_embeddings():
    """Generate embeddings for all existing messages in MongoDB"""
    try:
        logger.debug("Starting migration...")
        
        # Connect to MongoDB
        logger.debug("Connecting to MongoDB...")
        client = AsyncIOMotorClient(MONGO_URL)
        db = client[MONGO_DB]
        
        # Get total message count
        logger.debug("Counting messages...")
        total_messages = await db.messages.count_documents({})
        logger.info(f"Found {total_messages} messages to process")
        
        # Initialize embedding service
        logger.debug("Initializing EmbeddingService...")
        embedding_service = EmbeddingService()
        
        # Process in batches
        batch_size = 100
        processed = 0
        
        logger.debug("Starting batch processing...")
        while processed < total_messages:
            # Get next batch of messages
            logger.debug(f"Fetching batch starting at {processed}")
            messages = await db.messages.find({}).skip(processed).limit(batch_size).to_list(batch_size)
            if not messages:
                break
                
            # Debug log the first message structure
            if processed == 0:
                logger.debug(f"First message structure: {messages[0]}")
                logger.debug(f"First message keys: {messages[0].keys()}")
                
            # Add embeddings
            logger.debug(f"Adding embeddings for {len(messages)} messages")
            await embedding_service.add_messages(messages)
            processed += len(messages)
            logger.info(f"Processed {processed}/{total_messages} messages")
        
        logger.info("Migration complete!")
        
    except Exception as e:
        logger.error(f"Migration failed: {str(e)}", exc_info=True)
        raise

if __name__ == "__main__":
    asyncio.run(migrate_embeddings())
