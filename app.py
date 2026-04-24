import os
import re
import subprocess
import numpy as np
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
    # FDA approvals (primary — drawn as prominent vertical lines)
    {"year": 2017, "name": "tisa-cel (Kymriah)",   "target": "CD19", "regulator": "FDA"},
    {"year": 2017, "name": "axi-cel (Yescarta)",   "target": "CD19", "regulator": "FDA"},
    {"year": 2020, "name": "brexu-cel (Tecartus)", "target": "CD19", "regulator": "FDA"},
    {"year": 2021, "name": "liso-cel (Breyanzi)",  "target": "CD19", "regulator": "FDA"},
    {"year": 2021, "name": "ide-cel (Abecma)",     "target": "BCMA", "regulator": "FDA"},
    {"year": 2022, "name": "cilta-cel (Carvykti)", "target": "BCMA", "regulator": "FDA"},
    {"year": 2024, "name": "obe-cel (Aucatzyl)",   "target": "CD19", "regulator": "FDA"},
    # NMPA approvals (China — listed in caption only, no chart line)
    {"year": 2021, "name": "relma-cel (Carteyva)", "target": "CD19", "regulator": "NMPA"},
    {"year": 2023, "name": "eque-cel (Fucaso)",    "target": "BCMA", "regulator": "NMPA"},
    {"year": 2024, "name": "zevor-cel",            "target": "BCMA", "regulator": "NMPA"},
    # EMA approvals (EU — listed in caption only, no chart line)
    {"year": 2018, "name": "tisa-cel (Kymriah)",   "target": "CD19", "regulator": "EMA"},
    {"year": 2018, "name": "axi-cel (Yescarta)",   "target": "CD19", "regulator": "EMA"},
    {"year": 2020, "name": "brexu-cel (Tecartus)", "target": "CD19", "regulator": "EMA"},
    {"year": 2021, "name": "ide-cel (Abecma)",     "target": "BCMA", "regulator": "EMA"},
    {"year": 2022, "name": "liso-cel (Breyanzi)",  "target": "CD19", "regulator": "EMA"},
    {"year": 2022, "name": "cilta-cel (Carvykti)", "target": "BCMA", "regulator": "EMA"},
    {"year": 2025, "name": "obe-cel (Aucatzyl)",   "target": "CD19", "regulator": "EMA"},
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
MIXED_COLOR = "#475569"   # slate-600 — neutral (replaces indigo per style guide)
UNKNOWN_COLOR = "#94a3b8" # slate-400

BRANCH_COLORS = {
    "Heme-onc": HEME_COLOR,
    "Solid-onc": SOLID_COLOR,
    "Mixed": MIXED_COLOR,
    "Unknown": UNKNOWN_COLOR,
}

_MODALITY_COLORS: dict[str, str] = {}  # populated below once NEJM palette defined

# ---------------------------------------------------------------------------
# Shared UI constants — single source of truth (Rheum × Onc style guide).
# Reference these in new code instead of hard-coding heights or fonts.
# ---------------------------------------------------------------------------
PANEL_HEIGHT         = 440  # overview panels (horizontal bars)
TABLE_HEIGHT_DEFAULT = 360  # st.dataframe default when not auto-sized
HAIRLINE             = THEME["border"]
FONT_FAMILY          = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"


# ---------------------------------------------------------------------------
# Country name → ISO-3 mapping for Plotly choropleth. The library behind
# `locationmode="country names"` is being deprecated (DeprecationWarning
# on every app load); ISO-3 codes are the stable replacement. Covers
# every country appearing in CT.gov trial records for CAR-T oncology.
# ---------------------------------------------------------------------------
COUNTRY_TO_ISO3: dict[str, str] = {
    # Americas
    "United States": "USA", "Canada": "CAN", "Mexico": "MEX",
    "Brazil": "BRA", "Argentina": "ARG", "Chile": "CHL",
    "Colombia": "COL", "Peru": "PER", "Uruguay": "URY",
    "Costa Rica": "CRI", "Panama": "PAN", "Guatemala": "GTM",
    "Cuba": "CUB", "Puerto Rico": "PRI",
    # Europe
    "United Kingdom": "GBR", "Germany": "DEU", "France": "FRA",
    "Italy": "ITA", "Spain": "ESP", "Netherlands": "NLD",
    "Belgium": "BEL", "Switzerland": "CHE", "Austria": "AUT",
    "Sweden": "SWE", "Denmark": "DNK", "Norway": "NOR",
    "Finland": "FIN", "Poland": "POL", "Czechia": "CZE",
    "Czech Republic": "CZE", "Hungary": "HUN", "Greece": "GRC",
    "Portugal": "PRT", "Ireland": "IRL",
    "Romania": "ROU", "Slovakia": "SVK", "Slovenia": "SVN",
    "Bulgaria": "BGR", "Croatia": "HRV", "Serbia": "SRB",
    "Ukraine": "UKR", "Belarus": "BLR", "Estonia": "EST",
    "Latvia": "LVA", "Lithuania": "LTU", "Luxembourg": "LUX",
    "Iceland": "ISL", "Malta": "MLT", "Cyprus": "CYP",
    # Russia (both spellings)
    "Russia": "RUS", "Russian Federation": "RUS",
    # UK aliases
    "United Kingdom of Great Britain and Northern Ireland": "GBR",
    # Asia-Pacific
    "China": "CHN", "Japan": "JPN", "South Korea": "KOR",
    "Korea, Republic of": "KOR", "Korea, South": "KOR",
    "Taiwan": "TWN", "Hong Kong": "HKG",
    "Singapore": "SGP", "Malaysia": "MYS", "Thailand": "THA",
    "Indonesia": "IDN", "Philippines": "PHL", "Vietnam": "VNM",
    "Viet Nam": "VNM", "India": "IND", "Pakistan": "PAK",
    "Bangladesh": "BGD", "Sri Lanka": "LKA", "Nepal": "NPL",
    "Australia": "AUS", "New Zealand": "NZL",
    # Middle East / Africa
    "Israel": "ISR", "Turkey": "TUR", "Turkey (Türkiye)": "TUR",
    "Türkiye": "TUR", "Saudi Arabia": "SAU",
    "United Arab Emirates": "ARE", "Iran": "IRN",
    "Iran, Islamic Republic of": "IRN",
    "Egypt": "EGY", "South Africa": "ZAF", "Nigeria": "NGA",
    "Kenya": "KEN", "Morocco": "MAR", "Tunisia": "TUN",
    "Jordan": "JOR", "Lebanon": "LBN",
}


def _to_iso3(country: str | None) -> str | None:
    """Return the ISO-3 code for a country name, or None if not mapped.
    Ignoring unknowns drops them from the choropleth but keeps the bar chart."""
    if not country:
        return None
    c = str(country).strip()
    return COUNTRY_TO_ISO3.get(c)


# ---------------------------------------------------------------------------
# Table-config helpers — every st.dataframe in the app should route through
# one of these to keep column labels, widths, and formatting consistent
# (Rheum × Onc style guide). Helpers are shared utilities and do not touch
# data logic.
# ---------------------------------------------------------------------------

def _landscape_table_cols(dim_key: str, dim_label: str) -> dict:
    """Summary / 'landscape by …' tables (by disease / product / sponsor / …)."""
    _enroll_help = (
        "Planned enrollment from CT.gov (self-reported target, not actual accrual)."
    )
    return {
        dim_key:            st.column_config.TextColumn(dim_label),
        "Trials":           st.column_config.NumberColumn("Trials", format="%d"),
        "Open":             st.column_config.NumberColumn("Open / recruiting", format="%d"),
        "Sponsors":         st.column_config.NumberColumn("Distinct sponsors", format="%d"),
        "TotalEnrolled":    st.column_config.NumberColumn(
            "Total planned enrollment", format="%,d", help=_enroll_help),
        "MedianEnrollment": st.column_config.NumberColumn(
            "Median enrollment", format="%d", help=_enroll_help),
    }


def _trial_detail_cols(extra: dict | None = None) -> dict:
    """Drilldown 'Trials' detail tables — configure every shown column."""
    cfg = {
        "NCTId":           st.column_config.TextColumn("NCT ID"),
        "NCTLink":         st.column_config.LinkColumn("Trial link", display_text="Open trial"),
        "BriefTitle":      st.column_config.TextColumn("Title", width="large"),
        "Branch":          st.column_config.TextColumn("Branch"),
        "DiseaseCategory": st.column_config.TextColumn("Category"),
        "DiseaseEntity":   st.column_config.TextColumn("Disease"),
        "DiseaseEntities": st.column_config.TextColumn("Disease(s)", width="medium"),
        "TargetCategory":  st.column_config.TextColumn("Target"),
        "ProductType":     st.column_config.TextColumn("Product"),
        "ProductName":     st.column_config.TextColumn("Named product", width="small"),
        "Phase":           st.column_config.TextColumn("Phase"),
        "OverallStatus":   st.column_config.TextColumn("Status"),
        "LeadSponsor":     st.column_config.TextColumn("Lead sponsor", width="medium"),
        "SponsorType":     st.column_config.TextColumn("Sponsor type", width="small"),
        "AgeGroup":        st.column_config.TextColumn("Age group", width="small"),
        "StartYear":       st.column_config.NumberColumn("Start year", format="%d"),
        "Countries":       st.column_config.TextColumn("Countries", width="medium"),
        "ClassificationConfidence": st.column_config.TextColumn("Conf.", width="small"),
    }
    if extra:
        cfg.update(extra)
    return cfg


def _mini_count_cols(label: str) -> dict:
    """2-col count tables ('Antigen targets', 'Products', 'Top sponsors', …)."""
    return {
        label:    st.column_config.TextColumn(label, width="medium"),
        "Trials": st.column_config.NumberColumn("Trials", format="%d", width="small"),
    }


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

@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def load_live(max_records: int = 5000, statuses: tuple[str, ...] = ()) -> tuple:
    """Fetch from CT.gov; cache for 24 hours.

    With a 24h TTL the first user of the day pays the cold-start cost
    (~30–60s for ~2.5k trials) and everyone else in the same day gets an
    instant warm cache. This makes live-mode the natural default and
    removes the need for users to trigger a 'refresh' step.
    """
    statuses_list = list(statuses) if statuses else None
    return build_all_from_api(max_records=max_records, statuses=statuses_list)


@st.cache_data
def load_frozen(snapshot_date: str) -> tuple:
    return load_snapshot(snapshot_date)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def metric_card(label: str, value, foot: str = ""):
    """Deprecated — forwards to st.metric() per the Rheum × Onc style guide.
    All in-app call-sites have been migrated; kept as a compat shim in case
    external code / snapshots reference it."""
    st.metric(label, value, help=foot or None)


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


def _first_meaningful_year(counts_df: pd.DataFrame, year_col: str = "StartYear",
                            count_col: str = "Count", threshold: int = 5) -> int | None:
    """Earliest year where the total count (summed across stacked groups)
    reaches `threshold`. Used to trim near-empty leading years from temporal
    charts — underlying data is unchanged; only the visible x-axis range is
    tightened so 2-trial-years don't render as visually empty against the
    100+-trial peak years."""
    if counts_df is None or counts_df.empty:
        return None
    totals = counts_df.groupby(year_col)[count_col].sum().sort_index()
    meaningful = totals[totals >= threshold]
    if meaningful.empty:
        return int(totals.index.min())
    return int(meaningful.index.min())


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
            across hematologic and solid tumors — with disease, target-antigen, and
            cell-therapy modality classification; global site-level geography; and
            publication-ready figures.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Sidebar — data source
# ---------------------------------------------------------------------------
#
# Live-first architecture:
#   - Default: live CT.gov pull cached 24h. First visitor of the day pays the
#     cold-start cost; everyone else gets an instant warm cache. No manual
#     refresh step.
#   - Opt-in: pin a specific dated snapshot for publication reproducibility
#     (e.g., "pin to the dataset cited in the paper"). Hidden behind an
#     "Advanced" expander so casual viewers never see the mode toggle.
#   - Safety net: if CT.gov is unreachable, fall back to the most recent
#     frozen snapshot automatically.
#
# Previous architecture defaulted to frozen-by-default + manual Save snapshot,
# which forced every schema change to require a re-freeze and manual backfill.

st.sidebar.header("Data source")

available_snapshots = list_snapshots()
prisma_counts: dict = {}

# Detect an explicit user opt-in to pin a frozen snapshot. Stored in
# session_state so the Refresh button can clear it.
_pin_key = "pinned_snapshot"
_pinned = st.session_state.get(_pin_key)
if _pinned and _pinned not in available_snapshots:
    _pinned = None
    st.session_state[_pin_key] = None

if _pinned:
    with st.spinner(f"Loading pinned snapshot {_pinned}..."):
        df, df_sites, prisma_counts = load_frozen(_pinned)
    st.sidebar.success(
        f"Pinned to frozen snapshot **{_pinned}** ({len(df):,} trials)."
    )
    if st.sidebar.button("Unpin — switch back to live data"):
        st.session_state[_pin_key] = None
        st.cache_data.clear()
        st.rerun()
