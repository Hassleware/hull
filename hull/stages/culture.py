"""Culture: Gemma names each video's topics, from its exact subject up to its broad field, and they go into the
culture graph (hull/graph.py). A video is tagged once; after that it's answered from the graph at once.

Gemma runs in Ollama with the title, channel, description, Rudder's thumbnail text and the thumbnail itself, plus
the known topics nearest the video, so it reuses the graph's names. Videos not tagged within `budget` seconds are
hidden for now (strict) and keep being tagged; Rudder asks again the next time YouTube sends them.

Then the graph decides (relatedness: hull/graph.py):
  - block: a video with a topic at least `block_at` near a blocked topic is hidden, e.g. block = ["grand theft
    auto"] hides Los Santos, GTA RP, Michael De Santa;
  - focus: when set, only videos with a topic at least `focus_at` near a focus topic are shown, e.g. focus =
    ["bayesian statistics"] for a student learning just that.

config: { "model": "gemma4:e4b", "embed_model": "embeddinggemma", "ollama": "http://127.0.0.1:11434",
          "parallel": 6,     # requests to Ollama at once
          "budget": 18,      # seconds per batch, under Rudder's 25
          "merge": 0.94,     # cosine at which a new topic name is an old one
          "block": [], "block_at": 0.85, "focus": [], "focus_at": 0.75 }
"""
import concurrent.futures as cf, io, logging, threading

import numpy as np
from PIL import Image

from hull.graph import Graph
from hull.ollama import Ollama
from hull.video import Result

log = logging.getLogger("hull")
SCHEMA = {"type": "object", "properties": {"topics": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 6}},
          "required": ["topics"]}
SYSTEM = "You map YouTube videos onto the topics they are about, for a map of what a viewer is exposed to."
PROMPT = """Name this YouTube video's topics: 3 to 6 short lowercase noun phrases, from the most specific (the exact subject: the game, show, person, technique or idea) up to its broad field (such as "video games", "statistics", "cooking", "music").
Name subjects, not formats: in "100 days in Los Santos" the subject is the game Los Santos belongs to (grand theft auto v), not "100 days challenge". Name the franchise or field a place, character or term belongs to. Use the thumbnail too.
Topics already on this viewer's map, to reuse word for word when one fits: {known}

Title: {title}
Channel: {channel}
Description: {description}
Text in the thumbnail: {thumbnail_text}"""


def jpeg(image):
    """thumbnails as small JPEGs (Ollama doesn't read WebP)"""
    try:
        img = Image.open(io.BytesIO(image)).convert("RGB")
        img.thumbnail((480, 360))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        return [buf.getvalue()]
    except Exception:
        return []


class Culture:
    def __init__(self, config, store):
        self.ollama = Ollama(config.get("ollama", "http://127.0.0.1:11434"))
        self.model, self.budget = config.get("model", "gemma4:e4b"), config.get("budget", 18)
        self.graph = Graph(store, self.ollama, config.get("embed_model", "embeddinggemma"), config.get("merge", 0.94))
        self.pool = cf.ThreadPoolExecutor(config.get("parallel", 6))
        self.tagging, self.lock = {}, threading.Lock()  # video id → its tagging, while it runs
        self.block, self.block_at = [t.lower() for t in config.get("block", [])], config.get("block_at", 0.85)
        self.focus, self.focus_at = [t.lower() for t in config.get("focus", [])], config.get("focus_at", 0.75)
        self.anchor_vecs = {}  # block/focus topic → its embedding

    def warm(self):
        """load both models before Rudder sends anything (a cold Gemma takes ~50 s, past Rudder's 25)"""
        self.ollama.timeout = 300
        self.ollama.json(self.model, "Say ok.", {"type": "object", "properties": {"ok": {"type": "string"}}})
        self.anchors(self.block + self.focus)
        self.ollama.timeout = 60

    def tag(self, v):
        known = ", ".join(self.graph.nearest(self.graph.embed([f"{v.title} — {v.channel}"])[0])) or "(none yet)"
        r = self.ollama.json(self.model, PROMPT.format(known=known, title=v.title, channel=v.channel or "unknown",
                                                       description=v.description[:500] or "none",
                                                       thumbnail_text=v.fields.get("thumbnail_text") or "none"),
                             SCHEMA, jpeg(v.thumbnail) if v.thumbnail else [], SYSTEM)
        return self.graph.attest(v.id, r["topics"])

    def _start(self, v):
        with self.lock:
            f = self.tagging.get(v.id)
            if f is None:
                f = self.tagging[v.id] = self.pool.submit(self.tag, v)
                f.add_done_callback(lambda _: self._done(v.id, f))
            return f

    def _done(self, vid, f):
        with self.lock:
            self.tagging.pop(vid, None)
        if f.exception():
            log.warning("couldn't tag %s: %s", vid, f.exception())

    def topics(self, videos):
        """each video's topics, or None if not tagged within the budget"""
        known = {v.id: self.graph.topics_of(v.id) for v in videos}
        todo = {v.id: self._start(v) for v in videos if known[v.id] is None}
        cf.wait(todo.values(), self.budget)
        for vid, f in todo.items():
            known[vid] = f.result() if f.done() and not f.exception() else None
        return [known[v.id] for v in videos]

    def anchors(self, names):
        missing = [n for n in names if n not in self.anchor_vecs]
        if missing or not names:
            for n, v in zip(missing or ["warm"], self.graph.embed(missing or ["warm"])):
                self.anchor_vecs[n] = v
        return names, (np.array([self.anchor_vecs[n] for n in names]) if names else None)

    def judge(self, topics):
        fields = {"topics": "; ".join(topics)}
        if self.block:
            s, topic, anchor, via = self.graph.nearness(topics, *self.anchors(self.block))
            if s >= self.block_at:
                return Result("hide", f"{topic} is near {anchor}" + (f" (through {via})" if via else ""), fields)
        if self.focus:
            s, topic, anchor, via = self.graph.nearness(topics, *self.anchors(self.focus))
            fields["focus"] = f"{s:.2f} {topic}" + (f" through {via}" if via else "")
            if s < self.focus_at:
                return Result("hide", f"off focus (nearest: {topic}, {s:.2f})", fields)
        return Result(fields=fields)

    def decide(self, videos):
        return [self.judge(t) if t else Result("hide", "not tagged yet") for t in self.topics(videos)]

    def describe(self):
        s = self.graph.stats()
        return f"{s['tagged']} videos on {s['topics']} topics"
