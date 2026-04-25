# 📝 CHANGELOG — AIDrawAnalyser

> כל השינויים המהותיים בפרויקט. הפורמט מבוסס על
> [Keep a Changelog](https://keepachangelog.com/he/), הגרסאות לפי
> [Semantic Versioning](https://semver.org/lang/he/).

---

## [Sale-Readiness Sprint] — 25/04/2026

### 📦 Sale-Readiness Documentation
- **5 מסמכים חדשים** ל-due diligence:
  - [TECHNICAL_DUE_DILIGENCE.md](TECHNICAL_DUE_DILIGENCE.md) — ארכיטקטורה, סיכונים, מגבלות
  - [SECURITY.md](SECURITY.md) — מדיניות אבטחה
  - [DATA_HANDLING.md](DATA_HANDLING.md) — מה נשלח ל-Azure, מה נשמר
  - [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) — Windows/Linux/Docker setup
  - [LICENSE_REVIEW.md](LICENSE_REVIEW.md) — 9 תלויות + סיכון PyMuPDF AGPL
- [SALE_READINESS_RECOMMENDATIONS.md](SALE_READINESS_RECOMMENDATIONS.md) ו-[UX_IMPROVEMENT_RECOMMENDATIONS.md](UX_IMPROVEMENT_RECOMMENDATIONS.md) — roadmaps
- [IMPROVEMENT_RECOMMENDATIONS.md](docs/archive/IMPROVEMENT_RECOMMENDATIONS_2026-04-25.md) הועבר ל-`docs/archive/`

### 🎨 UX Improvements
- **Empty state** משופר במסך הראשון עם 4 bullets של ערך
- **Demo Mode** — `core/demo_data.py` + כפתור "🎬 טען דוגמה" — תוצאת דמו מלאה ללא Azure
- **Summary Card** — תקציר החלטה בראש המסך עם pills (P/N, DWG, Rev, Customer, Material, Role) + warning chips לפי חומרה + review badge
- **Review/Edit form** — עריכת 6 שדות סקלריים + standards + packaging לפני export. Status: pending/edited/reviewed. סימון ✏️ לשדות שנערכו. כפתור "✅ אשר תוצאה" — חוסם export עד אישור.
- **Warnings actionable** — הוספת severity label עברי + "💡 מה לבדוק" hint לכל סוג warning
- **תצוגה מכונסת** — `_render_drawing_card` בתוך expander במקום גלילה ארוכה

### 👥 Customer Manager UI
- דיאלוג ניהול לקוחות מלא ב-app.py עם:
  - selectbox לכל הלקוחות הקיימים + "➕ הוסף לקוח חדש"
  - טופס לכל 5 השדות (CAGE codes, default CAGE, aliases, P/N prefixes, regex patterns)
  - דוגמה מלאה לפי לקוח בדיוני "ACME Aerospace Inc."
  - placeholder text בכל שדה
  - שמירה/מחיקה/שינוי שם — מעדכן in-place ללא restart
- `core/_customer_data.py` הורחב ב-CRUD: `reload_mappings`, `save_mappings`, `list_customers`, `get_customer_record`, `empty_customer_record`, `upsert_customer`, `delete_customer`
- 16 בדיקות חדשות ב-`tests/test_customer_data.py` — round-trip, validation, rename, mutate-in-place

### 🛠️ Code Quality
- **`pyproject.toml` חדש** עם config של ruff (E/F/I/B/UP/W) + isort עם combine-as-imports
- **CI ruff עכשיו חוסם** (היה `continue-on-error`)
- 31 שגיאות ruff תוקנו: imports כפולים, `logger` undefined ב-app.py:606, `zip()` ללא strict, F541 f-strings ריקים, etc.
- 600+ בדיקות עוברות (היה 405; +210 בעקבות הרחבת suite)

### 📦 Demo Pack
- `demo_pack/` חדש עם:
  - **`interactive_demo.html`** — קובץ HTML עצמאי שמדמה את כל ה-flow בשני מצבים. פותח בכל דפדפן, בלי שרת. 1543 שורות, 60KB.
    - **🔍 Single mode**: Empty state → Load Demo → Summary → Edit → Approve → Export
    - **🧩 Assembly mode** ⭐: 4 שרטוטים (1 assembly + 3 parts) → Navigator → ניתוח קשרי אבא/בן עם עץ מוצר ויזואלי + Missing Children + 4 טאבי ייצוא
  - README הסבר על מה עוד להוסיף לחבילה
- `sample_drawings/` עם README הסבר איך לסניטיזה שרטוטים אמיתיים

### 🔒 Pre-Share Tooling
- `scripts/prepare_for_sharing.py` — checklist הרצה לפני שיתוף הריפו עם קונה. בודק:
  - תיקיות נתוני לקוח (draws/, output/, REPORTS/) לא tracked
  - secrets לא ב-git history
  - קבצים גדולים tracked
  - מסמכים נדרשים קיימים (חסר LICENSE — מסומן)
  - pytest + ruff עוברים
  - מציג נפח של תיקיות מקומיות לניקוי ידני

### ⚖️ AGPL Eliminated — Reports migrated to HTML
**הבעיה הקודמת:** PyMuPDF (fitz) הוא AGPL 3.0 / Commercial — סיכון לקונה שמתכנן SaaS / סגור-מקור.

**הפתרון:** הדוחות הוחלפו מ-PDF ל-**HTML עצמאי**:
- `core/pdf_utils.py` (קלט) השתמש ב-`pypdfium2` (Apache 2.0) — נשאר כמו שהוא ✅
- `storage/pdf_report.py` (פלט) — **`import fitz` הוסר לחלוטין**:
  - `build_assembly_pdf` → `build_assembly_html` (alias נשמר ל-backwards compat)
  - `build_tree_pdf` → `build_tree_html` (alias נשמר)
  - הקבצים נשמרים כ-`.html` במקום `.pdf`
- `_wrap_full_html_report()` חדש — עוטף את כל הסקציות ב-`<!DOCTYPE html>` עם:
  - `@page { size: A4; margin: 1.5cm; }` להדפסה איכותית
  - `@media print` rules שמסתיר את כפתור ההדפסה ומפרק לעמודים
  - כפתור "🖨️ הדפסה / שמירה כ-PDF" בראש העמוד
  - RTL native + Hebrew dir + meta charset utf-8
- `requirements.txt` — `pymupdf` הוסר לחלוטין
- ה-UI: tab "📕 PDF מלא" → "📄 דוח HTML" בשני המצבים (Single + Assembly)

**איך הקונה מקבל PDF?** פותח את ה-HTML בדפדפן → Ctrl+P → "Save as PDF". הדפדפן עושה את ההמרה בחינם, איכות מושלמת.

**יתרונות שולים:**
- searchable text · mobile-friendly · קובץ קטן יותר · קל לדבג

**תוצאה:** **0 AGPL בסטאק. כל התלויות Apache 2.0 / MIT / BSD.** קונה לא צריך לקנות שום רישיון.

15 בדיקות חדשות ב-[tests/test_pdf_report_optional.py](tests/test_pdf_report_optional.py) — HTML structure, RTL, content, print CSS, Excel regression, backwards-compat aliases, no fitz import. [LICENSE_REVIEW.md](LICENSE_REVIEW.md) עודכן עם טבלת השוואת חלופות.

---

## [Unreleased] — 25/04/2026

### 🔥 Major Refactor (ריפקטור גדול!)
- **Unified Pipeline** — `core/extractor.py` הוסר. שני המצבים (שרטוט בודד + מכלולים) משתמשים עכשיו ב-`core/assembly/pipeline.py` ו-`extract_assembly_drawing()`.
  - פרומפטים חיצוניים: `prompts/single/` (legacy, לא בשימוש runtime) → `prompts/assembly/` (שימוש עדכני)
  - `core/prompts.py` הוסר (פרומפטים כעת טעונים דרך `core/assembly_prompts.py`)
  - Stage 3 (סיכום עברי) + master matching הוסרו מה-pipeline (אם נדרשים — משימוש יידני של `core/master_matcher.py`)
  - כתיבה מכניסטית: חילוץ בשני שלבים (basic + processes) ללא סיכום.
- **Better Tests** — מ-5 קבצי בדיקות ל-13:
  - `test_assembly_pipeline.py` (full pipeline mocks) / `test_assembly_material.py` / `test_drawing_cache.py` / `test_two_pass.py` / `test_pdf_utils.py` / `test_ai_helpers.py` / `test_azure_client.py` / `test_customer_data.py` (צפוי)
  - + `tests/regression/` sub-folder לבדיקות post_process
  - כיסוי מצטבר כל כך גדל ל-~80% (מ-70%)
- **Documentation Sync** — עדכון [README.md](README.md) / [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) / [CHANGELOG.md](CHANGELOG.md) לתיאור הארכיטקטורה החדשה.

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
