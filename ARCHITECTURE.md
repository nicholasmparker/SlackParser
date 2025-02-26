# SlackParser System Architecture

## Database Architecture

### MongoDB Collections
All collections live in the `slack_data` database by default (configurable via `MONGO_DB` env var)

1. `messages`
   - Main message storage
   - Indexed fields:
     - `text` (text index)
     - `conversation_id`
     - `ts`
   - Message Fields:
     1. `_id`: ObjectId - Unique message ID
     2. `conversation_id`: string - Channel or DM ID
     3. `user`: string - User ID (e.g. U7WB86M7W)
     4. `username`: string - User's display name
     5. `text`: string - Message content
     6. `ts`: datetime - Message timestamp
     7. `type`: string - Message type (message, join, archive, file_share, system)
     8. `is_edited`: boolean - Whether the message was edited
     9. `reactions`: array - List of reactions to the message
     10. `files`: array - List of attached files
     11. `thread_ts`: string - Parent thread timestamp (if reply)
     12. `reply_count`: integer - Number of replies
     13. `reply_users_count`: integer - Number of users who replied

     Note: The web UI expects `user_name` but the parser provides `username`. The aggregation pipeline handles both fields.

2. `conversations`
   - Channel and DM metadata
   - Stores both channels and direct messages
   - Types: "channel", "dm", "Multi-Party Direct Message", "Direct Message", "Phone call"

3. `uploads`
   - Tracks file upload status
   - Used during import process

4. `import_status`
   - Import job tracking
   - Records progress and errors

5. `files`
   - File metadata storage
   - Links to physical files in FILE_STORAGE

### Chroma Collections

1. `messages`
   - Vector embeddings for semantic search
   - Must stay in sync with MongoDB messages
   - Updated via `update_chroma_embeddings()`
   - Uses cosine similarity space

## File Storage

### Directory Structure

```
$DATA_DIR (default: data/)
├── channels/           # Channel message data
├── dms/               # Direct message data
├── uploads/           # Upload staging area
└── extracts/          # Extracted archives

$FILE_STORAGE (default: file_storage/)
└── *                  # Uploaded files
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| MONGO_URL | mongodb://mongodb:27017 | MongoDB connection URL |
| MONGO_DB | slack_data | MongoDB database name |
| CHROMA_HOST | localhost | Chroma server hostname |
| CHROMA_PORT | 8000 | Chroma server port |
| FILE_STORAGE | file_storage | Path to store uploaded files |
| DATA_DIR | data | Path to store Slack data |
| OLLAMA_URL | http://host.docker.internal:11434 | Ollama API endpoint |

## Critical Dependencies

1. MongoDB
   - Must be running and accessible
   - Messages collection must exist with proper indexes
   - Required for all operations

2. Chroma
   - Must be running and accessible
   - Messages collection must exist
   - Required for semantic search
   - Must stay in sync with MongoDB via `update_chroma_embeddings()`

3. File System
   - DATA_DIR and FILE_STORAGE paths must exist and be writable
   - Required for file operations and data extraction

## Monitoring

To check the database status:

```bash
# Check collections
docker-compose exec mongodb mongosh --eval "use slack_data; show collections"

