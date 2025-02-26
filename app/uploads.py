from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId

# Upload status model
class UploadStatus:
    UPLOADING = "UPLOADING"
    UPLOADED = "UPLOADED"
    VALIDATING = "VALIDATING"
    EXTRACTING = "EXTRACTING"
    IMPORTING = "IMPORTING"
    TRAINING = "TRAINING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class UploadDetails(BaseModel):
    filename: str
    size: int
    uploaded_size: int = 0
    chunks_total: int = 0
    chunks_uploaded: int = 0
    channels_total: Optional[int] = None
    channels_processed: Optional[int] = None
    messages_total: Optional[int] = None
    messages_processed: Optional[int] = None
    current_channel: Optional[str] = None

class Upload(BaseModel):
    id: str
    status: str
    details: UploadDetails
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime

async def create_upload(db: AsyncIOMotorClient, filename: str, size: int, chunk_size: int) -> Upload:
    """Create a new upload record"""
    chunks_total = (size + chunk_size - 1) // chunk_size

    upload = {
        "status": UploadStatus.UPLOADING,
        "details": {
            "filename": filename,
            "size": size,
            "uploaded_size": 0,
            "chunks_total": chunks_total,
            "chunks_uploaded": 0
        },
        "created_at": datetime.now(),
        "updated_at": datetime.now()
    }

    result = await db.uploads.insert_one(upload)
    upload["id"] = str(result.inserted_id)
    return Upload(**upload)

async def update_upload_progress(db: AsyncIOMotorClient, upload_id: str, uploaded_size: int, chunks_uploaded: int):
    """Update upload progress"""
    await db.uploads.update_one(
        {"_id": ObjectId(upload_id)},
        {
            "$set": {
                "details.uploaded_size": uploaded_size,
                "details.chunks_uploaded": chunks_uploaded,
                "updated_at": datetime.now()
            }
        }
    )

async def get_upload(db: AsyncIOMotorClient, upload_id: str) -> Optional[Upload]:
    """Get upload status"""
    upload = await db.uploads.find_one({"_id": ObjectId(upload_id)})
    if upload:
        upload["id"] = str(upload["_id"])
        return Upload(**upload)
    return None

async def update_upload_status(
    db: AsyncIOMotorClient,
    upload_id: str,
    status: str,
    error: Optional[str] = None,
    **details
):
    """Update upload status and details"""
    update = {
        "status": status,
        "updated_at": datetime.now()
    }

    if error:
        update["error"] = error

    if details:
        for key, value in details.items():
            update[f"details.{key}"] = value

    await db.uploads.update_one(
        {"_id": ObjectId(upload_id)},
        {"$set": update}
    )

async def list_uploads(db: AsyncIOMotorClient, limit: int = 10) -> list[Upload]:
    """List recent uploads"""
    uploads = []
    cursor = db.uploads.find().sort("created_at", -1).limit(limit)
    async for upload in cursor:
        upload["id"] = str(upload["_id"])
        uploads.append(Upload(**upload))
    return uploads
