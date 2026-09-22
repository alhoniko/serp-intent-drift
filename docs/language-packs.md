# Language packs

Intent rules live in TOML files, one per language. The built-in packs are `serp_drift/rules/en.toml` and `serp_drift/rules/fi.toml`. A workspace can add or extend languages by placing files in its `rules/` directory; nothing in Python changes.

## Format

```toml
language = "de"      # ISO 639-1 code; matched against the panel's hl
version = 1          # bump when you change patterns
name = "Deutsch"

[rules]
informational = ['\banleitung\b', '\bwas ist\b', '\bwie (?:man|funktioniert)\b']
commercial = ['\bbeste[rn]?\b', '\bvergleich\b', '\btest\b', '\balternativen?\b']
transactional = ['\bkaufen\b', '\bpreis(?:e)?\b', '\bangebot\b']
navigational = ['\banmelden\b', '\blogin\b']

[sections]                     # leading URL path segments, contributed to every language
informational = ['ratgeber', 'wissen']
transactional = ['preise', 'kaufen']
```

Patterns are Python regular expressions, matched case-insensitively against the result title (3 points), snippet (2 points), and the words of the URL path (2 points). A section pattern adds 2 points when the path starts with it. A result needs at least 3 points and a margin of 2 over the runner-up to receive an intent; otherwise it stays `unknown`. Use word stems (`\w*`) for inflected languages, and use negative lookaheads to exclude known false positives such as `best practices`.

## Extending a built-in language

A workspace file with the same `language` as a built-in pack **extends** it: your patterns are appended. Set `replace = true` to use only your patterns.

## What changes when rules change

The effective rule set is part of every panel identity. Built-in packs give `rules-en-fi-v2`. Any workspace pack changes the identity to `rules-…+<languages>-<fingerprint>`, so panels start a fresh baseline; earlier captures stay in the database under the old identity. Change rules deliberately, then re-run `serp-drift run`. `serp-drift rules` prints the loaded packs and the resulting version.

## Contributing a language

Open a pull request that adds `serp_drift/rules/<code>.toml` with at least ten patterns per intent where the language allows, a short comment on stems and known false positives, and a test in `tests/test_monitor.py` with three or four real-looking titles per intent. Keep patterns conservative: an `unknown` is better than a wrong label, because unknowns cannot trigger a page-fit alert.
