"""
Parser module for Slack export files.
Handles exact formats specified in ARCHITECTURE.md.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.db.models import Channel, Message, Reaction

class ParserError(Exception):
    """Custom exception for parsing errors"""
    def __init__(self, message: str, line_number: int):
        self.message = message
        self.line_number = line_number
        super().__init__(f"Line {line_number}: {message}")

def parse_timestamp(timestamp_str: str) -> datetime:
    """Parse timestamp in format YYYY-MM-DD HH:MM:SS UTC"""
    try:
        return datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S UTC")
    except ValueError as e:
        raise ParserError(f"Invalid timestamp format: {timestamp_str}", 0)

def parse_channel_metadata(lines: List[str]) -> Channel:
    """Parse channel metadata from header lines.
    Format:
    Channel Name: #{channel-name}
    Channel ID: {C...}
    Created: {YYYY-MM-DD HH:MM:SS} UTC by {username}
    Type: Channel
    Topic: "{topic text}", set on {YYYY-MM-DD HH:MM:SS} UTC by {username}
    Purpose: "{purpose text}", set on {YYYY-MM-DD HH:MM:SS} UTC by {username}
    """
    metadata = {}
    for i, line in enumerate(lines):
        try:
            if line.startswith("Channel Name: #"):
                metadata["name"] = line.split("#", 1)[1].strip()
            elif line.startswith("Channel ID: "):
                metadata["id"] = line.split(": ", 1)[1].strip()
            elif line.startswith("Created: "):
                # Format: Created: 2023-01-01 12:00:00 UTC by username
                created_parts = line.split(": ", 1)[1].split(" by ")
                metadata["created"] = parse_timestamp(created_parts[0])
                metadata["creator_username"] = created_parts[1].strip()
            elif line.startswith("Topic: "):
                # Format: Topic: "text", set on YYYY-MM-DD HH:MM:SS UTC by username
                topic_parts = line.split('"', 2)
                if len(topic_parts) >= 2:
                    metadata["topic"] = topic_parts[1].strip()
                    set_info = topic_parts[2].strip(", ").split(" by ")
                    if len(set_info) == 2:
                        metadata["topic_set_at"] = parse_timestamp(set_info[0].split("set on ")[1])
                        metadata["topic_set_by"] = set_info[1].strip()
            elif line.startswith("Purpose: "):
                # Format: Purpose: "text", set on YYYY-MM-DD HH:MM:SS UTC by username
                purpose_parts = line.split('"', 2)
                if len(purpose_parts) >= 2:
                    metadata["purpose"] = purpose_parts[1].strip()
                    set_info = purpose_parts[2].strip(", ").split(" by ")
                    if len(set_info) == 2:
                        metadata["purpose_set_at"] = parse_timestamp(set_info[0].split("set on ")[1])
                        metadata["purpose_set_by"] = set_info[1].strip()
        except Exception as e:
            raise ParserError(f"Error parsing channel metadata: {str(e)}", i)

    return Channel(
        id=metadata["id"],
        name=metadata["name"],
        created=metadata["created"],
        creator_username=metadata.get("creator_username"),
        topic=metadata.get("topic"),
        topic_set_by=metadata.get("topic_set_by"),
        topic_set_at=metadata.get("topic_set_at"),
        purpose=metadata.get("purpose"),
        purpose_set_by=metadata.get("purpose_set_by"),
        purpose_set_at=metadata.get("purpose_set_at"),
        is_dm=False
    )

def parse_dm_metadata(lines: List[str]) -> Channel:
    """Parse DM metadata from header lines.
    Format:
    Private conversation between {user1}, {user2}
    Channel ID: {D...}
    Created: {YYYY-MM-DD HH:MM:SS} UTC
    Type: Direct Message
    """
    metadata = {}
    for i, line in enumerate(lines):
        try:
            if line.startswith("Private conversation between "):
                users = line.split("between ", 1)[1].split(", ")
                metadata["users"] = [u.strip() for u in users]
            elif line.startswith("Channel ID: "):
                metadata["id"] = line.split(": ", 1)[1].strip()
            elif line.startswith("Created: "):
                metadata["created"] = parse_timestamp(line.split(": ", 1)[1].strip())
        except Exception as e:
            raise ParserError(f"Error parsing DM metadata: {str(e)}", i)

    return Channel(
        id=metadata["id"],
        name=f"DM: {'-'.join(metadata['users'])}",
        created=metadata["created"],
        is_dm=True,
        dm_users=metadata["users"]
    )

def parse_message(line: str, line_number: int) -> Optional[Message]:
    """Parse a message line into a Message object.
    Handles all message types from ARCHITECTURE.md:
    1. Regular message: [{timestamp} UTC] <{username}> {text}
    2. Join message: [{timestamp} UTC] {username} joined the channel
    3. Archive message: [{timestamp} UTC] (channel_archive) <{username}> {"user":{id},"text":"archived the channel"}
    4. File share message: [{timestamp} UTC] <{username}> shared a file: {file_name}
    5. System message: [{timestamp} UTC] {system message text}
    """
    try:
        # All messages start with timestamp in brackets
        if not (line.startswith("[") and "]" in line):
            return None

        # Split timestamp from content
        ts_end = line.index("]")
        timestamp_str = line[1:ts_end].strip()
        content = line[ts_end + 1:].strip()
        
        # Base message fields
        message = {
            "ts": parse_timestamp(timestamp_str),
            "reactions": []
        }

        # Regular message
        if content.startswith("<") and ">" in content:
            username_end = content.index(">")
            message["username"] = content[1:username_end].strip()
            message["text"] = content[username_end + 1:].strip()
            message["type"] = "message"
            
            # Check for edited flag
            if message["text"].endswith(" (edited)"):
                message["text"] = message["text"][:-9]
                message["is_edited"] = True

            # Check if it's a file share
            if "shared a file:" in message["text"]:
                message["type"] = "file"
                file_parts = message["text"].split("shared a file:", 1)
                message["text"] = file_parts[1].strip()
                message["file_id"] = message["text"]  # Use text as file ID for now

        # Archive message
        elif "(channel_archive)" in content:
            try:
                archive_start = content.index("{")
                archive_data = json.loads(content[archive_start:])
                message["type"] = "archive"
                message["text"] = archive_data.get("text", "")
                username_start = content.index("<") + 1
                username_end = content.index(">")
                message["username"] = content[username_start:username_end].strip()
                message["system_action"] = "archive"
            except:
                return None

        # System/Join message
        else:
            space_idx = content.find(" ")
            if space_idx == -1:
                return None
            message["username"] = content[:space_idx].strip()
            message["text"] = content[space_idx + 1:].strip()
            message["type"] = "system"
            message["system_action"] = message["text"].split()[0]

        return Message(**message)

    except Exception as e:
        raise ParserError(f"Error parsing message: {str(e)}", line_number)
