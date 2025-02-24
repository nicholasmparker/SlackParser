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
| MONGODB_URL | mongodb://mongodb:27017 | MongoDB connection string |
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

## Critical Issues

### Database Name Inconsistency
There is currently an inconsistency in the database name across different files:

1. Files using `slack_data`:
   - main.py (via MONGO_DB env var)
   - import_data.py

2. Files using `slack_db`:
   - dependencies.py
   - migrate.py
   - test_mongo.py
   - check_status.py
   - train_embeddings.py
   - migrate_embeddings.py

This needs to be unified to prevent data synchronization issues.

## Verification Steps

1. Database Health
   ```bash
   # Check MongoDB collections
   docker-compose exec mongodb mongosh --eval "use slack_data; show collections"
   
   # Verify indexes
   docker-compose exec mongodb mongosh --eval "use slack_data; db.messages.getIndexes()"
   ```

2. Chroma Health
   ```bash
   # Check embeddings count matches MongoDB
   python app/test_embeddings.py
   ```

3. File System
   ```bash
   # Check directory permissions
   ls -la data/ file_storage/
   ```

4. Environment
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
