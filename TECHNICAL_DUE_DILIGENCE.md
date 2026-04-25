# Technical Due Diligence — AIDrawAnalyser

> מסמך זה מיועד לקונה / שותף טכנולוגי שעורך בדיקת נאותות לקוד. הוא מסכם
> ארכיטקטורה, תלויות, סיכונים, מגבלות ידועות, ונקודות שדורשות תשומת לב
> בהעברה.
>
> תאריך: 2026-04-25 · מתחזקת: yelena (`stolena2010-blip`)

---

## 1. סקירה בקצרה

| שדה | ערך |
|---|---|
| שם | AIDrawAnalyser |
| תיאור | חילוץ מידע משרטוטים הנדסיים (PDF) באמצעות Azure OpenAI Vision/Reasoning |
| סוג | אפליקציית Streamlit (single-tenant, on-prem / desktop) |
| שפת תכנות | Python 3.10+ (אומת על 3.11 ו-3.13 ב-CI) |
| Lines of code | ~10,000 שורות Python (לא כולל בדיקות) |
| LOC בדיקות | ~3,500 שורות, 405 בדיקות |
| תלויות חיצוניות | 8 ספריות ליבה (ראה [LICENSE_REVIEW.md](LICENSE_REVIEW.md)) |
| AI provider | Azure OpenAI בלבד (ניתן להחלפה ב-OpenAI / אחרים — ראה סיכון #3) |
| מודלים נתמכים | `gpt-4o` (Vision), `gpt-5.4` (Reasoning) — fallback אוטומטי |

---

## 2. ארכיטקטורה

### 2.1 שכבות

```
┌─────────────────────────────────────────────────────────┐
│ UI Layer (Streamlit)                                    │
│  app.py            — Single-drawing mode                │
│  ui_assembly.py    — Multi-drawing assembly mode        │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│ Pipeline Layer (core/assembly/)                         │
│  pipeline.py       — extract_assembly_drawing()         │
│  relationships.py  — analyze_relationships()            │
│  post_process.py   — validators + reconciliation        │
│  material.py       — OCR-based material extraction      │
│  api.py            — _call_vision / _call_text_json     │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│ Helpers Layer (core/)                                   │
│  azure_client      ai_helpers     drawing_cache          │
│  pdf_utils         ocr_fallback   pn_utils  text_utils   │
│  validators        cost_tracker   exceptions             │
│  master_matcher    two_pass       _customer_data         │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│ Storage Layer (storage/)                                │
│  save_handler.py   — JSON + multi-sheet Excel           │
│  pdf_report.py     — Hebrew RTL PDF reports             │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│ External (Azure OpenAI · Tesseract OCR · filesystem)    │
└─────────────────────────────────────────────────────────┘
```

### 2.2 Pipeline בקצרה

לכל שרטוט PDF:

1. **Cache lookup** — לפי MD5(file) + model + pipeline version. Cache hit מחזיר מיידית.
2. **PDF → Images** — pypdfium2 (Apache 2.0, Chromium PDFium), DPI=300, JPEG base64.
3. **OCR מקדים** — Tesseract (אם זמין) למילוי טקסט גולמי לעזרת ה-prompts.
4. **Stage 1 (Vision)** — basic info (P/N, revision, customer, material, BOM, role).
5. **Stage 2 (Vision)** — Production Routing Chart (machining/coating/painting/inspection/packing/standards).
6. **Post-processing** — reconcile P/N + revision + drawing number, normalize customer/CAGE,
   validate (RAL, brand names, coating classification, packing).
7. **Cache save** — תוצאה נשמרת ב-`output/.cache/<md5>.json`.

במצב Assembly יש שלב נוסף — `analyze_relationships()` שמקבל את כל ה-drawings יחד
ומסיק קשרי אבא/בן.

### 2.3 פרומפטים

חיצוניים, ב-`prompts/assembly/`:
- `stage_1.txt`, `stage_2.txt` — Vision prompts לחילוץ
- `overview_image.txt` — לתמונת מכלול גרפית
- `relationships_template.txt` — לניתוח קשרים

שינוי פרומפט → צריך bump של `CACHE_VERSION` ב-`core/drawing_cache.py` כדי לאלץ ניתוח מחדש.

---

## 3. תלויות צד שלישי

ראה [LICENSE_REVIEW.md](LICENSE_REVIEW.md) לרשימה מלאה עם רישיונות.

תקציר:

| חבילה | מטרה | רישיון | סיכון |
|---|---|---|---|
| streamlit | UI | Apache 2.0 | נמוך |
| openai | Azure client | Apache 2.0 | נמוך |
| pypdfium2 | PDF → image | Apache 2.0 | נמוך |
| Pillow | image processing | MIT-CMU | נמוך |
| pytesseract | OCR wrapper | Apache 2.0 | נמוך (Tesseract: Apache 2.0) |
| pandas | DataFrames לייצוא | BSD 3-clause | נמוך |
| openpyxl | Excel I/O | MIT | נמוך |
| python-dotenv | env vars | BSD 3-clause | נמוך |

---

## 4. סיכונים מרכזיים

### ~~סיכון #1 — רישיון PyMuPDF (AGPL)~~ ✅ נפתר

PyMuPDF הוסר לחלוטין מהפרויקט (אפריל 2026):
- **קלט (PDF→Images):** הוחלף ל-`pypdfium2` (Apache 2.0, מבוסס Chromium PDFium)
- **פלט (דוחות):** הוחלף מ-PDF ל-**HTML עצמאי**. הקונה לוחץ Ctrl+P בדפדפן כדי לקבל PDF.

**תוצאה:** כל התלויות עכשיו permissive (Apache 2.0 / MIT / BSD). אין צורך לקנות רישיון מסחרי לאף תרחיש שימוש.

ראה [LICENSE_REVIEW.md](LICENSE_REVIEW.md) סעיף 3 לפרטים מלאים על המעבר.

### סיכון #2 — תלות בלעדית ב-Azure OpenAI

כל הקריאות עוברות דרך `core/azure_client.py`. אין abstraction layer גנרי לספק AI אחר.

**השפעה:** קונה שמעדיף OpenAI ישיר / Anthropic / Google / מודל local יצטרך לשנות את `azure_client.py`.

**מיטיגציה:** ההפרדה ב-`core/ai_helpers.py` (call_vision/call_text/safe_call) מקלה על החלפה.
מאמץ מוערך: 2-3 ימי פיתוח.

### סיכון #3 — נתוני לקוחות במאגר

`data/customer_mappings.json` (tracked בגיט) מכיל שמות לקוחות אמיתיים מתחום הביטחון
הישראלי + קודי CAGE. ראה [DATA_HANDLING.md](DATA_HANDLING.md#customer-mappings).

**השפעה:** קונה עלול לראות את זה כסיכון משפטי / חשיפה של קשרי לקוחות.

**מיטיגציה מוצעת:** לפני העברה — פיצול ל-`customer_mappings.example.json` (sanitized,
tracked) + `customer_mappings.json` (real, gitignored, נטען בזמן ריצה).

### סיכון #4 — אין מדידת דיוק רשמית

יש 405 unit tests עם mocks ל-Azure, אבל אין **טבלת accuracy** שמודדת precision/recall
על שרטוטים אמיתיים (ground truth).

**השפעה:** קונה לא יכול להעריך כמה השדות באמת נכונים בהפעלה אמיתית.

**מיטיגציה מוצעת:** לבנות סט של 20-50 שרטוטים מסוננים עם תיוג ידני, ולתעד accuracy
לפי שדה. זמן מוערך: שבוע עבודה.

### סיכון #5 — אין טיפול ב-PDF זדוני

`core/pdf_utils.py` לא בודק:
- `file_size` (יכול להיות זיכרון בלתי-מוגבל)
- `page_count` (PDF עם 10,000 עמודים יחנוק את ה-API)
- magic bytes (`%PDF-`)
- embedded JavaScript

**השפעה:** קל-בינוני. אם הכלי משמש לקבצים פנימיים מאומתים — נמוך.
לעיבוד קבצים מהאינטרנט — חייב לטפל.

**מיטיגציה:** הוספת בדיקות `MAX_PDF_MB` ו-`MAX_PAGES` — שעה-שעתיים פיתוח.

### סיכון #6 — לא נעולים גרסאות תלויות

`requirements.txt` משתמש ב-`>=` בלבד. התקנה ב-2027 עלולה להביא גרסאות שוברות של
streamlit / openai / pypdfium2.

**השפעה:** רפרודוקציה בעייתית במכשיר נקי.

**מיטיגציה:** ליצור `requirements.lock.txt` מ-`pip freeze`. ראה [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md).

---

## 5. מגבלות ידועות

### 5.1 דיוק

- **OCR בעברית** עובד אבל לא מושלם — דורש Tesseract עם `tesseract-ocr-heb`.
- **שרטוטים סרוקים בנמוך-DPI** (< 200 DPI) — ירידה בדיוק חילוץ.
- **שרטוטים בכתב יד** — לא נתמכים.
- **טבלאות BOM ארוכות מאוד** (>50 פריטים) — עלולות להיחתך בהקשר של המודל.

### 5.2 ביצועים

- **שרטוט בודד**: 20-40 שניות (Vision call יחיד) או 5-10 שניות (cache hit).
- **מכלול 5 שרטוטים**: 1.5-3 דקות (סדרתי). אין כרגע parallelization.
- **עלות API לשרטוט**: $0.02-$0.08 (gpt-4o), $0.10-$0.40 (gpt-5.4 reasoning). תלוי בגודל.

### 5.3 דברים שלא נבדקו

- **לא רץ Linux production** — האפליקציה נכתבה ל-Windows. CI רץ Linux אך רק unit tests עם mocks.
- **לא נבדק ב-multi-user** — Streamlit single-tenant, אין auth, אין session isolation מעבר ל-`st.session_state`.
- **אין load test** — מה קורה ב-100 שרטוטים מקבילים? לא נבדק.

---

## 6. איכות קוד

| מדד | ערך |
|---|---|
| Tests | 405 (כולם passing) |
| בדיקות שעוברות ב-CI | Python 3.11 + 3.13 |
| Lint | ruff עם config ב-`pyproject.toml`, **חוסם** ב-CI |
| Type hints | חלקי — לא מוגדר `mypy` |
| Coverage | לא נמדד פורמלית; הוערך כ-~75% (כיסוי גבוה ב-pn_utils, validators, text_utils, assembly) |
| Logging | `logging.getLogger(__name__)` בכל מודול. אין רוטציה לקובץ. |
| Pre-commit | אין |

---

## 7. נקודות העברה (Handover)

קונה שמקבל את הקוד צריך:

1. **גישה ל-Azure OpenAI** עם deployments של `gpt-4o` ו-`gpt-5.4` (אופציונלי).
2. לעדכן את `data/customer_mappings.json` למיפויים שלו (או למחוק אותו).
3. לבחון את `Masters.xlsx` — קובץ מאסטרים שתלוי בעסק שלו (אם הוא משתמש ב-master matching).
4. להתקין Tesseract OCR (אופציונלי, ל-fallback).
5. להגדיר `.env` עם המפתחות שלו.

ראה [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) להוראות מלאות.

---

## 8. דברים שכדאי לתקן לפני העברה

ראה [SALE_READINESS_RECOMMENDATIONS.md](SALE_READINESS_RECOMMENDATIONS.md) לפירוט מלא.

קצר:

- [ ] להחליט על LICENSE (proprietary / commercial / open).
- [ ] לפצל `customer_mappings.json` ל-example + real (gitignored).
- [ ] ליצור `requirements.lock.txt`.
- [ ] להוסיף בדיקת magic bytes + size limit ב-`pdf_utils.py`.
- [ ] לבנות טבלת accuracy בסיסית.
- [x] ~~להחליט אם להשאיר את התלות ב-PyMuPDF (AGPL) או להחליף.~~ ✅ הוחלף — ראה LICENSE_REVIEW.md

---

## 9. קישורים

- [README.md](README.md) — הקדמה ושימוש
- [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) — סקירה מפורטת של ה-pipeline
- [SECURITY.md](SECURITY.md) — מדיניות אבטחה
- [DATA_HANDLING.md](DATA_HANDLING.md) — מה נשלח / נשמר / נמחק
- [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) — התקנה בסביבת קונה
- [LICENSE_REVIEW.md](LICENSE_REVIEW.md) — תלויות ורישיונות
- [CHANGELOG.md](CHANGELOG.md) — היסטוריית שינויים
