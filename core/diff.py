"""
השוואה בין שני שרטוטים — מציג מה השתנה (revision A → B).

שימוש לקוחות תעשייתיים: כשמקבלים revision חדש לשרטוט, חשוב לדעת מה
*בדיוק* השתנה — לא רק הנייר, אלא תהליכי הייצור, החומרים, התקנים.

הפונקציה המרכזית:
    diff_drawings(a, b) → רשימת שינויים מקטלגים לפי שדה.

קטגוריות שינוי:
    - identity (PN, drawing#, revision, customer)
    - material
    - processes (machining, coating, painting, NDT, inspection, ...)
    - standards
    - packaging
    - bom (אם קיים)
"""
from __future__ import annotations

from typing import Any

# קטגוריות + השדות שכל אחת כוללת
_DIFF_CATEGORIES: dict[str, list[str]] = {
    "identity": ["part_number", "drawing_number", "revision",
                 "customer", "cage_code", "title", "catalog_number"],
    "material": ["material", "alternative_material", "material_formerly"],
    "weights": ["raw_weight", "part_weight"],
    "role": ["assembly_role", "quantity"],
    "machining": ["machining_processes"],
    "welding": ["welding_processes"],
    "heat_treatment": ["heat_treatment_processes"],
    "coating": ["coating_processes"],
    "painting": ["painting_processes"],
    "ndt": ["ndt_processes"],
    "inspection": ["inspection_processes"],
    "final_approval": ["final_approval"],
    "additional": ["additional_processes"],
    "standards": ["standards"],
    "packaging": ["packaging_notes"],
    "notes": ["notes", "general_instructions", "environment_requirements"],
    "bom": ["bom_items"],
}


# כיווני שינוי
CHANGE_ADDED = "added"
CHANGE_REMOVED = "removed"
CHANGE_MODIFIED = "modified"
CHANGE_UNCHANGED = "unchanged"


def _normalize_value(value: Any) -> Any:
    """נירמול ערך להשוואה: strip strings, treat empty/None as ''."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return value


def _list_signature(items: list, key_fields: tuple[str, ...] = (
    "step_no", "name_en", "type", "part_number", "item_no",
)) -> dict:
    """ממיר רשימה של dicts ל-dict עם key מובנה — לזיהוי matching בין רשימות."""
    sig: dict = {}
    for item in items or []:
        if not isinstance(item, dict):
            sig[str(item)] = item
            continue
        # Build key from first non-empty key field
        key_parts = []
        for f in key_fields:
            v = item.get(f)
            if v:
                key_parts.append(str(v).strip())
        key = " | ".join(key_parts) if key_parts else str(item)[:50]
        sig[key] = item
    return sig


def _diff_lists(
    a_items: list, b_items: list, field_name: str,
) -> list[dict]:
    """משווה שתי רשימות (BOM, processes, etc.) — מחזיר added/removed/modified."""
    a_sig = _list_signature(a_items)
    b_sig = _list_signature(b_items)
    changes: list[dict] = []
    for key in a_sig:
        if key not in b_sig:
            changes.append({
                "field": field_name, "type": CHANGE_REMOVED,
                "key": key, "old": a_sig[key], "new": None,
            })
    for key in b_sig:
        if key not in a_sig:
            changes.append({
                "field": field_name, "type": CHANGE_ADDED,
                "key": key, "old": None, "new": b_sig[key],
            })
        elif a_sig[key] != b_sig[key]:
            changes.append({
                "field": field_name, "type": CHANGE_MODIFIED,
                "key": key, "old": a_sig[key], "new": b_sig[key],
            })
    return changes


def diff_drawings(a: dict, b: dict) -> dict:
    """משווה שני dictים של drawings, מחזיר dict מקטלג לפי קטגוריה.

    מבנה:
        {
          "summary": {
            "total_changes": int,
            "categories_changed": [str, ...],
            "a_label": str,  # "AC-12345 Rev A"
            "b_label": str,  # "AC-12345 Rev B"
          },
          "changes_by_category": {
            "identity": [{"field": "revision", "type": "modified",
                          "old": "A", "new": "B"}, ...],
            "material": [...],
            ...
          }
        }
    """
    a_label = (
        f"{(a.get('part_number') or '?').strip()} "
        f"Rev {(a.get('revision') or '?').strip()}"
    ).strip()
    b_label = (
        f"{(b.get('part_number') or '?').strip()} "
        f"Rev {(b.get('revision') or '?').strip()}"
    ).strip()

    changes_by_category: dict[str, list[dict]] = {}
    categories_changed: list[str] = []

    for category, fields in _DIFF_CATEGORIES.items():
        cat_changes: list[dict] = []
        for field in fields:
            a_val = _normalize_value(a.get(field))
            b_val = _normalize_value(b.get(field))

            if isinstance(a_val, list) or isinstance(b_val, list):
                a_list = a_val if isinstance(a_val, list) else []
                b_list = b_val if isinstance(b_val, list) else []
                if a_list or b_list:
                    cat_changes.extend(_diff_lists(a_list, b_list, field))
                continue

            if isinstance(a_val, dict) or isinstance(b_val, dict):
                # Dict comparison — flatten to JSON-ish string compare
                if a_val != b_val:
                    cat_changes.append({
                        "field": field, "type": CHANGE_MODIFIED,
                        "old": a_val, "new": b_val,
                    })
                continue

            if a_val != b_val:
                if not a_val and b_val:
                    cat_changes.append({
                        "field": field, "type": CHANGE_ADDED,
                        "old": "", "new": b_val,
                    })
                elif a_val and not b_val:
                    cat_changes.append({
                        "field": field, "type": CHANGE_REMOVED,
                        "old": a_val, "new": "",
                    })
                else:
                    cat_changes.append({
                        "field": field, "type": CHANGE_MODIFIED,
                        "old": a_val, "new": b_val,
                    })

        if cat_changes:
            changes_by_category[category] = cat_changes
            categories_changed.append(category)

    total_changes = sum(len(v) for v in changes_by_category.values())

    return {
        "summary": {
            "total_changes": total_changes,
            "categories_changed": categories_changed,
            "a_label": a_label,
            "b_label": b_label,
        },
        "changes_by_category": changes_by_category,
    }


def format_change_human(change: dict) -> str:
    """Format a single change as a Hebrew-friendly one-liner."""
    field = change.get("field", "?")
    ctype = change.get("type", "?")
    if ctype == CHANGE_ADDED:
        return f"➕ נוסף: {field} = {change.get('new')!r}"
    if ctype == CHANGE_REMOVED:
        return f"➖ הוסר: {field} (היה: {change.get('old')!r})"
    if ctype == CHANGE_MODIFIED:
        return f"🔄 שונה: {field}: {change.get('old')!r} → {change.get('new')!r}"
    return f"? {field}"
