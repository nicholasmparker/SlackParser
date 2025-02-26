"""
Import module for handling Slack exports.
Uses parser module to process files according to ARCHITECTURE.md.
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId

from app.db.models import Channel, Message, Upload, FailedImport
from app.importer.parser import parse_channel_metadata, parse_dm_metadata, parse_message, ParserError

logger = logging.getLogger(__name__)

class ImportError(Exception):
    """Custom exception for import errors"""
    pass

async def process_file(db: AsyncIOMotorClient, file_path: Path, upload_id: ObjectId) -> Tuple[Channel, List[Message]]:
    """Process a single channel or DM file.
    Returns the channel/DM metadata and list of messages.
    """
    try:
        lines = file_path.read_text().splitlines()
        
        # Find metadata section
        metadata_end = -1
        for i, line in enumerate(lines):
            if line.startswith("#" * 65):
                metadata_end = i
                break
        if metadata_end == -1:
            raise ImportError("Could not find metadata section")
            
        # Parse metadata
        metadata_lines = lines[:metadata_end]
        is_dm = "Private conversation between" in metadata_lines[0]
        channel = parse_dm_metadata(metadata_lines) if is_dm else parse_channel_metadata(metadata_lines)
        
        # Find messages section
        messages_start = -1
        for i, line in enumerate(lines[metadata_end:], metadata_end):
            if line.strip() == "Messages:":
                messages_start = i + 1
                break
        if messages_start == -1:
            raise ImportError("Could not find messages section")
            
        # Parse messages
        messages = []
        current_message = None
        
        for i, line in enumerate(lines[messages_start:], messages_start):
            # Skip date headers
            if line.startswith("----"):
                continue
                
            # Skip empty lines
            if not line.strip():
                continue
                
            # Handle reactions (indented lines starting with :)
            if line.startswith("    :"):
                if current_message:
                    emoji = line.strip()[1:].split(":")[0]
                    username = line.strip().split(" ", 1)[1].strip()
                    reaction = next((r for r in current_message.reactions if r.emoji == emoji), None)
                    if reaction:
                        reaction.users.append(username)
                    else:
                        current_message.reactions.append({"emoji": emoji, "users": [username]})
                continue
                
            # Parse new message
            try:
                message = parse_message(line, i)
                if message:
                    message.channel_id = channel.id
                    messages.append(message)
                    current_message = message
            except ParserError as e:
                # Log error but continue processing
                logger.warning(f"Error parsing message in {file_path}: {str(e)}")
                await db.failed_imports.insert_one({
                    "_id": ObjectId(),
                    "upload_id": upload_id,
                    "file_path": str(file_path),
                    "error": str(e),
                    "line_number": e.line_number,
                    "created_at": datetime.utcnow()
                })
                
        return channel, messages
        
    except Exception as e:
        raise ImportError(f"Error processing file {file_path}: {str(e)}")

async def import_slack_export(db: AsyncIOMotorClient, extract_path: Path, upload_id: ObjectId) -> None:
    """Import a Slack export from the given path.
    Follows the exact structure specified in ARCHITECTURE.md.
    """
    try:
        # Update upload status
        await db.uploads.update_one(
            {"_id": upload_id},
            {"$set": {"status": "IMPORTING", "progress": "Starting import..."}}
        )
        
        channels_path = extract_path / "channels"
        dms_path = extract_path / "dms"
        
        # Track unique users for user collection
        users: Dict[str, dict] = {}
        
        # Process channels
        if channels_path.exists():
            channel_count = len(list(channels_path.glob("*/*.txt")))
            for i, file_path in enumerate(channels_path.glob("*/*.txt")):
                try:
                    channel, messages = await process_file(db, file_path, upload_id)
                    
                    # Insert/update channel
                    await db.channels.update_one(
                        {"id": channel.id},
                        {"$set": channel.model_dump()},
                        upsert=True
                    )
                    
                    # Insert messages and track users
                    if messages:
                        message_docs = []
                        for msg in messages:
                            msg_dict = msg.model_dump(by_alias=True)
                            msg_dict["_id"] = ObjectId()  # Generate new ID for each message
                            message_docs.append(msg_dict)
                            
                            if msg.username not in users:
                                users[msg.username] = {
                                    "username": msg.username,
                                    "first_seen": msg.ts,
                                    "last_seen": msg.ts,
                                    "channels": {channel.id},
                                    "message_count": 1
                                }
                            else:
                                user = users[msg.username]
                                user["first_seen"] = min(user["first_seen"], msg.ts)
                                user["last_seen"] = max(user["last_seen"], msg.ts)
                                user["channels"].add(channel.id)
                                user["message_count"] += 1
                                
                        await db.messages.insert_many(message_docs)
                                
                    # Update progress
                    progress = f"Processed channel {i+1}/{channel_count}: {channel.name}"
                    progress_percent = int((i + 1) / channel_count * 100)
                    await db.uploads.update_one(
                        {"_id": upload_id},
                        {
                            "$set": {
                                "progress": progress,
                                "progress_percent": progress_percent
                            }
                        }
                    )
                    
                except Exception as e:
                    logger.error(f"Error processing channel {file_path}: {str(e)}")
                    await db.failed_imports.insert_one({
                        "_id": ObjectId(),
                        "upload_id": upload_id,
                        "file_path": str(file_path),
                        "error": str(e),
                        "line_number": 0,
                        "created_at": datetime.utcnow()
                    })
                    
        # Process DMs
        if dms_path.exists():
            dm_count = len(list(dms_path.glob("*/*.txt")))
            for i, file_path in enumerate(dms_path.glob("*/*.txt")):
                try:
                    channel, messages = await process_file(db, file_path, upload_id)
                    
                    # Insert/update DM channel
                    await db.channels.update_one(
                        {"id": channel.id},
                        {"$set": channel.model_dump()},
                        upsert=True
                    )
                    
                    # Insert messages and track users
                    if messages:
                        message_docs = []
                        for msg in messages:
                            msg_dict = msg.model_dump(by_alias=True)
                            msg_dict["_id"] = ObjectId()  # Generate new ID for each message
                            message_docs.append(msg_dict)
                            
                            if msg.username not in users:
                                users[msg.username] = {
                                    "username": msg.username,
                                    "first_seen": msg.ts,
                                    "last_seen": msg.ts,
                                    "channels": {channel.id},
                                    "message_count": 1
                                }
                            else:
                                user = users[msg.username]
                                user["first_seen"] = min(user["first_seen"], msg.ts)
                                user["last_seen"] = max(user["last_seen"], msg.ts)
                                user["channels"].add(channel.id)
                                user["message_count"] += 1
                                
                        await db.messages.insert_many(message_docs)
                                
                    # Update progress
                    progress = f"Processed DM {i+1}/{dm_count}: {channel.name}"
                    progress_percent = int((i + 1) / dm_count * 100)
                    await db.uploads.update_one(
                        {"_id": upload_id},
                        {
                            "$set": {
                                "progress": progress,
                                "progress_percent": progress_percent
                            }
                        }
                    )
                    
                except Exception as e:
                    logger.error(f"Error processing DM {file_path}: {str(e)}")
                    await db.failed_imports.insert_one({
                        "_id": ObjectId(),
                        "upload_id": upload_id,
                        "file_path": str(file_path),
                        "error": str(e),
                        "line_number": 0,
                        "created_at": datetime.utcnow()
                    })
                    
        # Insert/update users
        for username, user in users.items():
            await db.users.update_one(
                {"username": username},
                {
                    "$set": {
                        "username": username,
                        "first_seen": user["first_seen"],
                        "last_seen": user["last_seen"],
                        "channels": list(user["channels"]),
                        "message_count": user["message_count"]
                    }
                },
                upsert=True
            )
            
        # Update upload status
        await db.uploads.update_one(
            {"_id": upload_id},
            {
                "$set": {
                    "status": "COMPLETED",
                    "progress": "Import completed successfully",
                    "progress_percent": 100
                }
            }
        )
        
    except Exception as e:
        logger.error(f"Import failed: {str(e)}")
        await db.uploads.update_one(
            {"_id": upload_id},
            {
                "$set": {
                    "status": "FAILED",
                    "error": str(e),
                    "progress": "Import failed",
                    "progress_percent": 0
                }
            }
        )
