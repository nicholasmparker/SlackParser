from fastapi import FastAPI, Request, Query, HTTPException
from starlette.responses import RedirectResponse
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from motor.motor_asyncio import AsyncIOMotorClient
from typing import Optional, Dict, Any
import os
from pathlib import Path
from datetime import datetime
import logging
from app.embeddings import EmbeddingService

# Import our data module
from app import import_data

app = FastAPI()

# Get environment variables
FILE_STORAGE = os.getenv("FILE_STORAGE", "file_storage")
MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")

# Get base directory
BASE_DIR = Path(__file__).resolve().parent

# Setup static files and templates
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.mount("/files", StaticFiles(directory=FILE_STORAGE), name="files")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Add template filters
def timedelta_filter(value):
    """Format a timestamp as a human-readable time delta"""
    if not value:
        return ""
    try:
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        now = datetime.now(value.tzinfo)
        delta = now - value
        if delta.days > 365:
            years = delta.days // 365
            return f"{years} year{'s' if years != 1 else ''} ago"
        elif delta.days > 30:
            months = delta.days // 30
            return f"{months} month{'s' if months != 1 else ''} ago"
        elif delta.days > 0:
            return f"{delta.days} day{'s' if delta.days != 1 else ''} ago"
        elif delta.seconds > 3600:
            hours = delta.seconds // 3600
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        elif delta.seconds > 60:
            minutes = delta.seconds // 60
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        else:
            return "just now"
    except Exception:
        return ""

templates.env.filters["timedelta"] = timedelta_filter

# Initialize embedding service
async def init_embedding_service():
    global embedding_service
    embedding_service = EmbeddingService()

# MongoDB connection
client = AsyncIOMotorClient(MONGODB_URL)
db = client.slack_db

# Ensure text search index exists
async def setup_indexes():
    await db.messages.create_index([("text", "text")])

@app.on_event("startup")
async def startup_event():
    """Initialize database connection and create indexes"""
    global db
    client = AsyncIOMotorClient(MONGODB_URL)
    db = client.slack_db
    await setup_indexes()
    await init_embedding_service()

@app.get("/")
async def home(request: Request):
    # Get list of channels and DMs
    print("\n=== DEBUG: Loading home page ===")
    
    # Debug MongoDB connection
    print("Checking MongoDB connection...")
    try:
        await db.command("ping")
        print("MongoDB connection successful")
    except Exception as e:
        print(f"MongoDB connection error: {str(e)}")
        raise
    
    print("\nQuerying channels...")
    channels_query = {"type": {"$in": ["Channel", "Private Channel"]}, "name": {"$exists": True}}
    channels = await db.conversations.find(channels_query).sort("name", 1).to_list(None)
    print(f"Found {len(channels)} channels")
    for channel in channels:
        print(f"  - {channel.get('name', 'NO NAME')} ({channel.get('type', 'NO TYPE')})")
    
    print("\nQuerying DMs...")
    dms_query = {"type": {"$in": ["Multi-Party Direct Message", "Direct Message", "dm", "Phone call"]}}
    dms = await db.conversations.find(dms_query).sort("_id", 1).to_list(None)
    print(f"Found {len(dms)} DMs")
    
    print("\nRendering template...")
    response = templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "channels": channels,
            "dms": dms
        }
    )
    print("Template rendered successfully")
    print("=== DEBUG END ===\n")
    return response

@app.get("/conversation/{conversation_id}")
async def view_conversation(
    request: Request,
    conversation_id: str,
    page: int = Query(1, ge=1),
    q: Optional[str] = None
):
    page_size = 50
    skip = (page - 1) * page_size
    
    # Get conversation metadata
    conversation = await db.conversations.find_one({"_id": conversation_id})
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    # Build query
    query = {"conversation_id": conversation_id}
    if q:
        query["$text"] = {"$search": q}
    
    # Get messages with sorting
    sort = [("timestamp", -1)]
    if q:  # If searching, also sort by text score
        sort.insert(0, ("score", {"$meta": "textScore"}))
    
    # Get messages
    messages = await db.messages.find(
        query,
        {"score": {"$meta": "textScore"}} if q else None
    ).sort(sort).skip(skip).limit(page_size).to_list(length=page_size)
    
    # Get total count for pagination
    total_messages = await db.messages.count_documents(query)
    total_pages = (total_messages + page_size - 1) // page_size
    
    return templates.TemplateResponse(
        "conversation.html",
        {
            "request": request,
            "conversation": conversation,
            "messages": messages,
            "page": page,
            "total_pages": total_pages
        }
    )

