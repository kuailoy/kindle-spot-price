#!/usr/bin/env python3
"""Render today's Finnish spot electricity prices as a Kindle lock screen PNG.

Data source: api.spot-hinta.fi (Nord Pool day-ahead prices for the FI area,
15-minute resolution, prices including VAT).

Output (in --out-dir):
    kindle.png           image for the current hour (as stored on the Kindle)
    preview.png          the same image upright (landscape), for the web page
    index.html           small web page for GitHub Pages
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
import math
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

LAYOUT = os.environ.get("KSP_LAYOUT", "landscape")   # "portrait" or "landscape"
# landscape only: how the picture is turned into the Kindle's portrait image.
# 270: hold the Kindle with its top edge on your left; 90: top edge on your right.
ROTATE = int(os.environ.get("KSP_ROTATE", "270"))

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
# those values avoids dithering. 11 levels: 0-4, 4-8, ..., 36-40, >40,
# from light gray (204) to black.
GRAY_INDEX = [12, 11, 10, 9, 8, 7, 6, 5, 4, 2, 0]   # lightest bar = light gray, no outlines needed
GRAYS = [i * 17 for i in GRAY_INDEX]
# other grays, also exact panel levels
TEXT1 = 34        # secondary text in the landscape design (higher contrast)
TEXT2 = 68        # secondary text
TEXT3 = 102       # tertiary text
RULE = 170        # divider lines
GRID = 204        # grid lines
BAND = 238        # laundry window background


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
    """Cheapest continuous window of `hours` whole hours on `day` (starting on a full hour).

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
        if start.astimezone(TZ).minute != 0:      # whole hours only, e.g. 14-16
            continue
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


def extreme_window(slots: list[Slot], day: date, cheapest: bool, hours: int = 2) -> Window | None:
    """Cheapest or most expensive window of `hours` whole hours over the whole day."""
    day_slots = slots_for_day(slots, day)
    n = hours * 4
    best: Window | None = None
    for i in range(len(day_slots) - n + 1):
        chunk = day_slots[i : i + n]
        start = chunk[0].start
        end = chunk[-1].start + timedelta(minutes=15)
        if start.astimezone(TZ).minute != 0 or end - start != timedelta(minutes=15 * n):
            continue
        avg = sum(s.price for s in chunk) / n
        if best is None or (avg < best.price if cheapest else avg > best.price):
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


def _fonts() -> dict:
    return {
        "title": load_font("bold", 44),
        "small": load_font("regular", 30),
        "axis": load_font("regular", 28),
        "label": load_font("regular", 34),
        "big": load_font("bold", 76),
        "mid": load_font("bold", 42),
        "now": load_font("bold", 92),
        "unit": load_font("regular", 36),
        "axis_bold": load_font("bold", 28),
        "axis_small": load_font("regular", 24),
    }


def _stats(hours: list[Hour], laundry: Window | None, now_l: datetime) -> list[tuple[str, str, str]]:
    hi = max(hours, key=lambda h: h.price)
    lo = min(hours, key=lambda h: h.price)
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
    return stats


def _current(hours: list[Hour], now_l: datetime) -> Hour | None:
    return next((h for h in hours if h.start <= now_l < h.start + timedelta(hours=1)), None)


def scale_top_for(hours: list[Hour]) -> float:
    """Top of the y axis: the smallest of 10/20/30/40 that fits the day's highest price.

    Gray levels always follow absolute prices, so a cheap day is still recognisably
    light even though its bars fill the chart.
    """
    peak = max((h.price for h in hours), default=0)
    for top in (10, 20, 30):
        if peak <= top:
            return float(top)
    return Y_MAX


