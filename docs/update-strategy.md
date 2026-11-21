# Update strategy

How a new image gets from the price API onto a Kindle that is locked most of the day.
Everything here was measured on a Kindle Paperwhite 3, firmware 5.16.2.1.1.

## The idea in one paragraph

Day-ahead prices are fixed the afternoon before, so every hourly image can be rendered in
advance. The cloud renders a day's images once, the Kindle downloads them once (in the evening,
on Wi-Fi), and from then on it only needs to **copy the right file at the right hour**, which
needs no network. While the Kindle is locked, a hardware alarm wakes it briefly at each full
hour to do that copy and redraw the screen.

## 1. Cloud: render ahead

| When (Finnish time) | What |
|---|---|
| ~14:00 | Nord Pool publishes tomorrow's prices |
| 15:00, 16:00, 17:00, 20:00 (one hour later in summer) | GitHub Actions renders `frames/YYYYMMDD-HH.png` for today and tomorrow (up to 48 images, ~30 KB each) plus `frames/manifest.txt`, publishes them on GitHub Pages |

Each frame is complete for its hour: the "now" marker, the current price and the laundry
window for the rest of that day are already drawn in.

## 2. Kindle awake: download and switch

`ss_on.sh` starts a small updater (`/var/local/sslive/sslive_daemon.sh`) with two loops.
Both are frozen while the Kindle sleeps and cost nothing then.

- **Download** only when needed: the current hour's image is missing, or it is after 18:00 and
  tomorrow's images are not there yet. Needs Wi-Fi; at most one attempt every 30 minutes; waits
  up to 30 s for Wi-Fi to reconnect after a wake-up. Downloads only missing files, checks each
  one (PNG signature and 1072 × 1448 size), deletes the previous day's.
- **Switch** at every full hour and right after unlocking: copy the current hour's frame into
  the 20 lock-screen slots (`bg_ss00.png` … `bg_ss19.png`) of the bind-mounted folder.
- Tapping **Lockscreen ON** re-downloads everything (useful after a design change).

## 3. Kindle locked: timed wake-up

### What the power daemon does

Events from `com.lab126.powerd` (logged with `kindle/tools/wake_diag.sh`):

```
press power button     goingToScreenSaver
~60 s later            readyToSuspend 10, 8, 7, ... 1      (several, a few seconds apart)
                       suspending "mem"                     deep sleep
alarm or button        wakeupFromSuspend <seconds slept>
                       resuming
unlock                 outOfScreenSaver, exitingScreenSaver
```

### What we do

| Event | Action |
|---|---|
| `readyToSuspend` | write the alarm: next full hour + 30 s, or `QUIET_END:00:30` if the next hour is in the quiet hours. Re-written on every `readyToSuspend`; a suspend clears it. |
| `wakeupFromSuspend` | if the time matches our alarm (±2 min): copy the hour's frame into the slots and redraw with `eips -f -g` (~1 s). Otherwise the user woke it up: nothing special. |
| `outOfScreenSaver` | normal update (download if needed, switch) |

The device then goes back to sleep on its own; no extra code is needed for that.

### How the alarm is set

- powerd's `rtcWakeup` property is accepted but **did not wake the device** (test 1).
- Writing the alarm directly works: `echo 0 > /sys/class/rtc/rtc1/wakealarm`, then
  `echo <epoch seconds> > /sys/class/rtc/rtc1/wakealarm`. Target 19:35:45, woke up 19:35:46
  (test 2). The same approach is used by the kindle-dash project.
- Hour boundaries are computed in UTC epoch seconds; Finnish time is a whole number of hours
  from UTC, so a UTC hour boundary is also a local one. The Kindle labels its clock `EEST` in
  November, but its wall-clock time is right, so frames are picked with the local `date`.

### Settings: `/mnt/us/sslive/config.txt`

```
WAKE=1          # 0 turns timed wake-ups off
QUIET_START=23  # no wake-ups from 23:00 ...
QUIET_END=7     # ... to 07:00; first wake-up at 07:00
```

Read at every lock, no restart needed. **Lockscreen OFF** clears the alarm.

## Known limitation: awake time per wake-up

The redraw takes about 1 second and the screen stays on the lock screen. But powerd keeps the
device awake for about **95 seconds** after a timed wake-up before it suspends again (the same
~60 s wait as after pressing the power button, plus its countdown). Measured: woke 19:35:46,
suspended 19:37:21.

With 16 wake-ups a day that is roughly 25 minutes of idle awake time, estimated at around 1 %
of the battery per day. Accepted for now. The log records the battery level at every timed
wake-up (`timed wake: showing … battery N%`), so the real cost can be measured. A possible
later optimisation is to ask for an earlier suspend.

## Tools

| Script | Purpose |
|---|---|
| `kindle/tools/ss_diag.sh` | lock-screen files, tools, screen size (read-only) |
| `kindle/tools/wake_diag.sh` | powerd properties, RTC devices, 4 minutes of power events (read-only) |
| `kindle/tools/wake_test.sh` | one-shot wake-up test: arms rtc1, redraws once, logs timing and battery |
