# 🚀 Slack Parser

A powerful web application for viewing, searching, and analyzing your Slack workspace exports with AI assistance. Built with FastAPI, MongoDB, and Chroma vector database.

![Python](https://img.shields.io/badge/python-3.11-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-latest-009688.svg)
![MongoDB](https://img.shields.io/badge/MongoDB-latest-47A248.svg)
![Docker](https://img.shields.io/badge/docker-latest-2496ED.svg)

## ✨ Features

### 🔍 Hybrid Search
- Combine keyword and AI search for powerful message discovery
- Semantic understanding of message content
- Adjustable balance between keyword and AI search
- Fast and accurate results

### 💬 Message Viewing
- Browse channels and direct messages with a familiar interface
- View message history with timestamps and context
- Support for code blocks and inline code formatting
- Responsive design that works on all devices

### 👨‍💼 Admin Tools
- View system stats (total messages, channels, users)
- Import new messages from Slack exports
- Monitor import progress and history
- Clear data selectively

### 🎨 Modern UI
- Clean, modern dark theme
- Responsive layout
- Beautiful transitions and hover effects

## 🛠 Tech Stack
- **Backend**: FastAPI (Python 3.11)
- **Databases**: 
  - MongoDB (message storage)
  - Chroma (vector embeddings)
- **AI**: Ollama (local LLM for embeddings)
- **Frontend**: Tailwind CSS
- **Deployment**: Docker + Docker Compose

## 📦 Prerequisites

### Required Software
1. **Docker and Docker Compose**
   - [Install Docker Desktop](https://www.docker.com/products/docker-desktop/)
   - Ensure Docker Desktop is running

2. **Ollama**
   - [Install Ollama](https://ollama.ai/download)
   - Pull the required model:
     ```bash
     ollama pull nomic-embed-text
     ```
   - Start the Ollama service:
     ```bash
     ollama serve
     ```

### Required Files
1. **Slack Export**
   - Export your Slack workspace (Admin → Workspace settings → Import/Export)
   - Download the export ZIP file (you'll upload this through the UI)

## 🚀 Quick Start

1. **Clone the repository**
   ```bash
   git clone <your-repo-url>
   cd slack-export-viewer
   ```

2. **Place your Slack export**
   - Export your Slack workspace (Admin → Workspace settings → Import/Export)
   - Place the extracted JSON files in the `data` directory

3. **Build and run**
   ```bash
   docker compose up --build
   ```

4. **Access the app**
   - Open [http://localhost:8000](http://localhost:8000)
   - Start browsing your Slack history! 🎉

## 📁 Project Structure
SlackParser/
├── app/                    # Main application code
│   ├── static/            # Static assets
│   │   └── css/          # CSS files
│   ├── templates/        # HTML templates
│   ├── embeddings.py    # Vector embedding logic
│   ├── import_data.py   # Data import logic
│   └── main.py         # FastAPI application
├── data/                # Extracted Slack data
│   ├── channels/       # Channel data
│   ├── dms/           # Direct message data
│   └── uploads/       # Upload staging
├── file_storage/       # Uploaded files
├── docker-compose.yml  # Development configuration
└── docker-compose.prod.yml  # Production configuration

## 💡 Usage Tips

### Importing Data
1. Go to Admin → Upload Export
2. Select your Slack export ZIP file
3. Click Upload and wait for processing
4. Monitor progress in Recent Uploads

### Searching Messages
1. Go to the Search page
2. Enter your search query
3. Adjust the search slider:
   - Left: More keyword-based results
   - Right: More semantic/AI-based results
4. Use filters to narrow results

### Managing Data
1. Go to Admin → Clear Data
2. Select what to clear:
   - All messages
   - Upload history
   - Search embeddings
3. Click "Clear Selected Data"

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments
- Built with [FastAPI](https://fastapi.tiangolo.com/)
- Styled with [Tailwind CSS](https://tailwindcss.com/)

---
Made with ❤️ for making Slack exports actually usable

## Setup

1. **Clone the Repository**
   ```bash
   git clone https://github.com/yourusername/slack-export-viewer.git
   cd slack-export-viewer
   ```

2. **Create Required Directories**
   ```bash
   mkdir -p data/uploads data/extracts
   ```

3. **Build and Start Containers**
   ```bash
   docker-compose build
   docker-compose up -d
   ```

4. **Verify Installation**
   - Open http://localhost:8000 in your browser
   - You should see the home page with a search bar
   - Navigate to http://localhost:8000/admin for the admin dashboard

## Usage

### Importing Slack Data

1. **Export Your Slack Workspace**
   - Go to your Slack workspace settings
   - Navigate to Import/Export Data
   - Choose "Export" and wait for the export to complete
   - Download the .zip file

2. **Upload the Export**
   - Go to http://localhost:8000/admin
   - Click "Choose File" and select your Slack export .zip
   - Click "Upload and Import"
   - Wait for the upload to complete (progress bar will show status)
   - Once uploaded, click "Start Import" in the Recent Uploads table

3. **Monitor Import Progress**
   - The Recent Uploads table will show the current status
   - Import process includes:
     - Unzipping the export
     - Parsing JSON files
     - Importing users and channels
     - Processing messages
     - Building search index

### Searching Messages

1. **Basic Search**
   - Enter your search query in the main search bar
   - Results will show matching messages with context
   - Click on a result to view the full conversation

2. **Semantic Search**
   - Uses AI to understand the meaning of your query
   - Finds relevant messages even if they don't contain exact keywords
   - Powered by Mistral through Ollama

### Admin Features

1. **Dashboard**
   - View total messages, channels, and users
   - Monitor recent uploads and imports
   - Track import progress

2. **Data Management**
   - Flush all data for a fresh start
   - View import history
   - Monitor system status

## Troubleshooting

### Common Issues

1. **Upload Fails**
   - Ensure the file is a valid Slack export .zip
   - Check disk space in data/uploads directory
   - Verify Docker has sufficient resources

2. **Import Stalls**
   - Check Docker logs: `docker-compose logs -f web`
   - Ensure Ollama is running: `ollama list`
   - Verify MongoDB connection

3. **Search Not Working**
   - Confirm Ollama is running
   - Check if mistral model is installed
   - Verify data was imported successfully

### Getting Help

- Check Docker logs: `docker-compose logs -f web`
- Inspect MongoDB data: `docker-compose exec mongodb mongosh`
- Review application logs in data/logs

## Development

### Architecture

- FastAPI backend
- MongoDB database
- ChromaDB for vector storage
- Ollama for AI/ML features
- Jinja2 templates with Tailwind CSS

### Local Development

1. **Setup Development Environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # or `venv\Scripts\activate` on Windows
   pip install -r requirements.txt
   ```

2. **Run Tests**
   ```bash
   pytest tests/
   ```

### Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.
