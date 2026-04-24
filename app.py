import os
import re
import subprocess
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from datetime import date, datetime, timezone

from pipeline import (
    build_all_from_api,
    load_snapshot,
    list_snapshots,
    save_snapshot,
    BASE_URL,
)
from config import (
    ONTOLOGY,
    CATEGORY_TO_BRANCH,
    ENTITY_TO_CATEGORY,
    HEME_CATEGORIES,
    SOLID_CATEGORIES,
    BASKET_MULTI_LABEL,
    HEME_BASKET_LABEL,
    SOLID_BASKET_LABEL,
    UNCLASSIFIED_LABEL,
    ENTITY_TERMS,
    CATEGORY_FALLBACK_TERMS,
    HEME_BASKET_TERMS,
    SOLID_BASKET_TERMS,
    EXCLUDED_INDICATION_TERMS,
    HARD_EXCLUDED_NCT_IDS,
    CAR_CORE_TERMS,
    CAR_NK_TERMS,
    CAAR_T_TERMS,
    CAR_TREG_TERMS,
    ALLOGENEIC_MARKERS,
    AUTOL_MARKERS,
    HEME_TARGET_TERMS,
    SOLID_TARGET_TERMS,
    DUAL_TARGET_LABELS,
    NAMED_PRODUCT_TARGETS,
    NAMED_PRODUCT_TYPES,
    AMBIGUOUS_ENTITY_TOKENS,
    AMBIGUOUS_TARGET_TOKENS,
    MODALITY_ORDER,
)

st.set_page_config(
    page_title="CAR-T Oncology Trials Monitor",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)

STATUS_OPTIONS = [
    "RECRUITING",
    "NOT_YET_RECRUITING",
    "ACTIVE_NOT_RECRUITING",
    "ENROLLING_BY_INVITATION",
    "COMPLETED",
    "TERMINATED",
    "SUSPENDED",
    "WITHDRAWN",
    "UNKNOWN",
]

STATUS_DISPLAY = {
    "RECRUITING":              "Recruiting",
    "NOT_YET_RECRUITING":      "Not yet recruiting",
    "ACTIVE_NOT_RECRUITING":   "Active, not recruiting",
    "ENROLLING_BY_INVITATION": "By invitation",
    "COMPLETED":               "Completed",
    "TERMINATED":              "Terminated",
    "SUSPENDED":               "Suspended",
    "WITHDRAWN":               "Withdrawn",
    "UNKNOWN":                 "Unknown",
}

OPEN_SITE_STATUSES = {
    "RECRUITING", "NOT_YET_RECRUITING",
    "ENROLLING_BY_INVITATION", "ACTIVE_NOT_RECRUITING",
}

PHASE_ORDER = [
    "EARLY_PHASE1", "PHASE1", "PHASE1|PHASE2",
    "PHASE2", "PHASE2|PHASE3", "PHASE3", "PHASE4", "Unknown",
]

PHASE_LABELS = {
    "EARLY_PHASE1": "Early Phase I",
    "PHASE1": "Phase I",
    "PHASE1|PHASE2": "Phase I/II",
    "PHASE2": "Phase II",
    "PHASE2|PHASE3": "Phase II/III",
    "PHASE3": "Phase III",
    "PHASE4": "Phase IV",
    "Unknown": "Unknown",
}

_PLATFORM_LABELS = {"CAR-NK", "CAR-Treg", "CAAR-T", "CAR-γδ T"}

# ---------------------------------------------------------------------------
# Approved CAR-T products — used for temporal overlay annotations
# ---------------------------------------------------------------------------
APPROVED_PRODUCTS = [
    {"year": 2017, "name": "tisa-cel (Kymriah)",    "target": "CD19", "branch": "Heme-onc"},
    {"year": 2017, "name": "axi-cel (Yescarta)",    "target": "CD19", "branch": "Heme-onc"},
    {"year": 2020, "name": "brexu-cel (Tecartus)",  "target": "CD19", "branch": "Heme-onc"},
    {"year": 2021, "name": "liso-cel (Breyanzi)",   "target": "CD19", "branch": "Heme-onc"},
    {"year": 2021, "name": "ide-cel (Abecma)",      "target": "BCMA", "branch": "Heme-onc"},
    {"year": 2022, "name": "cilta-cel (Carvykti)",  "target": "BCMA", "branch": "Heme-onc"},
    {"year": 2024, "name": "obe-cel (Aucatzyl)",    "target": "CD19", "branch": "Heme-onc"},
    {"year": 2025, "name": "eque-cel (Fucaso)",     "target": "BCMA", "branch": "Heme-onc"},
    {"year": 2025, "name": "zevor-cel",             "target": "BCMA", "branch": "Heme-onc"},
]

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------
THEME = {
    "bg":      "#ffffff",
    "surface": "#ffffff",
    "surf2":   "#f8fafc",
    "surf3":   "#e5e7eb",
    "text":    "#0b1220",
    "muted":   "#475569",
    "faint":   "#94a3b8",
    "border":  "#e5e7eb",
    "primary": "#0b3d91",
    "teal":    "#0f766e",
    "amber":   "#92400e",
    "shadow":  "none",
    "grid":    "#f1f5f9",
}

# Heme vs Solid palette (publication-ready; not the primary navy)
HEME_COLOR  = "#0b3d91"   # deep navy — heme stories
SOLID_COLOR = "#b45309"   # amber-700 — solid stories (complementary warm tone)
MIXED_COLOR = "#4f46e5"   # indigo
UNKNOWN_COLOR = "#94a3b8" # slate-400

BRANCH_COLORS = {
    "Heme-onc": HEME_COLOR,
    "Solid-onc": SOLID_COLOR,
    "Mixed": MIXED_COLOR,
    "Unknown": UNKNOWN_COLOR,
}

_MODALITY_COLORS: dict[str, str] = {}  # populated below once NEJM palette defined

px.defaults.template = "plotly_white"


def _modality(row) -> str:
    """Mechanistic modality bucket for each trial."""
    t = str(row.get("TargetCategory", ""))
    p = str(row.get("ProductType", ""))
    _txt = " ".join([
        str(row.get("BriefTitle", "")),
        str(row.get("BriefSummary", "")),
        str(row.get("Interventions", "")),
    ]).lower()
    has_gd_t = (
        "γδ" in _txt or "gamma delta" in _txt or "gamma-delta" in _txt
        or "-gdt" in _txt or " gdt " in _txt
    )
    has_nk = "car-nk" in _txt or "car nk" in _txt or t.startswith("CAR-NK")
    if has_nk:
        return "CAR-NK"
    if t == "CAAR-T":
        return "CAAR-T"
    if t == "CAR-Treg":
        return "CAR-Treg"
    if has_gd_t or t == "CAR-γδ T":
        return "CAR-γδ T"
    if p == "In vivo":
        return "In vivo CAR"
    if p == "Autologous":
        return "Auto CAR-T"
    if p == "Allogeneic/Off-the-shelf":
        return "Allo CAR-T"
    return "CAR-T (unclear)"


# ---------------------------------------------------------------------------
# CSS — NEJM-flat, light canvas
# ---------------------------------------------------------------------------

st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

    html, body, [class*="css"] {{
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        -webkit-font-smoothing: antialiased;
        -moz-osx-font-smoothing: grayscale;
    }}
    .stApp {{ background: {THEME["bg"]}; color: {THEME["text"]}; }}
    .block-container {{
        max-width: 1320px;
        padding-top: 1.2rem;
        padding-bottom: 2.4rem;
        line-height: 1.55;
    }}
    h1 {{ color: {THEME["text"]}; font-weight: 600; letter-spacing: -0.022em; line-height: 1.2; }}
    h2 {{ color: {THEME["text"]}; font-weight: 600; letter-spacing: -0.018em; line-height: 1.25; }}
    h3 {{ color: {THEME["text"]}; font-weight: 600; letter-spacing: -0.012em; line-height: 1.3; }}

    ::-webkit-scrollbar {{ width: 5px; height: 5px; }}
    ::-webkit-scrollbar-track {{ background: transparent; }}
    ::-webkit-scrollbar-thumb {{ background: {THEME["surf3"]}; border-radius: 3px; }}
    ::-webkit-scrollbar-thumb:hover {{ background: {THEME["faint"]}; }}

    .hero {{
        padding: 1.6rem 0 1.4rem;
        border-top: 3px solid {THEME["primary"]};
        border-bottom: 1px solid {THEME["border"]};
        background: transparent;
        margin-bottom: 1.4rem;
    }}
    .hero-eyebrow {{
        display: flex; align-items: center; gap: 0.5rem;
        font-size: 0.66rem; font-weight: 600;
        letter-spacing: 0.16em; text-transform: uppercase;
        color: {THEME["primary"]};
        margin-bottom: 0.55rem;
    }}
    .hero-eyebrow::before {{
        content: ''; display: inline-block;
        width: 18px; height: 1px;
        background: {THEME["primary"]}; flex-shrink: 0;
    }}
    .hero-title {{
        font-size: 1.7rem; font-weight: 600;
        letter-spacing: -0.022em; line-height: 1.2;
        color: {THEME["text"]}; margin-bottom: 0.55rem;
    }}
    .hero-sub {{
        font-size: 0.86rem; line-height: 1.6;
        color: {THEME["muted"]}; max-width: 820px;
        font-weight: 400;
    }}

    .section-card {{
        background: transparent; border: none;
        border-top: 1px solid {THEME["border"]};
        border-radius: 0; padding: 1.0rem 0 0.8rem;
        box-shadow: none; margin-bottom: 0.6rem;
    }}

    .metric-card {{
        background: transparent; border: none;
        border-top: 2px solid {THEME["primary"]};
        border-radius: 0; padding: 0.7rem 0.1rem 0.4rem;
        box-shadow: none;
    }}
    .metric-label {{
        font-size: 0.66rem; font-weight: 600;
        color: {THEME["muted"]}; letter-spacing: 0.12em;
        text-transform: uppercase; margin-bottom: 0.45rem;
    }}
    .metric-value {{
        font-size: 1.65rem; font-weight: 600;
        letter-spacing: -0.02em; color: {THEME["text"]};
        line-height: 1.05; font-variant-numeric: tabular-nums;
    }}
    .metric-foot {{
        margin-top: 0.35rem; font-size: 0.72rem;
        color: {THEME["faint"]}; font-weight: 400; line-height: 1.4;
    }}
    .small-note {{
        color: {THEME["muted"]}; font-size: 0.84rem;
        line-height: 1.6; margin-top: 0.3rem; margin-bottom: 0.55rem;
        letter-spacing: -0.01em;
    }}

    div[data-testid="stSidebar"] {{
        background: {THEME["surf2"]};
        border-right: 1px solid {THEME["border"]};
    }}
    [data-testid="stSidebar"] > div:first-child {{
        border-top: 2px solid {THEME["primary"]};
    }}
    div[data-testid="stSidebar"] h1,
    div[data-testid="stSidebar"] h2,
    div[data-testid="stSidebar"] h3 {{
        font-size: 0.59rem !important; font-weight: 700 !important;
        letter-spacing: 0.14em !important; text-transform: uppercase !important;
        color: {THEME["faint"]} !important;
        margin-top: 1.3rem !important; margin-bottom: 0.1rem !important;
        padding-top: 0.9rem !important; padding-bottom: 0.1rem !important;
        border-top: 1px solid {THEME["border"]} !important;
        border-bottom: none !important;
    }}
    div[data-testid="stSidebar"] label {{
        font-size: 0.73rem !important; font-weight: 500 !important;
        color: {THEME["muted"]} !important; letter-spacing: -0.01em !important;
    }}
    div[data-testid="stSidebar"] p {{ color: {THEME["text"]}; font-size: 0.75rem; }}
    div[data-testid="stSidebar"] div[data-baseweb="select"] > div {{
        background: {THEME["surface"]} !important;
        border: 1px solid {THEME["border"]} !important;
        border-radius: 2px !important;
        min-height: 28px !important; font-size: 0.75rem !important;
    }}
    div[data-testid="stSidebar"] div[data-baseweb="select"] > div:focus-within {{
        border-color: {THEME["primary"]} !important;
        box-shadow: none !important;
    }}
    div[data-testid="stSidebar"] div[data-testid="stRadio"] label {{
        border-radius: 0 !important; padding: 0.28rem 0.45rem !important;
        transition: background 0.1s !important; margin-bottom: 0.06rem !important;
    }}
    div[data-testid="stSidebar"] div[data-testid="stRadio"] label:hover {{
        background: {THEME["surface"]} !important;
    }}

    .stButton > button, .stDownloadButton > button {{
        background: {THEME["surface"]}; color: {THEME["text"]};
        border: 1px solid {THEME["border"]}; border-radius: 2px;
        padding: 0.42rem 0.95rem; font-size: 0.82rem; font-weight: 500;
        letter-spacing: -0.005em; box-shadow: none;
        transition: background 0.12s, border-color 0.12s;
    }}
    .stButton > button:hover, .stDownloadButton > button:hover {{
        background: {THEME["surf2"]}; border-color: {THEME["primary"]};
        box-shadow: none; color: {THEME["primary"]};
    }}

    div[data-testid="stTabs"] [data-baseweb="tab-list"] {{
        background: transparent; border: none;
        border-bottom: 1px solid {THEME["border"]};
        border-radius: 0; padding: 0; gap: 0;
    }}
    div[data-testid="stTabs"] [data-baseweb="tab"] {{
        border-radius: 0; padding: 10px 18px;
        font-size: 0.84rem; font-weight: 500;
        letter-spacing: -0.005em; color: {THEME["muted"]};
        background: transparent; border: none !important;
        border-bottom: 2px solid transparent !important;
        margin-bottom: -1px; transition: color 0.12s, border-color 0.12s;
    }}
    div[data-testid="stTabs"] [data-baseweb="tab"]:hover {{
        background: transparent; color: {THEME["text"]};
    }}
    div[data-testid="stTabs"] button[aria-selected="true"] {{
        background: transparent !important;
        color: {THEME["primary"]} !important; font-weight: 600 !important;
        border-bottom: 2px solid {THEME["primary"]} !important;
        box-shadow: none;
    }}
    div[data-testid="stTabs"] [data-baseweb="tab-highlight"],
    div[data-testid="stTabs"] [data-baseweb="tab-border"] {{
        display: none !important;
    }}

    div[data-testid="stDataFrame"] {{
        border: 1px solid {THEME["border"]}; border-radius: 2px;
        overflow: hidden; background: {THEME["surface"]};
    }}
    div[data-baseweb="select"] > div, div[data-baseweb="input"] > div {{
        background-color: {THEME["surface"]};
        border-color: {THEME["border"]} !important;
        color: {THEME["text"]}; border-radius: 2px;
    }}
    .stTextInput input, .stNumberInput input {{
        background: {THEME["surface"]};
        border-color: {THEME["border"]}; border-radius: 2px;
        color: {THEME["text"]};
    }}
    div[data-testid="stExpander"] {{
        background: transparent; border: none;
        border-top: 1px solid {THEME["border"]};
        border-radius: 0; box-shadow: none;
    }}
    div[data-baseweb="tag"] {{
        background-color: {THEME["surf2"]} !important;
        border: 1px solid {THEME["border"]} !important;
        border-radius: 2px !important;
    }}
    div[data-baseweb="tag"] span {{ color: {THEME["text"]} !important; font-weight: 500; }}
    div[data-baseweb="tag"] [role="button"] {{ color: {THEME["muted"]} !important; opacity: 0.8; }}

    div[data-testid="stMarkdownContainer"] p,
    div[data-testid="stMarkdownContainer"] li,
    div[data-testid="stMarkdownContainer"] span {{ color: {THEME["text"]}; }}
    div[data-testid="stCaptionContainer"] p, .stCaption {{ color: {THEME["muted"]} !important; }}
    div[data-testid="stAlert"] p {{ color: {THEME["text"]}; }}

    div[data-testid="stSidebarContent"] {{ background-color: {THEME["surface"]} !important; }}

    div[data-testid="stVerticalBlock"],
    div[data-testid="stHorizontalBlock"],
    div[data-testid="stColumn"] > div,
    div[data-testid="block-container"] > div,
    div[data-testid="element-container"] {{
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        border-radius: 0 !important;
    }}

    div[data-testid="stMetric"] {{
        background: transparent !important; border: none !important;
        box-shadow: none !important; padding: 0.4rem 0 !important;
        border-radius: 0 !important;
    }}
    div[data-testid="stMetricValue"] > div {{
        color: {THEME["text"]} !important;
        font-size: 1.4rem !important; font-weight: 600 !important;
        letter-spacing: -0.02em !important;
        font-variant-numeric: tabular-nums;
    }}
    div[data-testid="stMetricLabel"] > div {{
        color: {THEME["muted"]} !important;
        font-size: 0.7rem !important; font-weight: 600 !important;
        letter-spacing: 0.10em !important; text-transform: uppercase !important;
    }}

    div[data-testid="stAlert"] {{
        background: rgba(11,61,145,0.04) !important;
        border: 1px solid rgba(11,61,145,0.14) !important;
        border-left: 3px solid {THEME["primary"]} !important;
        border-radius: 8px !important;
        box-shadow: none !important;
    }}
    div[data-testid="stAlert"] p {{ color: {THEME["text"]} !important; }}

    div[data-testid="stVerticalBlock"] h3 {{
        margin-top: 0.5rem !important;
        padding-top: 1.1rem !important;
        padding-bottom: 0.55rem !important;
        border-top: 1px solid {THEME["border"]} !important;
        letter-spacing: -0.03em !important;
    }}

    .pub-fig-header {{
        margin-top: 1.6rem; padding-top: 1.1rem;
        padding-bottom: 0.55rem;
        border-top: 1px solid {THEME["border"]};
    }}
    .pub-fig-eyebrow {{
        font-size: 0.66rem; font-weight: 700;
        letter-spacing: 0.16em; text-transform: uppercase;
        color: {THEME["primary"]}; margin-bottom: 0.35rem;
    }}
    .pub-fig-title {{
        font-size: 1.05rem; font-weight: 600;
        letter-spacing: -0.012em; line-height: 1.3;
        color: {THEME["text"]}; margin-bottom: 0.2rem;
    }}
    .pub-fig-sub {{
        font-size: 0.78rem; font-weight: 400; line-height: 1.5;
        color: {THEME["muted"]}; margin-top: 0.15rem;
    }}
    .pub-fig-caption {{
        font-size: 0.72rem; font-style: italic;
        color: {THEME["faint"]};
        margin: 0.4rem 0 0.8rem 0; line-height: 1.45;
    }}
    .pub-fig-header + div h3,
    .pub-fig-header ~ div[data-testid="stVerticalBlock"] h3 {{
        border-top: none !important; padding-top: 0 !important;
    }}

    .metric-card {{ background: {THEME["surface"]} !important; }}
    div[data-testid="stDataFrame"],
    div[data-testid="stDataFrame"] > div {{
        background-color: {THEME["surface"]} !important;
    }}
    div[data-testid="stExpander"] {{
        background-color: {THEME["surface"]} !important;
        border: 1px solid {THEME["border"]} !important;
        border-radius: 8px !important;
        box-shadow: none !important;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Cached loaders
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60 * 60)
def load_live(max_records: int = 5000, statuses: tuple[str, ...] = ()) -> tuple:
    statuses_list = list(statuses) if statuses else None
    return build_all_from_api(max_records=max_records, statuses=statuses_list)


@st.cache_data
def load_frozen(snapshot_date: str) -> tuple:
    return load_snapshot(snapshot_date)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def metric_card(label: str, value, foot: str = ""):
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
            <div class="metric-foot">{foot}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def make_bar(df_plot, x, y, height=360, color=HEME_COLOR):
    fig = px.bar(
        df_plot, x=x, y=y, height=height,
        color_discrete_sequence=[color], template="plotly_white",
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=8, r=8, t=8, b=8),
        font=dict(family="Inter, sans-serif", size=12, color=THEME["text"]),
        xaxis_title=None, yaxis_title=None, showlegend=False, bargap=0.35,
    )
    fig.update_traces(marker_line_width=0, opacity=0.90)
    fig.update_xaxes(showgrid=False, color=THEME["muted"], tickfont_size=11)
    fig.update_yaxes(
        gridcolor=THEME["grid"], gridwidth=1,
        color=THEME["muted"], tickfont_size=11, zeroline=False,
    )
    fig.update_layout(bargap=0.4)
    return fig


