"""Generate a synthetic (made-up) two-day price file in the spot-hinta.fi format.

Used for tests and preview images only; the shape mimics a cold winter day
(cheap night, morning and evening peaks).
"""
import json, math, random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

tz = ZoneInfo("Europe/Helsinki")
random.seed(7)
start = datetime(2026, 11, 21, tzinfo=tz)
out = []
for i in range(2 * 96):
    t = start + timedelta(minutes=15 * i)
    h = t.hour + t.minute / 60
    base = 3 + 24 * math.exp(-((h - 8.5) / 1.8) ** 2) + 38 * math.exp(-((h - 18) / 2.0) ** 2)
    base += 6 * math.exp(-((h - 13) / 3) ** 2)
    if t.day == 22:
        base *= 0.7
    p = max(0.5, base + random.uniform(-2, 2))
    out.append({"Rank": 0, "DateTime": t.isoformat(), "PriceNoTax": round(p / 125.5, 5),
                "PriceWithTax": round(p / 100, 5)})
json.dump(out, open("tests/fixtures/sample-winter.json", "w"), indent=1)
