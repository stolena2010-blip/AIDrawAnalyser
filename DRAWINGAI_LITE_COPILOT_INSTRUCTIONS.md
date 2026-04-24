# AIDrawAnalyser — הנחיות בנייה ל-GitHub Copilot

> **מטרה:** לבנות אפליקציית Streamlit עצמאית שמאפשרת למשתמש בודד להעלות שרטוט PDF, לקבל ניתוח אוטומטי של נתוני השרטוט, להציג אותם במסך ולשמור לקובץ. ללא מייל, ללא PL, ללא אוטומציה.

---

## 📋 תוכן עניינים

1. [רקע ומקור](#רקע-ומקור)
2. [מבנה הפרויקט](#מבנה-הפרויקט)
3. [שלב 1 — הקמה ראשונית](#שלב-1--הקמה-ראשונית)
4. [שלב 2 — העתקת קוד מ-drawingai-pro](#שלב-2--העתקת-קוד-מ-drawingai-pro)
5. [שלב 3 — בניית מודולי הליבה](#שלב-3--בניית-מודולי-הליבה)
   - 3.1 Azure Client
   - 3.2 PDF Utils
   - 3.3 Prompts
   - 3.4 💰 Cost Tracker
   - 3.5 🔍 OCR Fallback
   - 3.6 Extractor (מודול ראשי)
6. [שלב 4 — ממשק Streamlit](#שלב-4--ממשק-streamlit)
7. [שלב 5 — מודול שמירה](#שלב-5--מודול-שמירה)
8. [שלב 6 — בדיקות ידניות](#שלב-6--בדיקות-ידניות)
9. [תלויות ו-requirements](#תלויות-ו-requirements)
10. [הגדרות סביבה (.env)](#הגדרות-סביבה-env)

---

## רקע ומקור

### פרויקט המקור
**שם:** `drawingai-pro`
**מיקום:** GitHub repo קיים
**טכנולוגיה:** Python + Azure OpenAI Vision (GPT-4o / GPT-5.4) + Streamlit

### מה AIDrawAnalyser Pro עושה
מערכת אוטומציה מלאה: קוראת מיילים מ-`quotes_check@algat.co.il`, מורידה שרטוטים, מנתחת עם AI Vision, שולחת תוצאות חזרה. יש בה 5 מסלולים (הצעות, הזמנות, תעודות, חשבוניות, תלונות) ו-pipeline של 5 שלבי חילוץ.

### מה AIDrawAnalyser יעשה
**רק את שלבי 1-3 של החילוץ**, ללא שום קשר למייל:
- ❌ אין Graph API
- ❌ אין automation runner
- ❌ אין PL processing
- ❌ אין 5 מסלולים
- ❌ אין cost tracker מורכב
- ✅ העלאת PDF יחיד → חילוץ → תצוגה → שמירה

### שדות שרוצים לחלץ
מה-pipeline הקיים, שלבים 1-3:

| שדה | תיאור | מקור |
|------|--------|------|
| `part_number` | מספר פריט/חלק | Title block |
| `revision` | גרסה/רוויזיה | Title block |
| `drawing_number` | מספר שרטוט | Title block |
| `customer` | שם לקוח | Title block / logo |
| `material` | חומר גלם | Material box / Notes |
| `coating_processes` | תהליכי ציפוי | Notes |
| `painting_processes` | תהליכי צביעה | Notes |
| `standards` | תקנים (MIL-SPEC, RAL, וכו') | Notes |
| `notes` | הערות מיוחדות (CAGE CODE וכו') | Notes section |
| `process_summary_hebrew` | סיכום בעברית קצר | מיוצר מהשדות האחרים |

---

## מבנה הפרויקט

```
drawingai-lite/
│
├── .env.example              # תבנית הגדרות Azure
├── .gitignore
├── README.md
├── requirements.txt
│
├── app.py                    # 🎯 Streamlit entry point
│
├── core/
│   ├── __init__.py
│   ├── extractor.py          # חילוץ ראשי (העתק/התאמה מ-Pro)
│   ├── prompts.py            # Prompts לשלבים 1-3
│   ├── pdf_utils.py          # המרת PDF לתמונות
│   ├── ocr_fallback.py       # 🆕 OCR גיבוי עם Tesseract
│   ├── cost_tracker.py       # 🆕 מעקב עלויות לכל שרטוט
│   └── azure_client.py       # wrapper על Azure OpenAI
│
├── storage/
│   ├── __init__.py
│   └── save_handler.py       # שמירה ל-JSON / Excel
│
├── output/                   # ⬇️ קבצי יצוא (נוצר אוטומטית)
│   ├── costs.jsonl           # 🆕 לוג עלויות (נוצר אוטומטית)
│   └── .gitkeep
│
└── tests/
    └── sample_drawing.pdf    # דוגמה לבדיקה
```

---

## שלב 1 — הקמה ראשונית

### Copilot: בצע את הפעולות הבאות

**1.1 — צור ריפו חדש ב-GitHub:**

```bash
# בטרמינל של VS Code
mkdir drawingai-lite
cd drawingai-lite
git init
```

**1.2 — צור את מבנה התיקיות:**

```bash
mkdir -p core storage output tests
touch core/__init__.py storage/__init__.py
touch app.py requirements.txt README.md .env.example .gitignore
touch output/.gitkeep
# קבצים חדשים: OCR fallback + Cost tracker
touch core/ocr_fallback.py core/cost_tracker.py
```

**1.3 — צור `.gitignore`:**

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
.Python
venv/
env/
.venv/

# Environment
.env
*.env
!.env.example

# Output
output/*.json
output/*.xlsx
output/*.txt
!output/.gitkeep

# IDE
.vscode/
.idea/
*.swp

# OS
.DS_Store
Thumbs.db

# Streamlit
.streamlit/secrets.toml
```

**1.4 — צור סביבה וירטואלית:**

```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate
```

---

## שלב 2 — העתקת קוד מ-drawingai-pro

### ⚠️ חשוב: אל תעתיק הכל

רק את החלקים שקשורים ל-**שלבים 1-3 של החילוץ**. השאר לא נחוץ.

### קבצים להעתיק מ-drawingai-pro

| מ-drawingai-pro | ל-drawingai-lite | מה לקחת |
|---|---|---|
| `src/services/extraction/customer_extractor_v3_dual.py` | `core/extractor.py` | **רק** פונקציות של Stages 0, 1, 2, 3 |
| `src/services/extraction/stages_generic.py` | `core/prompts.py` | **רק** prompts של שלבים 1, 2, 3 |
| `src/utils/pdf_utils.py` (אם קיים) | `core/pdf_utils.py` | פונקציית PDF → images |

### מה **לא** להעתיק

- ❌ `automation_runner.py` — לא רלוונטי
- ❌ `graph_api_helper.py` / `ews_connector.py` — אין מייל
- ❌ `classifier.py` — לא צריך (המשתמש יודע שזה שרטוט)
- ❌ כל קוד של PL / Parts List
- ❌ GUIs של Tkinter (`*_gui.py`)
- ❌ SQL Server connectors
- ❌ Cost tracker מורכב (נבנה גרסה מינימלית)
- ❌ קוד Stage 4 (שטח גיאומטרי) — לא מתוכנן לגרסה הראשונה

### Copilot Prompt מוצע להעתקה

```
# Copy the extraction logic from drawingai-pro
# Source file: src/services/extraction/customer_extractor_v3_dual.py
# Target file: core/extractor.py
#
# Keep ONLY:
# - Stage 1: basic info extraction (part_number, revision, 
#   drawing_number, customer, material)
# - Stage 2: processes extraction (coating, painting, standards)
# - Stage 3: Hebrew summary generation
#
# Remove:
# - Stage 0 (classification) — not needed
# - Stage 4 (geometric area) — future feature
# - Email integration code
# - PL processing
# - Any imports from Graph API or email modules
#
# Add a single entry function:
# def extract_drawing(pdf_path: str) -> dict
```

---

## שלב 3 — בניית מודולי הליבה

### 3.1 — `core/azure_client.py`

```python
"""
Azure OpenAI client wrapper — מינימלי.
"""
import os
from openai import AzureOpenAI
from dotenv import load_dotenv

load_dotenv()


def get_client() -> AzureOpenAI:
    """מחזיר Azure OpenAI client מוגדר."""
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")
    
    if not endpoint or not api_key:
        raise ValueError(
            "חסרים משתני סביבה: AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY. "
            "ראה .env.example"
        )
    
    return AzureOpenAI(
        azure_endpoint=endpoint,
        api_key=api_key,
        api_version=api_version,
    )


def get_deployment() -> str:
    """מחזיר שם deployment ברירת מחדל."""
    return os.getenv("AZURE_DEPLOYMENT_NAME", "gpt-4o")
```

### 3.2 — `core/pdf_utils.py`

```python
"""
המרת PDF לתמונות base64 לצורך שליחה ל-Vision API.
"""
import base64
import io
from pathlib import Path
from pdf2image import convert_from_path, convert_from_bytes
from PIL import Image


def pdf_to_images(pdf_source, dpi: int = 200) -> list[str]:
    """
    ממיר PDF לרשימת תמונות base64.
    
    Args:
        pdf_source: נתיב לקובץ PDF או bytes
        dpi: רזולוציה (ברירת מחדל 200 — איזון איכות/עלות)
    
    Returns:
        רשימה של תמונות base64 (אחת לכל עמוד)
    """
    if isinstance(pdf_source, (str, Path)):
        images = convert_from_path(str(pdf_source), dpi=dpi)
    else:
        images = convert_from_bytes(pdf_source, dpi=dpi)
    
    base64_images = []
    for img in images:
        # אופטימיזציה: המרה ל-RGB והקטנת גודל אם צריך
        if img.mode != "RGB":
            img = img.convert("RGB")
        
        # אם התמונה גדולה מאוד — הקטן
        max_dim = 2048
        if max(img.size) > max_dim:
            img.thumbnail((max_dim, max_dim), Image.LANCZOS)
        
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
        base64_images.append(b64)
    
    return base64_images
```

### 3.3 — `core/prompts.py`

```python
"""
Prompts עבור שלבי החילוץ.
הועתקו והותאמו מ-stages_generic.py של drawingai-pro.
"""

STAGE_1_PROMPT = """
נתח את השרטוט הטכני וחלץ את המידע הבסיסי.

חפש את השדות הבאים (הסתכל במיוחד ב-Title Block בפינה הימנית תחתונה):

1. part_number — מספר פריט/חלק (Part Number, P/N, מק"ט)
2. revision — גרסה/רוויזיה (REV, Rev., גרסה)
3. drawing_number — מספר שרטוט (Drawing No., שרטוט)
4. customer — שם הלקוח (חפש לוגו, שם חברה)
5. material — חומר גלם (Material, MAT'L, חומר). דוגמאות: AL 7075-T6, STEEL 4130

החזר JSON בלבד:
{
  "part_number": "",
  "revision": "",
  "drawing_number": "",
  "customer": "",
  "material": ""
}

כללים:
- אם שדה לא נמצא — החזר מחרוזת ריקה ""
- החזר את הטקסט בדיוק כמו שמופיע בשרטוט
- אל תמציא מידע
"""

STAGE_2_PROMPT = """
חלץ מידע על תהליכי ייצור, ציפוי וצביעה מהשרטוט.

חפש באזור ה-NOTES ובכל מקום שמופיע מפרט תהליך:

1. coating_processes — תהליכי ציפוי/פלטינג:
   - דוגמאות: Anodize, Chrome, Nickel, Zinc Plating, Passivation, Alodine
   - כולל עובי אם מצוין

2. painting_processes — תהליכי צביעה:
   - Primer, Topcoat, עם קודי צבע (RAL, FED-STD-595)

3. standards — תקנים שמוזכרים:
   - MIL-SPEC (למשל MIL-PRF-23377, MIL-A-8625)
   - ASTM, AMS, ISO
   - תקנים פנימיים של החברה

4. notes — הערות מיוחדות / קריטיות:
   - CAGE CODE
   - דרישות בדיקה
   - תנאים מיוחדים

החזר JSON:
{
  "coating_processes": ["", ""],
  "painting_processes": ["", ""],
  "standards": ["", ""],
  "notes": ""
}

כללים:
- מערכים ריקים [] אם אין מידע
- notes כמחרוזת אחת (שרשור כל ההערות החשובות)
- אל תמציא תקנים שלא רואים
"""

STAGE_3_PROMPT_TEMPLATE = """
על סמך הנתונים הבאים, צור סיכום קצר בעברית (עד 80 תווים).

נתונים:
- חומר: {material}
- ציפויים: {coatings}
- צביעות: {paintings}

סדר הסיכום:
1. חומר גלם (אלומיניום/פלדה/נחושת)
2. תהליכי ציפוי (אנודייז, ניקל, פסיבציה)
3. תהליכי צביעה (פריימר, עליון + RAL אם יש)

דוגמאות:
- "אלומיניום | אנודייז שחור 15µm | צביעה RAL 7001"
- "פלדה 4130 | פסיבציה | ללא צביעה"
- "נחושת | ניקל אלקטרולס 25µm"

החזר רק את הטקסט, ללא הסבר, בהפרדה "|".
"""
```

### 3.4 — `core/cost_tracker.py`

```python
"""
מעקב עלויות — מחשב ושומר כמה עלה כל ניתוח שרטוט.
מבוסס על usage object שמחזיר Azure OpenAI בכל קריאה.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

# ═══════════════════════════════════════════════════════════════
# מחירים ל-1M טוקנים (עדכן לפי החוזה שלך ב-Azure)
# Azure בדרך כלל +10% על מחירי OpenAI הרשמיים
# ═══════════════════════════════════════════════════════════════
PRICING = {
    # gpt-4o (סטנדרטי)
    "gpt-4o": {
        "input":  2.50,   # $ per 1M tokens
        "output": 10.00,
    },
    # gpt-4o-mini (זול)
    "gpt-4o-mini": {
        "input":  0.15,
        "output": 0.60,
    },
    # gpt-5.4 (חדש, vision מעולה)
    "gpt-5.4": {
        "input":  2.50,
        "output": 15.00,
    },
}

# תוספת Azure (אם רלוונטי)
AZURE_SURCHARGE = 1.10  # +10%


def calculate_cost(usage, model: str, azure_surcharge: bool = True) -> dict:
    """
    מחשב עלות של קריאה אחת.
    
    Args:
        usage: אובייקט usage מ-Azure (יש לו prompt_tokens, completion_tokens)
        model: שם המודל (gpt-4o / gpt-4o-mini / gpt-5.4)
        azure_surcharge: האם להוסיף 10% של Azure
    
    Returns:
        dict עם input_tokens, output_tokens, input_cost, output_cost, total_cost
    """
    # התאם שם מודל (לפעמים deployment name שונה משם המודל)
    model_key = model.lower()
    if "mini" in model_key:
        pricing = PRICING["gpt-4o-mini"]
    elif "5.4" in model_key or "gpt-5" in model_key:
        pricing = PRICING["gpt-5.4"]
    else:
        pricing = PRICING["gpt-4o"]
    
    input_tokens = usage.prompt_tokens
    output_tokens = usage.completion_tokens
    
    # $ per token = price per 1M / 1_000_000
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    
    if azure_surcharge:
        input_cost *= AZURE_SURCHARGE
        output_cost *= AZURE_SURCHARGE
    
    return {
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "input_cost_usd": round(input_cost, 6),
        "output_cost_usd": round(output_cost, 6),
        "total_cost_usd": round(input_cost + output_cost, 6),
    }


class DrawingCostTracker:
    """
    מצבר עלויות של שרטוט יחיד (3 שלבים = 3 קריאות).
    """
    
    def __init__(self, filename: str):
        self.filename = filename
        self.started_at = datetime.now()
        self.stages: list[dict] = []
    
    def add_stage(self, stage_name: str, cost_data: dict) -> None:
        """הוסף עלות של שלב."""
        self.stages.append({
            "stage": stage_name,
            **cost_data,
        })
    
    def total_cost(self) -> float:
        """סך העלות בדולרים."""
        return sum(s["total_cost_usd"] for s in self.stages)
    
    def total_tokens(self) -> dict:
        """סך הטוקנים."""
        return {
            "input": sum(s["input_tokens"] for s in self.stages),
            "output": sum(s["output_tokens"] for s in self.stages),
        }
    
    def summary(self) -> dict:
        """סיכום מלא להצגה ולוג."""
        tokens = self.total_tokens()
        return {
            "filename": self.filename,
            "timestamp": self.started_at.isoformat(),
            "total_cost_usd": round(self.total_cost(), 6),
            "total_cost_ils": round(self.total_cost() * 3.7, 4),  # שער משוער
            "input_tokens": tokens["input"],
            "output_tokens": tokens["output"],
            "stages": self.stages,
        }
    
    def save_to_log(self, log_path: Path = Path("output/costs.jsonl")) -> None:
        """הוסף לקובץ לוג מצטבר (JSONL)."""
        log_path = Path(log_path)
        log_path.parent.mkdir(exist_ok=True)
        
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(self.summary(), ensure_ascii=False) + "\n")


def get_aggregate_stats(log_path: Path = Path("output/costs.jsonl")) -> Optional[dict]:
    """
    קרא את קובץ הלוג וחשב סטטיסטיקות מצטברות.
    שימושי לתצוגה ב-sidebar של Streamlit.
    """
    log_path = Path(log_path)
    if not log_path.exists():
        return None
    
    total_cost = 0.0
    total_input = 0
    total_output = 0
    count = 0
    
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
                total_cost += entry.get("total_cost_usd", 0)
                total_input += entry.get("input_tokens", 0)
                total_output += entry.get("output_tokens", 0)
                count += 1
            except json.JSONDecodeError:
                continue
    
    if count == 0:
        return None
    
    return {
        "count": count,
        "total_cost_usd": round(total_cost, 4),
        "avg_cost_usd": round(total_cost / count, 4),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
    }
```

### 3.5 — `core/ocr_fallback.py`

```python
"""
OCR fallback — משתמש ב-Tesseract להוצאת טקסט כשה-Vision API לא מזהה מספיק.

שימוש: כאשר Stage 1 מחזיר part_number ריק או חומר ריק, נריץ OCR
ונחזיר את הטקסט ל-Stage 1 עם prompt משופר שכולל את הטקסט שהוצא.
"""
import io
import logging
from pathlib import Path
from typing import Optional

from PIL import Image
from pdf2image import convert_from_path, convert_from_bytes

logger = logging.getLogger(__name__)

# ייבוא pytesseract עם טיפול בשגיאה אם לא מותקן
try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    logger.warning("pytesseract לא מותקן — OCR fallback לא יפעל")


def is_ocr_available() -> bool:
    """בודק אם Tesseract זמין במערכת."""
    if not TESSERACT_AVAILABLE:
        return False
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def extract_text_from_pdf(
    pdf_path: str | Path,
    languages: str = "eng+heb",
    dpi: int = 300,
) -> str:
    """
    מפיק טקסט מ-PDF באמצעות OCR.
    
    Args:
        pdf_path: נתיב ל-PDF
        languages: שפות Tesseract (eng+heb = אנגלית + עברית)
        dpi: רזולוציה (גבוה יותר = דיוק יותר טוב, איטי יותר)
    
    Returns:
        טקסט משורשר מכל העמודים
    """
    if not is_ocr_available():
        raise RuntimeError(
            "Tesseract לא זמין. התקן: "
            "Windows: https://github.com/UB-Mannheim/tesseract/wiki | "
            "Linux: apt install tesseract-ocr tesseract-ocr-heb | "
            "Mac: brew install tesseract tesseract-lang"
        )
    
    pdf_path = Path(pdf_path)
    logger.info(f"OCR מופעל על: {pdf_path.name}")
    
    images = convert_from_path(str(pdf_path), dpi=dpi)
    
    all_text = []
    for idx, img in enumerate(images, 1):
        try:
            text = pytesseract.image_to_string(img, lang=languages)
            all_text.append(f"=== עמוד {idx} ===\n{text}")
        except Exception as e:
            logger.warning(f"OCR נכשל על עמוד {idx}: {e}")
            continue
    
    full_text = "\n\n".join(all_text)
    logger.info(f"OCR חילץ {len(full_text)} תווים")
    return full_text


def should_use_fallback(stage1_result: dict) -> bool:
    """
    בודק אם צריך להפעיל OCR fallback.
    
    קריטריונים (אם 2+ שדות קריטיים ריקים — הפעל):
    - part_number
    - material
    - drawing_number
    """
    critical_fields = ["part_number", "material", "drawing_number"]
    empty_count = sum(
        1 for field in critical_fields
        if not stage1_result.get(field) or stage1_result.get(field).strip() == ""
    )
    return empty_count >= 2


def build_enhanced_prompt(base_prompt: str, ocr_text: str) -> str:
    """
    בונה prompt משופר שכולל את טקסט ה-OCR.
    """
    # חותך את OCR ל-3000 תווים מקסימום (אחרת ה-prompt מתארך מדי)
    ocr_snippet = ocr_text[:3000]
    
    return f"""{base_prompt}

═══════════════════════════════════════════════════
📝 טקסט שהוצא מה-PDF באמצעות OCR (עזרה נוספת):
═══════════════════════════════════════════════════
{ocr_snippet}
═══════════════════════════════════════════════════

⚠️ השתמש ב-OCR כעזר בלבד. המקור הראשי הוא התמונות.
אם יש סתירה, תן עדיפות למה שנראה בתמונה.
"""
```

### 3.6 — `core/extractor.py` (המודול הראשי — משלב הכל)

```python
"""
חילוץ נתונים משרטוט PDF — מודול ראשי של AIDrawAnalyser.
עם Cost Tracking + OCR Fallback.
"""
import json
import logging
from pathlib import Path

from core.azure_client import get_client, get_deployment
from core.pdf_utils import pdf_to_images
from core.prompts import STAGE_1_PROMPT, STAGE_2_PROMPT, STAGE_3_PROMPT_TEMPLATE
from core.cost_tracker import DrawingCostTracker, calculate_cost
from core.ocr_fallback import (
    is_ocr_available,
    extract_text_from_pdf,
    should_use_fallback,
    build_enhanced_prompt,
)

logger = logging.getLogger(__name__)


def _call_vision(client, deployment: str, prompt: str, images_b64: list[str]):
    """קריאה ל-Vision API. מחזיר (result_dict, usage)."""
    content = [{"type": "text", "text": prompt}]
    for img_b64 in images_b64:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
        })
    
    response = client.chat.completions.create(
        model=deployment,
        messages=[{"role": "user", "content": content}],
        max_tokens=1500,
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    
    result = json.loads(response.choices[0].message.content)
    return result, response.usage


def _call_text(client, deployment: str, prompt: str):
    """קריאה טקסטואלית. מחזיר (text, usage)."""
    response = client.chat.completions.create(
        model=deployment,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200,
        temperature=0.3,
    )
    return response.choices[0].message.content.strip(), response.usage


def extract_drawing(pdf_path: str | Path, use_ocr_fallback: bool = True) -> dict:
    """
    חילוץ מלא של שרטוט PDF עם cost tracking ו-OCR fallback.
    
    Args:
        pdf_path: נתיב לקובץ PDF
        use_ocr_fallback: האם להפעיל OCR fallback אם Stage 1 חלש
    
    Returns:
        dict עם כל השדות + _cost_info עם פירוט עלויות
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"קובץ לא נמצא: {pdf_path}")
    
    logger.info(f"מעבד שרטוט: {pdf_path.name}")
    
    # המרה לתמונות
    images = pdf_to_images(pdf_path)
    logger.info(f"PDF הומר ל-{len(images)} עמודים")
    
    client = get_client()
    deployment = get_deployment()
    tracker = DrawingCostTracker(pdf_path.name)
    
    # ─── Stage 1 — מידע בסיסי ───
    logger.info("Stage 1: חילוץ מידע בסיסי...")
    stage1, usage1 = _call_vision(client, deployment, STAGE_1_PROMPT, images)
    tracker.add_stage("stage_1_basic_info", calculate_cost(usage1, deployment))
    
    # ─── OCR Fallback (אם צריך) ───
    ocr_used = False
    if use_ocr_fallback and should_use_fallback(stage1):
        if is_ocr_available():
            logger.info("⚠️ Stage 1 חלש — מפעיל OCR fallback...")
            try:
                ocr_text = extract_text_from_pdf(pdf_path)
                enhanced_prompt = build_enhanced_prompt(STAGE_1_PROMPT, ocr_text)
                
                stage1_retry, usage_retry = _call_vision(
                    client, deployment, enhanced_prompt, images
                )
                tracker.add_stage(
                    "stage_1_ocr_retry",
                    calculate_cost(usage_retry, deployment)
                )
                
                # מזג — העדף ערכים לא ריקים מה-retry
                for key, value in stage1_retry.items():
                    if value and not stage1.get(key):
                        stage1[key] = value
                
                ocr_used = True
                logger.info("✅ OCR fallback הושלם")
            except Exception as e:
                logger.warning(f"OCR fallback נכשל: {e}")
        else:
            logger.info("OCR לא זמין — מדלג על fallback")
    
    # ─── Stage 2 — תהליכים ───
    logger.info("Stage 2: חילוץ תהליכים...")
    stage2, usage2 = _call_vision(client, deployment, STAGE_2_PROMPT, images)
    tracker.add_stage("stage_2_processes", calculate_cost(usage2, deployment))
    
    # ─── Stage 3 — סיכום עברי ───
    logger.info("Stage 3: יצירת סיכום עברי...")
    stage3_prompt = STAGE_3_PROMPT_TEMPLATE.format(
        material=stage1.get("material", ""),
        coatings=", ".join(stage2.get("coating_processes", [])),
        paintings=", ".join(stage2.get("painting_processes", [])),
    )
    hebrew_summary, usage3 = _call_text(client, deployment, stage3_prompt)
    tracker.add_stage("stage_3_hebrew_summary", calculate_cost(usage3, deployment))
    
    # ─── איחוד תוצאות ───
    result = {
        **stage1,
        **stage2,
        "process_summary_hebrew": hebrew_summary,
        "source_filename": pdf_path.name,
        "_cost_info": tracker.summary(),
        "_ocr_used": ocr_used,
    }
    
    # שמור ללוג עלויות
    tracker.save_to_log()
    
    logger.info(
        f"✅ חילוץ הושלם | עלות: ${tracker.total_cost():.4f} "
        f"(~₪{tracker.total_cost() * 3.7:.3f})"
    )
    return result
```

---

## שלב 4 — ממשק Streamlit

### `app.py`

```python
"""
AIDrawAnalyser — Streamlit UI
אפליקציה למשתמש בודד לניתוח שרטוט PDF.
"""
import json
import logging
from datetime import datetime
from pathlib import Path

import streamlit as st

from core.extractor import extract_drawing
from core.cost_tracker import get_aggregate_stats
from core.ocr_fallback import is_ocr_available
from storage.save_handler import save_to_json, save_to_excel

# ═══════════════════════════════════════════════════════════════
# הגדרות
# ═══════════════════════════════════════════════════════════════
logging.basicConfig(level=logging.INFO)

st.set_page_config(
    page_title="AIDrawAnalyser",
    page_icon="📐",
    layout="wide",
)

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)


# ═══════════════════════════════════════════════════════════════
# UI
# ═══════════════════════════════════════════════════════════════
st.title("📐 AIDrawAnalyser")
st.caption("ניתוח אוטומטי של שרטוטים טכניים — משתמש בודד")

# Session state
if "result" not in st.session_state:
    st.session_state.result = None
if "filename" not in st.session_state:
    st.session_state.filename = None

# ─────────────────────────────────────
# העלאת קובץ + אפשרויות
# ─────────────────────────────────────
st.markdown("### 1️⃣ העלה שרטוט PDF")

col_upload, col_opts = st.columns([3, 1])

with col_upload:
    uploaded_file = st.file_uploader(
        "גרור שרטוט או לחץ לבחירה",
        type=["pdf"],
        help="קבצי PDF בלבד, עד 20MB"
    )

with col_opts:
    st.markdown("**אפשרויות:**")
    ocr_enabled = st.checkbox(
        "OCR Fallback",
        value=True,
        disabled=not is_ocr_available(),
        help="יפעל אוטומטית אם AI לא מזהה שדות קריטיים"
    )
    if not is_ocr_available():
        st.caption("⚠️ Tesseract לא מותקן")

if uploaded_file is not None:
    temp_path = OUTPUT_DIR / f"_temp_{uploaded_file.name}"
    with open(temp_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    
    st.session_state.filename = uploaded_file.name
    
    if st.button("🔍 נתח שרטוט", type="primary"):
        with st.spinner("🔄 מנתח... (עשוי לקחת 20-40 שניות)"):
            try:
                result = extract_drawing(temp_path, use_ocr_fallback=ocr_enabled)
                st.session_state.result = result
                st.success("✅ ניתוח הושלם")
            except Exception as e:
                st.error(f"❌ שגיאה: {e}")
                st.session_state.result = None
            finally:
                if temp_path.exists():
                    temp_path.unlink()

# ─────────────────────────────────────
# תצוגת תוצאות
# ─────────────────────────────────────
if st.session_state.result:
    st.divider()
    
    r = st.session_state.result
    cost_info = r.get("_cost_info", {})
    ocr_used = r.get("_ocr_used", False)
    
    # ─── באנר עלות + OCR ───
    banner_col1, banner_col2, banner_col3, banner_col4 = st.columns(4)
    with banner_col1:
        total_usd = cost_info.get("total_cost_usd", 0)
        st.metric("💰 עלות השרטוט", f"${total_usd:.4f}")
    with banner_col2:
        total_ils = cost_info.get("total_cost_ils", 0)
        st.metric("💱 בשקלים", f"₪{total_ils:.3f}")
    with banner_col3:
        st.metric(
            "🔤 טוקנים",
            f"{cost_info.get('input_tokens', 0):,} + {cost_info.get('output_tokens', 0):,}"
        )
    with banner_col4:
        if ocr_used:
            st.metric("🔍 OCR", "הופעל")
        else:
            st.metric("🔍 OCR", "לא נדרש")
    
    st.divider()
    st.markdown("### 2️⃣ תוצאות הניתוח")
    
    # כרטיסים למידע בסיסי
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("מספר פריט", r.get("part_number") or "—")
        st.metric("לקוח", r.get("customer") or "—")
    with col2:
        st.metric("מספר שרטוט", r.get("drawing_number") or "—")
        st.metric("חומר גלם", r.get("material") or "—")
    with col3:
        st.metric("גרסה", r.get("revision") or "—")
    
    st.divider()
    
    # תהליכים ותקנים
    col_a, col_b = st.columns(2)
    
    with col_a:
        st.markdown("#### 🎨 תהליכי ציפוי")
        coatings = r.get("coating_processes", [])
        if coatings:
            for c in coatings:
                st.markdown(f"- {c}")
        else:
            st.caption("לא נמצאו")
        
        st.markdown("#### 🖌️ תהליכי צביעה")
        paintings = r.get("painting_processes", [])
        if paintings:
            for p in paintings:
                st.markdown(f"- {p}")
        else:
            st.caption("לא נמצאו")
    
    with col_b:
        st.markdown("#### 📜 תקנים")
        standards = r.get("standards", [])
        if standards:
            for s in standards:
                st.markdown(f"- `{s}`")
        else:
            st.caption("לא נמצאו")
        
        st.markdown("#### 📝 הערות")
        notes = r.get("notes", "")
        if notes:
            st.info(notes)
        else:
            st.caption("אין הערות")
    
    # סיכום עברי
    st.markdown("#### 🇮🇱 סיכום עברי")
    st.success(r.get("process_summary_hebrew", "—"))
    
    # ─── פירוט עלויות מתקפל ───
    with st.expander("💰 פירוט עלויות לפי שלב"):
        stages = cost_info.get("stages", [])
        if stages:
            import pandas as pd
            df = pd.DataFrame(stages)
            df = df[["stage", "input_tokens", "output_tokens", "total_cost_usd"]]
            df.columns = ["שלב", "Input tokens", "Output tokens", "עלות $"]
            st.dataframe(df, use_container_width=True, hide_index=True)
    
    # JSON גולמי
    with st.expander("📄 JSON מלא"):
        # הסר שדות פנימיים מהתצוגה
        display_data = {k: v for k, v in r.items() if not k.startswith("_")}
        st.json(display_data)
    
    # ─────────────────────────────────────
    # שמירה
    # ─────────────────────────────────────
    st.divider()
    st.markdown("### 3️⃣ שמור תוצאה")
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = Path(st.session_state.filename).stem
    
    col_s1, col_s2, col_s3 = st.columns(3)
    
    with col_s1:
        if st.button("💾 שמור JSON", use_container_width=True):
            path = save_to_json(r, OUTPUT_DIR / f"{base_name}_{timestamp}.json")
            st.success(f"נשמר: `{path.name}`")
    
    with col_s2:
        if st.button("📊 שמור Excel", use_container_width=True):
            path = save_to_excel(r, OUTPUT_DIR / f"{base_name}_{timestamp}.xlsx")
            st.success(f"נשמר: `{path.name}`")
    
    with col_s3:
        if st.button("🔄 שרטוט חדש", use_container_width=True):
            st.session_state.result = None
            st.session_state.filename = None
            st.rerun()

# ─────────────────────────────────────
# Sidebar — מידע ומעקב עלויות מצטבר
# ─────────────────────────────────────
with st.sidebar:
    st.markdown("### ℹ️ אודות")
    st.markdown("""
    **AIDrawAnalyser v1.0**
    
    - העלאה ידנית של PDF יחיד
    - ניתוח AI עם Azure OpenAI Vision
    - OCR fallback אוטומטי
    - מעקב עלויות לכל שרטוט
    """)
    
    st.divider()
    
    # ─── סטטיסטיקות עלויות מצטברות ───
    st.markdown("### 📊 עלויות מצטברות")
    stats = get_aggregate_stats()
    if stats:
        st.metric("שרטוטים שנותחו", stats["count"])
        st.metric("סה\"כ עלות", f"${stats['total_cost_usd']:.2f}")
        st.metric("ממוצע לשרטוט", f"${stats['avg_cost_usd']:.4f}")
    else:
        st.caption("עדיין לא נותחו שרטוטים")
    
    st.divider()
    
    st.markdown("### 📁 קבצים שמורים")
    saved = sorted(OUTPUT_DIR.glob("*.json"), reverse=True)[:10]
    saved = [f for f in saved if not f.name.startswith("_") and f.name != "costs.jsonl"]
    if saved:
        for f in saved:
            st.caption(f"📄 {f.name}")
    else:
        st.caption("עדיין אין קבצים")
```

---

## שלב 5 — מודול שמירה

### `storage/save_handler.py`

```python
"""
שמירת תוצאות ל-JSON ו-Excel.
"""
import json
from datetime import datetime
from pathlib import Path

import pandas as pd


def save_to_json(data: dict, path: Path) -> Path:
    """שמירה ל-JSON בפורמט קריא עם UTF-8 מלא."""
    path = Path(path)
    data_with_meta = {
        **data,
        "_saved_at": datetime.now().isoformat(),
    }
    path.write_text(
        json.dumps(data_with_meta, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    return path


def save_to_excel(data: dict, path: Path) -> Path:
    """שמירה ל-Excel — שורה אחת עם כל השדות."""
    path = Path(path)
    
    # להמיר מערכים למחרוזות מופרדות בפסיק
    flat = {}
    for k, v in data.items():
        if isinstance(v, list):
            flat[k] = ", ".join(str(x) for x in v)
        else:
            flat[k] = v
    
    flat["_saved_at"] = datetime.now().isoformat()
    
    df = pd.DataFrame([flat])
    df.to_excel(path, index=False, engine="openpyxl")
    return path


def append_to_log(data: dict, log_path: Path = Path("output/history.jsonl")) -> None:
    """הוסף שורה ל-JSONL לתיעוד היסטורי."""
    log_path = Path(log_path)
    log_path.parent.mkdir(exist_ok=True)
    
    entry = {
        "timestamp": datetime.now().isoformat(),
        **data,
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
```

---

## שלב 6 — בדיקות ידניות

### תסריטי בדיקה

**בדיקה 1 — שרטוט פשוט עם חומר בלבד:**
- שים PDF של שרטוט חלק מאלומיניום ללא ציפוי
- ציפייה: `material` = "AL 7075-T6" או דומה, `coating_processes` = []

**בדיקה 2 — שרטוט מורכב עם ציפויים:**
- PDF עם Anodize + MIL-A-8625
- ציפייה: `coating_processes` מכיל "Anodize", `standards` מכיל "MIL-A-8625"

**בדיקה 3 — שמירה ל-JSON:**
- אחרי ניתוח — לחץ "שמור JSON"
- ודא שנוצר קובץ ב-`output/` עם כל השדות

**בדיקה 4 — Edge cases:**
- PDF ריק / פגום — ציפייה: הודעת שגיאה ברורה
- PDF רב-עמודים — ציפייה: כל העמודים נשלחים ל-AI

---

## תלויות ו-requirements

### `requirements.txt`

```txt
# Core
streamlit>=1.30.0
openai>=1.12.0
python-dotenv>=1.0.0

# PDF processing
pdf2image>=1.17.0
Pillow>=10.0.0

# OCR fallback
pytesseract>=0.3.10

# Data export
pandas>=2.0.0
openpyxl>=3.1.0
```

### תלויות מערכת (לא Python)

**Poppler** (ל-pdf2image):
- **Windows:** הורד מ-https://github.com/oschwartz10612/poppler-windows, הוסף ל-PATH
- **Linux:** `sudo apt-get install poppler-utils`
- **Mac:** `brew install poppler`

**Tesseract** (ל-OCR fallback):
- **Windows:** הורד מ-https://github.com/UB-Mannheim/tesseract/wiki
  - ⚠️ בהתקנה, סמן **Hebrew** בשפות
  - הוסף ל-PATH: `C:\Program Files\Tesseract-OCR`
- **Linux:** `sudo apt-get install tesseract-ocr tesseract-ocr-heb tesseract-ocr-eng`
- **Mac:** `brew install tesseract tesseract-lang`

**בדיקה שהתקנה עובדת:**

```bash
tesseract --version
tesseract --list-langs  # ודא שיש eng + heb
```

> 💡 אם Tesseract לא מותקן — האפליקציה תעבוד בלעדיו, רק ה-OCR fallback יהיה מושבת.

### התקנה

```bash
pip install -r requirements.txt
```

---

## הגדרות סביבה (.env)

### `.env.example`

```env
# Azure OpenAI — העתק מ-drawingai-pro
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-api-key-here
AZURE_OPENAI_API_VERSION=2024-08-01-preview

# Deployment name (המודל שתשתמשי בו)
AZURE_DEPLOYMENT_NAME=gpt-4o
```

### הוראות למשתמש

```bash
# 1. העתק את הקובץ
cp .env.example .env

# 2. פתח .env וערוך את הערכים
# 3. אל תעלה את .env ל-GitHub! (כבר ב-.gitignore)
```

---

## הפעלה

```bash
# הפעל את האפליקציה
streamlit run app.py

# ייפתח אוטומטית ב-http://localhost:8501
```

---

## 📋 Checklist ל-Copilot

בנה בסדר הזה, ובדוק אחרי כל שלב:

- [ ] **שלב 1:** מבנה תיקיות + `.gitignore` + `.env.example`
- [ ] **שלב 2:** `requirements.txt` + `pip install`
- [ ] **שלב 3:** התקן Tesseract + Poppler במערכת, בדוק `tesseract --version`
- [ ] **שלב 4:** `core/azure_client.py` — בדוק שמתחבר
- [ ] **שלב 5:** `core/pdf_utils.py` — בדוק המרת PDF של דוגמה
- [ ] **שלב 6:** `core/prompts.py` — העתק prompts
- [ ] **שלב 7:** `core/cost_tracker.py` — בדוק חישוב על usage dummy
- [ ] **שלב 8:** `core/ocr_fallback.py` — בדוק `is_ocr_available()` מחזיר True
- [ ] **שלב 9:** `core/extractor.py` — בדוק על שרטוט בודד דרך python shell
- [ ] **שלב 10:** `storage/save_handler.py` — בדוק שמירה
- [ ] **שלב 11:** `app.py` — הפעל ובדוק כל הזרימה
- [ ] **שלב 12:** בדוק שמופיעים: עלות $, עלות ₪, טוקנים, סטטוס OCR
- [ ] **שלב 13:** בדוק ש-`output/costs.jsonl` נוצר ונערם אחרי כל שרטוט
- [ ] **שלב 14:** README.md עם הוראות הפעלה
- [ ] **שלב 15:** Commit + Push ל-GitHub

---

## הערות חשובות ל-Copilot

1. **⚠️ אל תמציא prompts חדשים.** העתק אותם מ-`drawingai-pro/src/services/extraction/stages_generic.py`. ה-prompts המוצעים במסמך הזה הם רק דוגמה — ה-prompts בפרודקשן כבר עברו אופטימיזציה.

2. **⚠️ בדוק את מבנה ה-JSON.** השדות שמחזיר הקוד של Pro עשויים להיות שונים קלות. התאם בהתאם.

3. **עלות לכל ניתוח:** הקוד כעת עוקב אוטומטית. בערך $0.02-0.05 לשרטוט סטנדרטי, $0.05-0.10 אם OCR fallback הופעל (כי זה stage רביעי). הכל נשמר ב-`output/costs.jsonl`.

4. **⚠️ בדקי את המחירים ב-`cost_tracker.py`.** המחירים בקוד נכונים לאפריל 2026 אבל OpenAI מעדכנת מחירים מדי פעם. ודאי מול דף התמחור הרשמי או מול החשבון שלך ב-Azure Portal.

5. **טיפול בשגיאות:** במיוחד חשוב — אם Azure מחזיר שגיאה (rate limit, timeout), האפליקציה צריכה להציג הודעה ברורה למשתמש, לא לקרוס.

6. **עברית ב-JSON:** ודא שהשמירה ל-JSON משתמשת ב-`ensure_ascii=False` אחרת העברית תישמר כ-escape codes.

7. **OCR fallback — מתי הוא מופעל:** רק כש-Stage 1 מחזיר 2+ שדות קריטיים ריקים (`part_number`, `material`, `drawing_number`). זה חוסך עלויות — לא נפעיל OCR על שרטוטים שה-Vision קורא טוב.

8. **Tesseract אופציונלי:** האפליקציה תעבוד גם בלעדיו. ב-UI מוצג checkbox שמתבטל אוטומטית אם Tesseract לא מותקן.

9. **לוג עלויות מצטבר (`costs.jsonl`):** Copilot, אל תמחק את הקובץ הזה ב-gitignore! **כן**, הוא כבר ב-gitignore כי הוא באופרציה של המשתמש. אבל חשוב — אם המשתמש רוצה לנתח את העלויות לאורך זמן, זה המקור.

10. **אין פונקציית login:** זה לשימוש בודד מקומי. אם בעתיד תרצי להעלות לשרת — תצטרכי להוסיף Azure AD או משהו דומה.

---

*נוצר לצורך בניית AIDrawAnalyser — גרסה מצומצמת של AIDrawAnalyser Pro לשימוש משתמש בודד*
