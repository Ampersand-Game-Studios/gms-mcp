import re
import time

import pytest

from gms_helpers.bounded_regex import MAX_PATTERN_LENGTH, RegexTimeoutError, search_many


def test_literal_pattern_matches_in_order_and_respects_limit():
    texts = ["alpha", "beta", "alphabet", "gamma alpha"]
    assert search_many("alpha", texts) == [(0, "alpha"), (2, "alpha"), (3, "alpha")]
    assert search_many("alpha", texts, max_matches=2) == [(0, "alpha"), (2, "alpha")]


def test_repetition_pattern_runs_in_child_with_flags():
    assert search_many(r"sc?r_\w+", ["SCR_PLAYER", "x", "spr"], flags=re.IGNORECASE) == [(0, "SCR_PLAYER")]


def test_catastrophic_pattern_is_stopped_at_deadline():
    started = time.monotonic()
    with pytest.raises(RegexTimeoutError):
        search_many(r"^(a+)+$", ["a" * 40 + "!"], timeout=1.0)
    assert time.monotonic() - started < 10


def test_invalid_and_oversized_patterns_are_rejected():
    with pytest.raises(re.error):
        search_many("(unclosed", ["x"])
    with pytest.raises(ValueError):
        search_many("a" * (MAX_PATTERN_LENGTH + 1), ["x"])
