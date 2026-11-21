# How it works

## Data

- Source: `https://api.spot-hinta.fi/TodayAndDayForward?region=FI&priceResolution=15`
- Each item has `DateTime` (ISO 8601 with offset), `PriceNoTax` and `PriceWithTax` in **EUR/kWh**.
  The renderer uses `PriceWithTax × 100` → c/kWh incl. VAT (25.5 %).
- Since 1 October 2025 the day-ahead market uses 15-minute periods. The chart shows the
  hourly average of the four quarters (the same way Helen calculates hourly prices); the
  laundry window is searched on the 15-minute data, so it can start at e.g. 13:15.
- Hours are grouped by their UTC hour, so DST days produce 23 or 25 bars instead of
  merging the repeated hour.
- Tomorrow's prices are published around 14:00 Finnish time.

## Hourly frames

Prices for a day are published around 14:00 the day before and do not change, so the
renderer draws **one image per local hour** for today and, once published, tomorrow:

```
frames/20261121-00.png … frames/20261122-23.png   (up to 48 × ~25 KB)
frames/manifest.txt                                (list of file names)
```

Each frame marks its own hour as "now" and shows the laundry window for the rest of
that day. The Kindle only needs the network to download a new batch; switching images
every hour is a local file copy. On the autumn DST day the repeated hour shares one file.

## Image

| Property | Value | Why |
|---|---|---|
| Size | 1072 × 1448 | native Paperwhite 3 resolution (from `eips -i`) |
| Format | 8-bit grayscale PNG | same as the stock `bg_ssNN.png` files |
| Gray values | multiples of 17 | the panel has 16 levels; exact values avoid dithering |
| Scale | 0–40 c/kWh + headroom | fixed, so days are comparable; higher bars are clipped with a value label |

Gray mapping, one level per 4 c/kWh:

```
price  0-4  4-8  8-12 12-16 16-20 20-24 24-28 28-32 32-36 36-40  40+
level   15   14    12    11     9     8     6     5     3     2    0   (×17)
```

## The Kindle lock screen

Findings from `kindle/ss_diag.sh` on a Paperwhite 3, firmware 5.16.2.1.1:

- Stock images: `/usr/share/blanket/screensaver/bg_ss00.png` … `bg_ss19.png`
  (plus `bg_kids_*` for Kindle Kids and `bg_kcblackbackground.jpg`).
  With "Display cover" off, the lock screen picks one of the `bg_ssNN` files.
- `/` is ext3 mounted **read-only**; `/mnt/us` (USB storage) is a FUSE mount.
- Available: `curl` 7.86 with OpenSSL (HTTPS works), `crond`, `eips`, `lipc-*`.
  Not available: Python.
- The system crontab lives on the read-only root, so the updater is a simple background
  loop instead of a cron job.

### Why a bind mount

Most guides remount `/` read-write and overwrite the stock images. A wrong file there can
leave the lock screen broken until the files are fixed by hand. Instead `ss_on.sh`:

1. copies the image 20 times as `bg_ss00.png` … `bg_ss19.png` into `/var/local/sslive/live`
   (internal storage, still available while the Kindle is in USB mode, unlike `/mnt/us`);
2. `mount --bind /var/local/sslive/live /usr/share/blanket/screensaver`;
3. asks the lock-screen module to reload (`lipc-set-prop com.lab126.blanket unload/load screensaver`).

The stock files are untouched underneath. `umount` or a reboot brings them back.

### The updater

`ss_on.sh` writes `/var/local/sslive/sslive_daemon.sh` (so it keeps working when `/mnt/us`
is unavailable in USB mode) and starts two small loops. Both are frozen while the Kindle is
suspended and cost nothing then.

| Loop | Trigger | Does |
|---|---|---|
| `timer` | sleeps until the next full hour (at most 15 min at a time) | `tick` |
| `events` | `lipc-wait-event -m com.lab126.powerd outOfScreenSaver,wakeupFromSuspend` | `tick` 2 s after wake-up |

`tick`:

1. **Download if needed** – when the current hour's frame is missing, or after 15:00 when
   tomorrow's frames are not there yet, and Wi-Fi is connected (`lipc-get-prop
   com.lab126.wifid cmState`). At most one attempt per 30 minutes. Fetches `manifest.txt`,
   downloads only missing frames, validates each one, deletes frames from previous days.
2. **Show the current hour** – if `frames/$(date +%Y%m%d-%H).png` is not the one already
   shown, copy it into the 20 slots.

A lock directory prevents the two loops from running `tick` at the same time.

The 15-minute cap on the timer is a safety net: a `sleep` that started before a suspend
continues counting after wake-up, so without the cap the next hourly switch could be late
if the wake-up event is missed.

**Time zone note:** the test Kindle reports `EEST` in November although Finland is on EET;
the wall-clock time it shows is still correct. The updater therefore picks frames by the
local time from `date`, never by UTC.

Every downloaded file is checked before use (PNG signature and 1072×1448 size in the
IHDR header, using only busybox tools), so a failed or partial download never
replaces a working image.

### Limits of the current version

- While suspended nothing runs, so the lock screen shows the hour in which the Kindle was
  locked. The hour printed in the top-right corner shows which one.
- The bind mount and the updater do not survive a reboot; run **Lockscreen ON** again.

### Next: timed wake-up

Because the frames are already on the device, a wake-up does not need Wi-Fi: set an RTC
wake-up before suspend, on wake copy the current frame and draw it with `eips -g`, then
suspend again. Rough estimate: a few seconds at ~100–200 mA per wake-up, i.e. about
0.5 % of the battery per day for hourly wake-ups (to be measured by logging the battery
level). A watchdog must make sure the device always goes back to sleep.
