"""What a stage sees and says. Video mirrors Rudder's video record (rudder.proto: Video) as plain Python."""
from dataclasses import dataclass, field

FIELDS = ("id", "title", "channel", "description", "published", "duration_seconds", "seen_at_ms",
          "thumbnail", "thumbnail_type", "thumbnail_url", "source", "short")
DECISIONS = ("pass", "hide", "show")


@dataclass
class Video:
    id: str
    title: str = ""
    channel: str = ""
    description: str = ""  # often empty: YouTube only sends one in search results and for played videos
    published: str = ""  # "3 days ago", or a date once played; may be empty
    duration_seconds: int = 0
    seen_at_ms: int = 0
    thumbnail: bytes = b""  # the image Firefox downloaded; empty if it came from the browser's cache
    thumbnail_type: str = ""
    thumbnail_url: str = ""
    source: str = ""  # browse, next, search, reel_watch_sequence, player, page, tile
    short: bool = False
    fields: dict[str, str] = field(default_factory=dict)  # from earlier stages: thumbnail_text, dislike_chance, ...

    @classmethod
    def from_pb(cls, v):
        return cls(**{f: getattr(v, f) for f in FIELDS}, fields=dict(v.fields))


@dataclass
class Result:
    decision: str = "pass"  # "hide", "show" or "pass" (no opinion: on to the next stage)
    why: str = ""  # shown in Rudder's popup
    fields: dict[str, str] = field(default_factory=dict)  # added to the video's record for later stages

    def __post_init__(self):
        if self.decision not in DECISIONS:
            raise ValueError(f"decision {self.decision!r} isn't one of {DECISIONS}")
