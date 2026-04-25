# Demo Pack — AIDrawAnalyser

חבילת הדגמה לקונה פוטנציאלי. המטרה: להעביר את הערך תוך 5 דקות.

## ⭐ Interactive HTML Demo (מוכן לשימוש)

[`interactive_demo.html`](interactive_demo.html) — קובץ HTML עצמאי שמדמה את כל זרימת
האפליקציה, **ללא צורך ב-Azure / Python / שרת**.

**שימוש:**
- כפילי קליק על הקובץ → נפתח בכל דפדפן
- שלחי לקונה במייל / Google Drive / לינק
- מארח אותו ב-GitHub Pages או כל static host

**שני מצבי עבודה — מתג בראש העמוד:**

### 🔍 שרטוט בודד (Single Mode)
- Empty state עם טקסט הסבר
- "טען דוגמה" → תוצאת ניתוח מלאה (פריט ACME-12345)
- Summary card עם pills, warning chips, badge של review status
- פירוט מלא: BOM / עיבוד שבבי / ציפויים / צביעות / NDT / תקנים / אריזה
- Warnings actionable עם "מה לבדוק"
- Review/Edit form אינטראקטיבי — עריכת שדות, סימון ✏️, אישור
- Export tabs (PDF/Excel/JSON) — חסומים עד אישור

### 🧩 מכלולים מרובים (Assembly Mode) ⭐
**זה החלק הכי חשוב למכירה לקונים תעשייתיים — מה שמייחד את המוצר.**

- "טען מכלול לדוגמה" → 4 שרטוטים (Camera Mount System):
  - 1 assembly: ACME-MOUNT-001
  - 3 parts: AC-12345 (bracket upper), AC-12346 (plate lower), AC-12347 (camera bracket)
- Stats overview: 4 קבצים · 5 פריטי BOM · 2 Missing Children · עלות
- אזהרת תיקון P/N אוטומטי מ-BOM cross-reference
- רשימת קבצים קליקבילית + navigator (◀️ ▶️) + selectbox
- Per-drawing summary card + פירוט מלא לכל שרטוט
- **🔗 ניתוח קשרי אבא/בן** (הכפתור הגדול):
  - סיכום בעברית של המכלול
  - **עץ מוצר ויזואלי** עם הורה + ילדים, סטטוס "✓ הועלה" / "✗ חסר", כמויות
  - **Missing Children** — 2 ברגי M5x20 + 2 דיסקיות נעילה (אומדנים סטנדרטיים)
  - אזהרות ולידציה ברמת המכלול (mixed materials, missing fastener drawings)
- 4 טאבי ייצוא: PDF מלא · PDF עץ · Excel מלא · Excel עץ

**יתרון מכירה:** דמו מהיר (5 שניות לטעון) בלי תקלות API, בלי המתנה של 40 שניות לכל שרטוט. הקונה רואה את היכולת המייחדת של ניתוח קשרים אוטומטי.

## מה עוד אפשר להוסיף לחבילה

```
demo_pack/
├── README.md                          ← זה המסמך
├── interactive_demo.html              ← ⭐ מוכן ✅
├── 01_drawings/                       ← קישור / קבצים מ-../sample_drawings/
├── 02_outputs/
│   ├── simple_part_extraction.json
│   ├── simple_part_report.xlsx
│   ├── complex_part_report.pdf
│   └── assembly_full_report.pdf
├── 03_screenshots/
│   ├── 01_upload_screen.png
│   ├── 02_extracted_results.png
│   ├── 03_validation_warnings.png
│   ├── 04_assembly_tree.png
│   └── 05_pdf_report.png
├── 04_one_pager.pdf                   ← דף אחד עסקי
└── 05_demo_video.mp4                  ← סרטון 2-3 דקות (אופציונלי)
```

## איך לבנות

### שלב 1 — צור sample_drawings (פעם אחת)
ראה [../sample_drawings/README.md](../sample_drawings/README.md) ליצירת 3 שרטוטים sanitized.

### שלב 2 — הרץ ניתוח על השרטוטים
```powershell
.\.venv\Scripts\Activate.ps1
streamlit run app.py
# העלה כל אחד מ-sample_drawings/
# שמור JSON + Excel + PDF ל-demo_pack/02_outputs/
```

### שלב 3 — צילומי מסך
- צלם את כל המסכים החשובים: העלאה, תוצאות, אזהרות, עץ מכלול, דוח.
- רזולוציה: 1920x1080 לפחות.
- שמור ב-`03_screenshots/`.

### שלב 4 — One-pager
מסמך עסקי בן עמוד אחד עם:
- מה האפליקציה עושה (משפט אחד).
- 3 נקודות חוזק עיקריות.
- לפני/אחרי — זמן הנדסה ידני vs. עם הכלי.
- מודלי תמחור ראשוניים.
- צ'אט / אימייל ליצירת קשר.

### שלב 5 — סרטון (אופציונלי)
2-3 דקות עם:
- 0:00-0:20 — מהי הבעיה (שרטוט מורכב, הנדסת ייצור ידנית).
- 0:20-1:30 — הדגמת העלאה + ניתוח חי.
- 1:30-2:30 — הצגת הפלט (Excel + PDF).
- 2:30-3:00 — call to action.

כלים: OBS Studio, Loom, Camtasia.

## שימוש

חבילה זו לעולם לא צריכה להישלח ב-email בנפח מלא — להעלות ל-Google Drive / OneDrive
ולשלוח לינק. **אסור** להעלות ל-public בלי NDA חתום.

## מה לא לכלול

- ❌ קבצים מ-`draws/`, `output/`, `REPORTS/` (מכילים IP אמיתי).
- ❌ צילומי מסך עם שמות לקוחות גלויים.
- ❌ דוחות עם מידע פנימי / עלויות API שלך.

## .gitkeep

הקובץ מאפשר את התיקייה להיכלל ב-git גם ריקה. הוסיפי לכאן רק תוכן sanitized.
