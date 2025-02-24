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
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def get_embedding_progress(client):
    """Get current embedding progress"""
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

async def update_embedding_progress(client, processed, total, status="running", error=None, last_message_id=None):
    """Update embedding progress"""
    db = client[MONGO_DB]
    update = {
        "processed": processed,
        "total": total,
        "status": status,
        "last_updated": datetime.now()
    }
    if error:
        update["$push"] = {"errors": {
            "timestamp": datetime.now(),
            "error": str(error),
            "processed": processed
        }}
    if last_message_id:
        update["last_message_id"] = last_message_id
    
    try:
        result = await db.embedding_progress.update_one(
            {"_id": "current"},
            {"$set": update},
            upsert=True
        )
        logger.debug(f"Progress update result: {result.modified_count} documents modified")
    except Exception as e:
        logger.error(f"Failed to update progress: {e}")

async def get_messages_batch(client, skip: int, limit: int) -> List[Dict[Any, Any]]:
    """Get a batch of messages with error handling and retries"""
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
    parser = argparse.ArgumentParser(description='Train embeddings on Slack messages')
    parser.add_argument('--batch-size', type=int, default=50, help='Batch size for processing embeddings')
    parser.add_argument('--fetch-batch-size', type=int, default=1000, help='Batch size for fetching messages')
    parser.add_argument('--max-retries', type=int, default=3, help='Maximum number of retries for failed batches')
    args = parser.parse_args()
    
    # Initialize clients
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[MONGO_DB]
    embedding_service = EmbeddingService()
    
    try:
        # Get or create progress
        progress = await get_embedding_progress(client)
        if progress["status"] == "completed":
            logger.info("Embeddings are already up to date")
            return
        
        # Start from where we left off
        processed = progress["processed"]
        retries = progress.get("retries", 0)
        logger.info(f"Resuming from {processed} processed messages (retries: {retries})")
        
        # Get total count
        total = await db.messages.count_documents({
            "text": {"$exists": True, "$ne": ""},
            "user": {"$not": {"$regex": ".*_bot$"}}
        })
        logger.info(f"Found {total} total messages to process")
        
        # Process messages in batches with progress bar
        pbar = tqdm(total=total, initial=processed, desc="Processing messages")
        
        while processed < total:
            try:
                # Fetch next batch of messages
                messages = await get_messages_batch(
                    client,
                    skip=processed,
                    limit=args.fetch_batch_size
                )
                
                if not messages:
                    break
                
                # Process messages
                successful = await process_message_batch(
                    client,
                    embedding_service,
                    messages,
                    args.batch_size
                )
                
                # Update progress
                if successful > 0:
                    processed += successful
                    last_id = str(messages[-1]["_id"]) if messages else None
                    await update_embedding_progress(
                        client,
                        processed,
                        total,
                        last_message_id=last_id
                    )
                    pbar.update(successful)
                else:
                    # If batch failed completely, increment retry counter
                    retries += 1
                    if retries >= args.max_retries:
                        raise Exception(f"Failed to process batch after {retries} retries")
                    logger.warning(f"Retrying batch (attempt {retries}/{args.max_retries})")
                    await asyncio.sleep(min(retries * 2, 30))  # Exponential backoff
            
            except Exception as e:
                logger.error(f"Error processing batch: {e}")
                await update_embedding_progress(
                    client,
                    processed,
                    total,
                    status="error",
                    error=str(e)
                )
                raise
        
        # Mark as completed
        await update_embedding_progress(client, processed, total, status="completed")
        logger.info("Successfully trained all embeddings")
        
    except Exception as e:
        logger.error(f"Error training embeddings: {e}", exc_info=True)
        await update_embedding_progress(
            client,
            processed,
            total,
            status="failed",
            error=str(e)
        )
        raise
    finally:
        pbar.close()
        client.close()

if __name__ == "__main__":
    asyncio.run(main())
