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


# ═══════════════════════════════════════════════════════════════════
# CRUD helpers — לשימוש ע"י ה-UI לניהול לקוחות בלי לערוך JSON ידנית.
# כל שינוי כותב את הקובץ ומרענן את הקבועים בזיכרון IN-PLACE כדי שמודולים
# שכבר ייבאו את הקבועים (CAGE_TO_CUSTOMER וכו') יראו את הערכים המעודכנים
# בלי restart.
# ═══════════════════════════════════════════════════════════════════

def reload_mappings() -> None:
    """קורא מחדש את customer_mappings.json ומרענן את הקבועים בזיכרון.

    הקבועים (CAGE_TO_CUSTOMER וכו') מתעדכנים IN-PLACE — clear + update —
    כך שמודולים שעשו ``from core._customer_data import CAGE_TO_CUSTOMER``
    ממשיכים לראות את אותו dict object עם ערכים חדשים.
    """
    raw = _load()
    CAGE_TO_CUSTOMER.clear()
    CAGE_TO_CUSTOMER.update(raw["cage_to_customer"])
    CUSTOMER_TO_DEFAULT_CAGE.clear()
    CUSTOMER_TO_DEFAULT_CAGE.update(raw["customer_to_default_cage"])
    CUSTOMER_ALIASES.clear()
    CUSTOMER_ALIASES.update(raw["customer_aliases"])
    PN_PREFIX_TO_CUSTOMER.clear()
    PN_PREFIX_TO_CUSTOMER.update(raw["pn_prefix_to_customer"])
    CUSTOMER_INTERNAL_SPEC_PATTERNS.clear()
    CUSTOMER_INTERNAL_SPEC_PATTERNS.update({
        customer: [re.compile(p, re.IGNORECASE) for p in patterns]
        for customer, patterns in raw["customer_internal_spec_patterns"].items()
    })


def _read_raw_file() -> dict:
    """קורא את ה-JSON כפי שהוא מהדיסק (לפני נירמול / קומפילציה של regex).

    שומר על שדות מטא-דאטה (``_description`` / ``_schema``) שלא נכנסים לקבועים.
    """
    if not _DATA_PATH.exists():
        return {
            "cage_to_customer": {},
            "customer_to_default_cage": {},
            "customer_aliases": {},
            "pn_prefix_to_customer": {},
            "customer_internal_spec_patterns": {},
        }
    with _DATA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_mappings(raw: dict) -> None:
    """מאמת + כותב את ה-JSON + מרענן בזיכרון.

    כתיבה אטומית: כותב לקובץ ``.tmp`` ואז ``replace()``. אם הוולידציה נכשלת —
    הקובץ הקיים לא נוגע (חריגה ``ValueError`` / ``TypeError`` / ``KeyError``).
    """
    _validate(raw)
    tmp_path = _DATA_PATH.with_suffix(".json.tmp")
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
    tmp_path.replace(_DATA_PATH)
    reload_mappings()


def list_customers() -> list[str]:
    """שמות קנוניים של כל הלקוחות — איחוד של כל המקורות, ממוין."""
    names: set[str] = set()
    names.update(CUSTOMER_TO_DEFAULT_CAGE.keys())
    names.update(CAGE_TO_CUSTOMER.values())
    names.update(CUSTOMER_ALIASES.values())
    names.update(PN_PREFIX_TO_CUSTOMER.values())
    names.update(CUSTOMER_INTERNAL_SPEC_PATTERNS.keys())
    return sorted(n for n in names if n.strip())


def get_customer_record(name: str) -> dict:
    """כל המידע על לקוח אחד — מתאים לטעינה לטופס עריכה."""
    name = name.strip()
    return {
        "name": name,
        "cage_codes": sorted(c for c, n in CAGE_TO_CUSTOMER.items() if n == name),
        "default_cage": CUSTOMER_TO_DEFAULT_CAGE.get(name, ""),
        "aliases": sorted(a for a, n in CUSTOMER_ALIASES.items() if n == name),
        "pn_prefixes": sorted(p for p, n in PN_PREFIX_TO_CUSTOMER.items() if n == name),
        "spec_patterns": [
            pat.pattern for pat in CUSTOMER_INTERNAL_SPEC_PATTERNS.get(name, [])
        ],
    }


