"""Control group: deterministic tests that must never be reported as flaky."""

from lab.text import slugify, truncate, word_count


def test_slugify():
    assert slugify("Hello, Flaky World!") == "hello-flaky-world"


def test_truncate():
    assert truncate("abcdefgh", 5) == "abcd…"
    assert truncate("abc", 5) == "abc"


def test_word_count():
    assert word_count("  the quick  brown fox ") == 4
