# 📐 AIDrawAnalyser — סקירת פרויקט מפורטת

> אפליקציית Streamlit לחילוץ אוטומטי של מידע משרטוטים הנדסיים (PDF) באמצעות
> Azure OpenAI Vision / Reasoning. תומכת בשני מצבי עבודה: **שרטוט בודד** עם
> התאמה למאגר מאסטרים, ו-**מכלולים מרובים** עם ניתוח קשרי אבא/בן בין השרטוטים
> והפקת דוח HTML מסכם (ניתן לשמירה כ-PDF דרך הדפדפן).

---

## תוכן עניינים

1. [מטרת הפרויקט](#מטרת-הפרויקט)
2. [סטאק טכנולוגי](#סטאק-טכנולוגי)
3. [מבנה התיקיות](#מבנה-התיקיות)
4. [התקנה והרצה](#התקנה-והרצה)
5. [משתני סביבה](#משתני-סביבה)
6. [שני מצבי האפליקציה](#שני-מצבי-האפליקציה)
7. [Pipeline של מצב 'שרטוט בודד'](#pipeline-של-מצב-שרטוט-בודד)
8. [Pipeline של מצב 'מכלולים מרובים'](#pipeline-של-מצב-מכלולים-מרובים)
9. [מנגנון התאמת מאסטרים](#מנגנון-התאמת-מאסטרים)
10. [מעקב עלויות](#מעקב-עלויות)
11. [קבצים מרכזיים — תפקיד מודולרי](#קבצים-מרכזיים--תפקיד-מודולרי)
12. [פלטים / קבצי שמירה](#פלטים--קבצי-שמירה)

---

## מטרת הפרויקט

חברות ייצור מקבלות שרטוטי PDF מלקוחות (RAFAEL וכו'), וצריכות לחלץ מהם:

- **מידע בסיסי**: מספר פריט, מספר שרטוט, גרסה, לקוח, חומר גלם.
- **תהליכי ייצור**: עיבוד שבבי, ציפויים, צביעות, בדיקות, אריזה.
- **תקנים** (MIL / AMS / ASTM / FED-STD / PS / RAFDOCS) עם Type/Class/Grade.
- **התאמה למאגר פנימי** (Masters.xlsx) של ~1239 ציפויים סטנדרטיים.
- **קשרים בין שרטוטים** במכלולי אבא/בן עם כמויות.

האפליקציה אוטומטית את כל אלו ומפיקה דוחות JSON / Excel / PDF.

---

## סטאק טכנולוגי

| תחום | טכנולוגיה |
|------|-----------|
| UI | **Streamlit** ≥ 1.30 (RTL, dialogs, multi-file upload) |
| AI | **Azure OpenAI** — `gpt-4o` (Vision) או `gpt-5.4` (Reasoning) |
| PDF → Image | **pypdfium2** (Apache 2.0, מבוסס Chromium PDFium) ב-DPI 300 |
| OCR Fallback | **pytesseract** (אופציונלי) |
| Excel | **pandas** + **openpyxl** |
| HTML Report | template strings + RTL CSS (Ctrl+P → Save as PDF דרך הדפדפן) |
| Python | 3.13 (תיבת `.venv` מקומית) |

---

## מבנה התיקיות

```
AIDrawAnalyser/
├── app.py                      # נקודת כניסה ראשית של Streamlit
├── ui_assembly.py              # מסך מצב 'מכלולים מרובים'
├── requirements.txt
├── Run_Web.bat                 # הפעלה מהירה ב-Windows
├── README.md
├── DRAWINGAI_LITE_COPILOT_INSTRUCTIONS.md
├── Masters.xlsx                # 1239 מאסטרים של ציפויים
├── .env / .env.example         # מפתחות Azure
│
├── core/                       # לוגיקה עסקית
│   ├── __init__.py
│   ├── azure_client.py         # ניהול clients ל-Vision / Reasoning
│   ├── ai_helpers.py           # call_vision/call_text/safe_call משותפים + retry decorator
│   ├── exceptions.py           # היררכיית custom exceptions + format_error_for_ui
│   ├── drawing_cache.py        # cache לפי MD5 + model + pipeline version
│   ├── pdf_utils.py            # PDF → JPEG base64 + image_file_to_b64 (PNG/JPG/WEBP)
│   ├── ocr_fallback.py         # Tesseract fallback
│   ├── validators.py           # ולידציות post-processing (RAL/brands/coating/packing)
│   ├── two_pass.py             # Two-Pass compare לשדות קריטיים בצביעה
│   ├── master_matcher.py       # התאמת ציפויים למאגר Masters (מודול בודד)
│   ├── cost_tracker.py         # מעקב עלויות לכל שרטוט (AZURE_SURCHARGE מ-env)
│   ├── pn_utils.py             # reconcile P/N · revision · drawing number
│   ├── text_utils.py           # נירמול לקוחות/CAGE + תיקוני טקסט BOM
│   ├── _customer_data.py       # מיפוי CAGE↔לקוח (data/customer_mappings.json)
│   ├── assembly_prompts.py     # טוען פרומפטים חיצוניים מ-prompts/assembly/
│   └── assembly/               # ★ Pipeline מאוחד לשני המצבים
│       ├── __init__.py         # API ציבורי: extract_assembly_drawing / extract_assembly_overview_image / analyze_relationships
│       ├── api.py              # _call_vision / _call_text_json (Azure helpers)
│       ├── material.py         # חילוץ MATERIAL מ-OCR (label-based + direct regex)
│       ├── post_process.py     # תיקונים / ולידציות אחרי Stage 1+2
│       ├── pipeline.py         # extract_assembly_drawing + extract_assembly_overview_image
│       └── relationships.py    # analyze_relationships (קשרי אבא/בן בין השרטוטים)
│   ├── cost_tracker.py         # מעקב עלויות לכל שרטוט (AZURE_SURCHARGE מ-env)
│   ├── assembly_prompts.py     # טוען פרומפטים + Overview Image
│   └── assembly/               # Pipeline מאוחד
│
├── prompts/                     # קבצי פרומפטים חיצוניים
│   ├── single/                  # legacy — לא בשימוש ב-runtime
│   └── assembly/                # stage_1.txt, stage_2.txt, overview_image.txt, relationships_template.txt
│
├── storage/                     # שכבת שמירה / ייצוא
│   ├── __init__.py
│   ├── save_handler.py         # JSON + Excel
│   └── pdf_report.py           # דוחות PDF (מלא + עץ מקוצר) + Tree Excel
│
├── tests/                       # 13 קבצי בדיקות + regression/
│   ├── test_assembly_pipeline.py    # pipeline מלא עם mocks ל-Azure
│   ├── test_assembly_material.py    # חילוץ MATERIAL
│   ├── test_drawing_cache.py        # MD5 cache I/O
│   ├── test_two_pass.py             # מיזוג שתי הרצות
│   ├── test_pdf_utils.py            # מידור בודד / תמונה
│   ├── test_ai_helpers.py           # retry / safe_call / fallback model
│   ├── test_azure_client.py         # הגדרות client / runtime settings
│   ├── test_customer_data.py        # CAGE ↔ customer
│   ├── test_master_matcher.py       # 26 בדיקות ל-Master Matcher
│   ├── test_validators.py           # validators (RAL/מותגים/אריזה)
│   ├── test_exceptions.py           # 20 בדיקות ל-exceptions
│   ├── test_pn_utils.py             # reconcile P/N
│   ├── test_text_utils.py
│   └── regression/                  # post_process regression
│
├── draws/                      # PDF קלט (לבדיקות)
└── output/                     # תוצאות ניתוח + costs.jsonl
```

---

## התקנה והרצה

### דרישות מקדימות
- Python 3.10+ (מומלץ 3.13)
- חשבון Azure OpenAI עם deployment של `gpt-4o` או `gpt-5.4`
- (אופציונלי) Tesseract OCR עבור fallback

### צעדים

```powershell
# 1. שכפול
git clone <repo> AIDrawAnalyser
cd AIDrawAnalyser

# 2. סביבה וירטואלית
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. תלויות
pip install -r requirements.txt

# 4. משתני סביבה — העתק וערוך
copy .env.example .env
# ערוך את .env והוסף את מפתחות Azure שלך

# 5. הרצה
streamlit run app.py
# או:
.\Run_Web.bat
```

האפליקציה תיפתח ב-`http://localhost:8501`.

---

## משתני סביבה

הקובץ `.env` בשורש הפרויקט:

```env
# בחירת מודל פעיל
ACTIVE_MODEL=gpt-4o-vision           # או "gpt-5.4"

# ─── Azure OpenAI (gpt-4o / Vision) ───
AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com
AZURE_OPENAI_API_KEY=<your-key>
AZURE_OPENAI_API_VERSION=2024-08-01-preview
AZURE_OPENAI_DEPLOYMENT=gpt-4o

# ─── GPT-5.4 (Reasoning) ───
MODEL_GPT_5_4_ENDPOINT=https://<your-resource>.openai.azure.com
MODEL_GPT_5_4_API_KEY=<your-key>
MODEL_GPT_5_4_API_VERSION=2024-12-11-preview
MODEL_GPT_5_4_DEPLOYMENT=gpt-5.4
MODEL_GPT_5_4_IS_REASONING=true

# ─── תוספת Azure על מחירי OpenAI הרשמיים ───
# 1.10 = +10% (ברירת מחדל ישנה) · 1.20 = +20% (Azure Regional)
AZURE_SURCHARGE=1.20

# ─── Drawing Cache (אופציונלי) ───
# true = השבת cache לחלוטין (ירוץ תמיד AI)
DRAWING_CACHE_DISABLED=false
```

---

## שני מצבי האפליקציה

המתג בסרגל הצד מתחת ל-"🧭 מצב עבודה":

### 🔍 שרטוט בודד (Single Mode)

- העלאת **קובץ PDF אחד**.
- ניתוח 3-שלבי (basic info → processes → Hebrew summary).
- **התאמת מאסטרים** מ-Masters.xlsx — Top-3 לכל ציפוי עם ציון 0-150.
- תצוגה: כרטיס "מבט-על", פירוט מלא, חלופות מאסטרים, אריזה, NOTES.
- שמירה: JSON / Excel.

### 🧩 מכלולים מרובים (Assembly Mode)

- העלאת **מספר קבצים יחד** — PDF + תמונת Exploded View (PNG/JPG/WEBP).
- תמונת מכלול (Overview Image) ממוינת אוטומטית לראש הרשימה ללא קשר לסדר ההעלאה.
- ניתוח **כל שרטוט בנפרד** (כולל עיבוד שבבי, BOM, בדיקות).
- ניווט עם חצים `⏮️ ◀️ ▶️ ⏭️` ו-selectbox בין השרטוטים.
- כפתור **"נתח קשרי אבא/בן"** מפעיל קריאת AI נפרדת על כל הנתונים
  (משתמש בתמונת המכלול כמפה מבנית אם זמינה).
- שלושה דוחות זמינים להורדה:
  - **📄 דוח HTML מלא** — כל השדות לכל שרטוט + קשרים (פותחים בדפדפן · Ctrl+P → Save as PDF).
  - **🌳 דוח עץ מוצר (PDF מקוצר)** — טבלה + סכמה ויזואלית.
   - **📊 עץ מוצר ל-Excel** — גיליון `Tree` עם רמה/אב ישיר/PN/Drawing/תיאור/כמות/חומר/נתיב.
   - **🧭 גיליון `OverviewImage` / `עץ מתמונה`** — פריטי Exploded View מופרדים מעץ המוצר האמיתי.
- שמירה: JSON מאוחד + PDF + Excel.

> **קריטי**: שני המצבים משתמשים בפרומפטים נפרדים (`core/prompts.py` מול
> `core/assembly_prompts.py`) ובמודולים נפרדים, כך שכל שינוי במצב אחד
> אינו משפיע על השני.

---

## Pipeline של מצב 'שרטוט בודד'

מימוש ב-[core/assembly/pipeline.py](core/assembly/pipeline.py) דרך `extract_assembly_drawing()`.

```
PDF
 │
 ├─► Cache lookup (MD5 + model + pipeline version) ──► HIT? החזר תוצאה
 │
 ├─► pypdfium2: pdf_to_images(dpi=300) ──► [JPEG base64]
 │
 ├─► Stage 1 (Vision): basic info
 │     • part_number, revision, drawing_number, customer, material
 │     • assembly_role, bom_items, quantity
 │
 ├─► OCR מראש + Stage 1 Retry (רק אם זמין)
 │     • Tesseract → enhanced prompt → ניסיון נוסף
 │
 ├─► Stage 2 (Vision): Production Routing Chart
 │     • machining_processes, coating_processes, painting_processes
 │     • inspection_processes, final_approval, additional_processes
 │     • packaging_notes, standards, notes
 │
 ├─► Post-processing (validation + reconciliation)
 │     • חילוץ material מ-NOTES אם חסר
 │     • _reconcile_part_number / drawing_number / revision
 │     • run_all_validators: בדיקות RAL, מותגים, סיווג ציפוי, אריזה
 │
 ├─► save_cached_result (MD5 + model) ──► תוצאה זמינה ל-runs עתידיים
 │
 └─► תוצאה מלאה + _cost_info + _ocr_used + _validation_warnings
```

> **הערה**: מצב 'שרטוט בודד' **לא כולל** Stage 3 (עברית) או master matching.
> את זה עושה סקריפט חיצוני אם נדרש. ראה `core/master_matcher.py`.

## Pipeline של מצב 'מכלולים מרובים'

מימוש ב-[core/assembly.py](core/assembly.py) ו-[core/assembly_prompts.py](core/assembly_prompts.py).

```
לכל PDF (במקביל ב-loop):
 │
 ├─► OCR מוקדם
 ├─► Assembly Stage 1: basic + assembly_role + bom_items + quantity
 ├─► Assembly Stage 2: כל ה-Production Routing Chart
 │     • machining_processes (עיבוד שבבי לפי step_no)
 │     • coating_processes / painting_processes
 │     • inspection_processes / final_approval
 │     • additional_processes / packaging_notes
 │     • standards / notes
 │
 └─► תוצאה — ללא התאמת מאסטרים, ללא Stage 3 עברי

לאחר שכל השרטוטים נותחו:
 │
 └─► analyze_relationships(results)
       • בונה תקציר טקסטואלי של כל שרטוט (P/N, role, BOM, processes)
       • שולח קריאת AI אחת על כל הנתונים יחד
       • מחזיר:
           - summary_he
           - assemblies: [{parent, children:[...]}]
           - orphans: שרטוטים בלי הורה
           - missing_children: BOM שלא הועלה כקובץ

לאחר יצירת relationships:
   • מסננים צומתי Overview מהעץ האמיתי (כדי לא לזהם היררכיה)
   • בגיליון עץ-מתמונה מבצעים התאמה שמרנית:
      - התאמה לפי Item No. בעדיפות ראשונה
      - fallback לפי part_number
      - קישורי Drawing/PN מוצגים רק אם הקובץ קיים בפועל
      - נתוני BOM (כמות/תיאור) מוצגים כשיש התאמה ל-BOM גם ללא קובץ שרטוט
           - warnings_he
```

ייצוא הדוח דרך [storage/pdf_report.py](storage/pdf_report.py) משתמש ב-
template strings עם HTML/CSS RTL לעברית. הקובץ HTML עצמאי — נפתח בכל דפדפן וניתן לשמירה כ-PDF דרך Ctrl+P.

---

## מנגנון התאמת מאסטרים

מימוש ב-[core/master_matcher.py](core/master_matcher.py).

מאגר Masters.xlsx מכיל ~1239 ציפויים סטנדרטיים. לכל ציפוי שהמודל מחלץ
מהשרטוט, האלגוריתם מחשב ציון התאמה (0-150) מול **כל המאסטרים** ובוחר
את ה-Top 3.

### משקלות הציון

| קריטריון | משקל | הערה |
|----------|------|------|
| **W_COATING_TYPE** | +50 | סוג ציפוי (zinc/nickel/anodize/...) — הכי קריטי |
| W_COATING_TYPE_PENALTY | -30 | קנס לסוג ציפוי שונה לחלוטין |
| **W_STANDARD** | +30 | קודי תקן משותפים (MIL/AMS/ASTM/QQ/PS/FED-STD) |
| W_STANDARD_EXTRA_PENALTY | -12 | **לכל תקן עודף במאסטר** שלא בשרטוט |
| W_TYPE_CLASS | +20 | Type/Class/Grade בתוך התקן |
| W_THICKNESS | +15 | חפיפת טווחי עובי |
| W_PHOSPHORUS | +15 | רמת זרחן ב-Electroless Nickel (High/Med/Low) |
| W_ROHS | +12 / -10 | תאימות RoHS דו-כיוונית |
| W_COLOR | +8 | NATURAL ≡ BLUE/WHITE chromate |

### לקחים מרכזיים בקוד

1. **תקנים עודפים במאסטר** — הוספת קנס מנע בחירת מאסטר משולב כמו
   "Tin over Electroless Nickel" כשהשרטוט מכיל רק תקן אחד מהם.
2. **גרסת תקן צמודה** — `AMS-C-26074D` ↔ `AMS-C-26074` נחשבים זהים
   (regex מורחב + נירמול אות גרסה אחרונה).
3. **Phosphorus level** — מבחין בין `Electroless Nickel High Phosphor` ו-`Low
   Phosphor` שהם מאסטרים שונים לחלוטין.

---

## מעקב עלויות

מימוש ב-[core/cost_tracker.py](core/cost_tracker.py).

- כל קריאת API נצברת ב-`DrawingCostTracker` עם input/output tokens.
- מחיר לכל מודל ב-`MODEL_PRICING` (USD per 1M tokens) + תוסף Azure לפי
  `AZURE_SURCHARGE` מ-`.env` (ברירת מחדל 1.20 = +20%; ניתן להגדיר 1.10 וכו').
  ראה `core/cost_tracker.py`.
- בכל שרטוט נשמרת שורה ב-`output/costs.jsonl`.
- פאנל מנהל בסרגל הצד מציג: סכום מצטבר, ממוצע, ופירוט לפי שלבים.
- במצב מכלולים מוצג גם סיכום עלויות סשן + פירוט לכל שרטוט בנפרד.

---

## קבצים מרכזיים — תפקיד מודולרי

### שכבת UI

| קובץ | תפקיד |
|------|-------|
| [app.py](app.py) | נקודת כניסה. בורר מצב + מסך 'שרטוט בודד' |
| [ui_assembly.py](ui_assembly.py) | מסך 'מכלולים מרובים' (העלאה מרובה, ניווט, PDF) |

### שכבת לוגיקה (`core/`)

| קובץ | תפקיד |
|------|-------|
| [core/azure_client.py](core/azure_client.py) | בחירת client לפי `ACTIVE_MODEL` (Vision/Reasoning) |
| [core/ai_helpers.py](core/ai_helpers.py) | `call_vision` / `call_text` / `safe_call` משותפים + `retry_on_transient` decorator |
| [core/exceptions.py](core/exceptions.py) | 15 custom exceptions עם עברית ידידותית + `format_error_for_ui` |
| [core/drawing_cache.py](core/drawing_cache.py) | cache תוצאות חילוץ לפי MD5(file) + model + pipeline version |
| [core/pdf_utils.py](core/pdf_utils.py) | המרת PDF לתמונות JPEG base64 (זורק `PDFError`/`ImageError` על פגמים) |
| [core/ocr_fallback.py](core/ocr_fallback.py) | Tesseract fallback (מותנה: רק אם זמין) |
| [core/validators.py](core/validators.py) | ולידציה post-processing (RAL, מותגים, סיווג ציפוי, הוראות אריזה) |
| [core/two_pass.py](core/two_pass.py) | Two-Pass השוואה לשדות קריטיים בצביעה + זיהוי אי-עקביות |
| [core/pn_utils.py](core/pn_utils.py) | reconcile P/N, drawing number, revision משמות קבצים ותוכן |
| [core/text_utils.py](core/text_utils.py) | נירמול CAGE↔customer, טיפול בטקסט BOM |
| [core/master_matcher.py](core/master_matcher.py) | אלגוריתם ציון התאמה (0-150) ל-Masters.xlsx — **משימוש יידני** |
| [core/cost_tracker.py](core/cost_tracker.py) | מצבר עלויות + לוג JSONL + תוסף Azure |
| [core/assembly_prompts.py](core/assembly_prompts.py) | טוען פרומפטים מ-`prompts/assembly/` |
| [core/assembly/api.py](core/assembly/api.py) | `_call_vision` / `_call_text_json` (Azure helpers פנימיים) |
| [core/assembly/material.py](core/assembly/material.py) | חילוץ MATERIAL מ-OCR (label-based + direct regex) |
| [core/assembly/post_process.py](core/assembly/post_process.py) | תיקונים + ולידציות אחרי Stage 1+2 |
| [core/assembly/pipeline.py](core/assembly/pipeline.py) | `extract_assembly_drawing()` + `extract_assembly_overview_image()` — **entry points** |
| [core/assembly/relationships.py](core/assembly/relationships.py) | `analyze_relationships()` — קשרי אבא/בן בין שרטוטים |

### שכבת שמירה (`storage/`)

| קובץ | תפקיד |
|------|-------|
| [storage/save_handler.py](storage/save_handler.py) | שמירה ל-JSON / Excel |
| [storage/pdf_report.py](storage/pdf_report.py) | דוח HTML עברי (RTL, @page A4, Print bar) — שם הקובץ נשמר היסטורית. Backwards-compat: `build_assembly_pdf` = `build_assembly_html` alias. |

---

## פלטים / קבצי שמירה

תיקיית `output/` מכילה:

| קובץ | תוכן |
|------|------|
| `<basename>_<timestamp>.json` | תוצאת ניתוח של שרטוט בודד |
| `<basename>_<timestamp>.xlsx` | Excel רב-גיליוני: Summary / Coatings / Paintings / Master_Matches / Standards / Warnings |
| `_assembly_<timestamp>.json` | תוצאת ניתוח מכלול (כל הDrawings + relationships) |
| `_assembly_report_<timestamp>.html` | דוח HTML מלא של מכלול (פותחים בדפדפן · Ctrl+P → Save as PDF) |
| `_assembly_tree_<timestamp>.pdf` | דוח עץ מוצר מקוצר (טבלה + סכמה) |
| `_assembly_tree_<timestamp>.xlsx` | עץ מוצר ל-Excel (גיליון `Tree`) |
| `costs.jsonl` | לוג מצטבר של עלויות AI (שורה לשרטוט) |
| `.cache/<md5>.json` | Drawing Cache — תוצאות חילוץ ממוחזרות לפי MD5 |

---

## עקרונות עיצוב מרכזיים

1. **Pipeline מאוחד** — שני המצבים משתמשים ב-`core/assembly/` (מה שנקרא `extract_assembly_drawing()` מעל). הפרדה בין מצבים עשויה דרך flow שונה ב-UI ([app.py](app.py) / [ui_assembly.py](ui_assembly.py)), לא בלוגיקה הליבה.
2. **Evidence-based extraction** — הפרומפטים אוסרים מפורשות על ניחושים;
   הציון משלים יחד עם RegEx fallback (material מ-NOTES, part_number משם הקובץ).
3. **RTL native** — כל ה-UI ודוח ה-PDF משתמשים ב-`unicode-bidi:plaintext`
   כדי לטפל בעברית עם תקנים אנגליים מעורבים.
4. **Cost-aware** — כל קריאה נמדדת; פאנל מנהל מסתיר את הפרטים מעיני
   המשתמש הסופי.
5. **Reasoning vs Vision** — `is_reasoning_model()` מתאים את ה-kwargs
   (`max_completion_tokens` במקום `max_tokens`, ללא `temperature`).
6. **Error Boundary** — היררכיית exceptions ב-[core/exceptions.py](core/exceptions.py)
   עם `user_message` עברי + `severity` + `suggestion`. המשתמש רואה הודעה
   ידידותית, לא stack trace.
7. **Cache-first** — לפני כל קריאה ל-AI, [core/drawing_cache.py](core/drawing_cache.py)
   בודק אם יש תוצאה שמורה לאותו MD5. חיסכון כספי על שרטוטים חוזרים.
8. **Retry אוטומטי** — [core/ai_helpers.py](core/ai_helpers.py) מלבד
   `safe_call` (fallback מודל) גם `retry_on_transient` decorator עם
   exponential backoff לשגיאות רשת זמניות.

---

## רישוי

פרויקט פנימי. ראה [README.md](README.md) למידע נוסף.

---

## שינויים אחרונים (Changelog)

ראה [CHANGELOG.md](CHANGELOG.md) לפירוט מלא של עדכונים, תיקוני באגים ותכונות חדשות.
