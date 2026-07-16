# PitchLens

AI-powered pitch deck analyzer that delivers investor-grade scorecards using a multi-agent architecture.

Upload a pitch deck PDF → get scored across 4 dimensions → receive actionable feedback in ~60 seconds.

## What it does

PitchLens uses specialized AI agents running in parallel to evaluate startup pitch decks:

| Dimension | What's evaluated |
|-----------|-----------------|
| **Market** | TAM/SAM/SOM, market timing, growth potential |
| **Team** | Founder backgrounds, relevant experience, completeness |
| **Business Model** | Revenue clarity, unit economics, scalability |
| **Competition** | Landscape awareness, differentiation, defensibility |

Each dimension produces a score (1-10), detailed reasoning, and specific improvement suggestions. A verdict aggregator synthesizes everything into a final scorecard with overall score and category ranking.

## Architecture

```
PDF Upload → Extractor Agent → 4 Parallel Scoring Agents → Verdict Aggregator → Scorecard
                                      ↓ (real-time)
                              WebSocket → Frontend Progress UI
```

- **Backend:** FastAPI + Python
- **AI Agents:** CrewAI with Claude Sonnet (via OpenAI-compatible proxy)
- **Frontend:** React 19 + TypeScript + Tailwind CSS 4 + Vite
- **Database:** PostgreSQL + pgvector (for RAG embeddings)
- **Real-time:** WebSocket streaming of analysis progress
- **Follow-up:** RAG-based chat grounded in deck content

## Features

- 🔐 JWT authentication with refresh tokens
- ⚡ Parallel agent execution (~60s total analysis)
- 📡 Real-time WebSocket progress streaming
- 💬 RAG-powered follow-up chat on analyzed decks
- 📊 Multi-dimensional scoring with detailed reasoning
- 🛡️ Prompt injection detection (fail-closed)
- ⏱️ Rate limiting (10 analyses/hour per user)
- 🌙 Dark/light mode
- 📱 Responsive design (375px–2560px)
- 📥 Downloadable HTML reports
- 📜 Paginated evaluation history

## Tech Stack

**Backend:**
Python, FastAPI, CrewAI, SQLAlchemy (async), PostgreSQL, pgvector, PyPDF2, bcrypt, PyJWT, Pydantic

**Frontend:**
React 19, TypeScript 6, Vite 8, Tailwind CSS 4, React Router 7, WebSocket (native)

**AI/LLM:**
Claude Sonnet (via OpenAI-compatible API), CrewAI agents, RAG with vector embeddings

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL 15+ with pgvector extension
- An LLM API key (OpenAI-compatible endpoint)

### Setup

1. **Clone:**
```bash
git clone https://github.com/sujal-31/pitchlens.git
cd pitchlens
```

2. **Backend:**
```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your database URL and LLM API key
python -m uvicorn app.main:app --port 8002 --reload
```

3. **Frontend:**
```bash
cd frontend
npm install
npm run dev
```

4. Open `http://localhost:3000`

### Environment Variables

Create a `.env` file from `.env.example`:

```
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/pitchlens
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://your-llm-proxy/v1
MODEL_ID=sonnet
JWT_SECRET=your-secret-key
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/register` | Create account |
| POST | `/api/auth/login` | Get tokens |
| POST | `/api/auth/refresh` | Refresh access token |
| POST | `/api/decks` | Upload PDF + start analysis |
| GET | `/api/decks/{id}/scorecard` | Get scorecard |
| POST | `/api/decks/{id}/chat` | Follow-up question (RAG) |
| GET | `/api/evaluations` | Evaluation history |
| WS | `/ws/analysis/{id}` | Real-time progress |

## Project Structure

```
pitchlens/
├── app/
│   ├── agents/          # AI scoring agents (CrewAI)
│   ├── api/             # REST endpoints + WebSocket
│   ├── db/              # Database models + migrations
│   ├── middleware/       # Rate limiting
│   ├── models/          # Pydantic schemas
│   ├── services/        # Business logic (orchestrator, auth, RAG)
│   └── main.py          # FastAPI entry point
├── frontend/
│   └── src/
│       ├── pages/       # Route components
│       ├── components/  # Shared UI
│       ├── hooks/       # WebSocket hook
│       └── contexts/    # Auth context
├── tests/               # Backend test suite
└── docs/                # Project documentation
```

## Testing

```bash
pytest tests/ -v
```

## License

MIT
