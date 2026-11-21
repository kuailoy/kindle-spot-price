# kindle-spot-price

Show today's Finnish electricity spot prices on the lock screen of a jailbroken
Kindle Paperwhite 3, while still reading normally in the stock Kindle reader.

<p align="center">
  <img src="docs/preview-morning.png" width="300" alt="Lock screen preview (sample data)">
  <img src="docs/preview-evening.png" width="300" alt="Lock screen preview late in the evening (sample data)">
</p>

<sub>Previews use made-up sample prices.</sub>

[中文说明](docs/README.zh-CN.md)

## How it works

```
 spot-hinta.fi  ──►  GitHub Actions  ──►  GitHub Pages  ──►  Kindle lock screen
 (Nord Pool FI)      renders 48 hourly     hosts the         downloads once a day,
                     e-ink images/day      images            switches every hour offline
```

- **Cloud:** after tomorrow's prices are published (~14:00), a GitHub Actions job renders one
  image per hour for today and tomorrow and publishes them on GitHub Pages. Free, no server.
- **Kindle:** a scriptlet covers the stock lock-screen folder with a bind mount (the system
  partition is never modified). While the Kindle is awake, a small updater downloads new images
  in the evening and shows the right one for the current hour, without needing Wi-Fi.

Details: [docs/how-it-works.md](docs/how-it-works.md)

## What it shows

- **Today's 24 hourly prices** (average of the four 15-minute prices), in c/kWh including VAT
- **Gray level per 4 c/kWh**, from white (< 4) to black (≥ 40); dashed lines at 8 c ("cheap") and 20 c ("expensive")
- **Current price** in large type at the top right, with its hour (e.g. `now · 13:00–14:00`), so a stale lock screen is easy to spot; the current hour's bar is outlined and marked with a triangle
- **Highest / lowest hour** of the day
- **Best 2-hour laundry window**: the cheapest continuous 2 hours between 07:00 and 22:00 in the rest of the day; late in the evening it switches to tomorrow

### Update schedule

| When (Finnish time) | What happens |
|---|---|
| ~14:00 | Nord Pool publishes tomorrow's prices |
| 15:00, 16:00, 17:00 (+ 20:00 backup) | GitHub Actions renders today + tomorrow (one hour later in summer, cron runs in UTC) |
| after 18:00, Kindle awake on Wi-Fi | Kindle downloads tomorrow's images, deletes the previous day's |
| every full hour / on wake-up | Kindle shows the current hour's image (no network) |
| Kindle missed the evening | the next time it wakes on Wi-Fi it downloads the missing images |

While the Kindle sleeps nothing runs, so the lock screen shows the hour in which it was locked.
Waking up briefly every hour to redraw (no Wi-Fi needed) is on the roadmap.

## Setup

### 1. Publish the image

1. Push this repository to GitHub.
2. **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. **Actions → Update price image → Run workflow**.
4. After a minute the site is at `https://<your-user>.github.io/kindle-spot-price/`
   (latest image: `kindle.png`, hourly images: `frames/`).

### 2. Kindle

Requirements: a jailbroken Kindle Paperwhite 3 (tested on firmware 5.16.2.1.1 with WinterBreak2).

Files in this repository:

```
kindle/
├── scriptlets/
│   ├── ss_on.sh      "Lockscreen ON"  - copy into the Kindle's documents/ folder
│   └── ss_off.sh     "Lockscreen OFF" - copy into the Kindle's documents/ folder
├── sslive/
│   └── url.txt       your GitHub Pages address - copy into the Kindle's sslive/ folder
└── tools/
    └── ss_diag.sh    optional read-only diagnostic, not needed for normal use
```

> **Copy the files, not the folders.** Dragging a folder named `documents` onto the Kindle
> makes Finder offer to *replace* the existing `documents` folder, which would delete your books.

#### Install

1. **Set your URL.** Open `kindle/sslive/url.txt` and replace `YOUR-USER` with your GitHub
   user name. Check the address in a browser first: `<your URL>frames/manifest.txt` should show
   a list of file names.
2. **Connect the Kindle** by USB. On a Mac it appears as `/Volumes/Kindle`.
3. **Copy the two scriptlets** into the Kindle's `documents` folder. In Finder, select
   `ss_on.sh` and `ss_off.sh` and drag them *into* `Kindle/documents`. If asked, replace the
   older versions (this replaces only these two files).
