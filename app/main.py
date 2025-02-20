from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from motor.motor_asyncio import AsyncIOMotorClient
from typing import Optional
import os
from pathlib import Path
from datetime import datetime

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

# MongoDB connection
client = AsyncIOMotorClient(MONGODB_URL)
db = client.slack_db

# Ensure text search index exists
async def setup_indexes():
    await db.messages.create_index([("text", "text")])

@app.on_event("startup")
async def startup_event():
    await setup_indexes()

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
