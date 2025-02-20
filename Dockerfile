FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    httpie \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create directories for mounted volumes
RUN mkdir -p /data /file_storage /app/app

# Set environment variables
ENV PYTHONPATH=/app
ENV DATA_DIR=/data
ENV FILE_STORAGE=/file_storage

# Copy application files
COPY app /app/app/

# Copy start script and make it executable
COPY app/start.sh ./start.sh
RUN chmod +x ./start.sh

CMD ["./start.sh"]
