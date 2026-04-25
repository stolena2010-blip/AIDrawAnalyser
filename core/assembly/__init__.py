"""
Assembly Mode — חילוץ מלא של מספר שרטוטים וניתוח קשרים בין מכלולים.

חבילה זו נפרדת לחלוטין מ-core/extractor.py כדי לא להשפיע על המצב הקיים
של ניתוח שרטוט בודד. היא משתמשת ב-pipeline משלה עם prompts ייעודיים
מתוך core/assembly_prompts.py.

מבנה פנימי (כל קובץ עצמאי, ללא תלויות מעגליות):
    api.py           — עזרי קריאה ל-Azure OpenAI (vision/text JSON)
    material.py      — חילוץ MATERIAL מטקסט OCR (label-based + direct regex)
    post_process.py  — מתקנים/ולידציות לשרטוט בודד אחרי Stage 1+2
    pipeline.py      — extract_assembly_drawing + extract_assembly_overview_image
    relationships.py — analyze_relationships (ניתוח קשרים בין כל השרטוטים)

API ציבורי (יציב):
    extract_assembly_drawing(pdf_path) → dict
    extract_assembly_overview_image(image_path) → dict
    analyze_relationships(results) → dict
"""
from core.assembly.pipeline import (
    extract_assembly_drawing,
    extract_assembly_overview_image,
)
from core.assembly.relationships import analyze_relationships

__all__ = [
    "extract_assembly_drawing",
    "extract_assembly_overview_image",
    "analyze_relationships",
]
