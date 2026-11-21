# Next step: refresh the lock screen while the Kindle sleeps

Status: **implemented** in `kindle/scriptlets/ss_on.sh`. The current description is in
[update-strategy.md](update-strategy.md); this file keeps the original plan and test notes. The current version only switches images while the
Kindle is awake; once it is locked, the lock screen stays on the hour in which it was locked.

## Goal

Every hour between 07:00 and 23:00 the Kindle wakes up for a few seconds, shows the image
for the new hour and goes back to sleep. No Wi-Fi is used, because the images for the day
are already on the device.

## Decisions so far

- **Keep rendering 24 images per day.** Dropping the night hours saves under 200 KB and
  would need extra logic (e.g. reading at 01:00 would look like a missing image).
- **Quiet hours instead:** no wake-ups between `QUIET_START=23` and `QUIET_END=7`.
  The first wake-up is at 07:00. 16 wake-ups a day instead of 24.
- Quiet hours and the wake-up interval go into a config file in `/mnt/us/sslive/`,
  so they can be changed without editing the scripts.
- The 22:00 and 23:00 images already show tomorrow's laundry window, so the overnight
  lock screen is still useful in the morning.

## Planned design

1. When the Kindle is about to suspend (powerd event, e.g. `readyToSuspend`), set an RTC
   wake-up for the next full hour, or for `QUIET_END` if the next hour is inside the quiet
   period.
2. On a timed wake-up while the lock screen is shown:
   - copy the current hour's frame into the lock-screen slots;
   - draw it directly with `eips -g <frame> -f` (full refresh), because the lock screen
     is already on screen and will not reload by itself;
   - log the battery level;
   - let the device suspend again.
3. **Watchdog:** whatever happens, the device must go back to sleep within ~30 s of a
   timed wake-up. A device that stays awake drains the battery in a day or two.
4. Do not start Wi-Fi on timed wake-ups.

## Verified on the device (PW3, firmware 5.16.2.1.1)

Tools: `kindle/tools/wake_diag.sh` (read-only) and `kindle/tools/wake_test.sh` (one-shot test).

- **Power events** after pressing the power button:
  `goingToScreenSaver` → about 60 s later a series of `readyToSuspend <n>` →
  `suspending "mem"`; on wake-up `wakeupFromSuspend <seconds slept>` → `resuming`;
  unlocking gives `outOfScreenSaver` / `exitingScreenSaver`.
- **powerd's `rtcWakeup` property** accepts a value but did **not** wake the device.
- **Writing the alarm directly to `/sys/class/rtc/rtc1/wakealarm` works**: target 19:35:45,
  woke up 19:35:46. It has to be (re)written on `readyToSuspend`; after the suspend it is cleared.
- **Redrawing on wake-up works**: `eips -f -g <frame.png>` while the lock screen is shown,
  about 1 s.
- **Going back to sleep happens by itself**: after the timed wake-up powerd waited about 60 s,
  sent `readyToSuspend` again and suspended ~95 s after waking. No watchdog was needed in the test,
  but the awake time per wake-up is ~95 s, not a few seconds.

## Expected cost

The device stays awake ~95 s per wake-up (mostly idle, screen not refreshing), so 16 wake-ups
mean roughly 25 minutes awake per day. Expected to be on the order of 1 % of the battery per day;
to be confirmed with the battery log. Shortening the awake time (e.g. asking for an earlier
suspend) is a possible later optimisation.

## Test plan

1. Run the diagnostic and decide on the wake-up mechanism.
2. Prototype with a short interval (e.g. 5 minutes) and watch the log.
3. Switch to hourly + quiet hours, leave it for 2–3 days, compare battery drain with the
   current version.
