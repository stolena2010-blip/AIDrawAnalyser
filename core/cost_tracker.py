"""
מעקב עלויות — מחשב ושומר כמה עלה כל ניתוח שרטוט.
מבוסס על usage object שמחזיר Azure OpenAI בכל קריאה.
"""
import json
import os
from datetime import datetime
from pathlib import Path

# ═══════════════════════════════════════════════════════════════
# מחירים ל-1M טוקנים (עדכן לפי החוזה שלך ב-Azure)
# Azure בדרך כלל +10% על מחירי OpenAI הרשמיים
# ═══════════════════════════════════════════════════════════════
PRICING = {
    "gpt-4o": {
        "input":  2.50,
        "output": 10.00,
    },
    "gpt-4o-mini": {
        "input":  0.15,
        "output": 0.60,
    },
    "gpt-5.4": {
        "input":  2.50,
        "output": 15.00,
    },
}

AZURE_SURCHARGE = float(os.getenv("AZURE_SURCHARGE", "1.20"))
# תוספת Azure על מחירי OpenAI הרשמיים.
# 1.10 = +10% (ברירת מחדל ישנה) | 1.20 = +20% (Azure Regional / Data Residency)
# ניתן לשנות דרך .env: AZURE_SURCHARGE=1.20


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
    model_key = model.lower()
    if "mini" in model_key:
        pricing = PRICING["gpt-4o-mini"]
    elif "5.4" in model_key or "gpt-5" in model_key:
        pricing = PRICING["gpt-5.4"]
    else:
        pricing = PRICING["gpt-4o"]

    input_tokens = usage.prompt_tokens
    output_tokens = usage.completion_tokens

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
    """מצבר עלויות של שרטוט יחיד (3 שלבים = 3 קריאות)."""

    def __init__(self, filename: str):
        self.filename = filename
        self.started_at = datetime.now()
        self.stages: list[dict] = []

    def add_stage(self, stage_name: str, cost_data: dict) -> None:
        self.stages.append({
            "stage": stage_name,
            **cost_data,
        })

    def total_cost(self) -> float:
        return sum(s["total_cost_usd"] for s in self.stages)

    def total_tokens(self) -> dict:
        return {
            "input": sum(s["input_tokens"] for s in self.stages),
            "output": sum(s["output_tokens"] for s in self.stages),
        }

    def summary(self) -> dict:
        tokens = self.total_tokens()
        return {
            "filename": self.filename,
            "timestamp": self.started_at.isoformat(),
            "total_cost_usd": round(self.total_cost(), 6),
            "total_cost_ils": round(self.total_cost() * 3.7, 4),
            "input_tokens": tokens["input"],
            "output_tokens": tokens["output"],
            "stages": self.stages,
        }

    def save_to_log(self, log_path: Path = Path("output/costs.jsonl")) -> None:
        log_path = Path(log_path)
        log_path.parent.mkdir(exist_ok=True)

        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(self.summary(), ensure_ascii=False) + "\n")


def get_aggregate_stats(log_path: Path = Path("output/costs.jsonl")) -> dict | None:
    """קרא את קובץ הלוג וחשב סטטיסטיקות מצטברות."""
    log_path = Path(log_path)
    if not log_path.exists():
        return None

    total_cost = 0.0
    total_input = 0
    total_output = 0
    count = 0

    with open(log_path, encoding="utf-8") as f:
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
