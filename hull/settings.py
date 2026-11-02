"""What the app changes, kept between runs in data/settings.json: whether Hull steers Rudder, and the goal
({"text", "focus": [...], "block": [...]}, which replaces the culture stage's focus and block from hull.toml)."""
import json, threading
from pathlib import Path


class Settings:
    def __init__(self, folder):
        self.path = Path(folder) / "settings.json"
        self.lock = threading.Lock()
        try:
            self.data = json.loads(self.path.read_text("utf-8"))
        except (FileNotFoundError, ValueError):
            self.data = {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def update(self, **changes):
        with self.lock:
            self.data.update(changes)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), "utf-8")
            tmp.replace(self.path)
