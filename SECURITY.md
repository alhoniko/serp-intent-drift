# Security

## Reporting

Email contact@nikoalho.fi with a description and reproduction steps. You will get an answer within a few days. Please do not open a public issue for something that could expose other users' keys or data.

## Supported versions

The latest minor release receives fixes. Older releases are not patched; upgrade instead.

## What the tool protects

- Your SearchApi key: read from the environment or a 0600 file, sent only as a bearer header, never written to URLs, logs, reports, exports, or the database.
- Your machine: optional page fetches refuse private and non-global addresses, non-web ports, and HTTPS downgrades; the app binds to loopback unless you choose otherwise and then requires a token; every mutation needs a custom header and a matching origin.
- Your data: the workspace `.gitignore` excludes the key, the database, reports, and logs; exports escape spreadsheet formulas.

## What it does not protect

- A token-protected app exposed without TLS. Put a reverse proxy with TLS in front of it.
- Webhook URLs stored in `monitor.toml`; treat the file as sensitive if the URL is.
- The content of third-party titles and snippets stored in your database; publishing an export is your decision.
