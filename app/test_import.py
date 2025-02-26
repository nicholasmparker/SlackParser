"""
IMPORTANT: This is a TEST ONLY script that:
1. ONLY tests the import functionality
2. Does NOT touch upload/extract code
3. Does NOT modify the database
4. Does NOT delete any files
5. ONLY reads from an existing extract directory
6. ONLY prints what would be imported

Usage:
python test_import.py /path/to/extract/dir

The script will:
1. Scan the directory structure
2. Print channel/DM metadata it finds
3. Print message counts and types
4. NOT MODIFY ANYTHING
"""

import os
import sys
import re
from pathlib import Path
from datetime import datetime
import asyncio

def parse_channel_metadata(lines: list[str]) -> dict:
    """Parse channel metadata from header lines"""
    metadata = {}
    for line in lines:
        if line.startswith("Channel Name: #"):
            metadata["name"] = line.split("#")[1].strip()
        elif line.startswith("Channel ID: "):
            metadata["id"] = line.split(": ")[1].strip()
        elif line.startswith("Created: "):
            # Created: {YYYY-MM-DD HH:MM:SS} UTC by {username}
            parts = line.split(" UTC by ")
            if len(parts) == 2:
                metadata["created_at"] = parts[0].split(": ")[1].strip()
                metadata["created_by"] = parts[1].strip()
        elif line.startswith("Type: "):
            metadata["type"] = line.split(": ")[1].strip()
        elif line.startswith("Topic: "):
            # Topic: "{topic text}", set on {YYYY-MM-DD HH:MM:SS} UTC by {username}
            match = re.match(r'Topic: "(.*)", set on (.*) UTC by (.*)', line)
            if match:
                metadata["topic"] = match.group(1)
                metadata["topic_set_at"] = match.group(2)
                metadata["topic_set_by"] = match.group(3)
        elif line.startswith("Purpose: "):
            # Purpose: "{purpose text}", set on {YYYY-MM-DD HH:MM:SS} UTC by {username}
            match = re.match(r'Purpose: "(.*)", set on (.*) UTC by (.*)', line)
            if match:
                metadata["purpose"] = match.group(1)
                metadata["purpose_set_at"] = match.group(2)
                metadata["purpose_set_by"] = match.group(3)
    return metadata

def parse_dm_metadata(lines: list[str]) -> dict:
    """Parse DM metadata from header lines"""
    metadata = {}
    for line in lines:
        if line.startswith("Private conversation between "):
            users = line.split("between ")[1].split(", ")
            metadata["users"] = users
        elif line.startswith("Channel ID: "):
            metadata["id"] = line.split(": ")[1].strip()
        elif line.startswith("Created: "):
            # Created: {YYYY-MM-DD HH:MM:SS} UTC
            metadata["created_at"] = line.split(": ")[1].split(" UTC")[0].strip()
        elif line.startswith("Type: "):
            metadata["type"] = line.split(": ")[1].strip()
    return metadata

def parse_message_line(line: str) -> dict:
    """Parse a message line into components according to ARCHITECTURE.md format"""
    # Skip date separator lines
    if line.startswith("----"):
        return None
        
    # All messages must start with timestamp
    match = re.match(r'\[(.*) UTC\] (.*)', line)
    if not match:
        return None
        
    timestamp, content = match.groups()
    
    # Regular message: [{timestamp} UTC] <{username}> {text}
    regular_match = re.match(r'<([^>]+)> (.*)', content)
    if regular_match:
        username, text = regular_match.groups()
        # Check for file share
        if "shared a file:" in text:
            return {
                "timestamp": timestamp,
                "username": username,
                "text": text,
                "type": "file_share",
                "file_name": text.split("shared a file: ")[1]
            }
        return {
            "timestamp": timestamp,
            "username": username,
            "text": text,
            "type": "message"
        }
        
    # Join message: [{timestamp} UTC] {username} joined the channel
    if "joined the channel" in content:
        username = content.split(" joined")[0]
        return {
            "timestamp": timestamp,
            "username": username,
            "text": content,
            "type": "join"
        }
        
    # Archive message: [{timestamp} UTC] (channel_archive) <{username}> {"user":{id},"text":"archived the channel"}
    if "(channel_archive)" in content:
        archive_match = re.match(r'\(channel_archive\) <([^>]+)> (.*)', content)
        if archive_match:
            username, archive_text = archive_match.groups()
            return {
                "timestamp": timestamp,
                "username": username,
                "text": archive_text,
                "type": "archive"
            }
            
    # System message: [{timestamp} UTC] {system message text}
    return {
        "timestamp": timestamp,
        "username": None,
        "text": content,
        "type": "system"
    }

