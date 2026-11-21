#!/usr/bin/env python3
"""Render today's Finnish spot electricity prices as a Kindle lock screen PNG.

Data source: api.spot-hinta.fi (Nord Pool day-ahead prices for the FI area,
15-minute resolution, prices including VAT).

Output (in --out-dir):
    kindle.png           image for the current hour
    prices.json          hourly prices + laundry window, for other displays
    frames/YYYYMMDD-HH.png  one image per hour for today and tomorrow
    frames/manifest.txt  list of the frame file names

Images are 1072x1448 8-bit grayscale PNGs (Kindle Paperwhite 3 native size).
Prices are fixed a day ahead, so the Kindle only has to download the frames
once a day and can switch images every hour without a network connection.

Usage:
    python render.py --out-dir out
    python render.py --input sample.json --now 2026-11-21T09:30 --out-dir out
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

# --------------------------------------------------------------------------
# Configuration (override with environment variables if needed)
# --------------------------------------------------------------------------

TZ = ZoneInfo(os.environ.get("KSP_TIMEZONE", "Europe/Helsinki"))
REGION = os.environ.get("KSP_REGION", "FI")
API_URL = "https://api.spot-hinta.fi/TodayAndDayForward?region={region}&priceResolution=15"

WIDTH, HEIGHT = 1072, 1448          # Kindle Paperwhite 3 (7th gen)

Y_MAX = 40.0                        # top of the scale, c/kWh
Y_HEADROOM = 4.0                    # extra space above Y_MAX
STEP = 4.0                          # one gray level per 4 c/kWh
CHEAP_LINE = 8.0                    # dashed "cheap" reference line
EXPENSIVE_LINE = 20.0               # dashed "expensive" reference line

LAUNDRY_HOURS = 2                   # length of the laundry window
LAUNDRY_EARLIEST = 7                # window may start at 07:00 at the earliest
LAUNDRY_LATEST = 22                 # ...and must end by 22:00

FONT_CANDIDATES = {
    "regular": [
        os.environ.get("KSP_FONT_REGULAR", ""),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",          # Ubuntu / GitHub Actions
        "/System/Library/Fonts/Supplemental/Arial.ttf",              # macOS
        "C:/Windows/Fonts/arial.ttf",
    ],
    "bold": [
        os.environ.get("KSP_FONT_BOLD", ""),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ],
}

# The Kindle panel shows 16 gray levels (multiples of 17). Using exactly
# those values avoids dithering. 11 levels: 0-4, 4-8, ..., 36-40, >40.
GRAY_INDEX = [15, 14, 12, 11, 9, 8, 6, 5, 3, 2, 0]
GRAYS = [i * 17 for i in GRAY_INDEX]


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Slot:
    start: datetime          # timezone-aware
    price: float             # c/kWh including VAT


@dataclass(frozen=True)
class Hour:
    start: datetime          # local time, timezone-aware
    price: float             # average of the 15-min slots, c/kWh


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime
    price: float             # average over the window, c/kWh
    day: date


def fetch_raw(region: str = REGION, retries: int = 3) -> list[dict]:
    url = API_URL.format(region=region)
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "kindle-spot-price"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except Exception as err:  # noqa: BLE001 - retry on any network error
            last_err = err
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Could not fetch prices from {url}: {last_err}")


def parse_slots(raw: list[dict]) -> list[Slot]:
    """spot-hinta.fi returns EUR/kWh; convert to c/kWh."""
    slots = [
        Slot(datetime.fromisoformat(item["DateTime"]), float(item["PriceWithTax"]) * 100)
        for item in raw
    ]
    return sorted(slots, key=lambda s: s.start)


def slots_for_day(slots: list[Slot], day: date) -> list[Slot]:
    return [s for s in slots if s.start.astimezone(TZ).date() == day]


def hourly_averages(slots: list[Slot]) -> list[Hour]:
    """Average 15-min slots per clock hour.

    Grouping is done on the UTC hour, so the repeated hour on the autumn DST
    day is kept as two separate bars (25 bars) and the spring day has 23.
    """
    groups: dict[datetime, list[float]] = {}
    for s in slots:
        key = s.start.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        groups.setdefault(key, []).append(s.price)
    return [
        Hour(k.astimezone(TZ), sum(v) / len(v))
        for k, v in sorted(groups.items())
    ]


def best_window(
    slots: list[Slot],
    day: date,
    not_before: datetime | None = None,
    hours: int = LAUNDRY_HOURS,
    earliest: int = LAUNDRY_EARLIEST,
    latest: int = LAUNDRY_LATEST,
) -> Window | None:
    """Cheapest continuous window of `hours` hours on `day`, using 15-min slots.

    The window must start at or after `earliest` o'clock (and after
    `not_before`, if given) and end at or before `latest` o'clock.
    """
    day_slots = slots_for_day(slots, day)
    if not day_slots:
        return None
    n = hours * 4
    lo = datetime.combine(day, datetime.min.time(), TZ).replace(hour=earliest)
    hi = datetime.combine(day, datetime.min.time(), TZ).replace(hour=latest)
    if not_before is not None:
        lo = max(lo, not_before)

    best: Window | None = None
    for i in range(len(day_slots) - n + 1):
        chunk = day_slots[i : i + n]
        start = chunk[0].start
        end = chunk[-1].start + timedelta(minutes=15)
        # slots must be contiguous (no gaps in the data)
        if end - start != timedelta(minutes=15 * n):
            continue
        if start < lo or end > hi:
            continue
        avg = sum(s.price for s in chunk) / n
        if best is None or avg < best.price:
            best = Window(start.astimezone(TZ), end.astimezone(TZ), avg, day)
    return best


def laundry_window(slots: list[Slot], now: datetime) -> Window | None:
    """Best window in the rest of today; if none is left, tomorrow's (if known)."""
    today = now.astimezone(TZ).date()
    # round "now" up to the next quarter hour
    q = now.astimezone(TZ).replace(second=0, microsecond=0)
    if q.minute % 15:
        q += timedelta(minutes=15 - q.minute % 15)
    win = best_window(slots, today, not_before=q)
    if win is None:
        win = best_window(slots, today + timedelta(days=1))
    return win


