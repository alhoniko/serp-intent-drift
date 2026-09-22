# nikoalho.fi preview integration

The canonical marketing site is the author's Astro project, kept outside this repository. Older site implementations are not deployment targets for this tool.

The demo is a complete static document. It needs no API key, server endpoint, database, build plugin, or iframe. Astro can publish it directly from `public/`.

## Build a reviewable bundle

From this project root:

```sh
python3 scripts/prepare-site-bundle.py --article path/to/article.md
```

Output:

```text
dist/site-bundle/
  public/
    tools/serp-intent-drift/
      index.html
      report.json
      report.csv
      example-data.json
      methodology.md
      searchapi.md
    downloads/serp-intent-drift-<version>.zip
    og/serp-intent-drift-monitor.png
  src/content/writing/_serp-intent-drift-monitor.md
  manifest.json
  INSTALL.md
```

The source ZIP uses an allowlist: only software, tests, scripts, public docs, and synthetic fixtures. It excludes local configuration, credentials, database files, generated real reports, private notes, and the article itself. Inspect `manifest.json` and the ZIP contents before release.

Copy these files into a **preview checkout** of the Astro site and run its normal build. This script never copies into that project, changes Git state, pushes, or deploys. Do not overwrite unrelated existing files. The new static demo route is `/tools/serp-intent-drift/`; the downloadable source is `/downloads/serp-intent-drift-<version>.zip`.

The article uses the current content schema (`category: Lab`, `draft: true`, TLDR, source list, and explicitly placed article components). Its underscore prefix keeps it outside the site's content glob. This is essential: the current single-article route builds every collection entry, including entries marked as drafts. Remove only the prefix in a local preview checkout when deliberately previewing the article. Never rely on `draft: true` alone to keep its direct URL unpublished in this site's current implementation. The public site's general draft handling was not changed.

If `assets/serp-intent-drift-monitor-og.png` exists beside the supplied article's directory, the bundle includes it under the site's normal OG path. The handoff image was rendered with the current site's existing generator.

## Match the current brand

The demo uses the current Paper/Ink/Voltage/Live Blue palette and a restrained report layout, with sentence-case labels and visible evidence. It follows the current site's operator voice rather than the old WordPress site's more provocative copy. The standalone report uses system font fallbacks so it works offline without font downloads.

## Publish after acceptance

After personal testing and editorial review, remove the article's `draft: true` and underscore prefix in the actual release change, set its real publication date, and resolve the repository URL. Keep synthetic labels on the example findings even after API access exists. Remove the standalone demo's `noindex` meta only if it should be indexed; that is separate from link markup.

Keep the paid-collaboration disclosure visible in the article and demo. Complete editorial review and verify the final article against the release's recorded testing and limitations before publication.

No external tracking code or analytics has been added to the standalone demo. When the final repository URL exists, add it deliberately; the build does not invent or publish a GitHub destination.

## Rollback

Remove the tool's new static directory, source ZIP, and article file from the preview/release change. The collector and SQLite data are separate and do not depend on the marketing site.
