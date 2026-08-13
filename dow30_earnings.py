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
    ]
    for ev in sorted(events, key=lambda e: e["date"]):
        d = dt.date.fromisoformat(ev["date"])
        dtend = d + dt.timedelta(days=1)
        timing = TIMING_LABEL.get(ev["hour"], "TBD")
        summary = f"{ev['symbol']} earnings ({timing})"

        desc_bits = [f"Fiscal {ev['year']} Q{ev['quarter']}."]
        if ev["eps_act"] is not None:
            desc_bits.append(f"Reported EPS: {ev['eps_act']}.")
        elif ev["eps_est"] is not None:
            desc_bits.append(f"Estimated EPS: {ev['eps_est']}.")
        desc_bits.append("Forward dates are estimates and may shift until confirmed.")
        description = " ".join(desc_bits)

        lines += [
            "BEGIN:VEVENT",
            fold(f"UID:{ev['uid']}"),
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{dtend.strftime('%Y%m%d')}",
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
