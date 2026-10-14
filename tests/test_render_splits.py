import pytest

from ninety.render.splits import TEST_SEEDS, check_seed, split_of, train_seeds


def test_test_seeds_are_fixed_and_separate():
    assert len(TEST_SEEDS) == 5
    assert all(split_of(s) == "test" for s in TEST_SEEDS)
    assert not set(train_seeds(500)) & set(TEST_SEEDS)


def test_training_cannot_use_a_reserved_seed():
    with pytest.raises(ValueError):
        check_seed(TEST_SEEDS[0], "train")
    with pytest.raises(ValueError):
        train_seeds(2, first=TEST_SEEDS[0])
    with pytest.raises(ValueError):
        check_seed(950000, "train")


def test_split_of_train_seed():
    assert split_of(7) == "train"
    check_seed(7, "train")
