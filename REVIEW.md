# Review of tool.py

I ran `tool.py` under uvicorn against the real API and checked each finding
below. For the failure cases I replaced `tool.client` with one that talks to a
fake upstream (`httpx.MockTransport`), so I could make the upstream go down or
return HTML. Most harmful to a customer first.

## 1. Rates are returned for dates they don't belong to

The cache key is `f"{base}-{target}"`, so it has no date in it and never
expires. On top of that, `rate_date` is just `str(on or date.today())`, so it
repeats whatever the caller asked for instead of reading the `date` field the
upstream sends back. And when the target currency is missing, the code quietly
switches to `/latest`.

For the customer this means the first EUR to TRY rate the service fetches is
used for every EUR to TRY question after that, whatever the date, and it is
labelled with the date they asked for. The number looks normal, so neither the
model nor the customer has any reason to doubt it.

How I checked: I asked for `on=2026-08-28` and then `on=2030-01-01`. Both came
back with 56.17, and the second one said `"rate_date": "2030-01-01"`. A
Saturday (`on=2026-08-29`) is labelled as Saturday, although the upstream says
the rate is from Friday.

## 2. The documented parameters are ignored

The handler's parameters are called `from_` and `on`, so a request with
`?from=USD&date=2026-08-28` has both of them ignored and falls back to EUR and
the latest rate. If a customer asks "how much is 250 USD in TRY on 28 August?",
they get an answer for 250 EUR, at the cached rate, labelled with today's date.

How I checked:
`curl '…/tools/convert?amount=250&from=USD&to=TRY&date=2026-08-28'` returned
`"from":"EUR"` and `"rate_date":"2026-09-23"`.

## 3. Every failure is returned as 200 with a rate of 0

`except Exception` catches everything and returns 200 with `rate: 0.0` and
`result: 0.0`. So the customer can be told that 250 EUR is 0 TRY. This happens
when the upstream is down or returns HTML, when the currency code is unknown,
when `from` and `to` are the same (the upstream answers 422), and even when the
code is just lowercase: `to=try` looks up `rates["try"]` and raises a KeyError.
The model gets no sign that anything failed.

How I checked: `to=try`, `to=XYZ` and `to=EUR` all returned 200 with zeros, and
so did the fake upstream when it raised `ConnectError` or returned `<html>`.

## 4. The rate is rounded to 2 decimals before multiplying

For small rates this is a big error. JPY to EUR is 0.00538, which becomes 0.01,
so 10,000 JPY is quoted as 100 EUR instead of 53.80, almost double. Even for
EUR to TRY the customer is misinformed: 250 × 56.17 = 14042.50 instead of
14042.95.

How I checked: I asked for `from_=JPY&to=EUR&on=2026-08-28` and compared the
result with the upstream's `0.00538`.

## 5. No input checks, and the upstream host is hardcoded

Negative amounts are converted (−100 EUR comes back as a negative TRY amount),
and `amount=nan` returns `null` values with 200. A missing amount gets
FastAPI's default 422 `{"detail": …}` instead of an error in the service's own
format. `UPSTREAM` is hardcoded, so the service can't be pointed at a test
double. I put these last because they only happen with unusual input.

## The one I would fix before shipping tonight

#1. In `fetch_rate` I would put the date in the cache key, return the
upstream's `payload["date"]` as `rate_date`, and remove the `/latest` fallback.
It's the only problem that gives wrong numbers that look correct on normal
requests, and the fix is a few lines in one function. I would do #3 right after
it. A zero at least looks wrong to someone reading it, while a wrong rate that
looks normal will just be passed on to the customer.

## Things that look suspicious but are fine

- **`httpx.AsyncClient()` without a timeout:** httpx has a 5 second default
  (`tool.client.timeout` is `Timeout(timeout=5.0)`), so a slow upstream can't
  hang a request forever.
- **One module-level client shared by all requests:** this is how httpx
  recommends using it, since it reuses connections.
- **A plain dict cache with no lock:** the event loop runs on one thread. Two
  requests can both miss the cache and both fetch, but that only means an
  extra upstream call, the dict itself stays fine. What's wrong with this
  cache is the key (#1).
- **`from __future__ import annotations` with FastAPI:** FastAPI resolves the
  string annotations, and `on` is parsed as a date correctly.
- **The comment "the ECB publishes nothing on weekends":** Frankfurter already
  returns Friday's rate for a Saturday, so weekends never reach the fallback.
  The comment is misleading, but the actual bugs in that fallback are #1 and #3.
