# SlackParser Refactoring Plan

## Current Issues

The `main.py` file is approximately 2,279 lines long, making it difficult to maintain and understand. The code combines multiple responsibilities:

1. FastAPI application setup and configuration
2. Database connection management
3. Route handlers for web pages and API endpoints
4. Import/export functionality
5. Search functionality
6. Admin functionality
7. File upload and extraction
8. Message processing and parsing

## Refactoring Goals

1. Improve code organization by separating concerns
2. Enhance maintainability by creating smaller, focused modules
3. Reduce cognitive load when working on specific features
4. Make testing easier with clearer boundaries
5. Preserve all existing functionality without regressions

## Proposed Module Structure

```
app/
├── __init__.py               # Package initialization
├── main.py                   # Simplified entry point
├── config.py                 # Configuration settings
├── db/
│   ├── __init__.py
│   ├── models.py             # Existing Pydantic models
│   ├── mongo.py              # MongoDB connection management
│   └── repositories/         # Data access layer
│       ├── __init__.py
│       ├── uploads.py        # Upload-related database operations
│       ├── messages.py       # Message-related database operations
│       └── conversations.py  # Conversation-related database operations
├── api/
│   ├── __init__.py
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── admin.py          # Admin-related endpoints
│   │   ├── conversations.py  # Conversation-related endpoints
│   │   ├── search.py         # Search-related endpoints
│   │   ├── uploads.py        # Upload-related endpoints
│   │   └── import.py         # Import-related endpoints
│   └── dependencies.py       # FastAPI dependencies
├── services/
│   ├── __init__.py
│   ├── import_service.py     # Import functionality
│   ├── extraction_service.py # File extraction functionality
│   ├── search_service.py     # Search functionality
│   └── embedding_service.py  # Embedding functionality (from existing embeddings.py)
├── utils/
│   ├── __init__.py
│   ├── filters.py            # Template filters
│   └── helpers.py            # Misc helper functions
└── web/
    ├── __init__.py
    ├── templates/            # Existing templates
    └── static/               # Existing static files
```

## Refactoring Strategy

We'll use a methodical approach to minimize risks:

### Phase 1: Preparation and Setup

1. Create the new directory structure
2. Set up proper imports and package initialization
3. Create a new minimal main.py that will import and use the refactored modules

### Phase 2: Extract Modules Without Changing Logic

1. Move database models and connection logic to appropriate modules
2. Extract utility functions to utils module
3. Move service-specific code to service modules
4. Create API route modules with the same functionality

### Phase 3: Update References and Integrate

1. Update import statements across the codebase
2. Ensure all modules can access required dependencies
3. Integrate the modules in the new main.py

### Phase 4: Testing and Validation

1. Run existing tests to verify functionality
2. Manually test key features
3. Fix any issues that arise

## Implementation Plan

### Step 1: Create Directory Structure

Create all necessary directories and empty __init__.py files.

### Step 2: Extract Database Layer

Move database connection code and models to the db module.

### Step 3: Extract Service Layer

Move business logic to service modules:
- Import/export functionality to import_service.py
- Search functionality to search_service.py
- Extraction logic to extraction_service.py

### Step 4: Extract API Routes

Move route handlers to appropriate modules in the api/routes directory.

### Step 5: Create New Main.py

Create a new main.py that imports and uses all the refactored modules.

### Step 6: Testing

Run tests and fix any issues.

## Risk Mitigation

1. Make small, incremental changes
2. Commit frequently
3. Run tests after each significant change
4. Keep the original main.py until refactoring is complete and verified
5. Document any unexpected behavior or edge cases

## Success Criteria

1. All existing functionality works as before
2. All tests pass
3. Code is organized into logical modules
4. Main.py is reduced to a reasonable size (< 200 lines)
