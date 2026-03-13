"""FastAPI app entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.api.routes import init_clients, router
from src.db.database import close_db, get_db
from src.enrichment.categorizer import Categorizer
from src.services.simplefin import SimpleFinClient
from src.services.ynab import YNABClient
from src.utils.logging import logger

_ynab: YNABClient | None = None
_simplefin: SimpleFinClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _ynab, _simplefin

    logger.info("Starting YNAB Enrichment API")

    # Initialize database
    await get_db()

    # Initialize API clients
    _ynab = YNABClient()
    _simplefin = SimpleFinClient()

    # Initialize categorizer
    categorizer = Categorizer()
    try:
        await categorizer.initialize(_ynab)
    except Exception as e:
        logger.warning("Failed to initialize categorizer (will retry on first use): %s", e)

    # Share clients with routes
    init_clients(_ynab, _simplefin, categorizer)

    logger.info("YNAB Enrichment API ready")
    yield

    # Cleanup
    logger.info("Shutting down YNAB Enrichment API")
    await _ynab.close()
    await _simplefin.close()
    await close_db()


app = FastAPI(
    title="YNAB Transaction Enrichment API",
    description="Enrich and validate YNAB transactions using SimpleFin and Amazon order data.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled error on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error: {type(exc).__name__}: {exc}"},
    )


app.include_router(router)
