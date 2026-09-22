# Contributing

Thanks for looking. The bar is simple: standard library only at runtime, every behaviour covered by an offline test, and honest wording in anything user-facing.

## Set up

```sh
git clone https://github.com/alhoniko/serp-intent-drift && cd serp-intent-drift
python3 -m unittest discover -s tests        # 80-ish tests, a couple of seconds, no network
uvx ruff check .                             # lint (or pip install ruff)
python3 -m serp_drift demo && python3 -m serp_drift serve --static reports/demo
```

`uv sync && uv run serp-drift …` also works if you prefer a managed environment. Python 3.11 through 3.14 are supported and tested in CI.

## What is welcome

- **Language packs.** The most useful contribution: `serp_drift/rules/<lang>.toml` with conservative patterns and a test. See `docs/language-packs.md`.
- **Engines.** Another SearchApi engine that fits the ranked-row schema, with a fixture-based test.
- **Notification formats**, small UI improvements, documentation fixes, and bug reports with a failing test.

## Ground rules

- No runtime dependencies. Development tools are fine.
- Tests must not touch the network; use fixtures and fake openers like the existing tests.
- Keep the analysis version honest: any change to rule packs bumps their `version` so baselines restart deliberately.
- Do not weaken the security model in `ARCHITECTURE.md` (key handling, page-fetch guards, app auth).
- Wording matters. The tool estimates intent from text; do not describe its numbers as measured user intent, Google metrics, or traffic forecasts.

## Pull requests

One topic per PR, tests included, `ruff check .` clean, and a line in `CHANGELOG.md` under Unreleased. Commit messages explain why, not only what.