def uniq_join(series):
    vals = []
    for v in series.dropna():
        v = str(v).strip()
        if v and v not in vals:
            vals.append(v)
    return " | ".join(vals)


def split_pipe_values(series: pd.Series) -> list[str]:
    values = []
    for item in series.dropna():
        for part in str(item).split("|"):
            part = part.strip()
            if part:
                values.append(part)
    return values


def normalize_phase_value(x):
    if pd.isna(x):
        return "Unknown"
    s = str(x).strip()
    if not s:
        return "Unknown"
    s_upper = s.upper().replace(" ", "").replace("/", "|")
    mapping = {
        "EARLYPHASE1": "EARLY_PHASE1", "EARLYPHASEI": "EARLY_PHASE1",
        "PHASE1": "PHASE1", "PHASEI": "PHASE1",
        "PHASE1|PHASE2": "PHASE1|PHASE2", "PHASEI|PHASEII": "PHASE1|PHASE2",
        "PHASE12": "PHASE1|PHASE2", "PHASE1PHASE2": "PHASE1|PHASE2",
        "PHASE2": "PHASE2", "PHASEII": "PHASE2",
        "PHASE2|PHASE3": "PHASE2|PHASE3", "PHASEII|PHASEIII": "PHASE2|PHASE3",
        "PHASE23": "PHASE2|PHASE3", "PHASE2PHASE3": "PHASE2|PHASE3",
        "PHASE3": "PHASE3", "PHASEIII": "PHASE3",
        "PHASE4": "PHASE4", "PHASEIV": "PHASE4",
        "N/A": "Unknown", "NA": "Unknown",
    }
    return mapping.get(s_upper, s_upper if s_upper in PHASE_ORDER else "Unknown")


def add_phase_columns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["Phase"] = out["Phase"].fillna("Unknown")
    out["PhaseNormalized"] = out["Phase"].apply(normalize_phase_value)
    out["PhaseOrdered"] = pd.Categorical(out["PhaseNormalized"], categories=PHASE_ORDER, ordered=True)
    out["PhaseLabel"] = out["PhaseNormalized"].map(PHASE_LABELS).fillna(out["Phase"])
    return out


# ---------------------------------------------------------------------------
# Hero
# ---------------------------------------------------------------------------

st.markdown(
    """
    <div class="hero">
        <div class="hero-eyebrow">ClinicalTrials.gov &middot; Live pipeline</div>
        <div class="hero-title">CAR-T &amp; Cell Therapies<br>in Oncology — Heme and Solid Tumors</div>
        <div class="hero-sub">
            Systematic landscape analysis of CAR-T, CAR-NK, CAAR-T, and CAR-γδ T trials
            across hematologic and solid tumors. Three-tier disease hierarchy
            (Branch → Category → Entity), target classification, approved-product
            overlays, Germany-specific site tracking, and publication-ready figures.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Sidebar — data source
# ---------------------------------------------------------------------------

st.sidebar.header("Data source")

available_snapshots = list_snapshots()
data_source = st.sidebar.radio(
    "Source",
    ["Live (ClinicalTrials.gov API)", "Frozen snapshot"],
    index=0 if not available_snapshots else 0,
)

prisma_counts: dict = {}

if data_source == "Frozen snapshot":
    if not available_snapshots:
        st.sidebar.warning("No snapshots found. Pull live data and save a snapshot first.")
        st.stop()
    selected_snapshot = st.sidebar.selectbox("Snapshot date", available_snapshots)
    with st.spinner(f"Loading frozen snapshot {selected_snapshot}..."):
        df, df_sites, prisma_counts = load_frozen(selected_snapshot)
    st.sidebar.caption(f"Loaded: {selected_snapshot} ({len(df)} trials)")
else:
    st.sidebar.header("Data pull")
    selected_statuses = st.sidebar.multiselect(
        "Statuses to pull",
        STATUS_OPTIONS,
        default=["RECRUITING", "NOT_YET_RECRUITING", "ACTIVE_NOT_RECRUITING"],
    )
    try:
        with st.spinner("Fetching and processing ClinicalTrials.gov data..."):
            df, df_sites, prisma_counts = load_live(statuses=tuple(selected_statuses))
    except Exception as api_err:
        st.sidebar.error(
            "ClinicalTrials.gov API is currently unreachable. "
            "Falling back to the most recent snapshot if available."
        )
        st.sidebar.caption(f"Error: {type(api_err).__name__}: {str(api_err)[:120]}")
        if available_snapshots:
            fallback = available_snapshots[0]
            with st.spinner(f"Loading snapshot {fallback}..."):
                df, df_sites, prisma_counts = load_frozen(fallback)
            st.sidebar.info(
                f"Loaded frozen snapshot **{fallback}** (fallback). "
                "Switch the source toggle above to 'Frozen snapshot' for intentional offline use."
            )
        else:
            st.error(
                "Cannot load data: the ClinicalTrials.gov API is unreachable and no local "
                "snapshots exist. Please try again later or check the API status at "
                "https://clinicaltrials.gov/."
            )
            st.stop()

    if st.sidebar.button("Save snapshot"):
        statuses_list = selected_statuses if selected_statuses else None
        snap_date = save_snapshot(df, df_sites, prisma_counts, statuses=statuses_list)
        st.sidebar.success(f"Saved snapshot: {snap_date}")
        st.cache_data.clear()

df = add_phase_columns(df)

if df.empty:
    st.error("No studies were returned. Try broadening the status filters.")
    st.stop()

df["Modality"] = df.apply(_modality, axis=1)


# ---------------------------------------------------------------------------
# Sidebar — cascading disease filter + other filters
# ---------------------------------------------------------------------------

st.sidebar.header("Filters")
st.sidebar.caption("Disease filter cascades: Branch → Category → Entity.")

branch_options_all = sorted(df["Branch"].dropna().unique().tolist())
branch_sel = st.sidebar.multiselect(
    "Branch",
    options=branch_options_all,
    default=branch_options_all,
    help="Heme-onc, Solid-onc, Mixed, Unknown.",
)

df_after_branch = df[df["Branch"].isin(branch_sel)] if branch_sel else df

category_options_all = sorted(df_after_branch["DiseaseCategory"].dropna().unique().tolist())
category_sel = st.sidebar.multiselect(
    "Disease category",
    options=category_options_all,
    default=category_options_all,
    help="Options narrow based on the selected branch(es).",
)

df_after_cat = (
    df_after_branch[df_after_branch["DiseaseCategory"].isin(category_sel)]
    if category_sel else df_after_branch
)

_entities: set[str] = set()
for val in df_after_cat["DiseaseEntities"].dropna():
    for e in str(val).split("|"):
        e = e.strip()
        if e:
            _entities.add(e)
for val in df_after_cat["DiseaseEntity"].dropna():
    _entities.add(str(val))
entity_options_all = sorted(_entities)
entity_sel = st.sidebar.multiselect(
    "Disease entity",
    options=entity_options_all,
    default=entity_options_all,
    help="Basket/multi-disease trials appear under every entity they enroll.",
)

# Trial design
design_options = sorted(df["TrialDesign"].dropna().unique().tolist())
design_sel = st.sidebar.multiselect(
    "Trial design", options=design_options, default=design_options,
    help="Single-disease vs basket/multi-disease trials.",
)

# Phase
phase_options = [PHASE_LABELS[p] for p in PHASE_ORDER if p in set(df["PhaseNormalized"].astype(str))]
phase_sel = st.sidebar.multiselect("Phase", options=phase_options, default=phase_options)

# Target category (exclude platform labels — those live in modality filter)
target_options = sorted(
    t for t in df["TargetCategory"].dropna().unique() if t not in _PLATFORM_LABELS
)
target_sel = st.sidebar.multiselect("Antigen target", options=target_options, default=target_options)

# Status
status_options = sorted(df["OverallStatus"].dropna().unique().tolist())
status_sel = st.sidebar.multiselect("Overall status", options=status_options, default=status_options)

# Product type
product_options = sorted(df["ProductType"].dropna().unique().tolist())
product_sel = st.sidebar.multiselect("Product type", options=product_options, default=product_options)

# Modality
modality_options = [m for m in MODALITY_ORDER if m in set(df["Modality"])]
modality_sel = st.sidebar.multiselect(
    "Cell therapy modality", options=modality_options, default=modality_options,
)

# Country
all_countries: set[str] = set()
for cs in df["Countries"].dropna():
    for c in str(cs).split("|"):
        c = c.strip()
        if c:
            all_countries.add(c)
country_options = sorted(all_countries)
country_sel = st.sidebar.multiselect("Country", options=country_options, default=country_options)


# ---------------------------------------------------------------------------
# CSV provenance helper
# ---------------------------------------------------------------------------

def _csv_with_provenance(
    df_export: pd.DataFrame, title: str, include_filters: bool = True,
) -> str:
    snap = (
        df["SnapshotDate"].iloc[0]
        if "SnapshotDate" in df.columns and not df.empty
        else date.today().isoformat()
    )
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines: list[str] = [
        f"# {title}",
        f"# Exported (UTC): {now_utc}",
    ]
    if data_source == "Frozen snapshot":
        lines.append(f"# Data source: ClinicalTrials.gov API v2 — frozen snapshot {snap}")
    else:
        lines.append(f"# Data source: ClinicalTrials.gov API v2 — live fetch (snapshot date {snap})")
    lines.append(f"# Source URL: {BASE_URL}")

    if include_filters:
        def _fmt(sel, opts) -> str:
            if not sel or set(sel) == set(opts):
                return "all"
            return "; ".join(str(s) for s in sel)
        lines += [
            f"# Filter — branch: {_fmt(branch_sel, branch_options_all)}",
            f"# Filter — disease category: {_fmt(category_sel, category_options_all)}",
            f"# Filter — disease entity: {_fmt(entity_sel, entity_options_all)}",
            f"# Filter — trial design: {_fmt(design_sel, design_options)}",
            f"# Filter — phase: {_fmt(phase_sel, phase_options)}",
            f"# Filter — antigen target: {_fmt(target_sel, target_options)}",
            f"# Filter — overall status: {_fmt(status_sel, status_options)}",
            f"# Filter — product type: {_fmt(product_sel, product_options)}",
            f"# Filter — cell therapy modality: {_fmt(modality_sel, modality_options)}",
            f"# Filter — country: {_fmt(country_sel, country_options)}",
        ]
    lines += [
        f"# Rows: {len(df_export)}",
        "# Read with: pd.read_csv(path, comment='#')",
        "",
    ]
    return "\n".join(lines) + df_export.to_csv(index=False)


# Data-quality expander
with st.sidebar.expander("Data quality / missing classifications", expanded=False):
    cols_to_check = ["Branch", "DiseaseCategory", "DiseaseEntity", "Phase", "TargetCategory", "OverallStatus", "Countries"]
    rows = []
    ambiguous_disease = [t.lower() for t in AMBIGUOUS_ENTITY_TOKENS] + [
        "basket/multidisease", "advanced solid tumors", "heme basket",
    ]
    ambiguous_target = [t.lower() for t in AMBIGUOUS_TARGET_TOKENS]
    for col in cols_to_check:
        s = df[col].astype("string")
        missing = int(df[col].isna().sum() + (s.str.strip() == "").sum())
        if col in {"Branch", "DiseaseCategory", "DiseaseEntity"}:
            ambiguous = int(s.str.lower().fillna("").isin(ambiguous_disease).sum())
        elif col == "TargetCategory":
            ambiguous = int(s.str.lower().fillna("").isin(ambiguous_target).sum())
        else:
            ambiguous = 0
        rows.append({"Column": col, "Missing / empty": missing, "Ambiguous labels": ambiguous})
    quality_df = pd.DataFrame(rows)
    st.dataframe(quality_df, width='stretch', hide_index=True)
    n_llm = int(df["LLMOverride"].sum()) if "LLMOverride" in df.columns else 0
    if n_llm:
        st.caption(
            f"LLM-assisted: **{n_llm}** trial(s) reclassified via `llm_overrides.json`. "
            "Run `python validate.py` to expand coverage."
        )
    else:
        st.caption(
            "No LLM overrides active. Run `python validate.py` to classify ambiguous trials "
            "and write `llm_overrides.json`."
        )


# ---------------------------------------------------------------------------
# Apply filters
# ---------------------------------------------------------------------------

mask = pd.Series(True, index=df.index)

if branch_sel:
    mask &= df["Branch"].isin(branch_sel)
if category_sel:
    mask &= df["DiseaseCategory"].isin(category_sel)
if entity_sel:
    entity_set = set(entity_sel)
    primary_match = df["DiseaseEntity"].isin(entity_set)
    list_match = df["DiseaseEntities"].fillna("").apply(
        lambda s: any(e.strip() in entity_set for e in str(s).split("|") if e.strip())
    )
    mask &= (primary_match | list_match)
if design_sel:
    mask &= df["TrialDesign"].isin(design_sel)
if phase_sel:
    selected_phase_norm = [k for k, v in PHASE_LABELS.items() if v in phase_sel]
    mask &= df["PhaseNormalized"].isin(selected_phase_norm)
if target_sel:
    mask &= df["TargetCategory"].isin(target_sel) | df["TargetCategory"].isin(_PLATFORM_LABELS)
if status_sel:
    mask &= df["OverallStatus"].isin(status_sel)
if product_sel:
    mask &= df["ProductType"].isin(product_sel)
if modality_sel:
    mask &= df["Modality"].isin(modality_sel)
if country_sel:
    country_pattern = "|".join([re.escape(c) for c in country_sel])
    mask &= df["Countries"].fillna("").str.contains(country_pattern, case=False, na=False, regex=True)

_df_filt = df[mask].copy()
df_filt = add_phase_columns(_df_filt)
df_filt["OverallStatus"] = df_filt["OverallStatus"].fillna("Unknown")
df_filt["NCTLink"] = df_filt["NCTId"].apply(
    lambda x: f"https://clinicaltrials.gov/study/{x}" if pd.notna(x) else None
)


# ---------------------------------------------------------------------------
# Germany deep-dive
# ---------------------------------------------------------------------------

germany_sites_all = pd.DataFrame()
germany_open_sites = pd.DataFrame()
germany_study_view = pd.DataFrame()

if not df_sites.empty:
    germany_sites_all = df_sites[df_sites["Country"].fillna("").str.lower() == "germany"].copy()
    germany_open_sites = germany_sites_all[
        germany_sites_all["SiteStatus"].fillna("").str.upper().isin(OPEN_SITE_STATUSES)
    ].copy()
    germany_open_sites = germany_open_sites[germany_open_sites["NCTId"].isin(df_filt["NCTId"])].copy()

    if not germany_open_sites.empty:
        germany_trials = df_filt[df_filt["NCTId"].isin(germany_open_sites["NCTId"])].copy()

        germany_study_view = (
            germany_open_sites.groupby("NCTId", as_index=False)
            .agg(
                GermanCities=("City", uniq_join),
                GermanSiteStatuses=("SiteStatus", uniq_join),
            )
        )

        germany_study_view = germany_study_view.merge(
            germany_trials[
                [
                    "NCTId", "BriefTitle",
                    "Branch", "DiseaseCategory", "DiseaseEntity",
                    "TargetCategory", "ProductType",
                    "Phase", "PhaseNormalized", "PhaseOrdered", "PhaseLabel",
                    "OverallStatus", "LeadSponsor",
                ]
            ].drop_duplicates(subset=["NCTId"]),
            on="NCTId", how="left",
        )

        germany_study_view["NCTLink"] = germany_study_view["NCTId"].apply(
            lambda x: f"https://clinicaltrials.gov/study/{x}" if pd.notna(x) else None
        )
        germany_study_view["Phase"] = germany_study_view["PhaseLabel"].fillna(germany_study_view["Phase"])

        germany_study_view = germany_study_view[
            [
                "NCTId", "NCTLink", "BriefTitle",
                "Branch", "DiseaseCategory", "DiseaseEntity",
                "TargetCategory", "ProductType",
                "Phase", "PhaseNormalized", "PhaseOrdered",
                "OverallStatus", "LeadSponsor",
                "GermanCities", "GermanSiteStatuses",
            ]
        ].sort_values(["PhaseOrdered", "Branch", "DiseaseCategory", "NCTId"], na_position="last")


# ---------------------------------------------------------------------------
# Metric row
# ---------------------------------------------------------------------------

total_trials = len(df_filt)
recruiting_trials = int(df_filt["OverallStatus"].isin(["RECRUITING", "NOT_YET_RECRUITING"]).sum())
german_trials_count = germany_study_view["NCTId"].nunique() if not germany_study_view.empty else 0
heme_count = int((df_filt["Branch"] == "Heme-onc").sum())
solid_count = int((df_filt["Branch"] == "Solid-onc").sum())
_tc_for_top = df_filt.loc[~df_filt["TargetCategory"].isin(_PLATFORM_LABELS), "TargetCategory"].dropna()
top_target = _tc_for_top.value_counts().idxmax() if not _tc_for_top.empty else "—"
_enroll_known = pd.to_numeric(df_filt["EnrollmentCount"], errors="coerce").dropna()
total_enrolled = int(_enroll_known.sum()) if not _enroll_known.empty else 0
median_enrolled = int(_enroll_known.median()) if not _enroll_known.empty else 0

m1, m2, m3, m4, m5 = st.columns(5)
with m1:
    metric_card("Filtered trials", total_trials, "Trials matching current filters")
with m2:
    metric_card("Open / recruiting", recruiting_trials, "Recruiting or not yet recruiting")
with m3:
    metric_card("Heme · Solid", f"{heme_count} · {solid_count}", "Heme-onc / Solid-onc split")
with m4:
    metric_card("Median enrollment", median_enrolled, f"{total_enrolled:,} patients across {len(_enroll_known)} trials")
with m5:
    metric_card("Top antigen target", top_target, "Most common non-platform target")

st.markdown(
    f"""
    <div class="small-note">
        {len(df)} total trials after processing. Current view shows {len(df_filt)} filtered trials.
    </div>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab_overview, tab_geo, tab_data, tab_pub, tab_methods, tab_about = st.tabs(
    ["Overview", "Geography / Map", "Data", "Publication Figures", "Methods & Appendix", "About"]
)


# ---------------------------------------------------------------------------
# TAB: Overview
# ---------------------------------------------------------------------------

with tab_overview:
    if prisma_counts:
        st.subheader("Study selection (PRISMA flow)")
        prisma_rows = [
            {"Step": "Records identified via ClinicalTrials.gov API", "n": prisma_counts.get("n_fetched", "—"), "Note": ""},
            {"Step": "Duplicate records removed", "n": prisma_counts.get("n_duplicates_removed", "—"), "Note": "Same NCT ID"},
            {"Step": "Records screened", "n": prisma_counts.get("n_after_dedup", "—"), "Note": ""},
            {"Step": "Excluded: pre-specified NCT IDs", "n": prisma_counts.get("n_hard_excluded", "—"), "Note": "Manually curated exclusion list"},
            {"Step": "Excluded: autoimmune-only indications", "n": prisma_counts.get("n_indication_excluded", "—"), "Note": "Keyword-based exclusion"},
            {"Step": "Studies included in analysis", "n": prisma_counts.get("n_included", "—"), "Note": "Final dataset"},
        ]
        prisma_df = pd.DataFrame(prisma_rows)
        st.dataframe(
            prisma_df, width='stretch', hide_index=True,
            column_config={
                "Step": st.column_config.TextColumn("Step", width="large"),
                "n": st.column_config.NumberColumn("n", width="small"),
                "Note": st.column_config.TextColumn("Note", width="medium"),
            },
        )

    # Row 1: Branch summary + Heme vs Solid targets
    ov_r1c1, ov_r1c2 = st.columns(2)

    with ov_r1c1:
        st.subheader("Trials by disease category")
        st.caption("Stacked by Branch. Basket trials shown under their inferred branch.")
        counts_cat = (
            df_filt.groupby(["DiseaseCategory", "Branch"], as_index=False)
            .size().rename(columns={"size": "Count"})
        )
        counts_cat = counts_cat.sort_values("Count", ascending=False)
        if not counts_cat.empty:
            fig_cat = px.bar(
                counts_cat, x="DiseaseCategory", y="Count", color="Branch",
                color_discrete_map=BRANCH_COLORS, template="plotly_white", height=380,
            )
            fig_cat.update_layout(
                barmode="stack",
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=10, r=10, t=10, b=10),
                font=dict(color=THEME["text"]),
                xaxis_title=None, yaxis_title=None, legend_title=None,
            )
            fig_cat.update_xaxes(color=THEME["muted"])
            fig_cat.update_yaxes(gridcolor=THEME["grid"], color=THEME["muted"])
            st.plotly_chart(fig_cat, width='stretch')
        else:
            st.info("No trials for the current filter selection.")

    with ov_r1c2:
        st.subheader("Trials by antigen target")
        st.caption("Top 20 antigens. Platforms (CAR-NK, CAAR-T, …) shown in the Modality figure.")
        counts_target = (
            df_filt.loc[~df_filt["TargetCategory"].isin(_PLATFORM_LABELS), "TargetCategory"]
            .fillna("Unknown").value_counts().rename_axis("TargetCategory")
            .reset_index(name="Count").head(20)
        )
        if not counts_target.empty:
            st.plotly_chart(
                make_bar(counts_target, "TargetCategory", "Count", color=THEME["primary"], height=380),
                width='stretch',
            )
        else:
            st.info("No trials for the current filter selection.")

    # Row 2: Phase by Branch + Temporal
    ov_r2c1, ov_r2c2 = st.columns(2)

    with ov_r2c1:
        st.subheader("Trials by phase")
        st.caption("Stacked by Branch — heme trials tend to sit later in development than solid.")
        phase_counts = (
            df_filt.groupby(["PhaseOrdered", "Branch"], observed=False).size().reset_index(name="Count")
        )
        phase_counts["PhaseNormalized"] = phase_counts["PhaseOrdered"].astype(str)
        phase_counts["Phase"] = phase_counts["PhaseNormalized"].map(PHASE_LABELS)
        phase_counts = phase_counts[phase_counts["Count"] > 0].copy()
        phase_counts["Phase"] = pd.Categorical(
            phase_counts["Phase"],
            categories=[PHASE_LABELS[p] for p in PHASE_ORDER], ordered=True,
        )
        phase_counts = phase_counts.sort_values("Phase")
        if not phase_counts.empty:
            fig_phase = px.bar(
                phase_counts, x="Phase", y="Count", color="Branch",
                color_discrete_map=BRANCH_COLORS, template="plotly_white", height=320,
            )
            fig_phase.update_layout(
                barmode="stack",
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=10, r=10, t=10, b=10),
                font=dict(color=THEME["text"]),
                xaxis_title=None, yaxis_title=None, legend_title=None,
            )
            fig_phase.update_xaxes(color=THEME["muted"], categoryorder="array",
                                    categoryarray=[PHASE_LABELS[p] for p in PHASE_ORDER])
            fig_phase.update_yaxes(gridcolor=THEME["grid"], color=THEME["muted"])
            st.plotly_chart(fig_phase, width='stretch')
        else:
            st.info("No trials for the current filter selection.")

    with ov_r2c2:
        st.subheader("Trials by start year")
        st.caption("Stacked area by Branch. Heme vs Solid trajectories diverge sharply.")
        year_df = df_filt.copy()
        year_df["StartYear"] = pd.to_numeric(year_df["StartYear"], errors="coerce")
        year_df = year_df.dropna(subset=["StartYear"])
        year_df["StartYear"] = year_df["StartYear"].astype(int)
        counts_year = (
            year_df.groupby(["StartYear", "Branch"], as_index=False)
            .size().rename(columns={"size": "Count"})
        )
        if not counts_year.empty:
            fig_year = px.area(
                counts_year, x="StartYear", y="Count", color="Branch",
                color_discrete_map=BRANCH_COLORS, template="plotly_white", height=320,
            )
            fig_year.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=10, r=10, t=10, b=10),
                font=dict(color=THEME["text"]),
                xaxis_title=None, yaxis_title=None, legend_title=None,
            )
            fig_year.update_xaxes(color=THEME["muted"], tickmode="linear", dtick=1, tickformat="d")
            fig_year.update_yaxes(gridcolor=THEME["grid"], color=THEME["muted"])
            st.plotly_chart(fig_year, width='stretch')
        else:
            st.info("No trials with a valid start year for the current filter selection.")


