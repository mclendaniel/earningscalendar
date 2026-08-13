#!/usr/bin/env python3
"""
Build a self-updating ICS feed of earnings dates for the 30 DJIA companies.

Data source: Finnhub earnings-calendar endpoint
    GET https://finnhub.io/api/v1/calendar/earnings?from=&to=&symbol=&token=

Requires the FINNHUB_API_KEY environment variable.
Writes ./earnings.ics (all-day events, one per company per fiscal quarter).
"""

import os
import sys
import time
import datetime as dt
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
import json

# --- Configuration ---------------------------------------------------------

# Current DJIA 30 constituents (verified Aug 2026: GOOGL replaced VZ on
# 2026-06-29; NVDA/SHW replaced INTC/DOW on 2024-11-08; AMZN replaced WBA
# on 2024-02-26). Review this list each quarter — the committee swaps members
# every couple of years and the feed silently goes stale if a ticker is dead.
# NOTE: Honeywell trades as HON but was renamed "Honeywell Technologies" after
# spinning off its aerospace unit in 2026 — confirm the ticker still resolves.
TICKERS = [
    "AAPL", "AMGN", "AMZN", "AXP", "BA", "CAT", "CRM", "CSCO", "CVX", "DIS",
    "GOOGL", "GS", "HD", "HON", "IBM", "JNJ", "JPM", "KO", "MCD", "MMM",
    "MRK", "MSFT", "NKE", "NVDA", "PG", "SHW", "TRV", "UNH", "V", "WMT",
]

# How far back / forward to pull. Past window keeps just-reported dates visible;
# forward window captures the next (usually estimated) quarter.
LOOKBACK_DAYS = 30
LOOKAHEAD_DAYS = 210

CAL_NAME = "DJIA 30 Earnings"
CAL_DESC = "Earnings dates for the 30 Dow Jones Industrial Average companies. Forward dates are estimates and shift until a company confirms."
OUTPUT_FILE = "earnings.ics"

API_URL = "https://finnhub.io/api/v1/calendar/earnings"
REQUEST_PAUSE = 0.4      # seconds between calls (free tier = 60/min)
MAX_RETRIES = 4

TIMING_LABEL = {"bmo": "BMO", "amc": "AMC", "dmh": "DMH", "": "TBD"}

# Map each session to a WINDOW of local Eastern time, not a point. A wide block
# puts the event in the right half of the day (morning vs. after-close) while its
# width signals that the exact release minute is unknown. Unknown -> all-day.
# Format: (start_hour, start_min), (end_hour, end_min).
SESSION_WINDOW = {
    "bmo": ((7, 0), (9, 30)),    # pre-market, up to the 9:30 open
    "amc": ((16, 0), (18, 0)),   # after the 4:00 close (release + typical call)
    "dmh": ((11, 0), (13, 0)),   # midday (rare)
}
TZID = "America/New_York"

# Self-contained VTIMEZONE so timed events render in correct local time for any
# subscriber regardless of their own zone. Current US DST rules: 2nd Sun Mar to
# 1st Sun Nov.
VTIMEZONE = "\r\n".join([
    "BEGIN:VTIMEZONE",
    f"TZID:{TZID}",
    "BEGIN:DAYLIGHT",
    "TZOFFSETFROM:-0500",
    "TZOFFSETTO:-0400",
    "TZNAME:EDT",
    "DTSTART:19700308T020000",
    "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU",
    "END:DAYLIGHT",
    "BEGIN:STANDARD",
    "TZOFFSETFROM:-0400",
    "TZOFFSETTO:-0500",
    "TZNAME:EST",
    "DTSTART:19701101T020000",
    "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU",
    "END:STANDARD",
    "END:VTIMEZONE",
])


# --- Finnhub fetch ---------------------------------------------------------

