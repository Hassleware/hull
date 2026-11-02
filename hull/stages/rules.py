"""Your own rules: regular expressions over a video's title, channel, description and thumbnail text.
The first rule that matches decides; no match passes the video on.

config: { "rules": [ { "pattern": "los santos|\\bgta\\b", "action": "hide", "why": "GTA" }, ... ] }
"""
import re

from hull.video import DECISIONS, Result


class Rules:
    def __init__(self, config, store=None):
        self.rules = []
        for r in config.get("rules", []):
            action = r.get("action", "hide")
            if action not in DECISIONS:
                raise ValueError(f"rule {r.get('pattern')!r}: action must be one of {DECISIONS}")
            self.rules.append((re.compile(r["pattern"], re.IGNORECASE), action, r.get("why") or r["pattern"]))

    def decide(self, videos):
        out = []
        for v in videos:
            text = "\n".join((v.title, v.channel, v.description, v.fields.get("thumbnail_text", "")))
            out.append(next((Result(action, why) for pattern, action, why in self.rules if pattern.search(text)), Result()))
        return out

    def describe(self):
        return f"{len(self.rules)} rules"
