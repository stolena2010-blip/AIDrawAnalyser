# Deployment Guide — AIDrawAnalyser

> מדריך התקנה מלא: ממכשיר נקי לאפליקציה רצה.
>
> תאריך עדכון: 2026-04-25

---

## 1. דרישות מערכת

### 1.1 חומרה (מינימום)
- 8GB RAM (16GB מומלץ — pypdfium2 ו-pillow אגרסיביים בזיכרון על שרטוטים גדולים)
- 5GB מקום פנוי (לא כולל קבצי input/output)
- אינטרנט יוצא ל-Azure OpenAI

### 1.2 מערכת הפעלה
- **Windows 10/11** — נבדק היטב, פלטפורמת הפיתוח הראשית
- **Linux (Ubuntu 22.04+)** — CI רץ ב-Ubuntu עם 405 בדיקות passing. Streamlit עובד אבל לא נבדק production.
- **macOS** — אמור לעבוד, לא נבדק רשמית

### 1.3 תוכנה
- **Python 3.10 או חדש יותר** (מומלץ 3.11 או 3.13 — מאומתים ב-CI)
- **Tesseract OCR** (אופציונלי — ל-fallback של חילוץ טקסט)
- **גישה ל-Azure OpenAI** עם deployment של `gpt-4o` (חובה) ו/או `gpt-5.4` (אופציונלי)

---

## 2. התקנה — Windows (מומלץ)

### 2.1 שלבים

```powershell
# 1. שכפול / חילוץ קוד
cd C:\
git clone <repo-url> AIDrawAnalyser
cd AIDrawAnalyser

# 2. סביבה וירטואלית
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. תלויות
pip install -r requirements.txt
# או: pip install -r requirements.lock.txt   (ראה סעיף 3)

# 4. משתני סביבה
Copy-Item .env.example .env
notepad .env   # מלא את המפתחות

# 5. (אופציונלי) Tesseract OCR
# הורידי מ: https://github.com/UB-Mannheim/tesseract/wiki
# התקיני, ואז הוסיפי ל-.env:
#   TESSERACT_PATH=C:\Program Files\Tesseract-OCR
# חובה לבחור גם חבילת שפה Hebrew (heb.traineddata).

# 6. הרצה
streamlit run app.py
# או: .\Run_Web.bat
```

הדפדפן ייפתח ב-http://localhost:8501.

---

## 3. נעילת תלויות — `requirements.lock.txt`

`requirements.txt` משתמש ב-`>=` בלבד. לרפרודוקציה מובטחת ב-production:

```powershell
# מ-venv שעובד היטב היום:
pip freeze > requirements.lock.txt
```

ב-production התקיני עם:
```powershell
pip install --no-deps -r requirements.lock.txt
```

⚠️ **כרגע הקובץ לא קיים** — ראה [SALE_READINESS_RECOMMENDATIONS.md](SALE_READINESS_RECOMMENDATIONS.md).

---

## 4. התקנה — Linux

### 4.1 שלבים

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv tesseract-ocr tesseract-ocr-heb

git clone <repo-url> AIDrawAnalyser
cd AIDrawAnalyser

python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
nano .env   # ערוך והוסף מפתחות

streamlit run app.py
```

### 4.2 פתחי firewall

Streamlit ברירת מחדל = 8501. אם פותחת מחוץ ל-localhost:
```bash
sudo ufw allow 8501/tcp
```
**זהירות:** אין auth מובנה — ראה [SECURITY.md](SECURITY.md).

---

## 5. התקנה — Docker (לא קיים, צריך לבנות)

כרגע אין `Dockerfile`. אם רוצים פריסת קונטיינר, בסיס מוצע:

```dockerfile
FROM python:3.13-slim

RUN apt-get update && apt-get install -y \
    tesseract-ocr tesseract-ocr-heb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

---

## 6. הגדרת Azure OpenAI

### 6.1 דרישות
- Azure subscription פעיל
- Azure OpenAI resource (regional — בחרי אזור עם vision support)
- Deployment של `gpt-4o` (חובה לחילוץ Vision)
- (אופציונלי) Deployment של `gpt-5.4` או `o1` (Reasoning) — fallback

### 6.2 משתני `.env`

