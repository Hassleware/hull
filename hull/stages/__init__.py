"""Hull's stage kinds. A stage is a class built from its config (a dict from hull.toml) with:

    __init__(config, store)                        # config from hull.toml; store: Hull's data (hull/store.py)
    decide(videos: list[Video]) -> list[Result]   # one Result per video, in order; runs in a worker thread
    describe() -> str                              # a few words for Rudder's popup
    shown(ids: list[str])                          # optional: videos Rudder just put on screen (worker thread)

To add one: write it in this folder and add it to KINDS.
"""
from .repeats import Repeats
from .rules import Rules

KINDS = {"repeats": Repeats, "rules": Rules}
