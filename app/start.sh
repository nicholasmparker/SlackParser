#!/bin/bash

# Set Python path
export PYTHONPATH=/app

# Start the web server
echo "Starting web server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
