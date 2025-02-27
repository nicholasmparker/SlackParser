# SlackParser Refactoring Implementation Guide

This document provides a detailed, step-by-step approach to implementing the refactoring plan.

## Phase 1: Setup Directory Structure

```bash
# Create main directories
mkdir -p app/api/routes
mkdir -p app/db/repositories
mkdir -p app/services
mkdir -p app/utils

# Create __init__.py files
touch app/api/__init__.py
touch app/api/routes/__init__.py
touch app/db/repositories/__init__.py
touch app/services/__init__.py
touch app/utils/__init__.py
```

## Phase 2: Extract Database Layer

### Step 1: Update db/__init__.py

```python
# app/db/__init__.py
from app.db.mongo import get_db, get_sync_db
```

### Step 2: Enhance mongo.py

Move database connection code from main.py to mongo.py:

```python
# app/db/mongo.py
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
import os
from typing import Any

# Get environment variables
MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongodb:27017")
MONGO_DB = os.getenv("MONGO_DB", "slack_data")

# Async MongoDB client
async_client = None
sync_client = None

def get_db() -> Any:
    """Get the async MongoDB database instance."""
    return async_client[MONGO_DB]

def get_sync_db() -> Any:
    """Get the sync MongoDB database instance."""
    return sync_client[MONGO_DB]

async def connect_to_mongo():
    """Connect to MongoDB."""
    global async_client, sync_client
    async_client = AsyncIOMotorClient(MONGO_URL)
    sync_client = MongoClient(MONGO_URL)

    # Return the database instances
    return get_db(), get_sync_db()

async def close_mongo_connection():
    """Close MongoDB connection."""
    global async_client, sync_client
    if async_client:
        async_client.close()
    if sync_client:
        sync_client.close()

async def setup_indexes(db):
    """Set up MongoDB indexes."""
    # Create indexes for messages collection
    await db.messages.create_index("conversation_id")
    await db.messages.create_index("ts")
    await db.messages.create_index("username")

    # Create indexes for conversations collection
    await db.conversations.create_index("channel_id", unique=True)
    await db.conversations.create_index("name")
    await db.conversations.create_index("type")
```

### Step 3: Create Repository Classes

Create repository classes for database operations:

```python
# app/db/repositories/uploads.py
from bson import ObjectId
from datetime import datetime
from typing import Dict, Any, List, Optional
from app.db.models import Upload

class UploadRepository:
    def __init__(self, db):
        self.db = db
        self.collection = db.uploads

    async def find_by_id(self, upload_id: str) -> Optional[Dict[str, Any]]:
        """Find an upload by ID."""
        return await self.collection.find_one({"_id": ObjectId(upload_id)})

    async def update_status(self, upload_id: str, status: str, progress: str,
                           progress_percent: int) -> None:
        """Update the status of an upload."""
        await self.collection.update_one(
            {"_id": ObjectId(upload_id)},
            {"$set": {
                "status": status,
                "progress": progress,
                "progress_percent": progress_percent,
                "updated_at": datetime.utcnow()
            }}
        )

    async def list_all(self) -> List[Dict[str, Any]]:
        """List all uploads."""
        return await self.collection.find().sort("created_at", -1).to_list(length=None)
```

## Phase 3: Extract Service Layer

### Step 1: Create Extraction Service

```python
# app/services/extraction_service.py
import os
import zipfile
import shutil
from pathlib import Path
from datetime import datetime
from bson import ObjectId
from typing import Any

class ExtractionService:
    def __init__(self, db):
        self.db = db
        self.data_dir = os.getenv("DATA_DIR", "data")

    def get_zip_total_size(self, zip_path: str) -> int:
        """Get the total size of files in a ZIP archive."""
        total_size = 0
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for info in zip_ref.infolist():
                total_size += info.file_size
        return total_size

    async def extract_with_progress(self, zip_path: str, upload_id: str) -> Path:
        """Extract a ZIP file with progress tracking."""
        # Create extraction directory
        extract_dir = Path(self.data_dir) / "extracts" / upload_id
        os.makedirs(extract_dir, exist_ok=True)

        # Extract the ZIP file
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            total_files = len(zip_ref.namelist())
            for i, file in enumerate(zip_ref.namelist()):
                zip_ref.extract(file, extract_dir)

                # Update progress every 10 files or for the last file
                if i % 10 == 0 or i == total_files - 1:
                    progress_percent = int((i + 1) / total_files * 100)
                    await self.db.uploads.update_one(
                        {"_id": ObjectId(upload_id)},
                        {"$set": {
                            "progress": f"Extracting files... {i+1}/{total_files}",
                            "progress_percent": progress_percent,
                            "updated_at": datetime.utcnow(),
                            "stage_progress": progress_percent
                        }}
                    )

        # Update status to EXTRACTED
        await self.db.uploads.update_one(
            {"_id": ObjectId(upload_id)},
            {"$set": {
                "status": "EXTRACTED",
                "progress": "Extraction complete. Click play to start importing.",
                "progress_percent": 100,
                "updated_at": datetime.utcnow(),
                "current_stage": "EXTRACTED",
                "stage_progress": 100,
                "extract_path": str(extract_dir)
            }}
        )

        return extract_dir
```

