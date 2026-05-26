"""JSON override loading for API command profiles.

Reads per-command tuning overrides from ``config/api_profiles.json``
and merges them into the default ``CommandProfile`` instances defined
in ``profiles.py``.  This allows operators to tweak retry counts,
backoff timing, and confirmation timeouts without editing code.

Placeholder — the loading logic will be implemented when the
config schema is finalised.
"""

from pathlib import Path

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "api_profiles.json"


def load_profile_overrides(config_path=None):
    """Load profile overrides from a JSON config file.

    Args:
        config_path: Path to the JSON config file.
            Defaults to ``config/api_profiles.json`` relative to
            the driver package root.

    Returns:
        dict: Mapping of profile name to override kwargs.
            Empty dict if the file does not exist or is empty.
    """
    return {}