4. **Copy `url.txt`** into the Kindle's `sslive` folder (create `sslive` in the Kindle root if
   it does not exist).

   Steps 3–4 in Terminal, from the repository folder (`-X` skips macOS metadata, which
   would otherwise create extra `._ss_on.sh` files on the Kindle):

   ```bash
   cp -X kindle/scriptlets/ss_on.sh kindle/scriptlets/ss_off.sh /Volumes/Kindle/documents/
   mkdir -p /Volumes/Kindle/sslive
   cp -X kindle/sslive/url.txt /Volumes/Kindle/sslive/
   dot_clean -m /Volumes/Kindle      # removes ._ files left by earlier Finder copies
   ```
5. **Eject** the Kindle in Finder before unplugging.
6. **Lock screen setting:** on the Kindle, turn **Display Cover** off, so the lock screen uses
   the built-in images.
7. **Start:** make sure Wi-Fi is connected, open the library and tap **Lockscreen ON**.
   If an older version was running, tap **Lockscreen OFF** first.
   The screen shows e.g. `Lockscreen ON. Showing: 20261121-13.png`.

#### Check that it works

| Check | Expected |
|---|---|
| Press the power button | the price chart, current hour in the top-right corner |
| `sslive/log.txt` (over USB) | `download: 24 new, 0 failed` and `showing YYYYMMDD-HH.png` |
| Stay awake past a full hour, then lock | the corner shows the new hour |
| Lock before a full hour, unlock after it, lock again | the corner shows the new hour |
| Use the Kindle on Wi-Fi after 18:00 | log: another `download: 24 new` (tomorrow's images) |

If the screen says `Using current.png ...` or `ERROR: no image yet`, nothing could be
downloaded: check Wi-Fi and `url.txt`, and look at `sslive/log.txt`.

#### Everyday use

- Nothing to do: images are downloaded and switched automatically while the Kindle is awake.
- **After a reboot** the stock lock screen is back; tap **Lockscreen ON** once.
- **Lockscreen OFF** restores the stock lock screen and stops the updater.
- **Updating** to a new version of the scripts: repeat steps 3, 5 and 7.
- Tapping **Lockscreen ON** again re-downloads all images (useful after the image design changed).
- **Uninstall:** tap **Lockscreen OFF**, delete `ss_on.sh`, `ss_off.sh` and the `sslive` folder.
  About 1.5 MB of downloaded images stays in `/var/local/sslive` on internal storage
  (harmless; it can be removed over SSH or kTerm).

#### Optional: diagnostic

`kindle/tools/ss_diag.sh` (shows up as **Screensaver Check**) only reads information: stock
screensaver files, available tools, screen size. Copy it into `documents`, run it, and read
`ss_diag/info.txt` over USB. Useful when something does not work or when trying another Kindle
model; not needed otherwise.

## Development

```bash
pip install -r requirements.txt
python -m pytest -q
python render/render.py --input tests/fixtures/sample-winter.json --now 2026-11-21T09:40 --out-dir out
# out/kindle.png, out/prices.json, out/frames/*.png + manifest.txt
```

Settings such as the scale, gray step and laundry hours are constants at the top of
`render/render.py`. Fonts: DejaVu Sans (Linux) or Arial (macOS); override with
`KSP_FONT_REGULAR` / `KSP_FONT_BOLD`.

## Roadmap

- [x] Pre-render hourly images; download once a day, switch hourly offline
- [ ] Wake the Kindle every hour (07–23, quiet at night) while it sleeps and redraw from local images, no Wi-Fi – [plan](docs/next-steps.md)
- [ ] Start automatically after a reboot
- [ ] Reuse `prices.json` on an ESP32-S3 + 7.5" e-ink desktop display
- [ ] Fallback data source

## Notes

- Prices are Nord Pool day-ahead prices for Finland incl. VAT, without your retailer's margin or
  transmission fees, from [spot-hinta.fi](https://spot-hinta.fi). Check their terms before heavy use.
- GitHub pauses scheduled workflows in repositories with no activity for 60 days; re-enable it
  from the Actions tab (GitHub sends an email).
- Jailbreaking is at your own risk. The lock-screen method here avoids writing to the system
  partition, but no warranty is given.
- The idea of fetching an image and showing it as the screensaver comes from the
  Kindle community's *Online Screensaver* extension; this project uses its own scripts.

## License

MIT, see [LICENSE](LICENSE).
