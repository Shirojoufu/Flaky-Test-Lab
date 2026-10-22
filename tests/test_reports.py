"""Environment-specific: passes in UTC, always fails in PST. In a CI matrix that is a real failure
in one environment, not a flake, even though the code is identical in both."""

from datetime import datetime, timezone

from lab.reports import report_date


def test_report_date_early_morning():
    assert report_date(datetime(2026, 3, 1, 3, 30, tzinfo=timezone.utc)) == "2026-03-01"
