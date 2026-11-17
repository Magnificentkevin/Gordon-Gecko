#!/usr/bin/env python3
"""Gordongecko market regime check.

Reads the public S&P 500 breadth dataset (share of S&P 500 stocks above their
200-day moving average) and turns it into a simple regime label plus a risk
multiplier that scales position size.

Usage:
  python3 gecko_regime.py                 # fetch the public CSV
  python3 gecko_regime.py --csv data.csv  # use a local copy instead
  python3 gecko_regime.py --json          # machine-readable output

Standard library only. Educational tool, not financial advice.
"""
import argparse
import csv
import io
import json
import sys
import urllib.request
from datetime import date, datetime

DEFAULT_URL = "https://tradermonty.github.io/market-breadth-analysis/market_breadth_data.csv"

REGIMES = [
    # (minimum points, label, risk multiplier, guidance)
    (3, "RISK-ON", 1.00, "Broad participation. Normal risk on new longs."),
    (1, "CONSTRUCTIVE", 0.75, "Mostly healthy, some cracks. Trim size, favor leaders."),
    (-1, "CAUTION", 0.50, "Mixed or weakening. Half size, A+ setups only, tight stops."),
    (-99, "DEFENSIVE", 0.00, "Breadth breaking down. No new longs; protect capital."),
]


def fetch_text(url):
    try:
        import requests  # honours proxy/CA settings when installed
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        return resp.text
    except ImportError:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return resp.read().decode("utf-8")


def load_rows(args):
    if args.csv:
        with open(args.csv, newline="", encoding="utf-8") as fh:
            text = fh.read()
    else:
        text = fetch_text(args.url)
    rows = list(csv.DictReader(io.StringIO(text)))
    if len(rows) < 10:
        raise ValueError("Not enough rows in breadth data")
    return rows


def as_float(row, key):
    return float(row[key])


def is_true(value):
    return str(value).strip().lower() in ("true", "1", "yes")


def assess(rows):
    last = rows[-1]
    prior = rows[-6]  # five sessions back
    ma8 = as_float(last, "Breadth_Index_8MA")
    ma200 = as_float(last, "Breadth_Index_200MA")
    ma8_prior = as_float(prior, "Breadth_Index_8MA")
    trend200 = int(float(last.get("Breadth_200MA_Trend", 0) or 0))
    bearish_recent = any(is_true(r.get("Bearish_Signal")) for r in rows[-5:])

    checks = []

    def add(name, ok, detail, weight=1):
        pts = weight if ok else -weight
        checks.append({"check": name, "points": pts, "detail": detail})

    add("8MA above 200MA", ma8 > ma200, f"8MA {ma8:.3f} vs 200MA {ma200:.3f}")
    add("200MA trending up", trend200 > 0, f"200MA trend flag {trend200}")
    add("8MA rising (5 sessions)", ma8 > ma8_prior, f"{ma8_prior:.3f} -> {ma8:.3f}")
    if ma8 >= 0.60:
        checks.append({"check": "Breadth level", "points": 1, "detail": f"{ma8:.0%} of stocks above 200DMA (strong)"})
    elif ma8 < 0.40:
        checks.append({"check": "Breadth level", "points": -1, "detail": f"{ma8:.0%} of stocks above 200DMA (weak)"})
    else:
        checks.append({"check": "Breadth level", "points": 0, "detail": f"{ma8:.0%} of stocks above 200DMA (middling)"})
    if bearish_recent:
        checks.append({"check": "Bearish signal (last 5 sessions)", "points": -1, "detail": "Bearish signal fired"})

    points = sum(c["points"] for c in checks)
    for minimum, label, mult, guidance in REGIMES:
        if points >= minimum:
            break

    data_date = last["Date"]
    age_days = (date.today() - datetime.strptime(data_date[:10], "%Y-%m-%d").date()).days
    return {
        "data_date": data_date,
        "data_age_days": age_days,
        "stale": age_days > 5,
        "points": points,
        "regime": label,
        "risk_multiplier": mult,
        "guidance": guidance,
        "checks": checks,
    }


def main():
    parser = argparse.ArgumentParser(description="Gordongecko market regime check")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--csv", help="Local breadth CSV instead of downloading")
    parser.add_argument("--json", action="store_true", help="Print JSON only")
    args = parser.parse_args()

    try:
        result = assess(load_rows(args))
    except Exception as exc:  # fail closed: unknown regime means no new risk
        result = {"regime": "UNKNOWN", "risk_multiplier": 0.0,
                  "guidance": f"Could not read breadth data ({exc}). Treat as DEFENSIVE.",
                  "checks": []}
        print(json.dumps(result, indent=2))
        return 1

    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    print(f"Regime: {result['regime']}  (risk multiplier x{result['risk_multiplier']:.2f})")
    print(f"Data as of {result['data_date']} ({result['data_age_days']} days old)"
          + ("  WARNING: stale data" if result["stale"] else ""))
    print(result["guidance"])
    for c in result["checks"]:
        print(f"  {c['points']:+d}  {c['check']}: {c['detail']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
