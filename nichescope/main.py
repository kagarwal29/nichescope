"""NicheScope — FastAPI application entrypoint."""
from __future__ import annotations
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from nichescope.api.auth import router as auth_router
from nichescope.api.channels import router as channels_router
from nichescope.api.gaps import router as gaps_router
from nichescope.api.insights import router as insights_router
from nichescope.api.reports import router as reports_router
from nichescope.config import settings
from nichescope.jobs.scheduler import create_scheduler
from nichescope.models.base import Base, engine

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ensured")
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("Background scheduler started")
    bot_app = None
    if settings.telegram_bot_token:
        from nichescope.bot.bot import start_bot_polling
        bot_app = await start_bot_polling()
    yield
    scheduler.shutdown(wait=False)
    if bot_app:
        from nichescope.bot.bot import stop_bot
        await stop_bot(bot_app)
    logger.info("Shutdown complete")

app = FastAPI(
    title="NicheScope",
    description="Creator Intelligence Platform",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(channels_router)
app.include_router(gaps_router)
app.include_router(insights_router)
app.include_router(reports_router)

@app.get("/health")
async def health():
    return {"status": "ok", "service": "nichescope"}
