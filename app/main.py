from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, Query

from app.config import Settings
from app.errors import register_error_handlers
from app.service import ConversionService
from app.upstream import FrankfurterClient
from app.validation import parse_convert_request


def create_app(
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    client = FrankfurterClient(settings.upstream_base, settings.upstream_timeout_seconds, transport)
    service = ConversionService(client)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await client.aclose()

    app = FastAPI(title="fx-tool", lifespan=lifespan)
    register_error_handlers(app)

    @app.get("/tools/convert")
    async def convert(
        amount: str | None = None,
        from_currency: str | None = Query(None, alias="from"),
        to: str | None = None,
        date: str | None = None,
    ) -> dict[str, Any]:
        """Convert an amount with ECB reference rates.

        `rate_date` is the day the rate belongs to; when it differs from
        `asked_date`, `note` says so and the customer should be told.
        """
        request = parse_convert_request(amount, from_currency, to, date, today=_utc_today())
        return await service.convert(request)

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    return app


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


app = create_app()