else:
    selected_statuses: list[str] = []
    try:
        with st.spinner("Fetching live ClinicalTrials.gov data (cached 24h)..."):
            df, df_sites, prisma_counts = load_live(statuses=tuple(selected_statuses))
        st.sidebar.caption(
            f"Live from CT.gov · {len(df):,} trials · cached 24h"
        )
        if st.sidebar.button("Refresh now"):
            st.cache_data.clear()
            st.rerun()
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
                f"Loaded frozen snapshot **{fallback}** (offline fallback)."
            )
        else:
            st.error(
                "Cannot load data: the ClinicalTrials.gov API is unreachable and no local "
                "snapshots exist. Please try again later or check the API status at "
                "https://clinicaltrials.gov/."
            )
            st.stop()

    # Reproducibility escape hatch — hidden by default so casual users never see it.
    with st.sidebar.expander("Reproducibility — pin a frozen dataset", expanded=False):
        if not available_snapshots:
            st.caption(
                "No frozen snapshots available. Click **Save current as snapshot** "
                "below to create one from the live data for citation."
            )
        else:
            _pin_choice = st.selectbox(
                "Pin a dated snapshot (for citing in a paper)",
                options=["— live data —"] + available_snapshots,
                index=0,
                key="pin_snapshot_select",
            )
            if _pin_choice != "— live data —":
                if st.button(f"Pin snapshot {_pin_choice}"):
                    st.session_state[_pin_key] = _pin_choice
                    st.rerun()
        if st.button("Save current as snapshot"):
            statuses_list = selected_statuses if selected_statuses else None
            snap_date = save_snapshot(df, df_sites, prisma_counts, statuses=statuses_list)
            st.success(f"Saved snapshot: {snap_date}")
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

# Reset button — clears every filter widget's state so defaults (all options
# selected) re-apply on the next rerun. Explicit keys on each multiselect below
# let us target them selectively without affecting the data-source radio.
_FILTER_KEYS = [
    "filter_branch", "filter_category", "filter_entity",
    "filter_design", "filter_phase", "filter_target",
    "filter_status", "filter_product", "filter_modality",
    "filter_country", "filter_agegroup", "filter_sponsortype",
    "filter_confidence",
]
if st.sidebar.button("↺ Reset all filters", use_container_width=True):
    for _k in _FILTER_KEYS:
        if _k in st.session_state:
            del st.session_state[_k]
    st.rerun()

st.sidebar.caption("Disease filter cascades: Branch → Category → Entity.")

branch_options_all = sorted(df["Branch"].dropna().unique().tolist())
branch_sel = st.sidebar.multiselect(
    "Branch",
    options=branch_options_all,
    default=branch_options_all,
    help="Heme-onc, Solid-onc, Mixed, Unknown.",
    key="filter_branch",
)

df_after_branch = df[df["Branch"].isin(branch_sel)] if branch_sel else df

category_options_all = sorted(df_after_branch["DiseaseCategory"].dropna().unique().tolist())
category_sel = st.sidebar.multiselect(
    "Disease category",
    options=category_options_all,
    default=category_options_all,
    help="Options narrow based on the selected branch(es).",
    key="filter_category",
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
    key="filter_entity",
)

# Trial design
design_options = sorted(df["TrialDesign"].dropna().unique().tolist())
design_sel = st.sidebar.multiselect(
    "Trial design", options=design_options, default=design_options,
    help="Single-disease vs basket/multi-disease trials.",
    key="filter_design",
)

# Phase
phase_options = [PHASE_LABELS[p] for p in PHASE_ORDER if p in set(df["PhaseNormalized"].astype(str))]
phase_sel = st.sidebar.multiselect("Phase", options=phase_options, default=phase_options, key="filter_phase")

# Target category (exclude platform labels — those live in modality filter)
target_options = sorted(
    t for t in df["TargetCategory"].dropna().unique() if t not in _PLATFORM_LABELS
)
target_sel = st.sidebar.multiselect(
    "Antigen target", options=target_options, default=target_options, key="filter_target",
)

# Status
status_options = sorted(df["OverallStatus"].dropna().unique().tolist())
status_sel = st.sidebar.multiselect(
    "Overall status", options=status_options, default=status_options, key="filter_status",
)

# Product type
product_options = sorted(df["ProductType"].dropna().unique().tolist())
product_sel = st.sidebar.multiselect(
    "Product type", options=product_options, default=product_options, key="filter_product",
)

# Modality
modality_options = [m for m in MODALITY_ORDER if m in set(df["Modality"])]
modality_sel = st.sidebar.multiselect(
    "Cell therapy modality", options=modality_options, default=modality_options,
    key="filter_modality",
)

# Country
all_countries: set[str] = set()
for cs in df["Countries"].dropna():
    for c in str(cs).split("|"):
        c = c.strip()
        if c:
            all_countries.add(c)
country_options = sorted(all_countries)
country_sel = st.sidebar.multiselect(
    "Country", options=country_options, default=country_options, key="filter_country",
)

# Age group (Pediatric / Adult / Both / Unknown)
age_options = sorted(df["AgeGroup"].dropna().unique().tolist()) if "AgeGroup" in df.columns else []
age_sel = st.sidebar.multiselect(
    "Age group", options=age_options, default=age_options, key="filter_agegroup",
    help="Derived from the trial's StdAges / MinAge / MaxAge fields.",
)

# Sponsor type (Academic / Industry / Government / Unknown)
sponsor_options = sorted(df["SponsorType"].dropna().unique().tolist()) if "SponsorType" in df.columns else []
sponsor_sel = st.sidebar.multiselect(
    "Sponsor type", options=sponsor_options, default=sponsor_options, key="filter_sponsortype",
    help="From CT.gov LeadSponsor.class; name-token fallback for uncategorised sponsors.",
)

