"""Shared operational settings, kept separate from credentials."""
import json
import os
from pathlib import Path


def load_settings():
    path = Path(os.getenv("SMART_CITY_SETTINGS", str(Path(__file__).resolve().parents[1] / "config/settings.json")))
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def analysis_time_limit(request=None, maximum=300):
    """Configured default, explicit request override, and endpoint safety cap."""
    default = load_settings().get("analysis_timeout_seconds", 30)
    return min(maximum, max(0.01, float((request or {}).get("time_limit_s", default))))
