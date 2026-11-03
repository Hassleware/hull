"""Taste: learns from your likes and dislikes in Rudder (its ⋮ menu and YouTube's like buttons; Rudder sends each one
with the video's record: WatchFeedback) and hides new videos like the ones you disliked.

Two kinds of evidence, both from Gemma's reading of the videos:
  - nearest rated videos: each video is read by embeddinggemma as "title — channel — its topics" (the internet
    culture stage's tags); a new video close to one you disliked (cosine ≥ near), and closer to it than to anything you
    liked, is hidden;
  - topics: a topic among a video's most specific ones that you've disliked on at least `topic_dislikes` videos and
    never liked is hidden wherever it turns up.
Videos you rated yourself are left to Rudder (its your-clicks stage). A video with a topic you liked (rated_topics) is
never hidden here. Place this stage after the internet culture
stage, so videos are tagged before it reads them.

config: { "near": 0.74, "margin": 0.03, "topic_dislikes": 2, "embed_model": "embeddinggemma", "ollama": "http://127.0.0.1:11434" }
"""
import threading

import numpy as np

from hull.graph import PREFIX, SCHEMA
from hull.ollama import Ollama
from hull.video import Result


def rated_topics(db):
    """your ratings on the map: each rated video's most specific topic (Gemma tags it first) → (liked, disliked) sets.
    A topic liked at least as often as it's disliked is liked: likes protect"""
    n = {}
    for name, liked in db.execute("""select t.name, r.liked from ratings r
                                     join video_topics vt on vt.video_id = r.video_id
                                      and vt.rank = (select min(rank) from video_topics where video_id = r.video_id)
                                     join topics t on t.id = vt.topic_id
                                     where r.at = (select max(at) from ratings r2 where r2.video_id = r.video_id)"""):
        n.setdefault(name, [0, 0])[0 if liked else 1] += 1
    liked = {t for t, (up, down) in n.items() if up >= down}
    return liked, set(n) - liked


class Taste:
    def __init__(self, config, store):
        self.db = store.db
        self.ollama = Ollama(config.get("ollama", "http://127.0.0.1:11434"))
        self.embed_model = config.get("embed_model", "embeddinggemma")
        self.near, self.margin = config.get("near", 0.74), config.get("margin", 0.03)  # measured: unrelated videos reach 0.70 one pair in 1000
        self.topic_dislikes = config.get("topic_dislikes", 2)
        self.db.executescript(SCHEMA)  # the internet culture stage's topics, which it reads (made here if it runs first)
        self.db.execute("create table if not exists taste_vecs (video_id text primary key, text text, vec blob)")
        self.lock = threading.Lock()

    def topics(self, vid):
        return [r[0] for r in self.db.execute("""select t.name from video_topics vt join topics t on t.id = vt.topic_id
                                                 where vt.video_id = ? order by vt.rank""", (vid,))]

    def text(self, vid, title, channel):
        return " — ".join(x for x in (title, channel, ", ".join(self.topics(vid))) if x)

    def vectors(self, items):
        """[(video id, its text)] → their vectors, kept (taste_vecs) and read again when the text changed (new tags)"""
        known = {}
        for vid, text in items:
            row = self.db.execute("select text, vec from taste_vecs where video_id = ?", (vid,)).fetchone()
            if row and row[0] == text:
                known[vid] = np.frombuffer(row[1], np.float32)
        todo = [(v, t) for v, t in items if v not in known]
        if todo:
            vecs = self.ollama.embed(self.embed_model, [PREFIX + t for _, t in todo])
            for (vid, text), vec in zip(todo, vecs):
                known[vid] = vec
                self.db.execute("insert or replace into taste_vecs values (?,?,?)", (vid, text, vec.astype(np.float32).tobytes()))
            self.db.commit()
        return known

    def ratings(self):
        """your latest rating of each video: [(id, title, channel, liked)]"""
        return self.db.execute("""select r.video_id, coalesce(v.title, ''), coalesce(v.channel, ''), r.liked from ratings r
                                  left join videos v on v.id = r.video_id
                                  where r.at = (select max(at) from ratings r2 where r2.video_id = r.video_id)""").fetchall()

    def decide(self, videos):
        rated = self.ratings()
        if not any(not liked for *_, liked in rated):
            return [Result() for _ in videos]  # nothing disliked yet: no opinion
        mine = {vid for vid, *_ in rated}
        todo = [v for v in videos if v.id not in mine]
        with self.lock:
            vecs = self.vectors([(vid, self.text(vid, t, c)) for vid, t, c, _ in rated] + [(v.id, self.text(v.id, v.title, v.channel)) for v in todo])
        liked = [(vid, t) for vid, t, _, l in rated if l]
        disliked = [(vid, t) for vid, t, _, l in rated if not l]
        tally = {}  # topic → [likes, dislikes]
        for vid, *_, l in rated:
            for t in self.topics(vid):
                tally.setdefault(t, [0, 0])[0 if l else 1] += 1
        out, protected = [], rated_topics(self.db)[0]
        for v in videos:
            if v.id in mine:
                out.append(Result())  # rated: Rudder decides it by your rating
                continue
            if protected & set(self.topics(v.id)):  # a topic you liked: always shown (by Hull)
                out.append(Result())
                continue
            x = vecs[v.id]
            best = lambda group: max(((float(x @ vecs[vid]), t) for vid, t in group), default=(-1.0, ""))
            d, dt = best(disliked)
            l, _ = best(liked)
            fields = {"taste": f"disliked {d:.2f} · liked {max(l, 0):.2f}"}
            sour = [t for t in self.topics(v.id)[:3] if tally.get(t, [0, 0])[1] >= self.topic_dislikes and not tally[t][0]]
            if d >= self.near and d > l + self.margin:
                out.append(Result("hide", f"like \"{dt[:60]}\", which you disliked ({d:.2f})", fields))
            elif sour:
                out.append(Result("hide", f"you've disliked {tally[sour[0]][1]} videos about {sour[0]}", fields))
            else:
                out.append(Result(fields=fields))
        return out

    def describe(self):
        rated = self.ratings()
        return f"learning from {sum(1 for *_, l in rated if l)} likes, {sum(1 for *_, l in rated if not l)} dislikes"
