# License Review — AIDrawAnalyser

> סקירת רישיונות של תלויות צד שלישי. מיועדת לעמידה ב-due diligence
> משפטית של קונה.
>
> תאריך עדכון: 2026-04-25

---

## 1. רישיון הפרויקט

⚠️ **כרגע אין קובץ `LICENSE` בריפו.** ללא הצהרת רישיון מפורשת:
- ברירת המחדל בארה"ב/אירופה: **All Rights Reserved** — אסור לקונה להשתמש ללא הסכם.
- צריך לבחור רישיון לפני מכירה. ראה סעיף 5 להמלצות.

---

## 2. תלויות ישירות (`requirements.txt`)

🎉 **כל התלויות עכשיו permissive (Apache 2.0 / MIT / BSD).** אין AGPL.

| חבילה | רישיון | תאימות לשימוש מסחרי | הערות |
|---|---|---|---|
| streamlit | Apache 2.0 | ✅ כן | UI framework |
| openai | Apache 2.0 | ✅ כן | Azure SDK |
| python-dotenv | BSD 3-Clause | ✅ כן | env vars |
| **pypdfium2** | **Apache 2.0** | ✅ כן | PDF→Image (קלט) |
| Pillow | MIT-CMU (HPND) | ✅ כן | Image processing |
| pytesseract | Apache 2.0 | ✅ כן | Tesseract wrapper |
| pandas | BSD 3-Clause | ✅ כן | DataFrames |
| openpyxl | MIT | ✅ כן | Excel I/O |
| pytest | MIT | ✅ כן | בדיקות בלבד |
| ~~pymupdf (fitz)~~ | ~~AGPL 3.0~~ | ✅ **הוסר** | דוחות עכשיו HTML — ראה סעיף 3 |

---

## 3. AGPL Eliminated — HTML Reports

### הפתרון

הדוחות הוחלפו מ-PDF (שדרש PyMuPDF AGPL) ל-**HTML עצמאי**. ה-HTML נפתח בכל
דפדפן, וכשהקונה רוצה PDF הוא לוחץ Ctrl+P → "Save as PDF" — הדפדפן עושה את
ההמרה בעצמו, בחינם, ללא שום ספריית צד שלישי.

### למה זה יותר טוב מ-PDF

| יתרון | למה |
|---|---|
| **0 AGPL** | אין שום ספריית PDF — רק string templating |
| **0 תלויות חדשות** | רק Python stdlib — שום install pain |
| **RTL עברית מושלם** | דפדפנים תומכים native, ללא font embedding issues |
| **PDF זמין** | Ctrl+P → Save as PDF (כל הדפדפנים תומכים) |
| **Searchable** | טקסט HTML מותאם לחיפוש, מובייל, קורא מסך |
| **קבצים קטנים יותר** | ~50% מגודל ה-PDF |
| **קל לדבג** | אם משהו לא נראה טוב — פותחים ב-DevTools |

### מה השתנה בקוד

- `core/pdf_utils.py` — כבר השתמש ב-`pypdfium2` (Apache 2.0) — לא נגעתי
- `storage/pdf_report.py` — `import fitz` הוסר. `build_assembly_pdf` → `build_assembly_html`. `build_tree_pdf` → `build_tree_html`. הקבצים נשמרים כ-`.html` במקום `.pdf`.
- ה-HTML המיוצר כולל:
  - `@page { size: A4; margin: 1.5cm; }` להדפסה איכותית
  - `@media print` שמסתיר את כפתור ההדפסה
  - `page-break-before: always` בין סקציות
  - כפתור "🖨️ הדפסה / שמירה כ-PDF" בראש העמוד
- `requirements.txt` — `pymupdf` הוסר לחלוטין
- ה-UI הוחלף: tab של "📕 PDF מלא" עכשיו "📄 דוח HTML"
- Backwards-compat aliases: `build_assembly_pdf = build_assembly_html` (קוד ישן עדיין עובד, מחזיר HTML)

### מה הקונה רואה

לחיצה על "📄 צור דוח HTML מלא" → קובץ `.html` יורד → כפילי קליק → דפדפן פותח →
- אפשר לקרוא ישירות
- אפשר לחפש (Ctrl+F)
- אפשר לפתוח במובייל (responsive)
- אפשר לשמור כ-PDF (Ctrl+P → Save as PDF) — מקבלים PDF איכותי בחינם
- אפשר לשלוח כ-attachment במייל

### אלטרנטיבות שנבחנו ונדחו

| חלופה | רישיון | למה לא |
|---|---|---|
| WeasyPrint | BSD-3 ✅ | דורש GTK/Pango — install pain ב-Windows |
| xhtml2pdf | Apache 2.0 ✅ | RTL Hebrew render לא יציב |
| Playwright | Apache 2.0 ✅ | דורש Chromium ~100MB, overkill |
| ReportLab | BSD ✅ | אין HTML→PDF, צריך rewrite מלא |
| **HTML טהור (נבחר)** | **stdlib** ✅ | **אפס תלויות, איכות מושלמת בעזרת הדפדפן** |

---

## 4. תלויות מערכת (לא Python)

### Tesseract OCR
- **רישיון:** Apache 2.0
- **שימוש:** binary חיצוני (לא mעריך לקוד)
- **בעיות?** אין

### MuPDF
- מותקן כתלות של pymupdf (לא ישירות)
- אותם תנאי AGPL כמו pymupdf

---

## 5. רישיון מומלץ ל-AIDrawAnalyser

תלוי במודל המכירה:

### אופציה א' — Proprietary (מכירת IP / רישיון שנתי)
```text
Copyright (c) 2026 <שם בעלת הקוד>
All Rights Reserved.

Use of this software requires a written commercial license.
Contact: app_test@algat.co.il
```
**מתאים אם:** רוצה למכור רישיון שנתי / IP, לא רוצה לאפשר שימוש חופשי.

### אופציה ב' — Apache 2.0 (open source)
```text
Apache License 2.0
```
**מתאים אם:** רוצה אימוץ רחב, לא ממנפת את הקוד עצמו (ממנפת שירותים מסביבו).

### אופציה ג' — Dual License (Commercial + AGPL)
**מתאים אם:** רוצה לאפשר שימוש פתוח לחוקרים אבל לחייב חברות לרכוש רישיון.

---

## 6. תלויות פיתוח (לא דורשות בדיקה משפטית)

מותקנות רק ב-`requirements.txt` תחת `# Testing` ו-CI:
- `pytest` — MIT
- `ruff` — MIT (רק ב-CI)

לא מועברות ל-runtime / לקונה.

---

## 7. דברים לבדוק לפני העברה

- [ ] יצירת קובץ `LICENSE` בשורש הפרויקט.
- [ ] החלטה על PyMuPDF: להחליף או לרכוש רישיון מסחרי.
- [ ] חתימה על NDA עם קונה לפני שיתוף הקוד (אם proprietary).
- [ ] רישום מסמכי IP — מי הבעלים של הקוד? (אם נכתב במהלך עבודה אחרת — צריך waiver).
- [ ] בדיקת קוד צד שלישי שאולי הוטמע (snippets מ-Stack Overflow CC-BY-SA וכו').

---

## 8. קישורים

- AGPL 3.0: https://www.gnu.org/licenses/agpl-3.0.html
- PyMuPDF Commercial: https://artifex.com/licensing/commercial/
- pypdfium2: https://github.com/pypdfium2-team/pypdfium2 (Apache 2.0)
- בחירת רישיון: https://choosealicense.com/
