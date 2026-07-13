#!/usr/bin/env python3
"""
Global Surf Scout — Backtester

Pulls historical marine + wind data from Open-Meteo for a past date range,
runs the same scoring logic, then compares against what actually happened.

Usage:
  python3 backtest.py                          # last 14 days
  python3 backtest.py 2026-06-01 2026-06-14    # specific range
  python3 backtest.py --archive                # save a forecast snapshot for future comparison

How backtesting works:
  1. Pull actual observed conditions for a past window (Open-Meteo historical API)
  2. Score them with the same engine as the forecaster
  3. Show what the scorer WOULD have recommended if conditions were known perfectly
  4. Compare against archived forecast runs to measure forecast accuracy

The key question: when we said "firing", was it actually firing?
"""

import json
import math
import os
import sys
from datetime import datetime, date, timedelta, timezone
from urllib.request import urlopen
from urllib.error import URLError

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ARCHIVE_DIR = os.path.join(SCRIPT_DIR, "archive")

# Import scoring functions from scorer
sys.path.insert(0, SCRIPT_DIR)
from scorer import (
    load_regions, score_swell_height, score_period, score_wind,
    score_hour, analyze_region, W_SWELL, W_PERIOD, W_WIND
)


def fetch_historical(lat, lon, start_date, end_date):
    """Fetch historical marine + wind data from Open-Meteo."""
    url = (
        f"https://marine-api.open-meteo.com/v1/marine?"
        f"latitude={lat}&longitude={lon}"
        f"&hourly=wave_height,wave_period,wave_direction"
        f"&start_date={start_date}&end_date={end_date}"
        f"&timezone=auto"
    )
    wind_url = (
        f"https://archive-api.open-meteo.com/v1/archive?"
        f"latitude={lat}&longitude={lon}"
        f"&hourly=wind_speed_10m,wind_direction_10m"
        f"&start_date={start_date}&end_date={end_date}"
        f"&timezone=auto"
    )
    try:
        with urlopen(url) as resp:
            marine = json.loads(resp.read())
        with urlopen(wind_url) as resp:
            wind = json.loads(resp.read())
        return marine, wind
    except URLError as e:
        print(f"  [ERROR] Failed to fetch historical data: {e}")
        return None, None


