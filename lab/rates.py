"""Currency conversion, with rates loaded from a data file that coverage can't see."""

from __future__ import annotations

import json
from pathlib import Path

RATES_FILE = Path(__file__).parent / "data" / "rates.json"


def convert(amount_usd: float, currency: str) -> float:
    rates = json.loads(RATES_FILE.read_text(encoding="utf-8"))
    return round(amount_usd * rates[currency], 2)
