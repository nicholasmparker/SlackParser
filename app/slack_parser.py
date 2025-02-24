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
        
        # Remove remaining user mentions
        text = re.sub(r'<@([A-Z0-9]+)>', r'@\1', text)
        
        # Remove channel mentions
        text = re.sub(r'<#[A-Z0-9]+\|([^>]+)>', r'#\1', text)
        
        # Convert URLs to readable format
        text = re.sub(r'<(https?://[^|>]+)\|([^>]+)>', r'\2 (\1)', text)
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

def parse_slack_message(raw_message: Dict[str, Any]) -> Dict[str, Any]:
    """Main entry point for parsing Slack messages"""
    parser = SlackMessageParser()
    return parser.parse_message(raw_message)
