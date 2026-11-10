"""FastAPI application factory. Routers are mounted under /api/v1 as milestones land."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api import accounts, auth, book, clients, ingest, models, transitions
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger, new_request_id, request_id_var

API_PREFIX = "/api/v1"


def sync_catalog_on_startup() -> None:
    """Reload data/models/target_models.json into the DB so edits apply on restart."""
    s = get_settings()
    log = get_logger("startup")
    if s.ANALYTICS_PROVIDER != "random":
        log.info("catalog sync skipped (non-synthetic provider)")
        return
    from app.db import models as m
    from app.db.catalog import build_fund_proxies, load_catalog
    from app.db.catalog_sync import sync_catalog
    from app.db.session import get_engine, get_sessionmaker, init_db
    from app.db.synthetic_market import load_or_generate

    init_db(get_engine())
    with get_sessionmaker()() as session:
        if session.query(m.Security).filter_by(security_type="equity").count() == 0:
            log.warning("database not seeded; run scripts/seed_demo.py")
            return
        market = load_or_generate(
            s.DATA_DIR, s.SYNTHETIC_SEED, s.AS_OF_DATE, s.UNIVERSE_SIZE, s.PRICE_HISTORY_YEARS
        )
        catalog = load_catalog(s.MODELS_FILE)
        ids = sync_catalog(session, catalog, market, build_fund_proxies(market, catalog))
        log.info("catalog synced", models=ids)
        from app.analytics.factory import get_provider
        from app.db.book_store import enable_write_through, set_price_source, sync_from_file

        set_price_source(get_provider().get_prices)
        what = sync_from_file(session, s.BOOK_FILE, market.as_of)
        enable_write_through(s.BOOK_FILE, market.as_of, engine=get_engine())
        log.info("book file", action=what, path=str(s.BOOK_FILE))
    import threading

    threading.Thread(target=warm_book_cache, name="warm-book-cache", daemon=True).start()


def warm_book_cache() -> None:
    """Precompute the landing-page numbers (cached until the book changes)."""
    from app.analytics.factory import get_provider
    from app.analytics.types import Granularity
    from app.db import models as m
    from app.db.session import get_sessionmaker
    from app.services.portfolio import PortfolioService

    log = get_logger("startup")
    try:
        with get_sessionmaker()() as session:
            p = get_provider()
            for advisor_id in session.scalars(select(m.Advisor.id)).all():
                svc = PortfolioService(session, p, advisor_id)
                svc.book_summary()
                svc.client_rows()
                svc.book_tax_impact(Granularity.MONTH)
                svc.book_activity(Granularity.MONTH)
                svc.book_tracking_error(63)
        log.info("book cache warmed")
    except Exception as exc:  # warming is best-effort
        log.warning("book cache warm-up failed", error=str(exc))


def create_app(sync_catalog: bool = True) -> FastAPI:
    """Build the FastAPI app with logging, request IDs and CORS.

    ``sync_catalog=False`` skips the startup catalog reload (tests use their own DB).
    """
    s = get_settings()
    configure_logging(s.LOG_LEVEL)
    log = get_logger("http")
    from app.db.book_store import install_listeners

    install_listeners()  # book cache invalidation (+ book file write-through once enabled)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if sync_catalog:
            sync_catalog_on_startup()
        yield
        from app.db.book_store import wait_for_book_writes

        wait_for_book_writes()  # don't lose the last change on shutdown

    app = FastAPI(
        lifespan=lifespan,
        title=s.APP_NAME,
        version="1.0.0",
        description=(
            "Transition Studio API (v1). Internal prototype on SYNTHETIC data only. "
            "Analytics are simulated (data_source=mock_random). Not tax or investment advice."
        ),
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url="/docs",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get("X-Request-ID") or new_request_id()
        token = request_id_var.set(rid)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        # path + status + timing only — never bodies, query values or user identifiers (no PII)
        log.info(
            "request",
            request_id=rid,
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            ms=round((time.perf_counter() - start) * 1000, 1),
        )
        return response

    for r in (
        auth.router,
        book.router,
        clients.router,
        accounts.router,
        models.router,
        transitions.router,
        ingest.router,
    ):
        app.include_router(r, prefix=API_PREFIX)

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok", "demo_mode": str(s.DEMO_MODE).lower()}

    return app


app = create_app()
