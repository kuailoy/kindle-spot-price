#!/bin/sh
# Name: Lockscreen OFF
# Author: kindle-spot-price
#
# Stops the updater and restores the stock lock screen (same as a reboot).
# Downloaded images stay in /var/local/sslive and are reused next time.

SYS=/usr/share/blanket/screensaver
BASE=/var/local/sslive

if [ -f "$BASE/pids" ]; then
    while read -r p; do kill "$p" 2>/dev/null; done < "$BASE/pids"
    rm -f "$BASE/pids"
fi
rmdir "$BASE/lock" 2>/dev/null
rm -f "$BASE/events.fifo"

if grep -q " $SYS " /proc/mounts; then
    umount "$SYS" && echo "Stock lock screen restored." || echo "ERROR: unmount failed, reboot to restore."
else
    echo "Was not active."
fi

lipc-set-prop com.lab126.blanket unload screensaver 2>/dev/null
lipc-set-prop com.lab126.blanket load screensaver 2>/dev/null
