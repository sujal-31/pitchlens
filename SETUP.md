# PitchLens — Setup & Deployment Guide

## Prerequisites

- Python 3.11+ (use `py` on Windows, `python3` on Mac/Linux)
- Node.js 18+
- PostgreSQL 15+ with pgvector extension enabled
- An LLM API key (OpenAI-compatible endpoint — e.g., Claude Sonnet via proxy)

---

## Local Development

### 1. Clone the repository

```bash
git clone https://github.com/sujal-31/pitchlens.git
cd pitchlens
```

### 2. Set up the environment file

```bash
cp .env.example .env
```

Edit `.env` with your values:

```env
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/pitchlens
JWT_SECRET=your-random-secret-key-here
LLM_API_KEY=your-llm-api-key
LLM_BASE_URL=https://your-openai-compatible-proxy/v1
MODEL_ID=sonnet
```

### 3. Set up PostgreSQL

```sql
-- Create database
CREATE DATABASE pitchlens;

-- Enable pgvector extension (connect to pitchlens db first)
\c pitchlens
CREATE EXTENSION IF NOT EXISTS vector;
```

### 4. Start the Backend

```bash
# Install Python dependencies
pip install -r requirements.txt

# Run the server (Windows)
py -m uvicorn app.main:app --port 8002 --reload

# Run the server (Mac/Linux)
python -m uvicorn app.main:app --port 8002 --reload
```

Backend will be available at `http://localhost:8002`

API docs at `http://localhost:8002/docs` (Swagger UI)

### 5. Start the Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend will be available at `http://localhost:3000`

The Vite dev server automatically proxies `/api` requests to `localhost:8002`.

### 6. Verify it's working

1. Open `http://localhost:3000`
2. Register a new account
3. Upload a PDF pitch deck
4. Watch real-time analysis progress
5. View the generated scorecard

---

## Running Tests

```bash
# From project root
pytest tests/ -v

# Run a specific test file
pytest tests/test_orchestrator.py -v

# Run with coverage
pytest tests/ --cov=app --cov-report=html
```

---

## Deployment

### Option A: Render (Free Tier)

**Backend:**

1. Create a new Web Service on [render.com](https://render.com)
2. Connect your GitHub repo (`sujal-31/pitchlens`)
3. Settings:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - Environment: Python 3
4. Add environment variables in Render dashboard:
   - `DATABASE_URL` (use Render's PostgreSQL service)
   - `JWT_SECRET`
   - `LLM_API_KEY`
   - `LLM_BASE_URL`
   - `MODEL_ID`

**Database:**

1. Create a PostgreSQL instance on Render
2. Connect to it and run: `CREATE EXTENSION IF NOT EXISTS vector;`
3. Copy the internal connection string to `DATABASE_URL`

**Frontend:**

1. Create a new Static Site on Render
2. Root Directory: `frontend`
3. Build Command: `npm install && npm run build`
4. Publish Directory: `dist`
5. Add environment variable:
   - `VITE_API_BASE_URL=https://your-backend-service.onrender.com`

### Option B: Vercel (Frontend) + Railway (Backend)

**Frontend on Vercel:**

```bash
cd frontend
npx vercel --prod
```

Or connect the repo on [vercel.com](https://vercel.com):
- Framework: Vite
- Root Directory: `frontend`
- Build Command: `npm run build`
- Output Directory: `dist`
- Environment variable: `VITE_API_BASE_URL=https://your-backend.railway.app`

**Backend on Railway:**

1. Create a new project on [railway.app](https://railway.app)
2. Connect GitHub repo
3. Add a PostgreSQL service (Railway provides one with pgvector)
4. Settings:
   - Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Add env vars: `DATABASE_URL`, `JWT_SECRET`, `LLM_API_KEY`, `LLM_BASE_URL`, `MODEL_ID`

### Option C: Docker (Self-hosted)

Create a `Dockerfile` in project root:

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY .env .

EXPOSE 8002
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
```

Build and run:

```bash
docker build -t pitchlens-backend .
docker run -p 8002:8002 --env-file .env pitchlens-backend
```

For the frontend:

```bash
cd frontend
npm run build
# Serve the dist/ folder with any static file server (nginx, caddy, etc.)
```

---

## Environment Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string (asyncpg format) |
| `JWT_SECRET` | Yes | Secret key for signing JWT tokens |
| `LLM_API_KEY` | Yes | API key for LLM provider |
| `LLM_BASE_URL` | Yes | Base URL of OpenAI-compatible LLM endpoint |
| `MODEL_ID` | No | Model identifier (default: `sonnet`) |

---

## Common Issues

**"Python was not found"** (Windows)
→ Use `py` instead of `python`, or add Python to PATH during installation.

**"Module not found: app"**
→ Make sure you're running from the project root directory, not from inside `app/`.

**Database connection refused**
→ Ensure PostgreSQL is running and the `DATABASE_URL` in `.env` is correct.

**Frontend shows "Backend not running"**
→ Start the backend on port 8002 first. The frontend proxy expects it there.

**pgvector extension not found**
→ Run `CREATE EXTENSION IF NOT EXISTS vector;` in your database.

**WebSocket connection fails**
→ Ensure both frontend and backend are running. Check browser console for CORS errors.

---

## Useful Commands

```bash
# Check backend is healthy
curl http://localhost:8002/docs

# Check frontend proxy is working
curl http://localhost:3000/api/auth/login  # should return 405 (method not allowed, not 404)

# Database migration (if needed)
py -c "from app.db.database import init_db; import asyncio; asyncio.run(init_db())"

# Build frontend for production
cd frontend && npm run build
```