def _draw_chart(d: ImageDraw.ImageDraw, f: dict, hours: list[Hour], laundry: Window | None,
                now_l: datetime, left: int, right: int, top: int, bottom: int) -> None:
    """Bars, grid, reference lines, laundry band, value labels and hour labels.

    The hour labels and the "now" marker use about 80 px below `bottom`.
    """
    plot_h = bottom - top
    y_max = scale_top_for(hours)
    scale_top = y_max * 1.1                      # a little headroom for value labels
    scale_bottom = -y_max * 0.1 if any(h.price < 0 for h in hours) else 0.0

    def y_of(v: float) -> float:
        v = max(min(v, scale_top), scale_bottom)
        return bottom - (v - scale_bottom) / (scale_top - scale_bottom) * plot_h

    n = max(len(hours), 1)
    slot_w = (right - left) / n

    def x_of(t: datetime) -> float:
        i0 = 0
        for i, h in enumerate(hours):
            if h.start <= t:
                i0 = i
        frac = (t - hours[i0].start) / timedelta(hours=1)
        return left + (i0 + frac) * slot_w

    # laundry window: light band behind the bars
    if laundry is not None and hours and laundry.day == now_l.date():
        lx0, lx1 = x_of(laundry.start), x_of(laundry.end)
        d.rectangle([lx0, top, lx1, bottom], fill=BAND)
        d.text(((lx0 + lx1) / 2, top + 4), "Laundry", font=f["axis"], fill=0, anchor="ma")

    # grid
    step = 2 if y_max <= 10 else 5 if y_max <= 20 else 10
    for v in range(0, int(y_max) + 1, step):
        y = y_of(v)
        d.line([(left, y), (right, y)], fill=GRID, width=1)
        d.text((left - 16, y), str(v), font=f["axis"], fill=TEXT2, anchor="rm")
    # reference lines, only if they fall inside the scale
    for v, fill in ((CHEAP_LINE, TEXT2), (EXPENSIVE_LINE, 0)):
        if v <= y_max:
            dashed_hline(d, left, right, round(y_of(v)), width=3, fill=fill)
            d.text((right, y_of(v) - 6), f"{v:.0f}", font=f["axis"], fill=fill, anchor="rb")

    # bars
    gap = max(4, round(slot_w * 0.16))
    zero_y = y_of(0)
    hi = max(hours, key=lambda h: h.price) if hours else None
    lo = min(hours, key=lambda h: h.price) if hours else None
    cur_idx = None
    for i, h in enumerate(hours):
        x0 = left + i * slot_w + gap / 2
        x1 = left + (i + 1) * slot_w - gap / 2
        cx = (x0 + x1) / 2
        is_now = h.start <= now_l < h.start + timedelta(hours=1)
        if is_now:
            cur_idx = i
        y0, y1 = sorted((y_of(h.price), zero_y))
        if y1 - y0 < 3:            # keep tiny prices visible
            y0 = zero_y - 3
        d.rectangle([x0, y0, x1, y1], fill=gray_for(h.price), outline=0,
                    width=5 if is_now else 2)
        if h.price > y_max:        # clipped
            d.polygon([(cx - 10, y0 - 6), (cx + 10, y0 - 6), (cx, y0 - 20)], fill=0)
            d.text((cx, y0 - 24), f"{h.price:.0f}", font=f["axis"], fill=0, anchor="mb")
        elif h is hi or h is lo or is_now:
            # value labels for the current, highest and lowest hour
            font = f["axis_bold"] if is_now else f["axis_small"]
            d.text((cx, y0 - 6), f"{h.price:.1f}", font=font, fill=0, anchor="mb")
    d.line([(left, zero_y), (right, zero_y)], fill=0, width=3)

    for i, h in enumerate(hours):
        if h.start.hour % 3 == 0 and h.start.minute == 0:
            cx = left + (i + 0.5) * slot_w
            d.text((cx, bottom + 14), f"{h.start.hour:02d}", font=f["axis"], fill=TEXT2, anchor="ma")

    if cur_idx is not None:
        cx = left + (cur_idx + 0.5) * slot_w
        ty = bottom + 52
        d.polygon([(cx, ty), (cx - 14, ty + 22), (cx + 14, ty + 22)], fill=0)


def _draw_legend(d: ImageDraw.ImageDraw, f: dict, left: int, right: int, top: int) -> None:
    block_w = (right - left) / len(GRAYS)
    for i, g in enumerate(GRAYS):
        x0 = left + i * block_w
        d.rectangle([x0, top, x0 + block_w, top + 30], fill=g, outline=0, width=1)
    for v, label in [(0, "0"), (8, "8"), (20, "20"), (40, "40+")]:
        d.text((left + (v / STEP) * block_w, top + 38), label, font=f["axis"], fill=TEXT2, anchor="ma")


