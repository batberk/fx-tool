# Notes

## Decisions

- **No ECB rate on the asked date:**  I chose to answer with the most recent earlier rate
  and make that difference visible. Frankfurter already does the fallback and
  reports the date it used, so `rate_date` always comes from the upstream's
  `date` field and never from the request. When it differs from `asked_date`,
  a `note` sentence says so, and the model can repeat it to the customer. I
  chose this over refusing because "the rate on Saturday" almost always means
  "the rate in force on Saturday", which is Friday's. A response with a note gives the model something to work with, and a refusal could cause the model to guess on its own.

- **Limits on that fallback:** a gap of more than 7 days is refused, and a rate dated after the asked day is treated as a broken upstream.

- **No date given:** use the latest rate. `asked_date` is `null`, and the
  `note` still names the day.

- **Validate before calling out:** Frankfurter answers "not found" for future
  dates, dates before 1999, and unknown codes alike. So dates and code formats
  are checked locally, and the currency list is only fetched after a 404.
  That keeps the normal path to one upstream call.

- **Numbers:** everything is `Decimal`, from the upstream JSON through to the
  result. The rate is passed through unrounded, and the result is rounded to 2 decimal places. Any number of decimals is accepted in `amount`, but only if they are in
  plain notation (scientific notation or any other format is rejected rather than guessed at).

- **Failures:** every upstream failure is a non-2xx error with a code. The
  service never returns 200 with a zero.

- **Cache:** the key includes the date. Dates that are two or more days in the past are final
  and kept for good; `latest`, today and yesterday are kept for 15 minutes.
  Errors are never cached.

## With another day

- One retry with backoff on connection errors and 5xx answers, inside the
  timeout budget.
- Round `result` to each currency's minor unit (JPY 0, most others 2) instead
  of 2 places everywhere.
- Time zones: a caller ahead of UTC asking for "today" currently gets
  `date_in_future`.


## AI tools

Claude Code. I used it to:
- read the brief and `tool.py`
- probe the live Frankfurter API with curl for the edge cases (weekend, future
  date, pre-1999, unknown code, same pair)
- draft a plan, then implement it one commit at a time

I made the policy decisions (flagged earlier-rate fallback, latest when no date
is given, how amounts are handled), reviewed each step before committing, and
handled the commits.

## One thing the AI got wrong

The first version of the endpoint returned `Decimal` values as they were,
assuming FastAPI would write them as JSON numbers. Running the service against
the real API showed `"rate": "56.1718"`, a string. That breaks the response
contract and any client that does arithmetic on the value. The fix converts
values at the response boundary (`_json_number` in `app/service.py`).
