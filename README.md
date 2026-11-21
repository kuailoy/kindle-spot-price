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
- **Current hour** marked with a triangle; the hour is also printed in the corner, so a stale lock screen is easy to spot
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

Requirements: a jailbroken Kindle Paperwhite 3 (tested on firmware 5.16.2.1.1, WinterBreak2),
lock screen set to the fixed image (not "Display cover").

1. Connect the Kindle by USB.
2. Copy `kindle/ss_on.sh` and `kindle/ss_off.sh` into the `documents` folder.
3. Create a folder `sslive` in the Kindle root and put in it:
   - `url.txt` – one line with your site URL, e.g. `https://<your-user>.github.io/kindle-spot-price/`
   - `current.png` (optional) – any 1072×1448 grayscale PNG, used only if nothing has been downloaded yet
4. Eject, turn on Wi-Fi, open **Lockscreen ON** from the library.

**Lockscreen OFF** (or a reboot) restores the stock lock screen and stops the updater.
After a reboot, open **Lockscreen ON** again. Logs are written to `sslive/log.txt`.

`kindle/ss_diag.sh` is a read-only diagnostic that lists the screensaver files, tools and
screen info; useful when porting to another Kindle model.

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
