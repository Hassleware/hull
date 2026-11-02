"""A Bloom filter: a fixed-size bit array that answers "seen this before?" in constant memory. It never forgets a key it
was given (no false negatives); about 1 in 1000 keys it never saw also say yes, which for Hull means a video hidden as
a repeat that wasn't one: strict, and acceptable. Kept on disk as its raw bits."""
import hashlib, math
from pathlib import Path


class Bloom:
    def __init__(self, path, capacity=1_000_000, error=0.001):
        self.path = Path(path)
        m = math.ceil(-capacity * math.log(error) / math.log(2) ** 2)  # bits for that error rate at capacity
        self.bits = bytearray(self.path.read_bytes()) if self.path.exists() else bytearray((m + 7) // 8)
        self.m = len(self.bits) * 8  # an existing file keeps its own size
        self.k = max(1, round(self.m / capacity * math.log(2)))  # hashes per key

    def _spots(self, key):
        d = hashlib.blake2b(key.encode(), digest_size=16).digest()
        a, b = int.from_bytes(d[:8], "little"), int.from_bytes(d[8:], "little") | 1
        return ((a + i * b) % self.m for i in range(self.k))  # double hashing: k spots from two hashes

    def add(self, key):
        for s in self._spots(key):
            self.bits[s >> 3] |= 1 << (s & 7)

    def __contains__(self, key):
        return all(self.bits[s >> 3] >> (s & 7) & 1 for s in self._spots(key))

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(self.bits)
        tmp.replace(self.path)  # never a half-written filter