# ---------------------------------------------------------------------------
# TAB: Geography / Map
# ---------------------------------------------------------------------------

with tab_geo:
    st.subheader("Global studies by country")

    countries_long = split_pipe_values(df_filt["Countries"])
    if countries_long:
        country_df = pd.DataFrame({"Country": countries_long})
        country_counts = (
            country_df["Country"].value_counts().rename_axis("Country").reset_index(name="Count")
        )

        fig_world = px.choropleth(
            country_counts, locations="Country", locationmode="country names",
            color="Count",
            color_continuous_scale=[
                [0.00, "#dbeafe"], [0.30, "#93c5fd"],
                [0.55, "#3b82f6"], [0.75, "#1d4ed8"], [1.00, "#1e3a8a"],
            ],
            projection="natural earth", template="plotly_white",
        )
        fig_world.update_layout(
            margin=dict(l=0, r=0, t=10, b=0),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color=THEME["text"]),
            geo=dict(
                bgcolor="rgba(0,0,0,0)", lakecolor="#ddeeff", landcolor="#e9ecef",
                showframe=False, showcoastlines=False,
                showcountries=True, countrycolor="rgba(0,0,0,0.12)",
            ),
            coloraxis_colorbar_title="No. of trials",
        )
        st.plotly_chart(fig_world, width='stretch')

        c1, c2 = st.columns([1.15, 0.85])
        with c1:
            st.markdown("**Country counts**")
            st.dataframe(country_counts, width='stretch', height=320, hide_index=True)
        with c2:
            st.markdown("**Top countries**")
            st.plotly_chart(
                make_bar(country_counts.head(12), "Country", "Count", height=320, color=THEME["primary"]),
                width='stretch',
            )
    else:
        st.info("No country information available for the current filter selection.")

    st.subheader("Germany by city")

    if germany_open_sites.empty:
        st.info("No open or recruiting German study sites found in the current result set.")
    else:
        germany_city_counts = (
            germany_open_sites["City"].fillna("Unknown").value_counts()
            .rename_axis("City").reset_index(name="OpenSiteCount")
            .sort_values(["OpenSiteCount", "City"], ascending=[False, True], na_position="last")
            .reset_index(drop=True)
        )

        g1, g2, g3 = st.columns(3)
        with g1:
            metric_card("German site rows", len(germany_open_sites), "Recruiting / active German site rows")
        with g2:
            metric_card("German cities", germany_open_sites["City"].dropna().nunique(), "Cities with open sites")
        with g3:
            metric_card(
                "German unique trials",
                germany_study_view["NCTId"].nunique() if not germany_study_view.empty else 0,
                "Unique NCT IDs with at least one open German site",
            )

        c1, c2 = st.columns([1, 1])
        with c1:
            st.markdown("**Open sites by city**")
            st.plotly_chart(
                make_bar(germany_city_counts, "City", "OpenSiteCount",
                         height=min(300, max(180, len(germany_city_counts) * 20 + 48)), color=THEME["primary"]),
                width='stretch',
            )
        with c2:
            st.markdown("**Germany city table**")
            city_event = st.dataframe(
                germany_city_counts, width='stretch',
                height=min(300, max(180, len(germany_city_counts) * 20 + 48)),
                hide_index=True,
                on_select="rerun", selection_mode="single-row",
                key="germany_city_table",
            )

        if city_event and city_event.selection.rows:
            selected_idx = city_event.selection.rows[0]
            selected_city = germany_city_counts.iloc[selected_idx]["City"]

            st.markdown(f"### Trials with open German sites in {selected_city}")

            city_nct_ids = (
                germany_open_sites.loc[
                    germany_open_sites["City"].fillna("Unknown") == selected_city, "NCTId",
                ].dropna().unique()
            )

            city_trial_view = germany_study_view[germany_study_view["NCTId"].isin(city_nct_ids)].copy()
            city_trial_view = city_trial_view.sort_values(
                ["PhaseOrdered", "Branch", "DiseaseCategory", "NCTId"],
                ascending=[True, True, True, True], na_position="last",
            )

            if city_trial_view.empty:
                st.info(f"No study rows found for {selected_city}.")
            else:
                st.dataframe(
                    city_trial_view[[
                        "NCTId", "NCTLink", "BriefTitle",
                        "Branch", "DiseaseCategory", "DiseaseEntity",
                        "TargetCategory", "ProductType", "Phase",
                        "OverallStatus", "LeadSponsor",
                        "GermanCities", "GermanSiteStatuses",
                    ]],
                    width='stretch', height=320, hide_index=True,
                    column_config={
                        "NCTId": st.column_config.TextColumn("NCT ID"),
                        "NCTLink": st.column_config.LinkColumn("Trial link", display_text="Open trial"),
                        "BriefTitle": st.column_config.TextColumn("Title", width="large"),
                        "Branch": st.column_config.TextColumn("Branch"),
                        "DiseaseCategory": st.column_config.TextColumn("Category"),
                        "DiseaseEntity": st.column_config.TextColumn("Entity"),
                        "TargetCategory": st.column_config.TextColumn("Target"),
                        "ProductType": st.column_config.TextColumn("Product"),
                        "Phase": st.column_config.TextColumn("Phase"),
                        "OverallStatus": st.column_config.TextColumn("Status"),
                        "LeadSponsor": st.column_config.TextColumn("Lead sponsor", width="medium"),
                        "GermanCities": st.column_config.TextColumn("German cities", width="large"),
                        "GermanSiteStatuses": st.column_config.TextColumn("German site status", width="medium"),
                    },
                )
        else:
            st.caption("Select a city row in the table to open the related trial list below.")


# ---------------------------------------------------------------------------
# TAB: Data
# ---------------------------------------------------------------------------

