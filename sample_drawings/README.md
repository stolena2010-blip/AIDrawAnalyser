# sample_drawings/

תיקייה זו מיועדת לקבצי **דוגמה ניטרליים** (sanitized) להדגמת AIDrawAnalyser
לקונים פוטנציאליים, ללא חשיפת IP של לקוחות אמיתיים.

## מה צריך להיות כאן

- **3 שרטוטים מייצגים:**
  1. `simple_part.pdf` — שרטוט פשוט של פריט בודד (P/N + revision + material).
  2. `complex_part.pdf` — שרטוט עם תהליכי ייצור מרובים (machining + coating + painting + standards).
  3. `assembly_overview.pdf` או `assembly_overview.png` — תרשים מכלול עם BOM.

- **מאפיינים נדרשים:**
  - אין שמות לקוחות אמיתיים (RAFAEL/Elbit/IAI/RADA וכו').
  - אין קודי CAGE אמיתיים — להחליף ל-`ACME-001` או דומה.
  - אין מספרי פרויקט מסווגים.
  - אין יצירת IP של אף לקוח.

## איך לסניטיזה שרטוט קיים

אופציה א' — בעריכת PDF (Adobe Acrobat / Foxit):
1. פתחי את השרטוט המקורי.
2. השתמשי ב-Redact (Tools → Redact) על:
   - שם לקוח / לוגו
   - קוד CAGE
   - מספר פרויקט
   - שם בעלים בכותרת
3. שמרי כ-`<simple|complex|assembly>_part.pdf`.

אופציה ב' — לבנות מאפס:
- ב-AutoCAD/SolidWorks — צרי שרטוט גנרי של פריט פשוט (מסבך, plate, bracket).
- ייצאי ל-PDF.
- שמירה כאן.

## מה לא לעשות

- ❌ לא להעלות שרטוטים מ-`draws/` או `REPORTS/` (אלה מכילים IP של לקוחות).
- ❌ לא להעלות שרטוטים שקיבלת תחת NDA.
- ❌ לא להעלות שרטוטים עם classification (סודי / שמור).

## .gitkeep

הקובץ מאפשר את התיקייה להיכלל ב-git גם אם ריקה. אחרי שמוסיפים את הדוגמאות
האמיתיות — השאירי את הקובץ.
