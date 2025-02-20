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
