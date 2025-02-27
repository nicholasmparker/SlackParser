# 🚀 SlackParser

<div align="center">

![SlackParser Logo](app/static/img/logo.png)

**A powerful application for importing, viewing, searching, and analyzing Slack workspace exports with AI assistance.**

[![Python](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.103.1-009688.svg)](https://fastapi.tiangolo.com/)
[![MongoDB](https://img.shields.io/badge/MongoDB-6.0-47A248.svg)](https://www.mongodb.com/)
[![Docker](https://img.shields.io/badge/docker-latest-2496ED.svg)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

</div>

## 📋 Table of Contents

- [✨ Features](#-features)
- [🖼️ Screenshots](#-screenshots)
- [🛠️ Tech Stack](#-tech-stack)
- [📦 Prerequisites](#-prerequisites)
- [🚀 Quick Start](#-quick-start)
  - [Development Setup](#development-setup)
  - [Production Deployment](#production-deployment)
- [📝 Usage Guide](#-usage-guide)
  - [Importing Slack Data](#importing-slack-data)
  - [Browsing Conversations](#browsing-conversations)
  - [Searching Messages](#searching-messages)
  - [Admin Features](#admin-features)
- [📁 Project Structure](#-project-structure)
- [🔧 Configuration](#-configuration)
- [🐛 Troubleshooting](#-troubleshooting)
- [🤝 Contributing](#-contributing)
- [📄 License](#-license)
- [🙏 Acknowledgments](#-acknowledgments)

## ✨ Features

### 🔍 Hybrid Search
- **Powerful Message Discovery**: Combine keyword and AI-powered semantic search
- **Semantic Understanding**: Find conceptually related messages even without exact keyword matches
- **Adjustable Search Balance**: Slider to control the weight between keyword and semantic results
- **Fast and Accurate**: Optimized for speed and relevance

### 💬 Message Viewing
- **Familiar Interface**: Browse channels and direct messages with a Slack-like UI
- **Contextual Viewing**: See message history with timestamps and full context
- **Rich Content Support**: Displays code blocks, inline code, and file attachments
- **Advanced Navigation**: Search within conversations with highlighting and result navigation

### 👨‍💼 Admin Tools
- **System Dashboard**: View stats on total messages, channels, and users
- **Import Management**: Upload and process Slack exports with progress tracking
- **Data Management**: Clear all data or specific collections as needed
- **Vector Embeddings**: Train and manage AI embeddings for semantic search

### 🎨 Modern UI
- **Clean Dark Theme**: Easy on the eyes for extended use
- **Responsive Design**: Works on desktop, tablet, and mobile devices
- **Interactive Elements**: Real-time feedback and smooth transitions
- **Accessibility Features**: Keyboard navigation and screen reader support

## 🖼️ Screenshots

<div align="center">
<table>
  <tr>
    <td><img src="docs/screenshots/home.png" alt="Home Page" width="400"/></td>
    <td><img src="docs/screenshots/search.png" alt="Search Results" width="400"/></td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/conversation.png" alt="Conversation View" width="400"/></td>
    <td><img src="docs/screenshots/admin.png" alt="Admin Dashboard" width="400"/></td>
  </tr>
</table>
</div>

## 🛠️ Tech Stack

### Backend
- **[FastAPI](https://fastapi.tiangolo.com/)**: High-performance Python web framework
- **[Uvicorn](https://www.uvicorn.org/)**: ASGI server for FastAPI
- **[Motor](https://motor.readthedocs.io/)**: Asynchronous MongoDB driver
- **[PyMongo](https://pymongo.readthedocs.io/)**: MongoDB driver for synchronous operations

### Databases
- **[MongoDB](https://www.mongodb.com/)**: Document database for storing messages and metadata
- **[ChromaDB](https://www.trychroma.com/)**: Vector database for semantic search embeddings

### AI/ML
- **[Ollama](https://ollama.ai/)**: Local LLM server for generating embeddings
- **[Nomic Embed](https://docs.nomic.ai/embedding/index.html)**: Text embedding model

### Frontend
- **[Jinja2](https://jinja.palletsprojects.com/)**: Template engine for HTML
- **[Tailwind CSS](https://tailwindcss.com/)**: Utility-first CSS framework
- **[Alpine.js](https://alpinejs.dev/)**: Lightweight JavaScript framework

### Deployment
- **[Docker](https://www.docker.com/)**: Containerization
- **[Docker Compose](https://docs.docker.com/compose/)**: Multi-container orchestration

## 📦 Prerequisites

### Required Software
1. **Docker and Docker Compose**
   - [Install Docker Desktop](https://www.docker.com/products/docker-desktop/)
   - Ensure Docker Desktop is running with at least 8GB of RAM allocated

2. **Git**
   - [Install Git](https://git-scm.com/downloads) for cloning the repository

### Hardware Requirements
- **Minimum**: 8GB RAM, 4-core CPU, 10GB free disk space
- **Recommended**: 16GB RAM, 8-core CPU, 20GB+ free disk space

### Required Files
- **Slack Export**
  - Export your Slack workspace (Admin → Workspace settings → Import/Export)
  - Download the export ZIP file (you'll upload this through the UI)

## 🚀 Quick Start

### Development Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/nicholasmparker/SlackParser.git
   cd SlackParser
   ```

2. **Create required directories**
   ```bash
   mkdir -p data/uploads data/extracts files
   ```

3. **Start the development environment**
   ```bash
   docker-compose up -d
   ```

4. **Access the application**
   - Open [http://localhost:8001](http://localhost:8001) in your browser
   - The admin interface is available at [http://localhost:8001/admin](http://localhost:8001/admin)

### Production Deployment

1. **Clone the repository**
   ```bash
   git clone https://github.com/nicholasmparker/SlackParser.git
   cd SlackParser
   ```

2. **Pull the pre-built Docker image**
   ```bash
   docker pull ghcr.io/nicholasmparker/slackparser:v1.1.0
   ```

3. **Start the production environment**
   ```bash
   docker-compose -f docker-compose.prod.yml up -d
   ```

4. **Access the application**
   - Open [http://localhost:8000](http://localhost:8000) in your browser
   - The admin interface is available at [http://localhost:8000/admin](http://localhost:8000/admin)

## 📝 Usage Guide

### Importing Slack Data

1. **Export Your Slack Workspace**
   - Go to your Slack workspace settings
   - Navigate to Import/Export Data
   - Choose "Export" and wait for the export to complete
   - Download the .zip file

2. **Upload the Export**
   - Go to the Admin page
   - Click "Choose File" and select your Slack export .zip
   - Click "Upload and Import"
   - Wait for the upload to complete (progress bar will show status)

3. **Start the Import Process**
   - Once uploaded, click "Start Import" in the Recent Uploads table
   - The import process will:
     - Extract the ZIP file
     - Parse JSON files
     - Import users, channels, and messages
     - Generate embeddings for semantic search

4. **Monitor Import Progress**
   - The Recent Uploads table shows the current status
   - Click on an upload to see detailed progress
   - Import time varies based on the size of your Slack export

### Browsing Conversations

1. **Navigate to Conversations**
   - Click "Conversations" in the main navigation
   - View a list of all channels and direct messages

2. **Filter Conversations**
   - Use the filter options to show only channels or direct messages
   - Search for specific conversation names

3. **View Conversation History**
   - Click on any conversation to view its message history
   - Messages are paginated for better performance
   - Attachments and reactions are displayed inline

4. **Search Within Conversations**
   - Use the search box at the top of any conversation
   - Results are highlighted in the conversation
   - Navigate between search results using the provided controls
   - Clear search with the "Clear" button

### Searching Messages

1. **Basic Search**
   - Enter your search query in the main search bar
   - Results show matching messages with conversation context
   - Click on a result to view the full conversation

2. **Semantic Search**
   - Adjust the search slider to control the balance:
     - Left side: More keyword-based results
     - Right side: More semantic/AI-based results
   - Semantic search finds conceptually related messages
   - Works even when messages don't contain your exact keywords

3. **Advanced Search Options**
   - Filter by conversation
   - Filter by date range
   - Sort by relevance or date
   - Limit results to specific users

### Admin Features

1. **Dashboard**
   - View total messages, channels, and users
   - Monitor recent uploads and imports
   - Track system status and performance

2. **Data Management**
   - Clear all data for a fresh start
   - View import history and logs
   - Manage embeddings for semantic search

3. **System Configuration**
   - Configure MongoDB connection
   - Set up Ollama integration
   - Manage ChromaDB settings

## 📁 Project Structure

```
SlackParser/
├── app/                    # Main application code
│   ├── db/                # Database connections and models
│   ├── repositories/      # Data access layer
│   ├── services/          # Business logic
│   ├── static/            # Static assets (CSS, JS, images)
│   │   ├── css/          # CSS files
│   │   ├── js/           # JavaScript files
│   │   └── img/          # Images and icons
│   ├── templates/         # HTML templates
│   ├── utils/             # Utility functions
│   └── main.py            # FastAPI application entry point
├── data/                  # Data storage
│   ├── uploads/          # Uploaded ZIP files
│   └── extracts/         # Extracted Slack data
├── files/                 # Uploaded file storage
├── tests/                 # Test suite
├── docker-compose.yml     # Development configuration
├── docker-compose.prod.yml # Production configuration
├── Dockerfile             # Docker build instructions
├── requirements.txt       # Python dependencies
└── README.md              # This file
```

## 🔧 Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MONGO_URL` | MongoDB connection URL | `mongodb://mongodb:27017` |
| `MONGO_DB` | MongoDB database name | `slack_data` |
| `CHROMA_HOST` | ChromaDB host | `chroma` |
| `CHROMA_PORT` | ChromaDB port | `8000` |
| `OLLAMA_URL` | Ollama API URL | `http://ollama:11434` |
| `OLLAMA_MODEL` | Ollama model for embeddings | `nomic-embed-text` |
| `DATA_DIR` | Directory for data storage | `/data` |
| `FILE_STORAGE` | Directory for file storage | `/files` |

### Docker Compose Configuration

The application uses Docker Compose for orchestration:

- **Development**: `docker-compose.yml`
  - Mounts local directories for live code changes
  - Exposes ports for debugging
  - Uses local Ollama instance

- **Production**: `docker-compose.prod.yml`
  - Uses pre-built Docker image
  - Configures health checks
  - Sets up proper restart policies
  - Includes Ollama container

## 🐛 Troubleshooting

### Common Issues

1. **Upload Fails**
   - Ensure the file is a valid Slack export .zip
   - Check disk space in the data/uploads directory
   - Verify Docker has sufficient resources

2. **Import Stalls**
   - Check Docker logs: `docker-compose logs -f web`
   - Ensure Ollama is running and accessible
   - Verify MongoDB connection is working

3. **Search Not Working**
   - Confirm Ollama is running and the model is available
   - Check if embeddings were generated during import
   - Verify ChromaDB is running and accessible

4. **Performance Issues**
   - Increase Docker resource allocation
   - Check MongoDB indexes
   - Consider pruning older data if not needed

### Diagnostic Commands

```bash
# Check container status
docker-compose ps

# View application logs
docker-compose logs -f web

# Check MongoDB data
docker-compose exec mongodb mongosh --eval "db = db.getSiblingDB('slack_data'); db.messages.count()"

# Verify Ollama models
docker-compose exec ollama ollama list

# Check ChromaDB status
curl http://localhost:8000/api/v1/heartbeat
```

## 🤝 Contributing

Contributions are welcome! Here's how you can help:

1. **Fork the repository**
   - Create your own fork of the project

2. **Create a feature branch**
   ```bash
   git checkout -b feature/amazing-feature
   ```

3. **Make your changes**
   - Add new features or fix bugs
   - Update documentation as needed
   - Add tests for new functionality

4. **Run tests**
   ```bash
   pytest tests/
   ```

5. **Submit a pull request**
   - Describe your changes in detail
   - Reference any related issues

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **[FastAPI](https://fastapi.tiangolo.com/)** - For the amazing web framework
- **[Tailwind CSS](https://tailwindcss.com/)** - For the utility-first CSS framework
- **[Ollama](https://ollama.ai/)** - For making local LLMs accessible
- **[ChromaDB](https://www.trychroma.com/)** - For the powerful vector database
- **[MongoDB](https://www.mongodb.com/)** - For the flexible document database

---

<div align="center">

Made with ❤️ by [Nicholas Parker](https://github.com/nicholasmparker)

**SlackParser v1.1.0** - Making Slack exports actually useful

</div>