def gray_for(price: float) -> int:
    if price < 0:
        return GRAYS[0]
    idx = min(int(price // STEP), len(GRAYS) - 1)
    return GRAYS[idx]


# --------------------------------------------------------------------------
# Drawing
# --------------------------------------------------------------------------

def load_font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES[kind]:
        if path and Path(path).exists():
            return ImageFont.truetype(path, size)
    raise FileNotFoundError(
        f"No {kind} font found. Install fonts-dejavu-core or set KSP_FONT_{kind.upper()}."
    )


def fmt_price(p: float) -> str:
    return f"{p:.1f}"


def fmt_hm(dt: datetime) -> str:
    return dt.astimezone(TZ).strftime("%H:%M")


def dashed_hline(d: ImageDraw.ImageDraw, x0: int, x1: int, y: int, width: int = 3,
                 dash: int = 18, gap: int = 12, fill: int = 0) -> None:
    x = x0
    while x < x1:
        d.line([(x, y), (min(x + dash, x1), y)], fill=fill, width=width)
        x += dash + gap


def render(hours: list[Hour], laundry: Window | None, now: datetime, out_path: Path) -> None:
    img = Image.new("L", (WIDTH, HEIGHT), 255)
    d = ImageDraw.Draw(img)

    f_title = load_font("bold", 44)
    f_small = load_font("regular", 30)
    f_axis = load_font("regular", 28)
    f_label = load_font("regular", 34)
    f_big = load_font("bold", 76)
    f_mid = load_font("bold", 42)
    f_now = load_font("bold", 92)

    now_l = now.astimezone(TZ)

    # ---- header ----
    title = "Spot price today"
    d.text((60, 60), title, font=f_title, fill=0)
    d.text((60, 122), "c/kWh incl. VAT", font=f_small, fill=85)

    # current hour's price, big, top right (also shows which hour this image is for)
    current = next((h for h in hours if h.start <= now_l < h.start + timedelta(hours=1)), None)
    if current is not None:
        d.text((WIDTH - 60, 40), fmt_price(current.price), font=f_now, fill=0, anchor="ra")
        span = f"now · {fmt_hm(current.start)}–{fmt_hm(current.start + timedelta(hours=1))}"
        d.text((WIDTH - 60, 140), span, font=f_small, fill=60, anchor="ra")
    else:
        d.text((WIDTH - 60, 72), f"{now_l:%H}:00", font=f_small, fill=85, anchor="ra")

    # ---- chart geometry ----
    left, right = 120, WIDTH - 50
    top, bottom = 250, 960
    plot_h = bottom - top
    scale_top = Y_MAX + Y_HEADROOM
    has_negative = any(h.price < 0 for h in hours)
    scale_bottom = -4.0 if has_negative else 0.0

    def y_of(v: float) -> float:
        v = max(min(v, scale_top), scale_bottom)
        return bottom - (v - scale_bottom) / (scale_top - scale_bottom) * plot_h

    # grid + y labels
    for v in range(0, int(Y_MAX) + 1, 10):
        y = y_of(v)
        d.line([(left, y), (right, y)], fill=200, width=1)
        d.text((left - 16, y), str(v), font=f_axis, fill=60, anchor="rm")
    # reference lines
    dashed_hline(d, left, right, round(y_of(CHEAP_LINE)), width=3, fill=60)
    dashed_hline(d, left, right, round(y_of(EXPENSIVE_LINE)), width=3, fill=0)
    d.text((right, y_of(CHEAP_LINE) - 6), "8", font=f_axis, fill=60, anchor="rb")
    d.text((right, y_of(EXPENSIVE_LINE) - 6), "20", font=f_axis, fill=0, anchor="rb")

    # bars
    n = max(len(hours), 1)
    slot_w = (right - left) / n
    gap = 6
    zero_y = y_of(0)
    cur_idx = None
    for i, h in enumerate(hours):
        x0 = left + i * slot_w + gap / 2
        x1 = left + (i + 1) * slot_w - gap / 2
        is_now = h.start <= now_l < h.start + timedelta(hours=1)
        if is_now:
            cur_idx = i
        y_top = y_of(h.price)
        y0, y1 = sorted((y_top, zero_y))
        if y1 - y0 < 3:            # keep tiny prices visible
            y0 = zero_y - 3
        d.rectangle([x0, y0, x1, y1], fill=gray_for(h.price), outline=0,
                    width=5 if is_now else 2)
        if h.price > Y_MAX:        # clipped: show the value above the bar
            cx = (x0 + x1) / 2
            d.polygon([(cx - 10, y0 - 6), (cx + 10, y0 - 6), (cx, y0 - 20)], fill=0)
            d.text((cx, y0 - 24), f"{h.price:.0f}", font=f_axis, fill=0, anchor="mb")

    # baseline
    d.line([(left, zero_y), (right, zero_y)], fill=0, width=3)

    # x labels every 3 hours
    for i, h in enumerate(hours):
        if h.start.hour % 3 == 0 and h.start.minute == 0:
            cx = left + (i + 0.5) * slot_w
            d.text((cx, bottom + 14), f"{h.start.hour:02d}", font=f_axis, fill=40, anchor="ma")

    # "now" marker under the current hour
    if cur_idx is not None:
        cx = left + (cur_idx + 0.5) * slot_w
        ty = bottom + 54
        d.polygon([(cx, ty), (cx - 14, ty + 22), (cx + 14, ty + 22)], fill=0)

    # laundry window bracket under the axis
    if laundry is not None and hours and laundry.day == now_l.date():
        def x_of(t: datetime) -> float:
            i0 = 0
            for i, h in enumerate(hours):
                if h.start <= t:
                    i0 = i
            h = hours[i0]
            frac = (t - h.start) / timedelta(hours=1)
            return left + (i0 + frac) * slot_w
        lx0, lx1 = x_of(laundry.start), x_of(laundry.end)
        ly = bottom + 92
        d.rectangle([lx0, ly, lx1, ly + 12], fill=0)
        d.text(((lx0 + lx1) / 2, ly + 18), "Laundry", font=f_axis, fill=0, anchor="ma")

    # ---- legend: gray scale ----
    lg_top = 1120
    lg_left, lg_right = 120, WIDTH - 50
    block_w = (lg_right - lg_left) / len(GRAYS)
    for i, g in enumerate(GRAYS):
        x0 = lg_left + i * block_w
        d.rectangle([x0, lg_top, x0 + block_w, lg_top + 30], fill=g, outline=0, width=1)
    for v, label in [(0, "0"), (8, "8"), (20, "20"), (40, "40+")]:
        x = lg_left + (v / STEP) * block_w
        d.text((x, lg_top + 38), label, font=f_axis, fill=40, anchor="ma")

    # ---- bottom stats ----
    if hours:
        hi = max(hours, key=lambda h: h.price)
        lo = min(hours, key=lambda h: h.price)
        col_w = (WIDTH - 120) / 3
        y_lab, y_val, y_sub = 1230, 1272, 1362
        stats = [
            ("High", fmt_price(hi.price), f"{fmt_hm(hi.start)}–{fmt_hm(hi.start + timedelta(hours=1))}"),
            ("Low", fmt_price(lo.price), f"{fmt_hm(lo.start)}–{fmt_hm(lo.start + timedelta(hours=1))}"),
        ]
        if laundry is not None:
            prefix = "" if laundry.day == now_l.date() else "Tomorrow · "
            stats.append(("Best laundry", f"{fmt_hm(laundry.start)}–{fmt_hm(laundry.end)}",
                          f"{prefix}avg {fmt_price(laundry.price)}"))
        else:
            stats.append(("Best laundry", "—", "none left today"))
        for i, (lab, val, sub) in enumerate(stats):
            cx = 60 + col_w * (i + 0.5)
            d.text((cx, y_lab), lab, font=f_label, fill=60, anchor="ma")
            font = f_big if i < 2 else f_mid
            vy = y_val if i < 2 else y_val + 16
            d.text((cx, vy), val, font=font, fill=0, anchor="ma")
            d.text((cx, y_sub), sub, font=f_small, fill=60, anchor="ma")
        # dividers
        for i in (1, 2):
            x = 60 + col_w * i
            d.line([(x, 1230), (x, 1400)], fill=170, width=2)
    else:
        d.text((WIDTH / 2, 560), "No price data for today", font=f_mid, fill=0, anchor="mm")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, optimize=True)


def summary(hours: list[Hour], laundry: Window | None, now: datetime) -> dict:
    return {
        "generated": now.astimezone(TZ).isoformat(timespec="minutes"),
        "unit": "c/kWh incl. VAT",
        "hours": [{"start": h.start.isoformat(timespec="minutes"), "price": round(h.price, 3)}
                  for h in hours],
        "laundry": None if laundry is None else {
            "start": laundry.start.isoformat(timespec="minutes"),
            "end": laundry.end.isoformat(timespec="minutes"),
            "price": round(laundry.price, 3),
        },
    }


def render_frames(slots: list[Slot], frames_dir: Path, now: datetime) -> list[str]:
    """Render one image per local hour for today and (if published) tomorrow.

    File names are YYYYMMDD-HH.png in local time. Each image marks its own hour
    as "now" and shows the laundry window for the rest of that day. Returns the
    file names, which are also written to manifest.txt.
    """
    frames_dir.mkdir(parents=True, exist_ok=True)
    today = now.astimezone(TZ).date()
    names: list[str] = []
    for day in (today, today + timedelta(days=1)):
        hours = hourly_averages(slots_for_day(slots, day))
        if not hours:
            continue
        for h in hours:
            name = f"{h.start:%Y%m%d-%H}.png"
            if name in names:          # repeated hour on the DST day: keep the first
                continue
            render(hours, laundry_window(slots, h.start), h.start, frames_dir / name)
            names.append(name)
    (frames_dir / "manifest.txt").write_text("\n".join(names) + "\n")
    return names


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", default="out", help="where to write the output")
    ap.add_argument("--input", help="read API JSON from a file instead of the network")
    ap.add_argument("--now", help="pretend the current local time is this (ISO format)")
    ap.add_argument("--no-frames", action="store_true", help="only render kindle.png for the current hour")
    args = ap.parse_args(argv)

    now = datetime.now(TZ)
    if args.now:
        now = datetime.fromisoformat(args.now)
        if now.tzinfo is None:
            now = now.replace(tzinfo=TZ)

    raw = json.loads(Path(args.input).read_text()) if args.input else fetch_raw()
    slots = parse_slots(raw)
    today = now.astimezone(TZ).date()
    hours = hourly_averages(slots_for_day(slots, today))
    laundry = laundry_window(slots, now)

    out = Path(args.out_dir)
    render(hours, laundry, now, out / "kindle.png")
    (out / "prices.json").write_text(json.dumps(summary(hours, laundry, now), ensure_ascii=False, indent=2))
    print(f"wrote {out / 'kindle.png'} ({len(hours)} hours)")

    if not args.no_frames:
        names = render_frames(slots, out / "frames", now)
        print(f"wrote {len(names)} frames to {out / 'frames'}")
    return 0 if hours else 1


if __name__ == "__main__":
    sys.exit(main())