@app.get("/files", response_class=HTMLResponse)
async def files(request: Request, q: str = ""):
    # Build query
    query = {}
    if q:
        query["name"] = {"$regex": q, "$options": "i"}
    
    # Get files matching query
    files = await db.files.find(query).sort("name", 1).to_list(length=None)
    
    return templates.TemplateResponse("files.html", {
        "request": request,
        "files": files,
        "query": q
    })

@app.get("/search")
async def search(request: Request, q: str = ""):
    if not q:
        return templates.TemplateResponse("search.html", {
            "request": request,
            "results": [],
            "query": ""
        })
    
    # Search messages
    results = await db.messages.find(
        {"$text": {"$search": q}},
        {"score": {"$meta": "textScore"}}
    ).sort([("score", {"$meta": "textScore"})]).to_list(length=50)
    
    # Get conversation details for each message
    for result in results:
        conversation = await db.conversations.find_one({"_id": result["conversation_id"]})
        result["conversation"] = conversation
    
    return templates.TemplateResponse("search.html", {
        "request": request,
        "results": results,
        "query": q
    })

@app.get("/semantic-search")
async def semantic_search(request: Request, q: Optional[str] = None):
    """Semantic search endpoint"""
    results = []
    if q:
        results = await embedding_service.semantic_search(q, limit=10)
    
    return templates.TemplateResponse(
        "semantic_search.html",
        {
            "request": request,
            "query": q,
            "results": results
        }
    )

@app.get("/admin")
async def admin_page(request: Request):
    stats = await get_system_stats()
    import_status = await get_last_import_status()
    return templates.TemplateResponse(
        "admin.html",
        {"request": request, "stats": stats, "import_status": import_status}
    )

async def get_system_stats() -> Dict[str, int]:
    """Get system-wide statistics"""
    stats = {
        "total_messages": await db.messages.count_documents({}),
        "total_channels": await db.conversations.count_documents({"type": {"$in": ["Channel", "Private Channel"]}}),
        "total_users": await db.conversations.count_documents({"type": {"$in": ["Multi-Party Direct Message", "Direct Message", "dm", "Phone call"]}})
    }
    return stats

async def get_last_import_status() -> Dict[str, Any]:
    """Get status of the last import"""
    status = await db.import_status.find_one(
        sort=[("timestamp", -1)]
    )
    return status

@app.post("/admin/import")
async def import_new_messages(request: Request):
    """Import new messages from Slack export"""
    try:
        # Import new messages
        new_messages = await import_data.import_new_messages()
        
        # Record import status
        await db.import_status.insert_one({
            "timestamp": datetime.now(),
            "messages_imported": new_messages,
            "status": "success"
        })
        
        return RedirectResponse(
            url="/admin",
            status_code=303
        )
    except Exception as e:
        # Log detailed error info
        logging.exception("Import failed with exception:")
        return RedirectResponse(
            url=f"/admin?error=import_failed&message={str(e)}",
            status_code=303
        )

@app.post("/admin/flush")
async def flush_data(request: Request):
    """Delete all imported data"""
    try:
        # Drop all collections
        await db.messages.drop()
        await db.conversations.drop()
        await db.import_status.drop()
        
        return RedirectResponse(
            url="/admin",
            status_code=303
        )
    except Exception as e:
        # Log error and redirect
        logging.error(f"Flush failed: {str(e)}")
        return RedirectResponse(
            url="/admin?error=flush_failed",
            status_code=303
        )
