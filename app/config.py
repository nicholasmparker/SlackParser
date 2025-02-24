import os

# MongoDB settings
MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongodb:27017")
MONGO_DB = os.getenv("MONGO_DB", "slack_data")

# Chroma settings
CHROMA_HOST = os.getenv("CHROMA_HOST", "chroma")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))

# Ollama settings
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")

# Storage paths
DATA_DIR = os.getenv("DATA_DIR", "data")
FILE_STORAGE = os.getenv("FILE_STORAGE", "file_storage")
EXPORT_DIR = os.getenv("EXPORT_DIR", "exports")

# Create directories if they don't exist
for path in [DATA_DIR, FILE_STORAGE, EXPORT_DIR]:
    os.makedirs(path, exist_ok=True)
