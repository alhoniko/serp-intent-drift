"""Create reviewable website/source artifacts; never write to the live site or deploy."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from serp_drift import __version__
from serp_drift.cli import demo


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "dist/site-bundle")
    parser.add_argument("--article", type=Path, help="Optional reviewed draft; copied with an underscore prefix and draft: true.")
    args = parser.parse_args()
    destination = args.out.resolve()
    if destination == ROOT or ROOT.is_relative_to(destination):
        raise ValueError("Choose a dedicated output directory, not the project root or its ancestor.")
    destination.mkdir(parents=True, exist_ok=True)
    demo_path = destination / "public/tools/serp-intent-drift"
    demo(demo_path)
    demo_html = demo_path / "index.html"
    demo_html.write_text(demo_html.read_text(encoding="utf-8").replace("</head>", '<link rel="canonical" href="https://nikoalho.fi/tools/serp-intent-drift/">\n</head>'), encoding="utf-8")
    for document in ("methodology.md", "searchapi.md"):
        shutil.copy2(ROOT / "docs" / document, demo_path / document)
    shutil.copy2(ROOT / "serp_drift/assets/example-data.json", demo_path / "example-data.json")
    source_name = f"serp-intent-drift-{__version__}.zip"
    source_path = destination / "public/downloads" / source_name
    source_path.parent.mkdir(parents=True, exist_ok=True)
    allowed_roots = {"serp_drift", "tests", "scripts", "examples", "docs", ".github"}
    allowed_files = {"README.md", "LICENSE", "pyproject.toml", ".gitignore", ".env.example", "CHANGELOG.md"}
    with zipfile.ZipFile(source_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(ROOT.rglob("*")):
            relative = path.relative_to(ROOT)
            if not path.is_file() or path.is_symlink() or path.is_relative_to(destination) or "__pycache__" in relative.parts:
                continue
            if (relative.parts[0] in allowed_roots or str(relative) in allowed_files) and path.suffix not in {".pyc", ".sqlite"}:
                archive.write(path, f"serp-intent-drift-{__version__}/{relative.as_posix()}")
    if args.article:
        content = args.article.read_text(encoding="utf-8")
        if "\ndraft: true\n" not in content:
            raise ValueError("The supplied article must explicitly contain draft: true.")
        target = destination / "src/content/writing/_serp-intent-drift-monitor.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        og_image = args.article.parent / "assets" / "serp-intent-drift-monitor-og.png"
        if og_image.is_file():
            og_destination = destination / "public/og/serp-intent-drift-monitor.png"
            og_destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(og_image, og_destination)
    manifest = {"version": __version__, "demo_route": "/tools/serp-intent-drift/", "source_download": f"/downloads/{source_name}",
                "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(), "contains_live_data": False,
                "publication_status": "Local preview bundle. Nothing installed or published."}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (destination / "INSTALL.md").write_text("# Preview installation\n\nCopy public/ into the Astro site's public/ directory. If present, copy src/ into src/. The article keeps both its underscore prefix and draft: true, so it cannot publish accidentally. Build the site in a preview checkout and open /tools/serp-intent-drift/. No existing routes need to change. See the source project's docs/site-integration.md for the release checklist.\n", encoding="utf-8")
    print(destination)


if __name__ == "__main__":
    main()
