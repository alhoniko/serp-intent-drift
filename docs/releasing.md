# Releasing

1. Update `CHANGELOG.md` (move Unreleased to a version heading) and bump `version` in `pyproject.toml` and `serp_drift/__init__.py`.
2. Run the checks locally: `python -m unittest discover -s tests`, `ruff check .`, `python -m serp_drift demo`.
3. Commit and push `main`, wait for the Check workflow, then tag only that commit: `git tag v0.6.0 && git push origin v0.6.0`. Push the single tag, never `--tags`: pushing a `v*` tag starts the release workflow, which publishes to PyPI.
4. `.github/workflows/release.yml` builds the wheel and sdist, verifies the tag matches the version, attaches the files to a GitHub Release with generated notes, and publishes to PyPI through trusted publishing.

Trusted publishing setup (once): on pypi.org create the project `serp-intent-drift`, add a trusted publisher for `alhoniko/serp-intent-drift`, workflow `release.yml`, environment `pypi`; then create the `pypi` environment in the GitHub repository settings. No API token is stored anywhere.

Users install with `uv tool install serp-intent-drift` or `pipx install serp-intent-drift`; both give the `serp-drift` command.

Before the first public release: configure PyPI trusted publishing (above), make the repository public, and confirm the version in `pyproject.toml`, `serp_drift/__init__.py` and `CHANGELOG.md` match. Until then, install from a checkout or a locally built wheel; do not document `pip install serp-intent-drift` as working.
