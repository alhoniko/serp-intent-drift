# Screenshot composition

Presents a genuine serp-drift screenshot on a quiet branded background (Paper or Ink with soft Live Blue and Voltage blooms and a little grain), with a rounded frame, a soft shadow and a small credit strip linking to nikoalho.fi and github.com/alhoniko. Everything renders locally. There are no network requests and no online services.

```
compose/
  capture.py     genuine app captures from a running `serp-drift serve` (read-only, 1440x900 at 2x)
  compose.py     driver (Python 3.11+, standard library only)
  template.html  page template ({{PLACEHOLDERS}} filled by compose.py)
  style.css      look: brand tokens, background, frame, credit strip
  fonts/         Outfit (variable) and JetBrains Mono 400, latin woff2, with their OFL licences
```

## Capture

`capture.py` loads app views from a running `serp-drift serve` through the same headless DevTools pipe, waits until the loading skeleton is gone and the page has stopped changing, and writes 2880x1800 PNGs. It only issues GET requests. Pick views that show no workspace paths (Settings and the agent connection page do).

```sh
cd docs/media/compose
python3 capture.py --out ../v0.7/originals '03-panel-summary=/p/ahrefs/panel/link-building@dark' '09-study-panels=/p/ahrefs-7d/panels'
```

Views default to the light theme; add `@dark` for the dark one. Panel tabs are hash parameters, for example `/p/ahrefs/panel/link-building?tab=history@dark`. The exact views, crops and capture times of the 0.7 set are in `docs/media/v0.7/manifest.json`.

## Usage

Requirements: macOS `sips`, `cwebp` (`brew install webp`) and Brave. Chrome, Chromium and `chrome-headless-shell` also work via `--browser` or `COMPOSE_BROWSER`. The browser runs headless with a throwaway profile (a new temp directory unless `--profile-dir` is given), so no real browser profile is touched.

```sh
# 1600x1000 image (light background)
python3 docs/media/compose/compose.py docs/media/v0.7/originals/09-study-panels.png --out-dir docs/media/v0.7/branded --name 09-study-panels

# dark-theme capture on the Ink background
python3 docs/media/compose/compose.py docs/media/v0.7/originals/03-panel-summary.png --out-dir docs/media/v0.7/branded --theme dark

# 1200x630 cover built from a readable crop: --focus x,y,w,h in source pixels
python3 docs/media/compose/compose.py docs/media/v0.7/originals/03-panel-summary.png --out-dir docs/media/v0.7/branded --name 00 --cover --focus 540,300,2298,1121 --theme dark

# screenshot of fixture data: adds a corner label outside the screenshot
python3 docs/media/compose/compose.py capture.png --out-dir OUT --label "Synthetic data"
```

Other options: `--alt` (alt text in the HTML version), `--browser`, `--cwebp` and `--profile-dir`.

| Run | Files written to `--out-dir` |
| --- | --- |
| default | `NAME@2x.png` master (3200x2000), `NAME.png` (1600x1000), `NAME.webp` (q85), `NAME.html` |
| `--cover` | `NAME-cover@2x.png` master (2400x1260), `NAME-cover.png` (exactly 1200x630), `NAME-cover.webp`, `NAME-cover.html` |

The HTML page links the source screenshot, `style.css` and the fonts by relative path. Keep it inside the repository so those links stay short, and don't move it away from the files it links to. In the HTML the credits are real links, and the page scales down to fit smaller windows.

After each run the driver prints the frame geometry, the paddings, the scale in pixels per source pixel and the fonts that were applied. It stops with an error if Outfit did not load, if the screenshot failed to load, or if the credit strip would leave the canvas or overlap the frame.

## Layout

The screenshot keeps its exact aspect ratio: it is only scaled, never stretched, and it is cropped only when `--focus` is used. It is fitted into the canvas with at least 5 % padding at the sides and about 4.6 % at the top. The bottom padding is slightly larger because it holds the credit strip. Any height left over is split above the frame and below the strip. For 16:10 captures (for example 2880x1800) on the 1600x1000 canvas, the frame is 1408x880 CSS px with 6 % padding at the sides.

For covers, pick a focus region with a ratio near 2.05:1, which matches the cover frame of 1088x532 CSS px. With a 2x capture, a region about 2176 px wide shows the UI at its native CSS size in the 1200x630 export. The driver warns when the web export would upscale the source.

## Rules for sources

- Sources must be untouched, genuine captures of the app. Cropping with `--focus` is fine. Retouching, compositing and edited numbers are not.
- Hide private data at capture time: use the example workspace, a Docker mount at `/home/you/serp-drift` and fixture data. Never paint over or blur anything afterwards.
- Label fixture or synthetic data with `--label "Synthetic data"`.

## Rendering note

Brave's `--screenshot` and `--dump-dom` switches hang in current releases, so the driver uses the DevTools protocol over `--remote-debugging-pipe` instead. It waits for the fonts and the image to be ready, then captures the viewport at device scale factor 2.

## Licences

- Outfit: SIL Open Font License 1.1, (c) The Outfit Project Authors (`fonts/OFL-Outfit.txt`).
- JetBrains Mono: SIL Open Font License 1.1, (c) The JetBrains Mono Project Authors (`fonts/OFL-JetBrainsMono.txt`).
- GitHub mark: `mark-github` from GitHub Octicons, MIT License, (c) GitHub Inc. The globe icon is a plain line drawing made for this template.