```env
ACTIVE_MODEL=gpt-4o-vision

# Vision (gpt-4o)
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=<your-key>
AZURE_OPENAI_API_VERSION=2024-08-01-preview
AZURE_OPENAI_DEPLOYMENT=gpt-4o

# Reasoning (gpt-5.4) — אופציונלי
MODEL_GPT_5_4_ENDPOINT=https://your-resource.openai.azure.com/
MODEL_GPT_5_4_API_KEY=<your-key>
MODEL_GPT_5_4_API_VERSION=2024-12-11-preview
MODEL_GPT_5_4_DEPLOYMENT=gpt-5.4
MODEL_GPT_5_4_IS_REASONING=true

# תוסף Azure על מחירי OpenAI הרשמיים (1.20 = +20%)
AZURE_SURCHARGE=1.20
```

### 6.3 בדיקה מהירה

```bash
streamlit run app.py
# העלי קובץ PDF קטן — ניתוח אמור להתחיל
# אם רואה "❌ AZURE_OPENAI_API_KEY לא מוגדר" — בדקי .env
```

---

## 7. הגדרת Tesseract (OCR fallback)

### Windows
1. הורידי installer מ-https://github.com/UB-Mannheim/tesseract/wiki
2. במהלך התקנה — **חובה** לסמן "Hebrew" בדיאלוג Additional language data.
3. הוסיפי ל-`.env`:
   ```env
   TESSERACT_PATH=C:\Program Files\Tesseract-OCR
   ```

### Linux
```bash
sudo apt install -y tesseract-ocr tesseract-ocr-heb
```
(ה-`PATH` כבר נכון ב-distros רגילים)

### בדיקה
```python
from core.ocr_fallback import is_ocr_available
print(is_ocr_available())  # True == עובד
```

---

## 8. הגדרת `Masters.xlsx`

הקובץ הזה הוא **business-specific** — מכיל מאגר ציפויים פנימיים.

- בקובץ הקיים: ~1239 ציפויים מותאמים לבעלים הנוכחית.
- קונה צריך:
  - להחליף בקובץ שלו, **או**
  - לכבות את `master_matcher` מה-UI (לא בשימוש במצב Assembly הסטנדרטי).

הגדרת path אופציונלית ב-`.env`:
```env
MASTERS_XLSX_PATH=C:\Data\Masters.xlsx
```

ברירת מחדל: `<root>/Masters.xlsx`.

---

## 9. בדיקת התקנה תקינה

```bash
# 1. בדיקות יחידה
pytest tests/ -v
# צפוי: 405 passed

# 2. import sanity
python -c "import core.assembly; import storage.save_handler; print('OK')"

# 3. UI smoke test
streamlit run app.py
# פתחי דפדפן ב-localhost:8501
# העלי PDF דמו (ראה sample_drawings/)
```

---

## 10. בעיות נפוצות

| בעיה | סיבה | פתרון |
|---|---|---|
| `❌ AZURE_OPENAI_API_KEY לא מוגדר` | `.env` ריק או חסר | מלאי את `.env` לפי `.env.example` |
| `❌ pdf_to_images` נכשל | pypdfium2 לא נטען | `pip install --upgrade pypdfium2` |
| `OCR לא זמין` | Tesseract לא בנתיב | בדקי `TESSERACT_PATH` ב-`.env` |
| `Hebrew gibberish ב-HTML report` | בעיית encoding נדירה | בדקי שהדפדפן פותח עם UTF-8 (ברירת מחדל). הקבצים כבר מציינים `<meta charset="utf-8">` |
| `Drawing Cache מחזיר תוצאה ישנה` | פרומפט/validator עודכן בלי bump של `CACHE_VERSION` | bump `CACHE_VERSION` ב-`core/drawing_cache.py` |
| Streamlit לא נפתח | port 8501 תפוס | `streamlit run app.py --server.port 8502` |

---

## 11. עדכון גרסה

```bash
# 1. גיבוי
cp -r output/ output.bak/
cp .env .env.bak

# 2. משוך עדכונים
git pull origin main

# 3. עדכן תלויות
pip install -r requirements.txt --upgrade

# 4. בדוק שעובר
pytest tests/

# 5. הרץ
streamlit run app.py
```

---

## 12. דברים שלא נתמכים out-of-the-box

- **Multi-tenant** — אין auth, אין session isolation
- **HA / Failover** — single process בלבד
- **HTTPS** — חייב reverse proxy (nginx/Caddy)
- **Backup אוטומטי של `output/`** — חייב cron / Task Scheduler חיצוני
- **Audit log פורמלי** — קיים `output/costs.jsonl` בלבד (לא user/action)

לשירותי enterprise הללו — ראה [SALE_READINESS_RECOMMENDATIONS.md](SALE_READINESS_RECOMMENDATIONS.md)
לפי שיפורים מומלצים.