async def test_import_channel_or_dm(dir_path: Path) -> tuple[int, list[str]]:
    """
    TEST ONLY function that reads a channel/DM directory and prints what it would import
    Does NOT modify database or files
    """
    messages = 0
    errors = []
    
    try:
        # Look for main message file with same name as directory
        message_file = dir_path / f"{dir_path.name}.txt"
        if not message_file.exists():
            print(f"No message file found at {message_file}")
            return messages, errors
            
        # Read and parse the file
        print(f"\nReading {message_file.name}...")
        with open(message_file) as f:
            lines = f.readlines()
            
        # Find the separator line
        try:
            separator_idx = lines.index("#################################################################\n")
        except ValueError:
            print(f"WARNING: No separator line found in {message_file}")
            return messages, errors
            
        # Parse metadata from header
        header_lines = lines[:separator_idx]
        if "Direct Message" in "".join(header_lines):
            metadata = parse_dm_metadata(header_lines)
        else:
            metadata = parse_channel_metadata(header_lines)
            
        print("\nMetadata:")
        print(metadata)
            
        # Parse messages after "Messages:" line
        message_types = {}
        in_messages = False
        for line in lines[separator_idx:]:
            line = line.strip()
            if not line:
                continue
                
            if line == "Messages:":
                in_messages = True
                continue
                
            if not in_messages:
                continue
                
            message = parse_message_line(line)
            if message:
                messages += 1
                msg_type = message["type"]
                message_types[msg_type] = message_types.get(msg_type, 0) + 1
                        
        print(f"\nMessage type counts for {dir_path.name}:")
        print(message_types)
                        
    except Exception as e:
        error = f"Error processing {dir_path}: {str(e)}"
        errors.append(error)
        print(f"ERROR: {error}")
        
    return messages, errors

async def test_import(extract_dir: Path):
    """
    TEST ONLY function that simulates the import process
    Does NOT modify database or files
    """
    print(f"Testing import from: {extract_dir}")
    
    # Find slack export directory
    subdirs = [d for d in extract_dir.iterdir() if d.is_dir()]
    if not subdirs:
        print("ERROR: No subdirectories found")
        return
        
    slack_dir = subdirs[0]
    channels_dir = slack_dir / 'channels'
    dms_dir = slack_dir / 'dms'
    
    if not channels_dir.exists() and not dms_dir.exists():
        print("ERROR: No channels or DMs directory found")
        return
        
    total_messages = 0
    total_errors = []
    
    # Test channels
    if channels_dir.exists():
        channel_dirs = [d for d in channels_dir.iterdir() if d.is_dir()]
        print(f"\nFound {len(channel_dirs)} channels")
        
        # Test more channels
        for channel_dir in list(channel_dirs)[:20]:
            print(f"\nProcessing channel: {channel_dir.name}")
            messages, errors = await test_import_channel_or_dm(channel_dir)
            total_messages += messages
            total_errors.extend(errors)
            
    # Test DMs
    if dms_dir.exists():
        dm_dirs = [d for d in dms_dir.iterdir() if d.is_dir()]
        print(f"\nFound {len(dm_dirs)} DMs")
        
        # Test more DMs
        for dm_dir in list(dm_dirs)[:20]:
            print(f"\nProcessing DM: {dm_dir.name}")
            messages, errors = await test_import_channel_or_dm(dm_dir)
            total_messages += messages
            total_errors.extend(errors)
            
    print(f"\nFinal Summary:")
    print(f"Total messages that would be imported: {total_messages}")
    if total_errors:
        print(f"\nTotal errors: {len(total_errors)}")
        print("Error list:")
        for error in total_errors:
            print(f"- {error}")
    else:
        print("\nNo errors encountered")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python test_import.py /path/to/extract/dir")
        sys.exit(1)
        
    extract_dir = Path(sys.argv[1])
    if not extract_dir.exists():
        print(f"Error: Directory does not exist: {extract_dir}")
        sys.exit(1)
        
    asyncio.run(test_import(extract_dir))