def _draw_portrait(img: Image.Image, hours: list[Hour], laundry: Window | None, now_l: datetime) -> None:
    W, H = img.size
    d = ImageDraw.Draw(img)
    f = _fonts()

    d.text((60, 60), "Spot price today", font=f["title"], fill=0)
    d.text((60, 122), "c/kWh incl. VAT", font=f["small"], fill=TEXT3)
    cur = _current(hours, now_l)
    if cur is not None:
        unit_w = d.textlength(" c", font=f["unit"])
        d.text((W - 60, 104), " c", font=f["unit"], fill=TEXT2, anchor="rs")
        d.text((W - 60 - unit_w, 104), fmt_price(cur.price), font=f["now"], fill=0, anchor="rs")
        d.text((W - 60, 140), f"now · {fmt_hm(cur.start)}–{fmt_hm(cur.start + timedelta(hours=1))}",
               font=f["small"], fill=TEXT2, anchor="ra")
    if not hours:
        d.text((W / 2, 560), "No price data for today", font=f["mid"], fill=0, anchor="mm")
        return

    _draw_chart(d, f, hours, laundry, now_l, left=110, right=W - 50, top=240, bottom=1080)

    col_w = (W - 120) / 3
    y0 = 1210
    d.line([(60, y0 - 30), (W - 60, y0 - 30)], fill=RULE, width=2)
    for i, (lab, val, sub) in enumerate(_stats(hours, laundry, now_l)):
        cx = 60 + col_w * (i + 0.5)
        d.text((cx, y0), lab, font=f["label"], fill=TEXT2, anchor="ma")
        if i < 2:
            d.text((cx, y0 + 42), val, font=f["big"], fill=0, anchor="ma")
        else:
            d.text((cx, y0 + 58), val, font=f["mid"], fill=0, anchor="ma")
        d.text((cx, y0 + 132), sub, font=f["small"], fill=TEXT2, anchor="ma")
    for i in (1, 2):
        x = 60 + col_w * i
        d.line([(x, y0), (x, y0 + 170)], fill=RULE, width=2)


# --------------------------------------------------------------------------
# Landscape design (default)
# --------------------------------------------------------------------------

FONT_DIR = Path(__file__).resolve().parent / "fonts"


def _inter(name: str, size: int) -> ImageFont.FreeTypeFont:
    path = FONT_DIR / f"{name}.ttf"
    if path.exists():
        return ImageFont.truetype(str(path), size)
    return load_font("bold" if "Bold" in name or "Semi" in name else "regular", size)


def chart_top_for(hours: list[Hour]) -> float:
    """Top of the y axis: 20 c/kWh on ordinary days; on expensive days the next
    multiple of 5 above the highest price (like Helen's app)."""
    peak = max((h.price for h in hours), default=0)
    if peak <= 20:
        return 20.0
    return float(math.ceil(peak / 5) * 5)


def level_for(price: float) -> tuple[str, str]:
    """(label, style) for the current price; style is 'light', 'mid' or 'dark'."""
    if price < CHEAP_LINE:
        return "CHEAP", "light"
    if price < EXPENSIVE_LINE:
        return "MODERATE", "mid"
    if price < 30:
        return "EXPENSIVE", "dark"
    return "VERY EXPENSIVE", "dark"


def _icon_washer(d: ImageDraw.ImageDraw, x: float, y: float, s: float, fill: int = 0) -> None:
    """Washing machine icon, s = size in px, (x, y) = top-left."""
    w = max(2, round(s / 14))
    d.rounded_rectangle([x, y, x + s, y + s], radius=s * 0.16, outline=fill, width=w)
    d.line([(x + w, y + s * 0.26), (x + s - w, y + s * 0.26)], fill=fill, width=w)
    r = s * 0.045
    for cx in (x + s * 0.18, x + s * 0.32):
        d.ellipse([cx - r, y + s * 0.13 - r, cx + r, y + s * 0.13 + r], fill=fill)
    cx, cy, R = x + s / 2, y + s * 0.62, s * 0.25
    d.ellipse([cx - R, cy - R, cx + R, cy + R], outline=fill, width=w)
    R2 = R * 0.55
    d.arc([cx - R2, cy - R2, cx + R2, cy + R2], start=200, end=320, fill=fill, width=w)


