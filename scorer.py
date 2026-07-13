#!/usr/bin/env python3
"""
Global Surf Scout — M1 Scoring Engine
Pulls 14-day marine forecasts from Open-Meteo, scores 10 pilot regions,
ranks them by surfability.

Scoring factors (V1):
  - Swell height: sweet spot 3-8ft (0.9-2.4m), penalize outside
  - Swell period: longer = better, 12s+ is quality, 16s+ is pumping
  - Wind: lighter is better, offshore is best, onshore kills it

No API key needed. Open-Meteo is free.
"""

import json
import math
import sys
from datetime import datetime, timezone
from urllib.request import urlopen
from urllib.error import URLError

# --- Configuration ---
SWEET_SPOT_MIN_M = 0.9   # ~3ft
SWEET_SPOT_MAX_M = 2.4   # ~8ft
HARD_MAX_M = 4.0          # ~13ft, safety gate
MAX_WIND_KMH = 35         # above this, almost always blown out

# Weights
W_SWELL = 0.40
W_PERIOD = 0.30
W_WIND = 0.30


def load_regions(path="regions.json"):
    with open(path) as f:
        return json.load(f)


def fetch_marine_forecast(lat, lon):
    """Fetch 14-day marine + wind forecast from Open-Meteo."""
    url = (
        f"https://marine-api.open-meteo.com/v1/marine?"
        f"latitude={lat}&longitude={lon}"
        f"&hourly=wave_height,wave_period,wave_direction"
        f"&forecast_days=14&timezone=auto"
    )
    wind_url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        f"&hourly=wind_speed_10m,wind_direction_10m"
        f"&forecast_days=14&timezone=auto"
    )
    try:
        with urlopen(url) as resp:
            marine = json.loads(resp.read())
        with urlopen(wind_url) as resp:
            wind = json.loads(resp.read())
        return marine, wind
    except URLError as e:
        print(f"  [ERROR] Failed to fetch forecast: {e}")
        return None, None


def score_swell_height(height_m):
    """0-100 score. Peak at sweet spot, drops off outside."""
    if height_m is None or height_m < 0.3:
        return 0  # flat
    if height_m > HARD_MAX_M:
        return 0  # safety gate
    if SWEET_SPOT_MIN_M <= height_m <= SWEET_SPOT_MAX_M:
        # Peak score in the middle of sweet spot
        mid = (SWEET_SPOT_MIN_M + SWEET_SPOT_MAX_M) / 2
        dist = abs(height_m - mid) / (SWEET_SPOT_MAX_M - SWEET_SPOT_MIN_M) * 2
        return int(100 - dist * 20)  # 80-100 range
    if height_m < SWEET_SPOT_MIN_M:
        return int((height_m / SWEET_SPOT_MIN_M) * 70)  # 0-70
    # Between max sweet spot and hard max
    ratio = (height_m - SWEET_SPOT_MAX_M) / (HARD_MAX_M - SWEET_SPOT_MAX_M)
    return int(70 * (1 - ratio))  # 70 down to 0


def score_period(period_s):
    """0-100. Under 8s is junk, 12+ is quality, 16+ is pumping."""
    if period_s is None or period_s < 5:
        return 0
    if period_s < 8:
        return int((period_s - 5) / 3 * 30)  # 0-30
    if period_s < 12:
        return int(30 + (period_s - 8) / 4 * 40)  # 30-70
    if period_s < 16:
        return int(70 + (period_s - 12) / 4 * 25)  # 70-95
    return min(100, int(95 + (period_s - 16) / 4 * 5))  # 95-100


def angle_diff(a, b):
    """Smallest angle between two compass bearings."""
    d = abs((a % 360) - (b % 360))
    return min(d, 360 - d)


def score_wind(speed_kmh, direction, offshore_dir, wind_profile=None):
    """0-100. Scores wind speed and direction.

    Default: light + offshore = best.
    With wind_profile: ideal_min-ideal_max offshore = best (e.g. Salina Cruz
    needs moderate north wind for grooming; too calm = mushy).
    """
    if speed_kmh is None or direction is None:
        return 50  # no data, neutral

    # Speed component
    if wind_profile:
        ideal_min = wind_profile["ideal_min"]
        ideal_max = wind_profile["ideal_max"]
        too_strong = wind_profile.get("too_strong", 45)

        if ideal_min <= speed_kmh <= ideal_max:
            speed_score = 100  # sweet spot
        elif speed_kmh < ideal_min:
            # Too calm — penalize proportionally
            speed_score = int(40 + 60 * (speed_kmh / ideal_min))
        elif speed_kmh <= too_strong:
            # Above ideal but not blown out
            ratio = (speed_kmh - ideal_max) / (too_strong - ideal_max)
            speed_score = int(100 - ratio * 70)  # 100 down to 30
        else:
            speed_score = 5  # blown out
    else:
        # Default: lighter is better
        if speed_kmh < 8:
            speed_score = 100  # glassy
        elif speed_kmh < 15:
            speed_score = 85   # light
        elif speed_kmh < 25:
            speed_score = 55   # moderate
        elif speed_kmh < MAX_WIND_KMH:
            speed_score = 25   # strong
        else:
            speed_score = 5    # howling

    # Direction component: offshore = 100, cross = 60, onshore = 20
    diff = angle_diff(direction, offshore_dir)
    if diff < 45:
        dir_score = 100  # offshore
    elif diff < 90:
        dir_score = 70   # cross-off
    elif diff < 135:
        dir_score = 40   # cross-on
    else:
        dir_score = 15   # onshore

    return int(speed_score * 0.5 + dir_score * 0.5)