def empty_customer_record(name: str = "") -> dict:
    """תבנית ריקה לטופס הוספת לקוח."""
    return {
        "name": name,
        "cage_codes": [],
        "default_cage": "",
        "aliases": [],
        "pn_prefixes": [],
        "spec_patterns": [],
    }


def upsert_customer(record: dict, *, original_name: str | None = None) -> None:
    """מוסיף או מעדכן לקוח. אם ``original_name`` ניתן ושונה מ-``record["name"]``
    → מבצע rename (מסיר את כל ההתייחסויות לשם הישן).

    מאמת ושומר ל-JSON. ``ValueError`` אם:
      - ``record["name"]`` ריק
      - CAGE לא תואם לתבנית
      - regex pattern לא חוקי
    """
    new_name = (record.get("name") or "").strip()
    if not new_name:
        raise ValueError("שם הלקוח לא יכול להיות ריק")

    raw = _read_raw_file()
    for key in (*_REQUIRED_DICT_KEYS, "customer_internal_spec_patterns"):
        raw.setdefault(key, {})

    # מסיר את כל ההתייחסויות לשם הישן ולשם החדש (במקרה rename או overwrite)
    names_to_remove = {new_name}
    if original_name and original_name.strip():
        names_to_remove.add(original_name.strip())

    raw["cage_to_customer"] = {
        c: n for c, n in raw["cage_to_customer"].items() if n not in names_to_remove
    }
    raw["customer_aliases"] = {
        a: n for a, n in raw["customer_aliases"].items() if n not in names_to_remove
    }
    raw["pn_prefix_to_customer"] = {
        p: n for p, n in raw["pn_prefix_to_customer"].items() if n not in names_to_remove
    }
    for stale_name in names_to_remove:
        raw["customer_to_default_cage"].pop(stale_name, None)
        raw["customer_internal_spec_patterns"].pop(stale_name, None)

    # מוסיף את הערכים החדשים
    for cage in record.get("cage_codes", []) or []:
        c = (cage or "").strip().upper()
        if c:
            raw["cage_to_customer"][c] = new_name

    default_cage = (record.get("default_cage") or "").strip().upper()
    if default_cage:
        raw["customer_to_default_cage"][new_name] = default_cage

    for alias in record.get("aliases", []) or []:
        a = (alias or "").strip().upper()
        if a:
            raw["customer_aliases"][a] = new_name

    for prefix in record.get("pn_prefixes", []) or []:
        p = (prefix or "").strip().upper()
        if p:
            raw["pn_prefix_to_customer"][p] = new_name

    patterns = [
        (p or "").strip()
        for p in (record.get("spec_patterns") or [])
        if (p or "").strip()
    ]
    if patterns:
        raw["customer_internal_spec_patterns"][new_name] = patterns

    save_mappings(raw)


def delete_customer(name: str) -> None:
    """מסיר לקוח מכל חמשת המפות. מאמת ושומר."""
    name = (name or "").strip()
    if not name:
        raise ValueError("שם הלקוח לא יכול להיות ריק")
    raw = _read_raw_file()
    for key in (*_REQUIRED_DICT_KEYS, "customer_internal_spec_patterns"):
        raw.setdefault(key, {})
    raw["cage_to_customer"] = {
        c: n for c, n in raw["cage_to_customer"].items() if n != name
    }
    raw["customer_aliases"] = {
        a: n for a, n in raw["customer_aliases"].items() if n != name
    }
    raw["pn_prefix_to_customer"] = {
        p: n for p, n in raw["pn_prefix_to_customer"].items() if n != name
    }
    raw["customer_to_default_cage"].pop(name, None)
    raw["customer_internal_spec_patterns"].pop(name, None)
    save_mappings(raw)