with tab_data:
    st.subheader("Trial table")

    show_cols = [
        "NCTId", "NCTLink", "BriefTitle",
        "Branch", "DiseaseCategory", "DiseaseEntities",
        "TrialDesign", "TargetCategory", "ProductType",
        "Phase", "OverallStatus", "StartYear", "Countries", "LeadSponsor",
    ]

    table_df = df_filt.sort_values(
        ["PhaseOrdered", "Branch", "DiseaseCategory", "NCTId"],
        ascending=[True, True, True, True],
    ).copy()
    table_df["Phase"] = table_df["PhaseLabel"]
    table_df["OverallStatus"] = table_df["OverallStatus"].map(STATUS_DISPLAY).fillna(table_df["OverallStatus"])

    st.dataframe(
        table_df[show_cols],
        width='stretch', height=460, hide_index=True,
        column_config={
            "NCTId": st.column_config.TextColumn("NCT ID"),
            "NCTLink": st.column_config.LinkColumn("Trial link", display_text="Open trial"),
            "BriefTitle": st.column_config.TextColumn("Title", width="large"),
            "Branch": st.column_config.TextColumn("Branch"),
            "DiseaseCategory": st.column_config.TextColumn("Category"),
            "DiseaseEntities": st.column_config.TextColumn("Entity(ies)", width="medium"),
            "TrialDesign": st.column_config.TextColumn("Trial design", width="small"),
            "TargetCategory": st.column_config.TextColumn("Target"),
            "ProductType": st.column_config.TextColumn("Product"),
            "Phase": st.column_config.TextColumn("Phase"),
            "OverallStatus": st.column_config.TextColumn("Status"),
            "StartYear": st.column_config.NumberColumn("Start year", format="%d"),
            "Countries": st.column_config.TextColumn("Countries", width="large"),
            "LeadSponsor": st.column_config.TextColumn("Lead sponsor", width="medium"),
        },
    )

    st.subheader("Studies active in Germany")

    if germany_study_view.empty:
        st.info("No open or recruiting German study sites found in the current result set.")
    else:
        germany_export_view = germany_study_view.copy()
        germany_export_view["OverallStatus"] = germany_export_view["OverallStatus"].map(STATUS_DISPLAY).fillna(germany_export_view["OverallStatus"])
        germany_export_view = germany_export_view.sort_values(
            ["PhaseOrdered", "Branch", "DiseaseCategory", "NCTId"], na_position="last",
        )
        st.dataframe(
            germany_export_view[[
                "NCTId", "NCTLink", "BriefTitle",
                "Branch", "DiseaseCategory", "DiseaseEntity",
                "TargetCategory", "ProductType", "Phase",
                "OverallStatus", "LeadSponsor",
                "GermanCities", "GermanSiteStatuses",
            ]],
            width='stretch', height=380, hide_index=True,
            column_config={
                "NCTId": st.column_config.TextColumn("NCT ID"),
                "NCTLink": st.column_config.LinkColumn("Trial link", display_text="Open trial"),
                "BriefTitle": st.column_config.TextColumn("Title", width="large"),
                "Branch": st.column_config.TextColumn("Branch"),
                "DiseaseCategory": st.column_config.TextColumn("Category"),
                "DiseaseEntity": st.column_config.TextColumn("Entity"),
                "TargetCategory": st.column_config.TextColumn("Target"),
                "ProductType": st.column_config.TextColumn("Product"),
                "Phase": st.column_config.TextColumn("Phase"),
                "OverallStatus": st.column_config.TextColumn("Status"),
                "LeadSponsor": st.column_config.TextColumn("Lead sponsor", width="medium"),
                "GermanCities": st.column_config.TextColumn("German cities", width="large"),
                "GermanSiteStatuses": st.column_config.TextColumn("German site status", width="medium"),
            },
        )

    d1, d2 = st.columns(2)
    with d1:
        st.download_button(
            label="Download filtered trial data as CSV",
            data=_csv_with_provenance(df_filt, "Filtered trial list"),
            file_name="car_t_oncology_trials_filtered.csv",
            mime="text/csv",
        )
    with d2:
        if not df_sites.empty:
            st.download_button(
                label="Download site-level data as CSV",
                data=_csv_with_provenance(df_sites, "Site-level data"),
                file_name="car_t_oncology_sites.csv",
                mime="text/csv",
            )


# ---------------------------------------------------------------------------
# Publication figure styling
# ---------------------------------------------------------------------------

NEJM = ["#0b3d91", "#b45309", "#059669", "#dc2626", "#4f46e5", "#0891b2", "#0d9488", "#64748b"]
NEJM_BLUE    = HEME_COLOR
NEJM_AMBER   = SOLID_COLOR
NEJM_GREEN   = "#059669"
NEJM_RED     = "#dc2626"
NEJM_PURPLE  = "#4f46e5"

_MODALITY_COLORS.update({
    "Auto CAR-T":      NEJM_BLUE,
    "Allo CAR-T":      "#0891b2",
    "CAR-T (unclear)": "#a1a1aa",
    "CAR-γδ T":        "#0d9488",
    "CAR-NK":          NEJM_GREEN,
    "CAR-Treg":        NEJM_PURPLE,
    "CAAR-T":          NEJM_AMBER,
    "In vivo CAR":     NEJM_RED,
})

_AX_COLOR  = "#1a1a1a"
_GRID_CLR  = "#c8c8c8"
_TICK_SZ   = 11
_TITLE_SZ  = 14
_LAB_SZ    = 12

PUB_FONT = dict(family="Arial, Helvetica, sans-serif", size=_TICK_SZ, color=_AX_COLOR)
PUB_BASE = dict(template="plotly_white", paper_bgcolor="white", plot_bgcolor="white", font=PUB_FONT)
PUB_EXPORT = {"toImageButtonOptions": {"format": "png", "width": 1600, "height": 900, "scale": 2}}


def _pub_header(figure_num: str, title: str, subtitle: str | None = None) -> None:
    sub_html = f'<div class="pub-fig-sub">{subtitle}</div>' if subtitle else ""
    st.markdown(
        f'<div class="pub-fig-header">'
        f'<div class="pub-fig-eyebrow">Figure {figure_num}</div>'
        f'<div class="pub-fig-title">{title}</div>'
        f'{sub_html}'
        f'</div>',
        unsafe_allow_html=True,
    )


def _pub_caption(n: int, extra: str | None = None) -> None:
    extra_html = f" {extra}" if extra else ""
    st.markdown(
        f'<div class="pub-fig-caption">n = {n:,} trials in the filtered set. '
        f'Full filter state and data source recorded in the CSV export header.'
        f'{extra_html}</div>',
        unsafe_allow_html=True,
    )


_V_XAXIS = dict(
    showline=True, linewidth=1.5, linecolor=_AX_COLOR, mirror=False,
    showgrid=False, ticks="outside", ticklen=6, tickwidth=1.2,
    title_font=dict(size=_LAB_SZ, color=_AX_COLOR),
    tickfont=dict(size=_TICK_SZ, color=_AX_COLOR),
)
_V_YAXIS = dict(
    showline=True, linewidth=1.5, linecolor=_AX_COLOR, mirror=False,
    showgrid=True, gridcolor=_GRID_CLR, gridwidth=0.7,
    ticks="outside", ticklen=6, tickwidth=1.2,
    title_font=dict(size=_LAB_SZ, color=_AX_COLOR),
    tickfont=dict(size=_TICK_SZ, color=_AX_COLOR),
    zeroline=False,
)
PUB_LAYOUT = dict(**PUB_BASE, margin=dict(l=72, r=36, t=24, b=72), xaxis=_V_XAXIS, yaxis=_V_YAXIS)

_H_XAXIS = dict(
    showline=True, linewidth=1.5, linecolor=_AX_COLOR,
    showgrid=True, gridcolor=_GRID_CLR, gridwidth=0.7,
    ticks="outside", ticklen=6, tickwidth=1.2,
    tickfont=dict(size=_TICK_SZ, color=_AX_COLOR),
    title_font=dict(size=_LAB_SZ, color=_AX_COLOR),
    zeroline=False,
)
_H_YAXIS = dict(
    showline=True, linewidth=1.5, linecolor=_AX_COLOR,
    showgrid=False,
    ticks="outside", ticklen=4, tickwidth=1.2,
    tickfont=dict(size=_TICK_SZ, color=_AX_COLOR),
)


def _cagr(first_count: int, last_count: int, n_years: int) -> float | None:
    if n_years <= 0 or first_count <= 0:
        return None
    return (last_count / first_count) ** (1 / n_years) - 1


# ---------------------------------------------------------------------------
# TAB: Publication Figures  (oncology-specific set, 8 figures)
# ---------------------------------------------------------------------------