def archive_forecast():
    """Save current forecast results with today's date for future comparison."""
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    results_path = os.path.join(SCRIPT_DIR, "results.json")
    if not os.path.exists(results_path):
        print("No results.json found. Run scorer.py first.")
        return

    with open(results_path) as f:
        data = json.load(f)

    today = date.today().isoformat()
    archive_path = os.path.join(ARCHIVE_DIR, f"forecast_{today}.json")
    with open(archive_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Forecast archived to {archive_path}")


def run_backtest(start_str, end_str):
    """Run scoring on historical data and compare against any archived forecasts."""
    regions = load_regions(os.path.join(SCRIPT_DIR, "regions.json"))

    print(f"\n  BACKTEST: {start_str} to {end_str}")
    print(f"  Pulling actual observed conditions...\n")

    actuals = []
    for region in regions:
        print(f"  [{region['id']}] Fetching actuals...", end=" ", flush=True)
        marine, wind = fetch_historical(region["lat"], region["lon"], start_str, end_str)
        if marine and wind:
            result = analyze_region(region, marine, wind)
            actuals.append(result)
            print(f"actual score: {result['trip_score']} | {result['good_days']} good days")
        else:
            print("FAILED")

    if not actuals:
        print("No data retrieved.")
        return

    # Print actual rankings
    ranked = sorted(actuals, key=lambda r: r["trip_score"], reverse=True)
    print("\n" + "=" * 70)
    print(f"  ACTUAL CONDITIONS: {start_str} to {end_str}")
    print("=" * 70)

    for i, r in enumerate(ranked, 1):
        print(f"\n  #{i}  {r['region']}")
        print(f"      Score: {r['trip_score']}/100  |  Good: {r['good_days']}  |  Firing: {r['great_days']}")
        for d in r["days"]:
            icon = {"firing": "***", "good": "** ", "fair": "*  ", "poor": ".  ", "flat": "   "}
            print(f"        {d['date']}  {icon.get(d['rating'], '   ')} {d['rating']:>7}  "
                  f"{d['score']:5.1f}  |  {d['avg_height_ft']:.0f}-{d['max_height_ft']:.0f}ft  "
                  f"{d['avg_period_s']:.0f}s  wind {d['avg_wind_kmh']:.0f}km/h")

    # Compare against archived forecast if one exists
    compare_with_archive(start_str, end_str, actuals)

    # Save backtest results
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    out_path = os.path.join(ARCHIVE_DIR, f"backtest_{start_str}_{end_str}.json")
    with open(out_path, "w") as f:
        json.dump({
            "type": "backtest",
            "start": start_str,
            "end": end_str,
            "generated": datetime.now(timezone.utc).isoformat(),
            "actuals": ranked,
        }, f, indent=2)
    print(f"\n  Backtest saved to {out_path}")


def compare_with_archive(start_str, end_str, actuals):
    """Find any archived forecast that covers this period and compare."""
    if not os.path.exists(ARCHIVE_DIR):
        return

    # Look for forecasts that would have covered this date range
    actual_by_id = {r["id"]: r for r in actuals}
    found_comparison = False

    for fname in sorted(os.listdir(ARCHIVE_DIR)):
        if not fname.startswith("forecast_"):
            continue

        fpath = os.path.join(ARCHIVE_DIR, fname)
        with open(fpath) as f:
            forecast_data = json.load(f)

        forecast_by_id = {r["id"]: r for r in forecast_data["rankings"]}

        # Check if forecast dates overlap with our backtest range
        overlap = False
        for r in forecast_data["rankings"]:
            if r["days"]:
                forecast_dates = {d["date"] for d in r["days"]}
                backtest_dates = {d["date"] for d in actuals[0]["days"]} if actuals else set()
                if forecast_dates & backtest_dates:
                    overlap = True
                    break

        if not overlap:
            continue

        found_comparison = True
        forecast_date = fname.replace("forecast_", "").replace(".json", "")

        print(f"\n{'=' * 70}")
        print(f"  FORECAST vs ACTUAL (forecast from {forecast_date})")
        print(f"{'=' * 70}")
        print(f"\n  {'Region':<35} {'Forecast':>10} {'Actual':>10} {'Diff':>8}  Accuracy")
        print(f"  {'-' * 35} {'-' * 10} {'-' * 10} {'-' * 8}  {'-' * 10}")

        total_diff = 0
        count = 0
        day_hits = 0
        day_total = 0

        for rid, actual in actual_by_id.items():
            if rid not in forecast_by_id:
                continue

            forecast = forecast_by_id[rid]
            diff = actual["trip_score"] - forecast["trip_score"]
            total_diff += abs(diff)
            count += 1

            # Day-level rating accuracy
            forecast_days = {d["date"]: d["rating"] for d in forecast["days"]}
            for d in actual["days"]:
                if d["date"] in forecast_days:
                    day_total += 1
                    f_rating = forecast_days[d["date"]]
                    a_rating = d["rating"]
                    # "Hit" = within one tier
                    tiers = ["flat", "poor", "fair", "good", "firing"]
                    f_idx = tiers.index(f_rating) if f_rating in tiers else -1
                    a_idx = tiers.index(a_rating) if a_rating in tiers else -1
                    if abs(f_idx - a_idx) <= 1:
                        day_hits += 1

            direction = "+" if diff > 0 else "" if diff == 0 else ""
            accuracy_pct = ""
            print(f"  {actual['region']:<35} {forecast['trip_score']:>10.1f} {actual['trip_score']:>10.1f} {direction}{diff:>+7.1f}")

        if count:
            mae = total_diff / count
            day_acc = (day_hits / day_total * 100) if day_total else 0
            print(f"\n  Mean absolute error: {mae:.1f} points")
            print(f"  Day-level accuracy (within 1 tier): {day_acc:.0f}% ({day_hits}/{day_total} days)")

            if mae < 5:
                print(f"  Verdict: Excellent — forecasts closely match reality")
            elif mae < 10:
                print(f"  Verdict: Good — minor deviations, rankings mostly held")
            elif mae < 20:
                print(f"  Verdict: Fair — some significant misses, review wind scoring")
            else:
                print(f"  Verdict: Poor — scoring model needs recalibration")

    if not found_comparison:
        print(f"\n  No archived forecast found covering {start_str} to {end_str}.")
        print(f"  Run 'python3 backtest.py --archive' to save today's forecast for future comparison.")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--archive":
        archive_forecast()
        return

    if len(sys.argv) == 3:
        start_str = sys.argv[1]
        end_str = sys.argv[2]
    else:
        # Default: last 14 days
        end = date.today() - timedelta(days=1)
        start = end - timedelta(days=13)
        start_str = start.isoformat()
        end_str = end.isoformat()

    run_backtest(start_str, end_str)


if __name__ == "__main__":
    main()
