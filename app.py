import re
import streamlit as st
import pandas as pd
import plotly.express as px

from pipeline import build_clean_dataframe, build_sites_dataframe
from config import (
    ONTOLOGY,
    CATEGORY_TO_BRANCH,
    HEME_CATEGORIES,
    SOLID_CATEGORIES,
    BASKET_MULTI_LABEL,
    HEME_BASKET_LABEL,
    SOLID_BASKET_LABEL,
    UNCLASSIFIED_LABEL,
    AMBIGUOUS_ENTITY_TOKENS,
    AMBIGUOUS_TARGET_TOKENS,
)

st.set_page_config(
    page_title="CAR-T Oncology Trials Monitor",
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

OPEN_SITE_STATUSES = {
    "RECRUITING",
    "NOT_YET_RECRUITING",
    "ENROLLING_BY_INVITATION",
    "ACTIVE_NOT_RECRUITING",
}

PHASE_ORDER = [
    "EARLY_PHASE1",
    "PHASE1",
    "PHASE1|PHASE2",
    "PHASE2",
    "PHASE2|PHASE3",
    "PHASE3",
    "PHASE4",
    "Unknown",
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

THEME = {
    "bg": "#0b0f14",
    "panel": "#11161d",
    "panel_2": "#151c24",
    "panel_3": "#1a232d",
    "text": "#ecf1f7",
    "muted": "#9aa6b2",
    "faint": "#6f7b87",
    "border": "rgba(255,255,255,0.08)",
    "primary": "#21b3a3",
    "primary_2": "#123b39",
    "accent": "#d38a5a",
    "heme": "#21b3a3",
    "solid": "#d38a5a",
    "mixed": "#b58bdb",
    "grid": "rgba(255,255,255,0.08)",
    "shadow": "0 12px 32px rgba(0,0,0,0.28)",
}

BRANCH_COLORS = {
    "Heme-onc": THEME["heme"],
    "Solid-onc": THEME["solid"],
    "Mixed": THEME["mixed"],
    "Unknown": THEME["faint"],
}

px.defaults.template = "plotly_dark"

st.markdown(
    f"""
    <style>
    html, body, [class*="css"] {{
        color: {THEME["text"]};
    }}

    .stApp {{
        background:
            radial-gradient(circle at top left, rgba(33,179,163,0.08), transparent 30%),
            radial-gradient(circle at top right, rgba(211,138,90,0.06), transparent 28%),
            linear-gradient(180deg, #0b0f14 0%, #0d1218 100%);
        color: {THEME["text"]};
    }}

    .block-container {{
        max-width: 1450px;
        padding-top: 1.6rem;
        padding-bottom: 2.2rem;
    }}

    h1, h2, h3 {{
        color: {THEME["text"]};
        letter-spacing: -0.02em;
    }}

    .hero {{
        position: relative;
        overflow: hidden;
        padding: 1.8rem 2rem;
        border: 1px solid {THEME["border"]};
        border-radius: 24px;
        background: linear-gradient(180deg, rgba(21,28,36,0.96) 0%, rgba(17,22,29,0.96) 100%);
        box-shadow: {THEME["shadow"]};
        margin-bottom: 1.2rem;
    }}

    .hero:before {{
        content: "";
        position: absolute;
        inset: 0;
        background: linear-gradient(120deg, rgba(33,179,163,0.08), transparent 35%, rgba(211,138,90,0.06) 100%);
        pointer-events: none;
    }}

    .hero-title {{
        position: relative;
        z-index: 1;
        font-size: 2rem;
        font-weight: 700;
        margin-bottom: 0.4rem;
        color: {THEME["text"]};
    }}

    .hero-sub {{
        position: relative;
        z-index: 1;
        font-size: 1rem;
        line-height: 1.65;
        color: {THEME["muted"]};
        max-width: 900px;
    }}

    .section-card {{
        background: linear-gradient(180deg, rgba(21,28,36,0.95) 0%, rgba(17,22,29,0.96) 100%);
        border: 1px solid {THEME["border"]};
        border-radius: 20px;
        padding: 1.1rem 1.1rem 0.9rem 1.1rem;
        box-shadow: {THEME["shadow"]};
        margin-bottom: 1rem;
    }}

    .metric-card {{
        background: linear-gradient(180deg, rgba(21,28,36,0.96) 0%, rgba(17,22,29,0.96) 100%);
        border: 1px solid {THEME["border"]};
        border-radius: 18px;
        padding: 1rem 1rem 0.85rem 1rem;
        box-shadow: {THEME["shadow"]};
    }}

    .metric-label {{
        font-size: 0.82rem;
        color: {THEME["muted"]};
        margin-bottom: 0.45rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }}

    .metric-value {{
        font-size: 1.95rem;
        font-weight: 700;
        color: {THEME["text"]};
        line-height: 1.05;
    }}

    .metric-foot {{
        margin-top: 0.4rem;
        font-size: 0.82rem;
        color: {THEME["faint"]};
    }}

    .small-note {{
        color: {THEME["muted"]};
        font-size: 0.92rem;
        margin-top: 0.35rem;
        margin-bottom: 0.5rem;
    }}

    div[data-testid="stSidebar"] {{
        background: linear-gradient(180deg, #0f141b 0%, #10161e 100%);
        border-right: 1px solid {THEME["border"]};
    }}

    div[data-testid="stSidebar"] h1,
    div[data-testid="stSidebar"] h2,
    div[data-testid="stSidebar"] h3,
    div[data-testid="stSidebar"] label,
    div[data-testid="stSidebar"] p,
    div[data-testid="stSidebar"] span {{
        color: {THEME["text"]};
    }}

    .stButton > button,
    .stDownloadButton > button {{
        background: linear-gradient(180deg, #1ab09f 0%, #149282 100%);
        color: white;
        border: 0;
        border-radius: 999px;
        padding: 0.62rem 1rem;
        font-weight: 600;
        box-shadow: 0 8px 20px rgba(33,179,163,0.18);
    }}

    .stButton > button:hover,
    .stDownloadButton > button:hover {{
        background: linear-gradient(180deg, #1fc0ae 0%, #169b8a 100%);
        color: white;
    }}

    div[data-testid="stTabs"] button {{
        color: {THEME["muted"]};
    }}

    div[data-testid="stTabs"] button[aria-selected="true"] {{
        color: {THEME["text"]};
    }}

    div[data-testid="stDataFrame"] {{
        border: 1px solid {THEME["border"]};
        border-radius: 16px;
        overflow: hidden;
        background: {THEME["panel"]};
    }}

    div[data-baseweb="select"] > div,
    div[data-baseweb="input"] > div {{
        background-color: {THEME["panel_3"]};
        border-color: {THEME["border"]};
        color: {THEME["text"]};
    }}

    .stTextInput input, .stSelectbox div, .stMultiSelect div {{
        color: {THEME["text"]};
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Data loading (cached)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60 * 60)
def load_trials(max_records: int = 5000, statuses: tuple[str, ...] = ()) -> pd.DataFrame:
    statuses_list = list(statuses) if statuses else None
    return build_clean_dataframe(max_records=max_records, statuses=statuses_list)


@st.cache_data(ttl=60 * 60)
def load_sites(max_records: int = 5000, statuses: tuple[str, ...] = ()) -> pd.DataFrame:
    statuses_list = list(statuses) if statuses else None
    return build_sites_dataframe(max_records=max_records, statuses=statuses_list)


# ---------------------------------------------------------------------------
# Visual helpers
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


def make_bar(df_plot, x, y, height=360, color="#21b3a3"):
    fig = px.bar(
        df_plot,
        x=x,
        y=y,
        height=height,
        color_discrete_sequence=[color],
        template="plotly_dark",
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=10, b=10),
        font=dict(color=THEME["text"]),
        xaxis_title=None,
        yaxis_title=None,
        showlegend=False,
    )
    fig.update_xaxes(showgrid=False, color=THEME["muted"])
    fig.update_yaxes(gridcolor=THEME["grid"], color=THEME["muted"])
    return fig


def make_stacked_bar(df_plot, x, y, color, height=360, color_map=None):
    fig = px.bar(
        df_plot,
        x=x,
        y=y,
        color=color,
        height=height,
        template="plotly_dark",
        color_discrete_map=color_map or BRANCH_COLORS,
    )
    fig.update_layout(
        barmode="stack",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=10, b=10),
        font=dict(color=THEME["text"]),
        xaxis_title=None,
        yaxis_title=None,
        legend_title=None,
    )
    fig.update_xaxes(showgrid=False, color=THEME["muted"])
    fig.update_yaxes(gridcolor=THEME["grid"], color=THEME["muted"])
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
        "EARLYPHASE1": "EARLY_PHASE1",
        "EARLYPHASEI": "EARLY_PHASE1",
        "PHASE1": "PHASE1",
        "PHASEI": "PHASE1",
        "PHASE1|PHASE2": "PHASE1|PHASE2",
        "PHASEI|PHASEII": "PHASE1|PHASE2",
        "PHASE12": "PHASE1|PHASE2",
        "PHASE1PHASE2": "PHASE1|PHASE2",
        "PHASE2": "PHASE2",
        "PHASEII": "PHASE2",
        "PHASE2|PHASE3": "PHASE2|PHASE3",
        "PHASEII|PHASEIII": "PHASE2|PHASE3",
        "PHASE23": "PHASE2|PHASE3",
        "PHASE2PHASE3": "PHASE2|PHASE3",
        "PHASE3": "PHASE3",
        "PHASEIII": "PHASE3",
        "PHASE4": "PHASE4",
        "PHASEIV": "PHASE4",
        "N/A": "Unknown",
        "NA": "Unknown",
    }
    return mapping.get(s_upper, s_upper if s_upper in PHASE_ORDER else "Unknown")


def add_phase_columns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["Phase"] = out["Phase"].fillna("Unknown")
    out["PhaseNormalized"] = out["Phase"].apply(normalize_phase_value)
    out["PhaseOrdered"] = pd.Categorical(out["PhaseNormalized"], categories=PHASE_ORDER, ordered=True)
    out["PhaseLabel"] = out["PhaseNormalized"].map(PHASE_LABELS).fillna(out["Phase"])
    return out


def entity_in_trial(entities_str: str, entity: str) -> bool:
    """Check if a leaf entity appears in a pipe-joined entities string."""
    if not entities_str or pd.isna(entities_str):
        return False
    return entity in [e.strip() for e in str(entities_str).split("|") if e.strip()]


# ---------------------------------------------------------------------------
# Hero
# ---------------------------------------------------------------------------

st.markdown(
    """
    <div class="hero">
        <div class="hero-title">CAR-T and Related Cell Therapies in Oncology</div>
        <div class="hero-sub">
            A monitoring dashboard for ClinicalTrials.gov studies across heme-onc and solid-onc.
            Three-tier disease hierarchy (Branch → Category → Entity), target classification,
            clickable NCT links, and a geography view with a Germany deep-dive.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Sidebar — data pull
# ---------------------------------------------------------------------------

st.sidebar.header("Data pull")
selected_statuses = st.sidebar.multiselect(
    "Statuses to pull",
    STATUS_OPTIONS,
    default=["RECRUITING", "NOT_YET_RECRUITING", "ACTIVE_NOT_RECRUITING"],
)

with st.spinner("Fetching and processing ClinicalTrials.gov data..."):
    df = load_trials(statuses=tuple(selected_statuses))
    df_sites = load_sites(statuses=tuple(selected_statuses))

df = add_phase_columns(df)

if df.empty:
    st.error("No studies were returned. Try broadening the status filters.")
    st.stop()


# ---------------------------------------------------------------------------
# Sidebar — cascading disease filter (Branch → Category → Entity)
# ---------------------------------------------------------------------------

st.sidebar.header("Filters")
st.sidebar.caption("Disease filter cascades: Branch narrows Category, Category narrows Entity.")

branch_options_all = sorted(df["Branch"].dropna().unique().tolist())
branch_sel = st.sidebar.multiselect(
    "Branch",
    options=branch_options_all,
    default=branch_options_all,
    help="Top-level: Heme-onc, Solid-onc, Mixed, Unknown.",
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
    if category_sel
    else df_after_branch
)

# Entity options drawn from the pipe-joined DiseaseEntities union for basket-safe filtering,
# plus any primary DiseaseEntity values that are category / branch-basket / unclassified labels.
_entities = set()
for val in df_after_cat["DiseaseEntities"].dropna():
    for e in str(val).split("|"):
        e = e.strip()
        if e:
            _entities.add(e)
# Also include DiseaseEntity labels that aren't real leaves (basket/unknown labels).
for val in df_after_cat["DiseaseEntity"].dropna():
    _entities.add(str(val))
entity_options_all = sorted(_entities)
entity_sel = st.sidebar.multiselect(
    "Disease entity",
    options=entity_options_all,
    default=entity_options_all,
    help="Basket/multi-disease trials appear under every entity they enroll.",
)

# Phase (multi-select, displayed as labels)
phase_options = [PHASE_LABELS[p] for p in PHASE_ORDER if p in set(df["PhaseNormalized"].astype(str))]
phase_sel = st.sidebar.multiselect(
    "Phase",
    options=phase_options,
    default=phase_options,
)

# Target category
target_options = sorted(df["TargetCategory"].dropna().unique().tolist())
target_sel = st.sidebar.multiselect(
    "Target category",
    options=target_options,
    default=target_options,
)

# Overall status
status_options = sorted(df["OverallStatus"].dropna().unique().tolist())
status_sel = st.sidebar.multiselect(
    "Overall status",
    options=status_options,
    default=status_options,
)

# Product type
product_options = sorted(df["ProductType"].dropna().unique().tolist())
product_sel = st.sidebar.multiselect(
    "Product type",
    options=product_options,
    default=product_options,
)

# Country
all_countries = set()
for cs in df["Countries"].dropna():
    for c in str(cs).split("|"):
        c = c.strip()
        if c:
            all_countries.add(c)
country_options = sorted(all_countries)
country_sel = st.sidebar.multiselect(
    "Country",
    options=country_options,
    default=country_options,
)

# Data-quality expander
with st.sidebar.expander("Data quality / missing classifications", expanded=False):
    cols_to_check = ["Branch", "DiseaseCategory", "DiseaseEntity", "Phase", "TargetCategory", "OverallStatus", "Countries"]
    rows = []
    ambiguous_disease = [t.lower() for t in AMBIGUOUS_ENTITY_TOKENS] + ["basket/multidisease", "advanced solid tumors", "heme basket"]
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
    st.dataframe(quality_df, use_container_width=True, hide_index=True)
    st.caption(
        "Ambiguous labels counted: unclassified / heme-onc_other / solid-onc_other / "
        "basket buckets (disease); CAR_T_unspecified / other_or_unknown (target)."
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
    # Basket-safe entity filter: match if primary DiseaseEntity is selected,
    # OR any element in the pipe-joined DiseaseEntities is selected.
    entity_set = set(entity_sel)
    primary_match = df["DiseaseEntity"].isin(entity_set)
    list_match = df["DiseaseEntities"].fillna("").apply(
        lambda s: any(e in entity_set for e in str(s).split("|") if e)
    )
    mask &= (primary_match | list_match)

if phase_sel:
    selected_phase_norm = [k for k, v in PHASE_LABELS.items() if v in phase_sel]
    mask &= df["PhaseNormalized"].isin(selected_phase_norm)

if target_sel:
    mask &= df["TargetCategory"].isin(target_sel)

if status_sel:
    mask &= df["OverallStatus"].isin(status_sel)

if product_sel:
    mask &= df["ProductType"].isin(product_sel)

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
# Germany deep-dive preparation
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
                    "NCTId",
                    "BriefTitle",
                    "Branch",
                    "DiseaseCategory",
                    "DiseaseEntity",
                    "TargetCategory",
                    "ProductType",
                    "Phase",
                    "PhaseNormalized",
                    "PhaseOrdered",
                    "PhaseLabel",
                    "OverallStatus",
                    "LeadSponsor",
                ]
            ].drop_duplicates(subset=["NCTId"]),
            on="NCTId",
            how="left",
        )

        germany_study_view["NCTLink"] = germany_study_view["NCTId"].apply(
            lambda x: f"https://clinicaltrials.gov/study/{x}" if pd.notna(x) else None
        )
        germany_study_view["Phase"] = germany_study_view["PhaseLabel"].fillna(germany_study_view["Phase"])

        germany_study_view = germany_study_view[
            [
                "NCTId",
                "NCTLink",
                "BriefTitle",
                "Branch",
                "DiseaseCategory",
                "DiseaseEntity",
                "TargetCategory",
                "ProductType",
                "Phase",
                "PhaseNormalized",
                "PhaseOrdered",
                "OverallStatus",
                "LeadSponsor",
                "GermanCities",
                "GermanSiteStatuses",
            ]
        ].sort_values(["PhaseOrdered", "DiseaseCategory", "NCTId"], na_position="last")


# ---------------------------------------------------------------------------
# Metric row
# ---------------------------------------------------------------------------

total_trials = len(df_filt)
recruiting_trials = int(df_filt["OverallStatus"].isin(["RECRUITING", "NOT_YET_RECRUITING"]).sum())
german_trials_count = germany_study_view["NCTId"].nunique() if not germany_study_view.empty else 0
top_target = df_filt["TargetCategory"].value_counts().idxmax() if not df_filt["TargetCategory"].dropna().empty else "—"
heme_count = int((df_filt["Branch"] == "Heme-onc").sum())
solid_count = int((df_filt["Branch"] == "Solid-onc").sum())

m1, m2, m3, m4, m5 = st.columns(5)
with m1:
    metric_card("Filtered trials", total_trials, "Trials matching current filters")
with m2:
    metric_card("Open / recruiting", recruiting_trials, "Recruiting or not yet recruiting")
with m3:
    metric_card("Heme vs Solid", f"{heme_count} / {solid_count}", "Heme-onc / Solid-onc split")
with m4:
    metric_card("German-linked trials", german_trials_count, "Unique filtered studies with an open German site")
with m5:
    metric_card("Top target", top_target, "Most common target category")

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

tab_overview, tab_geo, tab_data = st.tabs(["Overview", "Geography / Map", "Data"])

with tab_overview:
    # ---- Sunburst: Branch → Category → Entity ----
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("Disease hierarchy (Branch → Category → Entity)")
    if not df_filt.empty:
        sun_df = (
            df_filt[["Branch", "DiseaseCategory", "DiseaseEntity"]]
            .fillna("Unknown")
            .assign(Count=1)
            .groupby(["Branch", "DiseaseCategory", "DiseaseEntity"], as_index=False)
            .sum()
        )
        fig_sun = px.sunburst(
            sun_df,
            path=["Branch", "DiseaseCategory", "DiseaseEntity"],
            values="Count",
            color="Branch",
            color_discrete_map=BRANCH_COLORS,
            height=460,
            template="plotly_dark",
        )
        fig_sun.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=10, r=10, t=10, b=10),
            font=dict(color=THEME["text"]),
        )
        st.plotly_chart(fig_sun, use_container_width=True)
    else:
        st.info("No trials for the current filter selection.")
    st.markdown("</div>", unsafe_allow_html=True)

    left, right = st.columns([1.05, 1])

    with left:
        # ---- Trials by disease category (stacked by branch) ----
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("Trials by disease category")
        counts_cat = (
            df_filt.groupby(["DiseaseCategory", "Branch"], as_index=False)
            .size()
            .rename(columns={"size": "Count"})
            .sort_values("Count", ascending=False)
        )
        if not counts_cat.empty:
            st.plotly_chart(
                make_stacked_bar(counts_cat, "DiseaseCategory", "Count", "Branch"),
                use_container_width=True,
            )
        else:
            st.info("No trials for the current filter selection.")
        st.markdown("</div>", unsafe_allow_html=True)

        # ---- Trials by phase (stacked by branch) ----
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("Trials by phase")
        counts_phase = (
            df_filt.groupby(["PhaseOrdered", "Branch"], observed=False)
            .size()
            .reset_index(name="Count")
        )
        counts_phase["Phase"] = counts_phase["PhaseOrdered"].astype(str).map(PHASE_LABELS)
        counts_phase = counts_phase[counts_phase["Count"] > 0].copy()
        counts_phase["Phase"] = pd.Categorical(
            counts_phase["Phase"],
            categories=[PHASE_LABELS[p] for p in PHASE_ORDER],
            ordered=True,
        )
        counts_phase = counts_phase.sort_values("Phase")
        if not counts_phase.empty:
            fig_phase = make_stacked_bar(counts_phase, "Phase", "Count", "Branch")
            fig_phase.update_xaxes(
                categoryorder="array", categoryarray=[PHASE_LABELS[p] for p in PHASE_ORDER]
            )
            st.plotly_chart(fig_phase, use_container_width=True)
        else:
            st.info("No trials for the current filter selection.")
        st.markdown("</div>", unsafe_allow_html=True)

    with right:
        # ---- Trials by target category ----
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("Trials by target category")
        counts_target = (
            df_filt["TargetCategory"]
            .fillna("Unknown")
            .value_counts()
            .rename_axis("TargetCategory")
            .reset_index(name="Count")
        )
        if not counts_target.empty:
            st.plotly_chart(
                make_bar(counts_target.head(20), "TargetCategory", "Count", color="#6fb7ff"),
                use_container_width=True,
            )
        else:
            st.info("No trials for the current filter selection.")
        st.markdown("</div>", unsafe_allow_html=True)

        # ---- Trials by start year (line, stacked area by branch) ----
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("Trials by start year")
        year_df = df_filt.copy()
        year_df["StartYear"] = pd.to_numeric(year_df["StartYear"], errors="coerce")
        year_df = year_df.dropna(subset=["StartYear"])
        year_df["StartYear"] = year_df["StartYear"].astype(int)
        counts_year = (
            year_df.groupby(["StartYear", "Branch"], as_index=False)
            .size()
            .rename(columns={"size": "Count"})
        )
        if not counts_year.empty:
            fig_year = px.area(
                counts_year,
                x="StartYear",
                y="Count",
                color="Branch",
                height=360,
                template="plotly_dark",
                color_discrete_map=BRANCH_COLORS,
            )
            fig_year.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=10, r=10, t=10, b=10),
                font=dict(color=THEME["text"]),
                xaxis_title=None,
                yaxis_title=None,
                legend_title=None,
            )
            fig_year.update_xaxes(color=THEME["muted"], tickmode="linear", dtick=1, tickformat="d")
            fig_year.update_yaxes(gridcolor=THEME["grid"], color=THEME["muted"])
            st.plotly_chart(fig_year, use_container_width=True)
        else:
            st.info("No trials with a valid start year for the current filter selection.")
        st.markdown("</div>", unsafe_allow_html=True)

