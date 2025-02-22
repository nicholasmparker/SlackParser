# 🚀 Slack Export Viewer

A beautiful, modern web application for viewing and searching your Slack workspace exports. Built with FastAPI, MongoDB, and styled to match Slack's sleek design.

![Python](https://img.shields.io/badge/python-3.11-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-latest-009688.svg)
![MongoDB](https://img.shields.io/badge/MongoDB-latest-47A248.svg)
![Docker](https://img.shields.io/badge/docker-latest-2496ED.svg)

## ✨ Features

### 💬 Message Viewing
- Browse channels and direct messages with a familiar Slack-like interface
- View message history with user avatars and timestamps
- Support for code blocks and inline code formatting
- Responsive design that works on all devices

### 🔍 Powerful Search
- Search across all messages and channels
- Results show channel context and timestamps
- Clean, modern search interface

### 👨‍💼 Admin Tools
- View system stats (total messages, channels, users)
- Import new messages from Slack exports
- Flush data for fresh imports
- Monitor import history

### 🎨 Modern UI
- Slack-inspired design
- Dark mode support
- Responsive layout
- Beautiful transitions and hover effects

## 🛠 Tech Stack
- **Backend**: FastAPI (Python 3.11)
- **Database**: MongoDB
- **Frontend**: HTML + Tailwind CSS
- **Deployment**: Docker + Docker Compose

## 📦 Prerequisites
- Docker and Docker Compose
- A Slack workspace export (in JSON format)

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
```
slack-export-viewer/
├── app/                    # Main application code
│   ├── static/            # Static assets
│   │   └── css/          # CSS files
│   ├── templates/        # HTML templates
│   ├── import_data.py   # Data import logic
│   └── main.py         # FastAPI application
├── data/                # Slack export data
├── docker-compose.yml   # Docker configuration
└── requirements.txt    # Python dependencies
```

## 🔧 Configuration
The application can be configured using environment variables in `docker-compose.yml`:

| Variable | Description | Default |
|----------|-------------|---------|
| `MONGODB_URL` | MongoDB connection string | `mongodb://mongodb:27017` |
| `DATA_DIR` | Directory containing Slack export | `data` |
| `FILE_STORAGE` | Directory for uploaded files | `file_storage` |

## 💡 Usage Tips

### Importing Data
1. Go to the Admin page at `/admin`
2. Click "Import New Messages"
3. Watch your messages appear! 🪄

### Searching Messages
1. Use the search bar at the top of any page
2. Results are sorted by relevance
3. Click channel names to jump to conversations

### Managing Data
- Use the "Flush Data" button in Admin to start fresh
- Import status is shown after each import
- Monitor system stats in the Admin dashboard

## 🤝 Contributing
Contributions are welcome! Here's how you can help:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## 📝 License
This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments
- Built with [FastAPI](https://fastapi.tiangolo.com/)
- Styled with [Tailwind CSS](https://tailwindcss.com/)
- Inspired by Slack's beautiful design

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
