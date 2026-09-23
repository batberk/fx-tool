import asyncio

import pytest

from app.cache import TtlCache

PARAMS = {"amount": "250", "from": "EUR", "to": "TRY", "date": "2026-08-28"}


def test_repeated_question_does_not_ask_upstream_again(client, upstream):
    upstream.rate("2026-08-28")

    first = client.get("/tools/convert", params=PARAMS).json()
    second = client.get("/tools/convert", params={**PARAMS, "amount": "10", "from": "eur"}).json()

    assert upstream.paths() == ["/v1/2026-08-28"]
    assert first["rate"] == second["rate"]


def test_different_date_asks_upstream_again(client, upstream):
    upstream.rate("2026-08-28")
    upstream.rate("2026-08-27", rate=47.0)

    client.get("/tools/convert", params=PARAMS)
    body = client.get("/tools/convert", params={**PARAMS, "date": "2026-08-27"}).json()

    assert upstream.paths() == ["/v1/2026-08-28", "/v1/2026-08-27"]
    assert body["rate"] == 47.0


def test_latest_is_cached_too(client, upstream):
    upstream.rate("latest", published="2026-09-22")
    params = {key: value for key, value in PARAMS.items() if key != "date"}

    client.get("/tools/convert", params=params)
    client.get("/tools/convert", params=params)

    assert upstream.paths() == ["/v1/latest"]


def test_failures_are_not_cached(client, upstream):
    upstream.on("/v1/2026-08-28", status=500, json={})
    assert client.get("/tools/convert", params=PARAMS).status_code == 502

    upstream.rate("2026-08-28")
    assert client.get("/tools/convert", params=PARAMS).status_code == 200
    assert upstream.paths() == ["/v1/2026-08-28", "/v1/2026-08-28"]


def test_currency_list_is_cached(client, upstream):
    client.get("/tools/convert", params={**PARAMS, "to": "XYZ"})
    client.get("/tools/convert", params={**PARAMS, "to": "ABC"})

    assert upstream.paths().count("/v1/currencies") == 1


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def fetch_counter():
    calls = []

    async def fetch():
        calls.append(1)
        return len(calls)

    return fetch, calls


def test_entry_expires_after_its_ttl():
    clock = FakeClock()
    cache = TtlCache(clock=clock)
    fetch, calls = fetch_counter()

    async def scenario():
        assert await cache.get_or_fetch("k", fetch, ttl_seconds=60) == 1
        clock.now = 59
        assert await cache.get_or_fetch("k", fetch, ttl_seconds=60) == 1
        clock.now = 60
        assert await cache.get_or_fetch("k", fetch, ttl_seconds=60) == 2

    asyncio.run(scenario())
    assert len(calls) == 2


def test_entry_without_ttl_never_expires():
    clock = FakeClock()
    cache = TtlCache(clock=clock)
    fetch, calls = fetch_counter()

    async def scenario():
        await cache.get_or_fetch("k", fetch, ttl_seconds=None)
        clock.now = 10**9
        await cache.get_or_fetch("k", fetch, ttl_seconds=None)

    asyncio.run(scenario())
    assert len(calls) == 1


def test_oldest_entry_is_evicted_when_full():
    cache = TtlCache(max_entries=2)
    fetch, calls = fetch_counter()

    async def scenario():
        for key in ("a", "b", "c", "b", "a"):
            await cache.get_or_fetch(key, fetch, ttl_seconds=None)

    asyncio.run(scenario())
    assert len(calls) == 4  # a, b, c, then a again after it was evicted


def test_concurrent_requests_share_one_fetch():
    cache = TtlCache()
    release = asyncio.Event()
    calls = []

    async def slow_fetch():
        calls.append(1)
        await release.wait()
        return "rate"

    async def scenario():
        waiting = [asyncio.create_task(cache.get_or_fetch("k", slow_fetch, None)) for _ in range(5)]
        await asyncio.sleep(0)
        release.set()
        return await asyncio.gather(*waiting)

    assert asyncio.run(scenario()) == ["rate"] * 5
    assert len(calls) == 1


def test_failed_fetch_is_not_cached():
    cache = TtlCache()

    async def failing():
        raise RuntimeError("upstream down")

    async def scenario():
        with pytest.raises(RuntimeError):
            await cache.get_or_fetch("k", failing, None)
        fetch, calls = fetch_counter()
        assert await cache.get_or_fetch("k", fetch, None) == 1

    asyncio.run(scenario())
