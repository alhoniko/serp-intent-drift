# Deployment

The app is one Python process with no dependencies, so every option below is a way to keep `serp-drift serve` (or a daily `serp-drift run`) alive on a machine you control.

## Laptop or desktop

```sh
serp-drift schedule            # print what would be installed
serp-drift schedule --install  # register it
```

On macOS this writes a LaunchAgent that starts the app at login and restarts it if it stops; the in-process scheduler collects due panels. Use `--mode run --time 08:17` for a daily job instead of a resident app; launchd runs a missed job after the Mac wakes. On Linux the same command writes user systemd units (a persistent timer in run mode). `--uninstall` removes them. Anywhere else, the command prints a crontab line.

## Server without Docker

Install the package for a dedicated user, create the workspace with `serp-drift init --dir /srv/serp-drift`, put the key in `/srv/serp-drift/searchapi.key` (0600) and a token in `/etc/serp-drift.env` as `SERP_DRIFT_TOKEN=…`, then install [`deploy/serp-drift.service`](../deploy/serp-drift.service). Keep the app on `127.0.0.1` and terminate TLS with a reverse proxy; [`deploy/Caddyfile.example`](../deploy/Caddyfile.example) is enough for Caddy.

## Docker

```sh
mkdir workspace && serp-drift init --dir workspace --no-prompt   # or create monitor.toml by hand
echo "SERP_DRIFT_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')" > .env
docker compose up -d --build
```

The image runs as an unprivileged user, keeps everything in the mounted `workspace/` directory, and publishes the port on localhost only. Open `http://127.0.0.1:8765/?token=…` once; the app sets a cookie. Put the key in `workspace/searchapi.key` or pass `SEARCHAPI_API_KEY` in `.env`.

## GitHub Actions

For a workspace that lives in a repository and needs no server at all, see [`docs/github-actions.md`](github-actions.md).

## Backups

The workspace directory is the whole state. Stop the collector before copying `data/monitor.sqlite` together with its `-wal`/`-shm` files, or use `sqlite3 data/monitor.sqlite ".backup backup.sqlite"` while it runs.
