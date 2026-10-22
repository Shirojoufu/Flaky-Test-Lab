"""Text helpers. Deterministic: these tests are the control group."""

from __future__ import annotations

import re


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def truncate(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def word_count(text: str) -> int:
    return len(text.split())