with tab_pub:
    st.markdown(
        '<p class="small-note" style="color:#555">Publication-ready figures with white backgrounds. '
        "Use the camera icon (▷ toolbar) on each chart to download a high-resolution PNG. "
        "Heme-onc shown in navy, Solid-onc in amber throughout.</p>",
        unsafe_allow_html=True,
    )

    # ------------------------------------------------------------------
    # Fig 1 — Temporal trends, split by Branch, with approved-product overlay
    # ------------------------------------------------------------------
    years_raw = pd.to_numeric(df_filt["StartYear"], errors="coerce").dropna().astype(int)
    _yr_min = int(years_raw.min()) if len(years_raw) else None
    _yr_max = int(years_raw.max()) if len(years_raw) else None
    _fig1_sub = (
        f"Annual trial starts by branch, {_yr_min}–{_yr_max}. Vertical lines mark approvals of landmark CAR-T products."
        if _yr_min is not None else "Annual trial starts by branch."
    )
    _pub_header("1", "Temporal trends by branch, with approved-product overlay", _fig1_sub)

    year_branch = (
        df_filt.dropna(subset=["StartYear"])
        .assign(StartYear=lambda d: d["StartYear"].astype(int))
        .groupby(["StartYear", "Branch"], as_index=False).size()
        .rename(columns={"size": "Trials"})
    )

    if not year_branch.empty:
        fig1 = px.area(
            year_branch, x="StartYear", y="Trials", color="Branch",
            color_discrete_map=BRANCH_COLORS, template="plotly_white", height=420,
        )
        fig1.update_traces(opacity=0.85)
        fig1.update_layout(
            **PUB_BASE,
            margin=dict(l=72, r=36, t=24, b=110),
            xaxis=dict(
                tickmode="linear", dtick=1, tickformat="d", showgrid=False,
                showline=True, linewidth=1.5, linecolor=_AX_COLOR,
                ticks="outside", ticklen=6, tickwidth=1.2,
                tickfont=dict(size=_TICK_SZ, color=_AX_COLOR),
                title="Start year", title_font=dict(size=_LAB_SZ, color=_AX_COLOR),
            ),
            yaxis=dict(
                showline=True, linewidth=1.5, linecolor=_AX_COLOR,
                showgrid=True, gridcolor=_GRID_CLR, gridwidth=0.7,
                ticks="outside", ticklen=6, tickwidth=1.2,
                tickfont=dict(size=_TICK_SZ, color=_AX_COLOR),
                title="Number of trials",
                title_font=dict(size=_LAB_SZ, color=_AX_COLOR),
                zeroline=False, rangemode="tozero",
            ),
            legend=dict(
                orientation="h", yanchor="top", y=-0.20, xanchor="center", x=0.5,
                font=dict(size=11, color=_AX_COLOR), bgcolor="rgba(0,0,0,0)",
                borderwidth=0, title=None,
            ),
        )

        # Approved-product overlays — vertical dashed lines + year-aggregated labels
        products_by_year: dict[int, list[str]] = {}
        for p in APPROVED_PRODUCTS:
            products_by_year.setdefault(p["year"], []).append(p["name"])
        _yrs_present = set(year_branch["StartYear"].tolist())
        for yr, prods in products_by_year.items():
            if yr < (_yr_min or 0) or yr > (_yr_max or 9999):
                continue
            fig1.add_vline(x=yr, line_width=0.9, line_dash="dot", line_color="#64748b")
            fig1.add_annotation(
                x=yr, y=1.02, yref="paper",
                text="  " + "<br>  ".join(prods),
                showarrow=False, xanchor="left", yanchor="top",
                font=dict(size=9, color="#334155"),
                align="left",
            )

        _current_year = pd.Timestamp.now().year
        if _yr_max is not None and _yr_max >= _current_year:
            fig1.add_vrect(
                x0=_current_year - 0.5, x1=_current_year + 0.5,
                fillcolor="rgba(0,0,0,0.04)", line_width=0,
            )
            fig1.add_annotation(
                x=_current_year, y=1.10, yref="paper",
                text=f"{_current_year} (partial year)", showarrow=False,
                font=dict(size=10, color=THEME["muted"]),
                yanchor="bottom", xanchor="center",
            )

        st.plotly_chart(fig1, width='stretch', config=PUB_EXPORT)

        total_t = len(df_filt)
        fig1_yearly = year_branch.groupby("StartYear")["Trials"].sum().sort_index()
        peak_year = int(fig1_yearly.idxmax())
        peak_n = int(fig1_yearly.max())
        first_yr = int(fig1_yearly.index.min())
        last_yr = int(fig1_yearly.index.max())
        cagr = _cagr(int(fig1_yearly.iloc[0]), int(fig1_yearly.iloc[-1]), last_yr - first_yr)
        cagr_str = f"{cagr * 100:.1f}%" if cagr is not None else "N/A"

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total included trials", total_t)
        c2.metric("Year range", f"{first_yr}–{last_yr}")
        c3.metric("Peak year", f"{peak_year} (n={peak_n})")
        c4.metric("CAGR (overall)", cagr_str)

        _pub_caption(len(df_filt))
        st.download_button("Fig 1 data (CSV)",
                           _csv_with_provenance(year_branch, "Fig 1 — Temporal trends by branch"),
                           "fig1_temporal_trends.csv", "text/csv")
    else:
        st.info("No start year data available.")

    # ------------------------------------------------------------------
    # Fig 2 — Phase distribution, stacked by Branch
    # ------------------------------------------------------------------
    _pub_header("2", "Distribution of clinical trial phases, by branch",
                "Heme-onc trials are further along in development than solid-onc.")

    phase_counts = (
        df_filt.groupby(["PhaseOrdered", "Branch"], observed=False).size().reset_index(name="Trials")
    )
    phase_counts["Phase"] = phase_counts["PhaseOrdered"].astype(str).map(PHASE_LABELS)
    phase_counts = phase_counts[phase_counts["Trials"] > 0].copy()
    phase_counts["Phase"] = pd.Categorical(
        phase_counts["Phase"], categories=[PHASE_LABELS[p] for p in PHASE_ORDER], ordered=True,
    )
    phase_counts = phase_counts.sort_values("Phase")

    if not phase_counts.empty:
        fig2 = px.bar(
            phase_counts, x="Phase", y="Trials", color="Branch",
            color_discrete_map=BRANCH_COLORS, barmode="stack",
            template="plotly_white", height=420, text="Trials",
        )
        fig2.update_traces(marker_line_width=0, opacity=1, textposition="inside",
                           textfont=dict(size=10, color="white"))
        fig2.update_layout(
            **PUB_LAYOUT,
            xaxis_title="Phase", yaxis_title="Number of trials",
            legend=dict(
                orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5,
                font=dict(size=11, color=_AX_COLOR), bgcolor="rgba(0,0,0,0)",
                borderwidth=0, title=None,
            ),
        )
        fig2.update_xaxes(categoryorder="array", categoryarray=[PHASE_LABELS[p] for p in PHASE_ORDER])
        st.plotly_chart(fig2, width='stretch', config=PUB_EXPORT)

        total_ph = int(phase_counts["Trials"].sum())
        heme_ph = int(phase_counts.loc[phase_counts["Branch"] == "Heme-onc", "Trials"].sum())
        solid_ph = int(phase_counts.loc[phase_counts["Branch"] == "Solid-onc", "Trials"].sum())
        late_mask = phase_counts["Phase"].isin(["Phase II", "Phase II/III", "Phase III"])
        heme_late = int(phase_counts.loc[late_mask & (phase_counts["Branch"] == "Heme-onc"), "Trials"].sum())
        solid_late = int(phase_counts.loc[late_mask & (phase_counts["Branch"] == "Solid-onc"), "Trials"].sum())
        c1, c2, c3 = st.columns(3)
        c1.metric("Late-phase (II+)", f"{heme_late + solid_late} of {total_ph}")
        c2.metric("Heme late-phase", f"{heme_late} of {heme_ph}" if heme_ph else "—")
        c3.metric("Solid late-phase", f"{solid_late} of {solid_ph}" if solid_ph else "—")

        fig2_csv = phase_counts[["Phase", "Branch", "Trials"]].copy()
        _pub_caption(len(df_filt))
        st.download_button("Fig 2 data (CSV)",
                           _csv_with_provenance(fig2_csv, "Fig 2 — Phase distribution by branch"),
                           "fig2_phase_by_branch.csv", "text/csv")
    else:
        st.info("No phase data available.")

    # ------------------------------------------------------------------
    # Fig 3 — Geography, with Heme vs Solid split
    # ------------------------------------------------------------------
    _pub_header("3", "Global distribution of trial sites",
                "China leads in solid-tumor CAR-T; the US leads in heme. Toggle the branch stratification below.")

    def _country_branch_long(df_in: pd.DataFrame) -> pd.DataFrame:
        rows = []
        for _, r in df_in.iterrows():
            cs = str(r.get("Countries") or "")
            for c in cs.split("|"):
                c = c.strip()
                if c:
                    rows.append({"Country": c, "Branch": r["Branch"]})
        return pd.DataFrame(rows)

    geo_long = _country_branch_long(df_filt)
    if not geo_long.empty:
        geo_counts = (
            geo_long["Country"].value_counts().rename_axis("Country")
            .reset_index(name="Trials")
        )

        fig3_map = px.choropleth(
            geo_counts, locations="Country", locationmode="country names",
            color="Trials",
            color_continuous_scale=[[0, "#dce9f5"], [0.3, "#5aafd6"], [0.65, "#1c6faf"], [1, "#08306b"]],
            projection="natural earth", template="plotly_white",
        )
        fig3_map.update_layout(
            paper_bgcolor="white", plot_bgcolor="white",
            font=PUB_FONT, margin=dict(l=0, r=0, t=10, b=0),
            geo=dict(
                bgcolor="white", lakecolor="#ddeeff", landcolor="#eeeeee",
                showframe=False,
                showcoastlines=True, coastlinecolor="#999999", coastlinewidth=0.6,
                showcountries=True, countrycolor="#cccccc", countrywidth=0.4,
            ),
            coloraxis_colorbar=dict(
                title=dict(text="Trials", font=dict(size=11, color=_AX_COLOR)),
                tickfont=dict(size=10, color=_AX_COLOR),
                thickness=14, len=0.55, outlinewidth=0.5, outlinecolor="#aaaaaa",
            ),
        )
        st.plotly_chart(fig3_map, width='stretch', config=PUB_EXPORT)

        # 3b — Top 10 countries split by Branch
        st.markdown(
            '<div class="pub-fig-sub" style="margin-top: 1rem; '
            'border-top: 1px solid #e5e7eb; padding-top: 0.8rem;">'
            '<strong style="color: #0b1220;">3b — Top 10 countries, stratified by branch</strong>'
            '</div>',
            unsafe_allow_html=True,
        )
        top_countries = geo_counts.head(10)["Country"].tolist()
        country_branch = (
            geo_long[geo_long["Country"].isin(top_countries)]
            .groupby(["Country", "Branch"]).size().reset_index(name="Trials")
        )
        # Order by total
        order = geo_counts[geo_counts["Country"].isin(top_countries)].sort_values("Trials", ascending=True)["Country"].tolist()
        country_branch["Country"] = pd.Categorical(country_branch["Country"], categories=order, ordered=True)
        country_branch = country_branch.sort_values("Country")

        fig3_bar = px.bar(
            country_branch, x="Trials", y="Country", color="Branch",
            color_discrete_map=BRANCH_COLORS, orientation="h",
            template="plotly_white", height=420, text="Trials",
        )
        fig3_bar.update_traces(marker_line_width=0, opacity=1, textposition="inside",
                               textfont=dict(size=10, color="white"), insidetextanchor="middle")
        fig3_bar.update_layout(
            **PUB_BASE,
            barmode="stack",
            xaxis_title="Number of trials", yaxis_title=None,
            margin=dict(l=120, r=56, t=24, b=80),
            yaxis=_H_YAXIS, xaxis=_H_XAXIS,
            legend=dict(
                orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5,
                font=dict(size=11, color=_AX_COLOR), bgcolor="rgba(0,0,0,0)",
                borderwidth=0, title=None,
            ),
        )
        st.plotly_chart(fig3_bar, width='stretch', config=PUB_EXPORT)

        total_geo = int(geo_counts["Trials"].sum())
        top3 = geo_counts.head(3)
        c1, c2, c3 = st.columns(3)
        for col, (_, row) in zip([c1, c2, c3], top3.iterrows()):
            col.metric(row["Country"], f"{row['Trials']} ({100*row['Trials']/total_geo:.0f}%)")

        fig3_csv = geo_counts.copy()
        fig3_csv["% of total"] = (fig3_csv["Trials"] / total_geo * 100).round(1)
        _pub_caption(len(df_filt),
                     extra="Multi-country trials are counted once per country.")
        st.download_button("Fig 3 data (CSV)",
                           _csv_with_provenance(fig3_csv, "Fig 3 — Geographic distribution"),
                           "fig3_geographic_distribution.csv", "text/csv")
    else:
        st.info("No country data available.")

    # ------------------------------------------------------------------
    # Fig 4 — Enrollment landscape with Heme/Solid stratification
    # ------------------------------------------------------------------
    _pub_header("4", "Trial enrollment landscape",
                "Solid-onc trials tend to enroll smaller cohorts than heme-onc, with distinct phase and geography patterns.")

    df_enroll = df_filt.copy()
    df_enroll["EnrollmentCount"] = pd.to_numeric(df_enroll["EnrollmentCount"], errors="coerce")
    df_enroll_known = df_enroll.dropna(subset=["EnrollmentCount"]).copy()
    df_enroll_known["EnrollmentCount"] = df_enroll_known["EnrollmentCount"].astype(int)

    if len(df_enroll_known) >= 3:
        pct_known = 100 * len(df_enroll_known) / len(df_enroll)
        total_pts = int(df_enroll_known["EnrollmentCount"].sum())
        med_pts   = int(df_enroll_known["EnrollmentCount"].median())
        p25 = int(df_enroll_known["EnrollmentCount"].quantile(0.25))
        p75 = int(df_enroll_known["EnrollmentCount"].quantile(0.75))
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Trials with reported enrollment", f"{len(df_enroll_known)} ({pct_known:.0f}%)")
        c2.metric("Total enrolled patients", f"{total_pts:,}")
        c3.metric("Median enrollment", med_pts)
        c4.metric("IQR", f"{p25}–{p75}")

        # 4a — Enrollment distribution split by Branch (overlaid)
        st.markdown(
            '<div class="pub-fig-sub" style="margin-top: 1rem; '
            'border-top: 1px solid #e5e7eb; padding-top: 0.8rem;">'
            '<strong style="color: #0b1220;">4a — Distribution of planned enrollment, by branch</strong>'
            '</div>',
            unsafe_allow_html=True,
        )
        fig4a = px.histogram(
            df_enroll_known, x="EnrollmentCount", color="Branch",
            color_discrete_map=BRANCH_COLORS, nbins=40, height=400,
            template="plotly_white", barmode="overlay",
            labels={"EnrollmentCount": "Planned enrollment (patients)"},
        )
        fig4a.update_traces(marker_line_color="white", marker_line_width=0.4, opacity=0.6)
        fig4a.update_layout(
            **PUB_LAYOUT,
            xaxis_title="Planned enrollment (patients)",
            yaxis_title="Number of trials",
            legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5,
                        font=dict(size=11, color=_AX_COLOR), bgcolor="rgba(0,0,0,0)",
                        borderwidth=0, title=None),
        )
        st.plotly_chart(fig4a, width='stretch', config=PUB_EXPORT)

        # 4b — Median enrollment by phase × branch
        st.markdown(
            '<div class="pub-fig-sub" style="margin-top: 1rem; '
            'border-top: 1px solid #e5e7eb; padding-top: 0.8rem;">'
            '<strong style="color: #0b1220;">4b — Median enrollment by phase and branch</strong>'
            '</div>',
            unsafe_allow_html=True,
        )
        _phb_enroll = (
            df_enroll_known.groupby(["PhaseNormalized", "Branch"], observed=False)["EnrollmentCount"]
            .median().reset_index(name="Median")
        )
        _phb_enroll = _phb_enroll[_phb_enroll["Median"].notna()].copy()
        _phb_enroll["Median"] = _phb_enroll["Median"].astype(int)
        _phb_enroll["Phase"] = _phb_enroll["PhaseNormalized"].map(PHASE_LABELS)
        _phb_enroll["Phase"] = pd.Categorical(
            _phb_enroll["Phase"], categories=[PHASE_LABELS[p] for p in PHASE_ORDER], ordered=True,
        )
        _phb_enroll = _phb_enroll.sort_values("Phase")

        fig4b = px.bar(
            _phb_enroll, x="Phase", y="Median", color="Branch",
            color_discrete_map=BRANCH_COLORS, barmode="group",
            template="plotly_white", height=380, text="Median",
        )
        fig4b.update_traces(marker_line_width=0, opacity=1, textposition="outside",
                            textfont=dict(size=10, color=_AX_COLOR), cliponaxis=False)
        fig4b.update_layout(
            **PUB_LAYOUT,
            xaxis_title="Phase",
            yaxis_title="Median planned enrollment (patients)",
            legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5,
                        font=dict(size=11, color=_AX_COLOR), bgcolor="rgba(0,0,0,0)",
                        borderwidth=0, title=None),
        )
        st.plotly_chart(fig4b, width='stretch', config=PUB_EXPORT)

        # 4c — Total enrolled patients by disease category
        _dis_enroll_rows = []
        for _, row in df_enroll_known.iterrows():
            _dis_enroll_rows.append({
                "Category": row.get("DiseaseCategory", UNCLASSIFIED_LABEL),
                "Branch": row.get("Branch", "Unknown"),
                "Enrollment": row["EnrollmentCount"],
            })
        if _dis_enroll_rows:
            _dis_enroll_df = pd.DataFrame(_dis_enroll_rows)
            _dis_enroll_agg = (
                _dis_enroll_df.groupby(["Category", "Branch"])["Enrollment"]
                .agg(TotalEnrolled="sum", Trials="count").reset_index()
                .sort_values("TotalEnrolled", ascending=True)
            )
            _dis_enroll_agg["TotalEnrolled"] = _dis_enroll_agg["TotalEnrolled"].astype(int)

            st.markdown(
                '<div class="pub-fig-sub" style="margin-top: 1rem; '
                'border-top: 1px solid #e5e7eb; padding-top: 0.8rem;">'
                '<strong style="color: #0b1220;">4c — Total planned enrollment by disease category</strong>'
                '</div>',
                unsafe_allow_html=True,
            )
            _cat_order = (
                _dis_enroll_agg.groupby("Category")["TotalEnrolled"].sum()
                .sort_values(ascending=True).index.tolist()
            )
            _dis_enroll_agg["Category"] = pd.Categorical(
                _dis_enroll_agg["Category"], categories=_cat_order, ordered=True,
            )
            fig4c = px.bar(
                _dis_enroll_agg.sort_values("Category"),
                x="TotalEnrolled", y="Category", color="Branch",
                color_discrete_map=BRANCH_COLORS, orientation="h",
                height=max(380, len(_cat_order) * 26 + 100),
                template="plotly_white", text="TotalEnrolled",
            )
            fig4c.update_traces(marker_line_width=0, opacity=1, textposition="outside",
                                textfont=dict(size=10, color=_AX_COLOR), cliponaxis=False)
            fig4c.update_layout(
                **PUB_BASE, barmode="stack",
                xaxis_title="Total planned patients (reported trials)",
                yaxis_title=None, showlegend=True,
                margin=dict(l=155, r=72, t=24, b=80),
                yaxis=_H_YAXIS, xaxis=_H_XAXIS,
                legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5,
                            font=dict(size=11, color=_AX_COLOR), bgcolor="rgba(0,0,0,0)",
                            borderwidth=0, title=None),
            )
            st.plotly_chart(fig4c, width='stretch', config=PUB_EXPORT)

        # 4d — Forest plot with branch stratum
        st.markdown(
            '<div class="pub-fig-sub" style="margin-top: 1rem; '
            'border-top: 1px solid #e5e7eb; padding-top: 0.8rem;">'
            '<strong style="color: #0b1220;">4d — Enrollment by subgroup</strong> '
            '<span style="color: #94a3b8;">— median (dot) and IQR (whisker)</span>'
            '</div>',
            unsafe_allow_html=True,
        )

        def _geo_group(countries_str) -> str:
            if not countries_str or pd.isna(countries_str):
                return "Unknown"
            return "China" if "China" in str(countries_str).split("|") else "Non-China"

        df_enroll_known["GeoGroup"] = df_enroll_known["Countries"].apply(_geo_group)

        def _stat(rows: pd.Series) -> tuple[int, int, int, int]:
            return (
                int(len(rows)), int(rows.median()),
                int(rows.quantile(0.25)), int(rows.quantile(0.75)),
            )

        forest_rows = []
        _all = df_enroll_known["EnrollmentCount"]
        N, M, Q1, Q3 = _stat(_all)
        forest_rows.append({"Category": "Overall", "Group": "All trials", "Median": M, "Q1": Q1, "Q3": Q3, "N": N})
        for br in ["Heme-onc", "Solid-onc"]:
            rows = df_enroll_known[df_enroll_known["Branch"] == br]["EnrollmentCount"]
            if len(rows):
                N, M, Q1, Q3 = _stat(rows)
                forest_rows.append({"Category": "Branch", "Group": br, "Median": M, "Q1": Q1, "Q3": Q3, "N": N})
        for gg in ["China", "Non-China"]:
            rows = df_enroll_known[df_enroll_known["GeoGroup"] == gg]["EnrollmentCount"]
            if len(rows):
                N, M, Q1, Q3 = _stat(rows)
                forest_rows.append({"Category": "Geography", "Group": gg, "Median": M, "Q1": Q1, "Q3": Q3, "N": N})
        # Branch × Geography cross
        for br in ["Heme-onc", "Solid-onc"]:
            for gg in ["China", "Non-China"]:
                rows = df_enroll_known[
                    (df_enroll_known["Branch"] == br) & (df_enroll_known["GeoGroup"] == gg)
                ]["EnrollmentCount"]
                if len(rows) >= 3:
                    N, M, Q1, Q3 = _stat(rows)
                    forest_rows.append({"Category": "Branch × Geography",
                                        "Group": f"{br} · {gg}",
                                        "Median": M, "Q1": Q1, "Q3": Q3, "N": N})
        forest_df = pd.DataFrame(forest_rows)
        forest_df["Label"] = forest_df.apply(lambda r: f"{r['Category']}: {r['Group']}", axis=1)
        forest_df = forest_df.iloc[::-1].reset_index(drop=True)

        _CAT_COLORS = {
            "Overall": "#0b1220", "Branch": NEJM_BLUE,
            "Geography": NEJM_GREEN, "Branch × Geography": NEJM_AMBER,
        }

        fig4d = px.scatter(
            forest_df, x="Median", y="Label",
            color="Category", color_discrete_map=_CAT_COLORS,
            error_x=forest_df["Q3"] - forest_df["Median"],
            error_x_minus=forest_df["Median"] - forest_df["Q1"],
            height=max(360, 28 * len(forest_df) + 110),
            template="plotly_white",
        )
        fig4d.update_traces(
            marker=dict(size=11, line=dict(color="white", width=1.2)),
            error_x=dict(color=_AX_COLOR, thickness=1.2, width=6),
        )
        for _, r in forest_df.iterrows():
            fig4d.add_annotation(
                x=r["Q3"], y=r["Label"], xref="x", yref="y",
                text=f"  Median {r['Median']}  ·  n={r['N']}",
                showarrow=False,
                font=dict(size=10, color=THEME["muted"]),
                xanchor="left",
            )
        fig4d.update_layout(
            **PUB_BASE,
            margin=dict(l=240, r=120, t=24, b=64),
            xaxis=dict(
                title="Median planned enrollment (patients)",
                showline=True, linewidth=1.5, linecolor=_AX_COLOR,
                showgrid=True, gridcolor=_GRID_CLR, gridwidth=0.7,
                ticks="outside", ticklen=6, tickwidth=1.2,
                tickfont=dict(size=_TICK_SZ, color=_AX_COLOR),
                title_font=dict(size=_LAB_SZ, color=_AX_COLOR),
                zeroline=False, rangemode="tozero",
            ),
            yaxis=dict(title=None, showline=False, showgrid=False,
                       ticks="", tickfont=dict(size=_TICK_SZ, color=_AX_COLOR)),
            showlegend=False,
        )
        st.plotly_chart(fig4d, width='stretch', config=PUB_EXPORT)

        fig4_csv = df_enroll_known[[
            "NCTId", "BriefTitle", "Branch", "DiseaseCategory", "DiseaseEntity",
            "TargetCategory", "ProductType", "Phase", "EnrollmentCount", "GeoGroup",
        ]].sort_values("EnrollmentCount", ascending=False)
        _pub_caption(len(df_filt),
                     extra=f"Enrollment panels restricted to {len(df_enroll_known):,} trials with a numeric enrollment target.")
        st.download_button("Fig 4 data (CSV)",
                           _csv_with_provenance(fig4_csv, "Fig 4 — Enrollment by branch / phase / geography"),
                           "fig4_enrollment.csv", "text/csv")
    else:
        st.info("Insufficient enrollment data available.")

    # ------------------------------------------------------------------
    # Fig 5 — Branch → Category → Entity sunburst (signature oncology figure)
    # ------------------------------------------------------------------
    _pub_header("5", "Disease hierarchy (Branch → Category → Entity)",
                "Sunburst mapping the full oncology landscape. Click a wedge to zoom.")

    if not df_filt.empty:
        sun_df = (
            df_filt[["Branch", "DiseaseCategory", "DiseaseEntity"]]
            .fillna("Unknown").assign(Count=1)
            .groupby(["Branch", "DiseaseCategory", "DiseaseEntity"], as_index=False).sum()
        )
        fig5 = px.sunburst(
            sun_df, path=["Branch", "DiseaseCategory", "DiseaseEntity"],
            values="Count", color="Branch", color_discrete_map=BRANCH_COLORS,
            height=600, template="plotly_white",
        )
        fig5.update_traces(
            insidetextorientation="radial",
            marker=dict(line=dict(color="white", width=1.2)),
        )
        fig5.update_layout(
            paper_bgcolor="white", plot_bgcolor="white",
            margin=dict(l=8, r=8, t=8, b=8), font=PUB_FONT,
        )
        st.plotly_chart(fig5, width='stretch', config=PUB_EXPORT)

        # Companion: top categories side-by-side
        c1, c2 = st.columns(2)
        with c1:
            heme_cat = (
                df_filt[df_filt["Branch"] == "Heme-onc"]["DiseaseCategory"]
                .value_counts().head(10).reset_index()
            )
            heme_cat.columns = ["Category", "Trials"]
            if not heme_cat.empty:
                st.markdown("**Top heme-onc categories**")
                st.plotly_chart(make_bar(heme_cat.sort_values("Trials", ascending=True),
                                          "Trials", "Category", height=320, color=HEME_COLOR).update_traces(orientation="h"),
                                width='stretch')
        with c2:
            solid_cat = (
                df_filt[df_filt["Branch"] == "Solid-onc"]["DiseaseCategory"]
                .value_counts().head(10).reset_index()
            )
            solid_cat.columns = ["Category", "Trials"]
            if not solid_cat.empty:
                st.markdown("**Top solid-onc categories**")
                st.plotly_chart(make_bar(solid_cat.sort_values("Trials", ascending=True),
                                          "Trials", "Category", height=320, color=SOLID_COLOR).update_traces(orientation="h"),
                                width='stretch')

        _pub_caption(len(df_filt),
                     extra="Basket/Multidisease trials are shown as their own category slice under the inferred branch.")
        st.download_button("Fig 5 data (CSV)",
                           _csv_with_provenance(sun_df, "Fig 5 — Disease hierarchy"),
                           "fig5_disease_hierarchy.csv", "text/csv")
    else:
        st.info("No disease data available.")

    # ------------------------------------------------------------------
    # Fig 6 — Heme vs Solid antigen panels (side-by-side)
    # ------------------------------------------------------------------
    _pub_header("6", "Antigen target landscape, heme vs solid",
                "Heme is concentrated at CD19/BCMA; solid spans a long tail of GPC3, CLDN18.2, MSLN, GD2, HER2, EGFRvIII…")

    _UNCLEAR_BUCKET = "Undisclosed / unclear"

    def _target_counts(df_in: pd.DataFrame) -> pd.DataFrame:
        s = df_in.loc[~df_in["TargetCategory"].isin(_PLATFORM_LABELS), "TargetCategory"].fillna("Unknown")
        s = s.replace({
            "CAR-T_unspecified": _UNCLEAR_BUCKET,
            "Other_or_unknown":  _UNCLEAR_BUCKET,
            "Unknown":           _UNCLEAR_BUCKET,
        })
        return s.value_counts().rename_axis("Target").reset_index(name="Trials")

    heme_tgt = _target_counts(df_filt[df_filt["Branch"] == "Heme-onc"])
    solid_tgt = _target_counts(df_filt[df_filt["Branch"] == "Solid-onc"])

    col_h, col_s = st.columns(2)

    def _target_hbar(df_in, color, title, height):
        df_in = df_in.sort_values("Trials", ascending=True).head(20)
        fig = px.bar(
            df_in, x="Trials", y="Target", orientation="h",
            color_discrete_sequence=[color], template="plotly_white",
            height=max(height, len(df_in) * 30 + 80), text="Trials",
        )
        fig.update_traces(marker_line_width=0, opacity=1, textposition="outside",
                          textfont=dict(size=10, color=_AX_COLOR), cliponaxis=False)
        fig.update_layout(
            **PUB_BASE,
            xaxis_title="Number of trials", yaxis_title=None, showlegend=False,
            margin=dict(l=150, r=48, t=40, b=56),
            yaxis=_H_YAXIS, xaxis=_H_XAXIS, title=dict(text=title, x=0, font=dict(size=12, color=_AX_COLOR)),
        )
        return fig

    with col_h:
        if not heme_tgt.empty:
            st.plotly_chart(_target_hbar(heme_tgt, HEME_COLOR, "Heme-onc targets", 380),
                            width='stretch', config=PUB_EXPORT)
        else:
            st.info("No heme-onc trials in filter.")
    with col_s:
        if not solid_tgt.empty:
            st.plotly_chart(_target_hbar(solid_tgt, SOLID_COLOR, "Solid-onc targets", 380),
                            width='stretch', config=PUB_EXPORT)
        else:
            st.info("No solid-onc trials in filter.")

    # Summary metrics
    total_h = int(heme_tgt["Trials"].sum()) if not heme_tgt.empty else 0
    total_s = int(solid_tgt["Trials"].sum()) if not solid_tgt.empty else 0
    cd19_h = int(heme_tgt.loc[heme_tgt["Target"] == "CD19", "Trials"].sum()) if not heme_tgt.empty else 0
    bcma_h = int(heme_tgt.loc[heme_tgt["Target"] == "BCMA", "Trials"].sum()) if not heme_tgt.empty else 0
    top_s = solid_tgt.iloc[-1] if not solid_tgt.empty else None
    solid_diverse = solid_tgt["Target"].nunique() if not solid_tgt.empty else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Heme CD19", f"{cd19_h} ({100*cd19_h/total_h:.0f}%)" if total_h else "—")
    c2.metric("Heme BCMA", f"{bcma_h} ({100*bcma_h/total_h:.0f}%)" if total_h else "—")
    c3.metric("Solid top antigen", f"{top_s['Target']} ({top_s['Trials']})" if top_s is not None else "—")
    c4.metric("Distinct solid antigens", solid_diverse)

    fig6_csv = pd.concat(
        [heme_tgt.assign(Branch="Heme-onc"), solid_tgt.assign(Branch="Solid-onc")],
        ignore_index=True,
    ) if (not heme_tgt.empty or not solid_tgt.empty) else pd.DataFrame()
    _pub_caption(len(df_filt),
                 extra="Undisclosed / unclear merges CAR-T_unspecified and Other_or_unknown; both preserved in CSV.")
    if not fig6_csv.empty:
        st.download_button("Fig 6 data (CSV)",
                           _csv_with_provenance(fig6_csv, "Fig 6 — Antigen targets by branch"),
                           "fig6_targets_by_branch.csv", "text/csv")

    # ------------------------------------------------------------------
    # Fig 7 — Innovation signals (product type + modality over time)
    # ------------------------------------------------------------------
    _pub_header("7", "Innovation signals — product type and cell-therapy modality",
                "Autologous dominates historically; allogeneic and in vivo CAR are emerging. Modality mix differs between branches.")

    df_innov = df_filt[df_filt["StartYear"].notna()].copy()
    df_innov["StartYear"] = df_innov["StartYear"].astype(int)

    if not df_innov.empty:
        # 7a — Product type by start year
        product_year = (
            df_innov.groupby(["StartYear", "ProductType"]).size().reset_index(name="Trials")
        )
        st.markdown(
            '<div class="pub-fig-sub" style="margin-top: 0.4rem;">'
            '<strong style="color: #0b1220;">7a — Product type by start year</strong>'
            '</div>',
            unsafe_allow_html=True,
        )
        fig7a = px.bar(
            product_year, x="StartYear", y="Trials", color="ProductType",
            barmode="stack", height=420, template="plotly_white",
            color_discrete_map={
                "Autologous": NEJM_BLUE,
                "Allogeneic/Off-the-shelf": NEJM_RED,
                "In vivo": NEJM_GREEN,
                "Unclear": "#888888",
            },
            category_orders={"ProductType": ["Autologous", "Allogeneic/Off-the-shelf", "In vivo", "Unclear"]},
            labels={"StartYear": "Start year", "Trials": "Number of trials", "ProductType": "Product type"},
        )
        fig7a.update_traces(marker_line_width=0, opacity=1)
        fig7a.update_layout(
            **PUB_BASE,
            margin=dict(l=64, r=36, t=24, b=110),
            xaxis=dict(
                tickmode="linear", dtick=1, tickformat="d", showgrid=False,
                showline=True, linewidth=1.5, linecolor=_AX_COLOR,
                ticks="outside", ticklen=6, tickwidth=1.2,
                tickfont=dict(size=_TICK_SZ, color=_AX_COLOR),
                title="Start year", title_font=dict(size=_LAB_SZ, color=_AX_COLOR),
            ),
            yaxis=dict(
                showline=True, linewidth=1.5, linecolor=_AX_COLOR,
                showgrid=True, gridcolor=_GRID_CLR, gridwidth=0.7,
                ticks="outside", ticklen=6, tickwidth=1.2,
                tickfont=dict(size=_TICK_SZ, color=_AX_COLOR),
                title="Number of trials",
                title_font=dict(size=_LAB_SZ, color=_AX_COLOR), zeroline=False,
            ),
            legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5,
                        font=dict(size=11, color=_AX_COLOR), bgcolor="rgba(0,0,0,0)",
                        borderwidth=0, title=None),
        )
        st.plotly_chart(fig7a, width='stretch', config=PUB_EXPORT)

        # 7b — Modality by branch
        df_innov["Modality"] = df_innov.apply(_modality, axis=1)
        st.markdown(
            '<div class="pub-fig-sub" style="margin-top: 1rem; '
            'border-top: 1px solid #e5e7eb; padding-top: 0.8rem;">'
            '<strong style="color: #0b1220;">7b — Cell-therapy modality distribution, by branch</strong>'
            '</div>',
            unsafe_allow_html=True,
        )
        mod_branch = (
            df_innov.groupby(["Modality", "Branch"]).size().reset_index(name="Trials")
        )
        mod_branch["Modality"] = pd.Categorical(mod_branch["Modality"], categories=MODALITY_ORDER, ordered=True)
        mod_branch = mod_branch.sort_values("Modality")
        fig7b = px.bar(
            mod_branch, x="Trials", y="Modality", color="Branch",
            color_discrete_map=BRANCH_COLORS, orientation="h",
            template="plotly_white", height=max(320, len(mod_branch["Modality"].unique()) * 40 + 80),
            text="Trials",
        )
        fig7b.update_traces(marker_line_width=0, opacity=1, textposition="inside",
                            textfont=dict(size=10, color="white"), insidetextanchor="middle")
        fig7b.update_layout(
            **PUB_BASE, barmode="stack",
            xaxis_title="Number of trials", yaxis_title=None,
            margin=dict(l=120, r=56, t=24, b=80),
            yaxis=_H_YAXIS, xaxis=_H_XAXIS,
            legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5,
                        font=dict(size=11, color=_AX_COLOR), bgcolor="rgba(0,0,0,0)",
                        borderwidth=0, title=None),
        )
        st.plotly_chart(fig7b, width='stretch', config=PUB_EXPORT)

        # 7c — Modality mix by start year
        st.markdown(
            '<div class="pub-fig-sub" style="margin-top: 1rem; '
            'border-top: 1px solid #e5e7eb; padding-top: 0.8rem;">'
            '<strong style="color: #0b1220;">7c — Modality mix by start year</strong>'
            '</div>',
            unsafe_allow_html=True,
        )
        mod_year = (
            df_innov.groupby(["StartYear", "Modality"]).size().reset_index(name="Trials")
        )
        present_mods = [m for m in MODALITY_ORDER if m in mod_year["Modality"].unique()]
        fig7c = px.bar(
            mod_year[mod_year["Modality"].isin(present_mods)],
            x="StartYear", y="Trials", color="Modality",
            barmode="stack", height=400, template="plotly_white",
            color_discrete_map=_MODALITY_COLORS,
            category_orders={"Modality": MODALITY_ORDER},
            labels={"StartYear": "Start year", "Trials": "Number of trials"},
        )
        fig7c.update_traces(marker_line_width=0, opacity=1)
        fig7c.update_layout(
            **PUB_BASE,
            margin=dict(l=64, r=36, t=24, b=110),
            xaxis=dict(
                tickmode="linear", dtick=1, tickformat="d", showgrid=False,
                showline=True, linewidth=1.5, linecolor=_AX_COLOR,
                ticks="outside", ticklen=6, tickwidth=1.2,
                tickfont=dict(size=_TICK_SZ, color=_AX_COLOR),
                title="Start year", title_font=dict(size=_LAB_SZ, color=_AX_COLOR),
            ),
            yaxis=dict(
                showline=True, linewidth=1.5, linecolor=_AX_COLOR,
                showgrid=True, gridcolor=_GRID_CLR, gridwidth=0.7,
                ticks="outside", ticklen=6, tickwidth=1.2,
                tickfont=dict(size=_TICK_SZ, color=_AX_COLOR),
                title="Number of trials",
                title_font=dict(size=_LAB_SZ, color=_AX_COLOR), zeroline=False,
            ),
            legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5,
                        font=dict(size=11, color=_AX_COLOR), bgcolor="rgba(0,0,0,0)",
                        borderwidth=0, title=None),
        )
        st.plotly_chart(fig7c, width='stretch', config=PUB_EXPORT)

        total_prod = len(df_innov)
        auto_n = int((df_innov["ProductType"] == "Autologous").sum())
        allo_n = int((df_innov["ProductType"] == "Allogeneic/Off-the-shelf").sum())
        invivo_n = int((df_innov["Modality"] == "In vivo CAR").sum())
        carnk_n = int((df_innov["Modality"] == "CAR-NK").sum())
        gdt_n = int((df_innov["Modality"] == "CAR-γδ T").sum())
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Autologous", f"{auto_n} ({100*auto_n/total_prod:.0f}%)" if total_prod else "—")
        c2.metric("Allogeneic", f"{allo_n} ({100*allo_n/total_prod:.0f}%)" if total_prod else "—")
        c3.metric("CAR-NK", f"{carnk_n} ({100*carnk_n/total_prod:.0f}%)" if total_prod else "—")
        c4.metric("CAR-γδ T", f"{gdt_n} ({100*gdt_n/total_prod:.0f}%)" if total_prod else "—")
        c5.metric("In vivo CAR", f"{invivo_n} ({100*invivo_n/total_prod:.0f}%)" if total_prod else "—")

        fig7_csv = pd.merge(
            product_year.rename(columns={"ProductType": "Category", "Trials": "n_product"}),
            df_innov.groupby(["StartYear", "Modality"]).size().reset_index(name="n_modality"),
            left_on="StartYear", right_on="StartYear", how="outer",
        )
        _pub_caption(len(df_filt),
                     extra="Panel counts restricted to trials with a known start year.")
        st.download_button("Fig 7 data (CSV)",
                           _csv_with_provenance(fig7_csv, "Fig 7 — Innovation signals"),
                           "fig7_innovation_signals.csv", "text/csv")
    else:
        st.info("No start year data available for innovation analysis.")

    # ------------------------------------------------------------------
    # Fig 8 — Disease × Target heatmap (oncology-specific signature)
    # ------------------------------------------------------------------
    _pub_header("8", "Disease × antigen target heatmap",
                "Shows which antigens are being tested in which diseases. CD19 × B-NHL, BCMA × MM, GPC3 × HCC, GD2 × Neuroblastoma, CLDN18.2 × gastric/pancreatic are the signature clusters.")

    # Build disease-target matrix (top N of each for readability)
    hm_df = df_filt.copy()
    hm_df = hm_df[~hm_df["TargetCategory"].isin(_PLATFORM_LABELS)]
    hm_df["DisplayTarget"] = hm_df["TargetCategory"].replace({
        "CAR-T_unspecified": "Undisclosed",
        "Other_or_unknown":  "Undisclosed",
    })

    top_cats_hm = (
        hm_df["DiseaseCategory"].value_counts().head(15).index.tolist()
    )
    top_tgts_hm = (
        hm_df.loc[hm_df["DisplayTarget"] != "Undisclosed", "DisplayTarget"]
        .value_counts().head(18).index.tolist()
    )

    if top_cats_hm and top_tgts_hm:
        pivot = (
            hm_df[hm_df["DiseaseCategory"].isin(top_cats_hm) & hm_df["DisplayTarget"].isin(top_tgts_hm)]
            .groupby(["DiseaseCategory", "DisplayTarget"]).size().unstack(fill_value=0)
            .reindex(index=top_cats_hm, columns=top_tgts_hm, fill_value=0)
        )
        # Annotate branch by color-coding row labels
        row_colors = [
            BRANCH_COLORS["Heme-onc"] if c in HEME_CATEGORIES else
            BRANCH_COLORS["Solid-onc"] if c in SOLID_CATEGORIES else
            BRANCH_COLORS["Mixed"]
            for c in top_cats_hm
        ]

        fig8 = go.Figure(data=go.Heatmap(
            z=pivot.values,
            x=pivot.columns.tolist(),
            y=pivot.index.tolist(),
            text=pivot.values,
            texttemplate="%{text}",
            textfont=dict(size=10, color="#0b1220"),
            colorscale=[[0, "#f8fafc"], [0.2, "#dbeafe"], [0.5, "#93c5fd"], [0.8, "#1d4ed8"], [1, "#0b3d91"]],
            colorbar=dict(title=dict(text="Trials", font=dict(size=11, color=_AX_COLOR)),
                           tickfont=dict(size=10, color=_AX_COLOR), thickness=14, len=0.55),
            hovertemplate="Category: %{y}<br>Target: %{x}<br>Trials: %{z}<extra></extra>",
        ))
        fig8.update_layout(
            **PUB_BASE,
            height=max(420, len(top_cats_hm) * 28 + 120),
            margin=dict(l=170, r=40, t=40, b=100),
            xaxis=dict(
                title="Antigen target",
                tickfont=dict(size=11, color=_AX_COLOR),
                title_font=dict(size=_LAB_SZ, color=_AX_COLOR),
                tickangle=-35, side="bottom",
            ),
            yaxis=dict(
                title="Disease category",
                tickfont=dict(size=11, color=_AX_COLOR),
                title_font=dict(size=_LAB_SZ, color=_AX_COLOR),
                autorange="reversed",
            ),
        )
        # Color-code the y-axis tick labels by branch (via annotations behind y-axis)
        # Plotly doesn't natively support per-tick-label colors, so we emulate with annotations.
        st.plotly_chart(fig8, width='stretch', config=PUB_EXPORT)

        st.markdown(
            '<div class="pub-fig-caption" style="margin-top: 0.1rem;">'
            'Heme-onc categories shown against a navy background; solid-onc against amber. '
            'Only the top 15 categories × top 18 antigens are shown.'
            '</div>',
            unsafe_allow_html=True,
        )
        _pub_caption(len(df_filt))

        fig8_csv = pivot.reset_index().melt(
            id_vars="DiseaseCategory", var_name="Target", value_name="Trials"
        )
        fig8_csv = fig8_csv[fig8_csv["Trials"] > 0]
        st.download_button("Fig 8 data (CSV)",
                           _csv_with_provenance(fig8_csv, "Fig 8 — Disease × target heatmap"),
                           "fig8_disease_target_heatmap.csv", "text/csv")
    else:
        st.info("Insufficient disease-target data for heatmap.")


