# tests/regression/

Regression tests מבוססי-תרחישים — מגינים מרגרסיות באלגוריתם ה-post-processing
(reconcile, salvage, normalize, validators) כשמשנים prompts או חוקים.

## הרעיון

כל test כאן:
1. **מקבל קלט סינתטי** של `stage1`+`stage2` שמדמה דפוס אמיתי שראינו ב-batch
2. **מריץ את ה-post-processing pipeline** (reconcile_part_number, salvage_revision,
   normalize_known_phrases, validators ...) — בדיוק את הסדר שב-`assembly/pipeline.py`
3. **משווה לפלט-זהב** — dict עם השדות הסופיים הצפויים

אם validator משנה את התנהגותו — הבדיקה תיכשל מיד עם diff ברור, גם אם זה מצב
שלא נתפס ב-unit tests של פונקציה בודדת.

## הוספת תרחיש חדש

1. ב-[scenarios.py](scenarios.py) — הוסף entry חדש למילון `SCENARIOS`:
   ```python
   "scenario_name": {
       "description": "מה התרחיש בודק",
       "filename": "_asm_temp_BP70534A-A-PD-bp70534a.pdf",
       "stage1": {"part_number": "...", ...},
       "stage2": {"standards": [...], ...},
       "expected": {"part_number": "...", ...},  # לשדות שצריכים להשתנות
       "expected_warnings_contain": ["INFO", "HIGH"],  # סוגי warnings שצפויים
   }
   ```
2. הרץ `pytest tests/regression/` — תיכשל בפעם הראשונה
3. אם הפלט נראה נכון — עדכן את `expected` והרץ שוב

## למה לא להשתמש ב-cache files אמיתיים?

`output/.cache/` לא ב-git (PII), ובכל מקרה ה-cache שומר את ה-result אחרי
reconcile — אין דרך להפריד בין "מה המודל החזיר" לבין "מה ה-pipeline עשה". 
התרחישים הסינתטיים מאפשרים לבדוק כל שלב במנותק.
