# Releasing

1. Update `CHANGELOG.md` (move Unreleased to a version heading) and bump `version` in `pyproject.toml` and `serp_drift/__init__.py`.
2. Run the checks locally: `python -m unittest discover -s tests`, `ruff check .`, `python -m serp_drift demo`.
3. Commit, then tag: `git tag v0.3.0 && git push origin main --tags`.
4. `.github/workflows/release.yml` builds the wheel and sdist, verifies the tag matches the version, attaches the files to a GitHub Release with generated notes, and publishes to PyPI through trusted publishing.

Trusted publishing setup (once): on pypi.org create the project `serp-intent-drift`, add a trusted publisher for `alhoniko/serp-intent-drift`, workflow `release.yml`, environment `pypi`; then create the `pypi` environment in the GitHub repository settings. No API token is stored anywhere.

Users install with `uv tool install serp-intent-drift` or `pipx install serp-intent-drift`; both give the `serp-drift` command.
