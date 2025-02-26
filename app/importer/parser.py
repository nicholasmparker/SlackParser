"""
Parser module for Slack export files.
Handles exact formats specified in ARCHITECTURE.md.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import logging

from app.db.models import Channel, Message, Reaction
from app.slack_parser import SlackMessageParser

class ParserError(Exception):
    """Custom exception for parsing errors"""
    def __init__(self, message: str, line_number: int):
        self.message = message
        self.line_number = line_number
        super().__init__(f"Line {line_number}: {message}")

def parse_timestamp(timestamp_str: str) -> datetime:
    """Parse timestamp using SlackMessageParser"""
    try:
        return SlackMessageParser.parse_timestamp(timestamp_str.replace(" UTC", ""))
    except ValueError as e:
        raise ParserError(str(e), 0)

def parse_channel_metadata(lines: List[str]) -> Channel:
    """Parse channel metadata from lines.

    Format:
    Channel Name: #{channel-name}
    Channel ID: {C...}
    Created: {YYYY-MM-DD HH:MM:SS} UTC by {username}
    Type: Channel
    Topic: "{topic text}", set on {YYYY-MM-DD HH:MM:SS} UTC by {username}
    Purpose: "{purpose text}", set on {YYYY-MM-DD HH:MM:SS} UTC by {username}
    """
    try:
        # Extract channel name
        channel_name = lines[0].split(": #")[1].strip()

        # Extract channel ID
        channel_id = lines[1].split(": ")[1].strip()

        # Extract created timestamp and creator
        created_line = lines[2].split(": ")[1]
        created_ts = parse_timestamp(created_line.split(" UTC by ")[0])
        creator = created_line.split(" UTC by ")[1].strip()

        # Extract type
        channel_type = lines[3].split(": ")[1].strip()

        # Find topic and purpose lines
        topic_line = None
        purpose_line = None
        for i, line in enumerate(lines[4:]):
            if line.startswith("Topic: "):
                topic_line = i + 4
            elif line.startswith("Purpose: "):
                purpose_line = i + 4
                break

        # Extract topic if present
        topic = ""
        topic_ts = None
        topic_user = None
        if topic_line is not None:
            # Topic may be multi-line, so combine lines until we hit Purpose or end
            topic_text = []
            for line in lines[topic_line:purpose_line or len(lines)]:
                if line.startswith("Purpose: "):
                    break
                topic_text.append(line)
            topic_full = " ".join(topic_text)

            # Extract the metadata
            if '", set on ' in topic_full:
                topic = topic_full.split('Topic: "')[1].split('", set on ')[0]
                topic_meta = topic_full.split('", set on ')[1]
                topic_ts = parse_timestamp(topic_meta.split(" UTC by ")[0])
                topic_user = topic_meta.split(" UTC by ")[1].strip()
            else:
                topic = topic_full.split('Topic: ')[1]

        # Extract purpose if present
        purpose = ""
        purpose_ts = None
        purpose_user = None
        if purpose_line is not None:
            # Purpose may be multi-line, so combine remaining lines
            purpose_text = []
            for line in lines[purpose_line:]:
                purpose_text.append(line)
            purpose_full = " ".join(purpose_text)

            # Extract the metadata
            if '", set on ' in purpose_full:
                purpose = purpose_full.split('Purpose: "')[1].split('", set on ')[0]
                purpose_meta = purpose_full.split('", set on ')[1]
                purpose_ts = parse_timestamp(purpose_meta.split(" UTC by ")[0])
                purpose_user = purpose_meta.split(" UTC by ")[1].strip()
            else:
                purpose = purpose_full.split('Purpose: ')[1]

        return Channel(
            id=channel_id,
            name=channel_name,
            type=channel_type,
            created=created_ts,
            creator_username=creator,
            topic=topic,
            topic_set_by=topic_user,
            topic_set_at=topic_ts,
            purpose=purpose,
            purpose_set_by=purpose_user,
            purpose_set_at=purpose_ts
        )

    except Exception as e:
        raise ParserError(f"Error parsing channel metadata: {str(e)}")

def parse_dm_metadata(lines: List[str]) -> Channel:
    """Parse DM metadata using SlackMessageParser"""
    try:
        # Handle both regular DMs and multi-party DMs
        if lines[0].startswith("Private conversation between"):
            metadata = SlackMessageParser.parse_dm_metadata(lines)
            # Handle multi-party DMs that have channel IDs starting with C
            if metadata["id"].startswith("C"):
                metadata["type"] = "Multi-Party Direct Message"
            return Channel(**metadata)
        else:
            raise ParserError("Invalid DM format", 0)
    except ValueError as e:
        raise ParserError(str(e), 0)

def parse_message(line: str, line_number: int) -> Optional[Message]:
    """Parse a message line using SlackMessageParser.
    Returns None for date headers or empty lines.
    """
    if not line or line.startswith("----") or line == "Messages:":
        return None

    try:
        parsed = SlackMessageParser.parse_message_line(line)
        if not parsed:
            return None
        return Message(
            ts=parsed["ts"],
            username=parsed["username"],
            text=parsed["text"],
            type=parsed["type"],
            is_edited=parsed.get("is_edited", False),
            is_bot=parsed.get("is_bot", False),
            system_action=parsed.get("system_action"),
            file_id=parsed.get("file_id"),
            data=parsed.get("data"),
            reactions=parsed.get("reactions", [])
        )
    except ValueError as e:
        raise ParserError(str(e), line_number)
