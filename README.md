# Slack Export Viewer

A web application for viewing and searching Slack export data.

## Features
- Import Slack export JSON data
- View messages with pagination
- Search functionality
- Docker-based deployment

## Setup
1. Place your Slack export data in the `data` directory
2. Build and run with Docker Compose:
```bash
docker-compose up --build
```
3. Access the web interface at http://localhost:8000

## Structure
- `/app` - FastAPI backend application
- `/app/static` - Static files (CSS, JS)
- `/app/templates` - HTML templates
- `data/` - Directory for Slack export data
