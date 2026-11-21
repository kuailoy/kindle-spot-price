# Next step: refresh the lock screen while the Kindle sleeps

Status: **planned, not implemented.** The current version only switches images while the
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

## To verify on the device first (read-only diagnostic)

- Which powerd properties/events exist on firmware 5.16.2.1.1
  (`lipc-probe com.lab126.powerd`), e.g. an RTC wake-up property and the suspend events.
- Whether `/sys/class/rtc/rtc0/wakealarm` (or the mxc RTC equivalent) is present.
- Whether `eips -g` can draw over the lock screen without the system redrawing it.
- How long a timed wake-up takes until the device is suspended again.

## Expected cost

Rough estimate: a few seconds at ~100–200 mA per wake-up → about 0.3–0.5 % of the battery
per day with 16 wake-ups. To be confirmed with the battery log after a few days.

## Test plan

1. Run the diagnostic and decide on the wake-up mechanism.
2. Prototype with a short interval (e.g. 5 minutes) and watch the log.
3. Switch to hourly + quiet hours, leave it for 2–3 days, compare battery drain with the
   current version.
