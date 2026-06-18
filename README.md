# AI Study Planner

Gemini-powered chat app with user accounts, conversation history, and web search support.

## Stack

- **Backend:** FastAPI, MongoDB (Beanie ODM), JWT auth
- **Frontend:** React (Vite), Tailwind CSS
- **AI:** Google Gemini API

## Prerequisites

- Python 3.11+
- Node.js 18+
- MongoDB running locally (or a MongoDB Atlas connection string)

## Setup

### 1. Backend

```bash
cd backend
python -m venv ../venv
../venv/Scripts/activate   # Windows
pip install -r ../requirements.txt
```

Copy `.env.example` to `.env` and set:

- `GEMINI_API_KEY` — your Google Gemini API key
- `SECRET_KEY` — random string for JWT signing
- `MONGODB_URI` — e.g. `mongodb://localhost:27017`
- `MONGODB_DB` — database name (default: `gemini_agents`)

Start the API:

```bash
cd backend
uvicorn main:app --reload --port 8000
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). The Vite dev server proxies `/api` requests to the backend.

## Features

- Register / log in with password strength validation
- Multiple chat conversations per user
- Persistent message history in MongoDB
- Markdown rendering for assistant replies
- Web search: prefix a message with `search: your query` or `/search your query`

## Project structure

```
gemini_agents/
├── backend/
│   ├── main.py           # FastAPI app & routes
│   ├── models.py         # MongoDB documents
│   ├── database.py       # MongoDB connection
│   ├── auth.py           # JWT helpers
│   └── gemini_client.py  # Gemini + DuckDuckGo search
├── frontend/             # React SPA
└── requirements.txt
```
