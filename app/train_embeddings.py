import asyncio
import argparse
import logging
from datetime import datetime, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
from tqdm.asyncio import tqdm
import os
from typing import List, Dict, Any

from app.embeddings import EmbeddingService
from app.config import MONGO_URL, MONGO_DB

# Configure logging
def setup_logging():
    """Configure logging with debug level"""
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

logger = logging.getLogger(__name__)

async def get_embedding_progress(client):
    """Get current embedding progress"""
    try:
        db = client[MONGO_DB]
        progress = await db.embedding_progress.find_one({"_id": "current"}) or {
            "_id": "current",
            "processed": 0,
            "total": 0,
            "status": "not_started",
            "last_message_id": None,
            "errors": [],
            "retries": 0
        }
        return progress
    except Exception as e:
        logger.error(f"Failed to get progress: {e}")
        return {
            "processed": 0,
            "total": 0,
            "status": "error",
            "error": str(e)
        }

async def update_embedding_progress(client, processed, total, status="running", last_message_id=None, error=None):
    """Update the progress of embedding generation"""
    now = datetime.utcnow()
    
    # Calculate percentage and format nicely
    percent = (processed / total * 100) if total > 0 else 0
    percent_str = f"{percent:.1f}%"
    
    # Calculate messages per second
    prev_progress = await client[MONGO_DB]["embedding_progress"].find_one({"_id": "current"})
    if prev_progress and prev_progress.get("last_updated"):
        time_diff = (now - prev_progress["last_updated"]).total_seconds()
        if time_diff > 0:
            msgs_per_sec = (processed - prev_progress["processed"]) / time_diff
            # Calculate ETA
            remaining_msgs = total - processed
            eta_seconds = remaining_msgs / msgs_per_sec if msgs_per_sec > 0 else 0
            eta = str(timedelta(seconds=int(eta_seconds)))
        else:
            msgs_per_sec = 0
            eta = "calculating..."
    else:
        msgs_per_sec = 0
        eta = "calculating..."
    
    # Log progress
    logger.info(f"Progress: {processed:,}/{total:,} messages ({percent_str}) - {msgs_per_sec:.1f} msgs/sec - ETA: {eta}")
    
    await client[MONGO_DB]["embedding_progress"].update_one(
        {"_id": "current"},
        {
            "$set": {
                "last_updated": now,
                "processed": processed,
                "total": total,
                "status": status,
                "last_message_id": last_message_id,
                "error": error,
                "percent": percent,
                "messages_per_second": msgs_per_sec,
                "eta": eta
            }
        },
        upsert=True
    )

async def get_messages_batch(client, skip: int, limit: int) -> List[Dict[Any, Any]]:
    """Get a batch of messages with error handling and retries"""
    try:
        db = client[MONGO_DB]
        retries = 3
        backoff = 1
        
        for attempt in range(retries):
            try:
                cursor = db.messages.find({
                    "text": {"$exists": True, "$ne": ""},
                    "user": {"$not": {"$regex": ".*_bot$"}}
                }).sort("timestamp", -1).skip(skip).limit(limit)
                
                return await cursor.to_list(length=None)
            except Exception as e:
                if attempt == retries - 1:
                    raise
                logger.warning(f"Failed to fetch messages (attempt {attempt + 1}/{retries}): {e}")
                await asyncio.sleep(backoff)
                backoff *= 2
    except Exception as e:
        logger.error(f"Failed to get messages batch: {e}")
        return []

async def enrich_messages(client, messages: List[Dict[Any, Any]]) -> List[Dict[Any, Any]]:
    """Enrich messages with additional context"""
    if not messages:
        return []
        
    db = client[MONGO_DB]
    enriched = []
    
    # Get all unique conversation IDs
    conv_ids = list(set(m.get("conversation") for m in messages if m.get("conversation")))
    
    # Fetch all conversations in one query
    conversations = {}
    if conv_ids:
        cursor = db.conversations.find({"_id": {"$in": conv_ids}})
        async for conv in cursor:
            conversations[conv["_id"]] = conv
    
    for msg in messages:
        enriched_msg = msg.copy()
        
        # Add conversation context
        conv_id = msg.get("conversation")
        if conv_id and conv_id in conversations:
            conv = conversations[conv_id]
            enriched_msg["conversation_name"] = conv.get("name", "")
            enriched_msg["conversation_type"] = conv.get("type", "")
        
        # Clean and normalize text
        if enriched_msg.get("text"):
            enriched_msg["text"] = enriched_msg["text"].strip()
        
        enriched.append(enriched_msg)
    
    return enriched

