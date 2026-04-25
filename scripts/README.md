# scripts/

כלי עזר להרצה ידנית — *לא* חלק מה-pipeline הראשי ולא נטענים על ידי האפליקציה.

הרצה: `python scripts/<name>.py` משורש הפרויקט (ה-venv צריך להיות פעיל).

## כלים גנריים פעילים

| כלי | מה הוא עושה | מתי להשתמש |
|---|---|---|
| **[compare_batch.py](compare_batch.py)** | משווה תוצאות AI extraction מול PDF native text + Tesseract OCR לכל ה-cache files. משמש כ-ground truth (אין תשובות מאומתות ידנית). | אחרי batch של ניתוחים — לראות אילו שדות "קופצים" מהקריאה האמיתית של ה-PDF. |
| **[find_hallucinated_standards.py](find_hallucinated_standards.py)** | סורק את כל ה-cache + פלטי `output/*.json`, מריץ `validate_standards()`, ומסכם תקנים חשודים ב-CSV. | תקופתית — לזהות הזיות שחוזרות ולהוסיף ל-whitelist. |
| **[score_batch.py](score_batch.py)** | נותן ציון איכות 0-100 לכל שרטוט מ-cache (פילוח: זהות / חומר / תהליכים / וכו'). הגרסה הנוכחית מסננת ל-`v24` — שנה את הקבוע אם תרצה גרסה אחרת. | להעריך איכות אחרי שינוי prompt/validator. |

## ארכיון

[archive/](archive/) מכיל סקריפטים חד-פעמיים שניתחו batches ספציפיים בעבר:

- `analyze_batch3.py` — Batch 3 (`draws/new3/`) על v21
- `analyze_batch4.py` — Batch 4 (`draws/NEW4/`) על v23
- `analyze_new7.py` — Batch 7 (`draws/new7/`) על v24
- `compare_v18_v20.py` — השוואת v18→v20 על `draws/new/`

הם נשמרים כדי שאפשר יהיה להריץ אותם מחדש על ה-batches המקוריים, אבל לא כדאי לבסס עליהם תהליך חדש — להעתיק לקובץ חדש או להכליל לכלי גנרי.