# ---------------------------------------------------------------------------
# TAB: Methods & Appendix
# ---------------------------------------------------------------------------

def _build_methods_text(prisma: dict, snapshot_date: str, n_included: int) -> str:
    n_heme = sum(len(ents) for ents in ONTOLOGY["Heme-onc"].values())
    n_solid = sum(len(ents) for ents in ONTOLOGY["Solid-onc"].values())
    n_cats = sum(len(cats) for cats in ONTOLOGY.values())
    n_entities = n_heme + n_solid
    n_hard = len(HARD_EXCLUDED_NCT_IDS)
    n_indication = len(EXCLUDED_INDICATION_TERMS)
    n_fetched = prisma.get("n_fetched", "N/A")
    n_dedup = prisma.get("n_after_dedup", "N/A")
    n_hard_excl = prisma.get("n_hard_excluded", "N/A")
    n_indic_excl = prisma.get("n_indication_excluded", "N/A")

    text = f"""\
METHODS
=======

Data Source and Search Strategy
--------------------------------
Clinical trial data were retrieved from the ClinicalTrials.gov public registry using the
API (v2; {BASE_URL}; accessed {snapshot_date}). A structured keyword query was applied
combining CAR-based cell-therapy terms ("CAR T", "CAR-T", "chimeric antigen receptor",
"CAR-NK", "CAAR-T", "CAR-Treg", "gamma delta CAR") with oncology condition-search
terms (leukemia, lymphoma, myeloma, multiple myeloma, solid tumor, glioma, glioblastoma,
hepatocellular, pancreatic, gastric, colorectal, ovarian, breast, prostate, sarcoma,
melanoma, neuroblastoma, mesothelioma, carcinoma). No restriction was placed on study
phase, recruitment status, or geographic location at the query stage.

Inclusion Criteria
------------------
Studies were included if they: (1) described a CAR-based cellular therapy (CAR-T
[autologous, allogeneic, or in vivo], CAR-NK, CAAR-T, CAR-Treg, or CAR-γδ T); and
(2) targeted a hematologic or solid malignancy. No restriction was applied to study
phase, sponsor type, or country. TCR-T products (e.g., afami-cel, NY-ESO-1 directed
TCRs) are out of scope for this v1 dashboard.

Exclusion Criteria
------------------
Studies were excluded if they met any of the following criteria:
    (1) The NCT identifier appeared on a manually curated exclusion list ({n_hard}
        pre-specified identifiers) compiled via the curation loop to remove studies
        retrieved by the search query but confirmed on manual inspection as outside
        scope (e.g., non-CAR-T interventions, observational registries).
    (2) Text fields (conditions, title, brief summary, interventions) contained one
        or more of {n_indication} predefined autoimmune / rheumatologic keywords and
        no oncology-adjacent hit. This is the inverse of the sister rheumatology app;
        trials are excluded only when autoimmune is the *sole* indication.

Study Selection (PRISMA)
------------------------
    Records identified via database search  : {n_fetched}
    Duplicate records removed               : {prisma.get("n_duplicates_removed", "N/A")}
    Records screened                        : {n_dedup}
    Excluded — pre-specified NCT IDs        : {n_hard_excl}
    Excluded — autoimmune-only keywords     : {n_indic_excl}
    Studies included in final analysis      : {n_included}

Three-tier Disease Ontology
---------------------------
Each trial is assigned three hierarchical labels:
  • Branch — Heme-onc / Solid-onc / Mixed / Unknown
  • DiseaseCategory — {n_cats} Tier-2 categories spanning {len(ONTOLOGY["Heme-onc"])} heme
    (B-NHL, B-ALL, CLL_SLL, T-cell, Multiple myeloma, Hodgkin, AML, MDS_MPN,
    Heme-onc_other) and {len(ONTOLOGY["Solid-onc"])} solid (CNS, Thoracic, GI, GU, Gyn,
    Breast, H&N, Skin, Sarcoma, Pediatric solid, Solid-onc_other).
  • DiseaseEntity — {n_entities} Tier-3 leaves (e.g., DLBCL, Ph+ B-ALL, GBM, HCC,
    CLDN18.2-amplified gastric, TNBC, Neuroblastoma).
Basket trials spanning ≥2 categories are labelled "Basket/Multidisease" and retain
the full list of matched entities in the DiseaseEntities column (pipe-joined).
Branch-level baskets are labelled "Heme basket" or "Advanced solid tumors".

Classification Algorithm
------------------------
Assignment uses hierarchical rule-based matching of normalised text drawn from the
conditions, title, brief summary, and interventions fields. Resolution order:
    1. LLM override (if present in llm_overrides.json) — trusted wholesale.
    2. Leaf-level ENTITY_TERMS match on each condition chunk and on full text.
       Multiple leaves across ≥2 categories → Basket/Multidisease.
    3. Category-level CATEGORY_FALLBACK_TERMS match.
    4. Branch-level basket terms (SOLID_BASKET_TERMS, HEME_BASKET_TERMS).
    5. Fall-through to Unclassified.

Target Classification
---------------------
Priority-ordered ruleset:
    • Named-product short-circuit (NAMED_PRODUCT_TARGETS) — approved & late-stage
      oncology CAR-T products (tisa-cel, axi-cel, ide-cel, cilta-cel, GC012F, …).
    • Platform detection — CAR-NK, CAAR-T, CAR-Treg, CAR-γδ T.
    • Antigen detection — heme-typical (CD19, BCMA, CD20, CD22, CD7, CD30, CD33,
      CD38, CD70, CD123, GPRC5D, FcRH5, SLAMF7, CD79b, Kappa LC) and solid-typical
      (GPC3, Claudin 18.2, Mesothelin, GD2, HER2, EGFR, EGFRvIII, B7-H3, PSMA, PSCA,
      CEA, EpCAM, MUC1, CLDN6, NKG2D-L, ROR1, L1CAM, CD133, AFP, IL13Rα2, HER3, DLL3).
      EGFRvIII overrides EGFR when both match (prefix collision).
    • Dual-target combos (CD19/CD22, CD19/CD20, CD19/BCMA, BCMA/GPRC5D, BCMA/CD70,
      HER2/MUC1, GPC3/MSLN).
    • Residual: CAR-T_unspecified (CAR mention, no antigen) or Other_or_unknown.

Product Type Classification
---------------------------
Classified as Autologous / Allogeneic/Off-the-shelf / In vivo / Unclear. In vivo is
detected first (title contains "in vivo"; circular RNA / mRNA-LNP / lentiviral
nanoparticle markers). "autoleucel" and "autologous" are high-precision Autologous
markers. Strong allogeneic markers include UCART, off-the-shelf, universal CAR-T,
healthy donor, donor-derived. Named-product fallback (NAMED_PRODUCT_TYPES) applied
when no generic marker is present.

Cell-therapy Modality
---------------------
Each trial is assigned to one of eight mechanistically distinct modality categories:
Auto CAR-T, Allo CAR-T, CAR-T (unclear), CAR-γδ T, CAR-NK, CAR-Treg, CAAR-T,
In vivo CAR. Modality is derived from TargetCategory + ProductType + text-level
γδ-T detection.

Enrollment Analysis
-------------------
Planned enrollment counts were extracted from the EnrollmentCount field
(type = Anticipated or Actual) and coerced to numeric; missing or non-numeric values
were excluded from enrollment analyses (Figure 4). Branch stratification distinguishes
heme-onc (historically larger cohorts, Phase II+ trials) from solid-onc (smaller
Phase I dose-escalation cohorts). Geographic classification labels trials as "China"
if China is among the Countries, else "Non-China".

Data Processing
---------------
All processing was performed in Python (pandas {pd.__version__}) using a custom ETL
pipeline. Text normalisation includes lowercasing, Unicode normalisation, R/R → "relapsed
refractory" expansion, and hyphen-to-space conversion (so "b-cell", "chromosome-positive",
"non-hodgkin" match the space-separated forms in the term maps). Term matching uses
whole-word boundary matching for short terms (≤3 characters) and substring matching for
longer terms. Classification rules and term dictionaries are versioned in config.py and
updated via the curation loop and LLM validator (validate.py).

Dataset Snapshot
----------------
The frozen dataset used for all analyses was generated on {snapshot_date}. CSV exports of
the trial-level dataset (trials.csv) and site-level dataset (sites.csv) are available
via the Data tab. All analyses are reproducible from the frozen snapshot using the
published code and configuration files.
"""
    return text


