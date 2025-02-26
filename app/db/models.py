"""
Database models matching ARCHITECTURE.md schema exactly.
These models define the structure of our MongoDB collections.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict
from bson import ObjectId

class UploadStatus(str, Enum):
    """Status of a Slack export upload and processing"""
    UPLOADED = "UPLOADED"  # Initial state after file upload
    EXTRACTING = "EXTRACTING"  # ZIP file is being extracted
    EXTRACTED = "EXTRACTED"  # ZIP extraction complete
    IMPORTING = "IMPORTING"  # Data being imported to MongoDB
    IMPORTED = "IMPORTED"  # MongoDB import complete
    EMBEDDING = "EMBEDDING"  # Creating embeddings
    COMPLETE = "COMPLETE"  # All processing complete
    ERROR = "ERROR"  # Error in any stage

class Upload(BaseModel):
    """uploads collection - tracks file upload status"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: ObjectId = Field(alias="_id")
    filename: str
    status: UploadStatus  # Use enum instead of string
    created_at: datetime
    updated_at: datetime
    size: int
    uploaded_size: int
    error: Optional[str] = None
    progress: str
    progress_percent: int
    current_stage: Optional[str] = None  # Track which stage we're in
    stage_progress: Optional[int] = None  # Progress within current stage

class Channel(BaseModel):
    """channels collection - stores both channels and DMs"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str  # Slack channel ID (C... or D...)
    name: str  # Channel name without # or "DM: user1-user2"
    created: datetime
    creator_username: Optional[str] = None  # channels only
    topic: Optional[str] = None  # channels only
    topic_set_by: Optional[str] = None  # channels only
    topic_set_at: Optional[datetime] = None  # channels only
    purpose: Optional[str] = None  # channels only
    purpose_set_by: Optional[str] = None  # channels only
    purpose_set_at: Optional[datetime] = None  # channels only
    is_archived: bool = False
    archived_by: Optional[str] = None
    archived_at: Optional[datetime] = None
    is_dm: bool = False
    dm_users: Optional[List[str]] = None  # DMs only

class User(BaseModel):
    """users collection - basic user info from messages"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    username: str
    first_seen: datetime
    last_seen: datetime
    channels: List[str]  # channel IDs
    message_count: int = 0

class Reaction(BaseModel):
    """Nested model for message reactions"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    emoji: str
    users: List[str]

class Message(BaseModel):
    """messages collection - all message types"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: Optional[ObjectId] = Field(None, alias="_id")  # Allow None for testing
    channel_id: str = Field(default="test")  # Default for testing
    username: str
    text: str
    ts: datetime
    thread_ts: Optional[datetime] = None  # if reply
    is_edited: bool = False
    reactions: List[Reaction] = []
    type: str  # "message", "system", "archive", or "file"
    system_action: Optional[str] = None  # for system messages
    file_id: Optional[str] = None  # for file messages
    is_bot: bool = False  # for bot messages
    data: Optional[dict] = None  # for messages with JSON data

class FailedImport(BaseModel):
    """failed_imports collection - track import failures"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: ObjectId = Field(alias="_id")
    upload_id: ObjectId
    file_path: str
    error: str
    line_number: int
    created_at: datetime = Field(default_factory=datetime.utcnow)
