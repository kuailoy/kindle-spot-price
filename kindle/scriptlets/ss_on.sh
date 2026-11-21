#!/bin/sh
# Name: Lockscreen ON
# Author: kindle-spot-price
#
# Shows hourly electricity price images on the native lock screen.
#
# How it works
#   - The stock lock screen folder /usr/share/blanket/screensaver is covered
#     with a bind mount of /var/local/sslive/live. Nothing on the system
#     partition is modified; "Lockscreen OFF" or a reboot restores the original.
#   - A background updater (only runs while the Kindle is awake):
#       * downloads hourly images (frames) when Wi-Fi is on and images are
#         missing: the current hour's image, or after 18:00 tomorrow's images
#       * puts the image for the current hour in place at every full hour
#         and right after the Kindle wakes up (no network needed)
#
# Setup: /mnt/us/sslive/url.txt  = base URL of the published images, e.g.
#        https://<user>.github.io/kindle-spot-price/  (template in the repo:
#        kindle/sslive/url.txt)
#        /mnt/us/sslive/current.png (optional) = image used until frames exist

SYS=/usr/share/blanket/screensaver
BASE=/var/local/sslive            # internal storage, available in USB mode too
LIVE=$BASE/live
FRAMES=$BASE/frames
USER_DIR=/mnt/us/sslive
DAEMON=$BASE/sslive_daemon.sh
PIDS=$BASE/pids

mkdir -p "$LIVE" "$FRAMES" "$USER_DIR"

# ---------------------------------------------------------------------------
# Write the background updater to internal storage, so it keeps running when
# /mnt/us disappears in USB mode.
# ---------------------------------------------------------------------------
cat > "$DAEMON" <<'DAEMON_EOF'
#!/bin/sh
SYS=/usr/share/blanket/screensaver
BASE=/var/local/sslive
LIVE=$BASE/live
FRAMES=$BASE/frames
USER_DIR=/mnt/us/sslive
LOCK=$BASE/lock

log() {
    f="$USER_DIR/log.txt"
    [ -d "$USER_DIR" ] || return 0
    echo "$(date '+%F %T') $*" >> "$f" 2>/dev/null
    # keep the log small
    if [ "$(wc -c < "$f" 2>/dev/null || echo 0)" -gt 200000 ]; then
        tail -n 400 "$f" > "$f.tmp" 2>/dev/null && mv "$f.tmp" "$f"
    fi
}

# PNG signature + 1072x1448 size from the IHDR header, busybox tools only
valid_png() {
    [ -s "$1" ] || return 1
    sig=$(head -c 8 "$1" | od -An -tx1 | tr -d ' \n')
    [ "$sig" = "89504e470d0a1a0a" ] || return 1
    wh=$(dd if="$1" bs=1 skip=16 count=8 2>/dev/null | od -An -tx1 | tr -d ' \n')
    [ "$wh" = "00000430000005a8" ]
}

# copy one image over all 20 stock slots
install_image() {
    i=0
    while [ $i -le 19 ]; do
        n=$(printf "%02d" $i)
        cp "$1" "$LIVE/bg_ss$n.png.tmp" && mv "$LIVE/bg_ss$n.png.tmp" "$LIVE/bg_ss$n.png"
        i=$((i + 1))
    done
    sync
}

wifi_up() {
    lipc-get-prop com.lab126.wifid cmState 2>/dev/null | grep -q CONNECTED
}

base_url() {
    # first line that is not empty and not a # comment
    u=$(grep -v '^[[:space:]]*#' "$USER_DIR/url.txt" 2>/dev/null | tr -d '\r ' | grep -v '^$' | head -n 1)
    [ -n "$u" ] || return 1
    case "$u" in
        *YOUR-USER*) log "url.txt still has the placeholder YOUR-USER, edit it"; return 1 ;;
    esac
    case "$u" in
        *.png) u="${u%/*}/" ;;
        */)    ;;
        *)     u="$u/" ;;
    esac
    echo "$u"
}

now_s() { date +%s; }

