"""
Importer module for Slack export files.
Uses parser.py to parse files according to ARCHITECTURE.md.
"""

import asyncio
import json
import logging
import zipfile
import tempfile
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

from app.db.models import Channel, Message, Reaction
from app.dependencies import get_database
from app.importer.parser import parse_channel_metadata, parse_dm_metadata, parse_message, ParserError

logger = logging.getLogger(__name__)

class ImportError(Exception):
    """Custom exception for import errors"""
    pass

async def process_file(db: AsyncIOMotorClient, file_path: Path, upload_id: ObjectId, sync: bool = False) -> Tuple[Channel, List[Message]]:
    """Process a single channel or DM file.

    Args:
        db: MongoDB client
        file_path: Path to file
        upload_id: ID of upload
        sync: Whether to use synchronous operations

    Returns:
        Tuple of (channel metadata, list of messages)
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = [line.rstrip("\n") for line in f.readlines()]

        # Split metadata and messages
        try:
            separator_idx = lines.index("#################################################################")
        except ValueError:
            raise ImportError(f"Invalid file format: missing separator in {file_path}")

        metadata_lines = lines[:separator_idx]
        message_lines = lines[separator_idx + 2:]  # Skip separator and "Messages:" line

        # Parse metadata
        if "Private conversation between" in metadata_lines[0]:
            channel = parse_dm_metadata(metadata_lines)
        else:
            channel = parse_channel_metadata(metadata_lines)

        # Parse messages
        messages = []
        for i, line in enumerate(message_lines, 1):
            line = line.strip()
            if not line or line.startswith("----"):  # Skip date headers
                continue

            try:
                msg = parse_message(line, i)
                if msg:
                    # Set the channel_id on the message
                    msg.channel_id = channel.id
                    messages.append(msg)
            except ParserError as e:
                # Log error but continue processing
                logger.warning(f"Error parsing message in {file_path}: {str(e)}")
                if sync:
                    db.failed_imports.insert_one({
                        "file": str(file_path),
                        "line_number": i,
                        "line": line,
                        "error": str(e),
                        "upload_id": upload_id,
                        "timestamp": datetime.utcnow()
                    })
                else:
                    await db.failed_imports.insert_one({
                        "file": str(file_path),
                        "line_number": i,
                        "line": line,
                        "error": str(e),
                        "upload_id": upload_id,
                        "timestamp": datetime.utcnow()
                    })

        return channel, messages

    except Exception as e:
        raise ImportError(f"Error processing file {file_path}: {str(e)}")

async def import_slack_export(db: AsyncIOMotorClient, extract_path: Path, upload_id: ObjectId) -> None:
    """Import a Slack export from an extracted directory.

    Args:
        db: MongoDB client
        extract_path: Path to extracted Slack export
        upload_id: ID of upload
    """
    try:
        print(f"Starting import from {extract_path}")

        # Check if extraction is complete
        upload = await db.uploads.find_one({"_id": upload_id})
        if not upload.get("extraction_complete"):
            print("Extraction not complete, waiting...")
            for _ in range(30):  # Wait up to 30 seconds
                await asyncio.sleep(1)
                upload = await db.uploads.find_one({"_id": upload_id})
                if upload.get("extraction_complete"):
                    print("Extraction complete, proceeding with import")
                    break
            else:
                raise ImportError("Extraction did not complete in time")

        # Update status to confirm we're starting
        await db.uploads.update_one(
            {"_id": upload_id},
            {"$set": {
                "status": "IMPORTING",
                "progress": "Starting import process...",
                "progress_percent": 0,
                "updated_at": datetime.utcnow()
            }}
        )

        # Process all txt files
        txt_files = list(extract_path.rglob("*.txt"))
        total_files = len(txt_files)
        processed_files = 0
        total_messages = 0

        print(f"Found {total_files} txt files")

        for txt_file in txt_files:
            # Skip non-message files
            if (txt_file.name in ["title.txt", "metadata.txt"] or
                "canvas_in_the_conversation" in str(txt_file) or
                "/shares/" in str(txt_file) or
                "/canvases/" in str(txt_file)):
                logger.info(f"Skipping non-message file: {txt_file}")
                processed_files += 1
                continue

            try:
                print(f"Processing {txt_file}")
                # Process file and store messages
                channel, messages = await process_file(db, txt_file, upload_id)

                # Store channel metadata
                print(f"Storing channel metadata for {channel.name}")
                await db.channels.insert_one(channel.model_dump())

                # Store messages in batches
                if messages:
                    print(f"Storing {len(messages)} messages")
                    await db.messages.insert_many([m.model_dump() for m in messages])
                    total_messages += len(messages)

                # Update progress
                processed_files += 1
                progress_percent = int((processed_files / total_files) * 100)

                print(f"Progress: {progress_percent}% ({processed_files}/{total_files} files, {total_messages} messages)")
                await db.uploads.update_one(
                    {"_id": upload_id},
                    {"$set": {
                        "status": "IMPORTING",
                        "progress": f"Processed {processed_files}/{total_files} files ({total_messages} messages)",
                        "progress_percent": progress_percent,
                        "updated_at": datetime.utcnow()
                    }}
                )

            except ImportError as e:
                print(f"Error importing {txt_file}: {e}")
                # Log error but continue processing
                continue

        # Update status to complete
        print("Import complete!")
        await db.uploads.update_one(
            {"_id": upload_id},
            {"$set": {
                "status": "COMPLETE",
                "progress": f"Import complete: {total_messages} messages from {total_files} files",
                "progress_percent": 100,
                "updated_at": datetime.utcnow()
            }}
        )

    except Exception as e:
        print(f"Error during import: {e}")
        # Update status to error
        await db.uploads.update_one(
            {"_id": upload_id},
            {"$set": {
                "status": "ERROR",
                "error": str(e),
                "updated_at": datetime.utcnow()
            }}
        )
        raise

async def import_slack_export_from_folder(db, extract_path: Path, upload_id: ObjectId) -> None:
    """Import a Slack export from the given path.

    Args:
        db: MongoDB client
        extract_path: Path to extracted Slack export
        upload_id: ID of upload
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

                    # Also insert into conversations collection for UI
                    conversation = {
                        "name": channel.name,
                        "type": "dm" if channel.is_dm else "channel",
                        "channel_id": channel.id,
                        "created_at": channel.created,
                        "updated_at": datetime.utcnow(),
                        "topic": channel.topic,
                        "purpose": channel.purpose,
                        "is_archived": channel.is_archived,
                        "dm_users": channel.dm_users if channel.is_dm else []
                    }
                    await db.conversations.update_one(
                        {"channel_id": channel.id},
                        {"$set": conversation},
                        upsert=True
                    )

                    # Insert messages and track users
                    if messages:
                        message_docs = []
                        for msg in messages:
                            msg_dict = msg.model_dump(by_alias=True)
                            msg_dict["_id"] = ObjectId()  # Generate new ID for each message
                            # Add conversation_id for UI
                            msg_dict["conversation_id"] = channel.id
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

                    # Also insert into conversations collection for UI
                    conversation = {
                        "name": channel.name,
                        "type": "dm" if channel.is_dm else "channel",
                        "channel_id": channel.id,
                        "created_at": channel.created,
                        "updated_at": datetime.utcnow(),
                        "topic": channel.topic,
                        "purpose": channel.purpose,
                        "is_archived": channel.is_archived,
                        "dm_users": channel.dm_users if channel.is_dm else []
                    }
                    await db.conversations.update_one(
                        {"channel_id": channel.id},
                        {"$set": conversation},
                        upsert=True
                    )

                    # Insert messages and track users
                    if messages:
                        message_docs = []
                        for msg in messages:
                            msg_dict = msg.model_dump(by_alias=True)
                            msg_dict["_id"] = ObjectId()  # Generate new ID for each message
                            # Add conversation_id for UI
                            msg_dict["conversation_id"] = channel.id
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
                    "status": "COMPLETE",
                    "progress": "Import completed successfully",
                    "progress_percent": 100,
                    "updated_at": datetime.utcnow()
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
                    "progress_percent": 0,
                    "updated_at": datetime.utcnow()
                }
            }
        )
