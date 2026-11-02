"""The culture graph: every topic you've been exposed to, and how they connect. Nodes are topics (short noun
phrases, each with an embedding); a video attests to a few of them (video_topics), and topics that share videos are
linked by how often they do. Kept in hull.db; the topic vectors are also held in memory for fast lookups.

How near a topic is to another (relatedness): the larger of
  - how alike their meanings are (cosine of their embeddings), and
  - through a neighbour: for each topic u that shares videos with it, the share of its videos u is on, times how
    alike u is to the other. So "pymc", rarely worded like "bayesian statistics", becomes near it once most videos
    about pymc are also about bayesian statistics. Topics seen on fewer than 2 videos have no neighbours yet.

Names are merged on the way in: a new name whose embedding is within `merge` cosine of a known topic ("mcmc
methods" → "markov chain monte carlo") becomes that topic, so the graph doesn't fill with spellings of one idea.
"""
import threading

import numpy as np

PREFIX = "task: sentence similarity | query: "  # embeddinggemma's prompt for comparing short texts

SCHEMA = """
create table if not exists topics (id integer primary key, name text unique, vec blob, videos integer default 0);
create table if not exists video_topics (video_id text, topic_id integer, rank integer, primary key (video_id, topic_id));
create index if not exists video_topics_topic on video_topics(topic_id);
"""


class Graph:
    def __init__(self, store, ollama, embed_model="embeddinggemma", merge=0.92):
        self.db, self.ollama, self.embed_model, self.merge = store.db, ollama, embed_model, merge
        self.lock = threading.Lock()
        self.db.executescript(SCHEMA)
        rows = self.db.execute("select id, name, vec from topics order by id").fetchall()
        self.ids = [r[0] for r in rows]
        self.names = [r[1] for r in rows]
        self.index = {n: i for i, n in enumerate(self.names)}
        self.vecs = np.array([np.frombuffer(r[2], np.float32) for r in rows]) if rows else np.zeros((0, 768), np.float32)

    def embed(self, texts):
        return self.ollama.embed(self.embed_model, [PREFIX + t for t in texts])

    def topics_of(self, video_id):
        """its topics, most specific first; None if it hasn't been tagged"""
        rows = self.db.execute("select t.name from video_topics v join topics t on t.id = v.topic_id where v.video_id = ? order by v.rank",
                               (video_id,)).fetchall()
        return [r[0] for r in rows] or None

    def nearest(self, vec, k=12):
        """the k known topics closest to a vector"""
        if not len(self.names):
            return []
        sims = self.vecs @ vec
        return [self.names[i] for i in np.argsort(-sims)[:k]]

    def attest(self, video_id, names):
        """a video's topics → their canonical names, now in the graph"""
        names = list(dict.fromkeys(n.strip().lower() for n in names if n.strip()))[:8]
        if not names:
            return []
        vecs = self.embed(names)
        out = []
        with self.lock:
            for name, vec in zip(names, vecs):
                i = self._find(name, vec)
                if self.names[i] not in out:
                    out.append(self.names[i])
                    if self.db.execute("select 1 from video_topics where video_id = ? and topic_id = ?", (video_id, self.ids[i])).fetchone():
                        continue  # already on it (a video tagged again, from its captions)
                    rank = self.db.execute("select count(*) from video_topics where video_id = ?", (video_id,)).fetchone()[0] + 1
                    self.db.execute("insert into video_topics values (?,?,?)", (video_id, self.ids[i], rank))
                    self.db.execute("update topics set videos = videos + 1 where id = ?", (self.ids[i],))
            self.db.commit()
        return out

    def _find(self, name, vec):
        """index of the topic this name is (a new one if none is close enough)"""
        if name in self.index:
            return self.index[name]
        if len(self.names):
            sims = self.vecs @ vec
            best = int(np.argmax(sims))
            if sims[best] >= self.merge:
                return best
        cur = self.db.execute("insert into topics (name, vec) values (?,?)", (name, vec.astype(np.float32).tobytes()))
        self.ids.append(cur.lastrowid)
        self.names.append(name)
        self.index[name] = len(self.names) - 1
        self.vecs = np.vstack([self.vecs, vec[None, :]])
        return len(self.names) - 1

    def neighbours(self, name):
        """[(topic, share of this topic's videos it's also on)], most shared first"""
        i = self.index.get(name)
        if i is None:
            return []
        n = self.db.execute("select count(*) from video_topics where topic_id = ?", (self.ids[i],)).fetchone()[0]
        if n < 2:
            return []
        rows = self.db.execute("""select t.name, count(*) from video_topics a join video_topics b on b.video_id = a.video_id and b.topic_id != a.topic_id
                                  join topics t on t.id = b.topic_id where a.topic_id = ? group by b.topic_id order by 2 desc""", (self.ids[i],)).fetchall()
        return [(u, c / n) for u, c in rows]

    def area(self, anchor_vecs, at=0.85, link=0.5, hops=1):
        """the part of the map around some topics: the topics themselves and their near-synonyms (cosine ≥ at: "비디오
        게임" for "video games"), then, up to
        `hops` edges out, every neighbour most of whose videos (share ≥ link) are already inside. A topic that mostly
        lives there joins (roblox, frostpunk around video games); a big separate subject that touched it once doesn't
        (music, through a game's soundtrack), so the area can't leak across the map."""
        if not len(self.names):
            return set()
        key = (anchor_vecs.tobytes(), at, link, hops, self.db.execute("select count(*) from video_topics").fetchone()[0])
        if getattr(self, "_area", (None,))[0] == key:
            return self._area[1]
        on = {}  # topic → its videos
        for v, t in self.db.execute("select vt.video_id, t.name from video_topics vt join topics t on t.id = vt.topic_id"):
            on.setdefault(t, set()).add(v)
        inside = {self.names[i] for i in np.flatnonzero((self.vecs @ anchor_vecs.T).max(1) >= at)}
        for _ in range(hops):
            videos = set().union(*(on.get(t, ()) for t in inside))
            near = {t for t, vs in on.items() if t not in inside and vs & videos and len(vs & videos) / len(vs) >= link}
            if not near:
                break
            inside |= near
        self._area = (key, inside)
        return inside

    def nearness(self, names, anchors, anchor_vecs):
        """the nearest of a video's topics to any anchor: (relatedness, its topic, the anchor, the neighbour it went
        through or None)"""
        best = (-1.0, "", "", None)
        for name in names:
            for u, share in [(name, 1.0), *self.neighbours(name)]:  # itself first, so it wins ties
                sims = anchor_vecs @ self.vecs[self.index[u]]
                a = int(np.argmax(sims))
                if share * sims[a] > best[0]:
                    best = (round(float(share * sims[a]), 4), name, anchors[a], None if u == name else u)
        return best

    def stats(self):
        one = lambda q: self.db.execute(q).fetchone()[0]
        return {"topics": one("select count(*) from topics"), "tagged": one("select count(distinct video_id) from video_topics"),
                "top": self.db.execute("select name, videos from topics order by videos desc limit 8").fetchall()}
