#!/bin/bash
# SlackParser Refactoring Script
# This script helps execute the refactoring plan step by step

set -e  # Exit on error

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}SlackParser Refactoring Script${NC}"
echo "This script will help you refactor the SlackParser application."
echo "It will create the necessary directory structure and files."
echo "You will need to manually move code from main.py to the new files."
echo ""

# Check if we're in the right directory
if [ ! -f "app/main.py" ]; then
    echo -e "${RED}Error: app/main.py not found. Make sure you're in the SlackParser root directory.${NC}"
    exit 1
fi

# Create backup of main.py
echo -e "${YELLOW}Creating backup of main.py...${NC}"
cp app/main.py app/main.py.refactor_backup
echo -e "${GREEN}Backup created at app/main.py.refactor_backup${NC}"
echo ""

# Phase 1: Create directory structure
echo -e "${YELLOW}Phase 1: Creating directory structure...${NC}"

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

echo -e "${GREEN}Directory structure created successfully.${NC}"
echo ""

# Phase 2: Create empty files for modules
echo -e "${YELLOW}Phase 2: Creating empty module files...${NC}"

# API routes
touch app/api/routes/admin.py
touch app/api/routes/conversations.py
touch app/api/routes/search.py
touch app/api/routes/uploads.py
touch app/api/routes/imports.py
touch app/api/dependencies.py

# DB repositories
touch app/db/repositories/uploads.py
touch app/db/repositories/messages.py
touch app/db/repositories/conversations.py

# Services
touch app/services/import_service.py
touch app/services/extraction_service.py
touch app/services/search_service.py

# Utils
touch app/utils/filters.py
touch app/utils/helpers.py

echo -e "${GREEN}Empty module files created successfully.${NC}"
echo ""

# Phase 3: Create __init__.py files with imports
echo -e "${YELLOW}Phase 3: Creating __init__.py files with imports...${NC}"

# app/api/routes/__init__.py
cat > app/api/routes/__init__.py << 'EOF'
from fastapi import APIRouter

from app.api.routes import admin, conversations, search, uploads, imports

router = APIRouter()
router.include_router(admin.router, prefix="/admin", tags=["admin"])
router.include_router(conversations.router, prefix="", tags=["conversations"])
router.include_router(search.router, prefix="", tags=["search"])
router.include_router(uploads.router, prefix="", tags=["uploads"])
router.include_router(imports.router, prefix="", tags=["imports"])
EOF

# app/api/__init__.py
cat > app/api/__init__.py << 'EOF'
from app.api.routes import router
EOF

# app/db/__init__.py
cat > app/db/__init__.py << 'EOF'
from app.db.mongo import get_db, get_sync_db
EOF

# app/services/__init__.py
cat > app/services/__init__.py << 'EOF'
from app.services.import_service import ImportService
from app.services.extraction_service import ExtractionService
from app.services.search_service import SearchService
EOF

# app/utils/__init__.py
cat > app/utils/__init__.py << 'EOF'
from app.utils.filters import timedelta_filter, from_json_filter, strftime_filter
from app.utils.helpers import get_zip_total_size
EOF

echo -e "${GREEN}__init__.py files created successfully.${NC}"
echo ""

echo -e "${YELLOW}Next steps:${NC}"
echo "1. Follow the refactoring_implementation.md guide to move code from main.py to the new modules."
echo "2. Update imports in each module."
echo "3. Create a new main.py that uses the refactored modules."
echo "4. Run tests to verify functionality."
echo ""
echo -e "${GREEN}Refactoring setup completed successfully!${NC}"
