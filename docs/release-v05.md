# 0.5.0 upgrade, validation and rollback

This is a beta release with a stronger evidence and review workflow. It is not an accuracy-certified or accessibility-certified release. “AA++” is a product quality aspiration, not a WCAG conformance level.

## Upgrade safely

Before starting the new release on an existing workspace, use the new checkout to make a consistent backup of the old database. This command reads the source without migrating it:

```sh
python3 -m serp_drift --dir ~/serp-drift backup --out ~/serp-backups/before-0.5.0
```

It backs up SQLite through the SQLite backup API, checks integrity, copies configuration and custom rules, and writes file checksums. It excludes API key files. The backup directory is owner-only; configuration can contain a webhook credential, so keep the entire backup private.

Stop the old collector, install the new source/wheel and start the app. Schema 6 migration is additive: observations, observation reviews, analysis runs and review cases. Original normalized records are backfilled unchanged, with unavailable historic provenance left unverified. Rule-only panel identities stay unchanged. The optional semantic classifier has a new prompt/cache identity and therefore starts a separate baseline. Do not manually join observations from different classifier versions.

```sh
serp-drift --dir ~/serp-drift reanalyze
serp-drift --dir ~/serp-drift serve
```

`reanalyze` records the new versioned drift calculation and refreshes reports. It makes no API requests, changes no captured observations, sends no webhook and does not run a model on historical snippets. Observation exclusion changes only the analysis overlay. For an excluded original provider-context mismatch, restore removes the human exclusion but does not waive the underlying quarantine.

To roll back: stop the collector, retain the current database separately, install the preceding release, restore the pre-upgrade database/config/rules from the backup, and restart. Never open a schema-6 database with an older release or discard its WAL file while running. Retain the new database if decisions or captures accumulated after upgrade. API key files remain where they were.

## Verification record

Validation on 20 September 2026: 118 automated tests passed on Python 3.14; ruff and JavaScript syntax checks passed; source and wheel builds passed; the wheel installed and generated its four-scenario demo in a clean Python 3.13 environment. A Python 3.11 syntax parse passed (the full 3.11 runtime suite remains a CI check). Archive inspection found no local databases, keys or workspaces. Offline reanalysis of 238 real observations across 54 panels preserved every original normalized document byte-for-byte.

The automated suite covers migration preservation, wrong-query quarantine, model null/invalid responses, endpoint/query cache isolation, no transient-failure cache poisoning, whole-window comparison, false-alert suppression, repeated recovery, reversible exclusions, review episodes, webhook retry/deduplication, concurrent config edits, workspace isolation, backup integrity and blind-evaluation metrics. Existing collection/auth/import/MCP tests run alongside these regressions.

Browser checks use copies of real workspaces without their API keys or a scheduler. Checked paths: the responsive evidence view, exclusion and restoration, native keyboard search, saving a review/decision/rationale/follow-up date, light/dark themes and readable uncertainty. The settings page fits a 390-pixel viewport without horizontal page overflow; the inspected light-theme audit text passed a DOM-based contrast check. These checks are not a full assistive-technology or WCAG audit.

Synthetic demo outcomes test the implementation. Real observations test migration and rendering. Neither establishes classifier precision. The human-annotation benchmark remains necessary before claiming top-tier intent detection.

## Publication facts

- The tool is Python standard-library software with a local SQLite database; optional semantic labeling uses a configured compatible endpoint.
- `drift-v3` is an explainable change index. It is not a probability, a Google signal, a traffic forecast or proof that content needs rewriting.
- Search parameters and result evidence are preserved where the provider returns them. Historic missing metadata cannot be reconstructed.
- The first-run UI exposes cadence and request estimates; model settings expose the data sent and result cap. Provider pricing remains external.
- Earlier `docs/media` images show 0.4.0. Capture fresh images for a 0.5.0 article.
- Install from the checkout or a built wheel until the public package is actually published. Do not claim an unverified PyPI install path works.
- The compensated-collaboration disclosure remains required. The existing article draft needs the author's own rewrite and factual review; these notes are an implementation reference, not publication prose.

Public GitHub/PyPI/site publication, sharing real data and sending the article are separate actions.
