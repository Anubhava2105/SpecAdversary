# SpecAdversary

SpecAdversary is an AI-powered tool that stress-tests your product and technical specifications by sending them into a room full of hostile specialists. It analyzes your ideas, identifies weak points, and synthesizes a hardened, revised specification.

## 🎯 How It Works

You provide a raw product thesis or technical spec. SpecAdversary routes it through a LangGraph pipeline to a panel of specialized AI critics:

1. **🔍 Assumption Hunter:** Finds claims treated as fact that are actually unverified assumptions.
2. **⚔️ Competitor Simulator:** Role-plays as a rival team finding ways to build it cheaper, faster, or better.
3. **◈ Economics Tester:** Pressure-tests unit economics, cost structure, and pricing.
4. **⚙️ Feasibility Auditor:** Finds technical risks and scalability cliffs you might be glossing over.

Once the critics have finished their teardown, the system synthesizes their findings into a revised, hardened specification.

## 🏗️ Architecture

- **Frontend:** React + TypeScript + Vite. Features a dark-mode, 3-column layout with real-time WebSocket streaming for live feedback.
- **Backend:** Python + FastAPI. Uses LangGraph for orchestrating the multi-agent AI pipeline and SQLModel for session storage.
- **LLM Integration:** Powered by OpenRouter (compatible with OpenAI's Chat Completions API + Structured Outputs via JSON mode).
- **Deployment:** Fully containerized with Docker and Docker Compose.

## 🚀 Getting Started

### Prerequisites
- [Docker](https://docs.docker.com/get-docker/) & Docker Compose
- An [OpenRouter](https://openrouter.ai/) API key

### Installation

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd SpecAdversary
   ```

2. **Configure Environment Variables:**
   Navigate to the `backend` directory and edit the `.env` file with your OpenRouter API key and preferred model slug:
   ```env
   OPENAI_BASE_URL=https://openrouter.ai/api/v1
   OPENAI_API_KEY=your_openrouter_api_key_here
   OPENAI_MODEL=google/gemini-2.5-flash-lite
   ```
   *(Note: The system uses the Chat Completions API with `response_format={"type": "json_object"}`, so ensure your chosen model supports JSON mode).*

3. **Run with Docker:**
   From the root of the project, run:
   ```bash
   docker compose up --build
   ```

4. **Access the App:**
   Open your browser and navigate to `http://localhost:5174`

## 📁 Project Structure

```
SpecAdversary/
├── frontend/             # React + Vite frontend
│   ├── src/
│   │   ├── App.tsx       # Main application layout and state
│   │   ├── LiveFeed.tsx  # Real-time streaming UI for AI findings
│   │   ├── ReportView.tsx# Diff view and revised specification
│   │   └── SpecInput.tsx # Input panel for pasting/uploading specs
│   └── Dockerfile
├── backend/              # FastAPI + LangGraph backend
│   ├── main.py           # FastAPI entrypoint and WebSocket handler
│   ├── graph.py          # LangGraph multi-agent pipeline
│   ├── models.py         # Pydantic schemas and SQLModel tables
│   ├── database.py       # SQLite database configuration
│   └── Dockerfile
└── docker-compose.yml    # Multi-container orchestration
```

## 🛠️ Tech Stack
- React 18, TypeScript, Vite
- Python 3.12, FastAPI, Uvicorn
- LangGraph, OpenAI SDK
- SQLModel, PostgreSQL
- Docker

## 📝 License
MIT
