#!/usr/bin/env python3
"""Compose a genuine app screenshot onto the branded serp-drift background and render PNG/WebP/HTML.

Standard library only. Needs Brave (or Chrome) for headless rendering, macOS `sips` for downscaling and `cwebp` for WebP.
The source screenshot is never modified: it is only scaled (and, with --focus, cropped by the frame) at render time.
"""

import argparse
import base64
import fcntl
import html
import json
import os
from pathlib import Path
import re
import select
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
DEFAULT_BROWSER = "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
DEFAULT_CWEBP = "/opt/homebrew/bin/cwebp"
SCALE = 2  # device scale factor of the master render

# Canvas presets in CSS px. side/top/bottom are minimum paddings; bottom holds the credit strip.
FORMATS = {
    "primary": {"width": 1600, "height": 1000, "side": 80, "top": 46, "bottom": 74, "radius": 14, "font": 16.5, "suffix": ""},
    "cover": {"width": 1200, "height": 630, "side": 56, "top": 34, "bottom": 64, "radius": 12, "font": 15.5, "suffix": "-cover"},
}


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise SystemExit(f"{path}: not a PNG file")
    return struct.unpack(">II", header[16:24])


def parse_focus(value: str) -> tuple[int, int, int, int]:
    try:
        x, y, w, h = (int(part) for part in value.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError("expected x,y,w,h in source pixels, e.g. 540,120,2160,1060") from None
    if w <= 0 or h <= 0 or x < 0 or y < 0:
        raise argparse.ArgumentTypeError("focus needs x,y >= 0 and w,h > 0")
    return x, y, w, h


def fit(src_w: int, src_h: int, box_w: float, box_h: float) -> tuple[int, int]:
    """Largest integer size inside the box with the source ratio.

    Gives up at most 16 px of width and 8 px of height to land on an integer height, so the ratio stays exact.
    """
    ratio = src_h / src_w
    widest = int(min(box_w, box_h / ratio))
    candidates = [width for width in range(widest, max(widest - 16, 0), -1) if (widest - width) * ratio <= 8]
    error = {width: abs(width * ratio - round(width * ratio)) for width in candidates}
    exact = [width for width in candidates if error[width] < 0.02]
    width = exact[0] if exact else min(candidates, key=error.get)
    return width, round(width * ratio)


def layout(fmt: dict, crop_w: int, crop_h: int) -> dict:
    cw, ch, side, top, bottom = fmt["width"], fmt["height"], fmt["side"], fmt["top"], fmt["bottom"]
    fw, fh = fit(crop_w, crop_h, cw - 2 * side, ch - top - bottom)
    spare = ch - top - bottom - fh
    fx, fy = (cw - fw) // 2, top + spare // 2
    inner_w = cw - 2 * side
    # The credit row sits right under the frame (spare height is split above the frame and below the row). It spans the
    # frame width, or the inner canvas when the frame is narrow (portrait captures).
    rx, rw = (fx, fw) if fw >= 0.7 * inner_w else (side, inner_w)
    return {"cw": cw, "ch": ch, "fx": fx, "fy": fy, "fw": fw, "fh": fh, "rx": rx, "rw": rw, "ry": fy + fh + 1, "rh": bottom - 1}


def css_px(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".") + "px"


def build_html(source: Path, out_html: Path, fmt: dict, box: dict, focus: tuple[int, int, int, int], src_size: tuple[int, int],
               theme: str, label: str | None, alt: str, title: str) -> str:
    fx, fy, fw, _ = focus
    scale = box["fw"] / fw
    geometry = {
        "--cw": box["cw"], "--ch": box["ch"],
        "--fx": box["fx"], "--fy": box["fy"], "--fw": box["fw"], "--fh": box["fh"],
        "--ix": -fx * scale, "--iy": -fy * scale, "--iw": src_size[0] * scale, "--ih": src_size[1] * scale,
        "--rx": box["rx"], "--ry": box["ry"], "--rw": box["rw"], "--rh": box["rh"],
        "--radius": fmt["radius"], "--strip-font": fmt["font"],
    }
    style = "; ".join(f"{key}: {css_px(value)}" for key, value in geometry.items())
    label_html = f'\n    <span class="label">{html.escape(label)}</span>' if label else ""

    def relative(target: Path) -> str:
        return quote(os.path.relpath(target, out_html.parent))

    values = {
        "THEME": theme, "TITLE": html.escape(title), "STYLE_HREF": relative(HERE / "style.css"), "GEOMETRY": style,
        "IMG_SRC": relative(source), "IMG_W": str(src_size[0]), "IMG_H": str(src_size[1]), "ALT": html.escape(alt), "LABEL": label_html,
    }
    page = (HERE / "template.html").read_text(encoding="utf-8")
    return re.sub(r"\{\{([A-Z_]+)\}\}", lambda match: values[match.group(1)], page)


def run(command: list[str], timeout: int = 120) -> str:
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise SystemExit(f"command failed ({result.returncode}): {command[0]}\n{result.stderr[-2000:]}")
    return result.stdout


class DevTools:
    """Minimal Chrome DevTools Protocol client over --remote-debugging-pipe (NUL-separated JSON on fds 3 and 4).

    Brave's --screenshot/--dump-dom switches hang in current releases; the protocol also lets us wait for fonts and
    the image explicitly instead of guessing a time budget.
    """

    def __init__(self, browser: str, profile: Path, width: int, height: int, timeout: float = 60):
        to_browser, self._to_write = os.pipe()
        self._from_read, from_browser = os.pipe()

        def attach_pipes() -> None:  # runs in the child between fork and exec
            os.dup2(fcntl.fcntl(to_browser, fcntl.F_DUPFD_CLOEXEC, 10), 3)
            os.dup2(fcntl.fcntl(from_browser, fcntl.F_DUPFD_CLOEXEC, 10), 4)

        command = [
            browser, "--headless=new", "--remote-debugging-pipe", "--disable-gpu", "--hide-scrollbars",
            f"--force-device-scale-factor={SCALE}", f"--window-size={width},{height}", f"--user-data-dir={profile}",
            "--no-first-run", "--no-default-browser-check", "--disable-extensions", "--disable-sync", "--disable-default-apps",
            "--disable-background-networking", "--disable-component-update", "--mute-audio", "about:blank",
        ]
        self.process = subprocess.Popen(command, preexec_fn=attach_pipes, close_fds=False,
                                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(to_browser)
        os.close(from_browser)
        self._deadline = time.monotonic() + timeout
        self._buffer = b""
        self._next_id = 0

    def _message(self) -> dict:
        while b"\0" not in self._buffer:
            remaining = self._deadline - time.monotonic()
            if remaining <= 0 or not select.select([self._from_read], [], [], remaining)[0]:
                raise SystemExit("browser timed out")
            chunk = os.read(self._from_read, 1 << 20)
            if not chunk:
                raise SystemExit("browser exited unexpectedly")
            self._buffer += chunk
        raw, self._buffer = self._buffer.split(b"\0", 1)
        return json.loads(raw)

    def call(self, method: str, params: dict | None = None, session: str | None = None) -> dict:
        self._next_id += 1
        message = {"id": self._next_id, "method": method, "params": params or {}}
        if session:
            message["sessionId"] = session
        os.write(self._to_write, json.dumps(message).encode() + b"\0")
        while True:
            reply = self._message()
            if reply.get("id") == self._next_id:
                if "error" in reply:
                    raise SystemExit(f"{method} failed: {reply['error'].get('message')}")
                return reply["result"]

    def wait_event(self, method: str, session: str) -> None:
        while True:
            reply = self._message()
            if reply.get("method") == method and reply.get("sessionId") == session:
                return

    def close(self) -> None:
        try:
            if self.process.poll() is None:
                self.call("Browser.close")
            self.process.wait(timeout=10)
        except (SystemExit, OSError, subprocess.TimeoutExpired):
            self.process.kill()
        finally:
            os.close(self._to_write)
            os.close(self._from_read)


READY = """(async () => {
  await document.fonts.ready;
  const image = document.querySelector('.shot img');
  await image.decode().catch(() => {});
  await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  const box = (element) => { const rect = element.getBoundingClientRect(); return [rect.left, rect.top, rect.right, rect.bottom]; };
  return {
    fonts: [...document.fonts].filter((face) => face.status === 'loaded').map((face) => face.family.replace(/["']/g, '')),
    image: [image.naturalWidth, image.naturalHeight],
    viewport: [innerWidth, innerHeight, devicePixelRatio],
    frame: box(document.querySelector('.shot')),
    credits: [...document.querySelectorAll('.attribution, .label')].map(box),
  };
})()"""


def render(browser: str, profile: Path, page: Path, master: Path, width: int, height: int, src_size: tuple[int, int]) -> dict:
    devtools = DevTools(browser, profile, width, height)
    try:
        target = devtools.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        session = devtools.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        devtools.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": SCALE, "mobile": False}, session)
        devtools.call("Page.enable", session=session)
        devtools.call("Page.navigate", {"url": page.resolve().as_uri()}, session)
        devtools.wait_event("Page.loadEventFired", session)
        state = devtools.call("Runtime.evaluate", {"expression": READY, "awaitPromise": True, "returnByValue": True}, session)["result"]["value"]
        shot = devtools.call("Page.captureScreenshot", {"format": "png", "fromSurface": True}, session)
    finally:
        devtools.close()
    if tuple(state["image"]) != src_size:
        raise SystemExit(f"the page did not load the screenshot (got {state['image']}); check the relative path in {page}")
    if state["viewport"] != [width, height, SCALE]:
        raise SystemExit(f"unexpected viewport {state['viewport']}")
    if "Outfit Variable" not in state["fonts"]:
        raise SystemExit(f"Outfit was not applied (loaded: {state['fonts'] or 'none'}); check compose/fonts/")
    frame_bottom = state["frame"][3]
    for left, top, right, bottom in state["credits"]:
        if left < 0 or right > width or bottom > height or top < frame_bottom:
            raise SystemExit(f"credit strip {left, top, right, bottom} leaves the canvas or overlaps the frame (bottom {frame_bottom})")
    master.write_bytes(base64.b64decode(shot["data"]))
    if png_size(master) != (width * SCALE, height * SCALE):
        raise SystemExit(f"{master}: expected {width * SCALE}x{height * SCALE}, got {png_size(master)}")
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="genuine, untouched app screenshot (PNG)")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--name", help="output base name (default: source file name)")
    parser.add_argument("--theme", choices=("light", "dark"), default="light", help="background: Paper (light) or Ink (dark)")
    parser.add_argument("--cover", action="store_true", help="compose the 1200x630 cover instead of the 1600x1000 image")
    parser.add_argument("--focus", type=parse_focus, help="crop region x,y,w,h in source pixels (intended for --cover)")
    parser.add_argument("--label", help='small corner label outside the screenshot, e.g. "Synthetic data"')
    parser.add_argument("--alt", default="serp-drift screenshot", help="alt text of the screenshot in the HTML version")
    parser.add_argument("--browser", default=os.environ.get("COMPOSE_BROWSER", DEFAULT_BROWSER))
    parser.add_argument("--cwebp", default=os.environ.get("COMPOSE_CWEBP", DEFAULT_CWEBP))
    parser.add_argument("--profile-dir", type=Path, help="throwaway browser profile (default: a new temporary directory)")
    args = parser.parse_args()

    source = args.source.resolve()
    src_w, src_h = png_size(source)
    focus = args.focus or (0, 0, src_w, src_h)
    if focus[0] + focus[2] > src_w or focus[1] + focus[3] > src_h:
        raise SystemExit(f"focus {focus} falls outside the {src_w}x{src_h} source")
    for tool in (args.browser, args.cwebp, "sips"):
        if not shutil.which(tool):
            raise SystemExit(f"missing tool: {tool}")

    fmt = FORMATS["cover" if args.cover else "primary"]
    name = (args.name or source.stem) + fmt["suffix"]
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    page, master, web_png, web_webp = (out_dir / f"{name}{ext}" for ext in (".html", "@2x.png", ".png", ".webp"))

    box = layout(fmt, focus[2], focus[3])
    title = f"{args.name or source.stem} · serp-drift"
    page.write_text(build_html(source, page, fmt, box, focus, (src_w, src_h), args.theme, args.label, args.alt, title), encoding="utf-8")

    profile = args.profile_dir or Path(tempfile.mkdtemp(prefix="serp-drift-compose-"))
    profile.mkdir(parents=True, exist_ok=True)
    try:
        state = render(args.browser, profile, page, master, box["cw"], box["ch"], (src_w, src_h))
    finally:
        if not args.profile_dir:
            shutil.rmtree(profile, ignore_errors=True)

    run(["sips", "-z", str(box["ch"]), str(box["cw"]), str(master), "--out", str(web_png)])
    run([args.cwebp, "-quiet", "-q", "85", "-m", "6", "-sharp_yuv", str(web_png), "-o", str(web_webp)])

    cw, ch = box["cw"], box["ch"]
    bottom = ch - box["fy"] - box["fh"]
    device_per_source = box["fw"] / focus[2] * SCALE
    print(f"master  {master}  {cw * SCALE}x{ch * SCALE}")
    print(f"web     {web_png}  {cw}x{ch}")
    print(f"webp    {web_webp}")
    print(f"html    {page}")
    print(f"frame   x={box['fx']} y={box['fy']} w={box['fw']} h={box['fh']} CSS px; ratio {box['fw'] / box['fh']:.5f}, "
          f"source{' focus' if args.focus else ''} {focus[2]}x{focus[3]} ratio {focus[2] / focus[3]:.5f}")
    right = cw - box["fx"] - box["fw"]
    print(f"padding left {box['fx']} px ({box['fx'] / cw:.2%})  right {right} px ({right / cw:.2%})  "
          f"top {box['fy']} px ({box['fy'] / ch:.2%})  bottom {bottom} px ({bottom / ch:.2%}, holds the strip)")
    print(f"scale   {device_per_source:.3f} master px and {device_per_source / SCALE:.3f} web px per source px")
    strip = state["credits"][0]
    print(f"strip   x={strip[0]:.1f}-{strip[2]:.1f} y={strip[1]:.1f}-{strip[3]:.1f}; {strip[1] - state['frame'][3]:.1f} px below the frame, "
          f"{ch - strip[3]:.1f} px above the canvas edge")
    print(f"fonts   {', '.join(state['fonts'])}")
    if device_per_source / SCALE > 1.001:
        print("note    the web export upscales the source; use a larger --focus region or a 2x capture", file=sys.stderr)


if __name__ == "__main__":
    main()
