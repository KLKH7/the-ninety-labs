"""Train and test seeds, kept apart so targeted data rounds report honest before and after scores.

The fixed test set is five clips on reserved seeds with the parameters those seeds sample. It is
never re-rendered with overrides, and no training or targeted round may use a reserved seed.
"""

from __future__ import annotations

TEST_SEEDS: tuple[int, ...] = (900001, 900002, 900003, 900004, 900005)
RESERVED_FROM = 900000  # every seed at or above this is reserved for evaluation sets


def split_of(seed: int) -> str:
    if seed in TEST_SEEDS:
        return "test"
    if seed >= RESERVED_FROM:
        return "reserved"
    if seed < 0:
        raise ValueError(f"seed must be non-negative, got {seed}")
    return "train"


def check_seed(seed: int, split: str) -> None:
    """Raise if a seed is used for the wrong split."""
    actual = split_of(seed)
    if actual != split:
        raise ValueError(f"seed {seed} belongs to the {actual} split, not {split}")


def train_seeds(count: int, first: int = 1) -> list[int]:
    seeds = list(range(first, first + count))
    for s in seeds:
        check_seed(s, "train")
    return seeds
