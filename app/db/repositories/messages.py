"""Repository for message-related database operations."""

from datetime import datetime
from typing import Dict, Any, List, Optional
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)

class MessageRepository:
    """Repository for message-related database operations."""
    
    def __init__(self, db):
        """Initialize the repository with a database connection."""
        self.db = db
        self.collection = db.messages
        self.failed_imports = db.failed_imports
    
    async def find_by_conversation(self, conversation_id: str, limit: int = 100, 
                                  skip: int = 0, sort_order: int = -1) -> List[Dict[str, Any]]:
        """Find messages by conversation ID."""
        try:
            return await self.collection.find(
                {"conversation_id": conversation_id}
            ).sort("ts", sort_order).skip(skip).limit(limit).to_list(length=None)
        except Exception as e:
            logger.error(f"Error finding messages for conversation {conversation_id}: {e}")
            return []
    
    async def count_by_conversation(self, conversation_id: str) -> int:
        """Count messages by conversation ID."""
        try:
            return await self.collection.count_documents({"conversation_id": conversation_id})
        except Exception as e:
            logger.error(f"Error counting messages for conversation {conversation_id}: {e}")
            return 0
    
    async def text_search(self, query: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Search messages by text."""
        try:
            return await self.collection.find(
                {"$text": {"$search": query}}
            ).sort([("score", {"$meta": "textScore"})]).limit(limit).to_list(length=None)
        except Exception as e:
            logger.error(f"Error searching messages for query '{query}': {e}")
            return []
    
    async def insert_many(self, messages: List[Dict[str, Any]]) -> None:
        """Insert multiple messages."""
        if not messages:
            return
        
        try:
            await self.collection.insert_many(messages)
        except Exception as e:
            logger.error(f"Error inserting messages: {e}")
            # Try to insert one by one if bulk insert fails
            for message in messages:
                try:
                    await self.collection.insert_one(message)
                except Exception as e2:
                    logger.error(f"Error inserting single message: {e2}")
    
    async def record_failed_import(self, upload_id: str, file_path: str, 
                                  error: str, line_number: int = 0) -> None:
        """Record a failed import."""
        try:
            await self.failed_imports.insert_one({
                "upload_id": ObjectId(upload_id),
                "file_path": file_path,
                "error": error,
                "line_number": line_number,
                "created_at": datetime.utcnow()
            })
        except Exception as e:
            logger.error(f"Error recording failed import: {e}")
    
    async def get_failed_imports(self, upload_id: str) -> List[Dict[str, Any]]:
        """Get failed imports for an upload."""
        try:
            return await self.failed_imports.find(
                {"upload_id": ObjectId(upload_id)}
            ).to_list(length=None)
        except Exception as e:
            logger.error(f"Error getting failed imports for upload {upload_id}: {e}")
            return []
    
    async def count_failed_imports(self, upload_id: str) -> int:
        """Count failed imports for an upload."""
        try:
            return await self.failed_imports.count_documents({"upload_id": ObjectId(upload_id)})
        except Exception as e:
            logger.error(f"Error counting failed imports for upload {upload_id}: {e}")
            return 0