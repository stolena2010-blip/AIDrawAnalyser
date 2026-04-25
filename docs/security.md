# Security Policy — AIDrawAnalyser

> מסמך זה מתאר את עמדת האבטחה של AIDrawAnalyser: אילו נתונים נכנסים,
> איפה הם נשמרים, מה הם הסיכונים הידועים, ואיך לדווח על פגיעות.
>
> תאריך עדכון: 2026-04-25

---

## 1. סקירה

AIDrawAnalyser היא אפליקציית **single-tenant** המיועדת להפעלה מקומית (desktop / on-prem).
אין שירות ענן ציבורי, אין auth מובנה, אין mTLS. כל המשתמשים שיש להם גישה לתיקיית ההרצה
יכולים לראות הכל.

זוהי **החלטה מודעת**, לא דליפה — האפליקציה לא מיועדת ל-multi-tenant SaaS.

---

## 2. נתונים שנכנסים למערכת

| נתון | מקור | רגישות |
|---|---|---|
| קבצי PDF של שרטוטים | משתמש (העלאה) | **גבוהה** — לרוב IP של לקוחות |
| תמונות PNG/JPG/WEBP | משתמש (העלאה) | גבוהה (כמו PDF) |
| Masters.xlsx | בעלים של ההתקנה | בינונית — תלוי בתוכן |
| customer_mappings.json | בעלים של ההתקנה | בינונית — שמות לקוחות + CAGE |
| `.env` | מתקין | **קריטית** — מפתחות API של Azure |

### דרישות `.env`
- `AZURE_OPENAI_API_KEY` — מפתח Azure
- `MODEL_GPT_5_4_API_KEY` — מפתח שני (אם משתמש בשני deployments)
- מומלץ: הגנה filesystem (`chmod 600` / Windows ACL להגביל לעצמך בלבד)
- **לעולם לא** להעלות `.env` ל-Git (`.gitignore` כבר חוסם)

---

## 3. נתונים שיוצאים מהמערכת

### 3.1 ל-Azure OpenAI

עבור כל שרטוט נשלחים:
- **תמונות JPEG base64** של עמודי ה-PDF (DPI 300)
- **טקסט OCR** (אם Tesseract מותקן) כתוספת לפרומפט
- **פרומפטים** הכוללים את הטקסט הנקרא משם הקובץ

**Azure OpenAI אינו שומר את הנתונים** לאימון מודלים (במסגרת ה-Enterprise SLA).
אבל יש לוגים אבטחתיים של Azure שעלולים להישמר עד 30 יום. ראה את הסכם השירות שלך.

### 3.2 לדיסק המקומי

| נתיב | תוכן | נקה? |
|---|---|---|
| `output/<basename>_<timestamp>.json` | תוצאת ניתוח מלאה | כן — לרוב מכיל מידע מהשרטוט |
| `output/<basename>_<timestamp>.xlsx` | Excel רב-גיליוני | כן |
| `output/_assembly_*.{json,pdf,xlsx}` | תוצאות מצב מכלולים | כן |
| `output/.cache/<md5>.json` | Drawing Cache לפי MD5 | **כן — מכיל את כל החילוץ של שרטוטים קודמים** |
| `output/costs.jsonl` | לוג עלויות API | כן — מכיל שמות קבצים ועלויות |
| `output/_runtime_settings.json` | הגדרות runtime (לא secrets) | מותר להשאיר |

**לפי גרסה הנוכחית, אין rotation אוטומטי** של ה-output. בהתקנה לטווח ארוך
מומלץ scheduled cleanup (למשל מחיקה של פלטים ישנים מ-90 יום).

### 3.3 לדיסק (לא רצוי)

- `__pycache__/` — bytecode (לא מכיל שרטוטים)
- `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/` — לא רגיש
- `.coverage` — לא רגיש

---

## 4. בקרת גישה

| משאב | בקרה |
|---|---|
| Streamlit UI | אין auth מובנה — מאזין על `localhost:8501` |
| `.env` | filesystem ACL בלבד |
| `output/` | filesystem ACL בלבד |
| Azure API | מפתח (lifetime: עד שתחליפי) |

**המלצות לקונה שמתקין במחשב משותף:**
- להריץ תחת user dedicated עם הגבלות ACL.
- אם רוצים לחשוף ל-LAN — לעטוף ב-reverse proxy (nginx/Caddy) עם Basic Auth או OIDC.
- לא להציע את ה-port הציבורית — אין rate limit, אין input sanitization מעבר ל-PDF parser.

---

## 5. סיכונים ידועים

### 5.1 PDF malicious input
**הקלעות אפשריות:** PDFים שעלולים לחנוק זיכרון (גודל / מספר עמודים) או להיות בפורמט שגוי.

**סטטוס:** ✅ ממומש ב-`core/pdf_utils.py`:
- בדיקת magic bytes (`%PDF-`) לפני העברה ל-pypdfium2
- מגבלת גודל (`MAX_PDF_MB`, ברירת מחדל 50MB)
- מגבלת עמודים (`MAX_PDF_PAGES`, ברירת מחדל 20)
- ניתן לכוונן עם משתני סביבה

### 5.2 Prompt Injection
**סיכון:** טקסט ב-PDF (NOTES) עלול להכיל הוראות שמטעות את ה-AI לתת מידע
מוטעה (למשל "ignore all previous instructions").

**סטטוס:** הפרומפטים שלנו ספציפיים מאוד למטלת חילוץ ואוסרים על "ניחושים",
מה שמקטין סיכון. עדיין — לא ממומש סינון אקטיבי.

### 5.3 Customer Data Leakage
**סיכון:** `customer_mappings.json` tracked בגיט. כל מי שיש לו גישה ל-repo רואה
את שמות הלקוחות.

**סטטוס:** ידוע, ראה [DATA_HANDLING.md](DATA_HANDLING.md) להמלצת sanitization.

### 5.4 Cache leakage between users
**סיכון:** אם שני משתמשים שונים מנתחים את אותו PDF, ה-cache (לפי MD5) יחזיר
תוצאה ששמורה. במצב single-user זו תכונה. במצב multi-user — דליפה.

**סטטוס:** מודע. ה-cache לא מיועד למצב multi-user.

### 5.5 No HTTPS by default
**סיכון:** Streamlit מאזין HTTP בלבד.

**סטטוס:** מתאים ל-localhost. לחשיפה רחבה — לעטוף ב-reverse proxy עם TLS.

---

## 6. דיווח על פגיעות

נמצאה פגיעה? אנא שלחי מייל ל-app_test@algat.co.il עם:
- תיאור הפגיעה
- שלבים לשחזור
- השפעה משוערת
- (אופציונלי) הצעה לתיקון

נכון להיום אין program פורמלי של bug bounty.

---

## 7. רשימת תיקונים מומלצים לפני production

| # | תיקון | עדיפות | מאמץ |
|---|---|---|---|
| 1 | בדיקת magic bytes + size limit ב-`pdf_utils.py` | גבוהה | שעה |
| 2 | rotation אוטומטי של `output/` (למשל מחיקה > 90 יום) | בינונית | חצי יום |
| 3 | פיצול `customer_mappings.json` ל-example + real | גבוהה | שעה |
| 4 | rate limiting אם נחשף מעבר ל-localhost | תלוי בפריסה | יום |
| 5 | structured audit log (run_id + user + timestamp + model) | בינונית | יום-יומיים |
| 6 | החלפת מפתחות API → Managed Identity ב-Azure | בינונית | יום |