# Classification confidence (high / medium / low)
conf_options = ["high", "medium", "low"]
conf_present = [c for c in conf_options if c in set(df["ClassificationConfidence"].dropna())]
conf_sel = st.sidebar.multiselect(
    "Classification confidence", options=conf_present, default=conf_present, key="filter_confidence",
    help="Filter to high-confidence rows for strict analyses (see Methods §Classification Confidence).",
)


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
    # Provenance tag: pinned snapshot if user explicitly selected one, else live.
    _pinned_for_export = st.session_state.get("pinned_snapshot")
    if _pinned_for_export:
        lines.append(
            f"# Data source: ClinicalTrials.gov API v2 — pinned frozen snapshot {_pinned_for_export}"
        )
    else:
        lines.append(
            f"# Data source: ClinicalTrials.gov API v2 — live fetch (cached 24h, pulled on {snap})"
        )
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

    # ClassificationConfidence band summary.
    if "ClassificationConfidence" in df.columns:
        conf_counts = df["ClassificationConfidence"].value_counts()
        n_high = int(conf_counts.get("high", 0))
        n_med = int(conf_counts.get("medium", 0))
        n_low = int(conf_counts.get("low", 0))
        total = max(1, len(df))
        st.caption(
            f"**Classification confidence** (see Methods): "
            f"high = {n_high} ({100*n_high/total:.0f}%) · "
            f"medium = {n_med} ({100*n_med/total:.0f}%) · "
            f"low = {n_low} ({100*n_low/total:.0f}%)."
        )

    n_llm = int(df["LLMOverride"].sum()) if "LLMOverride" in df.columns else 0
    if n_llm:
        st.caption(
            f"LLM-assisted: **{n_llm}** trial(s) reclassified via `llm_overrides.json` "
            "(two-round Claude Opus validation; see Methods § LLM-Assisted Curation Loop). "
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
if age_sel:
    mask &= df["AgeGroup"].isin(age_sel)
if sponsor_sel:
    mask &= df["SponsorType"].isin(sponsor_sel)
if conf_sel:
    mask &= df["ClassificationConfidence"].isin(conf_sel)

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
# Sites-by-city helpers (country-selectable)
# ---------------------------------------------------------------------------
# Open / recruiting sites across ALL countries, restricted to trials visible
# under the current filter. Both "Sites by city" (Geography tab) and
# "Studies active in …" (Data tab) pick one country via a selectbox from
# this shared pool.

all_open_sites = pd.DataFrame()
if not df_sites.empty:
    _os = df_sites[
        df_sites["SiteStatus"].fillna("").str.upper().isin(OPEN_SITE_STATUSES)
    ].copy()
    _os = _os[_os["NCTId"].isin(df_filt["NCTId"])].copy()
    _os["Country"] = _os["Country"].fillna("Unknown").astype(str).str.strip()
    _os = _os[_os["Country"] != ""]
    all_open_sites = _os


def _country_study_view(country: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (open site rows for this country, per-trial study view)."""
    if all_open_sites.empty or not country:
        return pd.DataFrame(), pd.DataFrame()
    c_sites = all_open_sites[
        all_open_sites["Country"].str.lower() == country.lower()
    ].copy()
    if c_sites.empty:
        return c_sites, pd.DataFrame()
    c_trials = df_filt[df_filt["NCTId"].isin(c_sites["NCTId"])].copy()
    sv = (
        c_sites.groupby("NCTId", as_index=False)
        .agg(Cities=("City", uniq_join), SiteStatuses=("SiteStatus", uniq_join))
    )
    merge_cols = [c for c in [
        "NCTId", "BriefTitle",
        "Branch", "DiseaseCategory", "DiseaseEntity",
        "TargetCategory", "ProductType", "ProductName",
        "AgeGroup", "SponsorType",
        "Phase", "PhaseNormalized", "PhaseOrdered", "PhaseLabel",
        "OverallStatus", "LeadSponsor",
    ] if c in c_trials.columns]
    sv = sv.merge(
        c_trials[merge_cols].drop_duplicates(subset=["NCTId"]),
        on="NCTId", how="left",
    )
    sv["NCTLink"] = sv["NCTId"].apply(
        lambda x: f"https://clinicaltrials.gov/study/{x}" if pd.notna(x) else None
    )
    if "PhaseLabel" in sv.columns:
        sv["Phase"] = sv["PhaseLabel"].fillna(sv.get("Phase"))
    sort_cols = [c for c in ["PhaseOrdered", "Branch", "DiseaseCategory", "NCTId"] if c in sv.columns]
    if sort_cols:
        sv = sv.sort_values(sort_cols, na_position="last")
    return c_sites, sv


def _countries_by_activity() -> list[str]:
    """Countries with at least one open / recruiting site, ranked by unique trials."""
    if all_open_sites.empty:
        return []
    order = (
        all_open_sites.groupby("Country")["NCTId"].nunique()
        .sort_values(ascending=False)
    )
    return order.index.tolist()


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
    st.metric("Filtered trials", f"{total_trials:,}", help="Trials matching current filters")
with m2:
    st.metric("Open / recruiting", f"{recruiting_trials:,}", help="Recruiting or not yet recruiting")
with m3:
    st.metric("Heme · Solid", f"{heme_count} · {solid_count}", help="Heme-onc / Solid-onc split")
with m4:
    st.metric("Median enrollment", f"{median_enrolled:,}",
              help=f"{total_enrolled:,} patients across {len(_enroll_known)} trials")
with m5:
    st.metric("Top antigen target", top_target, help="Most common non-platform target")

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

tab_overview, tab_geo, tab_data, tab_deep, tab_pub, tab_methods, tab_about = st.tabs(
    ["Overview", "Geography / Map", "Data", "Deep Dive",
     "Publication Figures", "Methods & Appendix", "About"]
)


# ---------------------------------------------------------------------------
# TAB: Overview
# ---------------------------------------------------------------------------

with tab_overview:
    # Disease hierarchy sunburst (Branch → Category → Entity)
    st.subheader("Disease hierarchy at a glance")
    st.caption("Click a wedge to zoom in. Publication-quality version in Figure 5.")
    if not df_filt.empty:
        _ov_sun = (
            df_filt[["Branch", "DiseaseCategory", "DiseaseEntity"]]
            .fillna("Unknown").assign(Count=1)
            .groupby(["Branch", "DiseaseCategory", "DiseaseEntity"], as_index=False).sum()
        )
        fig_ov_sun = px.sunburst(
            _ov_sun, path=["Branch", "DiseaseCategory", "DiseaseEntity"],
            values="Count", color="Branch", color_discrete_map=BRANCH_COLORS,
            height=460, template="plotly_white",
        )
        fig_ov_sun.update_traces(
            insidetextorientation="radial",
            marker=dict(line=dict(color="white", width=1.2)),
        )
        fig_ov_sun.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=8, r=8, t=8, b=8),
            font=dict(family="Inter, sans-serif", size=12, color=THEME["text"]),
        )
        st.plotly_chart(fig_ov_sun, width='stretch')
    else:
        st.info("No trials for the current filter selection.")

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
        st.caption("Phase distribution of trials in the current filter, stacked by branch.")
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
        st.caption("Annual trial starts in the current filter, stacked area by branch.")
        year_df = df_filt.copy()
        year_df["StartYear"] = pd.to_numeric(year_df["StartYear"], errors="coerce")
        year_df = year_df.dropna(subset=["StartYear"])
        year_df["StartYear"] = year_df["StartYear"].astype(int)
        counts_year = (
            year_df.groupby(["StartYear", "Branch"], as_index=False)
            .size().rename(columns={"size": "Count"})
        )
        if not counts_year.empty:
            # plotly 6.x: px.area no longer auto-stacks. Use go.Scatter with
            # stackgroup="one" so Heme and Solid stack instead of overdraw.
            fig_year = go.Figure()
            for _branch in sorted(counts_year["Branch"].unique()):
                _bd = counts_year[counts_year["Branch"] == _branch].sort_values("StartYear")
                fig_year.add_trace(go.Scatter(
                    x=_bd["StartYear"], y=_bd["Count"],
                    name=_branch, mode="lines",
                    stackgroup="one",
                    line=dict(width=0.5, color=BRANCH_COLORS.get(_branch, THEME["primary"])),
                    fillcolor=BRANCH_COLORS.get(_branch, THEME["primary"]),
                ))
            fig_year.update_layout(template="plotly_white", height=320)
            fig_year.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=10, r=10, t=10, b=10),
                font=dict(color=THEME["text"]),
                xaxis_title=None, yaxis_title=None, legend_title=None,
            )
            _ov_first = _first_meaningful_year(counts_year) or int(counts_year["StartYear"].min())
            _ov_last = int(counts_year["StartYear"].max())
            fig_year.update_xaxes(
                color=THEME["muted"], tickmode="linear", dtick=1, tickformat="d",
                range=[_ov_first - 0.5, _ov_last + 0.5],
            )
            fig_year.update_yaxes(gridcolor=THEME["grid"], color=THEME["muted"])
            st.plotly_chart(fig_year, width='stretch')
        else:
            st.info("No trials with a valid start year for the current filter selection.")

    # Methodological backing — collapsed by default so the insight-first flow
    # above isn't blocked. Full PRISMA narrative also lives in the Methods tab.
    if prisma_counts:
        with st.expander("Study selection (PRISMA flow)", expanded=False):
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
            st.caption("Full PRISMA narrative and classification methodology in the Methods & Appendix tab.")


# ---------------------------------------------------------------------------
# TAB: Geography / Map
# ---------------------------------------------------------------------------

with tab_geo:
    st.subheader("Global studies by country")

    countries_long = split_pipe_values(df_filt["Countries"])
    if not countries_long:
        st.info("No country information available for the current filter selection.")
    else:
        country_df = pd.DataFrame({"Country": countries_long})
        country_counts = (
            country_df["Country"].value_counts().rename_axis("Country").reset_index(name="Count")
        )
        country_counts_iso = country_counts.copy()
        country_counts_iso["ISO3"] = country_counts_iso["Country"].map(_to_iso3)
        country_counts_iso = country_counts_iso.dropna(subset=["ISO3"])

        # Prep site-level overlay if coordinates available. Gracefully degrades
        # to a pure choropleth when snapshot predates lat/lon extraction.
        _has_coords = (
            not all_open_sites.empty
            and "Latitude" in all_open_sites.columns
            and not all_open_sites["Latitude"].isna().all()
        )
        _geo_sites = pd.DataFrame()
        if _has_coords:
            _geo_base = all_open_sites.dropna(subset=["Latitude", "Longitude"]).copy()
            _geo_base = _geo_base.merge(
                df_filt[["NCTId", "Branch", "BriefTitle"]].drop_duplicates("NCTId"),
                on="NCTId", how="left",
            )
            _geo_base["Branch"] = _geo_base["Branch"].fillna("Unknown")
            _geo_sites = _geo_base.drop_duplicates(["NCTId", "Facility", "City"]).copy()

        # Compact controls row above the map. Keeps the map itself at full
        # width so the world is read as one image, not a half-frame.
        if _has_coords:
            _c_ctrl1, _c_ctrl2, _c_ctrl3 = st.columns([0.22, 0.28, 0.50])
            with _c_ctrl1:
                _show_sites = st.checkbox(
                    "Show open-site dots",
                    value=True,
                    key="world_show_sites",
                    help="Overlay each open / recruiting site as a colored dot on the country map.",
                )
            with _c_ctrl2:
                _site_color = st.radio(
                    "Dot colour",
                    options=["Branch", "Single"],
                    index=0,
                    key="world_sites_color_by",
                    horizontal=True,
                    label_visibility="collapsed",
                    disabled=not _show_sites,
                )
            with _c_ctrl3:
                if _show_sites:
                    st.caption(
                        f"Country shading = trial count · "
                        f"**{len(_geo_sites):,}** sites across "
                        f"**{_geo_sites['NCTId'].nunique():,}** trials."
                    )
                else:
                    st.caption("Country shading = trial count.")
        else:
            _show_sites = False
            _site_color = "Branch"
            st.caption(
                "Country shading = trial count. "
                "Site-level coordinates not available — click **Refresh now** "
                "in the sidebar to enable site dots."
            )

        # Base choropleth.
        fig_world = go.Figure()
        fig_world.add_trace(go.Choropleth(
            locations=country_counts_iso["ISO3"],
            locationmode="ISO-3",
            z=country_counts_iso["Count"],
            text=country_counts_iso["Country"],
            hovertemplate="<b>%{text}</b><br>%{z} trials<extra></extra>",
            colorscale=[
                [0.00, "#dbeafe"], [0.30, "#93c5fd"],
                [0.55, "#3b82f6"], [0.75, "#1d4ed8"], [1.00, "#1e3a8a"],
            ],
            colorbar=dict(
                title=dict(text="Trials", side="top"),
                thickness=12, len=0.6, x=1.0, xanchor="left",
            ),
            marker_line_color="rgba(0,0,0,0.18)", marker_line_width=0.4,
            name="",  # blank name so legend doesn't display "trace 0"
            showscale=True,
        ))

        # Site dots overlay.
        if _show_sites and not _geo_sites.empty:
            if _site_color == "Branch":
                for _branch in sorted(_geo_sites["Branch"].unique()):
                    _sub = _geo_sites[_geo_sites["Branch"] == _branch]
                    fig_world.add_trace(go.Scattergeo(
                        lat=_sub["Latitude"], lon=_sub["Longitude"],
                        mode="markers",
                        name=_branch,
                        marker=dict(
                            size=4.5, opacity=0.75, line=dict(width=0.4, color="white"),
                            color=BRANCH_COLORS.get(_branch, THEME["primary"]),
                        ),
                        customdata=_sub[["NCTId", "Facility", "City", "Country", "SiteStatus"]].fillna(""),
                        hovertemplate=(
                            "<b>%{customdata[1]}</b><br>"
                            "%{customdata[2]}, %{customdata[3]}<br>"
                            "%{customdata[0]} · %{customdata[4]}"
                            "<extra>" + _branch + "</extra>"
                        ),
                    ))
            else:
                fig_world.add_trace(go.Scattergeo(
                    lat=_geo_sites["Latitude"], lon=_geo_sites["Longitude"],
                    mode="markers",
                    name="Open sites",
                    marker=dict(
                        size=4.5, opacity=0.7, line=dict(width=0.4, color="white"),
                        color="#dc2626",
                    ),
                    customdata=_geo_sites[["NCTId", "Facility", "City", "Country", "SiteStatus"]].fillna(""),
                    hovertemplate=(
                        "<b>%{customdata[1]}</b><br>"
                        "%{customdata[2]}, %{customdata[3]}<br>"
                        "%{customdata[0]} · %{customdata[4]}<extra></extra>"
                    ),
                ))

        fig_world.update_layout(
            margin=dict(l=0, r=0, t=10, b=0),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color=THEME["text"]),
            geo=dict(
                bgcolor="rgba(0,0,0,0)", lakecolor="#ddeeff", landcolor="#eef2f7",
                showframe=False, showcoastlines=False,
                showcountries=True, countrycolor="rgba(0,0,0,0.12)",
                projection_type="natural earth",
            ),
            legend=dict(
                orientation="h", yanchor="top", y=-0.02,
                xanchor="center", x=0.5,
                font=dict(size=11, color=THEME["text"]),
                bgcolor="rgba(0,0,0,0)", borderwidth=0, title=None,
            ),
            height=500,
        )

        # Map + top-countries bar side-by-side (the bar lets the eye read the
        # distribution quickly where the map's colour scale alone is dense).
        _c_map, _c_bar = st.columns([0.65, 0.35])
        with _c_map:
            st.plotly_chart(fig_world, width='stretch')
        with _c_bar:
            st.markdown("**Top countries by trial count**")
            st.plotly_chart(
                make_bar(country_counts.head(12), "Country", "Count", height=500, color=THEME["primary"]),
                width='stretch',
            )

        # Country-counts table spans full width below — the wider table wins
        # over a half-width version at the same height, since country names +
        # counts are the primary lookup asset for this panel.
        st.markdown("**Country counts (all)**")
        st.dataframe(country_counts, width='stretch', height=280, hide_index=True)

    st.subheader("Sites by city")

    _countries_avail = _countries_by_activity()
    if not _countries_avail:
        st.info("No open or recruiting study sites in the current filter selection.")
    else:
        # Default to most active country, but preserve user's last selection
        # via session state so the Geography + Data tabs stay in sync.
        _prev = st.session_state.get("sites_country", _countries_avail[0])
        _default_idx = _countries_avail.index(_prev) if _prev in _countries_avail else 0
        selected_country = st.selectbox(
            "Country",
            options=_countries_avail,
            index=_default_idx,
            key="sites_country",
            help="Pick any country with at least one open or recruiting site in the current filter.",
        )

        country_open_sites, country_study_view = _country_study_view(selected_country)

        if country_open_sites.empty:
            st.info(f"No open or recruiting sites found in {selected_country}.")
        else:
            country_city_counts = (
                country_open_sites["City"].fillna("Unknown").value_counts()
                .rename_axis("City").reset_index(name="OpenSiteCount")
                .sort_values(["OpenSiteCount", "City"], ascending=[False, True], na_position="last")
                .reset_index(drop=True)
            )

            g1, g2, g3 = st.columns(3)
            with g1:
                st.metric(f"{selected_country} site rows", f"{len(country_open_sites):,}",
                          help=f"Recruiting / active {selected_country} site rows")
            with g2:
                st.metric("Cities", country_open_sites["City"].dropna().nunique(),
                          help="Cities with open sites")
            with g3:
                st.metric(
                    "Unique trials",
                    country_study_view["NCTId"].nunique() if not country_study_view.empty else 0,
                    help=f"NCT IDs with at least one open {selected_country} site",
                )

            # Mirror the Global-view pattern: map + top-cities bar side by
            # side (primary visuals), then the full city table below spans
            # full width (lookup surface). This keeps the country's map next
            # to its ranking instead of floating at the bottom disconnected.
            _has_country_coords = (
                "Latitude" in country_open_sites.columns
                and not country_open_sites["Latitude"].isna().all()
            )
            _cgeo = pd.DataFrame()
            if _has_country_coords:
                _cgeo = country_open_sites.dropna(subset=["Latitude", "Longitude"]).copy()
                _cgeo = (
                    _cgeo.groupby(["City", "Latitude", "Longitude"], dropna=False)
                    .agg(Trials=("NCTId", "nunique"), Sites=("NCTId", "count"))
                    .reset_index()
                )

            _primary_h = 420
            _c_cmap, _c_cbar = st.columns([0.60, 0.40])
            with _c_cmap:
                st.markdown(f"**{selected_country} site map**")
                if _has_country_coords and not _cgeo.empty:
                    _c_fig = go.Figure()
                    _c_fig.add_trace(go.Scattergeo(
                        lat=_cgeo["Latitude"], lon=_cgeo["Longitude"],
                        mode="markers",
                        marker=dict(
                            size=(_cgeo["Trials"].astype(float).pow(0.6) * 4).clip(lower=5, upper=30),
                            sizemode="diameter",
                            color=THEME["primary"], opacity=0.65,
                            line=dict(width=0.5, color="white"),
                        ),
                        customdata=_cgeo[["City", "Trials", "Sites"]].fillna(""),
                        hovertemplate=(
                            "<b>%{customdata[0]}</b><br>"
                            "%{customdata[1]} trials · %{customdata[2]} site entries"
                            "<extra></extra>"
                        ),
                    ))
                    _c_fig.update_layout(
                        margin=dict(l=0, r=0, t=4, b=0),
                        paper_bgcolor="rgba(0,0,0,0)",
                        geo=dict(
                            bgcolor="rgba(0,0,0,0)",
                            lakecolor="#ddeeff", landcolor="#eef2f7",
                            showframe=False, showcoastlines=False,
                            showcountries=True, countrycolor="rgba(0,0,0,0.12)",
                            fitbounds="locations",
                            projection_type="natural earth",
                        ),
                        height=_primary_h,
                    )
                    st.plotly_chart(_c_fig, width='stretch')
                else:
                    st.info(
                        "Site-level coordinates unavailable for this country "
                        "in the current data. Click **Refresh now** in the "
                        "sidebar to enable site dots."
                    )
            with _c_cbar:
                # Cap the bar to top 15 so dense countries (China, US, …)
                # don't produce an unreadable crammed x-axis. Full list is
                # in the table below.
                _top_cities = country_city_counts.head(15)
                st.markdown(
                    f"**Top cities** "
                    f"<span style='color:#64748b; font-weight:400;'>"
                    f"(showing {len(_top_cities)} of {len(country_city_counts)})</span>",
                    unsafe_allow_html=True,
                )
                st.plotly_chart(
                    make_bar(_top_cities, "City", "OpenSiteCount",
                             height=_primary_h, color=THEME["primary"]),
                    width='stretch',
                )

            # Full city table below — spans full width. Click any row for
            # the trial drilldown.
            st.markdown(
                f"**{selected_country} city table** "
                f"<span style='color:#64748b; font-weight:400;'>"
                f"— click a row to see its trials</span>",
                unsafe_allow_html=True,
            )
            city_event = st.dataframe(
                country_city_counts, width='stretch',
                height=min(340, max(200, len(country_city_counts) * 32 + 48)),
                hide_index=True,
                on_select="rerun", selection_mode="single-row",
                key=f"city_table_{selected_country}",
                column_config={
                    "City": st.column_config.TextColumn("City", width="medium"),
                    "OpenSiteCount": st.column_config.NumberColumn(
                        "Open sites", format="%d",
                        help="Recruiting / active site rows in this city.",
                    ),
                },
            )

            if city_event and city_event.selection.rows:
                selected_idx = city_event.selection.rows[0]
                selected_city = country_city_counts.iloc[selected_idx]["City"]

                st.markdown(f"### Trials with open {selected_country} sites in {selected_city}")

                city_nct_ids = (
                    country_open_sites.loc[
                        country_open_sites["City"].fillna("Unknown") == selected_city, "NCTId",
                    ].dropna().unique()
                )

                city_trial_view = country_study_view[
                    country_study_view["NCTId"].isin(city_nct_ids)
                ].copy()

                if city_trial_view.empty:
                    st.info(f"No study rows found for {selected_city}.")
                else:
                    _cols = [c for c in [
                        "NCTId", "NCTLink", "BriefTitle",
                        "Branch", "DiseaseCategory", "DiseaseEntity",
                        "TargetCategory", "ProductType", "Phase",
                        "OverallStatus", "LeadSponsor",
                        "Cities", "SiteStatuses",
                    ] if c in city_trial_view.columns]
                    st.dataframe(
                        city_trial_view[_cols],
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
                            "Cities": st.column_config.TextColumn(f"{selected_country} cities", width="large"),
                            "SiteStatuses": st.column_config.TextColumn("Site status", width="medium"),
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
        "ClassificationConfidence",
        "Phase", "OverallStatus", "StartYear", "Countries", "LeadSponsor",
    ]

    table_df = df_filt.sort_values(
        ["PhaseOrdered", "Branch", "DiseaseCategory", "NCTId"],
        ascending=[True, True, True, True],
    ).copy()
    table_df["Phase"] = table_df["PhaseLabel"]
    table_df["OverallStatus"] = table_df["OverallStatus"].map(STATUS_DISPLAY).fillna(table_df["OverallStatus"])

    # Search + country-zoom header ------------------------------------------------
    _ALL_COUNTRIES_LABEL = "All countries"
    _zoom_countries = _countries_by_activity()
    _country_options = [_ALL_COUNTRIES_LABEL] + _zoom_countries
    _prev_zoom = st.session_state.get("data_country_zoom", _ALL_COUNTRIES_LABEL)
    _zoom_idx = (
        _country_options.index(_prev_zoom) if _prev_zoom in _country_options else 0
    )

    _c_search, _c_country = st.columns([0.65, 0.35])
    with _c_search:
        search_q = st.text_input(
            "Search",
            value=st.session_state.get("data_search", ""),
            key="data_search",
            placeholder="Title, NCT, sponsor, intervention…",
            label_visibility="collapsed",
        )
    with _c_country:
        _zoom_country = st.selectbox(
            "Zoom into country",
            options=_country_options,
            index=_zoom_idx,
            key="data_country_zoom",
            label_visibility="collapsed",
        )
    _zoom_active = _zoom_country != _ALL_COUNTRIES_LABEL

    # Apply text search across the columns users actually scan
    if search_q:
        q = search_q.lower().strip()
        _search_cols = [c for c in ["NCTId", "BriefTitle", "LeadSponsor", "Interventions"]
                        if c in table_df.columns]
        mask = pd.Series(False, index=table_df.index)
        for _c in _search_cols:
            mask = mask | table_df[_c].astype(str).str.lower().str.contains(q, na=False)
        table_df = table_df[mask].copy()

    # Apply country zoom — swap Countries for Cities + SiteStatuses
    if _zoom_active:
        if "Countries" in show_cols:
            _ci = show_cols.index("Countries")
            show_cols = show_cols[:_ci] + ["Cities", "SiteStatuses"] + show_cols[_ci + 1:]
        else:
            show_cols = show_cols + ["Cities", "SiteStatuses"]
        _country_sites, _country_sv = _country_study_view(_zoom_country)
        if _country_sv.empty:
            table_df = table_df.iloc[0:0]
        else:
            _nct_in_country = set(_country_sv["NCTId"])
            table_df = table_df[table_df["NCTId"].isin(_nct_in_country)].copy()
            _merge_bits = (
                _country_sv[["NCTId", "Cities", "SiteStatuses"]]
                .drop_duplicates("NCTId")
            )
            table_df = table_df.merge(_merge_bits, on="NCTId", how="left")
        st.caption(
            f"Zoomed to **{_zoom_country}** · {len(table_df)} trial"
            f"{'s' if len(table_df) != 1 else ''} with at least one site there"
        )

    st.caption(
        f"{len(table_df):,} trials · click any row to open the full trial record below."
    )
    _table_event = st.dataframe(
        table_df[show_cols],
        width='stretch', height=460, hide_index=True,
        on_select="rerun", selection_mode="single-row",
        key="data_table_sel",
        column_config=_trial_detail_cols({
            "ClassificationConfidence": st.column_config.TextColumn(
                "Conf.", width="small",
                help="high = explicit markers / LLM-validated; medium = defaults or weak markers; low = Unknown branch/entity or combined Unclear.",
            ),
            "Cities": st.column_config.TextColumn(
                f"{_zoom_country} cities" if _zoom_active else "Cities",
                width="large",
            ),
            "SiteStatuses": st.column_config.TextColumn(
                "Site status", width="medium",
            ),
        }),
    )

    # Row-click trial detail — scales to any dataset size (a selectbox would
    # balloon once the filtered set passes 100+ rows).
    _selected_rows = (
        _table_event.selection.rows
        if _table_event and hasattr(_table_event, "selection") else []
    )
    if _selected_rows:
        rec = table_df.iloc[_selected_rows[0]]
        _sel_nct = rec.get("NCTId", "")
        with st.expander(f"**{_sel_nct}** — {rec.get('BriefTitle', '')}", expanded=True):
            d1, d2 = st.columns([1, 1])
            with d1:
                st.markdown(
                    f"""
**Branch**: {rec.get('Branch', '—')}  ·  **Category**: {rec.get('DiseaseCategory', '—')}
**Entity**: {rec.get('DiseaseEntity', '—')}
**All entities matched**: {rec.get('DiseaseEntities', '—') or '—'}
**Trial design**: {rec.get('TrialDesign', '—')}
**Phase**: {rec.get('Phase', '—')}  ·  **Status**: {rec.get('OverallStatus', '—')}
**Start year**: {int(rec['StartYear']) if pd.notna(rec.get('StartYear')) else '—'}
                    """
                )
            with d2:
                _enroll_raw = rec.get('EnrollmentCount', None)
                _enroll_display = int(_enroll_raw) if pd.notna(_enroll_raw) else '—'
                st.markdown(
                    f"""
**Target**: {rec.get('TargetCategory', '—')}
**Product type**: {rec.get('ProductType', '—')}  ·  **Named product**: {rec.get('ProductName', '—') or '—'}
**Modality**: {rec.get('Modality', '—')}
**Age group**: {rec.get('AgeGroup', '—')}  ·  **Sponsor type**: {rec.get('SponsorType', '—')}
**Lead sponsor**: {rec.get('LeadSponsor', '—')}
**Enrollment**: {_enroll_display}
**Classification confidence**: {rec.get('ClassificationConfidence', '—')}
                    """
                )
            # External link + full record
            if rec.get("NCTLink"):
                st.markdown(f"[Open on ClinicalTrials.gov ↗]({rec['NCTLink']})")
            if rec.get("Conditions"):
                st.markdown(f"**Conditions**: {rec['Conditions']}")
            if rec.get("Interventions"):
                st.markdown(f"**Interventions**: {rec['Interventions']}")
            if rec.get("PrimaryEndpoints"):
                st.markdown(f"**Primary endpoints**: {rec['PrimaryEndpoints']}")
            if rec.get("Countries"):
                st.markdown(f"**Countries**: {rec['Countries']}")
            if rec.get("BriefSummary"):
                st.markdown("**Brief summary**")
                st.markdown(f"> {rec['BriefSummary']}")
    else:
        st.info(
            "Select a row in the table above to see the full trial record "
            "and classification breakdown."
        )

    # Three-button download row — current view + all filtered + site-level.
    _view_bits = []
    if _zoom_active:
        _view_bits.append(_zoom_country.lower().replace(" ", "_"))
    if search_q:
        _view_bits.append(
            "search_" + search_q.lower().strip().replace(" ", "_")[:32]
        )
    _view_suffix = "_" + "_".join(_view_bits) if _view_bits else ""
    _view_label = (
        f"Download current view ({len(table_df)} trial"
        f"{'s' if len(table_df) != 1 else ''}) as CSV"
    )

    _d1, _d2, _d3 = st.columns(3)
    with _d1:
        st.download_button(
            label=_view_label,
            data=_csv_with_provenance(table_df[show_cols], "Current view"),
            file_name=f"car_t_onc_view{_view_suffix}.csv",
            mime="text/csv",
            disabled=table_df.empty,
        )
    with _d2:
        st.download_button(
            label="Download all filtered trials as CSV",
            data=_csv_with_provenance(df_filt, "All filtered trials"),
            file_name="car_t_oncology_trials_filtered.csv",
            mime="text/csv",
        )
    with _d3:
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

# Categorical palette — navy / amber / green / red / teal / cyan / slate.
# No purple / violet / indigo per the Rheum × Onc style guide.
NEJM = ["#0b3d91", "#b45309", "#059669", "#dc2626", "#0f766e", "#0891b2", "#0d9488", "#475569"]
NEJM_BLUE    = HEME_COLOR
NEJM_AMBER   = SOLID_COLOR
NEJM_GREEN   = "#059669"
NEJM_RED     = "#dc2626"
NEJM_TEAL    = "#0f766e"  # replaces the former purple slot

_MODALITY_COLORS.update({
    "Auto CAR-T":      NEJM_BLUE,
    "Allo CAR-T":      "#0891b2",
    "CAR-T (unclear)": "#a1a1aa",
    "CAR-γδ T":        "#0d9488",
    "CAR-NK":          NEJM_GREEN,
    "CAR-Treg":        "#6b7280",   # gray-500 (was indigo)
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
# TAB: Deep Dive  (disease-entity focused view + per-product aggregation)
# ---------------------------------------------------------------------------

with tab_deep:
    st.markdown(
        '<p class="small-note">Two focused views that complement the aggregate dashboards: '
        "(1) drill into a single disease entity (category or Tier-3 leaf) to see all trials, "
        "sponsors, phases and targets in one place; (2) aggregate trials by named CAR-T product "
        "so you can track each product's portfolio across indications and phases.</p>",
        unsafe_allow_html=True,
    )

    deep_sub_disease, deep_sub_product, deep_sub_sponsor = st.tabs(
        ["By disease", "By product", "By sponsor type"]
    )

    # ===== By-disease focus =====
    with deep_sub_disease:
        st.subheader("Disease-entity focus")

        # Use the full (unfiltered) df so users can switch entity independently of filters.
        _branch_opts = sorted(df["Branch"].dropna().unique().tolist())
        _cat_opts = sorted(df["DiseaseCategory"].dropna().unique().tolist())
        _ent_opts = set()
        for _s in df["DiseaseEntity"].dropna():
            _ent_opts.add(str(_s))
        for _s in df["DiseaseEntities"].dropna():
            for _e in str(_s).split("|"):
                _e = _e.strip()
                if _e:
                    _ent_opts.add(_e)
        _ent_opts = sorted(_ent_opts)

        cdd1, cdd2, cdd3 = st.columns([1, 1, 1.2])
        with cdd1:
            dd_branch = st.selectbox("Branch", ["(any)"] + _branch_opts, key="dd_branch")
        _cat_filtered = (
            [c for c in _cat_opts if CATEGORY_TO_BRANCH.get(c, "Unknown") == dd_branch or dd_branch == "(any)"]
            if dd_branch != "(any)" else _cat_opts
        )
        with cdd2:
            dd_cat = st.selectbox("Category", ["(any)"] + _cat_filtered, key="dd_cat")
        # Entities scoped by the chosen category if any
        if dd_cat != "(any)":
            _ent_in_cat = sorted(
                [e for e in _ent_opts
                 if ENTITY_TO_CATEGORY.get(e) == dd_cat or e == dd_cat]
            )
            _ent_choices = ["(any)"] + _ent_in_cat
        else:
            _ent_choices = ["(any)"] + _ent_opts
        with cdd3:
            dd_ent = st.selectbox("Entity (leaf)", _ent_choices, key="dd_ent")

        # Build the focus cohort
        focus = df.copy()
        if dd_branch != "(any)":
            focus = focus[focus["Branch"] == dd_branch]
        if dd_cat != "(any)":
            focus = focus[focus["DiseaseCategory"] == dd_cat]
        if dd_ent != "(any)":
            _mask = focus["DiseaseEntity"] == dd_ent
            _mask |= focus["DiseaseEntities"].fillna("").apply(
                lambda s: dd_ent in [e.strip() for e in str(s).split("|") if e.strip()]
            )
            focus = focus[_mask]

        focus = add_phase_columns(focus)

        if focus.empty:
            st.info("No trials match this disease selection. Broaden the filters above.")
        else:
            st.caption(f"**{len(focus)}** trials in focus.")

            # Headline metrics for the focus cohort
            n_focus = len(focus)
            _rec = int(focus["OverallStatus"].isin(["RECRUITING", "NOT_YET_RECRUITING"]).sum())
            _sponsors = focus["LeadSponsor"].dropna().nunique()
            _countries = set()
            for cs in focus["Countries"].dropna():
                for c in str(cs).split("|"):
                    c = c.strip()
                    if c:
                        _countries.add(c)
            _enroll = pd.to_numeric(focus["EnrollmentCount"], errors="coerce").dropna()
            _enroll = _enroll[_enroll <= 1000]  # clip outliers per enrollment convention
            med_e = int(_enroll.median()) if not _enroll.empty else 0

            m1, m2, m3, m4 = st.columns(4)
            with m1: st.metric("Trials", f"{n_focus:,}", help="Matching this disease focus")
            with m2: st.metric("Open / recruiting", f"{_rec:,}")
            with m3: st.metric("Unique sponsors", f"{_sponsors:,}")
            with m4: st.metric("Median enrollment", f"{med_e:,}", help=f"across {len(_countries)} countries")

            dc1, dc2 = st.columns(2)

            with dc1:
                st.markdown("**Phase distribution**")
                _phase_counts = (
                    focus.groupby("PhaseOrdered", observed=False).size()
                    .reset_index(name="Count")
                )
                _phase_counts["Phase"] = _phase_counts["PhaseOrdered"].astype(str).map(PHASE_LABELS)
                _phase_counts = _phase_counts[_phase_counts["Count"] > 0]
                if not _phase_counts.empty:
                    st.plotly_chart(
                        make_bar(_phase_counts, "Phase", "Count", color=HEME_COLOR, height=280),
                        width='stretch',
                    )
                else:
                    st.info("No phase data.")

                st.markdown("**Antigen target breakdown (top 12)**")
                _tgt = (
                    focus.loc[~focus["TargetCategory"].isin(_PLATFORM_LABELS), "TargetCategory"]
                    .fillna("Unknown").value_counts().head(12)
                    .rename_axis("Target").reset_index(name="Count")
                )
                if not _tgt.empty:
                    st.plotly_chart(
                        make_bar(_tgt, "Target", "Count", color=SOLID_COLOR, height=280),
                        width='stretch',
                    )

            with dc2:
                st.markdown("**Trials by start year**")
                _yr = pd.to_numeric(focus["StartYear"], errors="coerce").dropna().astype(int)
                if not _yr.empty:
                    _yr_counts = _yr.value_counts().sort_index().rename_axis("StartYear").reset_index(name="Count")
                    st.plotly_chart(
                        make_bar(_yr_counts, "StartYear", "Count", color=HEME_COLOR, height=280),
                        width='stretch',
                    )
                else:
                    st.info("No start-year data.")

                st.markdown("**Top sponsors (top 10)**")
                _sp = focus["LeadSponsor"].dropna().value_counts().head(10).rename_axis("Sponsor").reset_index(name="Count")
                if not _sp.empty:
                    _sp_sorted = _sp.sort_values("Count", ascending=True)
                    import plotly.express as _px2
                    _sp_fig = _px2.bar(
                        _sp_sorted, x="Count", y="Sponsor", orientation="h",
                        height=max(280, len(_sp_sorted) * 28 + 60),
                        color_discrete_sequence=[MIXED_COLOR], template="plotly_white",
                    )
                    _sp_fig.update_traces(marker_line_width=0, opacity=0.9)
                    _sp_fig.update_layout(
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        margin=dict(l=160, r=16, t=8, b=8),
                        font=dict(family="Inter, sans-serif", size=11, color=THEME["text"]),
                        xaxis_title=None, yaxis_title=None, showlegend=False,
                    )
                    st.plotly_chart(_sp_fig, width='stretch')

            st.markdown("**Trial list (focus cohort)**")
            focus_show = focus.copy()
            focus_show["NCTLink"] = focus_show["NCTId"].apply(
                lambda x: f"https://clinicaltrials.gov/study/{x}" if pd.notna(x) else None
            )
            focus_show["Phase"] = focus_show["PhaseLabel"].fillna(focus_show["Phase"])
            focus_show["OverallStatus"] = focus_show["OverallStatus"].map(STATUS_DISPLAY).fillna(focus_show["OverallStatus"])
            show_cols_focus = [
                "NCTId", "NCTLink", "BriefTitle",
                "Branch", "DiseaseCategory", "DiseaseEntity",
                "TargetCategory", "ProductType", "ProductName",
                "AgeGroup", "SponsorType", "Phase", "OverallStatus",
                "StartYear", "Countries", "LeadSponsor",
            ]
            # Sort first (needs PhaseOrdered), then subset columns for display.
            focus_sorted = focus_show.sort_values(
                ["PhaseOrdered", "StartYear", "NCTId"], na_position="last",
            )
            st.dataframe(
                focus_sorted[[c for c in show_cols_focus if c in focus_sorted.columns]],
                width='stretch', height=420, hide_index=True,
                column_config={
                    "NCTLink": st.column_config.LinkColumn("Trial link", display_text="Open trial"),
                    "BriefTitle": st.column_config.TextColumn("Title", width="large"),
                    "ProductName": st.column_config.TextColumn("Product", width="medium"),
                    "LeadSponsor": st.column_config.TextColumn("Lead sponsor", width="medium"),
                    "Countries": st.column_config.TextColumn("Countries", width="medium"),
                },
            )

            st.download_button(
                "Download focus cohort as CSV",
                data=_csv_with_provenance(focus, f"Deep-dive: {dd_branch} / {dd_cat} / {dd_ent}", include_filters=False),
                file_name=f"deep_dive_{dd_branch}_{dd_cat}_{dd_ent}.csv".replace("(any)", "all").replace(" ", "_"),
                mime="text/csv",
            )

    # ===== By-product aggregation =====
    with deep_sub_product:
        st.subheader("Per-product pipeline view")
        st.caption(
            "Each row is one named CAR-T product (from NAMED_PRODUCT_TARGETS). "
            "Shows the product's portfolio across the filtered dataset: number of trials, "
            "targets, modality, phase distribution, sponsor, countries, median enrollment."
        )

        prod_df = df_filt.dropna(subset=["ProductName"]).copy()
        if prod_df.empty:
            st.info("No named-product trials in the current filter selection.")
        else:
            prod_df["EnrollmentCount"] = pd.to_numeric(prod_df["EnrollmentCount"], errors="coerce")
            prod_df_clean = prod_df.copy()
            prod_df_clean["EnrollCapped"] = prod_df_clean["EnrollmentCount"].where(
                prod_df_clean["EnrollmentCount"] <= 1000
            )

            def _phase_max_rank(phases: "pd.Series") -> str:
                """Return the most-advanced phase label among a set of phase labels."""
                try:
                    cat = pd.Categorical(phases.dropna(), categories=PHASE_ORDER, ordered=True)
                    if len(cat) == 0:
                        return "—"
                    return PHASE_LABELS.get(str(cat.max()), str(cat.max()))
                except Exception:
                    return "—"

            pivot = (
                prod_df_clean.groupby("ProductName")
                .agg(
                    Trials=("NCTId", "nunique"),
                    Target=("TargetCategory", lambda s: s.value_counts().index[0] if not s.empty else "—"),
                    Modality=("Modality", lambda s: s.value_counts().index[0] if not s.empty else "—"),
                    ProductType=("ProductType", lambda s: s.value_counts().index[0] if not s.empty else "—"),
                    FurthestPhase=("PhaseNormalized", _phase_max_rank),
                    Sponsors=("LeadSponsor", lambda s: s.dropna().nunique()),
                    Branches=("Branch", lambda s: ", ".join(sorted(set(s.dropna())))),
                    Categories=("DiseaseCategory", lambda s: ", ".join(sorted(set(s.dropna())))),
                    Countries=("Countries", lambda s: ", ".join(sorted(set(split_pipe_values(s)))[:8])),
                    MedianEnroll=("EnrollCapped", lambda s: int(s.median()) if s.notna().any() else 0),
                )
                .reset_index()
                .sort_values("Trials", ascending=False)
            )

            m1, m2, m3 = st.columns(3)
            with m1: st.metric("Named products", f"{len(pivot):,}", help="In the current filter")
            with m2: st.metric("Total trials", f"{int(pivot['Trials'].sum()):,}")
            with m3: st.metric(
                "Top product",
                pivot.iloc[0]["ProductName"] if not pivot.empty else "—",
                help=f"{int(pivot.iloc[0]['Trials'])} trials" if not pivot.empty else "",
            )

            st.caption(f"{len(pivot):,} named products · sorted by trial count")
            st.dataframe(
                pivot, width='stretch', height=460, hide_index=True,
                column_config={
                    "ProductName": st.column_config.TextColumn("Product", width="medium"),
                    "Target": st.column_config.TextColumn("Primary target", width="small"),
                    "Modality": st.column_config.TextColumn("Modality", width="small"),
                    "ProductType": st.column_config.TextColumn("Product type", width="small"),
                    "FurthestPhase": st.column_config.TextColumn("Furthest phase", width="small"),
                    "Sponsors": st.column_config.NumberColumn("# Sponsors", width="small"),
                    "Branches": st.column_config.TextColumn("Branches", width="small"),
                    "Categories": st.column_config.TextColumn("Categories", width="medium"),
                    "Countries": st.column_config.TextColumn("Countries (top)", width="large"),
                    "MedianEnroll": st.column_config.NumberColumn("Median enrollment", width="small"),
                },
            )

            st.download_button(
                "Download per-product CSV",
                data=_csv_with_provenance(pivot, "Per-product pipeline view", include_filters=True),
                file_name="per_product_pipeline.csv",
                mime="text/csv",
            )

    # ===== By-sponsor-type aggregation =====
    with deep_sub_sponsor:
        st.subheader("Landscape by sponsor type")
        st.caption(
            "Aggregates the filtered dataset by sponsor type "
            "(Industry / Academic / Government / Other). Drill into any "
            "bucket to see its top sponsors, antigen targets, and product mix."
        )

        # Defensive: re-derive SponsorType if a stale cached snapshot lacks it.
        if "SponsorType" not in df_filt.columns and "LeadSponsor" in df_filt.columns:
            try:
                from pipeline import _classify_sponsor as _cs
                df_filt["SponsorType"] = df_filt.apply(
                    lambda r: _cs(r.get("LeadSponsor"), r.get("LeadSponsorClass")),
                    axis=1,
                )
            except Exception:
                pass

        if "SponsorType" not in df_filt.columns:
            st.info("Sponsor type not available in the current snapshot.")
        elif df_filt.empty:
            st.info("No trials in the current filter.")
        else:
            sp_agg = (
                df_filt.groupby("SponsorType")
                .agg(
                    Trials=("NCTId", "nunique"),
                    Open=("OverallStatus", lambda s: int(s.isin(["RECRUITING", "NOT_YET_RECRUITING"]).sum())),
                    Sponsors=("LeadSponsor", "nunique"),
                    TotalEnrolled=("EnrollmentCount",
                                   lambda s: int(pd.to_numeric(s, errors="coerce").fillna(0)
                                                 .where(lambda x: x <= 1000, 0).sum())),
                    MedianEnrollment=("EnrollmentCount",
                                      lambda s: pd.to_numeric(s, errors="coerce")
                                                .where(lambda x: x <= 1000).median()),
                )
                .reset_index()
                .sort_values("Trials", ascending=False)
            )
            sp_agg["MedianEnrollment"] = sp_agg["MedianEnrollment"].fillna(0).astype(int)

            st.caption(f"{len(sp_agg)} sponsor types · sorted by trial count")
            st.dataframe(
                sp_agg, width='stretch', hide_index=True,
                column_config=_landscape_table_cols("SponsorType", "Sponsor type"),
            )

            sp_choices = sp_agg["SponsorType"].tolist()
            pick = st.selectbox(
                "Drill into sponsor type", options=["—"] + sp_choices, key="dd_sponsor_pick",
            )
            if pick and pick != "—":
                sub = df_filt[df_filt["SponsorType"] == pick]

                st.markdown(f"**Top sponsors in *{pick}* ({len(sub)} trials, {sub['LeadSponsor'].nunique()} distinct sponsors)**")
                top_sponsors = (
                    sub["LeadSponsor"].dropna().value_counts().head(10)
                    .rename_axis("Lead sponsor").reset_index(name="Trials")
                )
                st.caption(f"{len(top_sponsors)} sponsors · top-10 by trial count")
                st.dataframe(
                    top_sponsors, width='stretch', hide_index=True,
                    column_config=_mini_count_cols("Lead sponsor"),
                )

                # Antigen target and product-type breakdowns for this sponsor class
                cA, cB = st.columns(2)
                with cA:
                    st.markdown("**Antigen targets**")
                    _tgt_sub = (
                        sub.loc[~sub["TargetCategory"].isin(_PLATFORM_LABELS), "TargetCategory"]
                        .fillna("Unknown").value_counts().head(15)
                        .rename_axis("Target").reset_index(name="Trials")
                    )
                    st.caption(f"{len(_tgt_sub)} antigens · top 15")
                    st.dataframe(
                        _tgt_sub, width='stretch', hide_index=True,
                        column_config=_mini_count_cols("Target"),
                    )
                with cB:
                    st.markdown("**Product types**")
                    _prod_sub = (
                        sub["ProductType"].fillna("Unclear").value_counts()
                        .rename_axis("Product type").reset_index(name="Trials")
                    )
                    st.caption(f"{len(_prod_sub)} product types")
                    st.dataframe(
                        _prod_sub, width='stretch', hide_index=True,
                        column_config=_mini_count_cols("Product type"),
                    )

                # Branch split (useful signal: is industry concentrating on heme or solid?)
                _branch_sub = (
                    sub["Branch"].fillna("Unknown").value_counts()
                    .rename_axis("Branch").reset_index(name="Trials")
                )
                st.markdown("**Branch split**")
                st.caption(f"{len(_branch_sub)} branches")
                st.dataframe(
                    _branch_sub, width='stretch', hide_index=True,
                    column_config=_mini_count_cols("Branch"),
                )

            st.download_button(
                "Download sponsor-type aggregation (CSV)",
                data=_csv_with_provenance(sp_agg, "Landscape by sponsor type", include_filters=True),
                file_name="deep_dive_by_sponsor_type.csv",
                mime="text/csv",
            )


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
        f"Annual trial starts by branch, {_yr_min}–{_yr_max}, for the current "
        "filter. Early years will look sparse if the Overall-status filter "
        "excludes COMPLETED / TERMINATED trials (add them in the sidebar to "
        "see historical activity). Vertical lines mark FDA approvals."
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
        # Trim leading sparse years (<5 trials total) to avoid a long
        # visually-empty left tail; data itself is preserved for CSV export.
        _fig1_first = _first_meaningful_year(year_branch, count_col="Trials") or int(year_branch["StartYear"].min())
        _fig1_last = int(year_branch["StartYear"].max())

        # plotly 6.x: px.area stops auto-stacking. Explicit go.Scatter
        # (stackgroup="one") so Heme / Solid / Mixed / Unknown stack rather
        # than overdraw. Pin opacity on the fill for consistency with the
        # other branch-stacked charts.
        fig1 = go.Figure()
        for _branch in sorted(year_branch["Branch"].unique()):
            _bd = year_branch[year_branch["Branch"] == _branch].sort_values("StartYear")
            _color = BRANCH_COLORS.get(_branch, THEME["primary"])
            fig1.add_trace(go.Scatter(
                x=_bd["StartYear"], y=_bd["Trials"],
                name=_branch, mode="lines",
                stackgroup="one",
                line=dict(width=0.5, color=_color),
                fillcolor=_color,
                opacity=0.85,
            ))
        fig1.update_layout(template="plotly_white", height=420)
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

        # Approved-product overlays. Each regulator has its own tier of
        # vertical lines and year/brand labels; pills below the chart toggle
        # each tier on/off. Brand names (the parenthesised marketing name,
        # e.g. "Kymriah" from "tisa-cel (Kymriah)") are pulled out of the
        # APPROVED_PRODUCTS entries so each line tells the reader both WHEN
        # a product landed and WHAT it was.
        import re as _re_overlay
        _brand_re = _re_overlay.compile(r"\(([^)]+)\)")

        def _brand_of(full_name: str) -> str:
            m = _brand_re.search(full_name)
            return m.group(1).strip() if m else full_name.strip()

        _regulator_products: dict[str, dict[int, list[str]]] = {
            "FDA": {}, "EMA": {}, "NMPA": {},
        }
        for p in APPROVED_PRODUCTS:
            _regulator_products[p["regulator"]].setdefault(p["year"], []).append(
                _brand_of(p["name"])
            )
        # Keep full-name dicts for the below-chart caption (fallback reference).
        fda_products = {yr: [p["name"] for p in APPROVED_PRODUCTS
                             if p["regulator"] == "FDA" and p["year"] == yr]
                        for yr in _regulator_products["FDA"]}
        nmpa_products = {yr: [p["name"] for p in APPROVED_PRODUCTS
                              if p["regulator"] == "NMPA" and p["year"] == yr]
                         for yr in _regulator_products["NMPA"]}
        ema_products = {yr: [p["name"] for p in APPROVED_PRODUCTS
                             if p["regulator"] == "EMA" and p["year"] == yr]
                        for yr in _regulator_products["EMA"]}

        # Per-regulator line styling — solid / dashed / dotted so overlapping
        # years (e.g., 2020 FDA + EMA) stay distinguishable at the same X.
        _REG_STYLE = {
            "FDA":  {"dash": "solid",    "color": "#0b3d91", "width": 1.8, "opacity": 0.85, "y": 1.02},
            "EMA":  {"dash": "dash",     "color": "#1d4ed8", "width": 1.4, "opacity": 0.70, "y": 1.11},
            "NMPA": {"dash": "dot",      "color": "#b45309", "width": 1.4, "opacity": 0.70, "y": 1.20},
        }

        _reg_labels = ["FDA", "NMPA", "EMA"]
        _active_regs = st.session_state.get("fig1_approval_regs", _reg_labels) or []
        _show_fda = "FDA" in _active_regs
        _show_nmpa = "NMPA" in _active_regs
        _show_ema = "EMA" in _active_regs

        def _draw_regulator_tier(reg: str, active: bool) -> None:
            if not active:
                return
            style = _REG_STYLE[reg]
            for yr, brands in sorted(_regulator_products[reg].items()):
                if yr < _fig1_first or yr > _fig1_last:
                    continue
                fig1.add_vline(
                    x=yr, line_width=style["width"], line_dash=style["dash"],
                    line_color=style["color"], opacity=style["opacity"],
                )
                # Compact label: year + brands on two lines so product names
                # sit just under each year. Stacked Y offsets by regulator so
                # tiers don't collide at shared years.
                brand_str = ", ".join(brands)
                label_html = (
                    f"<b>{yr}</b><br>"
                    f"<span style='font-size:10px'>{brand_str}</span>"
                )
                fig1.add_annotation(
                    x=yr, y=style["y"], yref="paper",
                    text=label_html,
                    showarrow=False, xanchor="center", yanchor="bottom",
                    font=dict(size=11, color=style["color"], family="Inter, sans-serif"),
                    align="center",
                )

        _draw_regulator_tier("FDA",  _show_fda)
        _draw_regulator_tier("EMA",  _show_ema)
        _draw_regulator_tier("NMPA", _show_nmpa)

        # Bump top margin proportionally to active tier count so stacked
        # year/brand labels don't overflow into the title area.
        _active_tier_count = sum([_show_fda, _show_ema, _show_nmpa])
        _top_margin = {0: 40, 1: 70, 2: 105, 3: 135}[_active_tier_count]

        _current_year = pd.Timestamp.now().year
        if _yr_max is not None and _yr_max >= _current_year:
            fig1.add_vrect(
                x0=_current_year - 0.5, x1=_current_year + 0.5,
                fillcolor="rgba(0,0,0,0.04)", line_width=0,
            )
            fig1.add_annotation(
                x=_current_year, y=1.09, yref="paper",
                text=f"{_current_year} (partial year)", showarrow=False,
                font=dict(size=10, color=THEME["muted"]),
                yanchor="bottom", xanchor="center",
            )

        # Dynamic top margin — grows with the number of active overlay tiers
        # so stacked year/brand labels sit clear of the plot area.
        fig1.update_layout(margin=dict(l=72, r=36, t=_top_margin, b=110))
        # Trim the visible x-range so pre-meaningful-data years don't dominate.
        fig1.update_xaxes(range=[_fig1_first - 0.5, _fig1_last + 0.5])

        st.plotly_chart(fig1, width='stretch', config=PUB_EXPORT)

        # Pill row — visually reads as a caption-side chip row. Clicking a pill
        # toggles its overlay tier on/off on the chart and below the chart.
        st.pills(
            "Approval overlays",
            options=_reg_labels,
            default=_reg_labels,
            selection_mode="multi",
            key="fig1_approval_regs",
            label_visibility="collapsed",
        )

        # Legend-style caption — explains the line-style hierarchy and
        # lists the underlying generic names. Chart labels carry brand names
        # directly so the caption stays terse.
        _legend_bits = []
        if _show_fda and fda_products:
            _legend_bits.append(
                '<span style="color:#0b3d91; font-weight:600;">—— FDA</span>'
            )
        if _show_ema and ema_products:
            _legend_bits.append(
                '<span style="color:#1d4ed8; font-weight:500;">- - EMA</span>'
            )
        if _show_nmpa and nmpa_products:
            _legend_bits.append(
                '<span style="color:#b45309; font-weight:500;">· · NMPA</span>'
            )

        if _legend_bits:
            # Compact generic-name legend below the chart for anyone who wants
            # the full (generic) names next to the brand names on-chart.
            def _fmt_year_list(year_to_names: dict[int, list[str]]) -> str:
                parts = [f"<b>{yr}</b> {', '.join(names)}" for yr, names in sorted(year_to_names.items())]
                return " &nbsp;·&nbsp; ".join(parts)

            _detail_parts = []
            if _show_fda and fda_products:
                _detail_parts.append(
                    f'<span style="color:#0b3d91; font-weight:600;">FDA</span> '
                    f'<span style="color:#475569;">{_fmt_year_list(fda_products)}</span>'
                )
            if _show_ema and ema_products:
                _detail_parts.append(
                    f'<span style="color:#1d4ed8; font-weight:500;">EMA</span> '
                    f'<span style="color:#475569;">{_fmt_year_list(ema_products)}</span>'
                )
            if _show_nmpa and nmpa_products:
                _detail_parts.append(
                    f'<span style="color:#b45309; font-weight:500;">NMPA</span> '
                    f'<span style="color:#475569;">{_fmt_year_list(nmpa_products)}</span>'
                )
            st.markdown(
                '<div class="pub-fig-caption" '
                'style="margin-top: 0.1rem; font-size: 0.72rem; color: #64748b;">'
                + ' &nbsp;&nbsp;' + ' &nbsp;&nbsp; '.join(_legend_bits) + ' &nbsp;&nbsp; · '
                + ' &nbsp;|&nbsp; '.join(_detail_parts)
                + '.</div>',
                unsafe_allow_html=True,
            )

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
                "Number of trials at each phase in the current filter, stacked by branch.")

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
                "Country-level trial counts for the current filter. Companion 3b breaks the top 10 by branch.")

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

        # Use ISO-3 codes — "country names" locationmode is deprecated.
        geo_counts_iso = geo_counts.copy()
        geo_counts_iso["ISO3"] = geo_counts_iso["Country"].map(_to_iso3)
        geo_counts_iso = geo_counts_iso.dropna(subset=["ISO3"])

        fig3_map = px.choropleth(
            geo_counts_iso, locations="ISO3", locationmode="ISO-3",
            color="Trials", hover_name="Country",
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
            margin=dict(l=120, r=56, t=24, b=130),
            yaxis=_H_YAXIS, xaxis=_H_XAXIS,
            legend=dict(
                orientation="h", yanchor="top", y=-0.28, xanchor="center", x=0.5,
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
                "Distribution and median planned enrollment for the current filter, with subgroup panels by phase, disease category, branch and geography.")

    # Enrollment outlier handling: ClinicalTrials.gov lets registries and
    # real-world-data studies report absurd counts (e.g., 99,999,999 sentinel
    # for the CIBMTR database; 160,602 for a claims-data DLBCL cost study).
    # A prospective CAR-T trial tops out around ~800 patients (CARTITUDE).
    # We cap at 1,000 for the enrollment panels and report the exclusion.
    ENROLL_PLAUSIBLE_CAP = 1000

    df_enroll = df_filt.copy()
    df_enroll["EnrollmentCount"] = pd.to_numeric(df_enroll["EnrollmentCount"], errors="coerce")
    df_enroll_all = df_enroll.dropna(subset=["EnrollmentCount"]).copy()
    df_enroll_all["EnrollmentCount"] = df_enroll_all["EnrollmentCount"].astype(int)
    df_enroll_known = df_enroll_all[df_enroll_all["EnrollmentCount"] <= ENROLL_PLAUSIBLE_CAP].copy()
    n_excluded_outliers = len(df_enroll_all) - len(df_enroll_known)

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

        if n_excluded_outliers > 0:
            st.caption(
                f"Note: {n_excluded_outliers} trial(s) with EnrollmentCount > {ENROLL_PLAUSIBLE_CAP:,} "
                "(registries, real-world-data studies, or sentinel values like 99,999,999) "
                "are excluded from the enrollment panels below but remain in all other analyses."
            )

        # 4a — Enrollment distribution split by Branch (overlaid)
        st.markdown(
            '<div class="pub-fig-sub" style="margin-top: 1rem; '
            'border-top: 1px solid #e5e7eb; padding-top: 0.8rem;">'
            '<strong style="color: #0b1220;">4a — Distribution of planned enrollment, by branch</strong>'
            '</div>',
            unsafe_allow_html=True,
        )
        # Log-scale x-axis — enrollment is right-skewed (many 10–40 patient
        # dose-escalation trials, few 500+ Phase III). Linear axis crams the
        # bulk of trials at the left. Log-spaced bins + log axis spread the
        # distribution so every decade of enrollment size is legible.
        # 100%-stacked horizontal bar — each branch becomes one 0–100% bar
        # composed of five clinically-named size buckets in a sequential
        # navy ramp (light = small, dark = pivotal). Single chart, single
        # insight: reader sees trial-size composition AND compares branches
        # side-by-side without decoding a median / IQR / ECDF.
        _size_buckets = [
            ("Dose-escalation (≤ 20)",   0,   20),
            ("Small cohort (21–50)",    21,   50),
            ("Expansion (51–100)",      51,  100),
            ("Mid-size (101–300)",     101,  300),
            ("Pivotal (> 300)",        301, 10_000),
        ]
        # Single-hue sequential ramp — ordinal perception (small → large).
        _BUCKET_COLORS = {
            "Dose-escalation (≤ 20)":  "#dbeafe",  # blue-100
            "Small cohort (21–50)":    "#93c5fd",  # blue-300
            "Expansion (51–100)":      "#3b82f6",  # blue-500
            "Mid-size (101–300)":      "#1d4ed8",  # blue-700
            "Pivotal (> 300)":         "#0b3d91",  # primary navy
        }

        def _bucketise(series: pd.Series) -> dict[str, int]:
            out = {}
            for label, lo, hi in _size_buckets:
                out[label] = int(((series >= lo) & (series <= hi)).sum())
            return out

        _bar_rows = []
        _branch_meta = []   # for caption: median, n
        for _branch in ["Heme-onc", "Solid-onc"]:
            _vals = df_enroll_known[df_enroll_known["Branch"] == _branch]["EnrollmentCount"]
            if _vals.empty:
                continue
            _counts = _bucketise(_vals)
            _total = sum(_counts.values()) or 1
            for label, _, _ in _size_buckets:
                _bar_rows.append({
                    "Branch":          _branch,
                    "Enrollment size": label,
                    "Pct":             100 * _counts[label] / _total,
                    "Trials":          _counts[label],
                })
            _branch_meta.append(
                f"**{_branch}**: n={_total:,} · median {int(_vals.median())} patients"
            )
        _bar_df = pd.DataFrame(_bar_rows)

        if _bar_df.empty:
            st.info("No enrollment data for Heme-onc or Solid-onc under the current filter.")
        else:
            # Short summary strip above the chart so median / n are at hand
            st.markdown(" &nbsp;&nbsp;·&nbsp;&nbsp; ".join(_branch_meta))

            fig4a = px.bar(
                _bar_df,
                x="Pct", y="Branch",
                color="Enrollment size",
                color_discrete_map=_BUCKET_COLORS,
                orientation="h",
                template="plotly_white",
                category_orders={
                    "Branch":          ["Solid-onc", "Heme-onc"],   # Heme on top visually
                    "Enrollment size": [b[0] for b in _size_buckets],
                },
                text="Pct",
                custom_data=["Trials", "Enrollment size"],
                height=240,
            )
            fig4a.update_traces(
                texttemplate="%{text:.0f}%",
                textposition="inside",
                textfont=dict(size=11, color="white"),
                insidetextanchor="middle",
                marker_line_width=0,
                hovertemplate=(
                    "%{y} · %{customdata[1]}<br>"
                    "%{customdata[0]} trials (%{x:.1f}%)<extra></extra>"
                ),
            )
            fig4a.update_layout(
                **PUB_BASE,
                barmode="stack",
                margin=dict(l=100, r=24, t=16, b=92),
                xaxis=dict(
                    title="% of trials",
                    range=[0, 100],
                    ticksuffix="%",
                    showline=True, linewidth=1.5, linecolor=_AX_COLOR,
                    showgrid=True, gridcolor=_GRID_CLR, gridwidth=0.7,
                    ticks="outside", ticklen=6, tickwidth=1.2,
                    tickfont=dict(size=_TICK_SZ, color=_AX_COLOR),
                    title_font=dict(size=_LAB_SZ, color=_AX_COLOR),
                    zeroline=False,
                ),
                yaxis=dict(
                    title=None,
                    showline=True, linewidth=1.5, linecolor=_AX_COLOR,
                    ticks="outside", ticklen=4, tickwidth=1.2,
                    tickfont=dict(size=_TICK_SZ, color=_AX_COLOR),
                ),
                legend=dict(
                    orientation="h", yanchor="top", y=-0.28, xanchor="center", x=0.5,
                    font=dict(size=10, color=_AX_COLOR),
                    bgcolor="rgba(0,0,0,0)", borderwidth=0, title=None,
                    traceorder="normal",
                ),
            )
            st.plotly_chart(fig4a, width='stretch', config=PUB_EXPORT)
            st.caption(
                "Each bar totals 100%. Size buckets reflect standard CAR-T trial "
                "archetypes (dose-escalation → pivotal). Mixed and Unknown branches "
                "excluded; their enrollment data is preserved in the CSV export."
            )

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
                margin=dict(l=155, r=72, t=24, b=130),
                yaxis=_H_YAXIS, xaxis=_H_XAXIS,
                legend=dict(orientation="h", yanchor="top", y=-0.28, xanchor="center", x=0.5,
                            font=dict(size=11, color=_AX_COLOR), bgcolor="rgba(0,0,0,0)",
                            borderwidth=0, title=None),
            )
            st.plotly_chart(fig4c, width='stretch', config=PUB_EXPORT)

        # Fig 4d (forest plot by subgroup) was removed — 4a/4b/4c already
        # cover the enrollment landscape cleanly, and once a user filter
        # collapsed one axis the forest-plot rows duplicated each other.

        # Tag every trial with a GeoGroup label so the CSV export below
        # still carries the China / Non-China stratification.
        def _geo_group(countries_str) -> str:
            if not countries_str or pd.isna(countries_str):
                return "Unknown"
            return "China" if "China" in str(countries_str).split("|") else "Non-China"
        df_enroll_known["GeoGroup"] = df_enroll_known["Countries"].apply(_geo_group)

        fig4_csv = df_enroll_known[[
            "NCTId", "BriefTitle", "Branch", "DiseaseCategory", "DiseaseEntity",
            "TargetCategory", "ProductType", "Phase", "EnrollmentCount", "GeoGroup",
            "SponsorType",
        ]].sort_values("EnrollmentCount", ascending=False)
        _pub_caption(len(df_filt),
                     extra=f"Enrollment panels restricted to {len(df_enroll_known):,} trials with a numeric enrollment target.")
        st.download_button("Fig 4 data (CSV)",
                           _csv_with_provenance(fig4_csv, "Fig 4 — Enrollment by branch / phase / category"),
                           "fig4_enrollment.csv", "text/csv")
    else:
        st.info("Insufficient enrollment data available.")

    # ------------------------------------------------------------------
    # Fig 5 — Branch → Category → Entity sunburst (signature oncology figure)
    # ------------------------------------------------------------------
    _pub_header("5", "Disease hierarchy (Branch → Category → Entity)",
                "Sunburst of Branch → Category → Entity for trials in the current filter. Click a wedge to zoom.")

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
                "Top antigens among trials in the current filter, split into heme and solid panels. Long tail of low-count antigens aggregated as 'Other (N antigens)'.")

    _UNCLEAR_BUCKET = "Undisclosed / unclear"

    def _target_counts(df_in: pd.DataFrame, include_unclear: bool = False) -> pd.DataFrame:
        s = df_in.loc[~df_in["TargetCategory"].isin(_PLATFORM_LABELS), "TargetCategory"].fillna("Unknown")
        s = s.replace({
            "CAR-T_unspecified": _UNCLEAR_BUCKET,
            "Other_or_unknown":  _UNCLEAR_BUCKET,
            "Unknown":           _UNCLEAR_BUCKET,
        })
        if not include_unclear:
            s = s[s != _UNCLEAR_BUCKET]
        return s.value_counts().rename_axis("Target").reset_index(name="Trials")

    heme_tgt = _target_counts(df_filt[df_filt["Branch"] == "Heme-onc"])
    solid_tgt = _target_counts(df_filt[df_filt["Branch"] == "Solid-onc"])

    col_h, col_s = st.columns(2)

    def _top_n_with_other(df_in: pd.DataFrame, n: int = 15) -> pd.DataFrame:
        """Keep the top-n targets by trial count; aggregate the rest into an
        'Other (k antigens)' row so the long tail doesn't crowd the chart."""
        if len(df_in) <= n:
            return df_in.sort_values("Trials", ascending=False)
        top = df_in.sort_values("Trials", ascending=False).head(n)
        tail = df_in.sort_values("Trials", ascending=False).iloc[n:]
        tail_total = int(tail["Trials"].sum())
        tail_row = pd.DataFrame([{
            "Target": f"Other ({len(tail)} antigens)",
            "Trials": tail_total,
        }])
        return pd.concat([top, tail_row], ignore_index=True)

    def _target_hbar(df_in, color, title, height):
        df_in = _top_n_with_other(df_in, n=15)
        # For a horizontal bar chart the largest value should sit at the top —
        # Plotly renders y-categories bottom-up, so sort ascending *after*
        # truncation (NOT before, which caused CD19 to be dropped entirely).
        df_in = df_in.sort_values("Trials", ascending=True)
        fig = px.bar(
            df_in, x="Trials", y="Target", orientation="h",
            color_discrete_sequence=[color], template="plotly_white",
            height=max(height, len(df_in) * 28 + 80), text="Trials",
        )
        fig.update_traces(marker_line_width=0, opacity=1, textposition="outside",
                          textfont=dict(size=10, color=_AX_COLOR), cliponaxis=False)
        fig.update_layout(
            **PUB_BASE,
            xaxis_title="Number of trials", yaxis_title=None, showlegend=False,
            margin=dict(l=170, r=48, t=40, b=56),
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

    # Summary metrics (based on disclosed antigens only — unclear excluded)
    total_h = int(heme_tgt["Trials"].sum()) if not heme_tgt.empty else 0
    total_s = int(solid_tgt["Trials"].sum()) if not solid_tgt.empty else 0
    cd19_h = int(heme_tgt.loc[heme_tgt["Target"] == "CD19", "Trials"].sum()) if not heme_tgt.empty else 0
    bcma_h = int(heme_tgt.loc[heme_tgt["Target"] == "BCMA", "Trials"].sum()) if not heme_tgt.empty else 0
    # iloc[0] = largest (value_counts returns descending order)
    top_s = solid_tgt.iloc[0] if not solid_tgt.empty else None
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
                "Trial composition over time, by manufacturing approach (autologous / allogeneic / in vivo) and by cell-therapy platform.")

    df_innov = df_filt[df_filt["StartYear"].notna()].copy()
    df_innov["StartYear"] = df_innov["StartYear"].astype(int)

    if not df_innov.empty:
        # Former 7a (product type by start year) was removed — 7c (modality
        # by start year) is a strict superset: Modality is derived from
        # ProductType plus platform-specific text matching, so 7c carries
        # every signal 7a did plus CAR-NK / CAR-γδ T / CAR-Treg / CAAR-T /
        # In vivo CAR as distinct categories.
        df_innov["Modality"] = df_innov.apply(_modality, axis=1)

        # 7a — Modality by branch (renumbered from former 7b)
        st.markdown(
            '<div class="pub-fig-sub" style="margin-top: 1rem; '
            'border-top: 1px solid #e5e7eb; padding-top: 0.8rem;">'
            '<strong style="color: #0b1220;">7a — Cell-therapy modality distribution, by branch</strong>'
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
            template="plotly_white",
            height=max(340, len(mod_branch["Modality"].unique()) * 44 + 160),
            text="Trials",
        )
        fig7b.update_traces(marker_line_width=0, opacity=1, textposition="inside",
                            textfont=dict(size=10, color="white"), insidetextanchor="middle")
        fig7b.update_layout(
            **PUB_BASE, barmode="stack",
            xaxis_title="Number of trials", yaxis_title=None,
            margin=dict(l=120, r=56, t=24, b=130),
            yaxis=_H_YAXIS, xaxis=_H_XAXIS,
            legend=dict(orientation="h", yanchor="top", y=-0.32, xanchor="center", x=0.5,
                        font=dict(size=11, color=_AX_COLOR), bgcolor="rgba(0,0,0,0)",
                        borderwidth=0, title=None),
        )
        st.plotly_chart(fig7b, width='stretch', config=PUB_EXPORT)

        # 7b — Modality mix by start year (renumbered from former 7c)
        st.markdown(
            '<div class="pub-fig-sub" style="margin-top: 1rem; '
            'border-top: 1px solid #e5e7eb; padding-top: 0.8rem;">'
            '<strong style="color: #0b1220;">7b — Modality mix by start year</strong>'
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
        _f7c_first = _first_meaningful_year(mod_year, count_col="Trials") or int(mod_year["StartYear"].min())
        _f7c_last = int(mod_year["StartYear"].max())
        fig7c.update_xaxes(range=[_f7c_first - 0.5, _f7c_last + 0.5])
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

        # CSV export keeps both cuts (product type and modality) available
        # for downstream analysis, even though the figure only renders modality.
        _product_year = (
            df_innov.groupby(["StartYear", "ProductType"]).size().reset_index(name="n_product")
        )
        fig7_csv = pd.merge(
            _product_year.rename(columns={"ProductType": "Category"}),
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
                "Trial counts per (category, antigen) pair in the current filter. Top 15 categories × top 18 antigens shown; undisclosed-antigen trials excluded from the matrix.")

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

    # Quantify the LLM curation layer on the current dataset.
    n_llm_override = int(df.get("LLMOverride", pd.Series(dtype=bool)).sum()) if hasattr(df, "get") else 0

    text = f"""\
METHODS
=======

Data Source and Search Strategy
--------------------------------
Clinical trial data were retrieved from the ClinicalTrials.gov public registry using the
API (v2; {BASE_URL}; accessed {snapshot_date}). A deliberately broad query was applied
using only CAR-based cell-therapy terms ("CAR T", "CAR-T", "chimeric antigen receptor",
"CAR-NK", "CAR NK", "CAAR-T", "CAR-Treg", "gamma delta CAR", "CAR gamma delta"). No
AREA[ConditionSearch] restriction was applied so that trials registered under generic
labels such as "Hematological Malignancies", "Neoplasms", "B-Cell Malignancies", or
"Cancer" — commonly missed by specific-disease keyword queries — are captured. Scope
is enforced downstream by the three-tier classifier and the autoimmune-exclusion filter
(see Inclusion / Exclusion Criteria below). No restriction was placed on study phase,
recruitment status, or geographic location at the query stage.

Inclusion Criteria
------------------
Studies were included if they: (1) described a CAR-based cellular therapy (CAR-T
[autologous, allogeneic, or in vivo], CAR-NK, CAAR-T, CAR-Treg, or CAR-γδ T); and
(2) targeted a hematologic or solid malignancy. No restriction was applied to study
phase, sponsor type, or country. TCR-T products (e.g., afami-cel, NY-ESO-1-directed
TCRs) are out of scope for this v1 dashboard.

Exclusion Criteria
------------------
Studies were excluded if they met any of the following criteria:
    (1) The NCT identifier appeared on a curated hard-exclusion list ({n_hard}
        pre-specified identifiers) OR on the LLM-generated exclusion list (see
        "LLM-Assisted Curation Loop" below). Exclusions cover non-CAR-T
        interventions (bispecifics, mAbs, chemo/TKI, TIL, TCR-T, mRNA vaccines),
        supportive-care / patient-reported-outcome (PRO) studies, long-term
        follow-up registries, observational / biomarker / device trials, and
        out-of-scope indications (COVID-19, non-malignant blood disorders,
        transplant-rejection prophylaxis, etc.).
    (2) Text fields (conditions, title, brief summary, interventions) contained
        one or more of {n_indication} predefined autoimmune / rheumatologic
        keywords and no oncology-adjacent hit. This is the inverse of the sister
        rheumatology app; trials are excluded only when autoimmune is the *sole*
        indication. Generic autoimmune wrappers ("autoimmune diseases",
        "rheumatic diseases") and meta-therapeutic conditions ("cytokine release
        syndrome", "neurotoxicity", "nephrotic syndrome") are also on the list.

Study Selection (PRISMA)
------------------------
    Records identified via database search  : {n_fetched}
    Duplicate records removed               : {prisma.get("n_duplicates_removed", "N/A")}
    Records screened                        : {n_dedup}
    Excluded — hard list + LLM exclusions   : {n_hard_excl}
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
    Gastric/GEJ, TNBC, Neuroblastoma).
Basket trials spanning ≥2 categories are labelled "Basket/Multidisease" and retain
the full list of matched entities in the DiseaseEntities column (pipe-joined).
Branch-level baskets are labelled "Heme basket" or "Advanced solid tumors".

Hybrid Classification Architecture
----------------------------------
Classification combines rule-based keyword matching, curated named-product lookups,
calibrated defaults, and a two-round LLM validation layer. The resolution order for
each trial is:

1. **LLM override** (if the trial's NCT ID appears in llm_overrides.json with
   confidence "high" or "medium") — trusted wholesale.
2. **Leaf-level term match** — ENTITY_TERMS applied per condition chunk and to the
   combined text (conditions | title | brief summary | interventions). ≥2 leaves
   across different categories → "Basket/Multidisease".
3. **Category-level fallback** — CATEGORY_FALLBACK_TERMS (generic tumor-type
   wordings) match to Tier-2 labels.
4. **Branch-level basket terms** — HEME_BASKET_TERMS / SOLID_BASKET_TERMS.
5. **Fall-through** — "Unclassified" (Branch: Unknown).

Target Classification (Priority Order)
--------------------------------------
1. LLM override.
2. Named-product short-circuit (NAMED_PRODUCT_TARGETS) — maps approved and
   late-stage products to their disclosed antigen (tisa-cel, axi-cel, brexu-cel,
   liso-cel, ide-cel, cilta-cel, obe-cel, relma-cel, eque-cel, zevor-cel, GC012F,
   CT041 / satri-cel, BOXR1030, MT027, HBI0101, CT0596, JY231, Meta10-19, …).
3. Platform detection — CAR-NK, CAAR-T, CAR-Treg, CAR-γδ T (text-level match
   with word-boundary enforcement).
4. Antigen detection:
   • Heme-typical (16): CD19, BCMA, CD20, CD22, CD5, CD7, CD30, CD33, CD38, CD70,
     CD123, GPRC5D, FcRH5, SLAMF7, CD79b, Kappa LC, FLT3, CLL1, CD147.
   • Solid-typical (25): GPC3, Claudin 18.2, Mesothelin, GD2, HER2, EGFR,
     EGFRvIII, B7-H3, PSMA, PSCA, CEA, EpCAM, MUC1, CLDN6, NKG2D-L, ROR1,
     L1CAM, CD133, AFP, IL13Rα2, HER3, DLL3, CDH17, GUCY2C, GPNMB.
5. Dual-target combos (7 explicit pairs): CD19/CD22, CD19/CD20, CD19/BCMA,
   BCMA/GPRC5D, BCMA/CD70, HER2/MUC1, GPC3/MSLN.
6. Residual: "CAR-T_unspecified" (CAR mentioned but antigen not in public text)
   or "Other_or_unknown" (no CAR-T confirmation).

Word-boundary matching is used for all term lengths, so prefix collisions
(e.g., EGFR vs EGFRvIII; hodgkin vs non-hodgkin) do not produce false positives.

Product Type Classification with Calibrated Default
----------------------------------------------------
Labels: Autologous / Allogeneic/Off-the-shelf / In vivo / Unclear. Priority:

1. LLM override.
2. "in vivo" in the title; or IN_VIVO_TERMS in the combined text
   (circular RNA, mRNA-LNP, lentiviral nanoparticle, vivovec).
3. Explicit autologous markers: "autoleucel", "autologous".
4. Explicit allogeneic markers: UCART, "off the shelf", "universal CAR-T",
   "universal CD19", "healthy donor", "donor-derived".
5. Named-product lookup (NAMED_PRODUCT_TYPES).
6. Weak autologous/allogeneic keywords (ALLOGENEIC_MARKERS, AUTOL_MARKERS).
7. **Calibrated default** — if the trial is confirmed as CAR-T but no
   product-type marker surfaces, default to "Autologous". This is a calibrated
   choice: autologous cells are the dominant modality in the current
   CAR-T landscape (~85 % of approvals and ongoing trials). Each assignment
   carries a ProductTypeSource tag ("explicit_autologous", "named_product",
   "default_autologous_no_allo_markers", "weak_autologous_marker",
   "llm_override", "no_signal") so downstream users can distinguish high-signal
   from inferred labels.

Classification Confidence
-------------------------
Every trial carries a ClassificationConfidence label (high / medium / low)
combining the above signals:
  • high   — LLM-validated OR explicit markers + known branch/entity/target.
  • medium — default rules (Autologous fallback) OR unclear antigen target
             but known branch/entity.
  • low    — Branch = Unknown OR DiseaseEntity = Unclassified (rare after LLM).

The column is surfaced in the Data tab and can be used to filter analyses
to high-confidence rows only.

LLM-Assisted Curation Loop (validate.py + llm_overrides.json)
-------------------------------------------------------------
The pipeline's keyword layer is supplemented by a structured LLM validation
loop (Claude Opus). Workflow:

1. The Methods & Appendix tab exports `curation_loop.csv` — every trial with
   any field in {{Branch=Unknown, DiseaseEntity=Unclassified,
   TargetCategory ∈ [CAR-T_unspecified, Other_or_unknown], ProductType=Unclear}}.
2. A batched subagent workflow (6 parallel Claude agents, ~130 trials each)
   receives each batch CSV plus an allowed_values.json listing every valid
   branch / category / entity / target / product label. Each agent emits a
   strict-schema JSON array (nct_id, branch, disease_category, disease_entity,
   target_category, product_type, exclude, exclude_reason, confidence, notes).
3. A second round re-curates only the trials still low-confidence after the
   architectural upgrade, with stricter exclusion criteria (PRO studies,
   registries, bispecifics/mAbs, device trials, out-of-scope indications).
4. Results are merged into llm_overrides.json. On load the pipeline populates:
     _LLM_OVERRIDES         — per-trial classification overrides
                              (confidence ∈ {{high, medium}}, exclude=false).
     _LLM_EXCLUDED_NCT_IDS  — trials flagged exclude=true with high/medium
                              confidence; these are dropped at the PRISMA
                              hard-exclusion stage, the same step as the
                              manually curated hard-exclusion list.
5. The `LLMOverride` boolean column in the trial dataframe flags which rows
   were reclassified by the LLM ({n_llm_override} of {n_included} in the current
   dataset). Users can independently verify any override by inspecting the
   corresponding entry in llm_overrides.json alongside the ClinicalTrials.gov
   record.

This hybrid (rules + defaults + LLM) approach avoids brittleness (a pure
keyword system) and avoids cost/irreproducibility (a pure LLM system):
deterministic rules handle the bulk, the calibrated Autologous default
cleans up cases where information is genuinely absent, and the LLM layer
resolves the residual ambiguous cases with full reasoning and explicit
confidence tags.

Cell-therapy Modality
---------------------
Each trial is assigned to one of eight mechanistically distinct modality categories:
Auto CAR-T, Allo CAR-T, CAR-T (unclear), CAR-γδ T, CAR-NK, CAR-Treg, CAAR-T,
In vivo CAR. Modality is derived from TargetCategory + ProductType + text-level
γδ-T detection.

Sponsor Classification
----------------------
Lead sponsors are classified into four categories — Industry, Academic, Government,
Other — using a hierarchical heuristic that combines CT.gov's LeadSponsorClass
with keyword matching on the sponsor name. Resolution order:
  1. Strong government signals (word-boundary acronyms NIH / NCI / FDA / EMA /
     DOD / VA / CDC, plus full-phrase anchors "National Institutes of Health",
     "Department of Veterans Affairs", etc.) — these override academic markers
     because agencies like NCI are genuine federal funders despite containing
     "institute" in the name.
  2. Academic markers in the name (hospital, university, medical center, cancer
     center, klinik, affiliated hospital, PLA hospital, memorial Sloan, Dana-Farber,
     MD Anderson, …) — override CT.gov's OTHER_GOV class, which over-applies to
     Chinese provincial hospitals and Russian "Federal Research Institute"
     entries that function academically.
  3. CT.gov LeadSponsorClass for unambiguous codes (INDUSTRY → Industry; NIH /
     FED → Government; INDIV → Academic). OTHER_GOV is deliberately dropped
     (an audit reduced Government from 147 misclassified trials to 36 genuine NCI
     entries).
  4. Known pharma brand names without a corporate suffix (Novartis, Kite, Gilead,
     Janssen, Legend, Autolus, …).
  5. Industry corporate suffixes and industry-language keywords (Inc, GmbH, AG,
     S.p.A, Pharma, Biotech, Therapeutics, …).
  6. Secondary academic hints ("Institute of …", "Research Institute", Inserm,
     provincial, fondazione).
  7. PI detection (`_looks_like_personal_name`) — investigator-initiated trials
     where the sponsor field is the PI name ("Carl June, M.D.", "Stephan Grupp")
     get explicit routing to Academic based on degree markers + 2–4 short
     alphabetical tokens with no institutional keyword.
  8. Default to Academic for non-empty, unclassified names (overwhelmingly
     investigator-initiated in practice); "Other" reserved for truly empty strings.

Enrollment Analysis
-------------------
Planned enrollment counts were extracted from the EnrollmentCount field
(type = Anticipated or Actual) and coerced to numeric; missing or non-numeric
values were excluded from enrollment analyses (Figure 4). To remove data-entry
artifacts (registry placeholders like 99,999,999; real-world-data cost studies
with 160,000+ rows), enrollment is capped at 1,000 patients — a threshold safely
above the largest prospective CAR-T trial (cilta-cel CARTITUDE, n≈790). Excluded
outliers are reported in a caption.

Figure 4 presents a three-panel enrollment landscape:
  4a — Branch-stratified trial-size composition across five clinical buckets:
       Dose-escalation (≤ 20), Small cohort (21–50), Expansion (51–100),
       Mid-size (101–300), Pivotal (> 300). Rendered as a 100%-stacked
       horizontal bar (one bar per branch, single-hue sequential navy ramp so
       bucket order is pre-attentively readable), which shows trial-size
       composition and inter-branch comparison in a single chart without
       requiring readers to decode a histogram, ECDF, or IQR.
  4b — Median planned enrollment by Phase × Branch.
  4c — Per-trial enrollment dot plot, phase-ordered.

Data Processing
---------------
All processing was performed in Python (pandas {pd.__version__}) using a custom ETL
pipeline. Text normalisation includes lowercasing, Unicode normalisation, R/R →
"relapsed refractory" expansion, hyphen-to-space conversion (so "b-cell",
"chromosome-positive" match the space-separated forms), and "non hodgkin" →
"nonhodgkin" collapse to prevent "hodgkin lymphoma" from matching inside
"non-Hodgkin lymphoma" context. Term matching uses whole-word boundary regex for
all term lengths, so prefix collisions (EGFR vs EGFRvIII, CD19 vs CD190) do not
produce false positives. Classification rules, term dictionaries, and named-product
lookups are versioned in config.py and iteratively updated via the curation loop.

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
    rows.append({"Tier": "Exclusion", "Branch": "—", "Label": "Autoimmune/meta keyword exclusion",
                  "Terms (sample)": "; ".join(EXCLUDED_INDICATION_TERMS[:6]) + "…",
                  "N entities": len(EXCLUDED_INDICATION_TERMS)})
    rows.append({"Tier": "LLM curation",
                  "Branch": "—",
                  "Label": "Classification overrides (llm_overrides.json)",
                  "Terms (sample)": "Per-trial Branch/Category/Entity/Target/Product overrides from two-round Claude Opus validation.",
                  "N entities": 0})
    rows.append({"Tier": "LLM curation",
                  "Branch": "—",
                  "Label": "ClassificationConfidence",
                  "Terms (sample)": "high / medium / low band per trial, combining LLM validation, rule strength, and ProductTypeSource.",
                  "N entities": 0})
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
- **Archival DOI**: [10.5281/zenodo.19738097](https://doi.org/10.5281/zenodo.19738097)
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
    ">Klinik I für Innere Medizin<br>Hämatologie und Onkologie<br>Klinische Immunologie und Rheumatologie</div>
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
        f"Klinik I für Innere Medizin, Hämatologie und Onkologie, "
        f"Klinische Immunologie und Rheumatologie, "
        f"Universitätsklinikum Köln; {date.today().year} "
        f"[cited {date.today().isoformat()}]. "
        f"DOI: 10.5281/zenodo.19738097. "
        f"Data snapshot: {snap_date}. "
        f"Available from: https://onc-car-t-trial-monitor.streamlit.app"
    )
    st.code(citation, language="text")
    st.caption(
        "Vancouver-style citation. "
        "DOI: [10.5281/zenodo.19738097](https://doi.org/10.5281/zenodo.19738097)"
    )

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
Klinik I für Innere Medizin
Hämatologie und Onkologie
Klinische Immunologie und Rheumatologie
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
