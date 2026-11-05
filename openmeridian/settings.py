"""Per-user settings, kept the way the family keeps them (%APPDATA%\\OpenMeridian or ~/.config/openmeridian)."""
from __future__ import annotations

import json
import os
import sys
import tempfile

DEFAULTS = {"theme": "", "recent": [], "geometry": "", "revisionworx_path": "", "splitters": {}}


def config_dir() -> str:
    override = os.environ.get("OPENMERIDIAN_CONFIG_DIR")
    if override:
        return override
    if sys.platform.startswith("win"):
        return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming"), "OpenMeridian")
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "openmeridian")


def _openschematix_theme() -> str:
    base = os.environ.get("OPENSCHEMATIX_CONFIG_DIR")
    if not base:
        if sys.platform.startswith("win"):
            base = os.path.join(os.environ.get("APPDATA") or "", "OpenSchematix")
        else:
            base = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "openschematix")
    try:
        with open(os.path.join(base, "settings.json"), encoding="utf-8") as f:
            return str(json.load(f).get("theme") or "")
    except (OSError, ValueError, AttributeError):
        return ""


class Settings:
    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(config_dir(), "settings.json")
        self.data = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in DEFAULTS.items()}
        try:
            with open(self.path, encoding="utf-8") as f:
                loaded = json.load(f)
            for k, v in (loaded.items() if isinstance(loaded, dict) else ()):
                if k in DEFAULTS and isinstance(v, type(DEFAULTS[k])):
                    self.data[k] = v
        except (OSError, ValueError):
            pass
        if not self.data["theme"]:
            self.data["theme"] = _openschematix_theme() or "modern_light"

    def __getitem__(self, k):
        return self.data[k]

    def __setitem__(self, k, v):
        self.data[k] = v

    def add_recent(self, path: str) -> None:
        path = os.path.abspath(path)
        self.data["recent"] = [path] + [p for p in self.data["recent"] if p != path][:7]

    def save(self) -> None:
        try:
            d = os.path.dirname(self.path)
            os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=d, prefix=".settings-", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            pass
