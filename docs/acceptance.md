# Acceptance testing and release gate

For 1.0.0, start with [the changelog](../CHANGELOG.md), whose known limits apply, and the [human benchmark](evaluation.md); the 0.6 [release notes and verification record](release-v06.md) still describe how collection checks were verified. Automated checks verify software behavior; they do not measure intent accuracy. The following tests require the operator's credentials, judgment, or publication environment. They are intentionally not marked as passed by synthetic tests.

## Offline verification

```sh
python3 -m unittest discover -s tests -v
python3 -m serp_drift validate --config examples/monitor.example.toml
python3 -m serp_drift demo
```

Expected: four demo scenarios and the exact outcomes in `docs/methodology.md`. Open the report on desktop and mobile; filter queries, inspect evidence, and download JSON/CSV. Inspect a sparse panel and confirm that it cannot assert a current content mismatch.

## Live SearchApi acceptance

Record: steps 1–4 were completed on 16 September 2026 with one US/English/desktop panel (one credit per search, eight organic results, repeat collection skipped without a request). Step 5: two nikoalho.fi panels fetch their public page at every capture; the stored profile shows the fetched basis and lexical evidence (checked 23 September). Step 6: 54 panels collected daily 16–22 September; baselines completed and later captures were compared. It also exposed query-mismatched captures, handled from 0.6.0. Step 7 was applied once to a single capture and produced `rules-en-fi-v2`; a human-labelled sample is exported but not yet annotated. Step 8 passed on 22 September 2026 (0.6.0 RC): an invalid key gave exit code 1, one failed `http_401` attempt, no snapshot, a `collection_error` report, and the key appeared in no log or report. Step 9: launchd on the operator's Mac has run `serve` with its scheduler since 16 September; a machine-sleep gap has not been deliberately tested.

1. Activate API access. Set `SEARCHAPI_API_KEY` outside source control. Run `account` and record actual credit balance/hourly limits privately.
2. Use one query, an explicit country/language/device, and a page you own. Run `validate` and `estimate` before spending search credits.
3. Run `collect`, then `report`. Confirm exactly one stored snapshot and one request on a successful run without retries. Compare returned ranks, titles, URLs, snippets, and feature observations against SearchApi's dashboard for that request.
4. Run `collect` again before the interval has elapsed. Expect `skipped=1` and `requests=0`.
5. Enable `fetch = true` for your page, or provide a current local export. Confirm source, content fingerprint, inferred intent, and lexical evidence. A public-page fetch must not carry the SearchApi Authorization header.
6. Collect five interval-spaced captures. The first three form the baseline; only later captures can confirm a change. Do not assume a real query will drift during the test. Use the synthetic demo to exercise the deliberate change scenario.
7. Inspect a manually labeled sample of results in your actual market. Record obvious false classifications and tune the explicit rules before claiming accuracy. If a rule changes, bump `ANALYSIS_VERSION` and start the corresponding new baseline.
8. Temporarily use an invalid API key. Expect a nonzero exit, a failed attempt, unchanged snapshot count, no key in logs, and a collection-error report after regenerating it. Restore the real key afterwards.
9. Test the scheduler once on the intended always-on machine. Confirm paths, secret loading, timer timezone, log output, report update, and failure exit behavior. Confirm the machine sleeping or the collector stopping becomes an overdue state when the report is next generated.

## Publication acceptance

- Complete personal testing and editorial review before publication. Replace draft-only notes and verify every claim against the recorded evidence.
- Create the public GitHub repository from the verified local repository, choose the final repository URL, and add it to the README/article/demo where useful.
- Inspect the exact archive before publishing. It must contain source and synthetic examples only; exclude `monitor.toml`, `.env`, local databases, real reports, and private handoff notes.
- Install the prepared site bundle in a preview checkout. Validate the Astro build, open the standalone demo, and check downloads and internal links.
- Keep the paid-collaboration disclosure visible wherever the tool is presented.
- Publishing the GitHub repository, website, article, or a release is a separate action. No deployment or push is performed by the build scripts.

## Recovery

Stop the collector before moving its database. Keep the SQLite file and any `-wal`/`-shm` files together, or create a proper SQLite backup. Use a new database path to reset a study rather than deleting the existing history. Report files can be regenerated; they are not the canonical store. Remove only this tool's copied site files to roll back the preview integration.

