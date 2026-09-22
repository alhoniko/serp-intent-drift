"""Generate and install the scheduler entry for this machine: launchd on macOS, systemd on Linux, cron anywhere."""

import getpass
import hashlib
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import subprocess
import sys

from .workspace import Workspace


def label_for(workspace: Workspace) -> str:
    return f"io.serp-drift.{hashlib.sha256(str(workspace.root).encode()).hexdigest()[:10]}"


def source_root() -> Path | None:
    """The directory that makes `import serp_drift` work when running from a checkout rather than an installed package."""
    package = Path(__file__).resolve().parent
    return package.parent if (package.parent / "pyproject.toml").is_file() else None


def command_for(workspace: Workspace, mode: str, *, port: int, extra_dirs: list[Path] | None = None) -> list[str]:
    """Prefer the installed console script; otherwise the interpreter with -m, which then needs PYTHONPATH (see environment_for)."""
    executable = shutil.which("serp-drift")
    base = [executable, "--dir", str(workspace.root)] if executable else [sys.executable, "-m", "serp_drift", "--dir", str(workspace.root)]
    if mode == "app":
        command = [*base, "serve", "--port", str(port)]
        for extra in extra_dirs or []:
            command += ["--also", str(Path(extra).expanduser().resolve())]
        return command
    return [*base, "run"]


def environment_for() -> dict[str, str]:
    """A short PATH plus PYTHONPATH for source checkouts, so the job runs from any working directory."""
    env = {"PATH": f"{Path(sys.executable).parent}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin", "LANG": "en_US.UTF-8", "PYTHONUNBUFFERED": "1"}
    root = source_root()
    if root and not shutil.which("serp-drift"):
        env["PYTHONPATH"] = str(root)
    return env


def parse_time(value: str) -> tuple[int, int]:
    try:
        hour, minute = (int(part) for part in value.split(":"))
    except ValueError:
        raise ValueError("--time must look like 08:17.") from None
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError("--time must be a valid HH:MM.")
    return hour, minute


def launchd_plist(workspace: Workspace, mode: str, *, time: str, port: int, extra_dirs: list[Path] | None = None) -> bytes:
    """A LaunchAgent. `app` keeps serve running; `run` fires daily and launchd runs a missed job after wake-up."""
    hour, minute = parse_time(time)
    plist = {
        "Label": label_for(workspace),
        "ProgramArguments": command_for(workspace, mode, port=port, extra_dirs=extra_dirs),
        "WorkingDirectory": str(workspace.root),
        "StandardOutPath": str(workspace.logs / "launchd.log"),
        "StandardErrorPath": str(workspace.logs / "launchd.log"),
        "EnvironmentVariables": environment_for(),
    }
    if mode == "app":
        plist |= {"RunAtLoad": True, "KeepAlive": True}
    else:
        plist |= {"StartCalendarInterval": {"Hour": hour, "Minute": minute}}
    return plistlib.dumps(plist, sort_keys=False)


def systemd_units(workspace: Workspace, mode: str, *, time: str, port: int, extra_dirs: list[Path] | None = None) -> dict[str, str]:
    """User units. `app` is a long-running service; `run` is a service plus a persistent daily timer."""
    hour, minute = parse_time(time)
    command = " ".join(shlex.quote(part) for part in command_for(workspace, mode, port=port, extra_dirs=extra_dirs))
    service = f"""[Unit]
Description=serp-drift {'app' if mode == 'app' else 'collection'} ({workspace.root})
After=network-online.target

[Service]
Type={'simple' if mode == 'app' else 'oneshot'}
WorkingDirectory={workspace.root}
ExecStart={command}
{'Restart=on-failure' + chr(10) + 'RestartSec=10' if mode == 'app' else ''}
{chr(10).join(f"Environment={key}={shlex.quote(value)}" for key, value in environment_for().items())}

[Install]
WantedBy=default.target
"""
    units = {"serp-drift.service": service}
    if mode == "run":
        units["serp-drift.timer"] = f"""[Unit]
Description=Daily serp-drift collection

[Timer]
OnCalendar=*-*-* {hour:02d}:{minute:02d}:00
Persistent=true

[Install]
WantedBy=timers.target
"""
    return units


def cron_line(workspace: Workspace, *, time: str) -> str:
    hour, minute = parse_time(time)
    command = " ".join(shlex.quote(part) for part in command_for(workspace, "run", port=8765))
    env = environment_for()
    prefix = f"PYTHONPATH={shlex.quote(env['PYTHONPATH'])} " if "PYTHONPATH" in env else ""
    return f"{minute} {hour} * * * {prefix}{command} >> {shlex.quote(str(workspace.logs / 'cron.log'))} 2>&1"


def plan(workspace: Workspace, mode: str, *, time: str, port: int, platform: str | None = None, extra_dirs: list[Path] | None = None) -> dict:
    """Everything `schedule` would write and execute, without doing it."""
    platform = platform or sys.platform
    workspace.logs.mkdir(parents=True, exist_ok=True)
    if platform == "darwin":
        path = Path.home() / "Library" / "LaunchAgents" / f"{label_for(workspace)}.plist"
        domain = f"gui/{os.getuid()}"
        return {"platform": "launchd", "files": {str(path): launchd_plist(workspace, mode, time=time, port=port, extra_dirs=extra_dirs).decode()},
                "install": [["launchctl", "bootout", domain, str(path)], ["launchctl", "bootstrap", domain, str(path)]],
                "uninstall": [["launchctl", "bootout", domain, str(path)]],
                "note": "launchd runs a missed daily job after the Mac wakes; the app mode keeps serve alive and restarts it."}
    if platform.startswith("linux"):
        directory = Path.home() / ".config" / "systemd" / "user"
        units = systemd_units(workspace, mode, time=time, port=port, extra_dirs=extra_dirs)
        target = "serp-drift.timer" if mode == "run" else "serp-drift.service"
        return {"platform": "systemd", "files": {str(directory / name): body for name, body in units.items()},
                "install": [["systemctl", "--user", "daemon-reload"], ["systemctl", "--user", "enable", "--now", target]],
                "uninstall": [["systemctl", "--user", "disable", "--now", target]],
                "note": f"User units need `loginctl enable-linger {getpass.getuser()}` to run while you are logged out. Cron alternative: {cron_line(workspace, time=time)}"}
    return {"platform": "cron", "files": {}, "install": [], "uninstall": [],
            "note": f"Add this line with `crontab -e`:\n{cron_line(workspace, time=time)}"}


def apply(plan_data: dict, *, uninstall: bool = False) -> list[str]:
    """Write the files and run the platform commands. Returns the log of what happened."""
    log = []
    commands = plan_data["uninstall"] if uninstall else plan_data["install"]
    if not uninstall:
        for path, body in plan_data["files"].items():
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(body, encoding="utf-8")
            log.append(f"wrote {path}")
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True)
        tolerated = uninstall or (command[1:2] == ["bootout"])  # a bootout before bootstrap fails harmlessly when nothing is loaded
        log.append(f"{'ok' if result.returncode == 0 else ('skipped' if tolerated else 'FAILED')}: {' '.join(command)}{(' · ' + result.stderr.strip()) if result.returncode and not tolerated else ''}")
        if result.returncode and not tolerated:
            raise ValueError("\n".join(log))
    if uninstall:
        for path in plan_data["files"]:
            if Path(path).exists():
                Path(path).unlink()
                log.append(f"removed {path}")
    return log
