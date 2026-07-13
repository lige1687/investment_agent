"""FastAPI application entry point."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from app.config import settings
from app.database import init_db
from app.skills.bridge import bridge
from app.skills.strategies.direct_api import DirectAPIStrategy
from app.skills.strategies.claude_api import ClaudeAPIStrategy
from app.skills.strategies.claude_cli import ClaudeCLIStrategy


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup: initialize database and register skill strategies
    await init_db()

    # Register SkillBridge strategies (order = priority)
    bridge.register(DirectAPIStrategy())
    if settings.anthropic_api_key:
        bridge.register(ClaudeAPIStrategy())
    bridge.register(ClaudeCLIStrategy())

    # Store bridge in app state for access from routes
    app.state.bridge = bridge

    # Start task scheduler
    from app.tasks.scheduler import setup_scheduler
    setup_scheduler()

    yield

    # Shutdown: stop scheduler
    from app.tasks.scheduler import scheduler
    scheduler.shutdown(wait=False)


app = FastAPI(
    title="Fund Investment Agent",
    description="基金/ETF 投资辅助系统",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS - allow frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routes
from app.api.v1.router import api_router  # noqa: E402
app.include_router(api_router)


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
async def root_redirect():
    """Send browser visits on the API port to the frontend app."""
    return RedirectResponse(url="http://localhost:5173/", status_code=307)


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "version": "0.1.0"}
