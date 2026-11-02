"""Locality-sensitive hashing: find near-duplicates without comparing against every video ever shown. Similar items
get the same key in at least one band, so only those few are compared exactly.

  - Titles: MinHash over a title's words. 16 bands of 4 hashes catch title pairs whose words overlap by about half
    or more; the exact check then asks for `title_jaccard` (default 0.8): a re-upload. The next episode
    ("ep 12" vs "ep 13") shares 3 of 5 words, 0.6, and stays a video of its own.
  - Thumbnails: dHash, 256 bits of light-to-dark steps in a 17x16 grey copy, unchanged by resizing and
    recompression; fine enough to tell a channel's template with another face or text apart from a copy. 16 bands of 16
    bits: two hashes within 15 bits always share a band; the exact check asks for `thumb_bits` (default 12).
"""
import hashlib, io, re
from collections import defaultdict

import numpy as np
from PIL import Image

PERMS, ROWS = 64, 4
_rng = np.random.default_rng(7)  # fixed, so keys are the same across runs
_A = _rng.integers(1, 2**63, PERMS, dtype=np.uint64) | np.uint64(1)
_B = _rng.integers(0, 2**63, PERMS, dtype=np.uint64)


def words(title):
    return frozenset(re.findall(r"\w+", title.lower()))


def minhash(ws):
    h = np.array([int.from_bytes(hashlib.blake2b(w.encode(), digest_size=8).digest(), "little") for w in ws], np.uint64)
    with np.errstate(over="ignore"):  # wrapping is the point: (a*h + b) mod 2^64
        return (_A[:, None] * h[None, :] + _B[:, None]).min(axis=1)


def dhash(image_bytes):
    g = np.asarray(Image.open(io.BytesIO(image_bytes)).convert("L").resize((17, 16), Image.Resampling.LANCZOS), np.int16)
    return int("".join("1" if b else "0" for b in (g[:, 1:] > g[:, :-1]).flat), 2)


class NearDuplicates:
    def __init__(self, title_jaccard=0.8, thumb_bits=12):
        self.title_jaccard, self.thumb_bits = title_jaccard, thumb_bits
        self.titles, self.thumbs = {}, {}  # id → word set, id → dHash
        self.bands = defaultdict(set)  # band key → ids

    def _title_keys(self, ws):
        m = minhash(ws)
        return [("t", i, m[i * ROWS:(i + 1) * ROWS].tobytes()) for i in range(PERMS // ROWS)]

    @staticmethod
    def _thumb_keys(h):
        return [("i", i, h >> (16 * i) & 0xFFFF) for i in range(16)]

    def add(self, vid, title="", thumb_hash=None):
        ws = words(title)
        if len(ws) >= 3:  # "Untitled", "#shorts": too few words to call anything a copy
            self.titles[vid] = ws
            for k in self._title_keys(ws):
                self.bands[k].add(vid)
        if thumb_hash is not None:
            self.thumbs[vid] = thumb_hash
            for k in self._thumb_keys(thumb_hash):
                self.bands[k].add(vid)

    def match(self, vid, title="", thumb_hash=None):
        """(the shown video it copies, why), or None"""
        ws = words(title)
        if len(ws) >= 3:
            for other in set().union(*(self.bands.get(k, ()) for k in self._title_keys(ws))) - {vid}:
                j = len(ws & self.titles[other]) / len(ws | self.titles[other])
                if j >= self.title_jaccard:
                    return other, f"same title as a shown video ({j:.0%} of words)"
        if thumb_hash is not None:
            for other in set().union(*(self.bands.get(k, ()) for k in self._thumb_keys(thumb_hash))) - {vid}:
                if other in self.thumbs and (d := (thumb_hash ^ self.thumbs[other]).bit_count()) <= self.thumb_bits:
                    return other, f"same thumbnail as a shown video ({d} bits apart)"
        return None
