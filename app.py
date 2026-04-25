"""
AIDrawAnalyser — Streamlit UI
אפליקציה למשתמש בודד לניתוח שרטוט PDF.
"""
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from core import audit
from core.assembly import extract_assembly_drawing
from core.azure_client import (
    MODEL_GPT_4O,
    MODEL_GPT_5_4,
    SUPPORTED_MODELS,
    _active_model,
    enabled_modes,
    get_deployment,
    is_fallback_enabled,
    is_reasoning_model,
    save_runtime_settings,
)
from core.cost_tracker import get_aggregate_stats
from core.demo_data import DEMO_FILENAME, get_demo_result, is_demo_result
from core.exceptions import format_error_for_ui, get_streamlit_level
from core.history import append_history
from core.ocr_fallback import is_ocr_available
from storage.pdf_report import (
    build_assembly_excel,
    build_assembly_html,
)
from storage.save_handler import save_to_json
from ui_assembly import (
    _get_review_status,
    _render_export_pair,
    _render_stage_model_feedback as _asm_render_stage_model_feedback,
    _render_validation_warnings as _asm_render_validation_warnings,
    render_drawing_tabs,
    render_review_edit_form,
    render_summary_card,
)

# ═══════════════════════════════════════════════════════════════
# הגדרות
# ═══════════════════════════════════════════════════════════════
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="AIDrawAnalyser",
    page_icon="📐",
    layout="wide",
    initial_sidebar_state="expanded",
)

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)


_SEVERITY_ICON = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}


def _render_validation_warnings(result: dict) -> None:
    """מציג אזהרות ולידציה (RAL, מותג, ציפוי, אריזה, two-pass) אם קיימות."""
    warnings = result.get("_validation_warnings") or []
    if not warnings:
        return
    critical = [w for w in warnings if w.get("severity") == "CRITICAL"]
    label = f"⚠️ {len(warnings)} אזהרות ולידציה"
    if critical:
        label += f" — {len(critical)} 🔴 קריטיות"
    with st.expander(label, expanded=bool(critical)):
        for w in warnings:
            icon = _SEVERITY_ICON.get(w.get("severity", ""), "⚪")
            st.markdown(
                f"{icon} **{w.get('type', '')}** | מקור: `{w.get('source', '')}` | "
                f"ערך: `{w.get('value', '')[:80]}`  \n"
                f"_{w.get('message', '')}_"
            )


def _render_stage_model_feedback(cost_info: dict,
                                 title: str = "🤖 מודל בפועל לכל שלב",
                                 expanded: bool = False) -> None:
    """מציג פירוט שלבים עם המודל בפועל, טוקנים ועלות."""
    stages = (cost_info or {}).get("stages") or []
    if not stages:
        return

    rows = []
    for s in stages:
        if not isinstance(s, dict):
            continue
        rows.append({
            "שלב": s.get("stage", ""),
            "מודל בפועל": s.get("model", ""),
            "Input": s.get("input_tokens", 0),
            "Output": s.get("output_tokens", 0),
            "עלות $": s.get("total_cost_usd", 0),
        })

    if not rows:
        return

    with st.expander(title, expanded=expanded):
        st.dataframe(rows, use_container_width=True, hide_index=True)
        models = sorted({r["מודל בפועל"] for r in rows if r["מודל בפועל"]})
        if models:
            st.caption("מודלים בשימוש: " + " | ".join(models))


