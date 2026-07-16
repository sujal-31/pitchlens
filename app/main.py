"""PitchLens FastAPI Application.

AI-powered pitch deck analysis platform with multi-agent scoring,
real-time WebSocket streaming, and RAG-based follow-up chat.
"""

from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router as api_router
from app.api.ws import router as ws_router
from app.middleware.rate_limiter import RateLimiterMiddleware
from app.services.ws_manager import ws_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown lifecycle events."""
    # Startup: initialize resources
    print("PitchLens starting up...")
    # Database connection pool is initialized on first use via SQLAlchemy engine
    # WebSocket manager is initialized as a module-level singleton
    # TODO: Warm up injection guard patterns
    yield
    # Shutdown: clean up resources
    print("PitchLens shutting down...")
    await ws_manager.shutdown()
    from app.db.database import close_db

    await close_db()


app = FastAPI(
    title="PitchLens API",
    description="AI-powered pitch deck analysis platform",
    version="0.1.0",
    lifespan=lifespan,
    redirect_slashes=False,
)

# CORS configuration for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiter middleware
app.add_middleware(RateLimiterMiddleware)

# Mount API routes
app.include_router(api_router, prefix="/api")

# Mount WebSocket routes (no /api prefix - WebSocket at /ws/analysis/{id})
app.include_router(ws_router)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "pitchlens"}