def _icon_arrow(d: ImageDraw.ImageDraw, x: float, y: float, s: float, up: bool, fill: int = 0) -> None:
    """Simple arrow in an s x s box."""
    w = max(4, round(s / 8))
    cx = x + s / 2
    top, bot = y + s * 0.12, y + s * 0.88
    if up:
        d.line([(cx, bot), (cx, top + w)], fill=fill, width=w)
        d.line([(x + s * 0.2, y + s * 0.42), (cx, top), (x + s * 0.8, y + s * 0.42)], fill=fill, width=w, joint="curve")
    else:
        d.line([(cx, top), (cx, bot - w)], fill=fill, width=w)
        d.line([(x + s * 0.2, y + s * 0.58), (cx, bot), (x + s * 0.8, y + s * 0.58)], fill=fill, width=w, joint="curve")


def _icon_washer_simple(d: ImageDraw.ImageDraw, x: float, y: float, s: float, fill: int = 0) -> None:
    """Minimal washing machine: rounded square and a round door."""
    w = max(4, round(s / 10))
    d.rounded_rectangle([x, y, x + s, y + s], radius=s * 0.2, outline=fill, width=w)
    cx, cy, r = x + s / 2, y + s * 0.56, s * 0.24
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=fill, width=w)
    d.ellipse([x + s * 0.2 - w / 2, y + s * 0.18 - w / 2, x + s * 0.2 + w / 2, y + s * 0.18 + w / 2], fill=fill)


def _icon_peak(d: ImageDraw.ImageDraw, x: float, y: float, s: float, up: bool, fill: int = 0) -> None:
    """A small line chart with its peak (or valley) marked by a dot."""
    w = max(4, round(s / 9))
    if up:
        pts = [(x, y + s * 0.85), (x + s * 0.32, y + s * 0.55), (x + s * 0.55, y + s * 0.2),
               (x + s * 0.78, y + s * 0.6), (x + s, y + s * 0.5)]
        dot = pts[2]
    else:
        pts = [(x, y + s * 0.15), (x + s * 0.3, y + s * 0.4), (x + s * 0.55, y + s * 0.8),
               (x + s * 0.8, y + s * 0.45), (x + s, y + s * 0.5)]
        dot = pts[2]
    d.line(pts, fill=fill, width=w, joint="curve")
    r = s * 0.12
    d.ellipse([dot[0] - r, dot[1] - r, dot[0] + r, dot[1] + r], fill=fill)


def _icon_swatch(d: ImageDraw.ImageDraw, x: float, y: float, s: float, up: bool, fill: int = 0) -> None:
    """Same frame as the washer icon, with one bar inside: tall = highest, short = lowest."""
    w = max(3, round(s / 12))
    d.rounded_rectangle([x, y, x + s, y + s], radius=s * 0.2, outline=fill, width=w)
    bw = s * 0.26
    bh = s * (0.52 if up else 0.16)
    bx = x + (s - bw) / 2
    base = y + s * 0.76
    d.rounded_rectangle([bx, base - bh, bx + bw, base], radius=min(bw, bh) * 0.35, fill=fill)


def _hh(t: datetime) -> str:
    return t.astimezone(TZ).strftime("%H")