def score_hour(height, period, wind_speed, wind_dir, offshore_dir, wind_profile=None):
    """Combined score for a single hour."""
    s = score_swell_height(height)
    p = score_period(period)
    w = score_wind(wind_speed, wind_dir, offshore_dir, wind_profile)
    return s * W_SWELL + p * W_PERIOD + w * W_WIND


def analyze_region(region, marine, wind):
    """Score every hour, aggregate into daily and trip-level stats."""
    hours = marine["hourly"]
    wind_hours = wind["hourly"]
    times = hours["time"]

    # Build hourly scores
    daily = {}
    all_scores = []

    for i, t in enumerate(times):
        date = t[:10]
        height = hours["wave_height"][i]
        period = hours["wave_period"][i]

        # Match wind data by index (same hourly grid)
        w_speed = wind_hours["wind_speed_10m"][i] if i < len(wind_hours["wind_speed_10m"]) else None
        w_dir = wind_hours["wind_direction_10m"][i] if i < len(wind_hours["wind_direction_10m"]) else None

        sc = score_hour(height, period, w_speed, w_dir, region["offshore_dir"], region.get("wind_profile"))

        if date not in daily:
            daily[date] = {"scores": [], "heights": [], "periods": [], "winds": []}
        daily[date]["scores"].append(sc)
        daily[date]["heights"].append(height or 0)
        daily[date]["periods"].append(period or 0)
        daily[date]["winds"].append(w_speed or 0)
        all_scores.append(sc)

    # Aggregate daily
    day_summaries = []
    good_days = 0
    great_days = 0

    for date in sorted(daily.keys()):
        d = daily[date]
        # Use best 6-hour window (dawn patrol + morning typically)
        top_scores = sorted(d["scores"], reverse=True)[:6]
        best_window = sum(top_scores) / len(top_scores) if top_scores else 0
        avg_height_ft = (sum(d["heights"]) / len(d["heights"])) * 3.28 if d["heights"] else 0
        max_height_ft = max(d["heights"]) * 3.28 if d["heights"] else 0
        avg_period = sum(d["periods"]) / len(d["periods"]) if d["periods"] else 0
        avg_wind = sum(d["winds"]) / len(d["winds"]) if d["winds"] else 0

        rating = "flat"
        if best_window >= 70:
            rating = "firing"
            great_days += 1
            good_days += 1
        elif best_window >= 55:
            rating = "good"
            good_days += 1
        elif best_window >= 40:
            rating = "fair"
        elif best_window >= 25:
            rating = "poor"

        day_summaries.append({
            "date": date,
            "score": round(best_window, 1),
            "rating": rating,
            "avg_height_ft": round(avg_height_ft, 1),
            "max_height_ft": round(max_height_ft, 1),
            "avg_period_s": round(avg_period, 1),
            "avg_wind_kmh": round(avg_wind, 1),
        })

    # Trip-level
    avg_score = sum(all_scores) / len(all_scores) if all_scores else 0
    top_day_scores = sorted([d["score"] for d in day_summaries], reverse=True)
    best_5_avg = sum(top_day_scores[:5]) / min(5, len(top_day_scores)) if top_day_scores else 0

    return {
        "region": region["name"],
        "id": region["id"],
        "trip_score": round(best_5_avg, 1),
        "avg_score": round(avg_score, 1),
        "good_days": good_days,
        "great_days": great_days,
        "total_days": len(day_summaries),
        "days": day_summaries,
    }


def print_report(results):
    """Print ranked results."""
    ranked = sorted(results, key=lambda r: r["trip_score"], reverse=True)

    print("\n" + "=" * 70)
    print(f"  GLOBAL SURF SCOUT — 14-DAY FORECAST RANKINGS")
    print(f"  Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 70)

    for i, r in enumerate(ranked, 1):
        bar = "#" * int(r["trip_score"] / 2)
        print(f"\n  #{i}  {r['region']}")
        print(f"      Trip Score: {r['trip_score']}/100  [{bar}]")
        print(f"      Good days: {r['good_days']}/{r['total_days']}  |  Firing days: {r['great_days']}")
        print()

        # Show day-by-day
        for d in r["days"]:
            icon = {"firing": "***", "good": "** ", "fair": "*  ", "poor": ".  ", "flat": "   "}
            print(f"        {d['date']}  {icon.get(d['rating'], '   ')} {d['rating']:>7}  "
                  f"{d['score']:5.1f}  |  {d['avg_height_ft']:.0f}-{d['max_height_ft']:.0f}ft  "
                  f"{d['avg_period_s']:.0f}s  wind {d['avg_wind_kmh']:.0f}km/h")

    print("\n" + "=" * 70)
    print(f"  Top pick: {ranked[0]['region']} — {ranked[0]['good_days']} good days, "
          f"score {ranked[0]['trip_score']}")
    print("=" * 70 + "\n")

    return ranked


def save_json(results, path="results.json"):
    ranked = sorted(results, key=lambda r: r["trip_score"], reverse=True)
    output = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "rankings": ranked,
    }
    with open(path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"  Results saved to {path}")


def main():
    import os
    script_dir = os.path.dirname(os.path.abspath(__file__))
    regions = load_regions(os.path.join(script_dir, "regions.json"))

    print(f"\n  Fetching 14-day forecasts for {len(regions)} regions...")
    print(f"  Source: Open-Meteo Marine API (free, no key)\n")

    results = []
    for region in regions:
        print(f"  [{region['id']}] Fetching {region['name']}...", end=" ", flush=True)
        marine, wind = fetch_marine_forecast(region["lat"], region["lon"])
        if marine and wind:
            result = analyze_region(region, marine, wind)
            results.append(result)
            print(f"score: {result['trip_score']} | {result['good_days']} good days")
        else:
            print("FAILED")

    if results:
        print_report(results)
        save_json(results, os.path.join(script_dir, "results.json"))


if __name__ == "__main__":
    main()
