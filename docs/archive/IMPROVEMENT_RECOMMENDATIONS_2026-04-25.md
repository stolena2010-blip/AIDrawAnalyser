# 📋 המלצות לשיפור — DrawingAI Lite / AIDrawAnalyser

> מסמך זה מסכם המלצות מעשיות לשיפור הפרויקט, ממופות לפי **עדיפות** ו-**מאמץ**.
> כל פריט כולל: בעיה → פתרון מוצע → קבצים מושפעים → מדד הצלחה.

---

## 🎯 סיכום מנהלים

הפרויקט במצב **בוגר ומקצועי** (ציון 88/100). ארבעת השיפורים שיביאו את הציון ל-95+ הם:

1. **כיסוי בדיקות לליבת ה-pipeline** (כרגע כיסוי רק לעוזרים)
2. **פיצול `extractor.py`** בסגנון של `assembly/`
3. **Pinning של תלויות** ב-`requirements.lock`
4. **Input validation וטיפול ב-PDFים זדוניים**

---

## 🔴 עדיפות גבוהה

### 1. הוספת בדיקות ל-Pipeline המרכזי
- **בעיה:** `tests/` מכסה רק `master_matcher`, `validators`, `exceptions`, `pn_utils`, `text_utils`.
  המודולים הכי שבירים — [core/extractor.py](core/extractor.py), [core/assembly/pipeline.py](core/assembly/pipeline.py),
  [core/two_pass.py](core/two_pass.py), [core/drawing_cache.py](core/drawing_cache.py) — **ללא בדיקות**.
- **פתרון:**
  - להוסיף `tests/test_extractor.py` עם **mocks** ל-Azure client (לא קריאות אמיתיות).
  - להוסיף `tests/test_drawing_cache.py` (קל — קלט/פלט קבצים).
  - להוסיף `tests/test_two_pass.py` עם תרחישי merge מובנים.
  - להוסיף `tests/test_assembly_pipeline.py` עם BOM mock.
  - להוסיף **fixtures** של JSON תגובות מ-Azure תחת `tests/fixtures/`.
- **מדד:** כיסוי `pytest --cov=core` מעל **75%**.
- **מאמץ:** בינוני-גבוה (1-2 ימי עבודה).

### 2. פיצול `core/extractor.py`
- **בעיה:** קובץ יחיד שמרכז את כל ה-pipeline — קשה לקרוא, קשה לבדוק, מערב imports רבים.
- **פתרון:** לחקות את המבנה של [core/assembly/](core/assembly/):
  ```
  core/single/
    __init__.py
    api.py            # entry point ציבורי
    pipeline.py       # orchestration
    stage1.py         # Vision: basic info
    stage2.py         # Vision: processes
    stage3.py         # Text: Hebrew summary
    post_process.py   # validators + master matching
  ```
- **מדד:** כל קובץ מתחת ל-200 שורות; יבוא ציבורי יציב מ-`core.single`.
- **מאמץ:** בינוני (חצי יום + עדכון imports).

### 3. Input Validation על קבצי PDF
- **בעיה:** אין הגנה מפני PDFים זדוניים (zip-bombs, embedded JS, גודל חורג).
- **פתרון** ב-[core/pdf_utils.py](core/pdf_utils.py):
  - בדיקת `file_size <= MAX_PDF_MB * 1024 * 1024` (ברירת מחדל 50MB).
  - בדיקת `page_count <= MAX_PAGES` (ברירת מחדל 20).
  - בדיקת magic bytes (`%PDF-`) לפני העברה ל-`fitz.open()`.
  - תפיסת `fitz.FileDataError` והעלאה כ-`PDFError` ידידותית.
- **מדד:** בדיקת `tests/test_pdf_utils.py` עם קבצים פגומים/חורגים.
- **מאמץ:** נמוך (שעה-שעתיים).

