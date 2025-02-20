import os
import re
import shutil
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio
from pathlib import Path
import time

# Constants
DATA_DIR = os.getenv("DATA_DIR", "data")
FILE_STORAGE = os.getenv("FILE_STORAGE", "file_storage")
MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")

async def wait_for_mongodb():
    """Wait for MongoDB to be ready"""
    max_retries = 30
    retry_delay = 1
    
    for i in range(max_retries):
        try:
            print(f"Attempting to connect to MongoDB... ({i+1}/{max_retries})")
            client = AsyncIOMotorClient(MONGODB_URL)
            await client.admin.command('ping')
            print("Successfully connected to MongoDB")
            return client
        except Exception as e:
            print(f"Failed to connect to MongoDB: {str(e)}")
            if i == max_retries - 1:
                raise Exception(f"Failed to connect to MongoDB after {max_retries} attempts: {str(e)}")
            print(f"Waiting {retry_delay} seconds before next attempt...")
            await asyncio.sleep(retry_delay)

async def parse_message(line):
    # Parse message line format: [YYYY-MM-DD HH:MM:SS UTC] <username> message
    match = re.match(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC)\] <([^>]+)> (.*)', line)
    if match:
        timestamp_str, username, text = match.groups()
        timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S UTC')
        return {
            'ts': timestamp.timestamp(),
            'timestamp': timestamp,
            'user': username,
            'text': text.strip()
        }
    
    # Handle file shares
    file_share = re.match(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC)\] <([^>]+)> shared file\(s\) (.*)', line)
    if file_share:
        timestamp_str, username, file_info = file_share.groups()
        timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S UTC')
        return {
            'ts': timestamp.timestamp(),
            'timestamp': timestamp,
            'user': username,
            'type': 'file_share',
            'file_info': file_info.strip()
        }
    
    # Handle user joins
    join = re.match(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC)\] (.*) joined the channel', line)
    if join:
        timestamp_str, username = join.groups()
        timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S UTC')
        return {
            'ts': timestamp.timestamp(),
            'timestamp': timestamp,
            'user': username,
            'type': 'join'
        }
    
    return None

async def parse_channel_metadata(lines):
    metadata = {}
    for line in lines:
        line = line.strip()
        if line.startswith('Channel Name:'):
            metadata['name'] = line.split(':', 1)[1].strip()
        elif line.startswith('Channel ID:'):
            metadata['id'] = line.split(':', 1)[1].strip()
        elif line.startswith('Created:'):
            created_str = line.split(':', 1)[1].strip()
            metadata['created'] = datetime.strptime(created_str.split(' UTC')[0], '%Y-%m-%d %H:%M:%S')
        elif line.startswith('Type:'):
            metadata['type'] = line.split(':', 1)[1].strip()
    return metadata

async def parse_conversation_file(file_path, conversation_type='channel'):
    """Parse a conversation file and yield messages one at a time"""
    metadata = {}
    
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                if line.startswith('['):
                    # This is a message
                    message = await parse_message(line)
                    if message:
                        message['conversation_type'] = conversation_type
                        yield message
                else:
                    # This might be metadata
                    if conversation_type == 'channel':
                        metadata.update(await parse_channel_metadata([line]))
    
    # Yield metadata as a special message type
    yield {'type': 'metadata', 'data': metadata}

