# fx-tool

A small HTTP service with one endpoint an AI agent can call as a tool to convert
money using European Central Bank rates (via [Frankfurter](https://frankfurter.dev)).
It would rather return no number than a wrong one. The original brief is in
[BRIEF.md](BRIEF.md).

## Run

```sh
./run.sh                                   # http://localhost:8080
PORT=9000 FX_UPSTREAM_BASE=http://localhost:4000 ./run.sh
```

Needs Python 3.10+. The first run creates `.venv` and installs dependencies
(this needs network access). Later runs start offline.

| Variable | Default |
|---|---|
| `PORT` | `8080` |
| `FX_UPSTREAM_BASE` | `https://api.frankfurter.dev` (the service calls `$FX_UPSTREAM_BASE/v1/...`) |

## Test

```sh
./test.sh
```

The upstream is faked in-process, so the tests never touch the network and pass
with `FX_UPSTREAM_BASE` pointing anywhere, including a closed port.

## Use

```sh
curl 'localhost:8080/tools/convert?amount=250&from=EUR&to=TRY&date=2026-08-29'
```

```json
{
  "amount": 250,
  "from": "EUR",
  "to": "TRY",
  "rate": 56.1718,
  "result": 14042.95,
  "rate_date": "2026-08-28",
  "asked_date": "2026-08-29",
  "source": "ECB via frankfurter.dev",
  "note": "The ECB published no rate for 2026-08-29; this is the most recent earlier rate, from 2026-08-28."
}
```

- `rate_date` is the day the rate belongs to, as reported by the upstream. It
  is never taken from the request.
- `asked_date` is the date the caller asked for, or `null` if none was given.
- `note` is `null` when the two dates match. Otherwise it is a sentence the
  agent can pass on to the customer.
- `rate` is exactly the upstream's rate. `result` is `amount × rate`, computed
  with decimals (not floats) and rounded half-up to 2 places.

Parameters: `amount`, `from` and `to` are required. `date` (`YYYY-MM-DD`) is
optional; without it the latest published rate is used. Currency codes are
case-insensitive.

## Error codes

Every error is a non-2xx status with `{"error": "<code>", "message": "<sentence>"}`.

| Status | `error` | When |
|---|---|---|
| 400 | `missing_parameter` | `amount`, `from` or `to` is missing |
| 400 | `invalid_amount` | not a plain number, zero, negative, or above 1,000,000,000,000 |
| 400 | `invalid_currency` | not a three-letter code |
| 400 | `same_currency` | `from` and `to` are the same |
| 400 | `invalid_date` | not a real `YYYY-MM-DD` date |
| 400 | `date_in_future` | after today (UTC) |
| 400 | `date_before_series` | before 1999-01-04, when the ECB series starts |
| 404 | `unknown_currency` | the ECB does not currently publish that code |
| 404 | `rate_not_available` | the codes exist, but there is no rate within 7 days before the date |
| 502 | `upstream_error` | the upstream answered with a non-200 status |
| 502 | `upstream_bad_response` | the upstream answer is not JSON, is missing fields, has a non-positive rate, the wrong base, or a date after the asked one |
| 503 | `upstream_unavailable` | the upstream cannot be reached |
| 504 | `upstream_timeout` | the upstream took longer than 5 seconds |
| 404 / 405 | `not_found` / `method_not_allowed` | wrong path or method |
| 500 | `internal_error` | a bug on our side; no rate is returned |

## What happens when…

| Case | Behaviour |
|---|---|
| No ECB rate on the asked date (weekend, holiday, today before ~16:00 CET) | 200 with the most recent earlier rate. `rate_date` is set to that day, and `note` says so. If the nearest earlier rate is more than 7 days back, it is refused with `rate_not_available`. |
| Date in the future | `400 date_in_future`, without calling the upstream |
| Date before 1999-01-04 | `400 date_before_series`, without calling the upstream |
| Unknown currency code | `404 unknown_currency`, checked against the upstream's currency list. Currencies the ECB has dropped (e.g. RUB) show up here too. |
| `from` equals `to` | `400 same_currency` |
| Upstream slow | `504 upstream_timeout` after 5 seconds |
| Upstream returns 500 | `502 upstream_error` |
| Upstream returns something that is not JSON, or JSON of the wrong shape | `502 upstream_bad_response` |
| `amount` missing | `400 missing_parameter` |
| `amount` zero or negative | `400 invalid_amount` |
| `amount` with ten decimal places | Accepted and computed exactly. `result` is rounded to 2 places, so a very small amount can come back as `0.00`. |

In none of these cases does the service return a rate it did not get from the
upstream for that pair, and it never labels a rate with a date the rate does
not belong to.

## Caching

Successful upstream answers are kept in memory, so repeating a question does
not ask the upstream again. Rates for dates two or more days back are final and
kept until evicted (10,000 entries at most). `latest`, today and yesterday are
kept for 15 minutes, since the ECB may still publish or correct them. Errors
are never cached, and identical concurrent requests share one upstream call.

## Layout

```
app/main.py        routes and app factory
app/validation.py  request parsing and input rules
app/service.py     conversion policy: date fallback, rounding, error wording
app/upstream.py    Frankfurter client and strict response checks
app/cache.py       in-memory TTL cache with shared in-flight fetches
app/errors.py      the {error, message} contract
tests/             offline tests against a fake upstream
tool.py            the service reviewed in REVIEW.md (not used by the app)
```
