"""`luck-rng-v1`: a self-contained SplitMix64 so draws never change with the Python version (`random.sample`/`shuffle` have
changed between releases). Everything is integer arithmetic; weights are exact Decimals with power-of-two denominators.

Each (trip, stream) pair has its own sub-stream seeded by hashing, so a trip's draws never depend on other trips or order.
"""

import hashlib
import json
from collections.abc import Sequence
from decimal import Decimal
from typing import TypeVar

from .numeric_boundary import CALC

RNG_VERSION = "luck-rng-v1"
MASK64 = (1 << 64) - 1
WEIGHT_DENOMINATOR = 1 << 32
STREAMS = ("alt", "nifty", "boot_alt", "boot_nifty")

T = TypeVar("T")


def derive_seed(seed: int, formula_version: str, trip_id: str, stream: str) -> int:
    """First 8 bytes (big-endian) of SHA-256 of the canonical JSON array [seed, formula_version, trip_id, stream]."""
    if stream not in STREAMS:
        raise ValueError(f"unknown stream {stream!r}")
    text = json.dumps([seed, formula_version, trip_id, stream], separators=(",", ":"), ensure_ascii=True)
    return int.from_bytes(hashlib.sha256(text.encode("ascii")).digest()[:8], "big")


class SplitMix64:
    def __init__(self, seed: int) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int) or not (0 <= seed <= MASK64):
            raise ValueError("seed must be an int in [0, 2^64 - 1]")
        self._state = seed

    def next_u64(self) -> int:
        self._state = (self._state + 0x9E3779B97F4A7C15) & MASK64
        z = self._state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
        return z ^ (z >> 31)

    def randbelow(self, n: int) -> int:
        """Uniform integer in [0, n) by rejection sampling (no modulo bias)."""
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            raise ValueError("n must be a positive int")
        limit = (1 << 64) - ((1 << 64) % n)
        while True:
            value = self.next_u64()
            if value < limit:
                return value % n


def sample_without_replacement(rng: SplitMix64, pool: Sequence[T], k: int) -> list[T]:
    """Partial Fisher-Yates over a copy of `pool` (the caller fixes the pool order). `k` distinct items, in draw order."""
    if not (0 <= k <= len(pool)):
        raise ValueError("k must be between 0 and the pool size")
    items = list(pool)
    for i in range(k):
        j = i + rng.randbelow(len(items) - i)
        items[i], items[j] = items[j], items[i]
    return items[:k]


def simplex_weights(rng: SplitMix64, k: int) -> tuple[Decimal, ...]:
    """k weights uniform on the simplex: k-1 sorted integer cuts in [0, 2^32], weight = gap / 2^32, exact and summing to 1."""
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError("k must be a positive int")
    cuts = sorted(rng.randbelow(WEIGHT_DENOMINATOR + 1) for _ in range(k - 1))
    bounds = [0, *cuts, WEIGHT_DENOMINATOR]
    denominator = Decimal(WEIGHT_DENOMINATOR)
    return tuple(CALC.divide(Decimal(bounds[i + 1] - bounds[i]), denominator) for i in range(k))
