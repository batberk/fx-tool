import socket

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.helpers import assert_error

PARAMS = {"amount": "250", "from": "EUR", "to": "TRY", "date": "2026-08-28"}
GOOD = {"amount": 1.0, "base": "EUR", "date": "2026-08-28", "rates": {"TRY": 47.1234}}


@pytest.mark.parametrize("reply, status, code", [
    ({"error": httpx.ReadTimeout("slow")}, 504, "upstream_timeout"),
    ({"json": GOOD, "delay": 1.0}, 504, "upstream_timeout"),
    ({"error": httpx.ConnectError("refused")}, 503, "upstream_unavailable"),
    ({"status": 500, "json": {}}, 502, "upstream_error"),
    ({"status": 503, "text": "maintenance"}, 502, "upstream_error"),
    ({"text": "<html>hello</html>"}, 502, "upstream_bad_response"),
    ({"json": [1, 2, 3]}, 502, "upstream_bad_response"),
    ({"json": {**GOOD, "rates": None}}, 502, "upstream_bad_response"),
    ({"json": {**GOOD, "rates": {"TRY": "47.1"}}}, 502, "upstream_bad_response"),
    ({"json": {**GOOD, "rates": {"TRY": 0}}}, 502, "upstream_bad_response"),
    ({"json": {**GOOD, "rates": {"TRY": -47.1}}}, 502, "upstream_bad_response"),
    ({"json": {**GOOD, "base": "USD"}}, 502, "upstream_bad_response"),
    ({"json": {**GOOD, "date": None}}, 502, "upstream_bad_response"),
    ({"json": {**GOOD, "date": "yesterday"}}, 502, "upstream_bad_response"),
])
def test_upstream_failures_never_produce_a_rate(client, upstream, reply, status, code):
    upstream.on("/v1/2026-08-28", **reply)

    response = client.get("/tools/convert", params=PARAMS)

    assert_error(response, status, code)


def test_nan_rate_is_rejected(client, upstream):
    upstream.on("/v1/2026-08-28", text='{"base": "EUR", "date": "2026-08-28", "rates": {"TRY": NaN}}')

    response = client.get("/tools/convert", params=PARAMS)

    assert_error(response, 502, "upstream_bad_response")


def test_closed_port_from_environment_is_reported_as_unavailable(monkeypatch):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
    monkeypatch.setenv("FX_UPSTREAM_BASE", f"http://127.0.0.1:{closed_port}")

    client = TestClient(create_app(Settings.from_env()))
    response = client.get("/tools/convert", params=PARAMS)

    assert_error(response, 503, "upstream_unavailable")
