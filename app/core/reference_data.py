"""Currency decimals and phone calling codes live in config/reference-data.json, not in code.
A bad file stops the application at startup (same rule as every other setting)."""

import json
import re
from functools import lru_cache
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "reference-data.json"


class ReferenceData:
    def __init__(self, currencies: dict[str, int], calling_codes: dict[str, str]) -> None:
        self.currencies = currencies
        self.calling_codes = calling_codes


def load_reference_data(path: Path = DEFAULT_PATH) -> ReferenceData:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        currencies = {str(k): v for k, v in raw["currencies"].items()}
        calling_codes = {str(k): v for k, v in raw["callingCodes"].items()}
    except (OSError, ValueError, KeyError, AttributeError) as exc:
        raise ValueError(f"reference data file {path} is missing or unreadable") from exc

    for code, exponent in currencies.items():
        if (
            not re.fullmatch(r"[A-Z]{3}", code)
            or type(exponent) is not int
            or not 0 <= exponent <= 4
        ):
            raise ValueError(f"reference data: bad currency entry '{code}'")
    for prefix, country in calling_codes.items():
        if not re.fullmatch(r"[0-9]{1,3}", prefix) or not re.fullmatch(r"[A-Z]{2}", str(country)):
            raise ValueError(f"reference data: bad calling code entry '{prefix}'")
    return ReferenceData(currencies, calling_codes)


@lru_cache
def get_reference_data() -> ReferenceData:
    return load_reference_data()
