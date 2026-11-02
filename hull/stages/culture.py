"""Culture: Gemma names each video's topics, from its exact subject up to its broad field, and they go into the
culture graph (hull/graph.py). A video is tagged once; after that it's answered from the graph at once.

Gemma runs in Ollama with the title, channel, description, Rudder's thumbnail text and the thumbnail itself, plus
the known topics nearest the video, so it reuses the graph's names. A video you watch is tagged again once enough of
it has been said (`heard_chars` of its captions): its title and what's said in it, so watched videos are mapped by
their content, not just how they're sold (table watched). Videos not tagged within `budget` seconds are
hidden for now (strict) and keep being tagged; Rudder asks again the next time YouTube sends them.

Then the graph decides (relatedness: hull/graph.py):
  - block: a video with a topic at least `block_at` near a blocked topic is hidden, e.g. block = ["grand theft
    auto"] hides Los Santos, GTA RP, Michael De Santa;
  - focus: when set, only videos with a topic at least `focus_at` near a focus topic are shown, e.g. focus =
    ["bayesian statistics"] for a student learning just that.
  - In between (from `block_ask` up to block_at, from `focus_ask` up to focus_at) Gemma decides: is this topic part
    of that one? It sees the topic's neighbours in the graph and videos about it. Asked once per pair, kept in
    hull.db (judgements). A video waiting on that answer past the budget is hidden for now.

config: { "model": "gemma4:e4b", "embed_model": "embeddinggemma", "ollama": "http://127.0.0.1:11434",
          "parallel": 6,     # requests to Ollama at once
          "budget": 18,      # seconds per batch, under Rudder's 25
          "merge": 0.94,     # cosine at which a new topic name is an old one
          "heard_chars": 600,  # captions heard before a watched video is tagged again from them
          "block": [], "block_at": 0.85, "block_ask": 0.7,
          "focus": [], "focus_at": 0.75, "focus_ask": 0.62 }
"""
import concurrent.futures as cf, io, logging, threading, time

import numpy as np
from PIL import Image

from hull.graph import Graph
from hull.ollama import Ollama
from hull.video import Result, Video

log = logging.getLogger("hull")
SCHEMA = {"type": "object", "properties": {"topics": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 6}},
          "required": ["topics"]}
SYSTEM = "You map YouTube videos onto the topics they are about, for a map of what a viewer is exposed to."
ASK_SCHEMA = {"type": "object", "properties": {"part_of": {"type": "boolean"}, "why": {"type": "string"}}, "required": ["part_of", "why"]}
ASK = """On a viewer's map of the topics of the YouTube videos they see, is "{topic}" part of "{anchor}"? That is: is a video about {topic} a video about {anchor}?
Topics that share videos with "{topic}" on the map: {neighbours}
Videos about "{topic}": {titles}
Answer part_of, and why in a few words."""
GOAL_SCHEMA = {"type": "object", "properties": {
    "focus": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
    "block": {"type": "array", "items": {"type": "string"}, "maxItems": 8}}, "required": ["focus", "block"]}
