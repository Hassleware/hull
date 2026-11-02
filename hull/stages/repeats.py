"""Repeats: a video Rudder has put on screen once is never shown again. Seen ids live in a Bloom filter
(data/shown.bloom), filled from Rudder's WatchShown.

config: { "capacity": 1000000 }   # videos it holds at a 0.1% false-repeat rate; more fill it past that rate
"""
from hull.bloom import Bloom
from hull.video import Result


class Repeats:
    def __init__(self, config, store):
        path = store.folder / "shown.bloom"
        fresh = not path.exists()
        self.seen = Bloom(path, config.get("capacity", 1_000_000))
        if fresh:  # start from what the store already knows
            for (i,) in store.db.execute("select distinct video_id from shown"):
                self.seen.add(i)
            self.seen.save()

    def decide(self, videos):
        return [Result("hide", "shown before") if v.id in self.seen else Result() for v in videos]

    def shown(self, ids):
        for i in ids:
            self.seen.add(i)
        self.seen.save()

    def describe(self):
        return "shown once, never again"
