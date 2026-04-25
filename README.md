# 📐 AIDrawAnalyser

[![CI](https://github.com/stolena2010-blip/AIDrawAnalyser/actions/workflows/ci.yml/badge.svg)](https://github.com/stolena2010-blip/AIDrawAnalyser/actions/workflows/ci.yml)

אפליקציית Streamlit לניתוח שרטוטים טכניים (PDF) באמצעות Azure OpenAI Vision / Reasoning.

## תכולה

### 🔍 מצב 'שרטוט בודד'
- העלאת PDF יחיד → חילוץ אוטומטי של שדות טכניים (P/N, revision, customer, material, תהליכי ציפוי/צביעה, עיבוד שבבי, תקנים, הערות)
- **OCR אוטומטי** (Tesseract) כגיבוי לחילוץ שדות חסרים
- **שכבת ולידציה בקוד**: RAL תקני, מותגי צבע, סיווג ציפויים, והוראות אריזה חשודות
- הצגת **אזהרות ולידציה** ו-**המודל בפועל לכל שלב** במסך התוצאות
- **Drawing Cache** אוטומטי לפי MD5 — חיסכון משמעותי ב-API runs חוזרים
- שמירת תוצאות ל-**JSON** או **Excel רב-גיליוני** (Summary / Coatings / Paintings / Standards / Warnings)

> **הערה ארכיטקטונית:** ממאי 2026 שני המצבים משתמשים ב-pipeline **מאוחד** תחת `core/assembly/`.
> המצב ה'בודד' הישן (`core/extractor.py` + Stage 3 עברי + master matching אוטומטי) הוסר.
> מודול `core/master_matcher.py` עדיין קיים לשימוש ידני / סקריפטים.

### 🧩 מצב 'מכלולים מרובים'
- העלאת מספר PDFים יחד **או** תמונת Exploded View (PNG/JPG/WEBP)
- ניתוח כל שרטוט בנפרד + ניתוח קשרי אבא/בן בין השרטוטים
- תמונת מכלול ממוינת אוטומטית לראש (לא משנה סדר ההעלאה)
- גיליון **עץ מתמונה** נבנה עם קישור שמרני:
  - התאמה לפי `Item No.` בעדיפות ראשונה (עם fallback ל-`part_number`)
  - תיקון `P/N` שגוי מהתמונה לפי התאמת BOM מאומתת (למשל טעויות OCR)
  - `קושר ל-P/N` / `קושר ל-Drawing` מתמלאים רק אם קיים שרטוט שהועלה בפועל
  - `כמות לפי BOM` / `תיאור BOM` נשמרים כשיש התאמת BOM, גם אם אין שרטוט קיים
  - ללא ניחוש קישורים: עמודת `נמצא בקבצים?` מסמנת רק `כן/לא` לפי קבצים אמיתיים
- ייצוא:
  - 📄 דוח HTML מלא (RTL עברית · Ctrl+P → Save as PDF)
  - 🌳 דוח עץ מוצר מקוצר ב-HTML (טבלה + סכמה ויזואלית)
  - 📊 עץ מוצר ל-Excel (כולל עמודות אב ישיר/נתיב)
  - 🧭 גיליון נפרד לעץ מהתמונה (ללא ערבוב עם עץ מוצר אמיתי)
  - 💾 JSON מאוחד

### 💰 מעקב עלויות
- כל קריאת API נמדדת ונשמרת ב-`output/costs.jsonl`
- תוסף Azure ניתן להגדרה דרך `AZURE_SURCHARGE` ב-`.env`
- **Drawing Cache** לפי MD5 של הקובץ + גרסת מודל → runs חוזרים חינמיים
  (ניתן לכיבוי עם `DRAWING_CACHE_DISABLED=true`)

### 🛡️ יציבות
- **Custom Exceptions** עם הודעות עברית ידידותיות למשתמש (לא stack traces)
- **Retry אוטומטי** על שגיאות רשת/API זמניות (exponential backoff)
- **Fallback מודל** אוטומטי — אם gpt-4o נכשל, עובר ל-gpt-5.4 (ולהפך)

## התקנה

### 1. דרישות מוקדמות
- Python 3.10+ (מומלץ 3.13)
- חשבון Azure OpenAI עם deployment של `gpt-4o` או `gpt-5.4`
- (אופציונלי) [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) — לפעולת OCR Fallback (התקן גם חבילת שפה עברית)

### 2. venv + חבילות
```powershell
cd C:\AIDrawAnalyser
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. הגדרת Azure
```powershell
Copy-Item .env.example .env
# ערוך .env ומלא את הפרטים שלך
```

## הרצה

```powershell
.\.venv\Scripts\Activate.ps1
streamlit run app.py
```

או הרצה מהירה: `Run_Web.bat`

הדפדפן יפתח ב-http://localhost:8501

## בדיקות

```powershell
.\.venv\Scripts\Activate.ps1
pytest tests/ -v
```

## מבנה

```
AIDrawAnalyser/
├── app.py                  ← Streamlit entry (מצב 'שרטוט בודד')
├── ui_assembly.py          ← מסך 'מכלולים מרובים'
├── core/
│   ├── azure_client.py        ← Azure OpenAI wrapper
│   ├── ai_helpers.py          ← call_vision/call_text/safe_call משותפים + retry
│   ├── exceptions.py          ← היררכיית custom exceptions (עברית ידידותית)
│   ├── drawing_cache.py       ← cache לפי MD5 (חיסכון ב-API)
│   ├── pdf_utils.py           ← PDF/Image → base64 (זורק PDFError/ImageError)
│   ├── ocr_fallback.py        ← Tesseract fallback
│   ├── master_matcher.py      ← התאמה למאסטרים (1239 פריטים) — שימוש ידני
│   ├── cost_tracker.py        ← מעקב עלויות
│   ├── validators.py          ← ולידציה לאחר חילוץ (RAL/brands/coating/packing)
│   ├── two_pass.py            ← השוואת שתי הרצות לשדות קריטיים
│   ├── pn_utils.py            ← reconcile של P/N · revision · drawing number
│   ├── text_utils.py          ← נירמול לקוח/CAGE + תיקוני טקסט
│   ├── assembly_prompts.py    ← טוען פרומפטים חיצוניים מ-prompts/assembly/
│   └── assembly/              ← ★ Pipeline מאוחד לשני המצבים
│       ├── api.py             ← _call_vision / _call_text_json
│       ├── material.py        ← חילוץ MATERIAL מ-OCR
│       ├── post_process.py    ← ולידציות + תיקונים אחרי Stage 1+2
│       ├── pipeline.py        ← extract_assembly_drawing + extract_assembly_overview_image
│       └── relationships.py   ← analyze_relationships בין שרטוטים
├── prompts/
│   ├── single/                ← קבצי פרומפטים חיצוניים (legacy)
│   └── assembly/              ← פרומפטים פעילים: stage_1.txt, stage_2.txt, overview_image.txt, relationships_template.txt
├── storage/
│   ├── save_handler.py        ← JSON + Excel רב-גיליוני
│   └── pdf_report.py          ← דוחות PDF (מלא + עץ מוצר) + Excel עץ
├── tests/                     ← 13 קבצי בדיקות + תיקיית regression/
│   ├── test_assembly_pipeline.py
│   ├── test_assembly_material.py
│   ├── test_drawing_cache.py
│   ├── test_two_pass.py
│   ├── test_pdf_utils.py
│   ├── test_ai_helpers.py
│   ├── test_azure_client.py
│   ├── test_customer_data.py
│   ├── test_master_matcher.py
│   ├── test_validators.py
│   ├── test_exceptions.py
│   ├── test_pn_utils.py
│   ├── test_text_utils.py
│   └── regression/            ← בדיקות regression ל-post_processing
├── output/                    ← תוצאות + costs.jsonl
├── Masters.xlsx               ← מאגר ציפויים (לשימוש ידני ע"י master_matcher)
├── requirements.txt
├── .env.example
├── PROJECT_OVERVIEW.md        ← סקירה מפורטת
└── CHANGELOG.md               ← שינויים אחרונים
```

## תיעוד נוסף

### למפתחים
- [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) — סקירה טכנית מלאה של ה-pipeline
- [CHANGELOG.md](CHANGELOG.md) — שינויים אחרונים
- [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) — התקנה במחשב חדש

### למכירה / Due Diligence
- [SALE_READINESS_RECOMMENDATIONS.md](SALE_READINESS_RECOMMENDATIONS.md) — Roadmap להכנה למכירה
- [TECHNICAL_DUE_DILIGENCE.md](TECHNICAL_DUE_DILIGENCE.md) — סקירת ארכיטקטורה, סיכונים ומגבלות
- [SECURITY.md](SECURITY.md) — מדיניות אבטחה
- [DATA_HANDLING.md](DATA_HANDLING.md) — מה נשלח ל-Azure / נשמר מקומית
- [LICENSE_REVIEW.md](LICENSE_REVIEW.md) — תלויות ורישיונות (כולן Apache 2.0 / MIT / BSD — אין AGPL)

