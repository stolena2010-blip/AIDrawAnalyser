# Data Handling — AIDrawAnalyser

> מסמך זה מתאר בדיוק מה נשלח לכל מערכת חיצונית, מה נשמר מקומית, ומה ניתן
> למחוק. מיועד למחלקות אבטחה / משפטית של קונה לפני אישור פריסה.
>
> תאריך עדכון: 2026-04-25

---

## 1. תרשים זרימת נתונים

```
┌─────────────────────┐
│ User uploads PDF    │
└──────────┬──────────┘
           │
           ▼
┌──────────────────────────┐
│ MD5 hash → cache lookup  │
└──────┬───────────────┬───┘
       │ cache hit     │ cache miss
       ▼               ▼
┌──────────┐   ┌──────────────────────────┐
│ Return   │   │ PDF → JPEG (DPI 300)     │
│ cached   │   │ JPEG → base64            │
└──────────┘   └─────────────┬────────────┘
                             │
                             ▼
                   ┌─────────────────────┐
                   │ Tesseract OCR       │  (only if installed)
                   │ → extracted text    │
                   └─────────────┬───────┘
                                 │
                                 ▼
                   ┌──────────────────────────┐
                   │ Azure OpenAI API call    │
                   │ - images (base64)        │
                   │ - prompt + OCR text      │
                   └─────────────┬────────────┘
                                 │
                                 ▼
                   ┌──────────────────────────┐
                   │ Result JSON              │
                   │ - cached locally         │
                   │ - displayed in UI        │
                   │ - exported (JSON/Excel)  │
                   └──────────────────────────┘
```

---

## 2. נתונים שנשלחים ל-Azure OpenAI

### 2.1 לכל קריאת Vision

| שדה | תוכן | גודל טיפוסי |
|---|---|---|
| `messages[0].content[*].image_url` | תמונת JPEG בתוך base64 (data URI) | 200KB-2MB לעמוד |
| `messages[0].content[*].text` | פרומפט + טקסט OCR | 5-20KB |
| `messages[0].content[*].text` | שם הקובץ הגולמי | <100B |

**שם הקובץ נכנס לתוך הפרומפט** של Stage 1 כדי לעזור לחילוץ P/N. אם שם הקובץ
מכיל מידע רגיש (`B2BDraw_<part_num>_<rev>.pdf`) — זה הולך ל-Azure.

### 2.2 איך לדעת בוודאות

הפרומפטים נמצאים תחת `prompts/assembly/`:
- `stage_1.txt` — Vision prompt לחילוץ basic info
- `stage_2.txt` — Vision prompt לחילוץ processes
- `overview_image.txt` — לתמונת מכלול
- `relationships_template.txt` — לניתוח קשרים

ניתן לקרוא אותם כטקסט רגיל, אין פרומפט מוסתר.

### 2.3 מה Azure OpenAI עושה עם הנתונים

לפי Microsoft Enterprise terms:
- **לא משתמשים בנתונים שלכם לאימון מודלים** של OpenAI / Microsoft.
- לוגים שמורים עד 30 יום ל-abuse monitoring.
- ניתן לבקש **opt-out** מ-abuse monitoring (Limited Access).

ראה: https://learn.microsoft.com/en-us/legal/cognitive-services/openai/data-privacy

---

## 3. נתונים שנשמרים מקומית

### 3.1 תיקיות שמכילות נתוני שרטוטים

| נתיב | תוכן | הגנה ב-`.gitignore` |
|---|---|---|
| `draws/` | קבצי PDF גולמיים שהמשתמש העלה | ✅ |
| `output/*.json` | תוצאות ניתוח | ✅ |
| `output/*.xlsx` | דוחות Excel | ✅ |
| `output/*.pdf` | דוחות PDF | ✅ |
| `output/.cache/*.json` | Drawing Cache לפי MD5 | ✅ |
| `output/costs.jsonl` | לוג עלויות (כולל שמות קבצים) | ✅ |
| `REPORTS/` | פלטים ידניים | ✅ |

### 3.2 תיקיות שמכילות נתוני קונפיגורציה

| נתיב | תוכן | tracked? |
|---|---|---|
| `.env` | מפתחות Azure | **לא** (`.gitignore`) |
| `.env.example` | תבנית בלי ערכים אמיתיים | כן |
| `data/customer_mappings.json` | מיפוי CAGE→customer | **כן** ⚠️ |
| `Masters.xlsx` | מאגר ציפויים | כן |
| `prompts/` | פרומפטים | כן |

⚠️ **`data/customer_mappings.json` הוא בעיה** — ראה סעיף 5.

---

## 4. Drawing Cache

### 4.1 איך זה עובד

לכל שרטוט מחושב MD5 על תוכן הקובץ הבינארי. אם MD5 + model + pipeline version
זהים לזיהוי קודם — מחזירים את התוצאה השמורה ב-`output/.cache/<md5>.json` ללא קריאה
ל-Azure.

