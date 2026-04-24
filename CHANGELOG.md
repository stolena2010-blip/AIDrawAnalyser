# 📝 CHANGELOG — AIDrawAnalyser

> כל השינויים המהותיים בפרויקט. הפורמט מבוסס על
> [Keep a Changelog](https://keepachangelog.com/he/), הגרסאות לפי
> [Semantic Versioning](https://semver.org/lang/he/).

---

## [Unreleased] — 22/04/2026

### 🛡️ Reliability & DX (סוף יום)
- **`core/exceptions.py`** — 15 custom exceptions בהיררכיה (Configuration / Input /
  AI / Extraction / OCR). כל אחת עם `user_message`, `suggestion`, `severity`
  ו-emoji. helper `format_error_for_ui()` מציג Markdown ידידותי ב-Streamlit
  במקום stack traces. `get_streamlit_level()` בוחר אוטומטית `st.error/warning/info`.
  שולב ב-`azure_client.py`, `extractor.py`, `assembly.py`, `ocr_fallback.py`,
  `pdf_utils.py`, `app.py`, `ui_assembly.py`.
- **`core/ai_helpers.py`** — מודול משותף שמאחד `call_vision`, `call_text`,
  `safe_call` ו-`build_kwargs` ש-extractor/assembly שכפלו. הפך את כפילויות
  הקריאה ל-Azure ל-single source of truth.
- **`retry_on_transient` decorator** ב-`ai_helpers.py` — exponential backoff +
  jitter עם skip ל-DrawingLightError (לא מנסה שוב שגיאות יישום). מופעל על
  `call_vision` ו-`call_text` (3 ניסיונות, 2s base delay).
- **`core/drawing_cache.py`** — cache לפי MD5 של PDF/תמונה + גרסת מודל.
  `get_cached_result()` ב-entry של `extract_drawing`, `extract_assembly_drawing`,
  `extract_assembly_overview_image`. `save_cached_result()` בסוף.
  ניתן לכבות דרך `DRAWING_CACHE_DISABLED=true`. חיסכון כספי משמעותי על קבצים חוזרים.
- ~~**OCR מותנה**~~ — **בוטל** (regression!). ראה Fixed למטה.
- **Multi-Sheet Excel** ב-`save_to_excel()` — 6 גיליונות במקום 1:
  `Summary`, `Coatings`, `Paintings`, `Master_Matches`, `Standards`, `Warnings`.
- **`tests/test_exceptions.py`** — 20 unit tests (היררכיה, severity, formatting,
  exception chaining). רצים עצמאית ללא pytest.

### 🐛 Fixed (סוף יום)
- **🔴 Regression fix: OCR-always-on הוחזר** ב-`extractor.py`.
  הניסיון להפוך את OCR למותנה (רק כש-Stage 1 חלש) דפק זיהוי חומר/תקנים
  בשרטוטים מורכבים. דוגמה מתועדת: שרטוט `BH07784A` עם
  "LOW ALLOY STEEL 4340-NORM. & TEMP." זוהה בטעות כ-"ALUMINUM ALLOY 6061-T6"
  כי `should_use_fallback` בודק רק שדות ריקים — לא ערכים שגויים.
  ההחלטה: OCR ירוץ שוב תמיד (אם זמין) כמו קודם. Retry נוסף עדיין מותנה.
  בונוס: `CACHE_VERSION` → `v2` כדי לבטל cached results שגויים מהריצות הקודמות.
- **Hebrew mojibake ב-`core/azure_client.py`** — תיקון docstrings ו-comments
  שנפגעו מ-double-encoding (UTF-8 → cp1252 → UTF-8). מיטבי עברית ב-logs.
- **Silent JSON errors ב-`_call_vision`** — במקום להחזיר `{}` בשקט, זורק עכשיו
  `InvalidResponseError` / `EmptyResponseError` כדי ש-`safe_call` יוכל לנסות
  fallback model אוטומטית.
- **Stage failure context** — כל Stage 1/2/3 זורק עכשיו `StageFailedError` עם
  `stage` בהקשר, כך שה-UI מציג "שלב stage_2_processes נכשל" במקום error כללי.

### 🗑️ Removed (סוף יום)
- **קבצי `.bak`** — `core/prompts.py.bak` ו-`core/assembly_prompts.py.bak` נמחקו
  (Git מחליף אותם).

### ✨ Added
- **Two-Pass ל-Stage 2** במצב שרטוט בודד — `core/two_pass.py`:
  השוואת שתי הרצות לשדות קריטיים (RAL/מותגים), סימון `[VERIFY: ...]` במקרה אי-עקביות,
  והפקת אזהרות `RAL_MISMATCH` / `BRAND_MISMATCH`.
- **שכבת ולידציה לאחר חילוץ** — `core/validators.py`:
  בדיקות אוטומטיות ל-RAL תקני, זיהוי מותגי צבע לא מוכרים,
  זיהוי סיווג שגוי בין coating/painting, וזיהוי הוראות אריזה חשודות.
- **אזהרות ולידציה בתוצאות ה-UI** — `app.py`, `ui_assembly.py`:
  הצגת `_validation_warnings` לפי חומרה (CRITICAL/HIGH/MEDIUM/LOW).
- **פידבק מודל בפועל לכל שלב** במסכי התוצאות (בודד + מכלולים):
  מודל, input/output tokens ועלות לשלב.
- **דוח עץ מוצר מקוצר (PDF)** — `storage/pdf_report.py::build_tree_pdf()`
  כולל טבלת עץ (רמה · P/N · Drawing · תיאור · כמות · חומר) וסכמה ויזואלית מקננת.
- **ייצוא עץ מוצר ל-Excel** — `storage/pdf_report.py::build_tree_excel()`
  גיליון יחיד `Tree` ב-RTL, עם סימון "הועלה?" לחלקים שנמצאו בקבצי הקלט.
- **תמיכה בתמונת Exploded View** במצב מכלולים —
  `core/pdf_utils.py::image_file_to_b64()` ו-
  `core/assembly.py::extract_assembly_overview_image()`. מקבל PNG/JPG/JPEG/WEBP.
- **`ASSEMBLY_OVERVIEW_IMAGE_PROMPT`** — פרומפט ייעודי לניתוח Exploded View
  (סופר Find Numbers / בועות, מתאר חלקים בלי לנחש PN).
- **מיון אוטומטי**: תמונת מכלול (Overview Image) ממוינת תמיד לראש רשימת
  השרטוטים, ללא קשר לסדר ההעלאה.
- **`tests/test_master_matcher.py`** — 26 בדיקות יחידה ל-Master Matcher.
- **`AZURE_SURCHARGE`** ב-`.env` — תוסף Azure ניתן להגדרה (1.10 / 1.20 וכד').
- **`.env.example`** — תבנית הגדרות מלאה.
- **אזהרת חוסר Masters.xlsx** ב-`app.py`.

### 🐛 Fixed
- **תיקון קישור בגיליון 'עץ מתמונה'** — `storage/pdf_report.py::_flatten_overview_image_rows()`:
  קישור פריטי תמונה נשען קודם על `Item No.` (ואז `part_number`),
  כולל תיקון `P/N` מהתמונה כאשר קיימת התאמת BOM מאומתת.
- **ללא קישורים מומצאים לשרטוטים** בגיליון 'עץ מתמונה':
  העמודות `קושר ל-P/N` ו-`קושר ל-Drawing` מתמלאות רק אם קיים קובץ שרטוט בפועל.
- **שחזור נתוני BOM גם ללא קובץ שרטוט**:
  `כמות לפי BOM` ו-`תיאור BOM` מוצגים כאשר יש התאמת BOM,
  גם אם אותו פריט לא הועלה כשרטוט נפרד.
- **פאנל עלויות זמין גם במצב שרטוט בודד** כשהפירוט המלא כבוי:
  ה-render של ה-sidebar הוזז לפני `st.stop()` כדי לא להסתיר את כפתור הפאנל.
- **פאנל עלויות במצב מכלולים** מציג כעת סיכום סשן ופירוט לכל שרטוט,
  במקום להסתמך רק על `session_state.result` של מצב בודד.
- **`StreamlitAPIException` בניווט בין שרטוטים** — `ui_assembly.py::_goto()`
  לא מנסה יותר לכתוב ל-`asm_jump` אחרי יצירת ה-widget.
- **רגקס PN רחב מדי** — נוסף whitelist של prefixes מוכרים
  (PWRL, BBLE, HLTA, FTL, BG, IAI, EL וכו') ו-blacklist (CAGE, NOTES, DWG…).
- **טבלאות נחתכות באמצע ב-PDF** — נוספו `<thead>` עם
  `display: table-header-group`, `tr { page-break-inside: avoid }`,
  `table-layout: fixed` + `<colgroup>` עם מחלקות רוחב קבועות.
- **התהפכויות עברית/אנגלית ב-PDF** — מעטפת `_ltr()` עם `<bdi dir="ltr">`
  לכל ערך לועזי (PN, Drawing, תקנים, עוביים, כמויות, step_no, name_en).

### 🧪 Tests
```powershell
.\.venv\Scripts\Activate.ps1
pytest tests/ -v
# 26 passed
```

---

## עדכונים קודמים

### Assembly Mode (גרסת הבסיס)
- ניתוח מספר שרטוטים יחד עם BOM, עיבוד שבבי, ציפויים, צביעות, בדיקות
- ניתוח קשרי אבא/בן (`analyze_relationships`)
- דוח PDF מסכם מלא (RTL עברית) דרך PyMuPDF Story API
- ניווט עם חצים בין השרטוטים

### Single Mode (גרסת הבסיס)
- Pipeline 3 שלבים (basic → processes → Hebrew summary)
- OCR fallback (Tesseract) להעצמת prompt
- Master Matcher: Top-3 מתוך 1239 מאסטרים, אלגוריתם 9 קריטריונים משוקללים
- שמירה ל-JSON / Excel
- מעקב עלויות ב-`output/costs.jsonl`

### Dual Model Support
- `gpt-4o-vision` (Vision) ו-`gpt-5.4` (Reasoning)
- מתג `ACTIVE_MODEL` ב-`.env`; `is_reasoning_model()` מתאים kwargs אוטומטית
  (`max_completion_tokens` במקום `max_tokens`, ללא `temperature`)

---

## ✅ הושלם (22/04/2026)

סעיפים שנסגרו בעדכון של היום:

- ✅ **תיקון 5**: חילוץ [core/ai_helpers.py](core/ai_helpers.py) משותף
- ✅ **תיקון 6**: Drawing Cache — [core/drawing_cache.py](core/drawing_cache.py)
- ✅ **תיקון 7**: Error Boundary — [core/exceptions.py](core/exceptions.py)
- ✅ **שיפור 8**: `save_to_excel` רב-גיליונות (6 sheets)
- ✅ **תיקון 2**: OCR conditional (רק כש-Stage 1 חלש)

## פתוח לתיקון בעתיד

- 🐛 באג 12: `coatings_empty` retry — prompt מפורש במקום אותו prompt + הערה
- 🔴 תיקון 3: `_reconcile_part_number` זהיר יותר (לא להחליף DN ב-PN)
- 🟡 שיפור: העלאת assembly._call_vision ל-ai_helpers.call_vision (DRY נוסף)
- 🟡 שיפור: mypy/pyright clean + type hints מלאים
- 🟡 שיפור: pre-commit hooks (ruff/black) + CI pipeline
