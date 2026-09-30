# Compatibility

From 1.0.0 on, serp-drift follows [Semantic Versioning](https://semver.org/). This page lists what that promise covers.

## Stable within 1.x

- **Command line.** The `serp-drift` commands and their documented options: `init`, `serve`, `run`, `schedule`, `key`, `import`, `account`, `where`, `rules`, `export`, `insights`, `digest`, `backup`, `reanalyze`, `benchmark`, `mcp` and `demo`, plus the older `collect`, `report`, `watch`, `validate` and `estimate`. A command or option is removed only in 2.0. Until then it keeps working and prints a deprecation notice for at least one minor release.
- **Workspace config.** `monitor.toml` with `version = 1`. New keys can appear; their defaults keep the current behaviour.
- **Storage.** The SQLite database records its schema version (`PRAGMA user_version`, currently 6). A newer release migrates an older database forward when it opens it. A database written by a newer release is refused, not changed. Run `serp-drift backup` before an upgrade.
- **Exports.** `report.json` (`schema_version` 1) and the research dataset (`serp-drift export`): fields can be added, never renamed or removed.
- **JSON API.** The app's local API under `/api/`, with per-project routes under `/api/p/<project>/`: routes keep their meaning, and responses can gain fields.
- **MCP tools.** `list_panels`, `panel`, `history`, `compare`, `insights`, `citations`, `search_host` and `collect_now` keep their names and arguments; results can gain fields.

## Analysis versions

Scores and statuses come from a named method: `drift-v4` together with the loaded intent rule packs, shown by `serp-drift rules`. A change to the scoring or status rules gets a new method name and a changelog entry. `serp-drift reanalyze` applies it to stored observations without new API calls. Observations themselves are never rewritten.

## Not covered

- The HTML, CSS and JavaScript of the app and the static report. Layout and wording can change in any release.
- Undocumented API fields, internal Python modules and their function signatures.
- Default thresholds and weights. They belong to the analysis method above and change only with a new method name.
