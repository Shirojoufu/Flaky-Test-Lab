"""Daily report dates, in the timezone the job runs in."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

OFFSETS = {"UTC": 0, "PST": -8}


def report_date(moment: datetime) -> str:
    """The calendar date of ``moment`` in the runner's timezone (LAB_TZ, default UTC)."""
    offset = timedelta(hours=OFFSETS[os.environ.get("LAB_TZ", "UTC")])
    return moment.astimezone(timezone(offset)).date().isoformat()