# ─── עיצוב גלובלי: RTL + טיפוגרפיה + פלטה אחידה ───
st.markdown(
    """
    <style>
    /* ── RTL בסיסי ── */
    .stApp, .main, [data-testid="stAppViewContainer"] { direction: rtl; text-align: right; }
    [data-testid="stMarkdownContainer"], .stAlert, .stMetric { direction: rtl; text-align: right; }
    [data-testid="stAlert"] { unicode-bidi: plaintext; }
    code, pre { direction: ltr; text-align: left; unicode-bidi: embed; }

    /* ── טיפוגרפיה ── */
    html, body, [class*="css"] {
        font-family: "Segoe UI", "Heebo", -apple-system, BlinkMacSystemFont, sans-serif;
    }
    h1, h2, h3, h4 { font-weight: 700; letter-spacing: -0.01em; }

    /* ── הסר את הריווח העליון הענק של Streamlit ── */
    .block-container { padding-top: 1.2rem !important; max-width: 1300px; }

    /* ── כותרת אפליקציה ── */
    .app-header {
        background: linear-gradient(135deg, #0d6efd 0%, #6610f2 100%);
        color: white;
        padding: 0.9em 1.4em;
        border-radius: 0.7em;
        margin-bottom: 1em;
        box-shadow: 0 4px 12px rgba(13, 110, 253, 0.18);
        display: flex; justify-content: space-between; align-items: center;
    }
    .app-header h1 {
        margin: 0; font-size: 1.5em; color: white;
        display: flex; align-items: center; gap: 0.4em;
    }
    .app-header .tagline {
        font-size: 0.85em; opacity: 0.9; margin-top: 0.15em;
    }

    /* ── כרטיס סקשן ── */
    [data-testid="stExpander"] {
        border: 1px solid #dee2e6; border-radius: 0.5em;
    }
    [data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 0.6em !important;
    }

    /* ── מתג מצב (segmented control) ── */
    [data-testid="stSegmentedControl"] button {
        font-weight: 600 !important; padding: 0.6em 1.2em !important;
    }

    /* ── סיידבר ── */
    [data-testid="stSidebar"] {
        background: #f8f9fa; border-left: 1px solid #dee2e6;
    }
    [data-testid="stSidebar"] h3 {
        color: #495057; font-size: 0.85em;
        text-transform: uppercase; letter-spacing: 0.08em;
        margin-top: 1em; margin-bottom: 0.4em;
    }
    [data-testid="stSidebar"] hr {
        margin: 0.6em 0; border-color: #dee2e6;
    }

    /* ── כפתורים ── */
    .stButton > button {
        border-radius: 0.4em; font-weight: 600; transition: all 0.15s;
    }
    .stButton > button:hover {
        transform: translateY(-1px); box-shadow: 0 2px 6px rgba(0,0,0,0.1);
    }

    /* ── סקשן עם בורדר ── */
    .section-card {
        background: white; border: 1px solid #dee2e6;
        border-radius: 0.6em; padding: 1em 1.2em; margin-bottom: 1em;
    }

    /* ── באנר מצב עבודה (לפי מצב) ── */
    .mode-banner {
        color: white;
        padding: 0.75em 1.2em;
        border-radius: 0.6em;
        margin-bottom: 1em;
        display: flex; justify-content: space-between; align-items: center;
        font-weight: 600;
    }
    .mode-banner .mode-title {
        font-size: 1.15em; display: flex; align-items: center; gap: 0.45em;
    }
    .mode-banner .mode-tagline {
        font-size: 0.85em; opacity: 0.92; font-weight: 400;
    }
    .mode-banner-single {
        background: linear-gradient(135deg, #0891b2 0%, #06b6d4 100%);
        box-shadow: 0 3px 10px rgba(8, 145, 178, 0.22);
        border-right: 4px solid #155e75;
    }
    .mode-banner-assembly {
        background: linear-gradient(135deg, #ea580c 0%, #f59e0b 100%);
        box-shadow: 0 3px 10px rgba(234, 88, 12, 0.22);
        border-right: 4px solid #9a3412;
    }
    /* גוון רקע עדין לאזור התוכן לפי המצב */
    body[data-mode="single"]   { background: #f0fbfd; }
    body[data-mode="assembly"] { background: #fff7ed; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ═══════════════════════════════════════════════════════════════
# כותרת עליונה — לוגו + חיווי מודל
# ═══════════════════════════════════════════════════════════════
_active = get_deployment()
_badge = "🧠 Reasoning" if is_reasoning_model() else "👁️ Vision"

st.markdown(
    f'<div class="app-header">'
    f'<div>'
    f'<h1>📐 AIDrawAnalyser</h1>'
    f'<div class="tagline">ניתוח אוטומטי של שרטוטים טכניים בעזרת AI</div>'
    f'</div>'
    f'<div style="text-align:left; font-size:0.85em; opacity:0.95;">'
    f'<div>מודל פעיל: <b>{_active}</b></div>'
    f'<div style="margin-top:0.2em;">{_badge}</div>'
    f'</div>'
    f'</div>',
    unsafe_allow_html=True,
)


# ═══════════════════════════════════════════════════════════════
# סיידבר — מצב עבודה, הגדרות, מנהל, אודות
# ═══════════════════════════════════════════════════════════════
with st.sidebar:
    # ─── בורר מצב עבודה ───
    st.markdown("### 🧭 מצב עבודה")
    _allowed_modes = enabled_modes()
    _allowed_modes = [m for m in _allowed_modes if m in {"single", "assembly"}]
    if not _allowed_modes:
        _allowed_modes = ["single", "assembly"]

    _current_mode = st.session_state.get("app_mode", _allowed_modes[0])
    if _current_mode not in _allowed_modes:
        st.session_state["app_mode"] = _allowed_modes[0]

    _mode_btn_style = """
    <style>
    div[data-testid="stRadio"] > label { display: none; }
    div[data-testid="stRadio"] > div {
        display: flex; flex-direction: column; gap: 0.4em;
    }
    div[data-testid="stRadio"] > div > label {
        display: flex !important;
        align-items: center;
        background: #f0f4ff;
        border: 1.5px solid #c7d7fb;
        border-radius: 0.5em;
        padding: 0.65em 1em;
        font-size: 1.05em;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.15s;
        width: 100%;
    }
    div[data-testid="stRadio"] > div > label:hover {
        background: #dce8ff; border-color: #4a86e8;
    }
    div[data-testid="stRadio"] > div > label[data-checked="true"],
    div[data-testid="stRadio"] > div > label:has(input:checked) {
        background: #0d6efd;
        border-color: #0d6efd;
        color: white;
        box-shadow: 0 2px 6px rgba(13,110,253,0.3);
    }
    </style>
    """
    st.markdown(_mode_btn_style, unsafe_allow_html=True)
    if len(_allowed_modes) == 1:
        st.info(
            "🔒 מצב עבודה פעיל: "
            + ("🔍 שרטוט בודד" if _allowed_modes[0] == "single" else "🧩 מכלולים מרובים")
        )
        st.session_state["app_mode"] = _allowed_modes[0]
    else:
        st.radio(
            "מצב עבודה",
            options=_allowed_modes,
            index=0 if st.session_state.get("app_mode", "single") == _allowed_modes[0] else 1,
            format_func=lambda x: "🔍  שרטוט בודד" if x == "single" else "🧩  מכלולים מרובים",
            key="app_mode",
            label_visibility="collapsed",
        )

    st.divider()

    st.caption("⚙️ הגדרות מערכת נמצאות בפאנל מנהל")

    st.divider()

    # ─── אודות ───
    with st.expander("ℹ️ אודות AIDrawAnalyser", expanded=False):
        st.markdown(
            """
            **AIDrawAnalyser v1.0**

            ניתוח אוטומטי של שרטוטים טכניים:

            - 🔍 **שרטוט בודד** — ניתוח מלא של PDF יחיד
            - 🧩 **מכלולים מרובים** — ניתוח קשרי אבא/בן
            - 🤖 מנוע **Azure OpenAI** (GPT-4o / GPT-5.4)
            - 📄 **OCR Fallback** אוטומטי
            - 💰 מעקב **עלויות** לכל שרטוט
            """
        )


# ═══════════════════════════════════════════════════════════════
# פאנל עלויות למנהל מערכת
# ═══════════════════════════════════════════════════════════════
@st.dialog("🛠️ פאנל מנהל מערכת", width="large")
def _show_admin_cost_panel():
    """פאנל מוסתר המציג את כל מידע העלויות והטוקנים."""
    # ב-Single mode: result. ב-Assembly mode: asm_results (מחבר כולם)
    r = st.session_state.get("result") or {}
    asm_results = st.session_state.get("asm_results") or []
    is_assembly = st.session_state.get("app_mode") == "assembly"

    st.markdown("#### 📊 עלויות מצטברות (כל השרטוטים שנותחו)")
    stats = get_aggregate_stats()
    if stats:
        a1, a2, a3 = st.columns(3)
        a1.metric("שרטוטים שנותחו", stats["count"])
        a2.metric("סה\"כ עלות", f"${stats['total_cost_usd']:.2f}")
        a3.metric("ממוצע לשרטוט", f"${stats['avg_cost_usd']:.4f}")
    else:
        st.caption("עדיין לא נותחו שרטוטים")

    st.divider()

    if is_assembly and asm_results:
        # ─── Assembly mode: עלות לכל שרטוט ───
        st.markdown("#### 🎯 עלויות סשן המכלול")
        total_usd = sum(
            (res.get("_cost_info") or {}).get("total_cost_usd", 0)
            for res in asm_results
        )
        total_ils = sum(
            (res.get("_cost_info") or {}).get("total_cost_ils", 0)
            for res in asm_results
        )
        t1, t2 = st.columns(2)
        t1.metric("💰 סה\"כ עלות $", f"${total_usd:.4f}")
        t2.metric("💱 סה\"כ בשקלים", f"₪{total_ils:.3f}")

        for res in asm_results:
            ci = res.get("_cost_info") or {}
            if not ci:
                continue
            fname = res.get("source_filename", "שרטוט")
            with st.expander(f"📄 {fname}", expanded=False):
                c1, c2, c3 = st.columns(3)
                c1.metric("💰 עלות $", f"${ci.get('total_cost_usd', 0):.4f}")
                c2.metric("💱 בשקלים", f"₪{ci.get('total_cost_ils', 0):.3f}")
                c3.metric(
                    "🔤 טוקנים",
                    f"{ci.get('input_tokens', 0):,} + {ci.get('output_tokens', 0):,}",
                )
                stages = ci.get("stages", [])
                if stages:
                    df = pd.DataFrame(stages)
                    cols = [c for c in ["stage", "model", "input_tokens", "output_tokens", "total_cost_usd"] if c in df.columns]
                    df = df[cols].rename(columns={
                        "stage": "שלב", "model": "מודל בפועל",
                        "input_tokens": "Input tokens",
                        "output_tokens": "Output tokens",
                        "total_cost_usd": "עלות $",
                    })
                    st.dataframe(df, use_container_width=True, hide_index=True)

    else:
        # ─── Single mode ───
        cost_info = r.get("_cost_info", {})
        if cost_info:
            st.markdown("#### 🎯 עלות השרטוט הנוכחי")
            c1, c2, c3 = st.columns(3)
            c1.metric("💰 עלות $", f"${cost_info.get('total_cost_usd', 0):.4f}")
            c2.metric("💱 בשקלים", f"₪{cost_info.get('total_cost_ils', 0):.3f}")
            c3.metric(
                "🔤 טוקנים",
                f"{cost_info.get('input_tokens', 0):,} + {cost_info.get('output_tokens', 0):,}",
            )

            st.markdown("##### פירוט לפי שלב")
            stages = cost_info.get("stages", [])
            if stages:
                df = pd.DataFrame(stages)
                cols = [c for c in ["stage", "model", "input_tokens", "output_tokens", "total_cost_usd"] if c in df.columns]
                df = df[cols]
                col_map = {
                    "stage": "שלב",
                    "model": "מודל בפועל",
                    "input_tokens": "Input tokens",
                    "output_tokens": "Output tokens",
                    "total_cost_usd": "עלות $",
                }
                df = df.rename(columns=col_map)
                st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.caption("אין נתוני עלויות לשרטוט הנוכחי")

    st.divider()
    st.markdown("#### ⚙️ הגדרות מערכת (מנהל)")

    _current_model = _active_model()
    _model_idx = SUPPORTED_MODELS.index(_current_model) if _current_model in SUPPORTED_MODELS else 0
    _model_label = {
        MODEL_GPT_4O: "🟢 GPT-4o Vision (פשוט, מהיר)",
        MODEL_GPT_5_4: "🧠 GPT-5.4 (Reasoning, חזק)",
    }

    cset1, cset2 = st.columns([2, 1])
    with cset1:
        _new_model = st.radio(
            "מודל AI פעיל",
            options=list(SUPPORTED_MODELS),
            index=_model_idx,
            format_func=lambda x: _model_label.get(x, x),
            key="admin_active_model",
        )
    with cset2:
        _new_fb = st.checkbox(
            "Fallback אוטומטי",
            value=is_fallback_enabled(),
            key="admin_fallback",
            help="מעבר אוטומטי למודל השני אם הראשי נכשל",
        )

    _current_modes = enabled_modes()
    _mode_options = ["single", "assembly"]
    _new_modes = st.multiselect(
        "גישה למצבי עבודה",
        options=_mode_options,
        default=[m for m in _current_modes if m in _mode_options] or _mode_options,
        format_func=lambda x: "🔍 שרטוט בודד" if x == "single" else "🧩 מכלולים מרובים",
        key="admin_enabled_modes",
        help="בחר אילו מצבים יוצגו למשתמש בממשק",
    )

    if not _new_modes:
        st.error("חובה לבחור לפחות מצב עבודה אחד")
    else:
        _settings_changed = (
            _new_model != _current_model
            or _new_fb != is_fallback_enabled()
            or set(_new_modes) != set(_current_modes)
        )
        if _settings_changed:
            if st.button("💾 שמור הגדרות מערכת", use_container_width=True):
                save_runtime_settings(
                    active_model=_new_model,
                    fallback_enabled=_new_fb,
                    enabled_modes=_new_modes,
                )
                if st.session_state.get("app_mode") not in _new_modes:
                    st.session_state["app_mode"] = _new_modes[0]
                st.success("✅ הגדרות נשמרו")
                st.rerun()
        else:
            st.caption("אין שינויים להגדרה")

    # ─── ניהול cache ───
    st.divider()
    st.markdown("#### 🗄️ ניהול Cache")
    from core.drawing_cache import (
        CACHE_VERSION,
        cache_stats,
        cleanup_stale_cache,
        clear_cache,
    )
    _stats = cache_stats()
    cs1, cs2, cs3 = st.columns(3)
    cs1.metric("גרסה נוכחית", CACHE_VERSION)
    cs2.metric("קבצים", _stats.get("count", 0))
    cs3.metric("נפח", f"{_stats.get('size_mb', 0):.1f}MB")
    cb1, cb2 = st.columns(2)
    with cb1:
        if st.button("🧹 נקה גרסאות ישנות", use_container_width=True,
                     help="מוחק קבצי cache מ-CACHE_VERSIONים קודמים — שומר רק את הנוכחית"):
            removed = cleanup_stale_cache(keep_versions=1)
            st.success(f"✅ נמחקו {removed} קבצים מגרסאות ישנות")
            st.rerun()
    with cb2:
        if st.button("🗑️ מחק את כל ה-cache", use_container_width=True,
                     help="⚠️ הרצות הבאות יקראו ל-Azure מחדש לכל שרטוט (יקר)"):
            removed = clear_cache()
            st.warning(f"⚠️ נמחקו {removed} קבצים — הרצות הבאות = הוצאה מלאה")
            st.rerun()

    st.divider()
    if st.button("סגור", use_container_width=True):
        st.session_state["_show_admin"] = False
        st.rerun()


if st.session_state.get("_show_admin"):
    # מאפסים מיד את הדגל כדי שהדיאלוג ייפתח פעם אחת בלבד
    st.session_state["_show_admin"] = False
    _show_admin_cost_panel()


# ═══════════════════════════════════════════════════════════════
# פאנל ניהול לקוחות — CRUD ל-customer_mappings.json
# ═══════════════════════════════════════════════════════════════
@st.dialog("👥 ניהול לקוחות", width="large")
def _show_customer_manager_dialog():
    """ניהול CAGE / aliases / P/N prefixes / spec patterns לכל לקוח —
    בלי לערוך JSON ידנית ובלי restart לאפליקציה."""
    from core._customer_data import (
        delete_customer,
        empty_customer_record,
        get_customer_record,
        list_customers,
        upsert_customer,
    )

    st.info(
        "💡 **חשוב לדעת:** הרשימה הזו היא **עוזר** — לא חובה. "
        "האפליקציה תעבוד גם בלי שום לקוח מוגדר. "
        "כל לקוח שמוגדר משפר דיוק ב-3 דרכים: השלמת שם לקוח מקוד CAGE, "
        "נירמול ואריאציות שמות, וזיהוי תקנים פנימיים של הלקוח כדי לא לסמן "
        "אותם כהזיה. **אין הגבלה על מספר לקוחות.**"
    )

    # ─── עזרה ודוגמה מלאה ───
    with st.expander("📖 איך למלא? דוגמה מלאה", expanded=False):
        st.markdown("""
**דוגמה — לקוח בדיוני "ACME Aerospace Inc.":**

| שדה | ערך לדוגמה | מתי משמש |
|---|---|---|
| **שם קנוני** | `ACME Aerospace Inc.` | מופיע ככה בדוחות PDF/Excel |
| **קודי CAGE** | `AC001` ⏎ `AC002` (שורה לקוד) | אם השרטוט מציג רק "CAGE: AC001" → המערכת תשלים customer ל-"ACME Aerospace Inc." |
| **CAGE ברירת מחדל** | `AC001` | הקוד הנפוץ — משמש כשיש customer אבל אין CAGE |
| **Aliases (ואריאציות)** | `ACME` ⏎ `ACME AEROSPACE` ⏎ `ACME AEROSPACE INC` | אם המודל קורא "ACME" — נירמול ל-"ACME Aerospace Inc." |
| **קידומות P/N** | `AC` ⏎ `ACR` | אם P/N מתחיל ב-"AC-12345" → המערכת מסיקה שזה ACME |
| **Spec patterns** | `^AC-\\d{4}` ⏎ `^ACR-[A-Z]{2}\\d+` | תקנים פנימיים של הלקוח — לא יסומנו כ"הזיית תקן" |

**הערות:**
- **כל השדות אופציונליים** חוץ משם.
- ערכים יישמרו ב-uppercase אוטומטית (חוץ מ-spec patterns).
- ה-Spec patterns הם Python regex רגילים — `\\d` = ספרה, `[A-Z]` = אות גדולה, `^` = תחילת המחרוזת.
- Aliases — מומלץ לכתוב בלי פיסוק (לא "Acme, Inc." אלא "ACME INC").
""")

    customers = list_customers()
    new_option = "➕ הוסף לקוח חדש"
    options = [new_option, *customers]

    selected = st.selectbox(
        f"בחרי לקוח לעריכה ({len(customers)} מוגדרים · אין הגבלה על הוספה)",
        options=options,
        key="cm_selected",
    )

    is_new = selected == new_option
    if is_new:
        record = empty_customer_record()
        original_name = None
    else:
        record = get_customer_record(selected)
        original_name = selected

    # ─── טופס עריכה ───
    with st.form(key="cm_form", border=True):
        st.markdown("#### 📝 פרטי לקוח")
        if is_new:
            st.caption(
                "💬 ממלאים את השדות לפי הדוגמה למעלה. שם הלקוח חובה — השאר אופציונלי."
            )

        new_name = st.text_input(
            "שם קנוני של הלקוח (חובה — יופיע בדוחות) *",
            value=record.get("name", ""),
            key="cm_name",
            placeholder="ACME Aerospace Inc.",
            help="שם רשמי כפי שתרצי שיופיע בדוחות. למשל: 'ACME Aerospace Inc.'",
        )

        col_cage, col_default = st.columns([2, 1])
        with col_cage:
            cage_codes_str = st.text_area(
                "קודי CAGE (אופציונלי — אחד בשורה, 3-6 תווים אלפאנומריים)",
                value="\n".join(record.get("cage_codes", [])),
                key="cm_cages",
                height=110,
                placeholder="AC001\nAC002\nAC003",
                help="קוד CAGE רשמי של הלקוח. לדוגמה: 1931 (RAFAEL), 0772A (Elop).",
            )
        with col_default:
            default_cage = st.text_input(
                "CAGE ברירת מחדל (אופציונלי)",
                value=record.get("default_cage", ""),
                key="cm_default_cage",
                placeholder="AC001",
                help="ה-CAGE הנפוץ ביותר של הלקוח. משמש כש-customer ידוע אבל CAGE חסר.",
            )

        aliases_str = st.text_area(
            "ואריאציות / aliases (אופציונלי — אחד בשורה, באותיות גדולות בלי פיסוק)",
            value="\n".join(record.get("aliases", [])),
            key="cm_aliases",
            height=90,
            placeholder="ACME\nACME AEROSPACE\nACME AEROSPACE INC",
            help=(
                "שמות שונים שהמודל עלול להחזיר ושצריכים לתרגם לשם הקנוני. "
                "למשל: 'RAFAEL' → 'RAFAEL Advanced Defense Systems Ltd.'."
            ),
        )

        prefixes_str = st.text_area(
            "קידומות P/N (אופציונלי — אחד בשורה)",
            value="\n".join(record.get("pn_prefixes", [])),
            key="cm_prefixes",
            height=90,
            placeholder="AC\nACR",
            help=(
                "אם P/N מתחיל באחת הקידומות האלה — נחשב כשייך ללקוח. "
                "לדוגמה: BAS = BIRD Aerosystems."
            ),
        )

        patterns_str = st.text_area(
            "Regex patterns לתקנים פנימיים (אופציונלי — אחד בשורה, Python regex)",
            value="\n".join(record.get("spec_patterns", [])),
            key="cm_patterns",
            height=90,
            placeholder=r"^AC-\d{4}" + "\n" + r"^ACR-[A-Z]{2}\d+",
            help=(
                "תקנים שהמודל יכול לזהות שלא בטעות (לא הזיה). "
                r"למשל: '^I-\d{5,7}' לתקן פנימי של KRETOS. "
                "כל שורה היא Python regex (\\d=ספרה, [A-Z]=אות גדולה, ^=תחילה)."
            ),
        )

        col_save, col_del, col_cancel = st.columns([1, 1, 1])
        with col_save:
            submit_save = st.form_submit_button(
                "💾 שמור",
                use_container_width=True,
                type="primary",
            )
        with col_del:
            submit_del = st.form_submit_button(
                "🗑️ מחק לקוח" if not is_new else "מחק (לא זמין)",
                use_container_width=True,
                disabled=is_new,
            )
        with col_cancel:
            submit_cancel = st.form_submit_button(
                "❌ סגור בלי שינוי",
                use_container_width=True,
            )

    # ─── טיפול בלחיצות ───
    if submit_cancel:
        st.rerun()

    if submit_save:
        new_record = {
            "name": new_name,
            "cage_codes": [s.strip() for s in cage_codes_str.splitlines() if s.strip()],
            "default_cage": default_cage,
            "aliases": [s.strip() for s in aliases_str.splitlines() if s.strip()],
            "pn_prefixes": [s.strip() for s in prefixes_str.splitlines() if s.strip()],
            "spec_patterns": [
                s.strip() for s in patterns_str.splitlines() if s.strip()
            ],
        }
        try:
            upsert_customer(new_record, original_name=original_name)
            st.success(f"✅ נשמר: {new_name}")
            st.session_state["cm_selected"] = new_name
            st.rerun()
        except (ValueError, TypeError, KeyError) as exc:
            st.error(f"❌ שגיאת ולידציה: {exc}")

    if submit_del and not is_new:
        try:
            delete_customer(original_name)
            st.success(f"🗑️ נמחק: {original_name}")
            st.session_state["cm_selected"] = new_option
            st.rerun()
        except (ValueError, TypeError, KeyError) as exc:
            st.error(f"❌ שגיאה במחיקה: {exc}")


if st.session_state.get("_show_customer_manager"):
    st.session_state["_show_customer_manager"] = False
    _show_customer_manager_dialog()


# ═══════════════════════════════════════════════════════════════
# פאנל סטטיסטיקות — היסטוריית ניתוחים + עלויות
# ═══════════════════════════════════════════════════════════════
@st.dialog("📊 סטטיסטיקות וניתוחים אחרונים", width="large")
def _show_stats_dashboard_dialog():
    """דף עם 2 טאבים: היסטוריה (ניתוחים אחרונים) + עלויות (גרפים + ROI)."""
    from core.history import (
        aggregate_stats,
        clear_history,
        read_history,
    )

    history_records = read_history(limit=200)
    stats = aggregate_stats(history_records)

    # Hero metrics
    if stats["count"] > 0:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("ניתוחים", stats["count"])
        m2.metric("סה\"כ עלות", f"${stats['total_cost_usd']:.2f}")
        m3.metric("ממוצע לניתוח", f"${stats['avg_cost_usd']:.4f}")
        m4.metric("Cache hit rate", f"{stats['cache_hit_rate']*100:.0f}%",
                  help="אחוז ניתוחים שנטענו מ-cache במקום קריאה ל-Azure (חיסכון)")
    else:
        st.info("📥 עוד לא בוצעו ניתוחים. הקובץ history יתעדכן אחרי הניתוח הראשון.")

    tab_history, tab_costs, tab_roi = st.tabs([
        "📋 ניתוחים אחרונים",
        "💰 פילוח עלויות",
        "📈 ROI Calculator",
    ])

    # ═══ TAB 1: HISTORY ═══
    with tab_history:
        if not history_records:
            st.caption("אין רשומות. נסי לנתח שרטוט קודם.")
        else:
            st.caption(f"מציג {len(history_records)} רשומות אחרונות (מהחדש לישן)")
            rows = []
            for r in history_records:
                rows.append({
                    "תאריך": r.get("timestamp", "")[:19].replace("T", " "),
                    "מצב": "🔍 בודד" if r.get("mode") == "single" else "🧩 מכלול",
                    "P/N": r.get("part_number", "—"),
                    "שרטוטים": r.get("drawing_count", 1),
                    "אזהרות": r.get("warning_count", 0),
                    "עלות $": f"${r.get('cost_usd', 0):.4f}",
                    "Cache": "🎯" if r.get("cache_hit") else "🆕",
                    "Review": {
                        "reviewed": "✅",
                        "edited": "✏️",
                        "pending": "⏳",
                    }.get(r.get("review_status", "pending"), "⏳"),
                })
            st.dataframe(rows, use_container_width=True, hide_index=True)

            st.divider()
            cb1, cb2 = st.columns([1, 3])
            with cb1:
                if st.button("🗑️ נקה היסטוריה", use_container_width=True,
                             help="מוחק את output/history.jsonl. לא נוגע בקבצי תוצאות."):
                    n = clear_history()
                    st.warning(f"נמחקו {n} רשומות")
                    st.rerun()

    # ═══ TAB 2: COSTS ═══
    with tab_costs:
        if not history_records:
            st.caption("אין נתונים לפילוח.")
        else:
            # Cost over time
            from collections import defaultdict
            daily = defaultdict(lambda: {"cost": 0.0, "count": 0})
            for r in history_records:
                day = (r.get("timestamp") or "")[:10]  # YYYY-MM-DD
                if day:
                    daily[day]["cost"] += r.get("cost_usd", 0) or 0
                    daily[day]["count"] += 1
            if daily:
                df_rows = [
                    {"תאריך": d, "עלות $": round(v["cost"], 4),
                     "ניתוחים": v["count"]}
                    for d, v in sorted(daily.items())
                ]
                st.markdown("#### 📅 עלות יומית")
                st.dataframe(df_rows, use_container_width=True, hide_index=True)

                # Chart
                try:
                    import pandas as _pd
                    chart_df = _pd.DataFrame(df_rows).set_index("תאריך")
                    st.bar_chart(chart_df["עלות $"])
                except Exception:
                    pass

            # By mode
            st.markdown("#### 🧭 פילוח לפי מצב")
            mode_rows = [
                {"מצב": "🔍 שרטוט בודד", "ניתוחים": stats["by_mode"].get("single", 0)},
                {"מצב": "🧩 מכלולים", "ניתוחים": stats["by_mode"].get("assembly", 0)},
            ]
            st.dataframe(mode_rows, use_container_width=True, hide_index=True)

            # By review status
            st.markdown("#### ✏️ פילוח לפי סטטוס Review")
            rs = stats["by_review_status"]
            rs_rows = [
                {"סטטוס": "✅ אושר", "ניתוחים": rs.get("reviewed", 0)},
                {"סטטוס": "✏️ נערך", "ניתוחים": rs.get("edited", 0)},
                {"סטטוס": "⏳ ממתין", "ניתוחים": rs.get("pending", 0)},
            ]
            st.dataframe(rs_rows, use_container_width=True, hide_index=True)

    # ═══ TAB 3: ROI ═══
    with tab_roi:
        st.markdown("### 📈 חישוב ROI — חיסכון בזמן הנדסה")
        st.caption(
            "הנחת בסיס: ניתוח ידני של שרטוט מורכב לחילוץ כל השדות "
            "(P/N, חומר, תקנים, ציפויים, BOM, אריזה) לוקח 15-30 דקות "
            "להנדסאי מנוסה."
        )

        c1, c2 = st.columns(2)
        with c1:
            mins_per_drawing = st.slider(
                "דקות עבודה ידנית לשרטוט",
                min_value=5, max_value=60, value=20, step=5,
                key="roi_mins",
            )
        with c2:
            hourly_rate = st.number_input(
                "עלות שעה ($)",
                min_value=10, max_value=500, value=80, step=10,
                key="roi_rate",
            )

        n = stats["count"]
        if n > 0:
            saved_hours = n * mins_per_drawing / 60
            saved_money = saved_hours * hourly_rate
            ai_cost = stats["total_cost_usd"]
            net_savings = saved_money - ai_cost
            roi_x = saved_money / ai_cost if ai_cost > 0 else float("inf")

            r1, r2, r3, r4 = st.columns(4)
            r1.metric("שעות שנחסכו", f"{saved_hours:.1f}")
            r2.metric("חיסכון בעלות הנדסה", f"${saved_money:,.0f}")
            r3.metric("עלות AI מצטברת", f"${ai_cost:.2f}")
            r4.metric(
                "ROI (חיסכון נטו)",
                f"${net_savings:,.0f}",
                delta=f"×{roi_x:.0f}" if ai_cost > 0 else "∞",
            )

            st.success(
                f"💡 על {n} ניתוחים: חסכת ~{saved_hours:.0f} שעות הנדסה "
                f"(~${saved_money:,.0f}), שילמת ${ai_cost:.2f} ל-AI, "
                f"רווח נטו: ${net_savings:,.0f}."
            )
        else:
            st.info("נצטרך ניתוח אחד לפחות כדי לחשב ROI.")


if st.session_state.get("_show_stats_dashboard"):
    st.session_state["_show_stats_dashboard"] = False
    _show_stats_dashboard_dialog()


# ═══════════════════════════════════════════════════════════════
# Diff View — השוואת שני שרטוטים (revision A → B)
# ═══════════════════════════════════════════════════════════════
@st.dialog("🔄 השווה שני שרטוטים", width="large")
def _show_diff_dialog():
    """העלאה של 2 קבצי JSON של ניתוחים → הצגת השינויים בין הגרסאות."""
    import json as _json

    from core.diff import diff_drawings, format_change_human

    st.caption(
        "💡 העלי שני קבצי JSON של ניתוחים שמורים מתוך `output/`. "
        "המערכת תציג בדיוק מה השתנה בין הגרסאות — לפי קטגוריה."
    )

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("##### גרסה ישנה (A)")
        file_a = st.file_uploader(
            "JSON #1", type=["json"], key="diff_a",
            label_visibility="collapsed",
        )
    with col_b:
        st.markdown("##### גרסה חדשה (B)")
        file_b = st.file_uploader(
            "JSON #2", type=["json"], key="diff_b",
            label_visibility="collapsed",
        )

    if not (file_a and file_b):
        st.info(
            "👆 העלי 2 קבצי JSON של ניתוחים. "
            "טיפ: קבצי `output/<P/N>_<timestamp>.json` נוצרים אחרי כל ניתוח."
        )
        return

    try:
        a = _json.loads(file_a.read().decode("utf-8"))
        b = _json.loads(file_b.read().decode("utf-8"))
    except (UnicodeDecodeError, _json.JSONDecodeError) as exc:
        st.error(f"❌ שגיאה בקריאת JSON: {exc}")
        return

    # If files contain "drawings" key (assembly mode JSON), pick first drawing
    if isinstance(a, dict) and "drawings" in a and isinstance(a["drawings"], list):
        a = a["drawings"][0] if a["drawings"] else {}
    if isinstance(b, dict) and "drawings" in b and isinstance(b["drawings"], list):
        b = b["drawings"][0] if b["drawings"] else {}

    if not (isinstance(a, dict) and isinstance(b, dict)):
        st.error("❌ הקבצים לא במבנה המצופה (dict של ניתוח שרטוט).")
        return

    diff = diff_drawings(a, b)
    summary = diff["summary"]

    if summary["total_changes"] == 0:
        st.success(
            f"✅ אין שינויים בין '{summary['a_label']}' ל-'{summary['b_label']}'. "
            "הגרסאות זהות לחלוטין."
        )
        return

    st.markdown(
        f"### 🔄 {summary['a_label']}  →  {summary['b_label']}"
    )
    st.markdown(
        f"**סה\"כ שינויים: {summary['total_changes']}** "
        f"בקטגוריות: {', '.join(summary['categories_changed'])}"
    )
    st.divider()

    cat_he = {
        "identity": "🆔 זיהוי", "material": "🧱 חומר", "weights": "⚖️ משקלים",
        "role": "🧭 תפקיד וכמות", "machining": "🔧 עיבוד שבבי",
        "welding": "🔥 ריתוך", "heat_treatment": "🌡️ טיפול חום",
        "coating": "🎨 ציפויים", "painting": "🖌️ צביעות",
        "ndt": "🔬 NDT", "inspection": "🔍 בדיקות",
        "final_approval": "✅ אישור סופי", "additional": "🛠️ תהליכים נוספים",
        "standards": "📜 תקנים", "packaging": "📦 אריזה",
        "notes": "📝 הערות", "bom": "📋 BOM",
    }

    for category, changes in diff["changes_by_category"].items():
        with st.expander(
            f"{cat_he.get(category, category)} ({len(changes)} שינויים)",
            expanded=(category in ("identity", "material", "standards")),
        ):
            for ch in changes:
                ctype = ch["type"]
                color = {
                    "added": "#198754",
                    "removed": "#dc3545",
                    "modified": "#fd7e14",
                }.get(ctype, "#6c757d")
                st.markdown(
                    f'<div style="border-right:3px solid {color}; '
                    f'padding:0.4em 0.8em; margin-bottom:0.3em; '
                    f'background:#f8f9fa; border-radius:0.3em;">'
                    f'{format_change_human(ch)}</div>',
                    unsafe_allow_html=True,
                )


if st.session_state.get("_show_diff"):
    st.session_state["_show_diff"] = False
    _show_diff_dialog()


# ═══════════════════════════════════════════════════════════════
# סרגל צד תחתון משותף — מנהל + קבצים שמורים
# ═══════════════════════════════════════════════════════════════
def _render_sidebar_footer():
    with st.sidebar:
        st.divider()
        st.markdown("### 📊 פאנל מנהל")
        if st.button("🛠️ פתח פאנל מנהל", use_container_width=True,
                     key="open_admin_btn"):
            st.session_state["_show_admin"] = True
            st.rerun()
        if st.button("👥 ניהול לקוחות", use_container_width=True,
                     key="open_customer_manager_btn",
                     help="ניהול CAGE codes / aliases / P/N prefixes / spec patterns "
                          "לכל לקוח שלך — נשמר לקובץ customer_mappings.json"):
            st.session_state["_show_customer_manager"] = True
            st.rerun()
        if st.button("📊 סטטיסטיקות וניתוחים", use_container_width=True,
                     key="open_stats_btn",
                     help="היסטוריית ניתוחים + פילוח עלויות + ROI calculator"):
            st.session_state["_show_stats_dashboard"] = True
            st.rerun()
        if st.button("🔄 השווה שני שרטוטים", use_container_width=True,
                     key="open_diff_btn",
                     help="השוואה בין שני קבצי JSON של ניתוחים — מציג מה "
                          "השתנה בין revision A ל-B"):
            st.session_state["_show_diff"] = True
            st.rerun()


# ═══════════════════════════════════════════════════════════════
# באנר מצב עבודה — צבע שונה לכל מצב
# ═══════════════════════════════════════════════════════════════
_mode = st.session_state.get("app_mode", "single")
if _mode == "assembly":
    _banner_class = "mode-banner-assembly"
    _banner_icon = "🧩"
    _banner_title = "מצב מכלולים מרובים"
    _banner_tag = "ניתוח קבוצת שרטוטים + קשרי אבא/בן"
else:
    _banner_class = "mode-banner-single"
    _banner_icon = "🔍"
    _banner_title = "מצב שרטוט בודד"
    _banner_tag = "ניתוח מלא של PDF יחיד"

st.markdown(
    f'<div class="mode-banner {_banner_class}">'
    f'<div class="mode-title">{_banner_icon} {_banner_title}</div>'
    f'<div class="mode-tagline">{_banner_tag}</div>'
    f'</div>'
    f'<script>document.body.setAttribute("data-mode","{_mode}");</script>',
    unsafe_allow_html=True,
)


# ═══════════════════════════════════════════════════════════════
# ניתוב למצב מכלולים (Assembly)
# ═══════════════════════════════════════════════════════════════
if st.session_state.get("app_mode") == "assembly":
    from ui_assembly import render_assembly_mode
    render_assembly_mode(OUTPUT_DIR)
    _render_sidebar_footer()
    st.stop()


if "result" not in st.session_state:
    st.session_state.result = None
if "filename" not in st.session_state:
    st.session_state.filename = None

# ─────────────────────────────────────
# Empty state — מסך הסבר לפני שיש תוצאה
# ─────────────────────────────────────
if not st.session_state.result:
    with st.container(border=True):
        st.markdown(
            '<div dir="rtl" style="text-align:right;">'
            '<div style="font-size:1.25em; font-weight:700; color:#0d6efd; '
            'margin-bottom:0.4em;">נתחי שרטוט PDF והפיקי דוח ייצור</div>'
            '<div style="color:#495057; line-height:1.7;">'
            '• חילוץ אוטומטי של P/N, חומר, תקנים, ציפויים, צביעה ובדיקות.<br>'
            '• אזהרות ולידציה אוטומטיות לערכים חשודים (RAL, מותגי צבע, אריזה).<br>'
            '• Review ידני של שדות מרכזיים לפני ייצוא — שמירה על אמון.<br>'
            '• ייצוא לדוח HTML (Ctrl+P → Save as PDF), Excel רב-גיליוני או JSON.'
            '</div></div>',
            unsafe_allow_html=True,
        )

    with st.expander("🎓 איך זה עובד? (3 שלבים)", expanded=False):
        st.markdown(
            """
            <div dir="rtl" style="text-align:right; line-height:1.8;">
            <div style="background:#e7f1ff; padding:0.6em 0.9em; border-radius:0.4em;
                        border-right:4px solid #0d6efd; margin-bottom:0.5em;">
              <b>1️⃣ העלאה</b> — גררי קובץ PDF של שרטוט הנדסי
              (עד 20MB, עד 20 עמודים). או לחצי <b>'🎬 טען דוגמה'</b> כדי לראות
              תוצאה מוכנה ללא Azure.
            </div>
            <div style="background:#e7f1ff; padding:0.6em 0.9em; border-radius:0.4em;
                        border-right:4px solid #0d6efd; margin-bottom:0.5em;">
              <b>2️⃣ ניתוח אוטומטי (20-40 שניות)</b> — Azure OpenAI
              מחלץ P/N, drawing number, גרסה, לקוח, חומר, BOM, ציפויים,
              צביעה, בדיקות, תקנים, הערות ואריזה. ולידציות אוטומטיות מסמנות
              ערכים חשודים.
            </div>
            <div style="background:#e7f1ff; padding:0.6em 0.9em; border-radius:0.4em;
                        border-right:4px solid #0d6efd;">
              <b>3️⃣ Review וייצוא</b> — עברי על השדות, תקני אם צריך,
              ולחצי "אשר תוצאה". אז תוכלי לייצא HTML / Excel / JSON.
            </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

# ─────────────────────────────────────
# העלאת קובץ + אפשרויות
# ─────────────────────────────────────
st.markdown("### 1️⃣ העלה שרטוט PDF")

with st.container(border=True):
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

    # ─── Demo Mode — מציג תוצאה לדוגמה ללא קריאה ל-Azure ───
    if not st.session_state.result:
        st.divider()
        col_demo_btn, col_demo_caption = st.columns([1, 2])
        with col_demo_btn:
            if st.button("🎬 טען דוגמה", use_container_width=True,
                         key="load_demo_single",
                         help="טוען תוצאת ניתוח שמורה — בלי קריאה ל-Azure ובלי קובץ אמיתי"):
                st.session_state.result = get_demo_result()
                st.session_state.filename = DEMO_FILENAME
                for k in ("single_html_path", "single_xlsx_path", "single_json_path"):
                    st.session_state.pop(k, None)
                st.rerun()
        with col_demo_caption:
            st.caption(
                "אין לך עדיין שרטוט להעלות? לחצי 'טען דוגמה' "
                "כדי לראות איך נראית תוצאה מלאה (פריט ACME-12345)."
            )

    if uploaded_file is not None:
        temp_path = OUTPUT_DIR / f"_temp_{uploaded_file.name}"
        with open(temp_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

        st.session_state.filename = uploaded_file.name

        if st.button("🔍 נתח שרטוט", type="primary",
                     use_container_width=True):
            with st.status("🔄 מנתח... (עשוי לקחת 20-40 שניות)",
                           expanded=True) as status_box:
                step_log: list[str] = []

                def _on_step(i: int, name: str) -> None:
                    step_log.append(f"[{i}/7] {name}")
                    status_box.update(label=f"שלב {i}/7 · {name}")
                    status_box.write(name)

                try:
                    result = extract_assembly_drawing(
                        temp_path, progress_callback=_on_step,
                    )
                    st.session_state.result = result
                    status_box.update(label="✅ ניתוח הושלם", state="complete")
                    # log to history + audit (best-effort, silent on failure)
                    try:
                        cost = (result.get("_cost_info") or {}).get("total_cost_usd", 0)
                        cache_hit = (cost == 0)
                        append_history(
                            filename=uploaded_file.name,
                            mode="single",
                            part_number=result.get("part_number") or "",
                            drawing_count=1,
                            warning_count=len(result.get("_validation_warnings") or []),
                            cost_usd=cost,
                            cache_hit=cache_hit,
                        )
                        audit.log_extract(
                            uploaded_file.name,
                            model=get_deployment(),
                            cost_usd=cost,
                            cache_hit=cache_hit,
                            mode="single",
                        )
                    except Exception:
                        logger.warning("history logging failed", exc_info=True)
                except Exception as e:
                    logger.exception("Drawing extraction failed")
                    level = get_streamlit_level(e)
                    getattr(st, level)(format_error_for_ui(e, include_technical=True))
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

    # ─── באנר OCR בלבד (עלויות מוסתרות למנהל) ───
    if ocr_used:
        st.info("🔍 OCR הופעל כגיבוי לניתוח")

    st.markdown("### 2️⃣ תוצאות הניתוח")

    # ─── תקציר החלטה בראש המסך ───
    render_summary_card(r, demo=is_demo_result(r))

    # ─── תצוגה מלאה בטאבים ───
    render_drawing_tabs(r)
    _asm_render_validation_warnings(r)
    _asm_render_stage_model_feedback(
        cost_info,
        title="🤖 מודל בפועל בשלבי ניתוח השרטוט",
        expanded=False,
    )

    # ─────────────────────────────────────
    # 2.5 — Review / Edit לפני export
    # ─────────────────────────────────────
    st.divider()
    st.markdown("### 3️⃣ Review ואישור")
    render_review_edit_form(r, key_prefix="single_review")

    # ─────────────────────────────────────
    # שמירה — דוחות וייצוא (חסום עד אישור)
    # ─────────────────────────────────────
    st.divider()
    _approved = _get_review_status(r) == "reviewed"
    st.markdown("### 4️⃣ שמור תוצאה")
    if not _approved:
        st.warning(
            "⏳ הייצוא ייפתח אחרי אישור התוצאה למעלה. "
            "אם אין צורך בעריכה — לחצי 'אשר תוצאה לייצוא'."
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = Path(st.session_state.filename).stem
    single_list = [r]  # build_assembly_* עובדים עם list, גם לשרטוט בודד

    with st.expander("📦 הורדת קבצים (HTML / Excel / JSON)", expanded=_approved):
        if not _approved:
            st.caption("🔒 חסום עד אישור התוצאה למעלה.")
        tab_html, tab_xlsx, tab_json = st.tabs([
            "📄 דוח HTML",
            "📊 Excel מלא",
            "💾 JSON גולמי",
        ])

        with tab_html:
            st.caption(
                "דוח HTML מקיף: כותרת עם P/N ולקוח, חומר, תהליכים, "
                "ציפויים/צביעה, בדיקות, תקנים, NOTES. "
                "💡 לפתיחה — כפילי קליק על הקובץ. ל-PDF — בדפדפן Ctrl+P → 'Save as PDF'."
            )
            if not _approved:
                st.info("⏳ אישרי את התוצאה למעלה כדי לפתוח ייצוא HTML.")
            else:
                _render_export_pair(
                    button_label="📄 צור דוח HTML",
                    spinner_text="📄 מייצר דוח HTML...",
                    build_fn=lambda p: build_assembly_html(
                        single_list, None, p, single_mode=True
                    ),
                    out_path=OUTPUT_DIR / f"{base_name}_{timestamp}.html",
                    state_key="single_html_path",
                    mime="text/html",
                    btn_key="btn_single_html",
                    dl_key="dl_single_html",
                    err_label="HTML",
                )

        with tab_xlsx:
            st.caption("Excel רב-גיליונות: סיכום, BOM, עיבוד שבבי, ריתוך, "
                       "טיפול חום, ציפויים, צביעה, NDT, בדיקות, אישור סופי, "
                       "תקנים, תהליכים נוספים, עלויות.")
            if not _approved:
                st.info("⏳ אישרי את התוצאה למעלה כדי לפתוח ייצוא Excel.")
            else:
                _render_export_pair(
                    button_label="📊 צור Excel מלא",
                    spinner_text="📄 מייצר Excel...",
                    build_fn=lambda p: build_assembly_excel(
                        single_list, None, p, single_mode=True
                    ),
                    out_path=OUTPUT_DIR / f"{base_name}_{timestamp}.xlsx",
                    state_key="single_xlsx_path",
                    mime="application/vnd.openxmlformats-officedocument."
                         "spreadsheetml.sheet",
                    btn_key="btn_single_xlsx",
                    dl_key="dl_single_xlsx",
                    err_label="Excel",
                )

        with tab_json:
            st.caption("מבנה נתונים גולמי של הניתוח — מתאים לאינטגרציה, "
                       "debugging, או ייצוא ידני. JSON לא דורש אישור — "
                       "תמיד זמין למפתחים.")
            if st.button("💾 שמור JSON", use_container_width=True,
                         key="btn_single_json"):
                path = save_to_json(
                    r, OUTPUT_DIR / f"{base_name}_{timestamp}.json"
                )
                st.session_state["single_json_path"] = str(path)
                st.success(f"נשמר: `{path.name}`")

            _saved_json = st.session_state.get("single_json_path")
            if _saved_json and Path(_saved_json).exists():
                with open(_saved_json, "rb") as fh:
                    st.download_button(
                        label=f"⬇️ הורד {Path(_saved_json).name}",
                        data=fh.read(),
                        file_name=Path(_saved_json).name,
                        mime="application/json",
                        use_container_width=True,
                        key="dl_single_json",
                    )

    if st.button("🔄 שרטוט חדש", use_container_width=True,
                 key="single_new_drawing"):
        st.session_state.result = None
        st.session_state.filename = None
        # נקה נתיבי ייצוא כדי למנוע הצגת כפתור הורדה של שרטוט קודם
        for k in ("single_html_path", "single_xlsx_path", "single_json_path"):
            st.session_state.pop(k, None)
        st.rerun()

# ─────────────────────────────────────
# Sidebar — פאנל מנהל + קבצים שמורים
# ─────────────────────────────────────
_render_sidebar_footer()
