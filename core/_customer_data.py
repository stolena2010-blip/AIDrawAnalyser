"""
טוען מיפויי לקוח/CAGE/קידומת P-N מתוך data/customer_mappings.json.

מקור-אמת יחיד: עריכת data/customer_mappings.json מספיקה כדי להוסיף לקוח חדש,
CAGE חדש, alias או pattern של קודי-לקוח-פנימיים — ללא שינוי קוד.

נטען פעם אחת בעת ייבוא המודול. אם הקובץ חסר/פגום — חריגה ברורה (fail loud).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "customer_mappings.json"


_REQUIRED_DICT_KEYS = (
    "cage_to_customer",
    "customer_to_default_cage",
    "customer_aliases",
    "pn_prefix_to_customer",
)
_CAGE_PATTERN = re.compile(r"^[A-Z0-9]{3,6}$", re.IGNORECASE)


def _validate(data: dict) -> None:
    """
    מאמת את מבנה customer_mappings.json. מטרה: לתפוס טעויות הקלדה /
    JSON שבור בזמן ייבוא המודול ולא בזמן ריצה במצב production.

    בודק:
      • כל 5 המפתחות העליונים קיימים
      • כל str→str map הוא אכן dict עם string key + string value
      • CAGE codes (במפתח של cage_to_customer ובערכי customer_to_default_cage)
        תואמים לתבנית CAGE (3-6 alphanumeric)
      • customer_internal_spec_patterns: כל regex compile-able
    """
    # 1. Required keys
    for key in (*_REQUIRED_DICT_KEYS, "customer_internal_spec_patterns"):
        if key not in data:
            raise KeyError(f"customer_mappings.json חסר במפתח '{key}'")

    # 2. Each str→str map valid?
    for key in _REQUIRED_DICT_KEYS:
        value = data[key]
        if not isinstance(value, dict):
            raise TypeError(
                f"customer_mappings.json: '{key}' חייב להיות object (קיבלנו {type(value).__name__})"
            )
        for k, v in value.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise TypeError(
                    f"customer_mappings.json: ב-'{key}' כל key/value חייב להיות string "
                    f"(נמצא {k!r} → {v!r})"
                )
            if not k.strip() or not v.strip():
                raise ValueError(
                    f"customer_mappings.json: ב-'{key}' אסור key/value ריק "
                    f"(נמצא {k!r} → {v!r})"
                )

    # 3. CAGE pattern validation — keys of cage_to_customer + values of customer_to_default_cage
    for cage in data["cage_to_customer"].keys():
        if not _CAGE_PATTERN.match(cage):
            raise ValueError(
                f"customer_mappings.json: CAGE לא תקין '{cage}' "
                "(חייב 3-6 תווים אלפאנומריים)"
            )
    for cage in data["customer_to_default_cage"].values():
        if not _CAGE_PATTERN.match(cage):
            raise ValueError(
                f"customer_mappings.json: CAGE לא תקין '{cage}' "
                "ב-customer_to_default_cage"
            )

    # 4. customer_internal_spec_patterns: dict[str, list[str regex]]
    patterns_map = data["customer_internal_spec_patterns"]
    if not isinstance(patterns_map, dict):
        raise TypeError(
            "customer_mappings.json: 'customer_internal_spec_patterns' חייב להיות object"
        )
    for customer, patterns in patterns_map.items():
        if not isinstance(patterns, list):
            raise TypeError(
                f"customer_mappings.json: patterns של '{customer}' חייבים להיות list"
            )
        for pat in patterns:
            if not isinstance(pat, str):
                raise TypeError(
                    f"customer_mappings.json: pattern של '{customer}' חייב להיות string "
                    f"(נמצא {pat!r})"
                )
            try:
                re.compile(pat)
            except re.error as exc:
                raise ValueError(
                    f"customer_mappings.json: regex לא חוקי של '{customer}': "
                    f"'{pat}' — {exc}"
                ) from exc


def _load() -> dict:
    if not _DATA_PATH.exists():
        raise FileNotFoundError(
            f"Customer mappings file missing: {_DATA_PATH}. "
            "ראה data/customer_mappings.json בתבנית הפרויקט."
        )
    with _DATA_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    _validate(data)
    return data


_RAW = _load()

CAGE_TO_CUSTOMER: dict[str, str] = dict(_RAW["cage_to_customer"])
CUSTOMER_TO_DEFAULT_CAGE: dict[str, str] = dict(_RAW["customer_to_default_cage"])
CUSTOMER_ALIASES: dict[str, str] = dict(_RAW["customer_aliases"])
PN_PREFIX_TO_CUSTOMER: dict[str, str] = dict(_RAW["pn_prefix_to_customer"])

# Patterns are pre-compiled לעבודה מהירה ב-validate loop
CUSTOMER_INTERNAL_SPEC_PATTERNS: dict[str, list[re.Pattern]] = {
    customer: [re.compile(p, re.IGNORECASE) for p in patterns]
    for customer, patterns in _RAW["customer_internal_spec_patterns"].items()
}