def fetch_symbol(symbol, date_from, date_to, token):
    """Return the list of earnings rows for one symbol, or [] on failure."""
    qs = urlencode({"from": date_from, "to": date_to, "symbol": symbol, "token": token})
    url = f"{API_URL}?{qs}"
    for attempt in range(MAX_RETRIES):
        try:
            req = Request(url, headers={"User-Agent": "dow30-earnings-ics/1.0"})
            with urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            return payload.get("earningsCalendar", []) or []
        except HTTPError as e:
            if e.code == 429:               # rate limited — back off and retry
                wait = 2 ** attempt
                print(f"  429 for {symbol}, backing off {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"  HTTP {e.code} for {symbol}: {e.reason}", file=sys.stderr)
            return []
        except (URLError, json.JSONDecodeError) as e:
            print(f"  error for {symbol}: {e}", file=sys.stderr)
            time.sleep(1)
    print(f"  gave up on {symbol} after {MAX_RETRIES} tries", file=sys.stderr)
    return []


def collect_events(token):
    today = dt.date.today()
    date_from = (today - dt.timedelta(days=LOOKBACK_DAYS)).isoformat()
    date_to = (today + dt.timedelta(days=LOOKAHEAD_DAYS)).isoformat()

    events = {}   # uid -> event dict, dedupes repeated rows
    for sym in TICKERS:
        rows = fetch_symbol(sym, date_from, date_to, token)
        for row in rows:
            date_str = row.get("date")
            if not date_str:
                continue
            year = row.get("year")
            quarter = row.get("quarter")
            uid = f"{sym}-{year}Q{quarter}@dow30-earnings"
            events[uid] = {
                "uid": uid,
                "symbol": sym,
                "date": date_str,
                "year": year,
                "quarter": quarter,
                "hour": (row.get("hour") or "").lower(),
                "eps_est": row.get("epsEstimate"),
                "eps_act": row.get("epsActual"),
            }
        print(f"{sym}: {len(rows)} row(s)")
        time.sleep(REQUEST_PAUSE)
    return list(events.values())


# --- ICS generation --------------------------------------------------------

def fold(line):
    """RFC 5545 line folding at 75 octets."""
    out, cur = [], line
    while len(cur.encode("utf-8")) > 75:
        # step back until the 75-byte prefix is valid utf-8
        cut = 75
        while len(cur[:cut].encode("utf-8")) > 75:
            cut -= 1
        out.append(cur[:cut])
        cur = " " + cur[cut:]
    out.append(cur)
    return "\r\n".join(out)


def esc(text):
    return (str(text).replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\n", "\\n"))


def build_ics(events):
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//dow30-earnings-calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{esc(CAL_NAME)}",
        f"X-WR-CALDESC:{esc(CAL_DESC)}",
        "X-PUBLISHED-TTL:PT12H",
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
        VTIMEZONE,
    ]
    for ev in sorted(events, key=lambda e: e["date"]):
        d = dt.date.fromisoformat(ev["date"])
        day = d.strftime("%Y%m%d")
        timing = TIMING_LABEL.get(ev["hour"], "TBD")
        summary = f"{ev['symbol']} earnings ({timing})"
        window = SESSION_WINDOW.get(ev["hour"])

        if window:
            (sh, sm), (eh, em) = window
            dt_lines = [
                f"DTSTART;TZID={TZID}:{day}T{sh:02d}{sm:02d}00",
                f"DTEND;TZID={TZID}:{day}T{eh:02d}{em:02d}00",
            ]
        else:   # unknown session -> honest all-day event
            dtend = d + dt.timedelta(days=1)
            dt_lines = [
                f"DTSTART;VALUE=DATE:{day}",
                f"DTEND;VALUE=DATE:{dtend.strftime('%Y%m%d')}",
            ]

        desc_bits = [f"Fiscal {ev['year']} Q{ev['quarter']}."]
        if ev["eps_act"] is not None:
            desc_bits.append(f"Reported EPS: {ev['eps_act']}.")
        elif ev["eps_est"] is not None:
            desc_bits.append(f"Estimated EPS: {ev['eps_est']}.")
        if window:
            desc_bits.append("Time block is an approximate session window (US Eastern), "
                             "not a confirmed release time.")
        desc_bits.append("Forward dates are estimates and may shift until confirmed.")
        description = " ".join(desc_bits)

        lines += [
            "BEGIN:VEVENT",
            fold(f"UID:{ev['uid']}"),
            f"DTSTAMP:{stamp}",
            *dt_lines,
            "TRANSP:TRANSPARENT",
            fold(f"SUMMARY:{esc(summary)}"),
            fold(f"DESCRIPTION:{esc(description)}"),
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


# --- Main ------------------------------------------------------------------

def main():
    token = os.environ.get("FINNHUB_API_KEY")
    if not token:
        sys.exit("FINNHUB_API_KEY environment variable is not set.")

    print(f"Fetching earnings for {len(TICKERS)} DJIA tickers...")
    events = collect_events(token)
    if not events:
        sys.exit("No events returned — check the API key, rate limits, or tickers.")

    ics = build_ics(events)
    with open(OUTPUT_FILE, "w", newline="") as f:
        f.write(ics)
    print(f"Wrote {len(events)} events to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
