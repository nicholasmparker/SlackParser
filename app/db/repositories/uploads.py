"""Repository for upload-related database operations."""

from datetime import datetime
from typing import Dict, Any, List, Optional
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)

class UploadRepository:
    """Repository for upload-related database operations."""
    
    def __init__(self, db):
        """Initialize the repository with a database connection."""
        self.db = db
        self.collection = db.uploads
    
    async def find_by_id(self, upload_id: str) -> Optional[Dict[str, Any]]:
        """Find an upload by ID."""
        try:
            return await self.collection.find_one({"_id": ObjectId(upload_id)})
        except Exception as e:
            logger.error(f"Error finding upload {upload_id}: {e}")
            return None
    
    async def update_status(self, upload_id: str, status: str, progress: str, 
                           progress_percent: int) -> None:
        """Update the status of an upload."""
        try:
            await self.collection.update_one(
                {"_id": ObjectId(upload_id)},
                {"$set": {
                    "status": status,
                    "progress": progress,
                    "progress_percent": progress_percent,
                    "updated_at": datetime.utcnow()
                }}
            )
        except Exception as e:
            logger.error(f"Error updating upload status {upload_id}: {e}")
    
    async def update_extract_path(self, upload_id: str, extract_path: str) -> None:
        """Update the extract path of an upload."""
        try:
            await self.collection.update_one(
                {"_id": ObjectId(upload_id)},
                {"$set": {
                    "extract_path": extract_path,
                    "updated_at": datetime.utcnow()
                }}
            )
        except Exception as e:
            logger.error(f"Error updating extract path for upload {upload_id}: {e}")
    
    async def update_stage(self, upload_id: str, stage: str, progress: int) -> None:
        """Update the current stage and progress of an upload."""
        try:
            await self.collection.update_one(
                {"_id": ObjectId(upload_id)},
                {"$set": {
                    "current_stage": stage,
                    "stage_progress": progress,
                    "updated_at": datetime.utcnow()
                }}
            )
        except Exception as e:
            logger.error(f"Error updating stage for upload {upload_id}: {e}")
    
    async def update_error(self, upload_id: str, error: str) -> None:
        """Update the error message of an upload."""
        try:
            await self.collection.update_one(
                {"_id": ObjectId(upload_id)},
                {"$set": {
                    "status": "ERROR",
                    "error": error,
                    "updated_at": datetime.utcnow()
                }}
            )
        except Exception as e:
            logger.error(f"Error updating error for upload {upload_id}: {e}")
    
    async def list_all(self) -> List[Dict[str, Any]]:
        """List all uploads."""
        try:
            return await self.collection.find().sort("created_at", -1).to_list(length=None)
        except Exception as e:
            logger.error(f"Error listing uploads: {e}")
            return []
    
    async def create(self, filename: str, size: int) -> str:
        """Create a new upload."""
        try:
            now = datetime.utcnow()
            result = await self.collection.insert_one({
                "filename": filename,
                "status": "UPLOADED",
                "created_at": now,
                "updated_at": now,
                "size": size,
                "uploaded_size": size,
                "progress": "Upload complete. Click play to start extraction.",
                "progress_percent": 0,
                "current_stage": "UPLOADED",
                "stage_progress": 100
            })
            return str(result.inserted_id)
        except Exception as e:
            logger.error(f"Error creating upload: {e}")
            raise e