### 4. Pinning של תלויות
- **בעיה:** [requirements.txt](requirements.txt) משתמש ב-`>=` בלבד — `pip install` חדש עלול להביא major versions שוברות.
- **פתרון:**
  ```powershell
  pip freeze > requirements.lock.txt
  ```
  ולעדכן את `Run_Web.bat` להשתמש ב-`requirements.lock.txt` ב-production.
  להשאיר `requirements.txt` כ-**spec רך** ל-development.
- **מדד:** רפרודוקציה מלאה של הסביבה ב-machine נקי.
- **מאמץ:** מינימלי (15 דק').

---

## 🟡 עדיפות בינונית

### 5. ניקוי `scripts/`
- **בעיה:** [scripts/](scripts/) מכיל קבצים חד-פעמיים (`analyze_batch3.py`, `analyze_batch4.py`, `analyze_new7.py`, `compare_v18_v20.py`) שמסבכים את ה-repo.
- **פתרון:**
  - להעביר ל-`scripts/archive/` או למחוק.
  - להשאיר רק כלים גנריים (`compare_batch.py`, `score_batch.py`).
  - להוסיף `scripts/README.md` שמסביר מה כל סקריפט עושה.
- **מאמץ:** מינימלי.

### 6. הגנה על PII בנתוני לקוחות
- **בעיה:** [data/customer_mappings.json](data/customer_mappings.json) ו-[draws/](draws/) עשויים להכיל מידע רגיש של לקוחות.
- **פתרון:**
  - לוודא ב-`.gitignore` ש-`draws/`, `output/`, `REPORTS/` מוחרגים.
  - לבדוק עם `git ls-files draws/` שאין קבצים שכבר commited.
  - אם יש — `git rm --cached -r draws/ output/ REPORTS/` (אחרי אישור).
  - להוסיף `data/customer_mappings.example.json` ו-להחריג את האמיתי.
- **מאמץ:** נמוך.

### 7. שיפור Logging מובנה
- **בעיה:** רוב המודולים משתמשים ב-`logger = logging.getLogger(__name__)` אבל אין הגדרה מרכזית של פורמט/יעד.
- **פתרון:**
  - ליצור `core/logging_config.py` עם `setup_logging(level, log_file)`.
  - לקרוא ל-`setup_logging()` ב-`app.py` ו-`ui_assembly.py`.
  - להוסיף `RotatingFileHandler` ל-`output/app.log` (10MB × 3 קבצים).
- **מדד:** קל לעקוב אחרי runs דרך קובץ אחד.
- **מאמץ:** נמוך.

### 8. Type Hints מלאים + `mypy`
- **בעיה:** כיסוי type hints חלקי. אין בדיקות סטטיות.
- **פתרון:**
  - להוסיף `mypy>=1.0` ל-`requirements.txt`.
  - ליצור `mypy.ini` עם `strict_optional = True`.
  - להריץ `mypy core/` ולסגור hints חסרים בהדרגה.
  - להוסיף ל-CI workflow.
- **מאמץ:** בינוני (יום עבודה ראשוני).

### 9. CI Workflow מלא
- **בעיה:** ב-[README.md](README.md) יש badge ל-GitHub Actions, אבל לא ברור שה-workflow מכסה את כל מה שצריך.
- **פתרון:** `.github/workflows/ci.yml` שמריץ:
  - `pytest tests/ --cov=core --cov-fail-under=75`
  - `mypy core/`
  - `ruff check .` (linting מהיר)
  - `pip-audit` (CVEs בתלויות)
  על Python 3.11 + 3.13.
- **מאמץ:** בינוני.

---

## 🟢 עדיפות נמוכה (Polish)

### 10. ניהול גרסאות פרומפטים
- **בעיה:** [prompts/](prompts/) הוא קבצי טקסט גולמיים — אין מנגנון לעקוב אחרי שינויים בפרומפט מול תוצאות.
- **פתרון:**
  - להוסיף שורת `# version: X` בכותרת כל פרומפט.
  - לכלול את הגרסה ב-cache key של [core/drawing_cache.py](core/drawing_cache.py) (אם לא נכלל כבר).
  - לתעד שינויים ב-[CHANGELOG.md](CHANGELOG.md) תחת sub-section "Prompts".
- **מאמץ:** מינימלי.

### 11. Dashboard לניתוח עלויות
- **בעיה:** [output/costs.jsonl](output/costs.jsonl) נכתב יפה אבל אין כלי קריאה.
- **פתרון:** דף Streamlit נוסף `pages/cost_dashboard.py`:
  - סך עלות לפי יום/שבוע
  - פילוח לפי stage/model
  - cache hit rate
- **מאמץ:** בינוני.

### 12. Async / מקבילות לעיבוד מכלולים
- **בעיה:** [ui_assembly.py](ui_assembly.py) מעבד שרטוטים **סדרתית** — איטי כשיש 5+ קבצים.
- **פתרון:** `concurrent.futures.ThreadPoolExecutor` לקריאות Vision של שרטוטים שונים (Azure תומך ב-rate limit סביר).
- **מדד:** עיבוד 5 שרטוטים ב-≤40% מהזמן הסדרתי.
- **מאמץ:** בינוני.

### 13. Pre-commit hooks
- **בעיה:** אין אכיפת סטנדרטים אוטומטית לפני commit.
- **פתרון:** `.pre-commit-config.yaml` עם:
  - `ruff format` + `ruff check --fix`
  - `pytest -x tests/test_pn_utils.py` (smoke מהיר)
  - `check-merge-conflict`, `end-of-file-fixer`
- **מאמץ:** מינימלי.

### 14. תיעוד API פנימי
- **בעיה:** אין `docs/` עם sphinx/mkdocs — קשה למפתח חדש להבין מה כל פונקציה ציבורית עושה.
- **פתרון:** `mkdocs` + `mkdocstrings` שיוצר אתר מ-docstrings קיימים.
- **מאמץ:** בינוני.

### 15. הסרת imports לא בשימוש + Dead code
- **בעיה:** ייתכן שיש imports יתומים אחרי הריפקטור של `assembly/`.
- **פתרון:** `ruff check --select F401,F841 .` ולתקן.
- **מאמץ:** מינימלי.

---

## 📊 מטריצת עדיפות / מאמץ

| מאמץ ↓ / השפעה → | נמוכה | בינונית | גבוהה |
|---|---|---|---|
| **נמוך** | #15 | #4, #5, #6, #10, #13 | #3 |
| **בינוני** | #14 | #7, #8, #9, #11, #12 | #2 |
| **גבוה** | — | — | #1 |

**Quick wins** (השפעה גבוהה / מאמץ נמוך): **#3, #4, #6**
**Big bets** (שווים השקעה): **#1, #2**

---

## 🗓️ הצעת Roadmap

### Sprint 1 (שבוע)
- [ ] #4 Pinning תלויות
- [ ] #3 Input validation ל-PDF
- [ ] #6 הגנה על PII
- [ ] #5 ניקוי `scripts/`

### Sprint 2 (שבוע)
- [ ] #2 פיצול `extractor.py`
- [ ] #7 Logging מרכזי
- [ ] #10 גרסאות פרומפטים

### Sprint 3 (שבועיים)
- [ ] #1 בדיקות ל-pipeline (75% coverage)
- [ ] #9 CI workflow מלא
- [ ] #8 Type hints + mypy

### Backlog
- [ ] #11 Cost dashboard
- [ ] #12 Async assemblies
- [ ] #13 Pre-commit
- [ ] #14 mkdocs

---

## ✅ הגדרת "סיים" לציון 95+

- כיסוי בדיקות `pytest --cov=core` ≥ **75%**
- `mypy core/` עובר ללא שגיאות
- CI ירוק ב-Python 3.11 + 3.13
- אין `>=` ב-`requirements.lock.txt`
- אין PII ב-git history
- כל קובץ ב-`core/` < 250 שורות
