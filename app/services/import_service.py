"""Service for importing Slack export files."""

import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import logging
from bson import ObjectId

from app.db.models import Channel, Message
from app.importer.parser import parse_message, parse_channel_metadata, parse_dm_metadata, ParserError

logger = logging.getLogger(__name__)

class ImportService:
    """Service for importing Slack export files."""

    def __init__(self, db=None, sync_db=None):
        """Initialize the import service."""
        self.db = db
        self.sync_db = sync_db
        self.data_dir = os.getenv("DATA_DIR", "data")

    async def start_import_process(self, upload_id: str) -> Dict[str, Any]:
        """Start the import process for an extracted upload."""
        try:
            # Get the upload
            upload = await self.db.uploads.find_one({"_id": ObjectId(upload_id)})
            if not upload:
                logger.error(f"Upload not found: {upload_id}")
                return {"success": False, "error": "Upload not found"}

            # Check if the extract path exists
            extract_path = upload.get("extract_path")
            logger.info(f"Extract path from database: {extract_path}")

            # Convert to Path object and check if it exists
            extract_path_obj = Path(extract_path) if extract_path else None
            if not extract_path_obj or not extract_path_obj.exists():
                logger.error(f"Extract path does not exist: {extract_path_obj}")
                return {"success": False, "error": f"Extracted files not found at {extract_path_obj}"}

            # Update status to IMPORTING
            await self.db.uploads.update_one(
                {"_id": ObjectId(upload_id)},
                {"$set": {
                    "status": "IMPORTING",
                    "progress": "Starting import...",
                    "progress_percent": 0,
                    "updated_at": datetime.utcnow(),
                    "current_stage": "IMPORTING",
                    "stage_progress": 0
                }}
            )

            # Find the actual Slack export directory (it's usually a subdirectory)
            logger.info(f"Looking for Slack export directory in {extract_path_obj}")

            # List all directories to see what's available
            if extract_path_obj.exists():
                logger.debug("Contents of extract directory:")
                for item in extract_path_obj.iterdir():
                    logger.debug(f"  - {item} (is_dir: {item.is_dir()})")

            # Try different patterns to find the Slack export directory
            slack_export_dirs = list(extract_path_obj.glob("slack-export*")) or \
                              list(extract_path_obj.glob("*slack*")) or \
                              [d for d in extract_path_obj.iterdir() if d.is_dir()]

            if slack_export_dirs:
                logger.info(f"Found Slack export subdirectories: {slack_export_dirs}")
                extract_path_obj = slack_export_dirs[0]
                logger.info(f"Using Slack export directory: {extract_path_obj}")

            # Update status to IMPORTING
            await self.db.uploads.update_one(
                {"_id": ObjectId(upload_id)},
                {"$set": {
                    "status": "IMPORTING",
                    "progress": "Starting import process...",
                    "progress_percent": 0,
                    "updated_at": datetime.utcnow(),
                    "current_stage": "IMPORTING",
                    "stage_progress": 0
                }}
            )

            # Start the import in a separate thread
            def start_thread():
                try:
                    self.import_slack_export_sync(extract_path_obj, upload_id)
                except Exception as e:
                    logger.error(f"Error in import thread: {e}", exc_info=True)

            threading.Thread(name=f"import-{upload_id}", target=start_thread, daemon=True).start()
            logger.info(f"Started import thread for {upload_id}")

            return {"success": True, "message": "Import started successfully"}
        except Exception as e:
            logger.error(f"Error in start_import_process: {str(e)}", exc_info=True)
            # Update status to ERROR
            await self.db.uploads.update_one(
                {"_id": ObjectId(upload_id)},
                {"$set": {
                    "status": "ERROR",
                    "progress": f"Error: {str(e)}",
                    "updated_at": datetime.utcnow(),
                    "error": str(e)
                }}
            )
            return {"success": False, "error": str(e)}

    def import_slack_export_sync(self, extract_path: Path, upload_id: str):
        """Import a Slack export file - synchronous version."""
        logger.info(f"=== IMPORT_SLACK_EXPORT_SYNC STARTED FOR {upload_id} ===")
        logger.info(f"Importing from {extract_path}, exists: {extract_path.exists()}")

        # Convert upload_id to ObjectId if it's a string
        upload_id_obj = ObjectId(upload_id) if isinstance(upload_id, str) else upload_id

        # Update status to IMPORTING
        try:
            self.sync_db.uploads.update_one(
                {"_id": upload_id_obj},
                {"$set": {
                    "status": "IMPORTING",
                    "progress": "Starting import process...",
                    "progress_percent": 0,
                    "updated_at": datetime.utcnow()
                }}
            )
            logger.info("Updated status to IMPORTING")
        except Exception as e:
            logger.error(f"Error updating status to IMPORTING: {e}", exc_info=True)

        # Get list of channel files
        try:
            # Only include files from channels and dms directories, skip files directory
            channel_files = []

            # Process channels directory
            channels_dir = extract_path / "channels"
            if channels_dir.exists() and channels_dir.is_dir():
                logger.info(f"Processing channels directory: {channels_dir}")
                channel_files.extend(list(channels_dir.rglob("*.txt")))

            # Process dms directory
            dms_dir = extract_path / "dms"
            if dms_dir.exists() and dms_dir.is_dir():
                logger.info(f"Processing dms directory: {dms_dir}")
                channel_files.extend(list(dms_dir.rglob("*.txt")))

            # Filter out non-message files
            filtered_channel_files = []
            for file in channel_files:
                if (file.name in ["title.txt", "metadata.txt"] or
                    "canvas_in_the_conversation" in str(file) or
                    "/shares/" in str(file) or
                    "/canvases/" in str(file) or
                    "/files/" in str(file)):
                    logger.info(f"Skipping non-message file: {file}")
                    continue
                filtered_channel_files.append(file)

            channel_files = filtered_channel_files
            total_files = len(channel_files)
            logger.info(f"Found {total_files} channel files after filtering in channels and dms directories")

            if total_files == 0:
                logger.warning(f"No channel files found in channels or dms directories")
                # List the directory contents to debug
                logger.debug(f"Directory contents of {extract_path}:")
                for item in extract_path.iterdir():
                    logger.debug(f"  - {item} (is_dir: {item.is_dir()}, exists: {item.exists()})")

                    # If it's a directory, check its contents too
                    if item.is_dir():
                        logger.debug(f"    Contents of {item}:")
                        try:
                            for subitem in item.iterdir():
                                logger.debug(f"      - {subitem}")
                        except Exception as e:
                            logger.error(f"      Error listing contents: {e}")
        except Exception as e:
            logger.error(f"Error getting channel files: {e}", exc_info=True)
            total_files = 0
            channel_files = []

        # Process each channel file
        total_messages = 0
        users = {}  # Track users across all files
        processed_files = 0

        for i, channel_file in enumerate(channel_files):
            logger.info(f"Processing file {i+1}/{total_files}: {channel_file}")
            try:
                # Process the file using the synchronous version
                logger.debug(f"Calling process_file_sync for {channel_file}")
                channel, messages = self.process_file_sync(channel_file, upload_id_obj)
                logger.info(f"Successfully processed {channel_file}, got channel {channel.name} with {len(messages)} messages")

                # Store channel metadata
                logger.debug(f"Storing channel metadata for {channel.name}")
                result = self.sync_db.channels.insert_one(channel.model_dump())
                logger.debug(f"Channel inserted with ID: {result.inserted_id}")

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
                self.sync_db.conversations.update_one(
                    {"channel_id": channel.id},
                    {"$set": conversation},
                    upsert=True
                )
                logger.debug(f"Conversation inserted for UI")

                # Store messages in batches
                if messages:
                    logger.debug(f"Storing {len(messages)} messages")
                    # Add conversation_id to messages for UI
                    message_docs = []
                    for msg in messages:
                        msg_dict = msg.model_dump()
                        msg_dict["conversation_id"] = channel.id
                        message_docs.append(msg_dict)

                        # Track users
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

                    result = self.sync_db.messages.insert_many(message_docs)
                    logger.debug(f"Inserted {len(result.inserted_ids)} messages")
                    total_messages += len(messages)

                # Update progress
                percent = int(((i + 1) / total_files) * 100)
                self.sync_db.uploads.update_one(
                    {"_id": upload_id_obj},
                    {"$set": {
                        "progress": f"Importing channels... {percent}% ({total_messages} messages)",
                        "progress_percent": percent,
                        "stage_progress": percent,
                        "updated_at": datetime.utcnow()
                    }}
                )
                logger.debug(f"Updated progress: {percent}%")
                processed_files += 1
            except Exception as e:
                logger.error(f"Error processing {channel_file}: {e}", exc_info=True)
                # Log the error but continue with other files
                self.sync_db.failed_imports.insert_one({
                    "upload_id": upload_id_obj,
                    "file": str(channel_file),
                    "error": str(e),
                    "timestamp": datetime.utcnow()
                })

        logger.info(f"Processed {processed_files}/{total_files} files with {total_messages} messages")

        # Insert/update users
        for username, user in users.items():
            self.sync_db.users.update_one(
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
            logger.debug(f"User {username} inserted/updated")

        # Update status to IMPORTED
        try:
            self.sync_db.uploads.update_one(
                {"_id": upload_id_obj},
                {"$set": {
                    "status": "IMPORTED",
                    "progress": f"Import complete: {total_messages} messages from {total_files} files",
                    "progress_percent": 100,
                    "updated_at": datetime.utcnow()
                }}
            )
            logger.info(f"Updated status to IMPORTED. Processed {total_files} files with {total_messages} messages.")
        except Exception as e:
            logger.error(f"Error updating status to IMPORTED: {e}", exc_info=True)

        logger.info(f"=== IMPORT_SLACK_EXPORT_SYNC COMPLETED FOR {upload_id} ===")

    def process_file_sync(self, file_path: Path, upload_id: ObjectId) -> Tuple[Channel, List[Message]]:
        """Process a single Slack export file.

        Args:
            file_path: Path to file
            upload_id: ID of upload

        Returns:
            Tuple of (channel metadata, list of messages)
        """
        try:
            logger.debug(f"Processing {file_path}")
            logger.debug(f"File exists: {file_path.exists()}, size: {file_path.stat().st_size if file_path.exists() else 'N/A'}")

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    lines = [line.rstrip("\n") for line in f.readlines()]
                logger.debug(f"Read {len(lines)} lines from {file_path}")
            except UnicodeDecodeError:
                logger.warning(f"Unicode decode error, trying with errors='replace'")
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    lines = [line.rstrip("\n") for line in f.readlines()]
                logger.debug(f"Read {len(lines)} lines with error replacement")

            # Split metadata and messages
            try:
                separator_idx = lines.index("#################################################################")
                logger.debug(f"Found separator at line {separator_idx}")
            except ValueError:
                logger.error(f"No separator found in {file_path}, first 10 lines: {lines[:10]}")
                # This might be a non-message file, skip it
                raise ImportError(f"Invalid file format: missing separator in {file_path}, might not be a message file")

            metadata_lines = lines[:separator_idx]
            message_lines = lines[separator_idx + 2:]  # Skip separator and "Messages:" line
            logger.debug(f"Metadata lines: {len(metadata_lines)}, Message lines: {len(message_lines)}")

            # Parse metadata
            try:
                if metadata_lines and "Private conversation between" in metadata_lines[0]:
                    logger.debug("Parsing DM metadata")
                    channel = parse_dm_metadata(metadata_lines)
                else:
                    logger.debug("Parsing channel metadata")
                    channel = parse_channel_metadata(metadata_lines)
                logger.debug(f"Parsed channel: {channel.name}, ID: {channel.id}")
            except Exception as e:
                logger.error(f"Error parsing metadata: {e}", exc_info=True)
                raise ImportError(f"Error parsing metadata: {e}")

            # Parse messages
            messages = []
            if message_lines:
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
                        logger.warning(f"Error parsing message in {file_path} at line {i}: {str(e)}")
                        try:
                            self.sync_db.failed_imports.insert_one({
                                "file": str(file_path),
                                "line_number": i,
                                "line": line,
                                "error": str(e),
                                "upload_id": upload_id,
                                "timestamp": datetime.utcnow()
                            })
                        except Exception as db_err:
                            logger.error(f"Error logging failed message: {db_err}")

            logger.debug(f"Parsed {len(messages)} messages from {file_path}")

            return channel, messages

        except Exception as e:
            logger.error(f"Error processing file {file_path}: {str(e)}", exc_info=True)
            raise ImportError(f"Error processing file {file_path}: {str(e)}")
