import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from app.embeddings import EmbeddingService
import logging
from tqdm import tqdm
import argparse
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB connection
MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")

async def get_messages_by_engagement(client, min_reactions=1, min_replies=1, limit=None):
    """Get messages with high engagement (reactions or replies)"""
    db = client.slack_db
    
    # Query for messages with reactions or replies
    query = {
        "text": {"$exists": True, "$ne": ""},
        "user": {"$not": {"$regex": ".*_bot$"}},  # Exclude bot messages
        "$or": [
            {"reactions": {"$exists": True, "$ne": []}},
            {"reply_count": {"$gte": min_replies}}
        ]
    }
    
    # Get messages sorted by engagement (reaction count + reply count)
    pipeline = [
        {"$match": query},
        {"$addFields": {
            "engagement_score": {
                "$add": [
                    {"$size": {"$ifNull": ["$reactions", []]}},
                    {"$ifNull": ["$reply_count", 0]}
                ]
            }
        }},
        {"$sort": {"engagement_score": -1}},
    ]
    
    if limit:
        pipeline.append({"$limit": limit})
        
    cursor = db.messages.aggregate(pipeline)
    return await cursor.to_list(length=None)

async def get_recent_messages(client, days=30, limit=None):
    """Get recent messages within the specified time window"""
    db = client.slack_db
    
    # Calculate cutoff date
    cutoff = datetime.now() - timedelta(days=days)
    
    # Query for recent messages
    query = {
        "text": {"$exists": True, "$ne": ""},
        "user": {"$not": {"$regex": ".*_bot$"}},  # Exclude bot messages
        "timestamp": {"$gte": cutoff}
    }
    
    cursor = db.messages.find(query).sort("timestamp", -1)
    if limit:
        cursor = cursor.limit(limit)
        
    return await cursor.to_list(length=None)

async def enrich_messages(client, messages):
    """Enrich messages with additional context"""
    # Get thread contexts
    thread_ts_values = {msg.get("thread_ts") for msg in messages if msg.get("thread_ts")}
    thread_messages = {}
    
    if thread_ts_values:
        # Fetch all parent messages in one query
        parent_messages = await client.slack_db.messages.find({
            "ts": {"$in": list(thread_ts_values)}
        }).to_list(length=None)
        
        # Create lookup dictionary
        thread_messages = {msg["ts"]: msg for msg in parent_messages}
    
    # Get channel names
    channel_ids = {msg["conversation_id"] for msg in messages if msg.get("conversation_id")}
    channels = await client.slack_db.conversations.find(
        {"_id": {"$in": list(channel_ids)}},
        {"_id": 1, "name": 1}
    ).to_list(length=None)
    channel_names = {str(c["_id"]): c.get("name") for c in channels}
    
    # Enrich messages
    for msg in messages:
        # Add thread context
        if msg.get("thread_ts"):
            msg["parent_message"] = thread_messages.get(msg["thread_ts"])
        
        # Add channel name
        conv_id = msg.get("conversation_id")
        if conv_id:
            msg["channel_name"] = channel_names.get(str(conv_id))
    
    return messages

async def main():
    parser = argparse.ArgumentParser(description='Train embeddings on Slack messages')
    parser.add_argument('--limit', type=int, default=None, help='Number of messages to process')
    parser.add_argument('--batch-size', type=int, default=50, help='Batch size for processing')
    parser.add_argument('--days', type=int, default=30, help='Days of recent messages to include')
    parser.add_argument('--min-reactions', type=int, default=1, help='Minimum reactions for engagement-based selection')
    parser.add_argument('--min-replies', type=int, default=1, help='Minimum replies for engagement-based selection')
    parser.add_argument('--engagement-ratio', type=float, default=0.5, help='Ratio of messages to select by engagement vs recency')
    args = parser.parse_args()
    
    # Initialize MongoDB client
    client = AsyncIOMotorClient(MONGODB_URL)
    
    # Initialize embedding service
    embedding_service = EmbeddingService()
    
    try:
        # Get messages by engagement
        logger.info("Fetching high-engagement messages...")
        if args.limit:
            engagement_limit = int(args.limit * args.engagement_ratio)
        else:
            engagement_limit = None
            
        engagement_messages = await get_messages_by_engagement(
            client, 
            min_reactions=args.min_reactions,
            min_replies=args.min_replies,
            limit=engagement_limit
        )
        logger.info(f"Got {len(engagement_messages)} high-engagement messages")
        
        # Get recent messages
        logger.info("Fetching recent messages...")
        if args.limit:
            recent_limit = args.limit - len(engagement_messages)
        else:
            recent_limit = None
            
        recent_messages = await get_recent_messages(
            client,
            days=args.days,
            limit=recent_limit
        )
        logger.info(f"Got {len(recent_messages)} recent messages")
        
        # Combine and deduplicate messages
        all_messages = list({str(m["_id"]): m for m in engagement_messages + recent_messages}.values())
        logger.info(f"Got {len(all_messages)} total unique messages")
        
        # Enrich messages with context
        logger.info("Enriching messages with context...")
        enriched_messages = await enrich_messages(client, all_messages)
        
        # Clear existing embeddings
        logger.info("Clearing existing embeddings...")
        await embedding_service.delete_all()
        
        # Add messages to ChromaDB in batches with progress bar
        logger.info("Generating embeddings and adding to ChromaDB...")
        await embedding_service.add_messages(enriched_messages, batch_size=args.batch_size)
        
        logger.info("Successfully trained embeddings")
        
    except Exception as e:
        logger.error(f"Error training embeddings: {str(e)}", exc_info=True)
        raise
    finally:
        client.close()

if __name__ == "__main__":
    asyncio.run(main())
