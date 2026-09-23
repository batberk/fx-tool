import asyncio
from collections.abc import Awaitable, Callable

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

Reply = Callable[[httpx.Request], Awaitable[httpx.Response]]

KNOWN_CURRENCIES = {"EUR": "Euro", "TRY": "Turkish Lira", "USD": "US Dollar", "JPY": "Japanese Yen"}


class FakeUpstream:
    """In-process stand-in for frankfurter.dev that records every request."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.routes: dict[str, Reply] = {}
        self.on("/v1/currencies", json=KNOWN_CURRENCIES)

    def on(self, path: str, status: int = 200, json=None, text: str | None = None,
           error: Exception | None = None, delay: float = 0) -> None:
        async def reply(request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(delay)
            if error:
                raise error
            if text is not None:
                return httpx.Response(status, text=text)
            return httpx.Response(status, json=json)

        self.routes[path] = reply

    def rate(self, asked: str, rate: float = 47.1234, published: str | None = None,
             base: str = "EUR", target: str = "TRY") -> None:
        self.on(f"/v1/{asked}", json={
            "amount": 1.0, "base": base, "date": published or asked, "rates": {target: rate},
        })

    def paths(self) -> list[str]:
        return [request.url.path for request in self.requests]

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        reply = self.routes.get(request.url.path)
        if reply is None:
            return httpx.Response(404, json={"message": "not found"})
        return await reply(request)


@pytest.fixture
def upstream() -> FakeUpstream:
    return FakeUpstream()


@pytest.fixture
def client(upstream: FakeUpstream) -> TestClient:
    settings = Settings(upstream_base="http://upstream.test", upstream_timeout_seconds=0.2)
    app = create_app(settings, transport=httpx.MockTransport(upstream.handle))
    return TestClient(app, raise_server_exceptions=False)
