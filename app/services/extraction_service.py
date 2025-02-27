"""Service for extracting Slack export files."""

import os
import zipfile
import shutil
from pathlib import Path
from datetime import datetime
from bson import ObjectId
from typing import Any, Optional
import logging

logger = logging.getLogger(__name__)

class ExtractionService:
    """Service for extracting Slack export files."""
    
    def __init__(self, db=None, sync_db=None):
        """Initialize the extraction service."""
        self.db = db
        self.sync_db = sync_db
        self.data_dir = os.getenv("DATA_DIR", "data")
    
    def get_zip_total_size(self, zip_path: str) -> int:
        """Get the total uncompressed size of all files in the ZIP."""
        logger.info(f"Calculating total size of {zip_path}")
        total = 0
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for info in zip_ref.infolist():
                total += info.file_size
        logger.info(f"Total size: {total} bytes")
        return total
    
    async def extract_with_progress(self, zip_path: str, extract_dir: Path, upload_id: str) -> Path:
        """Extract ZIP file with progress updates - async version."""
        logger.info(f"Starting async extraction from {zip_path} to {extract_dir}")
        
        # Convert upload_id to ObjectId if it's a string
        upload_id_obj = ObjectId(upload_id) if isinstance(upload_id, str) else upload_id
        
        # Get total size
        total_size = self.get_zip_total_size(zip_path)
        extracted_size = 0
        
        # Create extract directory if it doesn't exist
        os.makedirs(extract_dir, exist_ok=True)
        
        # Update status to EXTRACTING
        await self.db.uploads.update_one(
            {"_id": upload_id_obj},
            {"$set": {
                "status": "EXTRACTING",
                "progress": "Starting extraction...",
                "progress_percent": 0,
                "updated_at": datetime.utcnow(),
                "current_stage": "EXTRACTING",
                "stage_progress": 0
            }}
        )
        
        # Extract files
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for file_info in zip_ref.infolist():
                logger.debug(f"Extracting {file_info.filename}")
                zip_ref.extract(file_info, extract_dir)
                extracted_size += file_info.file_size
                percent = int((extracted_size / total_size) * 100)
                
                # Update progress every 5%
                if percent % 5 == 0:
                    logger.debug(f"Extraction progress: {percent}%")
                    await self.db.uploads.update_one(
                        {"_id": upload_id_obj},
                        {"$set": {
                            "status": "EXTRACTING",
                            "progress": f"Extracting... {percent}%",
                            "progress_percent": percent,
                            "updated_at": datetime.utcnow(),
                            "stage_progress": percent
                        }}
                    )
        
        logger.info("Extraction complete")
        
        # Update status to EXTRACTED when complete
        await self.db.uploads.update_one(
            {"_id": upload_id_obj},
            {"$set": {
                "status": "EXTRACTED",
                "progress": "Extraction complete. Click play to start importing.",
                "progress_percent": 100,
                "updated_at": datetime.utcnow(),
                "current_stage": "EXTRACTED",
                "stage_progress": 100,
                "extract_path": str(extract_dir)
            }}
        )
        
        return extract_dir
    
    def extract_with_progress_sync(self, zip_path: str, extract_path: Path, upload_id: str) -> Path:
        """Extract ZIP file with progress updates - sync version."""
        logger.info(f"Starting sync extraction from {zip_path} to {extract_path}")
        
        # Convert upload_id to ObjectId if it's a string
        upload_id_obj = ObjectId(upload_id) if isinstance(upload_id, str) else upload_id
        
        # Get total size
        total_size = self.get_zip_total_size(zip_path)
        extracted_size = 0
        
        # Create extract directory if it doesn't exist
        os.makedirs(extract_path, exist_ok=True)
        
        # Update status to EXTRACTING
        self.sync_db.uploads.update_one(
            {"_id": upload_id_obj},
            {"$set": {
                "status": "EXTRACTING",
                "progress": "Starting extraction...",
                "progress_percent": 0,
                "updated_at": datetime.utcnow(),
                "current_stage": "EXTRACTING",
                "stage_progress": 0
            }}
        )
        
        # Extract files
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for file_info in zip_ref.infolist():
                logger.debug(f"Extracting {file_info.filename}")
                zip_ref.extract(file_info, extract_path)
                extracted_size += file_info.file_size
                percent = int((extracted_size / total_size) * 100)
                
                # Update progress every 5%
                if percent % 5 == 0:
                    logger.debug(f"Extraction progress: {percent}%")
                    self.sync_db.uploads.update_one(
                        {"_id": upload_id_obj},
                        {"$set": {
                            "progress": f"Extracting... {percent}%",
                            "progress_percent": percent,
                            "stage_progress": percent,
                            "updated_at": datetime.utcnow()
                        }}
                    )
        
        logger.info("Extraction complete")
        
        # Update status to EXTRACTED when complete
        self.sync_db.uploads.update_one(
            {"_id": upload_id_obj},
            {"$set": {
                "status": "EXTRACTED",
                "progress": "Extraction complete. Click play to start importing.",
                "progress_percent": 100,
                "updated_at": datetime.utcnow(),
                "current_stage": "EXTRACTED",
                "stage_progress": 100,
                "extract_path": str(extract_path)
            }}
        )
        
        return extract_path
    
    def get_extract_path(self, upload_id: str) -> Path:
        """Get the extract path for an upload."""
        return Path(self.data_dir) / "extracts" / upload_id