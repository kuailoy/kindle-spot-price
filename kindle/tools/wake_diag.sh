#!/bin/sh
# Name: Wake Check
# Author: kindle-spot-price
#
# Read-only diagnostic for the "wake up while locked" feature.
# It changes nothing on the device. It
#   1. lists the power daemon's properties, RTC (real-time clock) devices and tools
#   2. listens to power events for 4 minutes, so you can lock and unlock the
#      Kindle and see which events fire and in which order.
#
# Output: /mnt/us/ss_diag/wake_info.txt and /mnt/us/ss_diag/wake_events.txt

OUT=/mnt/us/ss_diag
mkdir -p "$OUT"
INFO="$OUT/wake_info.txt"
EVENTS="$OUT/wake_events.txt"
: > "$INFO"

log() { echo "$@" >> "$INFO"; }

log "== Wake Check $(date) =="
cat /etc/prettyversion.txt 2>/dev/null >> "$INFO"

log ""
log "== Tools =="
for t in lipc-probe lipc-get-prop lipc-set-prop lipc-wait-event eips fbink rtcwake hwclock mkfifo timeout; do
    p=$(command -v $t 2>/dev/null)
    log "$t: ${p:-MISSING}"
done

log ""
log "== powerd properties (lipc-probe) =="
lipc-probe -v com.lab126.powerd >> "$INFO" 2>&1 || log "(lipc-probe failed)"

log ""
log "== powerd readable values =="
for prop in state status battLevel isCharging preventScreenSaver; do
    log "-- $prop:"
    lipc-get-prop com.lab126.powerd $prop >> "$INFO" 2>&1
done

log ""
log "== RTC devices =="
for r in /sys/class/rtc/rtc*; do
    [ -e "$r" ] || continue
    log "-- $r"
    for f in name since_epoch wakealarm date time; do
        [ -r "$r/$f" ] && log "   $f: $(cat "$r/$f" 2>/dev/null)"
    done
    ls "$r" 2>/dev/null | tr '\n' ' ' >> "$INFO"; log ""
    [ -r "$r/device/power/wakeup" ] && log "   device/power/wakeup: $(cat "$r/device/power/wakeup")"
done
[ -r /proc/driver/rtc ] && { log "-- /proc/driver/rtc"; cat /proc/driver/rtc >> "$INFO"; }
for f in /sys/devices/platform/mxc_rtc.0/wakeup_enable /sys/devices/platform/snvs_rtc.0/wakeup_enable; do
    [ -e "$f" ] && log "$f: $(cat "$f" 2>/dev/null)"
done

log ""
log "== Clock =="
log "date: $(date)   epoch: $(date +%s)"
log "TZ: ${TZ:-unset}   /etc/localtime -> $(readlink /etc/localtime 2>/dev/null)"
hwclock -r >> "$INFO" 2>&1

log ""
log "== Upstart jobs mentioning powerd / suspend =="
ls /etc/upstart 2>/dev/null | grep -i -E "power|suspend|blanket" >> "$INFO"

# ---------------------------------------------------------------------------
# Listen to power events for 4 minutes (runs in the background)
# ---------------------------------------------------------------------------
: > "$EVENTS"
(
    echo "== powerd events from $(date '+%T') (listening 4 min) ==" >> "$EVENTS"
    lipc-wait-event -m com.lab126.powerd '*' 2>&1 | while read -r line; do
        echo "$(date '+%T') $line" >> "$EVENTS"
    done
) </dev/null >/dev/null 2>&1 &
LISTENER=$!
(
    sleep 240
    kill $LISTENER 2>/dev/null
    # stop our lipc-wait-event too (only the '*' listener, not the lock-screen updater's)
    for p in $(ps | grep -F "com.lab126.powerd *" | grep -v grep | awk '{print $1}'); do
        kill "$p" 2>/dev/null
    done
    echo "== stopped $(date '+%T') ==" >> "$EVENTS"
) </dev/null >/dev/null 2>&1 &

echo "Info written to ss_diag/wake_info.txt"
echo ""
echo "Now listening to power events for 4 minutes:"
echo "  1. press the power button (lock)"
echo "  2. wait about 1 minute"
echo "  3. press it again (unlock)"
echo "(the 4 minutes pause while the Kindle sleeps)"
echo "Then connect USB and send ss_diag/wake_info.txt and wake_events.txt"
