from collections.abc import Callable
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.cache import TtlCache
from app.errors import ApiError
from app.upstream import FrankfurterClient, PublishedRate, RateNotFound
from app.validation import ConvertRequest

SOURCE = "ECB via frankfurter.dev"
CENT = Decimal("0.01")
# Weekends plus the longest ECB holiday run (Easter, Christmas) stay well under
# a week; a bigger gap means the rate is too old to hand to a customer.
MAX_FALLBACK_DAYS = 7
CURRENCIES_TTL_SECONDS = 24 * 60 * 60


class ConversionService:
    def __init__(
        self,
        client: FrankfurterClient,
        cache: TtlCache,
        recent_rate_ttl_seconds: float,
        today: Callable[[], date],
    ) -> None:
        self._client = client
        self._cache = cache
        self._recent_rate_ttl_seconds = recent_rate_ttl_seconds
        self._today = today

    async def convert(self, request: ConvertRequest) -> dict[str, Any]:
        published = await self._published_rate(request)
        _check_rate_date(published.rate_date, request.asked_date)
        result = (request.amount * published.rate).quantize(CENT, rounding=ROUND_HALF_UP)
        return {
            "amount": _json_number(request.amount),
            "from": request.from_currency,
            "to": request.to_currency,
            "rate": _json_number(published.rate),
            "result": _json_number(result),
            "rate_date": published.rate_date.isoformat(),
            "asked_date": request.asked_date.isoformat() if request.asked_date else None,
            "source": SOURCE,
            "note": _note(published.rate_date, request.asked_date),
        }

    async def _published_rate(self, request: ConvertRequest) -> PublishedRate:
        key = ("rate", request.from_currency, request.to_currency, request.asked_date)
        try:
            return await self._cache.get_or_fetch(
                key,
                lambda: self._client.get_rate(request.from_currency, request.to_currency, request.asked_date),
                self._rate_ttl(request.asked_date),
            )
        except RateNotFound:
            raise await self._explain_missing_rate(request)

    async def _explain_missing_rate(self, request: ConvertRequest) -> ApiError:
        # The upstream says "not found" both for unknown codes and for known codes
        # without a rate on that date; its currency list tells the two apart.
        try:
            known = await self._cache.get_or_fetch("currencies", self._client.get_currencies, CURRENCIES_TTL_SECONDS)
        except ApiError:
            return _rate_not_available(request, codes_unverified=True)
        unknown = [code for code in (request.from_currency, request.to_currency) if code not in known]
        if unknown:
            return ApiError(
                404, "unknown_currency",
                f"The ECB does not currently publish rates for {' or '.join(unknown)}; check the currency code.",
            )
        return _rate_not_available(request)

    def _rate_ttl(self, asked_date: date | None) -> float | None:
        # The ECB publishes around 16:00 CET, so "latest", today and yesterday can
        # still change; anything older is final and can be kept for good.
        if asked_date is not None and asked_date <= self._today() - timedelta(days=2):
            return None
        return self._recent_rate_ttl_seconds


def _json_number(value: Decimal) -> int | float:
    # FastAPI would serialise Decimal as a string; the contract says numbers.
    return int(value) if value == value.to_integral_value() else float(value)


def _check_rate_date(rate_date: date, asked_date: date | None) -> None:
    if asked_date is None:
        return
    if rate_date > asked_date:
        raise ApiError(
            502, "upstream_bad_response",
            f"The rate provider returned a rate from {rate_date} for {asked_date}, a later day; no rate was returned.",
        )
    if (asked_date - rate_date).days > MAX_FALLBACK_DAYS:
        raise ApiError(
            404, "rate_not_available",
            f"The most recent ECB rate before {asked_date} is from {rate_date}, "
            f"more than {MAX_FALLBACK_DAYS} days earlier; no rate was returned.",
        )


def _note(rate_date: date, asked_date: date | None) -> str | None:
    if asked_date is None:
        return f"No date was asked; this is the latest published ECB rate, from {rate_date}."
    if rate_date != asked_date:
        return f"The ECB published no rate for {asked_date}; this is the most recent earlier rate, from {rate_date}."
    return None


def _rate_not_available(request: ConvertRequest, codes_unverified: bool = False) -> ApiError:
    when = f"on or shortly before {request.asked_date}" if request.asked_date else "at the moment"
    message = f"The ECB has no {request.from_currency} to {request.to_currency} rate {when}; no rate was returned."
    if codes_unverified:
        message += " One of the currency codes may not be supported."
    return ApiError(404, "rate_not_available", message)
