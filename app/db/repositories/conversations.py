"""Repository for conversation-related database operations."""

from datetime import datetime
from typing import Dict, Any, List, Optional
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)

class ConversationRepository:
    """Repository for conversation-related database operations."""
    
    def __init__(self, db):
        """Initialize the repository with a database connection."""
        self.db = db
        self.collection = db.conversations
    
    async def find_by_id(self, channel_id: str) -> Optional[Dict[str, Any]]:
        """Find a conversation by channel ID."""
        try:
            return await self.collection.find_one({"channel_id": channel_id})
        except Exception as e:
            logger.error(f"Error finding conversation {channel_id}: {e}")
            return None
    
    async def find_all(self, limit: int = 100, skip: int = 0, 
                      sort_field: str = "name", sort_order: int = 1) -> List[Dict[str, Any]]:
        """Find all conversations."""
        try:
            return await self.collection.find().sort(
                sort_field, sort_order
            ).skip(skip).limit(limit).to_list(length=None)
        except Exception as e:
            logger.error(f"Error finding conversations: {e}")
            return []
    
    async def find_by_type(self, type_filter: str, limit: int = 100, 
                          skip: int = 0) -> List[Dict[str, Any]]:
        """Find conversations by type."""
        try:
            return await self.collection.find(
                {"type": type_filter}
            ).sort("name", 1).skip(skip).limit(limit).to_list(length=None)
        except Exception as e:
            logger.error(f"Error finding conversations by type {type_filter}: {e}")
            return []
    
    async def count_by_type(self, type_filter: str) -> int:
        """Count conversations by type."""
        try:
            return await self.collection.count_documents({"type": type_filter})
        except Exception as e:
            logger.error(f"Error counting conversations by type {type_filter}: {e}")
            return 0
    
    async def search_by_name(self, query: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Search conversations by name."""
        try:
            # Use regex for case-insensitive search
            regex = {"$regex": query, "$options": "i"}
            return await self.collection.find(
                {"name": regex}
            ).sort("name", 1).limit(limit).to_list(length=None)
        except Exception as e:
            logger.error(f"Error searching conversations for query '{query}': {e}")
            return []
    
    async def insert_one(self, conversation: Dict[str, Any]) -> str:
        """Insert a conversation."""
        try:
            # Check if conversation already exists
            existing = await self.collection.find_one({"channel_id": conversation["channel_id"]})
            if existing:
                return str(existing["_id"])
            
            # Insert new conversation
            result = await self.collection.insert_one(conversation)
            return str(result.inserted_id)
        except Exception as e:
            logger.error(f"Error inserting conversation: {e}")
            raise e
    
    async def update_one(self, channel_id: str, update_data: Dict[str, Any]) -> None:
        """Update a conversation."""
        try:
            await self.collection.update_one(
                {"channel_id": channel_id},
                {"$set": {**update_data, "updated_at": datetime.utcnow()}}
            )
        except Exception as e:
            logger.error(f"Error updating conversation {channel_id}: {e}")
    
    async def count_all(self) -> int:
        """Count all conversations."""
        try:
            return await self.collection.count_documents({})
        except Exception as e:
            logger.error(f"Error counting conversations: {e}")
            return 0