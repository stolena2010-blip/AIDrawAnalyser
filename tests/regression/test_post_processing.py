"""
Regression tests — מריצים את כל ה-post-processing pipeline על תרחישים סינתטיים
ובודקים שהפלט תואם לציפיות.

מגן מרגרסיות כשמשנים prompts/validators/heuristics — אם תרחיש שעבד מתחיל
להכשל, יש diff ברור שמראה איזה שדה השתנה.

הוסף תרחיש חדש ב-[scenarios.py](scenarios.py); ראה [README.md](README.md).
"""
from __future__ import annotations

import copy

import pytest

from core.assembly.post_process import (
    _default_role_if_missing,
    _detect_self_reference_bom,
    _infer_drawing_number_from_pn,
    _split_material_formerly,
    _validate_dwg_prefix,
    _validate_spec_prefixes,
)
from core.pn_utils import (
    reconcile_drawing_number,
    reconcile_part_number,
    reconcile_revision,
    salvage_revision,
)
from core.text_utils import (
    clean_bom_items_in_place,
    infer_cage_from_customer,
    infer_customer_from_cage,
    normalize_customer_in_place,
    normalize_known_phrases_in_place,
)
from core.validators import (
    run_all_validators,
    validate_coating_classification,
)

from tests.regression.scenarios import SCENARIOS


def _apply_pipeline(stage1: dict, stage2: dict, filename: str) -> tuple[dict, dict, list[dict]]:
    """
    מריץ את אותם שלבי post-processing שב-`core/assembly/pipeline.py`,
    בלי להריץ את שלב ה-Vision (אין API). מחזיר (stage1, stage2, warnings).

    סדר השלבים זהה ל-extract_assembly_drawing — אם משנים שם, צריך לשנות גם כאן.
    """
    s1 = copy.deepcopy(stage1)
    s2 = copy.deepcopy(stage2)

    # ─── Reconcile P/N + DWG + Revision (כמו בpipeline) ───
    reconcile_part_number(s1, filename)
    reconcile_drawing_number(s1)
    salvage_revision(s1)
    reconcile_revision(s1, filename)

    # ─── Customer enrichment ───
    infer_customer_from_cage(s1)
    normalize_customer_in_place(s1)
    infer_cage_from_customer(s1)

    # ─── Assembly-specific post_process (מ-core/assembly/post_process.py) ───
    # סדר: self-ref BOM קודם (יכול להפוך role ל-PART), אז default role,
    # אז DWG inference, material formerly split, DWG prefix validation, spec prefixes.
    _detect_self_reference_bom(s1)
    _default_role_if_missing(s1)
    _infer_drawing_number_from_pn(s1)
    _split_material_formerly(s1)
    _validate_dwg_prefix(s1)
    # spec prefix validation מחזירה (kept, warnings) — לא דורסת תוכן
    _, _spec_warnings = _validate_spec_prefixes(s2.get("standards") or [])

    # ─── BOM cleanup + phrase normalization ───
    clean_bom_items_in_place(s1.get("bom_items") or [])
    normalize_known_phrases_in_place(s1)
    normalize_known_phrases_in_place(s2)

    # ─── Validators (מאוחד לבדיקות הזיה) ───
    merged = {**s1, **s2}
    warnings = run_all_validators(merged)
    # שמירה על תאימות עם validators שמקבלים רשימה ישירות
    coating_warnings = validate_coating_classification(s2.get("coating_processes", []))
    warnings.extend(coating_warnings)

    return s1, s2, warnings


@pytest.mark.parametrize("name", list(SCENARIOS.keys()))
def test_scenario(name):
    """כל תרחיש ב-SCENARIOS עובר את ה-pipeline ומאומת מול ציפיות."""
    scenario = SCENARIOS[name]
    s1, s2, warnings = _apply_pipeline(
        scenario["stage1"], scenario["stage2"], scenario["filename"]
    )

    # 1. השוואת שדות שצופים השתנו
    expected = scenario.get("expected", {})
    final = {**s1, **s2}
    for field, expected_value in expected.items():
        actual = final.get(field)
        assert actual == expected_value, (
            f"\n[{name}] field '{field}' mismatch:\n"
            f"  expected: {expected_value!r}\n"
            f"  actual:   {actual!r}\n"
            f"  description: {scenario['description']}"
        )

    # 2. סוגי warnings שחייבים להופיע
    if "expected_warnings_contain" in scenario:
        warning_types = {w.get("type") for w in warnings}
        for must_contain in scenario["expected_warnings_contain"]:
            assert any(must_contain in t for t in warning_types if t), (
                f"\n[{name}] expected warning type containing {must_contain!r}, "
                f"got: {sorted(t for t in warning_types if t)}"
            )

    # 3. סוגי warnings שאסור שיופיעו
    if "expected_warnings_must_not_contain" in scenario:
        warning_types = {w.get("type") for w in warnings}
        for must_not in scenario["expected_warnings_must_not_contain"]:
            assert not any(must_not == t for t in warning_types), (
                f"\n[{name}] warning type {must_not!r} should NOT appear, "
                f"but found in: {sorted(t for t in warning_types if t)}\n"
                f"  description: {scenario['description']}"
            )


def test_all_scenarios_have_descriptions():
    """כל תרחיש חייב כותרת + קלט מינימלי."""
    for name, sc in SCENARIOS.items():
        assert sc.get("description"), f"{name}: missing description"
        assert sc.get("filename"), f"{name}: missing filename"
        assert "stage1" in sc, f"{name}: missing stage1"
        assert "stage2" in sc, f"{name}: missing stage2"
