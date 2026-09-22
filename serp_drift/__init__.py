"""SERP Intent Drift Monitor. Runtime dependencies: Python standard library only."""

__version__ = "0.5.0"


def analysis_version() -> str:
    """Rule-pack identity used in every panel hash; stable while the built-in packs are unchanged."""
    from .packs import registry
    return registry().analysis_version()
