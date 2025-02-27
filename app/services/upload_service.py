"""Service for handling file uploads."""

import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from bson import ObjectId
from fastapi import UploadFile, HTTPException
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)

class UploadService:
    """Service for handling file uploads."""
    
    def __init__(self, db=None, sync_db=None):
        """Initialize the upload service."""
        self.db = db
        self.sync_db = sync_db
        self.upload_dir = os.getenv("UPLOAD_DIR", "/data/uploads")
        
    async def upload_file(self, file: UploadFile) -> Dict[str, Any]:
        """Handle file upload.
        
        Args:
            file: The uploaded file
            
        Returns:
            Dict with upload ID and status
            
        Raises:
            HTTPException: If upload fails
        """
        file_path = None
        upload_id = None
        
        try:
            logger.info(f"Starting upload of {file.filename}")

            # Validate file
            if not file.filename or not file.filename.lower().endswith('.zip'):
                raise HTTPException(status_code=400, detail="Only ZIP files are allowed")

            # Create upload record
            upload_id = ObjectId()
            await self.db.uploads.insert_one({
                "_id": upload_id,
                "filename": file.filename,
                "status": "UPLOADING",
                "created_at": datetime.utcnow(),
                "size": 0,
                "uploaded_size": 0
            })

            logger.info(f"Created upload record with ID {upload_id}")

            # Ensure upload directory exists
            os.makedirs(self.upload_dir, exist_ok=True)

            # Save file with unique name to avoid conflicts
            safe_filename = f"{upload_id}_{secure_filename(file.filename)}"
            file_path = os.path.join(self.upload_dir, safe_filename)

            # Save file in chunks to handle large files
            total_size = 0
            last_update = 0

            with open(file_path, "wb") as buffer:
                while True:
                    chunk = await file.read(8 * 1024 * 1024)  # 8MB chunks
                    if not chunk:
                        break

                    buffer.write(chunk)
                    total_size += len(chunk)

                    # Only update DB every 100MB to reduce load
                    if total_size - last_update > 100 * 1024 * 1024:
                        await self.db.uploads.update_one(
                            {"_id": upload_id},
                            {"$set": {
                                "uploaded_size": total_size,
                                "updated_at": datetime.utcnow()
                            }}
                        )
                        last_update = total_size

            # Update final status
            await self.db.uploads.update_one(
                {"_id": upload_id},
                {"$set": {
                    "status": "UPLOADED",
                    "size": total_size,
                    "uploaded_size": total_size,
                    "file_path": str(file_path),
                    "updated_at": datetime.utcnow()
                }}
            )

            logger.info(f"Upload complete: {total_size} bytes")

            return {
                "id": str(upload_id),
                "status": "UPLOADED",
                "size": total_size
            }

        except Exception as e:
            logger.error(f"Upload error: {str(e)}", exc_info=True)
            
            # Clean up file if it was created
            if file_path:
                try:
                    os.unlink(file_path)
                except FileNotFoundError:
                    logger.warning(f"Could not delete file {file_path}, it does not exist")
            
            # Clean up database record if it was created
            if upload_id:
                try:
                    await self.db.uploads.delete_one({"_id": upload_id})
                except Exception as db_err:
                    logger.error(f"Error deleting upload record: {db_err}")
            
            raise HTTPException(status_code=500, detail=str(e))
    
    async def get_upload(self, upload_id: str) -> Optional[Dict[str, Any]]:
        """Get upload by ID.
        
        Args:
            upload_id: The upload ID
            
        Returns:
            Upload record or None if not found
        """
        try:
            upload = await self.db.uploads.find_one({"_id": ObjectId(upload_id)})
            if upload:
                upload["id"] = str(upload["_id"])
            return upload
        except Exception as e:
            logger.error(f"Error getting upload {upload_id}: {e}", exc_info=True)
            return None
    
    async def delete_upload(self, upload_id: str) -> bool:
        """Delete upload by ID.
        
        Args:
            upload_id: The upload ID
            
        Returns:
            True if deleted, False otherwise
        """
        try:
            # Get the upload to find the file path
            upload = await self.db.uploads.find_one({"_id": ObjectId(upload_id)})
            if not upload:
                return False
            
            # Delete the file if it exists
            file_path = upload.get("file_path")
            if file_path:
                try:
                    os.unlink(file_path)
                    logger.info(f"Deleted file {file_path}")
                except FileNotFoundError:
                    logger.warning(f"Could not delete file {file_path}, it does not exist")
            
            # Delete the extract directory if it exists
            extract_path = upload.get("extract_path")
            if extract_path:
                try:
                    import shutil
                    shutil.rmtree(extract_path)
                    logger.info(f"Deleted extract directory {extract_path}")
                except FileNotFoundError:
                    logger.warning(f"Could not delete extract directory {extract_path}, it does not exist")
            
            # Delete the upload record
            result = await self.db.uploads.delete_one({"_id": ObjectId(upload_id)})
            if result.deleted_count > 0:
                logger.info(f"Deleted upload record {upload_id}")
                return True
            
            return False
        except Exception as e:
            logger.error(f"Error deleting upload {upload_id}: {e}", exc_info=True)
            return False
    
    async def list_uploads(self, limit: int = 100) -> list:
        """List all uploads.
        
        Args:
            limit: Maximum number of uploads to return
            
        Returns:
            List of upload records
        """
        try:
            uploads = await self.db.uploads.find().sort("created_at", -1).limit(limit).to_list(length=limit)
            for upload in uploads:
                upload["id"] = str(upload["_id"])
            return uploads
        except Exception as e:
            logger.error(f"Error listing uploads: {e}", exc_info=True)
            return []