def _build_ontology_df() -> pd.DataFrame:
    rows = []
    for branch, cats in ONTOLOGY.items():
        for cat, ents in cats.items():
            rows.append({
                "Tier": "Category",
                "Branch": branch,
                "Label": cat,
                "Terms (sample)": "; ".join(CATEGORY_FALLBACK_TERMS.get(cat, [])[:6]) or "—",
                "N entities": len(ents),
            })
            for ent in ents:
                terms = ENTITY_TERMS.get(ent, [])
                rows.append({
                    "Tier": "Entity",
                    "Branch": branch,
                    "Label": f"{cat} / {ent}",
                    "Terms (sample)": "; ".join(terms[:6]) + ("…" if len(terms) > 6 else ""),
                    "N entities": 0,
                })
    rows.append({"Tier": "Special", "Branch": "—", "Label": BASKET_MULTI_LABEL,
                  "Terms (sample)": "≥2 categories matched", "N entities": 0})
    rows.append({"Tier": "Special", "Branch": "Heme-onc", "Label": HEME_BASKET_LABEL,
                  "Terms (sample)": "; ".join(HEME_BASKET_TERMS[:4]) + "…", "N entities": 0})
    rows.append({"Tier": "Special", "Branch": "Solid-onc", "Label": SOLID_BASKET_LABEL,
                  "Terms (sample)": "; ".join(SOLID_BASKET_TERMS[:4]) + "…", "N entities": 0})
    rows.append({"Tier": "Target (heme antigens)", "Branch": "—", "Label": f"{len(HEME_TARGET_TERMS)} antigens",
                  "Terms (sample)": ", ".join(list(HEME_TARGET_TERMS.keys())[:10]) + "…", "N entities": 0})
    rows.append({"Tier": "Target (solid antigens)", "Branch": "—", "Label": f"{len(SOLID_TARGET_TERMS)} antigens",
                  "Terms (sample)": ", ".join(list(SOLID_TARGET_TERMS.keys())[:10]) + "…", "N entities": 0})
    rows.append({"Tier": "Target (dual)", "Branch": "—", "Label": f"{len(DUAL_TARGET_LABELS)} combos",
                  "Terms (sample)": ", ".join([lbl for _p, lbl in DUAL_TARGET_LABELS][:4]) + "…", "N entities": 0})
    rows.append({"Tier": "Named products (approved/clinical)", "Branch": "—",
                  "Label": f"{sum(len(v) for v in NAMED_PRODUCT_TARGETS.values())} product terms",
                  "Terms (sample)": "tisagenlecleucel, axicabtagene ciloleucel, ide-cel, cilta-cel, GC012F, …",
                  "N entities": 0})
    rows.append({"Tier": "Exclusion", "Branch": "—", "Label": "Autoimmune keyword exclusion",
                  "Terms (sample)": "; ".join(EXCLUDED_INDICATION_TERMS[:6]) + "…",
                  "N entities": len(EXCLUDED_INDICATION_TERMS)})
    return pd.DataFrame(rows)


