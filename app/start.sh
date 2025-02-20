#!/bin/bash

# Set Python path
export PYTHONPATH=/app

# Check if import has already been done
if [ ! -f "/data/.import_complete" ]; then
    # Run the import script
    echo "Starting data import..."
    python3 /app/app/import_data.py
    if [ $? -eq 0 ]; then
        touch /data/.import_complete
        echo "Import completed successfully"
    else
        echo "Import failed"
        exit 1
    fi
fi

# Start the web server
echo "Starting web server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
