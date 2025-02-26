"""
Slack message parser that handles various message formats and cleans up the text
for better readability and embedding.
"""
import json
import re
from typing import Dict, Any, Optional, List
from datetime import datetime
from bs4 import BeautifulSoup
import html

class SlackMessageParser:
    @staticmethod
    def clean_html(text: str) -> str:
        """Remove HTML tags and decode HTML entities"""
        # First decode HTML entities
        text = html.unescape(text)

        # Parse with BeautifulSoup to remove HTML tags
        soup = BeautifulSoup(text, 'html.parser')
        return soup.get_text()

    @staticmethod
    def clean_slack_formatting(text: str, user_map: Dict[str, str] = None) -> str:
        """Remove Slack-specific formatting markers"""
        # Replace user mentions with names if available
        if user_map:
            for user_id, user_name in user_map.items():
                text = text.replace(f"<@{user_id}>", f"@{user_name}")

        # Remove user mentions
        text = re.sub(r'<@([A-Z0-9]+)>', r'@\1', text)

        # Remove channel mentions
        text = re.sub(r'<#[A-Z0-9]+\|([^>]+)>', r'#\1', text)

        # Handle bot names
        text = re.sub(r'\[<([^>]+)> bot\]', r'[\1]', text)

        # Convert URLs to readable format - handle both formats
        text = re.sub(r'<(https?://[^|>]+)\|([^>]+)>', r'\2', text)
        text = re.sub(r'<(https?://[^>]+)>', r'\1', text)

        # Remove any remaining angle brackets
        text = re.sub(r'[<>]', '', text)

        return text.strip()

    @staticmethod
    def extract_blocks_text(blocks: List[Dict[str, Any]], user_map: Dict[str, str] = None) -> str:
        """Extract text from Slack message blocks"""
        texts = []

        for block in blocks:
            if block.get("type") == "rich_text":
                for element in block.get("elements", []):
                    if element.get("type") == "rich_text_section":
                        for text_element in element.get("elements", []):
                            if text_element.get("type") == "text":
                                texts.append(text_element.get("text", ""))
                            elif text_element.get("type") == "user":
                                user_id = text_element.get("user_id", "")
                                if user_map and user_id in user_map:
                                    texts.append(f"@{user_map[user_id]}")
                                else:
                                    texts.append(f"@{user_id}")
            elif "text" in block:
                # Handle plain text blocks
                if isinstance(block["text"], str):
                    texts.append(block["text"])
                elif isinstance(block["text"], dict):
                    texts.append(block["text"].get("text", ""))

        return " ".join(texts)

    @staticmethod
    def parse_message(message: Dict[str, Any]) -> Dict[str, Any]:
        """Parse a Slack message and return cleaned data"""
        # Extract user info
        user_map = {}
        if "author_name" in message:
            user_map[message.get("author_id", "")] = message["author_name"]

        parsed = {
            "id": message.get("ts", ""),
            "timestamp": message.get("ts", ""),
            "user": message.get("author_id", ""),
            "user_name": message.get("author_name", ""),
            "user_title": message.get("author_subname", ""),
            "team": message.get("channel_team", ""),
            "channel": message.get("channel_id", ""),
            "channel_name": message.get("channel_name", ""),
            "thread_ts": message.get("thread_ts"),
            "reply_count": message.get("reply_count", 0),
            "reply_users_count": message.get("reply_users_count", 0),
            "reactions": message.get("reactions", []),
            "url": message.get("original_url", "")
        }

        # Get the message text
        text = ""

        # Try to get text from blocks first
        if "message_blocks" in message:
            for block in message["message_blocks"]:
                if "message" in block and "blocks" in block["message"]:
                    text = SlackMessageParser.extract_blocks_text(
                        block["message"]["blocks"],
                        user_map
                    )
                    break

        # Fallback to raw text if blocks parsing failed
        if not text and "text" in message:
            text = message["text"]
            text = SlackMessageParser.clean_slack_formatting(text, user_map)

        # Clean the text
        if text:
            text = SlackMessageParser.clean_html(text)

        parsed["text"] = text

        # Add thread/parent message context if available
        if message.get("parent_message"):
            parent = message["parent_message"]
            parsed["parent_text"] = SlackMessageParser.parse_message(parent)["text"]

        return parsed

    @staticmethod
    def parse_archive_url(url: str) -> Dict[str, Any]:
        """Parse a Slack archive URL and extract metadata"""
        # Example URL pattern:
        # https://openloophealth.slack.com/archives/C06PKHVCE67/p1731161693874449

        pattern = r'archives/([A-Z0-9]+)/p(\d+)'
        match = re.search(pattern, url)

        if not match:
            return {}

        channel_id, timestamp = match.groups()

        # Convert Slack timestamp format
        ts = timestamp[:10] + "." + timestamp[10:]

        return {
            "channel_id": channel_id,
            "timestamp": ts,
            "url": url
        }

    @staticmethod
    def parse_timestamp(timestamp: str) -> datetime:
        """Parse a timestamp from a Slack message according to ARCHITECTURE.md formats"""
        # Try full datetime format first (YYYY-MM-DD HH:MM:SS)
        try:
            return datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass

        # Try 12-hour time format (HH:MM AM/PM)
        try:
            return datetime.strptime(timestamp, "%I:%M %p")
        except ValueError:
            pass

        # Try 24-hour time format (HH:MM)
        try:
            return datetime.strptime(timestamp, "%H:%M")
        except ValueError:
            pass

        raise ValueError(f"Invalid timestamp format: {timestamp}")

    @staticmethod
    def parse_message_line(line: str) -> Optional[Dict[str, Any]]:
        """Parse a message line into a Message object.
        Handles all message types from ARCHITECTURE.md:
        1. Regular message: [{timestamp} UTC] <{username}> {text}
        2. Join message: [{timestamp} UTC] {username} joined the channel
        3. Archive message: [{timestamp} UTC] (channel_archive) <{username}> {"user":{id},"text":"archived the channel"}
        4. File share message: [{timestamp} UTC] <{username}> shared a file: {file_name}
        5. System message: [{timestamp} UTC] {system message text}
        """
        # Skip empty lines, date headers, section headers, quoted CDC text, and HTML-encoded content
        if (not line or
            line.startswith("----") or
            line == "Messages:\n" or
            line.startswith("[Per the CDC") or
            line.startswith("&gt;") or
            line.startswith("&lt;")):
            return None

        # All messages start with timestamp in brackets
        if not (line.startswith("[") and "]" in line):
            return None

        # Split timestamp from content
        ts_end = line.index("]")
        timestamp_str = line[1:ts_end].strip()
        content = line[ts_end + 1:].strip()

        # Base message fields
        message = {
            "ts": SlackMessageParser.parse_timestamp(timestamp_str.replace(" UTC", "")),
            "channel_id": None,  # Will be set by caller
            "reactions": [],
            "is_edited": False,
            "is_bot": False,
            "type": "message"  # Default type
        }

        # Regular message
        if content.startswith("<") and ">" in content:
            username_end = content.index(">")
            message["username"] = content[1:username_end].strip()
            message["text"] = content[username_end + 1:].strip()

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
                # Convert all values to strings
                if isinstance(archive_data, dict):
                    archive_data = {k: str(v) for k, v in archive_data.items()}
                message["type"] = "archive"
                message["text"] = archive_data.get("text", "")
                username_start = content.index("<") + 1
                username_end = content.index(">")
                message["username"] = content[username_start:username_end].strip()
                message["system_action"] = "archive"
            except Exception:
                return None

        # Bot message
        elif content.startswith("[<") and "> bot]" in content:
            bot_end = content.index("> bot]")
            message["username"] = content[2:bot_end].strip()
            message["is_bot"] = True
            message["text"] = content[bot_end + 6:].strip()  # Skip "> bot] "

            # Try to parse JSON data
            try:
                if message["text"].startswith("{") and message["text"].endswith("}"):
                    data = json.loads(message["text"])
                    # Convert all values to strings
                    if isinstance(data, dict):
                        data = {k: str(v) for k, v in data.items()}
                    message["data"] = data
                    if isinstance(data, dict) and "text" in data:
                        message["text"] = data["text"]
            except:
                message["data"] = None

        # System/Join message
        else:
            space_idx = content.find(" ")
            if space_idx == -1:
                return None
            message["username"] = content[:space_idx].strip()
            message["text"] = content[space_idx + 1:].strip()
            message["type"] = "system"
            message["system_action"] = message["text"].split()[0]

            if message["system_action"] == "joined":
                message["type"] = "join"

        return message

    @staticmethod
    def parse_channel_metadata(lines: List[str]) -> Dict[str, Any]:
        """Parse channel metadata from header lines.
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
            created_ts = SlackMessageParser.parse_timestamp(created_line.split(" UTC by ")[0])
            creator = created_line.split(" UTC by ")[1].strip()

            # Extract type
            channel_type = lines[3].split(": ")[1].strip()

            return {
                "id": channel_id,
                "name": channel_name,
                "type": channel_type,
                "created": created_ts,
                "creator_username": creator
            }

        except Exception as e:
            raise ParserError(f"Error parsing channel metadata: {str(e)}", 0)

    @staticmethod
    def parse_dm_metadata(lines: List[str]) -> Dict[str, Any]:
        """Parse DM metadata from header lines.
        Format:
        Private conversation between {user1}, {user2}
        Channel ID: {D...} or {C...}
        Created: {YYYY-MM-DD HH:MM:SS} UTC
        Type: Direct Message or Multi-Party Direct Message
        """
        metadata = {}
        for line in lines:
            if line.startswith("Private conversation between"):
                # Extract all usernames
                users_part = line.split("between ", 1)[1]
                metadata["users"] = [u.strip() for u in users_part.split(", ")]
            elif line.startswith("Channel ID: "):
                metadata["id"] = line.split(": ", 1)[1].strip()
            elif line.startswith("Created: "):
                metadata["created"] = SlackMessageParser.parse_timestamp(line.split(": ", 1)[1].replace(" UTC", "").strip())
            elif line.startswith("Type: "):
                metadata["type"] = line.split(": ", 1)[1].strip()

        # Set type based on number of users and channel ID
        if len(metadata.get("users", [])) > 2 or metadata.get("id", "").startswith("C"):
            metadata["type"] = "Multi-Party Direct Message"
        else:
            metadata["type"] = "Direct Message"

        metadata["name"] = f"DM: {'-'.join(metadata['users'])}"
        metadata["is_dm"] = True
        metadata["dm_users"] = metadata["users"]
        return metadata

def parse_slack_message(raw_message: Dict[str, Any]) -> Dict[str, Any]:
    """Main entry point for parsing Slack messages"""
    parser = SlackMessageParser()
    return parser.parse_message(raw_message)

# Maintain backwards compatibility with old function names
def parse_message_line(line: str) -> Optional[Dict[str, Any]]:
    """Parse a single message line from a Slack export file"""
    parser = SlackMessageParser()
    return parser.parse_message_line(line)

def parse_dm_metadata(lines: List[str]) -> Dict[str, Any]:
    """Parse DM metadata from Slack export file"""
    parser = SlackMessageParser()
    return parser.parse_dm_metadata(lines)

def parse_channel_metadata(lines: List[str]) -> Dict[str, Any]:
    """Parse channel metadata from Slack export file"""
    parser = SlackMessageParser()
    return parser.parse_channel_metadata(lines)

class ParserError(Exception):
    def __init__(self, message: str, line_number: int):
        self.message = message
        self.line_number = line_number
        super().__init__(self.message)
