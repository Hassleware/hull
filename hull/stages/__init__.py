"""Hull's stage kinds. A stage is a class built from its config (a dict from hull.toml) with:

    decide(videos: list[Video]) -> list[Result]   # one Result per video, in order; runs in a worker thread
    describe() -> str                              # a few words for Rudder's popup

To add one: write it in this folder and add it to KINDS.
"""
from .rules import Rules

KINDS = {"rules": Rules}
