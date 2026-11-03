"""Repeats: a video Rudder has put on screen once is never shown again, and neither is a copy of it (a re-upload
under another id: the same title, or the same thumbnail). Everywhere but searches and channel pages (Rudder's
fields.page), where you went looking: there it's shown, and still counts as shown for everywhere else.

  - Shown ids live in a Bloom filter (data/shown.bloom), filled from Rudder's WatchShown.
  - Copies are found with locality-sensitive hashing (hull/lsh.py) over shown videos' titles and thumbnails, kept in
    hull.db (shown_prints) and indexed in memory.

config: { "capacity": 1000000,   # videos the Bloom filter holds at a 0.1% false-repeat rate
          "title_jaccard": 0.8,  # share of words that makes a title a copy
          "thumb_bits": 12 }     # dHash bits (of 256) two thumbnails may differ by and still be a copy
"""
import threading

from hull.bloom import Bloom
from hull.lsh import NearDuplicates, dhash
from hull.video import Result


def thumb_hash(v):
    try:
        return dhash(v.thumbnail) if v.thumbnail else None
    except Exception:  # an image Pillow can't read: judged on the title alone
        return None


class Repeats:
    def __init__(self, config, store):
        self.store, self.lock = store, threading.Lock()
        store.db.execute("create table if not exists shown_prints (video_id text primary key, title text, dhash text)")
        path = store.folder / "shown.bloom"
        fresh = not path.exists()
        self.shown_ids = Bloom(path, config.get("capacity", 1_000_000))
        if fresh:  # start from what the store already knows
            for (i,) in store.db.execute("select distinct video_id from shown"):
                self.shown_ids.add(i)
            self.shown_ids.save()
        self.copies = NearDuplicates(config.get("title_jaccard", 0.8), config.get("thumb_bits", 12))
        for i, title, h in store.db.execute("select video_id, title, dhash from shown_prints"):
            self.copies.add(i, title, int(h, 16) if h else None)
        self.waiting = {}  # id → (title, dHash) of videos decided but not yet shown

    LOOKING = ("search", "channel")  # pages where repeats are fine

    def decide(self, videos):
        out = []
        for v in videos:
            looking = v.fields.get("page") in self.LOOKING
            if v.id in self.shown_ids and not looking:
                out.append(Result("hide", "shown before"))
                continue
            h = thumb_hash(v)
            with self.lock:
                self.waiting[v.id] = (v.title, h)
                if len(self.waiting) > 20000:  # most decided videos are never shown: forget the oldest
                    self.waiting.pop(next(iter(self.waiting)))
                m = None if looking else self.copies.match(v.id, v.title, h)
            out.append(Result("hide", m[1]) if m else Result())
        return out

    def shown(self, ids):
        rows = []
        with self.lock:
            for i in ids:
                if i in self.shown_ids:
                    continue
                self.shown_ids.add(i)
                title, h = self.waiting.pop(i, None) or (self.title_of(i), None)
                self.copies.add(i, title, h)
                rows.append((i, title, f"{h:064x}" if h is not None else None))
            self.shown_ids.save()
        self.store.db.executemany("insert or ignore into shown_prints values (?,?,?)", rows)
        self.store.db.commit()

    def title_of(self, vid):
        r = self.store.db.execute("select title from videos where id = ?", (vid,)).fetchone()
        return r[0] if r else ""

    def describe(self):
        return f"shown once, never again ({len(self.copies.titles)} titles, {len(self.copies.thumbs)} thumbnails)"
