"""Service for handling search functionality."""

import logging
from typing import Any, Dict, List, Optional, Set
from bson import ObjectId

from app.embeddings import EmbeddingService

logger = logging.getLogger(__name__)

class SearchService:
    """Service for handling search functionality."""
    
    def __init__(self, db=None, sync_db=None):
        """Initialize the search service."""
        self.db = db
        self.sync_db = sync_db
        self.embeddings = None
    
    def initialize_embeddings(self):
        """Initialize the embeddings service if not already initialized."""
        if not self.embeddings:
            logger.info("Initializing embeddings service")
            self.embeddings = EmbeddingService()
            self.embeddings.initialize()
    
    async def search(self, query: str, limit: int = 50, hybrid_alpha: float = 0.5) -> List[Dict[str, Any]]:
        """Search for messages using hybrid search.
        
        Args:
            query: The search query
            limit: Maximum number of results to return
            hybrid_alpha: Weight between semantic and keyword search (0.0 = all keyword, 1.0 = all semantic)
            
        Returns:
            List of search results with conversation details
        """
        try:
            # Initialize embeddings service if not already initialized
            self.initialize_embeddings()
            
            # Perform semantic search
            search_results = await self.embeddings.search(
                query=query,
                limit=limit,
                hybrid_alpha=hybrid_alpha
            )
            
            # Extract conversation IDs from results
            conversation_ids = list(set(r["metadata"]["conversation_id"] for r in search_results))
            
            # Get conversation details
            conversations = await self.db.conversations.find(
                {"channel_id": {"$in": conversation_ids}},
                {"name": 1, "type": 1, "channel_id": 1}
            ).to_list(None)
            conv_map = {c["channel_id"]: c for c in conversations}
            
            # Format results for template
            results = []
            for r in search_results:
                try:
                    ts = float(r["metadata"]["timestamp"]) if r["metadata"]["timestamp"] and r["metadata"]["timestamp"].replace('.','').isdigit() else 0
                except (ValueError, TypeError):
                    ts = 0
                    logger.warning(f"Could not parse timestamp: {r['metadata']['timestamp']}")
                
                conv_id = r["metadata"]["conversation_id"]
                results.append({
                    "text": r["text"],
                    "conversation": conv_map.get(conv_id, {"name": "Unknown", "type": "unknown"}),
                    "conversation_id": conv_id,
                    "user": r["metadata"]["user"],
                    "ts": ts,
                    "score": r["similarity"],
                    "keyword_match": r.get("keyword_match", False)
                })
            
            # Sort results by score
            results.sort(key=lambda x: x["score"], reverse=True)
            
            return results
        except Exception as e:
            logger.error(f"Error in search: {str(e)}", exc_info=True)
            raise
    
    async def text_search(self, query: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Perform a text search on messages.
        
        Args:
            query: The search query
            limit: Maximum number of results to return
            
        Returns:
            List of messages matching the query
        """
        try:
            # Create text search query
            db_query = {"$text": {"$search": query}}
            
            # Perform search
            messages = await self.db.messages.find(
                db_query,
                {"score": {"$meta": "textScore"}}
            ).sort([("score", {"$meta": "textScore"})]).limit(limit).to_list(length=limit)
            
            # Get conversation details
            conversation_ids = list(set(msg.get("conversation_id") for msg in messages if msg.get("conversation_id")))
            
            conversations = await self.db.conversations.find(
                {"channel_id": {"$in": conversation_ids}},
                {"name": 1, "type": 1, "channel_id": 1}
            ).to_list(None)
            conv_map = {c["channel_id"]: c for c in conversations}
            
            # Format results
            results = []
            for msg in messages:
                conv_id = msg.get("conversation_id")
                results.append({
                    "text": msg.get("text", ""),
                    "conversation": conv_map.get(conv_id, {"name": "Unknown", "type": "unknown"}),
                    "conversation_id": conv_id,
                    "user": msg.get("username", "Unknown"),
                    "ts": msg.get("ts"),
                    "score": msg.get("score", 0),
                    "keyword_match": True
                })
            
            return results
        except Exception as e:
            logger.error(f"Error in text_search: {str(e)}", exc_info=True)
            raise
    
    async def get_context(self, conversation_id: str, message_ts: float, context_size: int = 5) -> List[Dict[str, Any]]:
        """Get context messages around a specific message.
        
        Args:
            conversation_id: The conversation ID
            message_ts: The timestamp of the message
            context_size: Number of messages before and after to include
            
        Returns:
            List of messages providing context
        """
        try:
            # Get messages before
            before = await self.db.messages.find(
                {"conversation_id": conversation_id, "ts": {"$lt": message_ts}}
            ).sort("ts", -1).limit(context_size).to_list(length=context_size)
            
            # Get the message itself
            current = await self.db.messages.find_one(
                {"conversation_id": conversation_id, "ts": message_ts}
            )
            
            # Get messages after
            after = await self.db.messages.find(
                {"conversation_id": conversation_id, "ts": {"$gt": message_ts}}
            ).sort("ts", 1).limit(context_size).to_list(length=context_size)
            
            # Combine and sort
            context = []
            if before:
                context.extend(reversed(before))
            if current:
                context.append(current)
            if after:
                context.extend(after)
            
            # Sort by timestamp
            context.sort(key=lambda x: x.get("ts", 0))
            
            return context
        except Exception as e:
            logger.error(f"Error in get_context: {str(e)}", exc_info=True)
            raise