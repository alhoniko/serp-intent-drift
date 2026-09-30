#!/usr/bin/env python3
"""Capture genuine app screenshots through the same headless DevTools pipe as compose.py.

Read-only: it only loads app pages (GET requests) from a running `serp-drift serve`. 1440×900 CSS px at scale 2.
Hide anything private at capture time (choose views without workspace paths); never paint over a capture.

    python3 capture.py --base http://127.0.0.1:8765 --out ORIGINALS_DIR name=/p/ahrefs/dashboard name2=/portfolio@dark
"""

import argparse
import base64
from pathlib import Path
import sys
import tempfile

from compose import DEFAULT_BROWSER, SCALE, DevTools, png_size

WIDTH, HEIGHT = 1440, 900

# Waits for the web fonts and for the single-page app to stop changing the DOM (data fetched and rendered).
SETTLED = r"""(async () => {
  await document.fonts.ready;
  const start = performance.now();
  let last = performance.now();
  const observer = new MutationObserver(() => { last = performance.now(); });
  observer.observe(document.body, {subtree: true, childList: true, characterData: true, attributes: true});
  const loading = () => Boolean(document.querySelector('main .skeleton')) || /Loading(…|\.\.\.)/.test(document.querySelector('main')?.innerText || '');
  while ((loading() || performance.now() - last < 1200) && performance.now() - start < 45000) await new Promise((r) => setTimeout(r, 100));
  observer.disconnect();
  await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  return {title: document.querySelector('main h1')?.textContent || '', viewport: [innerWidth, innerHeight, devicePixelRatio],
          errors: document.querySelectorAll('.notice.error, .toast.error').length, loading: loading()};
})()"""


def capture(browser: str, url: str, out: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="serp-capture-") as profile:
        devtools = DevTools(browser, Path(profile), WIDTH, HEIGHT)
        try:
            target = devtools.call("Target.createTarget", {"url": "about:blank"})["targetId"]
            session = devtools.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
            devtools.call("Emulation.setDeviceMetricsOverride", {"width": WIDTH, "height": HEIGHT, "deviceScaleFactor": SCALE, "mobile": False}, session)
            devtools.call("Page.enable", session=session)
            devtools.call("Page.navigate", {"url": url}, session)
            devtools.wait_event("Page.loadEventFired", session)
            state = devtools.call("Runtime.evaluate", {"expression": SETTLED, "awaitPromise": True, "returnByValue": True}, session)["result"]["value"]
            shot = devtools.call("Page.captureScreenshot", {"format": "png", "fromSurface": True}, session)
        finally:
            devtools.close()
    if state["loading"]:
        raise SystemExit(f"{url} was still loading after 45 s")
    if state["viewport"] != [WIDTH, HEIGHT, SCALE]:
        raise SystemExit(f"unexpected viewport {state['viewport']} for {url}")
    out.write_bytes(base64.b64decode(shot["data"]))
    if png_size(out) != (WIDTH * SCALE, HEIGHT * SCALE):
        raise SystemExit(f"{out}: unexpected size {png_size(out)}")
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("views", nargs="+", help="name=/hash/route, optionally suffixed with @dark")
    parser.add_argument("--base", default="http://127.0.0.1:8765")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--browser", default=DEFAULT_BROWSER)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for view in args.views:
        name, _, route = view.partition("=")
        route, _, theme = route.partition("@")
        url = f"{args.base.rstrip('/')}/?theme={theme or 'light'}#{route}"
        state = capture(args.browser, url, args.out / f"{name}.png")
        print(f"{name}.png <- {url} · {state['title']!r}", file=sys.stderr if state["errors"] else sys.stdout)


if __name__ == "__main__":
    main()
