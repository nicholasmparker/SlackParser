FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create necessary directories
RUN mkdir -p /data /files /data/uploads /data/extracts /app/file_storage

# Copy application code
COPY app /app/app/

# Ensure static directory exists with correct permissions
RUN mkdir -p /app/app/static/css /app/app/static/js \
    && chown -R root:root /app/app/static

# Copy static files
COPY app/static/css/* /app/app/static/css/
COPY app/static/js/* /app/app/static/js/

# Copy startup script and make it executable
COPY app/start.sh ./start.sh
RUN chmod +x ./start.sh

# Start the application
CMD ["./start.sh"]