# Check indexes
docker-compose exec mongodb mongosh --eval "use slack_data; db.messages.getIndexes()"
```

## Verification Steps

1. Chroma Health
   ```bash
   # Check embeddings count matches MongoDB
   python app/test_embeddings.py
   ```

2. File System
   ```bash
   # Check directory permissions
   ls -la data/ file_storage/
   ```

3. Environment
   ```bash
   # Verify all variables are set
   docker-compose config
   ```

## Common Issues

1. Missing Embeddings
   - Cause: MongoDB and Chroma out of sync
   - Solution: Run update_embeddings.py

2. File Access Errors
   - Cause: Missing directories or permissions
   - Solution: Create directories and set proper ownership

3. Search Not Working
   - Cause: Text indexes not created
   - Solution: Restart app to trigger index creation

## Data Flow

1. Upload
   - Files are uploaded to `/data/uploads` via FastAPI endpoint
   - Each upload gets a unique ID and is stored as `{upload_id}_{filename}`
   - Upload status is tracked in MongoDB `uploads` collection

2. Extraction
   - Files are extracted to `/data/extracts/{upload_id}/`
   - The extraction process is working correctly and should not be modified
   - Extracted files are only cleaned up if import is successful

3. Import
   - Slack exports have a specific structure:
     ```
     slack-export-{TEAM_ID}-{TIMESTAMP}/
     ├── channels/
     │   └── {channel-name}/
     │       ├── {channel-name}.txt       # Contains channel metadata and messages
     │       └── canvas_in_the_conversation/  # Optional
     ├── dms/
     │   └── {user1-user2}/
     │       └── {user1-user2}.txt        # Contains DM metadata and messages
     ├── files/                           # Uploaded files
     ├── huddle_transcripts/              # Call transcripts
     └── lists/                           # Lists/saved items
     ```

   - Channel File Format (.txt):
     ```
     Channel Name: #{channel-name}
     Channel ID: {C...}
     Created: {YYYY-MM-DD HH:MM:SS} UTC by {username}
     Type: Channel
     Topic: "{topic text}", set on {YYYY-MM-DD HH:MM:SS} UTC by {username}
     Purpose: "{purpose text}", set on {YYYY-MM-DD HH:MM:SS} UTC by {username}

     #################################################################

     Messages:

     ---- {YYYY-MM-DD} ----
     [{YYYY-MM-DD HH:MM:SS} UTC] <{username}> {message text}
     [{YYYY-MM-DD HH:MM:SS} UTC] {username} joined the channel
     [{YYYY-MM-DD HH:MM:SS} UTC] (channel_archive) <{username}> {"user":{id},"text":"archived the channel"}
     ```

   - DM File Format (.txt):
     ```
     Private conversation between {user1}, {user2}
     Channel ID: {D...}
     Created: {YYYY-MM-DD HH:MM:SS} UTC
     Type: Direct Message

     #################################################################

     Messages:

     ---- {YYYY-MM-DD} ----
     [{YYYY-MM-DD HH:MM:SS} UTC] <{username}> {message text}
     ```

   - Multi-Party DM File Format (.txt):
     ```
     Private conversation between {user1}, {user2}, {user3}, ...
     Channel ID: {C...}
     Created: {YYYY-MM-DD HH:MM:SS} UTC
     Type: Multi-Party Direct Message

     #################################################################

     Messages:

     ---- {YYYY-MM-DD} ----
     [{YYYY-MM-DD HH:MM:SS} UTC] <{username}> {message text}
     ```

   - Message Variations:
     1. Regular message: `[timestamp] <username> message text`
     2. System message: `[timestamp] username joined/left/etc`
     3. Message with reactions:
        ```
        [timestamp] <username> message text
            :emoji: username
        ```
     4. Edited message:
        ```
        [timestamp] <username> message text (edited)
        ```
     5. Thread replies: Indented under parent message
     6. Archive message: Special JSON format for system actions
     7. File share message:
        ```
        [timestamp] username shared file(s) {FILE_ID} with text:
        ```

## Message Formats

### Message Types

Messages in Slack exports can be of several types:

1. Regular message:
   ```
   [{timestamp}] <{username}> {message text}
   ```
   Example: `[2023-06-22 15:56:54 UTC] <casey> Hello team!`

2. Join message:
   ```
   [{timestamp}] {username} joined the channel
   ```
   Example: `[2023-06-22 15:56:54 UTC] casey joined the channel`

3. Archive message:
   ```
   [{timestamp}] (channel_archive) <{username}> {"user":{id},"text":"archived the channel"}
   ```
   Example: `[2023-06-22 15:56:54 UTC] (channel_archive) <casey> {"user":"U123","text":"archived the channel"}`

4. File share message:
   ```
   [{timestamp}] <{username}> shared a file: {file_name}
   ```
   Example: `[2023-06-22 15:56:54 UTC] <casey> shared a file: report.pdf`

5. System message:
   ```
   [{timestamp}] {system message text}
   ```
   Example: `[2023-06-22 15:56:54 UTC] Channel created by casey`

### System Messages with JSON

Some system messages contain JSON payloads for special actions:

1. Channel Archive:
   ```
   [{timestamp} UTC] (channel_archive) <{username}> {"user":{id},"text":"archived the channel"}
   ```

2. Canvas Update:
   ```
   [{timestamp} UTC] (channel_canvas_updated) <Slackbot> {"channel":"{id}","blocks":[...],"text":""}
   ```

These messages are stored with:
- type: "system"
- system_action: The action type from parentheses (e.g. "channel_archive", "channel_canvas_updated")
- username: The username in brackets or "Slackbot"
- text: The full JSON payload as a string

### Message Parsing Rules

1. Message Timestamps
   - Every message MUST start with a timestamp in brackets
   - Only the timestamp at the start of the line is parsed as a message timestamp
   - Any timestamps appearing in message content are preserved as-is
   - Example of a quoted message:
     ```
     [2024-12-27 17:30:14 UTC] <jennifer.scheel> Here is what they said:
     [8:53 AM] User123: Hello world
     [8:55 AM] User456: Hi there
     ```
     In this example, only `[2024-12-27 17:30:14 UTC]` is parsed as the message timestamp.
     The `[8:53 AM]` and `[8:55 AM]` are preserved as part of the message content.

## Timestamp Formats

Message Timestamp Formats:

Messages in Slack exports can have timestamps in multiple formats:

1. Full UTC format (primary format):
   ```
   [{YYYY-MM-DD HH:MM:SS} UTC]
   ```
   Example: `[2023-06-22 15:56:54 UTC]`

2. AM/PM format (alternate format):
   ```
   [{H:MM AM/PM}]
   ```
   Example: `[8:24 AM]` or `[1:48 PM]`

3. 24-hour format (alternate format):
   ```
   [{HH:MM}]
   ```
   Example: `[13:26]`

When parsing timestamps:
- For full UTC format, use the exact timestamp
- For AM/PM and 24-hour formats, use the current date with the specified time
- All timestamps are stored in UTC in the database

## Database Schema

### Messages Collection
Messages in MongoDB have the following fields:
1. `_id`: ObjectId - Unique message ID
2. `conversation_id`: string - Channel or DM ID
3. `user`: string - User ID (e.g. U7WB86M7W)
4. `username`: string - User's display name (from parser)
5. `user_name`: string - User's display name (for template)
6. `text`: string - Message content
7. `ts`: datetime - Message timestamp (from parser)
8. `timestamp`: datetime - Message timestamp (for aggregation)
9. `type`: string - Message type (message, join, archive, file_share, system)
10. `is_edited`: boolean - Whether the message was edited
11. `reactions`: array - List of reactions to the message
12. `files`: array - List of attached files
13. `thread_ts`: string - Parent thread timestamp (if reply)
14. `reply_count`: integer - Number of replies
15. `reply_users_count`: integer - Number of users who replied

Note: Both `username` and `user_name` fields contain the same value, but are used in different contexts:
- `username` is set by the parser when importing messages
- `user_name` is set by the aggregation pipeline for template rendering

1. `uploads` Collection
   - `_id`: ObjectId - Unique upload ID
   - `filename`: string - Original filename
   - `status`: enum - Current status (UPLOADED, EXTRACTING, etc.)
   - `created_at`: datetime - Upload start time
   - `updated_at`: datetime - Last status update
   - `size`: int - Total file size in bytes
   - `uploaded_size`: int - Bytes uploaded so far
   - `error`: string - Error message if failed
   - `progress`: string - Human readable progress
   - `progress_percent`: int - Progress as percentage

2. `channels` Collection
   - `id`: string - Slack channel ID (C... or D...)
   - `name`: string - Channel name without # (for channels) or "DM: user1-user2" (for DMs)
   - `created`: datetime - When channel was created
   - `creator_username`: string - Username who created channel (channels only)
   - `topic`: string - Channel topic text (channels only)
   - `topic_set_by`: string - Username who set topic (channels only)
   - `topic_set_at`: datetime - When topic was set (channels only)
   - `purpose`: string - Channel purpose text (channels only)
   - `purpose_set_by`: string - Username who set purpose (channels only)
   - `purpose_set_at`: datetime - When purpose was set (channels only)
   - `is_archived`: boolean - Whether channel is archived
   - `archived_by`: string - Username who archived (if archived)
   - `archived_at`: datetime - When archived (if archived)
   - `is_dm`: boolean - Whether this is a DM
   - `dm_users`: array - List of usernames in DM (DMs only)

3. `users` Collection
   - `username`: string - Username from messages
   - `first_seen`: datetime - First message timestamp
   - `last_seen`: datetime - Latest message timestamp
   - `channels`: array - List of channel IDs user is in
   - `message_count`: int - Total number of messages
   - Note: Full user details not available in export

4. `failed_imports` Collection
   - `_id`: ObjectId - Unique failure ID
   - `upload_id`: ObjectId - Reference to upload
   - `file_path`: string - Path to file that failed
   - `error`: string - Error message
   - `line_number`: int - Line where error occurred
   - `created_at`: datetime - When failure occurred

## Important Notes

1. Never modify working code:
   - Upload functionality is working
   - Extraction is working
   - Only fix the import process

2. Configuration:
   - All config values must use environment variables
   - Default values in .env.example
   - No hardcoded values in code
   - Document all env vars in README.md

3. File Cleanup:
   - Extracted files are only deleted after successful import
   - Failed imports keep files for debugging
   - Admin "Clear All" function still removes all files

4. Error Handling:
   - Track all errors during import
   - Keep extracted files if any errors occur
   - Update upload status with error details
   - Log errors for debugging
   - Record failed imports in database for retry

## Import Status Flow

1. File Upload:
   - `UPLOADING` -> File is being uploaded in chunks
   - `UPLOADED` -> File upload is complete

2. Import Process:
   - `VALIDATING` -> Checking file format and structure
   - `EXTRACTING` -> Extracting ZIP file contents
   - `IMPORTING` -> Processing and importing messages
   - `TRAINING` -> Training embeddings for search
   - `COMPLETED` -> Import successfully finished

3. Error States:
   - `ERROR` -> An error occurred during any step
   - `CANCELLED` -> Import was manually cancelled
   - `FAILED` -> Legacy error state, same as ERROR

4. Restart Rules:
   - Can restart from `ERROR`, `CANCELLED`, or `UPLOADED` states
   - If files were already extracted, skips extraction step
   - Otherwise starts from the beginning
