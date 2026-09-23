import asyncio
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import httpx

from app.errors import ApiError


@dataclass(frozen=True)
class PublishedRate:
    rate: Decimal
    rate_date: date


class RateNotFound(Exception):
    """The upstream has no rate for this pair on or before the asked date."""


class FrankfurterClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._http = httpx.AsyncClient(base_url=base_url, timeout=timeout_seconds, transport=transport)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get_rate(self, base: str, target: str, on: date | None) -> PublishedRate:
        path = f"/v1/{on.isoformat() if on else 'latest'}"
        response = await self._get(path, params={"base": base, "symbols": target})
        if response.status_code == 404:
            raise RateNotFound
        _expect_ok(response)
        return _parse_rate(_json(response), base, target)

    async def get_currencies(self) -> set[str]:
        response = await self._get("/v1/currencies")
        _expect_ok(response)
        payload = _json(response)
        if not isinstance(payload, dict) or not payload:
            raise _bad_response("the currency list was empty or not an object")
        return {str(code).upper() for code in payload}

    async def _get(self, path: str, params: dict[str, str] | None = None) -> httpx.Response:
        # httpx timeouts apply per network operation; wait_for bounds the whole call.
        try:
            return await asyncio.wait_for(self._http.get(path, params=params), self._timeout_seconds)
        except (asyncio.TimeoutError, httpx.TimeoutException):
            raise ApiError(504, "upstream_timeout", "The rate provider did not answer in time; no rate was returned.")
        except httpx.TransportError:
            raise ApiError(503, "upstream_unavailable", "The rate provider could not be reached; no rate was returned.")


def _expect_ok(response: httpx.Response) -> None:
    if response.status_code != 200:
        raise ApiError(
            502, "upstream_error",
            f"The rate provider answered with HTTP {response.status_code}; no rate was returned.",
        )


def _json(response: httpx.Response) -> Any:
    try:
        return json.loads(response.content, parse_float=Decimal)
    except ValueError:
        raise _bad_response("it was not JSON")


def _parse_rate(payload: Any, base: str, target: str) -> PublishedRate:
    if not isinstance(payload, dict) or not isinstance(payload.get("rates"), dict):
        raise _bad_response("it had no rates")
    if payload.get("base") != base:
        raise _bad_response(f"it was for base {payload.get('base')!r}, not {base}")

    rate_date = _parse_date(payload.get("date"))
    if rate_date is None:
        raise _bad_response("it did not say which date the rate is from")

    if target not in payload["rates"]:
        raise RateNotFound
    rate = payload["rates"][target]
    # NaN/Infinity parse as float and booleans are ints, so both are excluded here.
    if isinstance(rate, bool) or not isinstance(rate, (int, Decimal)) or rate <= 0:
        raise _bad_response(f"the rate {rate!r} is not a positive number")
    return PublishedRate(rate=Decimal(rate), rate_date=rate_date)


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _bad_response(reason: str) -> ApiError:
    return ApiError(
        502, "upstream_bad_response",
        f"The rate provider sent an unusable answer ({reason}); no rate was returned.",
    )
