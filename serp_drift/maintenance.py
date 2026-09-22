"""Local backup and reproducible analysis; no provider calls and no notifications."""

from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

from .report import build_report, write_report
from .storage import Store, utc_now


def backup(workspace, directory: Path) -> dict:
    if directory.exists():
        raise ValueError('Choose a new backup directory; existing backups are never overwritten.')
    directory.mkdir(parents=True, mode=0o700)
    if workspace.config.is_file():
        shutil.copy2(workspace.config, directory / 'monitor.toml')
        (directory / 'monitor.toml').chmod(0o600)
    if workspace.rules.is_dir():
        shutil.copytree(workspace.rules, directory / 'rules')
    count = 0
    if workspace.database.is_file():
        with closing(sqlite3.connect(workspace.database.resolve().as_uri() + '?mode=ro', uri=True)) as source, closing(sqlite3.connect(directory / 'monitor.sqlite')) as target:
            source.backup(target)
            if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('SQLite backup integrity check failed.')
            count = target.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0]
        (directory / 'monitor.sqlite').chmod(0o600)
    manifest = {'created_at': utc_now(), 'snapshots': count, 'keys_included': False,
                'files': {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(directory.rglob('*')) if p.is_file()}}
    (directory / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest | {'directory': str(directory)}


def reanalyze(config: dict, workspace, out: Path | None = None) -> dict:
    with Store(workspace.database) as store:
        report = build_report(config, store)
        for query in report['queries']:
            store.record_analysis(query)
    write_report(report, out or workspace.reports)
    return {'queries': len(report['queries']), 'method': report['queries'][0]['method'] if report['queries'] else None,
            'observations_changed': 0, 'provider_requests': 0, 'notifications': 0, 'report': str(out or workspace.reports)}