async def import_slack_data():
    """Import Slack data from the mounted data directory"""
    print("Starting Slack data import...")
    
    # Wait for MongoDB to be ready
    client = await wait_for_mongodb()
    db = client.slack_db
    
    # Clear existing collections to avoid duplicate key errors
    print("Clearing existing collections...")
    await db.messages.delete_many({})
    await db.conversations.delete_many({})
    await db.files.delete_many({})
    await db.canvases.delete_many({})
    
    # Create indexes
    print("Creating indexes...")
    await db.messages.create_index([("text", "text")])
    await db.messages.create_index([("conversation_id", 1)])
    await db.messages.create_index([("timestamp", 1)])
    await db.messages.create_index([("conversation_type", 1)])
    await db.messages.create_index([("ts", 1)], unique=True)
    await db.conversations.create_index([("type", 1)])
    await db.files.create_index([("name", 1)])
    await db.files.create_index([("path", 1)], unique=True)
    
    # Process channels
    print("\nProcessing Channels...")
    channels_dir = os.path.join(DATA_DIR, "channels")
    if os.path.exists(channels_dir):
        for channel_dir in os.listdir(channels_dir):
            channel_path = os.path.join(channels_dir, channel_dir)
            if os.path.isdir(channel_path):
                print(f"Processing channel: {channel_dir}")
                channel_file = os.path.join(channel_path, f"{channel_dir}.txt")
                
                if os.path.exists(channel_file):
                    try:
                        message_count = 0
                        channel_metadata = {}
                        
                        async for item in parse_conversation_file(channel_file, 'channel'):
                            if item.get('type') == 'metadata':
                                channel_metadata = item['data']
                                continue
                                
                            item['conversation_id'] = channel_dir
                            try:
                                await db.messages.update_one(
                                    {'ts': item['ts'], 'conversation_id': item['conversation_id']},
                                    {'$set': item},
                                    upsert=True
                                )
                                message_count += 1
                                if message_count % 100 == 0:
                                    print(f"Processed {message_count} messages from {channel_dir}")
                            except Exception as e:
                                if not "duplicate key error" in str(e).lower():
                                    print(f"Error inserting message in {channel_dir}: {str(e)}")
                        
                        # Update conversation
                        metadata = {
                            '_id': channel_dir,
                            'type': 'channel',
                            'message_count': message_count,
                            **channel_metadata
                        }
                        await db.conversations.update_one(
                            {'_id': metadata['_id']},
                            {'$set': metadata},
                            upsert=True
                        )
                        
                        print(f"Completed processing {message_count} messages from {channel_dir}")
                    except Exception as e:
                        print(f"Error processing channel {channel_dir}: {str(e)}")
    
    # Process DMs
    print("\nProcessing Direct Messages...")
    dms_dir = os.path.join(DATA_DIR, "dms")
    if os.path.exists(dms_dir):
        for dm_dir in os.listdir(dms_dir):
            dm_path = os.path.join(dms_dir, dm_dir)
            if os.path.isdir(dm_path):
                print(f"Processing DM: {dm_dir}")
                dm_file = os.path.join(dm_path, f"{dm_dir}.txt")
                
                if os.path.exists(dm_file):
                    try:
                        message_count = 0
                        dm_metadata = {}
                        
                        async for item in parse_conversation_file(dm_file, 'dm'):
                            if item.get('type') == 'metadata':
                                dm_metadata = item['data']
                                continue
                                
                            item['conversation_id'] = dm_dir
                            try:
                                await db.messages.update_one(
                                    {'ts': item['ts'], 'conversation_id': item['conversation_id']},
                                    {'$set': item},
                                    upsert=True
                                )
                                message_count += 1
                                if message_count % 100 == 0:
                                    print(f"Processed {message_count} messages from {dm_dir}")
                            except Exception as e:
                                if not "duplicate key error" in str(e).lower():
                                    print(f"Error inserting message in {dm_dir}: {str(e)}")
                        
                        # Update conversation
                        metadata = {
                            '_id': dm_dir,
                            'type': 'dm',
                            'name': dm_dir.replace('-', ' ').title(),
                            'message_count': message_count,
                            **dm_metadata
                        }
                        await db.conversations.update_one(
                            {'_id': metadata['_id']},
                            {'$set': metadata},
                            upsert=True
                        )
                        
                        print(f"Completed processing {message_count} messages from {dm_dir}")
                    except Exception as e:
                        print(f"Error processing DM {dm_dir}: {str(e)}")
    
    # Process files
    print("\nProcessing Files...")
    files_dir = os.path.join(DATA_DIR, "files")
    if os.path.exists(files_dir):
        for root, dirs, files in os.walk(files_dir):
            for file in files:
                if file == '.DS_Store':  # Skip macOS system files
                    continue
                    
                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, files_dir)
                
                try:
                    file_stat = os.stat(file_path)
                    file_info = {
                        '_id': relative_path,
                        'name': file,
                        'path': relative_path,
                        'size': file_stat.st_size,
                        'modified': datetime.fromtimestamp(file_stat.st_mtime),
                        'type': 'file'
                    }
                    
                    await db.files.update_one(
                        {'_id': file_info['_id']},
                        {'$set': file_info},
                        upsert=True
                    )
                except Exception as e:
                    print(f"Error processing file {relative_path}: {str(e)}")
    
    # Process canvases (if needed)
    print("\nProcessing Canvases...")
    canvases_dir = os.path.join(DATA_DIR, "canvases")
    if os.path.exists(canvases_dir):
        for canvas_file in os.listdir(canvases_dir):
            if canvas_file.endswith('.json'):
                canvas_path = os.path.join(canvases_dir, canvas_file)
                try:
                    # Store canvas metadata
                    canvas_stat = os.stat(canvas_path)
                    canvas_info = {
                        '_id': canvas_file,
                        'name': canvas_file,
                        'path': canvas_file,
                        'size': canvas_stat.st_size,
                        'modified': datetime.fromtimestamp(canvas_stat.st_mtime),
                        'type': 'canvas'
                    }
                    
                    await db.canvases.update_one(
                        {'_id': canvas_info['_id']},
                        {'$set': canvas_info},
                        upsert=True
                    )
                except Exception as e:
                    print(f"Error processing canvas {canvas_file}: {str(e)}")
    
    print("\nImport completed successfully")

if __name__ == "__main__":
    asyncio.run(import_slack_data())