GOAL = """A viewer says what they want YouTube for. Turn it into topics for their filter:
- focus: only if they want nothing but certain subjects (they say "only", "just", "nothing else"): those subjects. Otherwise focus is empty: liking something is not wanting only it;
- block: subjects they never want to see.
Short lowercase noun phrases naming the subject or field itself, like "bayesian statistics" or "grand theft auto". Reuse these topics from their map, word for word, when one fits: {known}

The viewer: {text}"""
PROMPT = """Name this YouTube video's topics: 3 to 6 short lowercase noun phrases, from the most specific (the exact subject: the game, show, person, technique or idea) up to its broad field (such as "video games", "statistics", "cooking", "music").
Name subjects, not formats: in "100 days in Los Santos" the subject is the game Los Santos belongs to (grand theft auto v), not "100 days challenge". Name the franchise or field a place, character or term belongs to. Use the thumbnail too.
Topics already on this viewer's map, to reuse word for word when one fits: {known}

Title: {title}
Channel: {channel}
Description: {description}
Text in the thumbnail: {thumbnail_text}"""
HEARD = """

The viewer watched this video. What's said in it (its captions, as far as they watched): {said}"""


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
        self.block_ask, self.focus_ask = config.get("block_ask", 0.7), config.get("focus_ask", 0.62)
        self.anchor_vecs = {}  # block/focus topic → its embedding
        store.db.execute("create table if not exists judgements (topic text, anchor text, part_of integer, why text, primary key (topic, anchor))")
        self.db = store.db
        self.verdicts = {(t, a): (bool(p), w) for t, a, p, w in store.db.execute("select * from judgements")}
        self.asking = {}  # (topic, anchor) → Gemma's answer, while it runs
        store.db.execute("create table if not exists watched (video_id text primary key, at real, topics text)")
        self.heard_chars = config.get("heard_chars", 600)
        self.said = {}  # video id → its captions heard so far, until it's tagged from them
        self.retagged = {r[0] for r in store.db.execute("select video_id from watched")}

    def warm(self):
        """load both models before Rudder sends anything (a cold Gemma takes ~50 s, past Rudder's 25)"""
        self.ollama.timeout = 300
        self.ollama.json(self.model, "Say ok.", {"type": "object", "properties": {"ok": {"type": "string"}}})
        self.anchors(self.block + self.focus)
        self.ollama.timeout = 60

    def tag(self, v, said=""):
        known = ", ".join(self.graph.nearest(self.graph.embed([f"{v.title} — {v.channel}"])[0])) or "(none yet)"
        prompt = PROMPT.format(known=known, title=v.title, channel=v.channel or "unknown", description=v.description[:500] or "none",
                               thumbnail_text=v.fields.get("thumbnail_text") or "none") + (HEARD.format(said=said[:2500]) if said else "")
        r = self.ollama.json(self.model, prompt, SCHEMA, jpeg(v.thumbnail) if v.thumbnail else [], SYSTEM)
        return self.graph.attest(v.id, r["topics"])

    def heard(self, video_id, text):
        """a caption line of a video you're watching: once enough is said, Gemma tags it again from it (once per video)"""
        with self.lock:
            if video_id in self.retagged:
                return
            self.said[video_id] = (self.said.get(video_id, "") + " " + text).strip()
            if len(self.said[video_id]) < self.heard_chars:
                return
            said = self.said.pop(video_id)
            self.retagged.add(video_id)
        row = self.db.execute("select title, channel, description from videos where id = ?", (video_id,)).fetchone()
        v = Video(video_id, *(row or ("", "", "")))

        def work():
            topics = self.tag(v, said)
            self.db.execute("insert or replace into watched values (?,?,?)", (video_id, time.time(), "; ".join(topics)))
            self.db.commit()
            log.info("watched %s: %s", v.title or video_id, ", ".join(topics))
        f = self.pool.submit(work)
        f.add_done_callback(lambda f: f.exception() and log.warning("couldn't tag %s from its captions: %s", video_id, f.exception()))
        return f

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
        # ponytail: tagging can use the whole budget, leaving Gemma's judgements none; split it if both often run long
        known = {v.id: self.graph.topics_of(v.id) for v in videos}
        todo = {v.id: self._start(v) for v in videos if known[v.id] is None}
        cf.wait(todo.values(), self.budget)
        for vid, f in todo.items():
            known[vid] = f.result() if f.done() and not f.exception() else None
        return [known[v.id] for v in videos]

    def draft_goal(self, text):
        """a goal in the viewer's words → {"text", "focus": [...], "block": [...]}, drafted by Gemma with the map's names"""
        known = ", ".join(self.graph.nearest(self.graph.embed([text])[0], 20)) or "(none yet)"
        r = self.ollama.json(self.model, GOAL.format(known=known, text=text), GOAL_SCHEMA, system=SYSTEM)
        clean = lambda xs: list(dict.fromkeys(x.strip().lower() for x in xs if x.strip()))
        return {"text": text.strip(), "focus": clean(r["focus"]), "block": clean(r["block"])}

    def marks(self, names):
        """what the goal does with each topic, for the culture map: "focus", "block", "ask" (Gemma hasn't decided yet) or
        None. Only what's known: it never asks Gemma or embeds anything new."""
        if any(n not in self.anchor_vecs for n in self.focus + self.block):
            return {}
        out = {}
        for name in names:
            for anchors, at, ask, mark in ((self.block, self.block_at, self.block_ask, "block"), (self.focus, self.focus_at, self.focus_ask, "focus")):
                if not anchors or name not in self.graph.index:
                    continue
                s, _, anchor, _ = self.graph.nearness([name], *self.anchors(anchors))
                if s >= at:
                    out[name] = mark
                elif s >= ask:
                    v = self.verdicts.get((name, anchor))
                    out[name] = "ask" if v is None else (mark if v[0] else None)
                if out.get(name):
                    break
        return out

    def set_goal(self, focus, block):
        self.focus, self.block = [t.lower() for t in focus], [t.lower() for t in block]

    def anchors(self, names):
        missing = [n for n in names if n not in self.anchor_vecs]
        if missing or not names:
            for n, v in zip(missing or ["warm"], self.graph.embed(missing or ["warm"])):
                self.anchor_vecs[n] = v
        return names, (np.array([self.anchor_vecs[n] for n in names]) if names else None)

    def ask(self, topic, anchor):
        """Gemma's answer to "is topic part of anchor?" (part_of, why), with the graph as context"""
        neighbours = ", ".join(u for u, _ in self.graph.neighbours(topic)[:8]) or "none yet"
        titles = "; ".join(r[0] for r in self.db.execute("""select v.title from video_topics vt join topics t on t.id = vt.topic_id
                                                           join videos v on v.id = vt.video_id where t.name = ? limit 5""", (topic,))) or "none recorded"
        r = self.ollama.json(self.model, ASK.format(topic=topic, anchor=anchor, neighbours=neighbours, titles=titles), ASK_SCHEMA, system=SYSTEM)
        with self.lock:
            self.verdicts[(topic, anchor)] = (bool(r["part_of"]), str(r["why"])[:200])
            self.db.execute("insert or replace into judgements values (?,?,?,?)", (topic, anchor, int(r["part_of"]), str(r["why"])[:200]))
            self.db.commit()
            self.asking.pop((topic, anchor), None)

    def verdict(self, topic, anchor):
        """(part_of, why) once Gemma has answered; None while it thinks (and starts it thinking)"""
        with self.lock:
            if (topic, anchor) in self.verdicts:
                return self.verdicts[(topic, anchor)]
            if (topic, anchor) not in self.asking:
                f = self.asking[(topic, anchor)] = self.pool.submit(self.ask, topic, anchor)
                f.add_done_callback(lambda f: f.exception() and log.warning("couldn't ask about %s: %s", topic, f.exception()))
        return None

    def judge(self, topics):
        fields = {"topics": "; ".join(topics)}
        if self.block:
            s, topic, anchor, via = self.graph.nearness(topics, *self.anchors(self.block))
            near = f"{topic} is near {anchor}" + (f" (through {via})" if via else "")
            if s >= self.block_at:
                return Result("hide", near, fields)
            if s >= self.block_ask:
                v = self.verdict(topic, anchor)
                if v is None:
                    return Result("hide", f"still deciding whether {topic} is part of {anchor}", fields)
                if v[0]:
                    return Result("hide", f"{near}: {v[1]}", fields)
        if self.focus:
            s, topic, anchor, via = self.graph.nearness(topics, *self.anchors(self.focus))
            fields["focus"] = f"{s:.2f} {topic}" + (f" through {via}" if via else "")
            if s < self.focus_ask:
                return Result("hide", f"off focus (nearest: {topic}, {s:.2f})", fields)
            if s < self.focus_at:
                v = self.verdict(topic, anchor)
                if v is None:
                    return Result("hide", f"still deciding whether {topic} is part of {anchor}", fields)
                if not v[0]:
                    return Result("hide", f"off focus: {topic} isn't {anchor} ({v[1]})", fields)
                fields["focus"] += f" (gemma: {v[1]})"
        return Result(fields=fields)

    def decide(self, videos):
        end = time.monotonic() + self.budget
        topics = self.topics(videos)
        results = [self.judge(t) if t else Result("hide", "not tagged yet") for t in topics]
        with self.lock:
            asking = list(self.asking.values())
        if asking:  # Gemma's thinking about some: wait for it, within the budget
            cf.wait(asking, max(0, end - time.monotonic()))
            results = [self.judge(t) if t else r for t, r in zip(topics, results)]
        return results

    def panel(self):
        """for Hull's panel in Rudder's popup: [(title, [(label, value)])]"""
        s = self.graph.stats()
        rules = "; ".join(filter(None, [self.focus and "focus: " + ", ".join(self.focus), self.block and "block: " + ", ".join(self.block)]))
        return [(f"Culture: {s['topics']} topics from {s['tagged']} videos{f' ({rules})' if rules else ''}. Most seen:", s["top"])]

    def describe(self):
        s = self.graph.stats()
        return f"{s['tagged']} videos on {s['topics']} topics"