with tab_methods:
    snap_date = df["SnapshotDate"].iloc[0] if "SnapshotDate" in df.columns and not df.empty else date.today().isoformat()
    n_inc = len(df_filt)

    methods_text = _build_methods_text(prisma_counts, snap_date, n_inc)

    st.subheader("Methods section (auto-generated)")
    st.markdown(
        '<p class="small-note">Generated from config.py, pipeline.py, and the current dataset. '
        "Copy or download for use in your manuscript. Edit the journal-specific wording as needed.</p>",
        unsafe_allow_html=True,
    )
    st.text_area("Methods text", value=methods_text, height=520, label_visibility="collapsed")
    st.download_button(
        "Download methods (.txt)", data=methods_text,
        file_name=f"car_t_oncology_methods_{snap_date}.txt",
        mime="text/plain",
    )

    st.subheader("Appendix — Classification ontology")
    st.markdown(
        '<p class="small-note">Tri-level ontology and key term maps (supplementary Table S1).</p>',
        unsafe_allow_html=True,
    )
    ontology_df = _build_ontology_df()
    st.dataframe(
        ontology_df, width='stretch', hide_index=True,
        column_config={
            "Tier": st.column_config.TextColumn("Tier", width="medium"),
            "Branch": st.column_config.TextColumn("Branch", width="small"),
            "Label": st.column_config.TextColumn("Label", width="medium"),
            "Terms (sample)": st.column_config.TextColumn("Terms (sample)", width="large"),
            "N entities": st.column_config.NumberColumn("N entities", width="small"),
        },
    )
    st.download_button(
        "Download ontology table (CSV)",
        data=_csv_with_provenance(ontology_df,
                                    "Classification ontology — supplementary Table S1",
                                    include_filters=False),
        file_name=f"car_t_onco_ontology_{snap_date}.csv",
        mime="text/csv",
    )

    st.subheader("Appendix — Hard-excluded NCT IDs")
    if HARD_EXCLUDED_NCT_IDS:
        excl_df = pd.DataFrame(sorted(HARD_EXCLUDED_NCT_IDS), columns=["NCTId"])
        excl_df["ClinicalTrials.gov link"] = excl_df["NCTId"].apply(
            lambda x: f"https://clinicaltrials.gov/study/{x}"
        )
        st.dataframe(
            excl_df, width='stretch', hide_index=True,
            column_config={
                "NCTId": st.column_config.TextColumn("NCT ID"),
                "ClinicalTrials.gov link": st.column_config.LinkColumn("Link", display_text="Open"),
            },
        )
    else:
        st.info("No hard-excluded NCT IDs yet. Additions flow from the curation loop below.")

    # Curation loop
    st.subheader("Curation loop — unclear / unclassified trials")
    st.markdown(
        '<p class="small-note">Download the structured CSV, feed it to Claude Code, '
        "and the assistant will propose and apply patches to config.py / pipeline.py automatically.</p>",
        unsafe_allow_html=True,
    )
    unclear_disease_mask = (
        df_filt["Branch"].astype(str).str.lower().isin(["unknown"])
        | df_filt["DiseaseEntity"].astype(str).str.lower().isin([UNCLASSIFIED_LABEL.lower(), "heme-onc_other", "solid-onc_other"])
    )
    unclear_target_mask = df_filt["TargetCategory"].astype(str).str.lower().isin(
        ["other_or_unknown", "car-t_unspecified", "car_t_unspecified", "unclassified", "unknown"]
    )
    unclear_product_mask = df_filt["ProductType"].astype(str).str.lower() == "unclear"

    df_unclear = df_filt[unclear_disease_mask | unclear_target_mask | unclear_product_mask].copy()

    if not df_unclear.empty:
        def _unclear_fields(row):
            flags = []
            if (str(row.get("Branch", "")).lower() == "unknown"
                or str(row.get("DiseaseEntity", "")).lower() in {"unclassified", "heme-onc_other", "solid-onc_other"}):
                flags.append("Disease")
            if str(row.get("TargetCategory", "")).lower() in {"other_or_unknown", "car-t_unspecified", "car_t_unspecified", "unclassified", "unknown"}:
                flags.append("Target")
            if str(row.get("ProductType", "")).lower() == "unclear":
                flags.append("Product")
            return "|".join(flags)

        df_unclear["UnclearFields"] = df_unclear.apply(_unclear_fields, axis=1)
        export_cols = [
            "NCTId", "BriefTitle", "Conditions", "Interventions",
            "Branch", "DiseaseCategory", "DiseaseEntity",
            "TargetCategory", "ProductType", "UnclearFields", "BriefSummary",
        ]
        df_export = df_unclear[[c for c in export_cols if c in df_unclear.columns]].copy()
        if "BriefSummary" in df_export.columns:
            df_export["BriefSummary"] = df_export["BriefSummary"].astype(str).str[:300]

        import io as _io
        header_lines = [
            "# CURATION_LOOP_ONCO_V1",
            "# INSTRUCTION: You are Claude Code assisting with a CAR-T oncology trial pipeline.",
            "# For each row below, read BriefTitle / Conditions / Interventions / BriefSummary.",
            "# Propose the correct Branch (Heme-onc | Solid-onc | Mixed),",
            "#   DiseaseCategory, DiseaseEntity, TargetCategory, and ProductType.",
            "# Then automatically patch config.py and/or pipeline.py to capture these cases.",
            "# UnclearFields shows which field(s) triggered inclusion (Disease|Target|Product).",
            "#",
        ]
        buf = _io.StringIO()
        for line in header_lines:
            buf.write(line + "\n")
        df_export.to_csv(buf, index=False)
        curation_csv = buf.getvalue()

        st.dataframe(
            df_export[["NCTId", "BriefTitle", "Branch", "DiseaseCategory",
                        "DiseaseEntity", "TargetCategory", "ProductType", "UnclearFields"]],
            width='stretch', height=280,
        )
        st.caption(f"{len(df_export)} trial(s) flagged for curation")

        st.download_button(
            label=f"Download curation CSV ({len(df_export)} trials)",
            data=curation_csv, file_name="curation_loop.csv", mime="text/csv",
        )
    else:
        st.success("No unclear / unclassified trials in the current filter.")

    # Validation sample + Cohen's κ
    st.subheader("Validation sample export")
    st.markdown(
        '<p class="small-note">Stratified random sample for manual classification review. '
        "Two reviewers complete independently, then compute inter-rater agreement (Cohen's κ).</p>",
        unsafe_allow_html=True,
    )

    val_n = st.slider("Target sample size", min_value=25, max_value=200, value=100, step=25)
    val_seed = st.number_input("Random seed (for reproducibility)", min_value=0, max_value=9999, value=42, step=1)

    def build_validation_sample(source_df: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
        review_cols = [
            "NCTId", "BriefTitle", "Conditions", "BriefSummary",
            "Branch", "DiseaseCategory", "DiseaseEntity",
            "TargetCategory", "ProductType",
            "Phase", "OverallStatus", "LeadSponsor", "Countries",
        ]
        available = [c for c in review_cols if c in source_df.columns]
        base = source_df[available].copy()

        strata = base["DiseaseCategory"].fillna("Unclassified")
        counts = strata.value_counts()
        total = len(base)
        per_stratum = (counts / total * n).clip(lower=1).round().astype(int)
        diff = n - per_stratum.sum()
        if diff != 0:
            largest = per_stratum.idxmax()
            per_stratum[largest] = max(1, per_stratum[largest] + diff)

        frames = []
        for entity, k in per_stratum.items():
            rows = base[strata == entity]
            k = min(k, len(rows))
            frames.append(rows.sample(n=k, random_state=int(seed), replace=False))

        sample = pd.concat(frames, ignore_index=True).sample(frac=1, random_state=int(seed)).reset_index(drop=True)
        sample.insert(0, "SampleID", range(1, len(sample) + 1))

        for col in ["Reviewer1_Branch", "Reviewer1_Category", "Reviewer1_Entity",
                    "Reviewer1_Target", "Reviewer1_Product",
                    "Reviewer2_Branch", "Reviewer2_Category", "Reviewer2_Entity",
                    "Reviewer2_Target", "Reviewer2_Product", "Notes"]:
            sample[col] = ""
        return sample

    if not df_filt.empty:
        sample_df = build_validation_sample(df_filt, val_n, int(val_seed))
        st.caption(
            f"Sample: {len(sample_df)} trials across "
            f"{df_filt['DiseaseCategory'].nunique()} category strata (seed={int(val_seed)})"
        )
        st.dataframe(
            sample_df[["SampleID", "NCTId", "Branch", "DiseaseCategory", "DiseaseEntity",
                        "TargetCategory", "ProductType", "BriefTitle"]],
            width='stretch', height=260, hide_index=True,
        )
        st.download_button(
            label="Download validation sample CSV",
            data=sample_df.to_csv(index=False),
            file_name=f"car_t_onco_validation_sample_n{len(sample_df)}_seed{int(val_seed)}.csv",
            mime="text/csv",
        )
    else:
        st.info("No trials in the current filter selection.")

    st.subheader("Inter-rater agreement (Cohen's κ)")
    st.markdown(
        '<p class="small-note">Upload the completed validation CSV to compute Cohen\'s κ for '
        "Branch, Category, Entity, Target, and Product classification.</p>",
        unsafe_allow_html=True,
    )

    def _cohen_kappa(y1: list, y2: list) -> float:
        from collections import Counter
        n = len(y1)
        if n == 0:
            return float("nan")
        p_o = sum(a == b for a, b in zip(y1, y2)) / n
        c1, c2 = Counter(y1), Counter(y2)
        all_labels = set(c1) | set(c2)
        p_e = sum((c1[k] / n) * (c2[k] / n) for k in all_labels)
        if p_e >= 1.0:
            return 1.0
        return (p_o - p_e) / (1 - p_e)

    def _kappa_label(k: float) -> str:
        if k != k:
            return "—"
        if k < 0.00: return "Poor (< 0)"
        if k < 0.20: return "Slight (< 0.20)"
        if k < 0.40: return "Fair (0.20–0.40)"
        if k < 0.60: return "Moderate (0.40–0.60)"
        if k < 0.80: return "Substantial (0.60–0.80)"
        return "Almost perfect (≥ 0.80)"

    uploaded = st.file_uploader(
        "Completed validation CSV", type="csv",
        help="Upload the filled-in validation sample with Reviewer1_* and Reviewer2_* columns.",
    )

    if uploaded is not None:
        try:
            rev_df = pd.read_csv(uploaded)
        except Exception as e:
            st.error(f"Could not read file: {e}")
            rev_df = None

        if rev_df is not None:
            required = {
                "Reviewer1_Branch", "Reviewer2_Branch",
                "Reviewer1_Category", "Reviewer2_Category",
                "Reviewer1_Entity", "Reviewer2_Entity",
                "Reviewer1_Target", "Reviewer2_Target",
                "Reviewer1_Product", "Reviewer2_Product",
            }
            missing_cols = required - set(rev_df.columns)
            if missing_cols:
                st.error(f"Missing columns: {', '.join(sorted(missing_cols))}")
            else:
                pairs = [
                    ("Branch",    "Reviewer1_Branch",   "Reviewer2_Branch"),
                    ("Category",  "Reviewer1_Category", "Reviewer2_Category"),
                    ("Entity",    "Reviewer1_Entity",   "Reviewer2_Entity"),
                    ("Target",    "Reviewer1_Target",   "Reviewer2_Target"),
                    ("Product",   "Reviewer1_Product",  "Reviewer2_Product"),
                ]
                kappa_rows = []
                for label, col1, col2 in pairs:
                    sub = rev_df[[col1, col2]].dropna()
                    sub = sub[(sub[col1].str.strip() != "") & (sub[col2].str.strip() != "")]
                    n_rated = len(sub)
                    n_agreed = int((sub[col1].str.strip() == sub[col2].str.strip()).sum())
                    k = _cohen_kappa(sub[col1].str.strip().tolist(), sub[col2].str.strip().tolist())
                    kappa_rows.append({
                        "Classification task": label, "n rated": n_rated, "n agreed": n_agreed,
                        "% agreement": f"{100 * n_agreed / n_rated:.1f}%" if n_rated else "—",
                        "κ": round(k, 3) if k == k else "—",
                        "Interpretation": _kappa_label(k),
                    })
                kappa_summary = pd.DataFrame(kappa_rows)
                st.dataframe(kappa_summary, width='stretch', hide_index=True)


# ---------------------------------------------------------------------------
# TAB: About / Impressum
# ---------------------------------------------------------------------------

def _git_version() -> tuple[str, str]:
    repo_root = os.path.dirname(os.path.abspath(__file__))
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root, stderr=subprocess.DEVNULL,
        ).decode().strip()
        commit_date = subprocess.check_output(
            ["git", "log", "-1", "--format=%cs"],
            cwd=repo_root, stderr=subprocess.DEVNULL,
        ).decode().strip()
        return sha or "dev", commit_date or date.today().isoformat()
    except Exception:
        return "dev", date.today().isoformat()


with tab_about:
    sha, commit_date = _git_version()
    snap_date = (
        df["SnapshotDate"].iloc[0]
        if "SnapshotDate" in df.columns and not df.empty
        else date.today().isoformat()
    )

    st.subheader("About this dashboard")
    st.markdown(
        f"""
**CAR-T Oncology Trials Monitor** is an interactive dashboard that tracks CAR-T,
CAR-NK, CAAR-T, and CAR-γδ T clinical trials across hematologic and solid tumors,
sourced from the public ClinicalTrials.gov registry. It is the sister app to the
[Rheumatology CAR-T Trials Monitor](https://rheum-car-t-trial-monitor.streamlit.app/)
and is designed as a research and educational resource — not a medical, regulatory,
or decision-support tool.

- **Data source**: ClinicalTrials.gov API v2 ([{BASE_URL}]({BASE_URL}))
- **Current data snapshot**: {snap_date}
- **Software version**: `{sha}` &nbsp;·&nbsp; built {commit_date}
- **Code license**: MIT
        """
    )

    st.markdown("---")
    st.subheader("Contact")
    st.markdown(
        f"""
<div style="
    border: 1px solid {THEME['border']};
    border-left: 3px solid {THEME['primary']};
    border-radius: 8px;
    padding: 1.1rem 1.3rem;
    background: {THEME['surface']};
    max-width: 520px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.03);
">
    <div style="
        font-size: 1.02rem; font-weight: 600;
        color: {THEME['text']}; letter-spacing: -0.01em;
        margin-bottom: 0.35rem;
    ">Peter Jeong</div>
    <div style="
        font-size: 0.88rem; color: {THEME['text']}; line-height: 1.45;
    ">Universitätsklinikum Köln</div>
    <div style="
        font-size: 0.82rem; color: {THEME['muted']};
        line-height: 1.5; margin-bottom: 0.6rem;
    ">Klinik I für Innere Medizin<br>Klinische Immunologie und Rheumatologie</div>
    <div style="
        font-size: 0.80rem; color: {THEME['muted']};
        line-height: 1.55; padding-top: 0.55rem;
        border-top: 1px dashed {THEME['border']}; margin-bottom: 0.7rem;
    ">Kerpener Straße 62<br>50937 Köln, Germany</div>
    <a href="mailto:peter.jeong@uk-koeln.de" style="
        display: inline-flex; align-items: center; gap: 0.4rem;
        font-size: 0.84rem; font-weight: 500;
        color: {THEME['primary']}; text-decoration: none;
        padding: 0.35rem 0.7rem;
        border: 1px solid {THEME['border']};
        border-radius: 6px; background: {THEME['surf2']};
        transition: background 0.12s, border-color 0.12s;
    " onmouseover="this.style.background='{THEME['surf3']}';this.style.borderColor='{THEME['primary']}'"
       onmouseout="this.style.background='{THEME['surf2']}';this.style.borderColor='{THEME['border']}'">
        ✉ peter.jeong@uk-koeln.de
    </a>
</div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("---")
    st.subheader("Suggested citation")
    citation = (
        f"Jeong P. CAR-T Oncology Trials Monitor (version {sha}) [Internet]. "
        f"Klinik I für Innere Medizin, Klinische Immunologie und Rheumatologie, "
        f"Universitätsklinikum Köln; {date.today().year} "
        f"[cited {date.today().isoformat()}]. "
        f"Data snapshot: {snap_date}. Source: ClinicalTrials.gov API v2."
    )
    st.code(citation, language="text")
    st.caption("Vancouver-style citation.")

    st.markdown("---")
    st.subheader("Scientific disclaimer")
    st.markdown(
        """
Trial classifications (branch, disease category, disease entity, antigen target,
cell-therapy modality, product type, geography) are produced by an automated
pipeline combining keyword matching, curated lookup tables, and — for flagged
ambiguous cases — large-language-model-assisted review. Despite careful curation,
errors, omissions, and misclassifications are possible.

For any definitive scientific, clinical, or regulatory purpose, consult the
original trial records on ClinicalTrials.gov. This dashboard does not provide
medical advice and must not be used to guide individual patient care.
        """
    )

    with st.expander("Impressum · Datenschutz · Haftungsausschluss", expanded=False):
        st.markdown(
            f"""
#### Angaben gemäß § 5 TMG

**Verantwortlich für den Inhalt im Sinne des § 18 Abs. 2 MStV**

Peter Jeong
Universitätsklinikum Köln
Klinik I für Innere Medizin — Klinische Immunologie und Rheumatologie
Kerpener Straße 62
50937 Köln
Germany

E-Mail: peter.jeong@uk-koeln.de

---

#### Haftung für Inhalte

Die Inhalte dieses Dashboards wurden mit größtmöglicher Sorgfalt erstellt. Für die
Richtigkeit, Vollständigkeit und Aktualität der Inhalte kann jedoch keine Gewähr
übernommen werden. Die hier bereitgestellten Klassifikationen, Grafiken und
aggregierten Statistiken dienen ausschließlich wissenschaftlichen und edukativen
Zwecken. Sie stellen **keine medizinische Beratung** dar und sind nicht zur
Unterstützung individueller klinischer Entscheidungen geeignet.

#### Haftung für Links

Dieses Dashboard enthält Links zu externen Webseiten Dritter (insbesondere
ClinicalTrials.gov), auf deren Inhalte ich keinen Einfluss habe.

#### Urheberrecht

Der Quellcode dieser Anwendung steht unter der MIT-Lizenz. Die zugrunde liegenden
Studiendaten stammen aus dem öffentlichen Register ClinicalTrials.gov (U.S. National
Library of Medicine) und unterliegen deren Nutzungsbedingungen.

---

#### Datenschutz (kurz)

Diese Anwendung erhebt selbst **keine personenbezogenen Daten** von Nutzerinnen und
Nutzern. Es werden keine Tracking-Cookies, keine Analytics-Dienste und keine
Drittanbieter-Einbettungen mit Tracking-Funktion verwendet.

**Hosting-Anbieter:** Streamlit Community Cloud (Snowflake Inc., Bozeman, MT, USA).
Beim Aufruf der Anwendung werden technisch notwendige Verbindungsdaten (IP-Adresse,
Zeitstempel, User-Agent) vorübergehend durch den Hosting-Anbieter verarbeitet.
Details: [streamlit.io/privacy-policy](https://streamlit.io/privacy-policy) und
[snowflake.com/privacy-notice](https://www.snowflake.com/privacy-notice/).

**Datenquelle:** Die Anwendung ruft Studiendaten über die öffentliche API von
ClinicalTrials.gov ab ([{BASE_URL}]({BASE_URL})).

---

#### Versionierung

- **Software-Version (git commit):** `{sha}`
- **Build-Datum:** {commit_date}
- **Datensatz-Snapshot:** {snap_date}
- **Datenquelle:** ClinicalTrials.gov API v2

Stand: {date.today().isoformat()}
            """
        )