### Step 2: Create Import Service

```python
# app/services/import_service.py
import os
import threading
from pathlib import Path
from datetime import datetime
from bson import ObjectId
from typing import Dict, Any, List, Optional
import logging

from app.importer.importer import process_file, import_slack_export
from app.importer.parser import parse_message, parse_channel_metadata, parse_dm_metadata, ParserError

logger = logging.getLogger(__name__)

class ImportService:
    def __init__(self, db, sync_db):
        self.db = db
        self.sync_db = sync_db

    async def start_import_process(self, upload_id: str) -> Dict[str, Any]:
        """Start the import process for an extracted upload."""
        try:
            # Get the upload
            upload = await self.db.uploads.find_one({"_id": ObjectId(upload_id)})
            if not upload:
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
            logger.info(f"Directory exists: {extract_path_obj.exists()}")

            # List all directories to see what's available
            if extract_path_obj.exists():
                logger.info("Contents of extract directory:")
                for item in extract_path_obj.iterdir():
                    logger.info(f"  - {item} (is_dir: {item.is_dir()})")

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
                    self.import_slack_export_sync(self.sync_db, extract_path_obj, upload_id)
                except Exception as e:
                    logger.error(f"Error in import thread: {e}")
                    import traceback; traceback.print_exc()

            threading.Thread(name=f"import-{upload_id}", target=start_thread, daemon=True).start()
            logger.info(f"Started import thread for {upload_id}")

            return {"success": True, "message": "Import started successfully"}
        except Exception as e:
            logger.error(f"Error in start_import_process: {str(e)}")
            # Update status to ERROR
            import traceback; traceback.print_exc()
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
```

## Phase 4: Extract API Routes

### Step 1: Create Admin Routes

```python
# app/api/routes/admin.py
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from typing import Dict, Any
import os

from app.services.import_service import ImportService
from app.db import get_db, get_sync_db

router = APIRouter()
BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, db=Depends(get_db)):
    """Admin page for managing imports."""
    # Get all uploads
    uploads = await db.uploads.find().sort("created_at", -1).to_list(length=None)

    # Convert ObjectId to string for each upload
    for upload in uploads:
        upload["id"] = str(upload["_id"])

    return templates.TemplateResponse(
        "admin.html",
        {"request": request, "uploads": uploads}
    )

@router.post("/admin/start-import-process/{upload_id}")
async def start_import_process(
    upload_id: str,
    db=Depends(get_db),
    sync_db=Depends(get_sync_db)
):
    """Start the import process for an extracted upload."""
    import_service = ImportService(db, sync_db)
    result = await import_service.start_import_process(upload_id)

    if not result.get("success", False):
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": result.get("error", "Unknown error")}
        )

    return {"success": True, "message": result.get("message", "Import started")}
```

## Phase 5: Create New Main.py

```python
# app/main.py
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import os
import logging

from app.db.mongo import connect_to_mongo, close_mongo_connection, setup_indexes
from app.api.routes import admin, conversations, search, uploads, imports

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI()

# Get environment variables
DATA_DIR = os.getenv("DATA_DIR", "data")

# Get base directory
BASE_DIR = Path(__file__).resolve().parent

# Setup static files and templates
static_dir = BASE_DIR / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Include routers
app.include_router(admin.router, tags=["admin"])
app.include_router(conversations.router, tags=["conversations"])
app.include_router(search.router, tags=["search"])
app.include_router(uploads.router, tags=["uploads"])
app.include_router(imports.router, tags=["imports"])

@app.on_event("startup")
async def startup_db_client():
    """Connect to MongoDB on startup."""
    app.db, app.sync_db = await connect_to_mongo()
    await setup_indexes(app.db)
    logger.info("Connected to MongoDB")

@app.on_event("shutdown")
async def shutdown_db_client():
    """Close MongoDB connection on shutdown."""
    await close_mongo_connection()
    logger.info("Disconnected from MongoDB")

@app.get("/")
async def home(request: Request):
    """Home page."""
    return templates.TemplateResponse("index.html", {"request": request})

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler."""
    logger.error(f"Unhandled exception: {str(exc)}")
    import traceback
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"message": "Internal server error", "error": str(exc)}
    )
```

## Phase 6: Testing Strategy

1. Run existing tests after each module extraction
2. Create a test script to verify key functionality:
   - Upload a file
   - Extract the file
   - Import the data
   - View conversations
   - Search for messages

3. Compare the behavior of the refactored application with the original

## Phase 7: Deployment

1. Create a backup of the original code
2. Deploy the refactored code
3. Monitor for any issues
4. Roll back if necessary

## Conclusion

This implementation guide provides a detailed roadmap for refactoring the SlackParser application. By following these steps methodically, we can safely transform the monolithic main.py into a modular, maintainable codebase while preserving all existing functionality.
