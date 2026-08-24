# SpecAdversary

SpecAdversary is an AI-powered stress-testing platform designed to harden product and technical specifications. By routing raw ideas through a specialized panel of AI agents, the system identifies vulnerabilities and synthesizes a revised, robust specification.

## Key Capabilities

Users provide a raw product thesis or technical specification. The system then executes a multi-agent pipeline via LangGraph:

- **Multi-Agent Pipeline:**
  - **Assumption Hunter:** Identifies unverified claims masquerading as facts.
  - **Competitor Simulator:** Role-plays as a rival team to identify competitive vulnerabilities.
  - **Economics Tester:** Evaluates unit economics, cost structures, and pricing models.
  - **Feasibility Auditor:** Pinpoints technical risks and scalability bottlenecks.
- **Real-time Streaming:** Delivers live, real-time agent feedback directly to the client via WebSockets.
- **Durable execution:** Redis-dispatched workers persist every analysis run and stream event to PostgreSQL, so reconnects and backend restarts do not discard work.
- **Secure Authentication:** Implements a robust JWT-based authentication system featuring anonymous guest soft-gating and seamless session claiming upon registration.

## System Architecture

### Frontend
- **Framework:** React 18, TypeScript, Vite
- **Routing & State:** React Router DOM, React Context API
- **Design:** Dark-mode, 3-column layout optimized for real-time WebSocket data consumption

### Backend
- **Framework:** Python 3.12, FastAPI
- **Orchestration:** LangGraph (Multi-agent state management)
- **LLM Integration:** OpenRouter (OpenAI-compatible API supporting JSON mode and Structured Outputs)
- **Database & Security:** SQLModel (SQLite/PostgreSQL), Passlib (Bcrypt hashing), Python-JOSE (JWT handling)

### Deployment
- **Containerization:** Docker & Docker Compose

## Repository Structure

```text
SpecAdversary/
├── frontend/             # React + Vite frontend
│   ├── src/
│   │   ├── components/   # Modular UI components (app, landing)
│   │   ├── pages/        # Route-level pages (AdversaryApp, Login, Landing)
│   │   ├── styles/       # CSS style tokens
│   │   ├── App.tsx       # Main router entry point
│   │   └── AuthContext.tsx # Global authentication state manager
│   └── Dockerfile
├── backend/              # FastAPI + LangGraph backend
│   ├── main.py           # API endpoints, WebSockets, and Auth routes
│   ├── auth.py           # Security, password hashing, and JWT utilities
│   ├── graph.py          # LangGraph multi-agent pipeline
│   ├── models.py         # Pydantic schemas and SQLModel tables
│   ├── database.py       # Database connection configuration
│   ├── alembic/          # Database migrations
│   ├── tests/            # Pytest test suite
│   └── Dockerfile
└── docker-compose.yml    # Multi-container orchestration
```

## Getting Started

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) & Docker Compose
- Node.js (v18+) and Python 3.12+ (For local development)
- [OpenRouter](https://openrouter.ai/) API key

### Installation (Docker)

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd SpecAdversary
   ```

2. **Configure Environment:**
   Create a `.env` file in the `backend/` directory:
   ```env
   OPENAI_BASE_URL=https://openrouter.ai/api/v1
   OPENAI_API_KEY=your_key_here
   OPENAI_MODEL=google/gemini-2.5-flash-lite
   JWT_SECRET=your_super_secret_jwt_key
   ```

3. **Run the services:**
   ```bash
   docker compose up --build
   ```

4. **Access the application:**
   Navigate your browser to `http://localhost:5174`. The `worker` service processes queued analyses; it must remain running with the API.

### Local Development Guide

If you prefer to run the services outside of Docker for development:

**Backend Setup:**
```bash
cd backend
python -m venv .venv
# Activate virtual environment
# Windows: .venv\Scripts\Activate.ps1
# Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --reload
```

**Frontend Setup:**
```bash
cd frontend
npm install
npm run dev
```

**Testing:**
```bash
cd backend
python -m pytest tests/ -v
```
