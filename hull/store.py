"""Everything Hull sees, kept on disk: every video Rudder decided (its record and outcome), what each Hull stage said
about it, and its thumbnail. SQLite in data/hull.db, thumbnails in data/thumbs/. This is what later algorithms learn
from and are measured against."""
import json, sqlite3, threading, time
from pathlib import Path

SCHEMA = """
create table if not exists videos (  -- Rudder's video record, newest values kept
  id text primary key, title text, channel text, description text, published text, duration_seconds integer,
  seen_at_ms integer, thumbnail_type text, thumbnail_url text, source text, short integer, fields text,
  first_recorded real, last_recorded real);
create table if not exists outcomes (  -- what Rudder's pipeline did with it, each time it was decided
  video_id text, at real, hidden integer, decided_by text, why text);
create table if not exists stage_results (  -- what a Hull stage said about it
  video_id text, stage text, at real, decision text, why text, fields text, ms real);
create table if not exists shown (  -- each time Rudder put it on screen
  video_id text, at_ms integer);
create index if not exists outcomes_video on outcomes(video_id);
create index if not exists stage_results_video on stage_results(video_id);
"""


class Rows:
    """a query's rows, already fetched (so the lock isn't held while they're read)"""
    def __init__(self, cur):
        self.rows, self.lastrowid = cur.fetchall(), cur.lastrowid

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows

    def __iter__(self):
        return iter(self.rows)


class LockedDB:
    """one SQLite connection shared by Hull's threads (the link, stages' workers, the app), one call at a time: SQLite's
    Python driver fails ("API misuse") when threads use a connection at once. ponytail: one lock for everything; a
    connection per thread if it ever gets contended"""
    def __init__(self, path):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.RLock()

    def execute(self, sql, args=()):
        with self.lock:
            return Rows(self.conn.execute(sql, args))

    def executemany(self, sql, rows):
        with self.lock:
            self.conn.executemany(sql, rows)

    def executescript(self, sql):
        with self.lock:
            self.conn.executescript(sql)

    def commit(self):
        with self.lock:
            self.conn.commit()

    def close(self):
        with self.lock:
            self.conn.close()


class Store:
    def __init__(self, folder):
        self.folder = Path(folder)
        (self.folder / "thumbs").mkdir(parents=True, exist_ok=True)
        self.db = LockedDB(self.folder / "hull.db")
        self.db.executescript(SCHEMA)

    def _keep(self, v, now):
        self.db.execute(
            """insert into videos values (?,?,?,?,?,?,?,?,?,?,?,?,?,?) on conflict(id) do update set
               title=excluded.title, channel=coalesce(nullif(excluded.channel,''), channel),
               description=coalesce(nullif(excluded.description,''), description),
               published=coalesce(nullif(excluded.published,''), published), duration_seconds=max(excluded.duration_seconds, duration_seconds),
               fields=excluded.fields, last_recorded=excluded.last_recorded""",
            (v.id, v.title, v.channel, v.description, v.published, v.duration_seconds, v.seen_at_ms, v.thumbnail_type,
             v.thumbnail_url, v.source, int(v.short), json.dumps(v.fields), now, now))
        if v.thumbnail:
            path = self.folder / "thumbs" / (v.id + (".webp" if v.thumbnail_type == "image/webp" else ".jpg"))
            if not path.exists():
                path.write_bytes(v.thumbnail)

    def record(self, video, hidden, decided_by, why):
        """a video Rudder decided, with its outcome"""
        now = time.time()
        self._keep(video, now)
        self.db.execute("insert into outcomes values (?,?,?,?,?)", (video.id, now, int(hidden), decided_by, why))
        self.db.commit()

    def stage_results(self, stage, videos, results, ms):
        """what one of Hull's stages said about a batch, and how long it took (ms per video)"""
        now, each = time.time(), ms / max(len(videos), 1)
        for v in videos:
            self._keep(v, now)
        self.db.executemany("insert into stage_results values (?,?,?,?,?,?,?)",
                            [(v.id, stage, now, r.decision, r.why, json.dumps(r.fields), each) for v, r in zip(videos, results)])
        self.db.commit()

    def shown(self, ids, at_ms):
        """videos Rudder put on screen"""
        self.db.executemany("insert into shown values (?,?)", [(i, at_ms) for i in ids])
        self.db.commit()

    def stats(self):
        one = lambda q: self.db.execute(q).fetchone()[0]
        return {
            "videos": one("select count(*) from videos"),
            "hidden": one("select count(distinct video_id) from outcomes where hidden = 1"),
            "shown": one("select count(distinct video_id) from shown"),
            "thumbnails": sum(1 for _ in (self.folder / "thumbs").iterdir()),
            "hid_by_stage": dict(self.db.execute("select stage, count(distinct video_id) from stage_results where decision = 'hide' group by stage").fetchall()),
            "ms_by_stage": dict(self.db.execute("select stage, avg(ms) from stage_results group by stage").fetchall()),
            "recent": self.db.execute(
                """select v.title, s.stage, s.why from stage_results s join videos v on v.id = s.video_id
                   where s.decision = 'hide' order by s.at desc limit 5""").fetchall(),
        }