def _draw_landscape(img: Image.Image, hours: list[Hour], laundry: Window | None, now_l: datetime,
                    low: Window | None = None, high: Window | None = None) -> None:
    """Current price on the left, today's chart on the right.

    Layout grid (1448 x 1072):
      - top and bottom margins are equal (84 px): kickers start at y=84, the x-axis
        labels end ~84 px above the bottom edge
      - left column: the upper block (price) and the icons share the left edge x=64;
        the lower block's text starts at x=124, its block is centered vertically
        between the label pill and the bottom edge
      - chart: x 530-1384
    """
    W, H = img.size
    d = ImageDraw.Draw(img)
    # sizes tuned on the device: a Kindle is read from further away than a phone
    F = {
        "hero": _inter("InterDisplay-Bold", 212),
        "unit": _inter("Inter-Medium", 32),
        "kicker": _inter("Inter-SemiBold", 28),
        "pill": _inter("Inter-Bold", 26),
        "stat": _inter("InterDisplay-SemiBold", 62),
        "sub": _inter("Inter-Medium", 30),
        "axis": _inter("Inter-Medium", 26),
        "tag": _inter("Inter-Bold", 24),
        "now": _inter("Inter-Bold", 26),
    }
    M = 64
    TOP = 84                     # top line for kickers
    LX_ICON = M                  # icons and the upper block share the left edge
    LX = M + 60                  # text of the lower block
    if not hours:
        d.text((W / 2, H / 2), "No price data for today", font=F["stat"], fill=0, anchor="mm")
        return

    CHART_LEFT = 530
    PLOT_BOTTOM = 940            # chart baseline; x labels below end ~84 px above the edge
    ROW_STEP = 166
    # lower block: centered between the label pill and the bottom edge,
    # so it has the same space above and below (and sits a little above the x axis)
    block_h = 2 * ROW_STEP + 78 + 24                # first value top .. last detail bottom
    pill_bottom = TOP + 352
    ROW_Y0 = round(pill_bottom + (H - pill_bottom - block_h) / 2)

    def span(w: Window) -> str:
        return f"{_hh(w.start)} – {_hh(w.end)}"

    # ======================= left column =======================
    lx = M                       # upper block: kicker, price, unit, label
    cur = _current(hours, now_l)
    if cur is not None:
        d.text((lx, TOP), f"NOW  {_hh(cur.start)} – {_hh(cur.start + timedelta(hours=1))}",
               font=F["kicker"], fill=TEXT1, anchor="lt")
        hero = F["hero"]
        size = 212
        while d.textlength(fmt_price(cur.price), font=hero) > CHART_LEFT - 90 - lx and size > 140:
            size -= 4
            hero = _inter("InterDisplay-Bold", size)
        d.text((lx - 7, TOP + 228), fmt_price(cur.price), font=hero, fill=0, anchor="ls")
        d.text((lx, TOP + 250), "c/kWh incl. VAT", font=F["unit"], fill=TEXT1, anchor="lt")
        label, style = level_for(cur.price)
        tw = d.textlength(label, font=F["pill"])
        box = [lx, TOP + 306, lx + tw + 40, TOP + 352]
        mid = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
        if style == "dark":
            d.rounded_rectangle(box, radius=23, fill=0)
            d.text(mid, label, font=F["pill"], fill=255, anchor="mm")
        elif style == "mid":
            d.rounded_rectangle(box, radius=20, fill=GRID)
            d.text(mid, label, font=F["pill"], fill=0, anchor="mm")
        else:
            d.rounded_rectangle(box, radius=20, outline=0, width=3)
            d.text(mid, label, font=F["pill"], fill=0, anchor="mm")

    # stats: icon, big value, one line of detail; the last row ends on the chart baseline
    icon_s = 40
    tx = LX
    style = os.environ.get("KSP_ICONS", "arrow")
    if style == "peak":
        hi_icon = lambda y: _icon_peak(d, LX_ICON, y, icon_s, up=True)
        lo_icon = lambda y: _icon_peak(d, LX_ICON, y, icon_s, up=False)
    elif style == "arrow":
        hi_icon = lambda y: _icon_arrow(d, LX_ICON, y, icon_s, up=True)
        lo_icon = lambda y: _icon_arrow(d, LX_ICON, y, icon_s, up=False)
    else:
        hi_icon = lambda y: _icon_swatch(d, LX_ICON, y, icon_s, up=True)
        lo_icon = lambda y: _icon_swatch(d, LX_ICON, y, icon_s, up=False)
    rows = []
    if high is not None:
        rows.append((lambda y: hi_icon(y),
                     fmt_price(high.price), f"Highest 2 h · {span(high)}", "stat"))
    if low is not None:
        rows.append((lambda y: lo_icon(y),
                     fmt_price(low.price), f"Lowest 2 h · {span(low)}", "stat"))
    if laundry is not None:
        label = "Tomorrow" if laundry.day != now_l.date() else "Laundry"
        rows.append((lambda y: _icon_washer_simple(d, LX_ICON, y, icon_s),
                     span(laundry), f"{label} · avg {fmt_price(laundry.price)} c", "stat"))
    else:
        rows.append((lambda y: _icon_washer_simple(d, LX_ICON, y, icon_s, fill=TEXT3),
                     "—", "Laundry · no window left today", "stat"))
    for i, (icon, big, sub, font) in enumerate(rows):
        y = ROW_Y0 + i * ROW_STEP
        d.text((tx - 3, y), big, font=F[font], fill=0, anchor="lt")
        # center the icon on the digits' visual middle (cap height), not the text box
        _, gy0, _, gy1 = d.textbbox((tx, y), "0", font=F[font], anchor="lt")
        icon((gy0 + gy1) / 2 - icon_s / 2)
        sub_font = F["sub"]
        max_w = CHART_LEFT - 90 - tx          # stay clear of the chart's axis labels
        size = 30
        while d.textlength(sub, font=sub_font) > max_w and size > 20:
            size -= 1
            sub_font = _inter("Inter-Medium", size)
        d.text((tx, y + 78), sub, font=sub_font, fill=TEXT1, anchor="lt")

    # ======================= chart =======================
    left, right = CHART_LEFT, W - M
    top, bottom = TOP + 120, PLOT_BOTTOM
    y_max = chart_top_for(hours)
    lo_v = min(h.price for h in hours)
    scale_top = y_max
    scale_bottom = 0.0 if lo_v >= 0 else -math.ceil(-lo_v / 5) * 5
    plot_h = bottom - top

    def y_of(v: float) -> float:
        v = max(min(v, scale_top), scale_bottom)
        return bottom - (v - scale_bottom) / (scale_top - scale_bottom) * plot_h

    n = len(hours)
    slot = (right - left) / n

    def x_at(t: datetime) -> float:
        """x of a point in time (hour boundaries map to bar edges)."""
        for i, h in enumerate(hours):
            if h.start <= t < h.start + timedelta(hours=1):
                return left + (i + (t - h.start) / timedelta(hours=1)) * slot
        return right if t >= hours[-1].start else left

    # date of the chart, so a stale lock screen is obvious (English names, locale-independent)
    day = hours[0].start.astimezone(TZ)
    wd = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")[day.weekday()]
    mon = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")[day.month - 1]
    d.text((left, TOP), f"{wd} {day.day} {mon} · c/kWh", font=F["kicker"], fill=TEXT1, anchor="lt")

    # grid
    gstep = 5 if y_max <= 25 else 10
    ticks = list(range(int(scale_bottom), int(y_max) + 1, gstep))
    if int(y_max) not in ticks:
        ticks.append(int(y_max))
    for v in ticks:
        yy = y_of(v)
        d.line([(left, yy), (right, yy)], fill=GRID if v else 0, width=1 if v else 2)
        d.text((left - 16, yy), f"{v}", font=F["axis"], fill=TEXT1, anchor="rm")

    # cheapest / most expensive 2 h: background bands behind the bars.
    # LOW is always the lightest gray (lighter than any bar). HIGH is a few levels
    # lighter than the bars inside it, but never as light as LOW, so the two differ.
    def band_gray(w: Window, is_low: bool) -> int:
        if is_low:
            return 14 * 17                                   # 238
        inside = [h for h in hours if w.start <= h.start < w.end]
        lightest = max((gray_for(h.price) // 17 for h in inside), default=12)
        return max(12, min(13, lightest + 4)) * 17           # 204 or 221

    tags = []
    for w, tag, is_low in ((low, "LOW", True), (high, "HIGH", False)):
        if w is None:
            continue
        bx0, bx1 = x_at(w.start), x_at(w.end)
        d.rectangle([bx0, top, bx1, bottom], fill=band_gray(w, is_low))
        tags.append(((bx0 + bx1) / 2, tag))

    # current hour: dashed line on the left edge of its bar, NOW label above the chart
    if cur is not None:
        nx = left + hours.index(cur) * slot
        y = top - 50
        while y < bottom:
            d.line([(nx, y), (nx, min(y + 10, bottom))], fill=0, width=2)
            y += 18
        lab = "NOW"
        tw = d.textlength(lab, font=F["now"])
        bx0 = min(max(nx - tw / 2 - 14, left - 20), right - tw - 28)
        d.rounded_rectangle([bx0, top - 92, bx0 + tw + 30, top - 50], radius=21, fill=0)
        d.text((bx0 + 15 + tw / 2, top - 71), lab, font=F["now"], fill=255, anchor="mm")

    for tx, tag in tags:
        tw = d.textlength(tag, font=F["tag"])
        d.rectangle([tx - tw / 2 - 6, top - 36, tx + tw / 2 + 6, top - 4], fill=255)
        d.text((tx, top - 8), tag, font=F["tag"], fill=TEXT1, anchor="mb")

    # bars: no outlines, gray = absolute price level
    zero_y = y_of(0)
    bar_w = slot * 0.68
    for i, h in enumerate(hours):
        cx = left + (i + 0.5) * slot
        y0, y1 = sorted((y_of(h.price), zero_y))
        if y1 - y0 < 4:
            y0 = zero_y - 4 if h.price >= 0 else y0
            y1 = max(y1, y0 + 4)
        r = min(7, bar_w / 3, (y1 - y0) / 2)
        top_round = h.price >= 0
        d.rounded_rectangle([cx - bar_w / 2, y0, cx + bar_w / 2, y1], radius=r, fill=gray_for(h.price),
                            corners=(top_round, top_round, not top_round, not top_round))
        if h.price > scale_top:          # off the scale: value on top
            d.text((cx, y0 + 6), f"{h.price:.0f}", font=F["tag"], fill=255, anchor="mt")
    d.line([(left, zero_y), (right, zero_y)], fill=0, width=2)

    # x axis: ticks and labels on hour boundaries, every 3 hours, evenly spaced
    for k in range(0, n + 1):
        t_hour = (hours[0].start + timedelta(hours=k)).hour if k < n else 24
        x = left + k * slot
        if t_hour % 3 == 0:
            d.line([(x, zero_y + 2), (x, zero_y + 12)], fill=TEXT1, width=2)
            d.text((x, bottom + 22), f"{t_hour:02d}", font=F["axis"], fill=TEXT1, anchor="mt")


def render(hours: list[Hour], laundry: Window | None, now: datetime, out_path: Path,
           layout: str = LAYOUT, low: Window | None = None, high: Window | None = None,
           preview_path: Path | None = None) -> None:
    """Draw one lock-screen image. The saved PNG is always 1072x1448 (portrait),
    as the Kindle expects; the landscape layout is drawn sideways and rotated."""
    now_l = now.astimezone(TZ)
    if layout == "landscape":
        img = Image.new("L", (HEIGHT, WIDTH), 255)
        _draw_landscape(img, hours, laundry, now_l, low=low, high=high)
        if preview_path is not None:          # upright copy for the web page
            preview_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(preview_path, optimize=True)
        img = img.rotate(ROTATE, expand=True)
    else:
        img = Image.new("L", (WIDTH, HEIGHT), 255)
        _draw_portrait(img, hours, laundry, now_l)
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
        low = extreme_window(slots, day, cheapest=True)
        high = extreme_window(slots, day, cheapest=False)
        for h in hours:
            name = f"{h.start:%Y%m%d-%H}.png"
            if name in names:          # repeated hour on the DST day: keep the first
                continue
            render(hours, laundry_window(slots, h.start), h.start, frames_dir / name,
                   low=low, high=high)
            names.append(name)
    (frames_dir / "manifest.txt").write_text("\n".join(names) + "\n")
    return names


def write_index(out: Path, now: datetime) -> None:
    """Small web page for GitHub Pages: the upright preview and links to the files."""
    img = "preview.png" if (out / "preview.png").exists() else "kindle.png"
    (out / "index.html").write_text(f"""<!doctype html>
<html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>kindle-spot-price</title>
<body style="font-family:system-ui,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;color:#222">
<h1 style="font-size:1.3rem">Finnish spot price · Kindle lock screen</h1>
<p>Generated {now.astimezone(TZ):%Y-%m-%d %H:%M} (Helsinki).
The image below is the current hour's lock screen, shown upright.</p>
<img src="{img}" alt="Today's lock screen" style="width:100%;border:1px solid #ddd">
<p><a href="kindle.png">kindle.png</a> (rotated, as stored on the Kindle) ·
<a href="frames/manifest.txt">hourly frames</a> ·
<a href="prices.json">prices.json</a> ·
<a href="https://github.com/kuailoy/kindle-spot-price">source</a></p>
</body></html>
""")


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
    render(hours, laundry, now, out / "kindle.png",
           low=extreme_window(slots, today, cheapest=True),
           high=extreme_window(slots, today, cheapest=False),
           preview_path=out / "preview.png")
    write_index(out, now)
    (out / "prices.json").write_text(json.dumps(summary(hours, laundry, now), ensure_ascii=False, indent=2))
    print(f"wrote {out / 'kindle.png'} ({len(hours)} hours)")

    if not args.no_frames:
        names = render_frames(slots, out / "frames", now)
        print(f"wrote {len(names)} frames to {out / 'frames'}")
    return 0 if hours else 1


if __name__ == "__main__":
    sys.exit(main())
