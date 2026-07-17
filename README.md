# SpecAdversary Product Specification

SpecAdversary is an AI-powered stress-testing platform designed to harden product and technical specifications. By routing raw ideas through a specialized panel of AI agents, the system identifies vulnerabilities and synthesizes a revised, robust specification.

## 🎯 Core Workflow

Users provide a raw product thesis or technical specification. The system then executes a multi-agent pipeline via LangGraph:

1.  **🔍 Assumption Hunter:** Identifies unverified claims masquerading as facts.
2.  **⚔️ Competitor Simulator:** Role-plays as a rival team to identify competitive vulnerabilities.
3.  **◈ Economics Tester:** Evaluates unit economics, cost structures, and pricing models.
4.  **⚙️ Feasibility Auditor:** Pinpoints technical risks and scalability bottlenecks.

**Synthesis:** The system reconciles the feedback from all agents to generate a single, hardened, revised specification.

---

## 🏗️ System Architecture & Tech Stack

### Frontend

- **Framework:** React 18 + TypeScript + Vite
- **Features:** Dark-mode, 3-column layout with real-time WebSocket streaming for live agent feedback.

### Backend

- **Framework:** Python 3.12 + FastAPI
- **Orchestration:** LangGraph (Multi-agent state management)
- **LLM Integration:** OpenRouter (OpenAI-compatible API supporting JSON mode/Structured Outputs)
- **Database/Storage:** SQLModel for session storage; SQLite/PostgreSQL

### Deployment

- **Containerization:** Docker & Docker Compose

---

## 🛠️ Technical Roadmap & Implementation Notes

To ensure the system moves beyond a basic LLM wrapper and provides professional-grade utility, the following technical requirements and architectural patterns must be addressed:

### 1. Agent Intelligence & Domain Expertise

- **Vertical Specialization:** To avoid generic critiques, the system should implement "Expert Mode" modules. This allows users to select specific domains (e.g., Fintech, Cloud Infrastructure) to load specialized agent personas and industry-standard knowledge bases.
- **RAG Integration:** To move beyond generic LLM responses, a Retrieval-Augmented Generation (RAG) layer containing technical whitepapers and PM frameworks should be integrated to provide authoritative feedback.

### 2. Orchestration & State Management

- **Conflict Resolution:** The synthesis step must include a dedicated "Moderator" node within the LangGraph to reconcile contradictory feedback (e.g., balancing feature requests vs. economic constraints) and prevent "hallucination loops."
- **Asynchronous Processing:** Given the high-latency nature of multi-agent reasoning, the backend must decouple HTTP requests from agent execution using `FastAPI BackgroundTasks` or a dedicated task queue (e.g., Redis/Celery) to prevent connection timeouts.
- **Tiered Execution Models:**
  - _Quick Scan:_ A lightweight, single-pass reasoning model for instant sanity checks.
  - _Deep Dive:_ The full LangGraph multi-agent orchestration for comprehensive hardening.

### 3. Data Integrity & Input Validation

- **Schema Enforcement:** To prevent context loss, the system should enforce a structured input schema (e.g., Markdown with specific headers) to ensure agents can distinguish between verified data and unstated assumptions.

---

## 📁 Project Structure

```text
SpecAdversary/
├── frontend/             # React + Vite frontend
│   ├── src/
│   │   ├── App.tsx       # Main application layout and state
│   │   ├── LiveFeed.tsx  # Real-time streaming UI for AI findings
│   │   ├── ReportView.tsx# Diff view and revised specification
│   │   └── SpecInput.tsx # Input panel for uploading specs
│   └── Dockerfile
├── backend/              # FastAPI + LangGraph backend
│   ├── main.py           # FastAPI entrypoint and WebSocket handler
│   ├── graph.py          # LangGraph multi-agent pipeline
│   ├── models.py         # Pydantic schemas and SQLModel tables
│   ├── database.py       # Database configuration
│   └── Dockerfile
└── docker-compose.yml    # Multi-container orchestration
```

## 🚀 Getting Started

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) & Docker Compose
- [OpenRouter](https://openrouter.ai/) API key

### Installation

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
   ```

3. **Run:**

   ```bash
   docker compose up --build
   ```

4. **Access:**
   Navigate to `http://localhost:5174`