with tab_geo:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("Global studies by country")

    countries_long = split_pipe_values(df_filt["Countries"])
    if countries_long:
        country_df = pd.DataFrame({"Country": countries_long})
        country_counts = (
            country_df["Country"]
            .value_counts()
            .rename_axis("Country")
            .reset_index(name="Count")
        )

        fig_world = px.choropleth(
            country_counts,
            locations="Country",
            locationmode="country names",
            color="Count",
            color_continuous_scale=[
                [0.00, "#1d4e89"],
                [0.20, "#4f86c6"],
                [0.40, "#a8c6ea"],
                [0.58, "#f3d37a"],
                [0.78, "#e67e22"],
                [1.00, "#b22222"],
            ],
            projection="natural earth",
            template="plotly_dark",
        )
        fig_world.update_layout(
            margin=dict(l=0, r=0, t=10, b=0),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color=THEME["text"]),
            geo=dict(
                bgcolor="rgba(0,0,0,0)",
                lakecolor="rgba(0,0,0,0)",
                landcolor="#17202a",
                showframe=False,
                showcoastlines=False,
                showcountries=True,
                countrycolor="rgba(255,255,255,0.12)",
            ),
            coloraxis_colorbar_title="Trials",
        )
        st.plotly_chart(fig_world, use_container_width=True)

        c1, c2 = st.columns([1.15, 0.85])
        with c1:
            st.markdown("**Country counts**")
            st.dataframe(country_counts, use_container_width=True, height=320, hide_index=True)
        with c2:
            st.markdown("**Top countries**")
            st.plotly_chart(
                make_bar(country_counts.head(12), "Country", "Count", height=320, color="#21b3a3"),
                use_container_width=True,
            )
    else:
        st.info("No country information available for the current filter selection.")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("Germany by city")

    if germany_open_sites.empty:
        st.info("No open or recruiting German study sites found in the current result set.")
    else:
        germany_city_counts = (
            germany_open_sites["City"]
            .fillna("Unknown")
            .value_counts()
            .rename_axis("City")
            .reset_index(name="OpenSiteCount")
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
                make_bar(germany_city_counts, "City", "OpenSiteCount", height=380, color="#d38a5a"),
                use_container_width=True,
            )
        with c2:
            st.markdown("**Germany city table**")
            city_event = st.dataframe(
                germany_city_counts,
                use_container_width=True,
                height=380,
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                key="germany_city_table",
            )

        if city_event and city_event.selection.rows:
            selected_idx = city_event.selection.rows[0]
            selected_city = germany_city_counts.iloc[selected_idx]["City"]

            st.markdown(f"### Trials with open German sites in {selected_city}")

            city_nct_ids = (
                germany_open_sites.loc[
                    germany_open_sites["City"].fillna("Unknown") == selected_city,
                    "NCTId",
                ]
                .dropna()
                .unique()
            )

            city_trial_view = germany_study_view[
                germany_study_view["NCTId"].isin(city_nct_ids)
            ].copy()

            city_trial_view = city_trial_view.sort_values(
                ["PhaseOrdered", "DiseaseCategory", "NCTId"],
                ascending=[True, True, True],
                na_position="last",
            )

            if city_trial_view.empty:
                st.info(f"No study rows found for {selected_city}.")
            else:
                st.dataframe(
                    city_trial_view[
                        [
                            "NCTId",
                            "NCTLink",
                            "BriefTitle",
                            "Branch",
                            "DiseaseCategory",
                            "DiseaseEntity",
                            "TargetCategory",
                            "ProductType",
                            "Phase",
                            "OverallStatus",
                            "LeadSponsor",
                            "GermanCities",
                            "GermanSiteStatuses",
                        ]
                    ],
                    use_container_width=True,
                    height=320,
                    hide_index=True,
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
    st.markdown("</div>", unsafe_allow_html=True)

with tab_data:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("Trial table")

    show_cols = [
        "NCTId",
        "NCTLink",
        "BriefTitle",
        "Branch",
        "DiseaseCategory",
        "DiseaseEntity",
        "TargetCategory",
        "ProductType",
        "Phase",
        "OverallStatus",
        "StartYear",
        "Countries",
        "LeadSponsor",
    ]

    table_df = df_filt.sort_values(
        ["PhaseOrdered", "Branch", "DiseaseCategory", "NCTId"],
        ascending=[True, True, True, True],
    ).copy()
    table_df["Phase"] = table_df["PhaseLabel"]

    st.dataframe(
        table_df[show_cols],
        use_container_width=True,
        height=460,
        hide_index=True,
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
            "StartYear": st.column_config.NumberColumn("Start year", format="%d"),
            "Countries": st.column_config.TextColumn("Countries", width="large"),
            "LeadSponsor": st.column_config.TextColumn("Lead sponsor", width="medium"),
        },
    )
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("Studies active in Germany")

    if germany_study_view.empty:
        st.info("No open or recruiting German study sites found in the current result set.")
    else:
        germany_export_view = germany_study_view.copy()
        germany_export_view = germany_export_view.sort_values(
            ["PhaseOrdered", "DiseaseCategory", "NCTId"], na_position="last"
        )
        st.dataframe(
            germany_export_view[
                [
                    "NCTId",
                    "NCTLink",
                    "BriefTitle",
                    "Branch",
                    "DiseaseCategory",
                    "DiseaseEntity",
                    "TargetCategory",
                    "ProductType",
                    "Phase",
                    "OverallStatus",
                    "LeadSponsor",
                    "GermanCities",
                    "GermanSiteStatuses",
                ]
            ],
            use_container_width=True,
            height=380,
            hide_index=True,
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
    st.markdown("</div>", unsafe_allow_html=True)

    # Unclassified trial helper text
    unclassified_mask = (
        df_filt["Branch"].astype(str).str.lower().isin(["unknown"])
        | df_filt["DiseaseEntity"].astype(str).str.lower().isin([UNCLASSIFIED_LABEL.lower()])
        | df_filt["TargetCategory"].astype(str).str.lower().isin(["other_or_unknown", "unclassified", "unknown"])
    )
    df_unclassified = df_filt[unclassified_mask].copy()

    unclassified_text = ""
    if not df_unclassified.empty:
        lines = []
        lines.append(
            "INSTRUCTION / COMMAND: Based on the following clinical trials, generate a supplementary curation "
            "checklist to improve Branch / DiseaseCategory / DiseaseEntity / TargetCategory classification. "
            "For each trial, propose refined labels and a short justification that can be integrated back "
            "into the ETL pipeline."
        )
        lines.append(
            "Output format (CSV columns): "
            "NCTId, ExistingBranch, ExistingDiseaseCategory, ExistingDiseaseEntity, ExistingTargetCategory, "
            "ProposedBranch, ProposedDiseaseCategory, ProposedDiseaseEntity, ProposedTargetCategory, Rationale"
        )
        lines.append("")
        lines.append(
            "Trial rows (NCTId | Branch | Category | Entity | Target | BriefTitle):"
        )
        for _, row in df_unclassified.iterrows():
            lines.append(
                f"- {row.get('NCTId', '')} | "
                f"{row.get('Branch', '')} | "
                f"{row.get('DiseaseCategory', '')} | "
                f"{row.get('DiseaseEntity', '')} | "
                f"{row.get('TargetCategory', '')} | "
                f"{row.get('BriefTitle', '')}"
            )
        unclassified_text = "\n".join(lines)

    d1, d2, d3 = st.columns(3)
    with d1:
        st.download_button(
            label="Download filtered trial data as CSV",
            data=df_filt.to_csv(index=False),
            file_name="car_t_oncology_trials_filtered.csv",
            mime="text/csv",
        )
    with d2:
        if not df_sites.empty:
            st.download_button(
                label="Download site-level data as CSV",
                data=df_sites.to_csv(index=False),
                file_name="car_t_oncology_sites.csv",
                mime="text/csv",
            )
    with d3:
        st.download_button(
            label="Unclassified trials prompt (.txt)",
            data=unclassified_text if unclassified_text else "No unclassified trials in current filter.",
            file_name="unclassified_trials_prompt.txt",
            mime="text/plain",
            disabled=df_unclassified.empty,
        )