need_fetch() {
    today=$(date +%Y%m%d)
    hour=$(date +%H); hour=${hour#0}
    cur="$FRAMES/$(date +%Y%m%d-%H).png"
    [ -f "$cur" ] || return 0                       # current hour missing
    last=$(tail -n 1 "$FRAMES/manifest.txt" 2>/dev/null)
    # after 18:00, fetch again until tomorrow's images are there
    # (the cloud renders them between 15:00 and 18:00)
    if [ "$hour" -ge 18 ] && [ "${last%%-*}" = "$today" ]; then
        return 0
    fi
    return 1
}

fetch() {
    # at most one attempt every 30 minutes
    t=$(now_s); prev=$(cat "$BASE/last_fetch" 2>/dev/null || echo 0)
    [ $((t - prev)) -ge 1800 ] || return 1
    echo "$t" > "$BASE/last_fetch"
    url=$(base_url) || { log "no url.txt, skipping download"; return 1; }

    tmp=$BASE/manifest.tmp
    if ! curl -fsSL --max-time 30 -o "$tmp" "${url}frames/manifest.txt"; then
        log "manifest download failed"
        return 1
    fi
    got=0; bad=0
    while read -r name; do
        case "$name" in [0-9]*-[0-9][0-9].png) ;; *) continue ;; esac
        [ -f "$FRAMES/$name" ] && continue
        if curl -fsSL --max-time 60 -o "$FRAMES/$name.tmp" "${url}frames/$name" \
           && valid_png "$FRAMES/$name.tmp"; then
            mv "$FRAMES/$name.tmp" "$FRAMES/$name"; got=$((got + 1))
        else
            rm -f "$FRAMES/$name.tmp"; bad=$((bad + 1))
        fi
    done < "$tmp"
    mv "$tmp" "$FRAMES/manifest.txt"

    # remove images from previous days
    today=$(date +%Y%m%d)
    for f in "$FRAMES"/*.png; do
        [ -f "$f" ] || continue
        d=$(basename "$f"); d=${d%%-*}
        [ "$d" -lt "$today" ] 2>/dev/null && rm -f "$f"
    done
    log "download: $got new, $bad failed"
}

apply_current() {
    name="$(date +%Y%m%d-%H).png"
    f="$FRAMES/$name"
    [ "$(cat "$BASE/applied" 2>/dev/null)" = "$name" ] && return 0
    if [ -f "$f" ]; then
        install_image "$f"
        echo "$name" > "$BASE/applied"
        log "showing $name"
    fi
}

tick() {
    mkdir "$LOCK" 2>/dev/null || return 0           # another tick is running
    if need_fetch; then
        # right after a wake-up Wi-Fi needs a few seconds to reconnect
        n=0
        while ! wifi_up && [ $n -lt 10 ]; do sleep 3; n=$((n + 1)); done
        wifi_up && fetch
    fi
    apply_current
    rmdir "$LOCK"
}

case "$1" in
    tick)
        tick
        ;;
    timer)
        # wake up at the next full hour (capped, in case a suspend
        # stretched the sleep), then put the right image in place
        while true; do
            tick
            m=$(date +%M); m=${m#0}; s=$(date +%S); s=${s#0}
            left=$((3600 - m * 60 - s + 5))
            [ $left -gt 900 ] && left=900
            sleep $left
        done
        ;;
    events)
        # react right after the Kindle wakes up from the lock screen
        fifo=$BASE/events.fifo
        rm -f "$fifo"
        mkfifo "$fifo" 2>/dev/null || { log "mkfifo missing, wake events disabled"; exit 0; }
        lipc-wait-event -m com.lab126.powerd outOfScreenSaver,wakeupFromSuspend > "$fifo" 2>/dev/null &
        echo $! >> "$BASE/pids"
        while read -r line; do
            sleep 2
            tick
        done < "$fifo"
        ;;
esac
DAEMON_EOF
chmod +x "$DAEMON"

say() { echo "$@"; [ -d "$USER_DIR" ] && echo "$(date '+%F %T') $*" >> "$USER_DIR/log.txt"; }

# ---------------------------------------------------------------------------
# Stop an updater from an earlier run
# ---------------------------------------------------------------------------
if [ -f "$PIDS" ]; then
    while read -r p; do kill "$p" 2>/dev/null; done < "$PIDS"
    rm -f "$PIDS"
fi
rmdir "$BASE/lock" 2>/dev/null
rm -f "$BASE/applied" "$BASE/last_fetch"

# space check (frames need ~2 MB)
free_kb=$(df -k /var/local | awk 'NR==2 {print $4}')
if [ -n "$free_kb" ] && [ "$free_kb" -lt 4000 ]; then
    say "ERROR: not enough space in /var/local (${free_kb} KB). Nothing changed."
    exit 1
fi

# keep the non-standard stock files (black background etc.) available
for f in "$SYS"/*; do
    b=$(basename "$f")
    case "$b" in bg_ss[0-9][0-9].png|bg_kids_*) continue ;; esac
    [ -e "$LIVE/$b" ] || cp "$f" "$LIVE/$b" 2>/dev/null
done

# load the helper functions (valid_png, install_image) from the updater
. "$DAEMON"

# first image: download now if possible, else current.png
"$DAEMON" tick
if [ ! -f "$LIVE/bg_ss00.png" ] || ! [ -s "$BASE/applied" ]; then
    if valid_png "$USER_DIR/current.png" 2>/dev/null; then
        install_image "$USER_DIR/current.png"
        say "Using current.png until hourly images are downloaded."
    elif [ ! -f "$LIVE/bg_ss00.png" ]; then
        say "ERROR: no image yet. Turn on Wi-Fi and check url.txt, or add current.png."
        exit 1
    fi
fi

# (re)mount the live folder over the stock one
if grep -q " $SYS " /proc/mounts; then
    umount "$SYS" 2>/dev/null
fi
if mount --bind "$LIVE" "$SYS"; then
    say "Bind mount OK."
else
    say "ERROR: bind mount failed. Nothing changed."
    exit 1
fi
lipc-set-prop com.lab126.blanket unload screensaver 2>/dev/null
lipc-set-prop com.lab126.blanket load screensaver 2>/dev/null

# start the updater (two small loops, both idle while the Kindle sleeps)
"$DAEMON" timer  </dev/null >/dev/null 2>&1 &
echo $! >> "$PIDS"
"$DAEMON" events </dev/null >/dev/null 2>&1 &
echo $! >> "$PIDS"

say "Lockscreen ON. Showing: $(cat "$BASE/applied" 2>/dev/null || echo current.png)"
say "Keep 'Display cover' OFF in settings."
