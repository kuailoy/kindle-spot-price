#!/bin/sh
# Name: Screensaver Check
# Author: Claude
#
# Read-only diagnostic. Collects info about the lock screen images and
# available tools into /mnt/us/ss_diag/ . Changes nothing on the system.

OUT=/mnt/us/ss_diag
mkdir -p "$OUT"
LOG="$OUT/info.txt"
: > "$LOG"

say() { echo "$@" | tee -a "$LOG"; }

say "== Screensaver Check $(date) =="

say ""
say "== Firmware / device =="
cat /etc/prettyversion.txt 2>/dev/null >> "$LOG"
uname -a >> "$LOG" 2>&1

for d in /usr/share/blanket/screensaver /usr/share/blanket/screensavers; do
    say ""
    say "== $d =="
    if [ -d "$d" ]; then
        ls -la "$d" >> "$LOG" 2>&1
        say "count: $(ls "$d" 2>/dev/null | wc -l)"
        # copy up to 2 original images so their exact format can be checked
        n=0
        for f in "$d"/*.png; do
            [ -f "$f" ] || continue
            cp "$f" "$OUT/orig_$(basename "$f")"
            n=$((n+1))
            [ $n -ge 2 ] && break
        done
    else
        say "(not found)"
    fi
done

say ""
say "== Mounts (root fs, user storage) =="
mount | grep -E ' / |/mnt/us|blanket' >> "$LOG" 2>&1

say ""
say "== Tools available =="
for t in curl wget crond crontab fbink eips lipc-get-prop lipc-set-prop lipc-wait-event python3 python; do
    p=$(command -v $t 2>/dev/null)
    say "$t: ${p:-MISSING}"
done
curl --version 2>&1 | head -2 >> "$LOG"

say ""
say "== Cron =="
ls -la /etc/crontab 2>&1 >> "$LOG"
cat /etc/crontab/root 2>/dev/null >> "$LOG"
ps | grep -E 'cron' | grep -v grep >> "$LOG" 2>&1

say ""
say "== Screen =="
eips -i 2>/dev/null | head -20 >> "$LOG"

say ""
say "== Blanket / power state =="
lipc-get-prop com.lab126.blanket load >> "$LOG" 2>&1
lipc-get-prop com.lab126.powerd status 2>/dev/null | head -10 >> "$LOG"

say ""
say "== Network test (HTTPS) =="
if command -v curl >/dev/null 2>&1; then
    curl -s -o /dev/null -w "github.io HTTP %{http_code}\n" --max-time 15 https://pages.github.com/ >> "$LOG" 2>&1 \
        || say "curl https failed (Wi-Fi off?)"
fi

say ""
say "Done. Files are in the ss_diag folder on your Kindle."