### 4.2 השלכות פרטיות

- ה-cache **לא מכיל את ה-PDF עצמו** — רק את תוצאת החילוץ (JSON).
- תוצאת חילוץ עלולה להכיל: P/N, customer name, BOM items, notes, material.
- **כל מי שיש לו גישה ל-`output/.cache/`** רואה את היסטוריית כל הניתוחים.

### 4.3 איך לכבות

```env
DRAWING_CACHE_DISABLED=true
```

או למחוק ידנית:

```bash
rm -rf output/.cache/
```

---

## 5. customer_mappings.json — בעיה ידועה

### הבעיה

הקובץ `data/customer_mappings.json` tracked בגיט ומכיל:
- שמות לקוחות אמיתיים: RAFAEL Advanced Defense Systems, Elbit Systems Elop,
  Israel Aerospace Industries (IAI), KRETOS General Microwave, BIRD Aerosystems,
  RADA, Mechanico-Shaftech, Airpart, ETTEM Engineering ועוד.
- קודי CAGE אמיתיים (1931, 1933A, 1410A וכו').
- קידומות P/N שמזהות לקוחות.

### למה זה משמש

הקובץ נטען ע"י `core/_customer_data.py` ומשמש את:
- `core/text_utils.py` — נירמול שמות לקוחות
- `core/validators.py` — וידוא שתקנים פנימיים תואמים ללקוח
- `core/assembly/post_process.py` — הסקת לקוח מקידומת P/N

### הסיכון

- קונה שמקבל את ה-repo רואה את רשימת הלקוחות שלך.
- אם הקונה מתחרה — מקבל מודיעין עסקי.
- חשיפה משפטית — לקוחות בתחום הביטחון לרוב מצריכים סודיות מסחרית.

### תיקון מומלץ (לפני העברה)

1. ליצור `data/customer_mappings.example.json` עם דוגמאות גנריות (`ACME Corp` וכו').
2. לעדכן `core/_customer_data.py` שיעדיף `customer_mappings.json` אם קיים, אחרת
   נופל ל-`.example.json`.
3. להוסיף `data/customer_mappings.json` ל-`.gitignore`.
4. למחוק את `customer_mappings.json` מהיסטוריית הגיט בעזרת `git filter-repo`
   (אם זה אכפת — פעולה destructive שמשנה היסטוריה).
5. לעדכן ב-README שהקונה צריך ליצור `customer_mappings.json` לפי הפורמט בexample.

---

## 6. נתונים שניתן/חייב למחוק לפני העברה

### חובה למחוק

```bash
# קבצי PDF של שרטוטים אמיתיים
rm -rf draws/
rm -rf REPORTS/

# פלטים שמכילים מידע רגיש
rm -rf output/*.json output/*.xlsx output/*.pdf output/*.csv

# Drawing Cache — מכיל היסטוריה של כל הניתוחים
rm -rf output/.cache/

# לוג עלויות (מכיל שמות קבצים)
rm -f output/costs.jsonl

# מפתחות Azure
rm -f .env

# Masters אם מכיל מידע פרטי
# (בדקי: האם Masters.xlsx מכיל ציפויים פנימיים שאינם פומביים?)
# rm -f Masters.xlsx

# customer_mappings אם לא בוצע sanitization
# rm -f data/customer_mappings.json
```

### מומלץ לבדוק

```bash
git ls-files | xargs -I{} grep -l "RAFAEL\|Elbit\|IAI\|RADA\|Mechanico" {} 2>/dev/null
```

(אם יש hits מחוץ ל-`customer_mappings.json` ו-`docs/` — לסנן ידנית)

---

## 7. צ'קליסט לפני העברה

- [ ] `.env` הוסר ולא tracked.
- [ ] `draws/` ריק.
- [ ] `output/` ריק (כולל `.cache/`).
- [ ] `REPORTS/` ריק.
- [ ] `customer_mappings.json` סוניטיזה או הוסר.
- [ ] `Masters.xlsx` נבדק ידנית (האם מכיל מידע פרטי?).
- [ ] `git log --all --oneline -- draws/ output/ REPORTS/` ריק.
- [ ] `git log --all --oneline -- .env` ריק.
- [ ] בדיקה ידנית של `git log -p -- data/customer_mappings.json` להבין מה היסטוריית הקובץ.

---

## 8. תאימות רגולטורית

האפליקציה **לא מבצעת**:
- מסירת מידע אישי לפי GDPR (אין PII של אנשים פרטיים).
- שמירה לפי SOX / HIPAA (לא רלוונטי).

האפליקציה **כן עוברת מידע** שעלול להיות תחת:
- ITAR / EAR (אם השרטוטים תחת בקרת ייצוא של ארה"ב).
- חוק שטחי הביטחון הישראלי (אם הלקוח חיצוני וזה IP בטחוני).

**אחריות הקונה לבדוק** אם מותר לשלוח את השרטוטים שלו ל-Azure OpenAI לפני
פריסה ב-production.
