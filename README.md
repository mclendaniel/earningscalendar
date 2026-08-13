# DJIA 30 Earnings Calendar

A self-updating iCalendar (`.ics`) feed of earnings dates for the 30 companies
in the Dow Jones Industrial Average. A GitHub Actions job runs daily, pulls
upcoming earnings dates from Finnhub, regenerates `earnings.ics`, and commits it.
Subscribe any calendar app to the file's URL and it stays current.

## How it works

```
GitHub Actions (daily cron) --> dow30_earnings.py --> Finnhub API
                                        |
                                        v
                                  earnings.ics  <-- committed to the repo
                                        |
                                        v
              your calendar app subscribes to the raw file URL
```

Nothing runs on your machine. The only moving part you maintain is a free
Finnhub API key stored as a repository secret.

## Setup

1. **Create the repo.** Put these files in a new GitHub repository
   (public is simplest, so the raw `.ics` URL needs no auth).

2. **Get a Finnhub key.** Register at https://finnhub.io and copy the API key
   from the dashboard. The free tier covers this use (US companies, 60 calls/min;
   this script makes 30 calls per run).

3. **Store the key as a secret.** In the repo: *Settings -> Secrets and
   variables -> Actions -> New repository secret*. Name it exactly
   `FINNHUB_API_KEY`.

4. **Run it once.** Go to the *Actions* tab, pick *Update DJIA earnings
   calendar*, and click *Run workflow*. After it finishes, `earnings.ics`
   appears in the repo.

5. **Subscribe.** Use the raw file URL:
   ```
   https://raw.githubusercontent.com/<you>/<repo>/main/earnings.ics
   ```
   - **Google Calendar:** *Other calendars -> + -> From URL* -> paste the URL.
   - **Apple Calendar:** *File -> New Calendar Subscription* -> paste the URL
     (lets you set the refresh interval yourself).
   - **Outlook:** *Add calendar -> Subscribe from web* -> paste the URL.

   To share it, share the same URL, or share the resulting Google/Apple calendar
   with other people.

## Things worth knowing

- **Refresh latency is the calendar app's, not yours.** Google re-polls
  subscribed URLs on its own schedule (often many hours, sometimes ~a day) and
  gives you no control. Apple Calendar lets you set the interval. The daily cron
  keeps the *file* fresh; how fast your app notices is up to the app.

- **Forward dates are estimates.** A company only confirms its date (via an 8-K)
  a couple of weeks out, so future entries shift. Stable per-quarter UIDs mean a
  shifted date updates the existing event in place rather than duplicating it.

- **The Dow's membership drifts.** The `TICKERS` list in `dow30_earnings.py` is
  current as of August 2026 (Alphabet/GOOGL replaced Verizon on 2026-06-29).
  The committee swaps members every couple of years — review the list each
  quarter, or the feed silently skips a new member and queries a dead one.

- **Honeywell caveat.** HON was renamed "Honeywell Technologies" after its 2026
  aerospace spin-off. The parent should still resolve under `HON`; confirm on the
  first run that it returns rows.

- **`GOOGL` vs `GOOG`.** The Dow uses Class A (`GOOGL`). The earnings *date* is
  identical for both share classes; swap the ticker if Finnhub returns nothing
  for one.

## Adjusting

- Change how far ahead the feed looks: edit `LOOKAHEAD_DAYS` in the script.
- Change the update cadence: edit the `cron` line in
  `.github/workflows/update-calendar.yml`.
- Add timing to the event *time* instead of the title: the script currently
  makes all-day events with `(BMO)`/`(AMC)` in the title to sidestep timezone
  issues; swap to timed events if you prefer.
