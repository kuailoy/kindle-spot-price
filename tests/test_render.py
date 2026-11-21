"""Tests for the price logic. Run with:  python -m pytest -q"""

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "render"))

import render  # noqa: E402
from render import TZ, Slot  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "sample-winter.json"


def make_day(day: date, prices_per_hour):
    """Build 15-min slots from a list of hourly prices (4 equal slots each)."""
    start = datetime.combine(day, datetime.min.time(), TZ)
    slots = []
    for h, p in enumerate(prices_per_hour):
        for q in range(4):
            slots.append(Slot(start + timedelta(hours=h, minutes=15 * q), p))
    return slots


def test_parse_converts_to_cents():
    raw = [{"DateTime": "2026-11-21T00:00:00+02:00", "PriceWithTax": 0.05}]
    (s,) = render.parse_slots(raw)
    assert abs(s.price - 5.0) < 1e-9


def test_hourly_average_of_quarters():
    day = date(2026, 11, 21)
    start = datetime.combine(day, datetime.min.time(), TZ)
    slots = [Slot(start + timedelta(minutes=15 * q), p) for q, p in enumerate([1, 2, 3, 6])]
    (hour,) = render.hourly_averages(slots)
    assert hour.price == 3.0
    assert hour.start == start


def test_dst_fall_back_day_has_25_hours():
    day = date(2026, 10, 25)  # EEST -> EET
    start = datetime.combine(day, datetime.min.time(), TZ)
    slots = []
    t = start
    while t.astimezone(TZ).date() == day:
        slots.append(Slot(t, 5.0))
        t = (t.astimezone(render.timezone.utc) + timedelta(minutes=15)).astimezone(TZ)
    hours = render.hourly_averages(render.slots_for_day(slots, day))
    assert len(hours) == 25


def test_best_window_respects_daytime_limits():
    day = date(2026, 11, 21)
    prices = [1] * 7 + [10] * 6 + [3, 3] + [10] * 9   # cheapest daytime: 13-15
    win = render.best_window(make_day(day, prices), day)
    assert win.start.hour == 13 and win.end.hour == 15
    assert win.price == 3


def test_best_window_skips_the_past():
    day = date(2026, 11, 21)
    prices = [10] * 8 + [2, 2] + [10] * 6 + [4, 4] + [10] * 6
    slots = make_day(day, prices)
    now = datetime.combine(day, datetime.min.time(), TZ).replace(hour=11)
    win = render.laundry_window(slots, now)
    assert win.start.hour == 16   # 08-10 already passed


def test_falls_back_to_tomorrow_late_in_the_evening():
    data = render.parse_slots(json.loads(FIXTURE.read_text()))
    now = datetime(2026, 11, 21, 21, 30, tzinfo=TZ)
    win = render.laundry_window(data, now)
    assert win is not None and win.day == date(2026, 11, 22)


def test_gray_levels():
    assert render.gray_for(0) == 255
    assert render.gray_for(3.9) == 255
    assert render.gray_for(4) < 255
    assert render.gray_for(55) == 0
    assert all(g % 17 == 0 for g in render.GRAYS)


def test_render_output_format(tmp_path):
    rc = render.main(["--input", str(FIXTURE), "--now", "2026-11-21T09:40", "--out-dir", str(tmp_path)])
    assert rc == 0
    from PIL import Image
    im = Image.open(tmp_path / "kindle.png")
    assert im.size == (1072, 1448) and im.mode == "L"
    summary = json.loads((tmp_path / "prices.json").read_text())
    assert len(summary["hours"]) == 24


def test_frames_cover_today_and_tomorrow(tmp_path):
    render.main(["--input", str(FIXTURE), "--now", "2026-11-21T15:00", "--out-dir", str(tmp_path)])
    frames = tmp_path / "frames"
    names = (frames / "manifest.txt").read_text().split()
    assert len(names) == 48
    assert names[0] == "20261121-00.png" and names[-1] == "20261122-23.png"
    assert all((frames / n).exists() for n in names)


def test_frames_only_today_when_tomorrow_unknown(tmp_path):
    raw = json.loads(FIXTURE.read_text())[:96]   # today only
    f = tmp_path / "today.json"
    f.write_text(json.dumps(raw))
    render.main(["--input", str(f), "--now", "2026-11-21T10:00", "--out-dir", str(tmp_path / "o")])
    names = (tmp_path / "o" / "frames" / "manifest.txt").read_text().split()
    assert len(names) == 24
