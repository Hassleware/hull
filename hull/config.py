"""hull.toml → settings, with defaults for everything but the stages."""
import tomllib
from pathlib import Path

DEFAULTS = {
    "rudder": {"address": "127.0.0.1:7833", "start_bridge": True},  # Rudder's API (its bridge; Hull runs it if none is)
    "pipeline": {"after": "your-clicks", "when_missing": "hide"},
    "data": {"folder": "data"},
    "stage": [],
}


def load(path):
    path = Path(path)
    cfg = tomllib.loads(path.read_text("utf-8")) if path.exists() else {}
    out = {k: (dict(v, **cfg.get(k, {})) if isinstance(v, dict) else cfg.get(k, v)) for k, v in DEFAULTS.items()}
    ids = set()
    for s in out["stage"]:
        s.setdefault("id", s.get("kind", ""))
        s.setdefault("config", {})
        if s["id"] in ids:
            raise ValueError(f"hull.toml: two stages with the id {s['id']!r}")
        ids.add(s["id"])
    out["data"]["folder"] = str((path.parent / out["data"]["folder"]).resolve())
    return out
