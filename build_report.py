#!/usr/bin/env python3
"""
Generates a static HTML report from scorer results.
Run after scorer.py: python3 build_report.py
Outputs index.html for GitHub Pages.
"""

import json
import os
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def load_results():
    with open(os.path.join(SCRIPT_DIR, "results.json")) as f:
        return json.load(f)

def rating_color(rating):
    return {
        "firing": "#2ecc71",
        "good": "#7eb87e",
        "fair": "#c9a84c",
        "poor": "#c0392b",
        "flat": "#666",
    }.get(rating, "#666")

def score_bar_color(score):
    if score >= 70: return "#2ecc71"
    if score >= 55: return "#7eb87e"
    if score >= 40: return "#c9a84c"
    return "#c0392b"

def build_html(data):
    generated = data["generated"][:16].replace("T", " ") + " UTC"
    rankings = data["rankings"]

    cards_html = ""
    for i, r in enumerate(rankings, 1):
        # Day rows
        day_rows = ""
        for d in r["days"]:
            color = rating_color(d["rating"])
            day_rows += f"""
            <tr>
              <td style="color:#aaa">{d['date'][5:]}</td>
              <td><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{color};margin-right:6px"></span>{d['rating']}</td>
              <td style="text-align:right">{d['score']:.0f}</td>
              <td style="text-align:right">{d['avg_height_ft']:.0f}–{d['max_height_ft']:.0f}ft</td>
              <td style="text-align:right">{d['avg_period_s']:.0f}s</td>
              <td style="text-align:right">{d['avg_wind_kmh']:.0f}km/h</td>
            </tr>"""

        bar_width = r["trip_score"]
        bar_color = score_bar_color(r["trip_score"])

        cards_html += f"""
    <div class="card">
      <div class="card-header">
        <div class="rank">#{i}</div>
        <div class="region-info">
          <h2>{r['region']}</h2>
          <div class="meta">{r['good_days']} good days &middot; {r['great_days']} firing</div>
        </div>
        <div class="score-block">
          <div class="score-num">{r['trip_score']:.0f}</div>
          <div class="score-label">/ 100</div>
        </div>
      </div>
      <div class="bar-track"><div class="bar-fill" style="width:{bar_width}%;background:{bar_color}"></div></div>
      <table class="day-table">
        <thead>
          <tr><th>Date</th><th>Rating</th><th>Score</th><th>Height</th><th>Period</th><th>Wind</th></tr>
        </thead>
        <tbody>{day_rows}
        </tbody>
      </table>
    </div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Global Surf Scout</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #0a0a0a;
    color: #e0e0e0;
    padding: 2rem 1rem;
    max-width: 900px;
    margin: 0 auto;
  }}
  h1 {{
    font-size: 1.8rem;
    font-weight: 700;
    letter-spacing: -0.02em;
    margin-bottom: 0.3rem;
  }}
  .subtitle {{
    color: #888;
    font-size: 0.85rem;
    margin-bottom: 2rem;
  }}
  .card {{
    background: #151515;
    border: 1px solid #222;
    border-radius: 10px;
    padding: 1.2rem 1.4rem;
    margin-bottom: 1rem;
  }}
  .card-header {{
    display: flex;
    align-items: center;
    gap: 1rem;
    margin-bottom: 0.8rem;
  }}
  .rank {{
    font-size: 1.4rem;
    font-weight: 800;
    color: #555;
    min-width: 2.5rem;
  }}
  .region-info {{ flex: 1; }}
  .region-info h2 {{
    font-size: 1.15rem;
    font-weight: 600;
    color: #fff;
  }}
  .meta {{
    font-size: 0.8rem;
    color: #888;
    margin-top: 0.15rem;
  }}
  .score-block {{ text-align: right; }}
  .score-num {{
    font-size: 2rem;
    font-weight: 800;
    color: #fff;
    line-height: 1;
  }}
  .score-label {{
    font-size: 0.7rem;
    color: #555;
  }}
  .bar-track {{
    height: 4px;
    background: #222;
    border-radius: 2px;
    margin-bottom: 1rem;
    overflow: hidden;
  }}
  .bar-fill {{
    height: 100%;
    border-radius: 2px;
    transition: width 0.5s;
  }}
  .day-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.82rem;
  }}
  .day-table th {{
    text-align: left;
    color: #555;
    font-weight: 500;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 0.3rem 0.5rem;
    border-bottom: 1px solid #222;
  }}
  .day-table th:nth-child(n+3) {{ text-align: right; }}
  .day-table td {{
    padding: 0.35rem 0.5rem;
    border-bottom: 1px solid #1a1a1a;
  }}
  .day-table tr:last-child td {{ border-bottom: none; }}
  .footer {{
    text-align: center;
    color: #444;
    font-size: 0.75rem;
    margin-top: 2rem;
    padding-top: 1rem;
    border-top: 1px solid #1a1a1a;
  }}
  @media (max-width: 600px) {{
    body {{ padding: 1rem 0.5rem; }}
    .card {{ padding: 1rem; }}
    .score-num {{ font-size: 1.5rem; }}
    .day-table {{ font-size: 0.75rem; }}
    .day-table td, .day-table th {{ padding: 0.25rem 0.3rem; }}
  }}
</style>
</head>
<body>
  <h1>Global Surf Scout</h1>
  <p class="subtitle">14-day forecast rankings &middot; {generated}</p>
  {cards_html}
  <div class="footer">
    Data: Open-Meteo Marine API &middot; Swell + period + wind scoring &middot; Updated {generated}
  </div>
</body>
</html>"""

    return html


def main():
    data = load_results()
    html = build_html(data)
    out_path = os.path.join(SCRIPT_DIR, "index.html")
    with open(out_path, "w") as f:
        f.write(html)
    print(f"Report written to {out_path}")


if __name__ == "__main__":
    main()
