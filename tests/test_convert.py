from datetime import datetime, timedelta, timezone

import pytest

CONVERT = "/tools/convert"


def convert(client, amount, from_, to, date=None):
    params = {"amount": amount, "from": from_, "to": to}
    if date:
        params["date"] = date
    return client.get(CONVERT, params=params)


def assert_error(response, status, code):
    assert response.status_code == status
    assert response.json().keys() == {"error", "message"}
    assert response.json()["error"] == code


def test_converts_with_the_rate_of_the_asked_date(client, upstream):
    upstream.rate("2026-08-28", rate=47.1234)

    response = convert(client, "250", "EUR", "TRY", "2026-08-28")

    assert response.status_code == 200
    assert response.json() == {
        "amount": 250,
        "from": "EUR",
        "to": "TRY",
        "rate": 47.1234,
        "result": 11780.85,
        "rate_date": "2026-08-28",
        "asked_date": "2026-08-28",
        "source": "ECB via frankfurter.dev",
        "note": None,
    }
    assert dict(upstream.requests[0].url.params) == {"base": "EUR", "symbols": "TRY"}


def test_day_without_rate_uses_earlier_rate_and_says_so(client, upstream):
    upstream.rate("2026-08-29", published="2026-08-28")

    body = convert(client, "250", "EUR", "TRY", "2026-08-29").json()

    assert body["rate_date"] == "2026-08-28"
    assert body["asked_date"] == "2026-08-29"
    assert "2026-08-29" in body["note"] and "2026-08-28" in body["note"]


def test_no_date_uses_latest_and_names_its_date(client, upstream):
    upstream.rate("latest", published="2026-09-22")

    body = convert(client, "10", "EUR", "TRY").json()

    assert upstream.paths() == ["/v1/latest"]
    assert body["asked_date"] is None
    assert body["rate_date"] == "2026-09-22"
    assert "2026-09-22" in body["note"]


def test_rate_older_than_a_week_is_refused(client, upstream):
    upstream.rate("2026-08-28", published="2026-08-20")

    response = convert(client, "1", "EUR", "TRY", "2026-08-28")

    assert_error(response, 404, "rate_not_available")


def test_rate_dated_after_the_asked_day_is_refused(client, upstream):
    upstream.rate("2026-08-28", published="2026-08-31")

    response = convert(client, "1", "EUR", "TRY", "2026-08-28")

    assert_error(response, 502, "upstream_bad_response")


def test_currency_codes_are_case_insensitive(client, upstream):
    upstream.rate("2026-08-28")

    body = convert(client, "1", "eur", "try", "2026-08-28").json()

    assert (body["from"], body["to"]) == ("EUR", "TRY")
    assert dict(upstream.requests[0].url.params) == {"base": "EUR", "symbols": "TRY"}


def test_small_rates_are_not_rounded(client, upstream):
    upstream.rate("2026-08-28", rate=0.00538, base="JPY", target="EUR")

    body = convert(client, "1000", "JPY", "EUR", "2026-08-28").json()

    assert body["rate"] == 0.00538
    assert body["result"] == 5.38


def test_many_decimals_are_computed_exactly(client, upstream):
    upstream.rate("2026-08-28", rate=47.1234)

    body = convert(client, "0.1234567890", "EUR", "TRY", "2026-08-28").json()

    assert body["amount"] == 0.123456789
    assert body["result"] == 5.82


def test_result_rounds_half_up(client, upstream):
    upstream.rate("2026-08-28", rate=0.125)

    body = convert(client, "1", "EUR", "TRY", "2026-08-28").json()

    assert body["result"] == 0.13


def test_unknown_currency(client, upstream):
    response = convert(client, "1", "EUR", "XYZ", "2026-08-28")

    assert_error(response, 404, "unknown_currency")
    assert "XYZ" in response.json()["message"]


def test_known_currency_without_rate_for_the_date(client, upstream):
    response = convert(client, "1", "EUR", "USD", "2026-08-28")

    assert_error(response, 404, "rate_not_available")


def test_missing_rate_when_currency_list_is_unavailable(client, upstream):
    upstream.on("/v1/currencies", status=500, json={})

    response = convert(client, "1", "EUR", "XYZ", "2026-08-28")

    assert_error(response, 404, "rate_not_available")
    assert "may not be supported" in response.json()["message"]


def utc_today():
    return datetime.now(timezone.utc).date()


VALID = {"amount": "250", "from": "EUR", "to": "TRY", "date": "2026-08-28"}


@pytest.mark.parametrize("override, code", [
    ({"amount": None}, "missing_parameter"),
    ({"from": None}, "missing_parameter"),
    ({"to": None}, "missing_parameter"),
    ({"amount": "0"}, "invalid_amount"),
    ({"amount": "-5"}, "invalid_amount"),
    ({"amount": "abc"}, "invalid_amount"),
    ({"amount": "nan"}, "invalid_amount"),
    ({"amount": "inf"}, "invalid_amount"),
    ({"amount": "1e3"}, "invalid_amount"),
    ({"amount": "10000000000000"}, "invalid_amount"),
    ({"to": "LIRA"}, "invalid_currency"),
    ({"to": "T1Y"}, "invalid_currency"),
    ({"to": "eur"}, "same_currency"),
    ({"date": "2026-02-30"}, "invalid_date"),
    ({"date": "28.08.2026"}, "invalid_date"),
    ({"date": str(utc_today() + timedelta(days=1))}, "date_in_future"),
    ({"date": "1999-01-03"}, "date_before_series"),
])
def test_bad_input_is_rejected_without_asking_upstream(client, upstream, override, code):
    params = {key: value for key, value in {**VALID, **override}.items() if value is not None}

    response = client.get(CONVERT, params=params)

    assert_error(response, 400, code)
    assert upstream.requests == []


def test_unknown_route_uses_the_error_shape(client):
    assert_error(client.get("/nope"), 404, "not_found")
