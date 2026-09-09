"""Tests for the generated alliterative speaker names."""

from lifelog.speaker_names import (
    FIRST_NAMES,
    LAST_NAMES,
    generate_speaker_name,
)


def test_first_and_last_share_initial():
    """Every candidate pair shares the same initial letter."""
    for letter, firsts in FIRST_NAMES.items():
        for first in firsts:
            assert first[0].lower() == letter
        for last in LAST_NAMES[letter]:
            assert last[0].lower() == letter


def test_generate_speaker_name_avoids_existing():
    """Generated names never collide with the existing set."""
    existing: set[str] = set()
    for _ in range(20):
        name = generate_speaker_name(existing)
        assert name not in existing
        existing.add(name)


def test_generate_speaker_name_format():
    """Names are two Title Case words sharing an initial."""
    name = generate_speaker_name(set())
    parts = name.split(" ")
    assert len(parts) == 2
    first, last = parts
    assert first[0] == last[0]
    assert first[0].isupper() and last[0].isupper()


def test_generate_speaker_name_exhaustion_fallback():
    """When every candidate is taken, a numeric suffix disambiguates."""
    all_candidates = {
        f"{first} {last}"
        for letter in FIRST_NAMES
        for first in FIRST_NAMES[letter]
        for last in LAST_NAMES[letter]
    }
    name = generate_speaker_name(all_candidates)
    assert name not in all_candidates
    first, last, suffix = name.split(" ")
    assert first[0] == last[0]
    assert int(suffix) >= 2
