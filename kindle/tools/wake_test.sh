#!/bin/sh
# Name: Wake Test 2
# Author: kindle-spot-price
#
# One-shot test of "wake up while locked and redraw", second attempt.
# Test 1 showed that powerd's rtcWakeup property is accepted but does not wake
# the device. This version sets the alarm directly on the hardware clock
# /sys/class/rtc/rtc1 (the approach used by kindle-dash), re-arming it on every
# readyToSuspend in case powerd clears it. When the Kindle wakes up it redraws
# the lock screen with the current hour's image plus "WAKE TEST hh:mm".
# Nothing is installed; the test stops by itself. A reboot also stops it.
#
# Log: /mnt/us/ss_diag/wake_test.txt

DELAY=180          # seconds after the first readyToSuspend (it sleeps ~55 s later)
RTC=/sys/class/rtc/rtc1
OUT=/mnt/us/ss_diag
LOG=$OUT/wake_test.txt
STATE=/var/local/wake_test2

# stop listeners left over from earlier test runs (they would act on the same events)
for p in $(ps | grep -F "com.lab126.powerd *" | grep -v grep | awk '{print $1}'); do
    kill "$p" 2>/dev/null
done
sleep 1

rm -rf "$STATE"
mkdir -p "$OUT" "$STATE"
: > "$LOG"

log() { echo "$(date '+%T') $*" >> "$LOG"; }

frame() {
    f="/var/local/sslive/frames/$(date +%Y%m%d-%H).png"
    [ -f "$f" ] || f=/mnt/us/sslive/current.png
    echo "$f"
}

redraw() {   # $1 = what noticed the wake-up
    [ -f "$STATE/armed" ] || return 0
    mkdir "$STATE/done" 2>/dev/null || return 0     # only once
    t0=$(date +%s)
    log "woke up ($1), $((t0 - $(cat "$STATE/armed_at"))) s after arming;" \
        "powerd state: $(lipc-get-prop com.lab126.powerd state 2>/dev/null)"
    f=$(frame)
    eips -f -g "$f" >> "$LOG" 2>&1 && log "drew $f" || log "eips -g FAILED for $f"
    eips 2 2 "WAKE TEST $(date '+%H:%M')" >> "$LOG" 2>&1
    log "redraw took $(( $(date +%s) - t0 )) s, battery" \
        "$(lipc-get-prop com.lab126.powerd battLevel 2>/dev/null)%"
    echo 0 > /sys/class/rtc/rtc1/wakealarm 2>/dev/null
    log "slept until $(date '+%T'); target was $(date -d @$(cat "$STATE/target") '+%T' 2>/dev/null || cat "$STATE/target")"
}

# self-check: can we write the hardware alarm at all?
echo 0 > $RTC/wakealarm 2>>"$LOG"
echo $(( $(date +%s) + 3600 )) > $RTC/wakealarm 2>>"$LOG"
log "self-check: rtc1 wakealarm after writing now+3600: '$(cat $RTC/wakealarm 2>/dev/null)'"
echo 0 > $RTC/wakealarm 2>>"$LOG"
log "self-check: after clearing: '$(cat $RTC/wakealarm 2>/dev/null)'"

log "start, battery $(lipc-get-prop com.lab126.powerd battLevel 2>/dev/null)%"
log "lock the Kindle now and do not touch it for 5 minutes"

(
    lipc-wait-event -m com.lab126.powerd '*' 2>&1 | while read -r ev rest; do
        log "event: $ev $rest"
        case "$ev" in
            readyToSuspend)
                # first time: choose the wake-up time; every time: (re)write it
                if [ ! -s "$STATE/target" ]; then
                    date +%s > "$STATE/armed_at"
                    echo $(( $(date +%s) + DELAY )) > "$STATE/target"
                    touch "$STATE/armed"
                fi
                target=$(cat "$STATE/target")
                if [ ! -d "$STATE/done" ]; then
                    echo 0 > $RTC/wakealarm 2>>"$LOG"
                    echo "$target" > $RTC/wakealarm 2>>"$LOG"
                    log "rtc1 wakealarm=$(cat $RTC/wakealarm 2>/dev/null) (target $target," \
                        "in $((target - $(date +%s))) s); rtc0 wakealarm=$(cat /sys/class/rtc/rtc0/wakealarm 2>/dev/null)"
                fi
                ;;
            suspending)
                log "rtc1 wakealarm just before sleep: $(cat $RTC/wakealarm 2>/dev/null)"
                ;;
            wakeupFromSuspend|resuming)
                redraw "event $ev $rest"
                ;;
            outOfScreenSaver)
                log "unlocked by user"
                ;;
        esac
    done
) </dev/null >/dev/null 2>&1 &

# backup in case the wake-up event has another name: notice the clock jump
# that a sleep leaves behind (this loop is frozen while the Kindle sleeps)
(
    last=$(date +%s)
    n=0
    while [ ! -d "$STATE/done" ] && [ $n -lt 200 ]; do
        n=$((n + 1))
        sleep 5
        now=$(date +%s)
        [ $((now - last)) -gt 30 ] && redraw "clock jump $((now - last)) s"
        last=$now
    done
) </dev/null >/dev/null 2>&1 &

# stop after 15 minutes of awake time (the timer pauses while the Kindle sleeps)
(
    n=0
    while [ $n -lt 45 ]; do sleep 20; n=$((n + 1)); done
    for p in $(ps | grep -F "com.lab126.powerd *" | grep -v grep | awk '{print $1}'); do
        kill "$p" 2>/dev/null
    done
    log "test finished"
) </dev/null >/dev/null 2>&1 &

echo "Wake Test 2 started. Do NOT connect USB during the test"
echo "(plugging in wakes the Kindle and spoils the result)."
echo ""
echo "1. Press the power button now (lock)."
echo "2. Do not touch the Kindle for 5 minutes."
echo "   About 3-4 minutes after locking, the lock screen should redraw by itself"
echo "   and show 'WAKE TEST hh:mm' in the top-left corner."
echo "3. Unlock, connect USB, send ss_diag/wake_test.txt"
