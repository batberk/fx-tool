import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.errors import ApiError

SERIES_START = date(1999, 1, 4)
MAX_AMOUNT = Decimal("1000000000000")

_PLAIN_NUMBER = re.compile(r"[+-]?\d+(\.\d+)?")
_CURRENCY_CODE = re.compile(r"[A-Za-z]{3}")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class ConvertRequest:
    amount: Decimal
    from_currency: str
    to_currency: str
    asked_date: date | None


def parse_convert_request(
    amount: str | None,
    from_currency: str | None,
    to_currency: str | None,
    asked_date: str | None,
    today: date,
) -> ConvertRequest:
    _require({"amount": amount, "from": from_currency, "to": to_currency})
    request = ConvertRequest(
        amount=parse_amount(amount),
        from_currency=parse_currency(from_currency),
        to_currency=parse_currency(to_currency),
        asked_date=parse_date(asked_date, today),
    )
    if request.from_currency == request.to_currency:
        raise ApiError(
            400, "same_currency",
            f"from and to are both {request.from_currency}; there is nothing to convert.",
        )
    return request


def parse_amount(raw: str) -> Decimal:
    text = raw.strip()
    if not _PLAIN_NUMBER.fullmatch(text):
        raise ApiError(400, "invalid_amount", f"amount '{raw}' is not a plain number like 250 or 99.95.")
    amount = Decimal(text)
    if amount <= 0:
        raise ApiError(400, "invalid_amount", "amount must be greater than zero.")
    if amount > MAX_AMOUNT:
        raise ApiError(400, "invalid_amount", "amount is too large; the maximum is 1,000,000,000,000.")
    return amount


def parse_currency(raw: str) -> str:
    code = raw.strip()
    if not _CURRENCY_CODE.fullmatch(code):
        raise ApiError(400, "invalid_currency", f"'{raw}' is not a currency code; use a three-letter code like EUR.")
    return code.upper()


def parse_date(raw: str | None, today: date) -> date | None:
    if raw is None or not raw.strip():
        return None
    asked = _to_date(raw.strip())
    if asked is None:
        raise ApiError(400, "invalid_date", f"date '{raw}' is not a real calendar date in YYYY-MM-DD format.")
    if asked > today:
        raise ApiError(400, "date_in_future", f"{asked} is in the future; ECB rates exist only up to today ({today}, UTC).")
    if asked < SERIES_START:
        raise ApiError(400, "date_before_series", f"ECB rates start on {SERIES_START}; there is no rate for {asked}.")
    return asked


def _to_date(text: str) -> date | None:
    if not _ISO_DATE.fullmatch(text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _require(params: dict[str, str | None]) -> None:
    missing = [name for name, value in params.items() if value is None or not value.strip()]
    if missing:
        raise ApiError(400, "missing_parameter", f"Missing required parameter(s): {', '.join(missing)}.")