async def process_message_batch(
    client,
    embedding_service: EmbeddingService,
    messages: List[Dict[Any, Any]],
    batch_size: int
) -> int:
    """Process a batch of messages, returning number of successful embeddings"""
    if not messages:
        return 0
    
    try:
        # Enrich messages
        enriched_messages = await enrich_messages(client, messages)
        
        # Generate embeddings in smaller batches
        successful = 0
        for i in range(0, len(enriched_messages), batch_size):
            batch = enriched_messages[i:i + batch_size]
            try:
                await embedding_service.add_messages(batch, batch_size=batch_size)
                successful += len(batch)
            except Exception as e:
                logger.error(f"Failed to process messages {i} to {i + len(batch)}: {e}")
                # Continue with next batch instead of failing completely
                continue
        
        return successful
    except Exception as e:
        logger.error(f"Failed to process batch: {e}")
        return 0

async def main():
    setup_logging()
    logger.debug("Starting embedding training with debug logging enabled")
    parser = argparse.ArgumentParser(description='Train embeddings on Slack messages')
    parser.add_argument('--batch-size', type=int, default=100, help='Batch size for processing embeddings')
    parser.add_argument('--fetch-batch-size', type=int, default=1000, help='Batch size for fetching messages')
    parser.add_argument('--max-retries', type=int, default=3, help='Maximum number of retries for failed batches')
    parser.add_argument('--reset', action='store_true', help='Reset existing embeddings before starting')
    args = parser.parse_args()
    
    # Initialize services
    try:
        logger.debug("Initializing services...")
        embedding_service = EmbeddingService()
        mongo_client = AsyncIOMotorClient(MONGO_URL)
        
        # Test MongoDB connection
        logger.debug("Testing MongoDB connection...")
        await mongo_client.admin.command('ping')
        logger.info(f"Connected to MongoDB at {MONGO_URL}")
        
        # Get database
        db = mongo_client[MONGO_DB]
        
        if args.reset:
            logger.info("Resetting existing embeddings...")
            await embedding_service.delete_all()
        
        # Get or create progress
        logger.debug("Getting embedding progress...")
        progress = await get_embedding_progress(mongo_client)
        if progress["status"] == "completed":
            logger.info("Embeddings are already up to date")
            return
            
        # Get total count
        logger.debug("Getting total message count...")
        total = await db.messages.count_documents({
            "text": {"$exists": True, "$ne": ""},
            "user": {"$not": {"$regex": ".*_bot$"}}
        })
        logger.info(f"Found {total:,} total messages to process")
        
        if total == 0:
            logger.error("No messages found in database")
            return
            
        # Process messages in batches with progress bar
        logger.debug("Starting message processing...")
        pbar = tqdm(total=total, initial=progress["processed"], desc="Processing messages")
        
        try:
            while progress["processed"] < total:
                try:
                    # Fetch next batch of messages
                    logger.debug(f"Fetching batch at offset {progress['processed']}")
                    messages = await get_messages_batch(
                        mongo_client,
                        skip=progress["processed"],
                        limit=args.fetch_batch_size
                    )
                    
                    if not messages:
                        logger.warning("No messages returned in batch")
                        break
                    
                    logger.debug(f"Processing batch of {len(messages)} messages")
                    # Process messages
                    successful = await process_message_batch(
                        mongo_client,
                        embedding_service,
                        messages,
                        args.batch_size
                    )
                    
                    # Update progress
                    if successful > 0:
                        progress["processed"] += successful
                        last_id = str(messages[-1]["_id"]) if messages else None
                        await update_embedding_progress(
                            mongo_client,
                            progress["processed"],
                            total,
                            last_message_id=last_id
                        )
                        pbar.update(successful)
                        logger.debug(f"Successfully processed {successful} messages")
                    else:
                        # If batch failed completely, increment retry counter
                        progress["retries"] += 1
                        if progress["retries"] >= args.max_retries:
                            raise Exception(f"Failed to process batch after {progress['retries']} retries")
                        logger.warning(f"Retrying batch (attempt {progress['retries']}/{args.max_retries})")
                        await asyncio.sleep(min(progress["retries"] * 2, 30))  # Exponential backoff
            
                except Exception as e:
                    logger.error(f"Error processing batch: {e}", exc_info=True)
                    await update_embedding_progress(
                        mongo_client,
                        progress["processed"],
                        total,
                        status="error",
                        error=str(e)
                    )
                    raise
            
            # Mark as completed
            await update_embedding_progress(mongo_client, progress["processed"], total, status="completed")
            logger.info("Successfully trained all embeddings")
            
        except Exception as e:
            logger.error(f"Error training embeddings: {e}", exc_info=True)
            await update_embedding_progress(
                mongo_client,
                progress["processed"],
                total,
                status="failed",
                error=str(e)
            )
            raise
        finally:
            pbar.close()
            mongo_client.close()
            
    except Exception as e:
        logger.error(f"Failed to initialize services: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
