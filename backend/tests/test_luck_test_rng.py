"""Feature 007 RNG, simplex weights, sampling and interval positions (spec sections 6, 7, 10 rows 3-4)."""
from decimal import Decimal as D

import pytest

from app.quant.luck_test.numeric_boundary import CALC, interval_indexes, to_float
from app.quant.luck_test.rng import (
    MASK64, STREAMS, SplitMix64, derive_seed, sample_without_replacement, simplex_weights,
)


def test_splitmix64_known_answer_vector():  # spec 10.3 (reference outputs for seed 0)
    rng = SplitMix64(0)
    assert [rng.next_u64() for _ in range(3)] == [0xE220A8397B1DCDAF, 0x6E789E6AA1B965F4, 0x06C45D188009454F]


def test_splitmix64_is_reproducible_and_seed_sensitive():
    a, b, c = SplitMix64(42), SplitMix64(42), SplitMix64(43)
    xs = [a.next_u64() for _ in range(20)]
    assert xs == [b.next_u64() for _ in range(20)]
    assert xs != [c.next_u64() for _ in range(20)]
    assert all(0 <= x <= MASK64 for x in xs)


@pytest.mark.parametrize("seed", [-1, 2 ** 64, True, 1.5, "1"])
def test_splitmix64_rejects_a_bad_seed(seed):
    with pytest.raises(ValueError):
        SplitMix64(seed)


def test_derive_seed_is_stable_and_separates_every_component():  # spec 6
    base = derive_seed(7, "luck-v1", "T1", "alt")
    assert base == derive_seed(7, "luck-v1", "T1", "alt")
    others = {derive_seed(8, "luck-v1", "T1", "alt"), derive_seed(7, "luck-v2", "T1", "alt"),
              derive_seed(7, "luck-v1", "T2", "alt"), derive_seed(7, "luck-v1", "T1", "nifty")}
    assert base not in others and len(others) == 4
    assert 0 <= base <= MASK64
    assert len({derive_seed(7, "luck-v1", "", s) for s in STREAMS}) == len(STREAMS)


def test_derive_seed_has_no_delimiter_ambiguity():
    assert derive_seed(1, "f", "a|b", "alt") != derive_seed(1, "f|a", "b", "alt")
    with pytest.raises(ValueError):
        derive_seed(1, "f", "t", "unknown")


def test_randbelow_stays_in_range_and_rejects_biased_values():
    rng = SplitMix64(5)
    assert {rng.randbelow(3) for _ in range(200)} == {0, 1, 2}

    class Scripted(SplitMix64):
        def __init__(self, values):
            super().__init__(0)
            self.values = list(values)

        def next_u64(self):
            return self.values.pop(0)

    # n = 3: 2^64 % 3 == 1, so the single value 2^64 - 1 lies in the biased tail and must be skipped.
    scripted = Scripted([MASK64, 4])
    assert scripted.randbelow(3) == 1 and scripted.values == []
    with pytest.raises(ValueError):
        rng.randbelow(0)
    with pytest.raises(ValueError):
        rng.randbelow(True)


def test_sampling_is_distinct_deterministic_and_does_not_touch_the_pool():  # spec 10.4
    pool = list(range(10))
    a = sample_without_replacement(SplitMix64(9), pool, 6)
    assert a == sample_without_replacement(SplitMix64(9), pool, 6)
    assert len(set(a)) == 6 and set(a) <= set(pool) and pool == list(range(10))
    assert sorted(sample_without_replacement(SplitMix64(9), pool, 10)) == pool
    assert sample_without_replacement(SplitMix64(9), pool, 0) == []
    with pytest.raises(ValueError):
        sample_without_replacement(SplitMix64(9), pool, 11)


@pytest.mark.parametrize("k", [1, 2, 5, 10])
def test_simplex_weights_sum_to_exactly_one_and_are_exact(k):  # spec 10.4
    rng = SplitMix64(3)
    for _ in range(25):
        w = simplex_weights(rng, k)
        total = D(0)
        for x in w:
            total = CALC.add(total, x)
            assert x >= 0 and CALC.multiply(x, D(2 ** 32)) == CALC.multiply(x, D(2 ** 32)).to_integral_value()
        assert len(w) == k and total == D(1)


def test_simplex_weights_reject_a_bad_k_and_are_seed_reproducible():
    assert simplex_weights(SplitMix64(1), 4) == simplex_weights(SplitMix64(1), 4)
    assert simplex_weights(SplitMix64(1), 4) != simplex_weights(SplitMix64(2), 4)
    for k in (0, -1, True):
        with pytest.raises(ValueError):
            simplex_weights(SplitMix64(1), k)


def test_interval_indexes_follow_the_spec_rule():  # spec 7
    assert interval_indexes(10_000, D("0.95")) == (249, 9749)
    assert interval_indexes(200, D("0.95")) == (4, 194)
    assert interval_indexes(10, D("0.99")) == (0, 9)  # tiny B: the interval degenerates to the extremes, still in range
    assert interval_indexes(1, D("0.95")) == (0, 0)


def test_to_float_is_the_only_boundary_and_rejects_non_decimals():
    assert to_float(D("0.1")) == float("0.1")
    for bad in (0.1, 1, D("NaN"), D("Infinity")):
        with pytest.raises(ValueError):
            to_float(bad)
