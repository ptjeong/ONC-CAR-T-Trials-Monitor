"""ETL pipeline for the Oncology CAR-T Trials Monitor.

Fetches studies from ClinicalTrials.gov v2, flattens them, and classifies
each into:
  • Branch          — Heme-onc / Solid-onc / Mixed / Unknown
  • DiseaseCategory — Tier-2 category (e.g. B-NHL, Multiple myeloma, CNS, GI)
  • DiseaseEntity   — Tier-3 leaf (e.g. DLBCL, R/R MM, GBM, HCC)
  • TargetCategory  — antigen label (CD19, BCMA, GPC3, CLDN18.2, dual combos)
  • ProductType     — Autologous / Allogeneic / In vivo / Unclear
Plus PRISMA-style flow accounting, snapshot I/O, and LLM-override support.
"""

import json
import os
import re
import requests
import pandas as pd
from datetime import datetime

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
    CAR_GD_T_TERMS,
    ALLOGENEIC_MARKERS,
    AUTOL_MARKERS,
    IN_VIVO_TERMS,
    HEME_TARGET_TERMS,
    SOLID_TARGET_TERMS,
    DUAL_TARGET_LABELS,
    NAMED_PRODUCT_TARGETS,
    NAMED_PRODUCT_TYPES,
)

BASE_URL = "https://clinicaltrials.gov/api/v2/studies"

# ---------------------------------------------------------------------------
# LLM override cache  (populated by:  python validate.py)
# ---------------------------------------------------------------------------

_OVERRIDES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "llm_overrides.json")
_LLM_OVERRIDES: dict[str, dict] = {}
_LLM_EXCLUDED_NCT_IDS: set[str] = set()


def _load_overrides() -> None:
    """Populate two caches from llm_overrides.json:
      _LLM_OVERRIDES        — per-trial classification overrides the pipeline applies.
      _LLM_EXCLUDED_NCT_IDS — trials the LLM flagged for exclusion (off-scope).
    Only high/medium confidence entries are honoured.
    """
    global _LLM_OVERRIDES, _LLM_EXCLUDED_NCT_IDS
    if not os.path.exists(_OVERRIDES_PATH):
        _LLM_OVERRIDES = {}
        _LLM_EXCLUDED_NCT_IDS = set()
        return
    try:
        with open(_OVERRIDES_PATH) as f:
            entries = json.load(f)
    except (json.JSONDecodeError, OSError):
        _LLM_OVERRIDES = {}
        _LLM_EXCLUDED_NCT_IDS = set()
        return

    def _is_exclude(e: dict) -> bool:
        return bool(e.get("exclude")) or e.get("disease_entity") == "Exclude"

    _LLM_OVERRIDES = {
        e["nct_id"]: e
        for e in entries
        if e.get("confidence") in ("high", "medium")
        and not _is_exclude(e)
        and e.get("disease_entity") not in (None,)
        and e.get("nct_id")
    }
    _LLM_EXCLUDED_NCT_IDS = {
        e["nct_id"]
        for e in entries
        if e.get("confidence") in ("high", "medium")
        and _is_exclude(e)
        and e.get("nct_id")
    }


def reload_overrides() -> int:
    """Reload LLM overrides from disk. Returns number of active overrides."""
    _load_overrides()
    return len(_LLM_OVERRIDES)


_load_overrides()


# ---------------------------------------------------------------------------
# Text normalization
# ---------------------------------------------------------------------------

def _safe_text(value) -> str:
    if pd.isna(value):
        return ""
    return str(value)


def _normalize_text(text: str) -> str:
    text = (text or "").lower()
    text = text.replace("sjögren", "sjogren")
    text = text.replace("r/r", "relapsed refractory")
    text = re.sub(r"[^a-z0-9/+.\- ]+", " ", text)
    # Treat hyphens as word separators: "b-cell" → "b cell",
    # "chromosome-positive" → "chromosome positive", "car-t" → "car t".
    text = text.replace("-", " ")
    text = re.sub(r"\s+", " ", text).strip()
    # Collapse "non hodgkin" into a single token so "hodgkin lymphoma" terms
    # do NOT match B-NHL text by accident. After this pass, "b cell non
    # hodgkin lymphoma" becomes "b cell nonhodgkin lymphoma", which lets the
    # word-boundary lookbehind in _term_in_text correctly reject the match.
    text = re.sub(r"\bnon\s+hodgkin\b", "nonhodgkin", text)
    return text


def _row_text(row: dict) -> str:
    return _normalize_text(
        " | ".join(
            [
                _safe_text(row.get("Conditions")),
                _safe_text(row.get("BriefTitle")),
                _safe_text(row.get("BriefSummary")),
                _safe_text(row.get("Interventions")),
            ]
        )
    )


def _contains_any(text: str | None, terms: list[str]) -> bool:
    if not text:
        return False
    normalized = _normalize_text(text)
    return any(_term_in_text(normalized, term) for term in terms)


def _term_in_text(normalized_text: str, term: str) -> bool:
    normalized_term = _normalize_text(term)
    if not normalized_term:
        return False
    # Word-boundary match for ALL term lengths — prevents false positives like:
    #   • "hodgkin lymphoma" matching inside "nonhodgkin lymphoma"
    #   • "egfr" matching inside "egfrviii"
    #   • "cd19" matching inside "cd190"
    return bool(
        re.search(
            rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])",
            normalized_text,
        )
    )


def _match_terms(text: str, term_map: dict[str, list[str]]) -> list[str]:
    matches = []
    for label, terms in term_map.items():
        if any(_term_in_text(text, term) for term in terms):
            matches.append(label)
    return matches


def _lookup_named_product(text: str, product_dict: dict[str, list[str]]) -> str | None:
    """Return the first category whose product name appears in normalized text."""
    for category, names in product_dict.items():
        if any(_normalize_text(name) in text for name in names):
            return category
    return None


# ---------------------------------------------------------------------------
# Tri-level disease classifier
# ---------------------------------------------------------------------------

def _classify_disease(row: dict) -> dict:
    """Return {'branch', 'category', 'entity', 'entities', 'design'}."""
    nct = _safe_text(row.get("NCTId")).strip()
    if nct and nct in _LLM_OVERRIDES:
        ov = _LLM_OVERRIDES[nct]
        entity = ov.get("disease_entity") or UNCLASSIFIED_LABEL
        category = ov.get("disease_category")
        if not category:
            category = ENTITY_TO_CATEGORY.get(entity, entity)
        branch = ov.get("branch")
        if not branch:
            branch = CATEGORY_TO_BRANCH.get(category, "Unknown")
        design = "Basket/Multidisease" if entity == BASKET_MULTI_LABEL else "Single disease"
        return {
            "branch": branch, "category": category, "entity": entity,
            "entities": entity, "design": design,
        }

    conditions_raw = _safe_text(row.get("Conditions"))
    full_text = _row_text(row)
    condition_chunks = [
        _normalize_text(c) for c in conditions_raw.split("|") if _normalize_text(c)
    ]

    # 1. Leaf-level term matching on conditions and full text.
    cond_matches: list[str] = []
    for chunk in condition_chunks:
        cond_matches.extend(_match_terms(chunk, ENTITY_TERMS))
    cond_matches = sorted(set(cond_matches))
    full_matches = sorted(set(_match_terms(full_text, ENTITY_TERMS)))
    all_entities = sorted(set(cond_matches + full_matches))

    if all_entities:
        categories = sorted({ENTITY_TO_CATEGORY[e] for e in all_entities})
        branches = sorted({CATEGORY_TO_BRANCH[c] for c in categories})
        branch = branches[0] if len(branches) == 1 else "Mixed"

        primary_entity = cond_matches[0] if cond_matches else all_entities[0]
        primary_category = ENTITY_TO_CATEGORY[primary_entity]

        # Multi-category within one branch → Basket/Multidisease.
        if len(categories) >= 2:
            return {
                "branch": branch,
                "category": BASKET_MULTI_LABEL,
                "entity": BASKET_MULTI_LABEL,
                "entities": "|".join(all_entities),
                "design": "Basket/Multidisease",
            }
        # Same category, multiple entities — keep primary, flag as basket design.
        design = "Basket/Multidisease" if len(all_entities) >= 2 else "Single disease"
        return {
            "branch": branch,
            "category": primary_category,
            "entity": primary_entity,
            "entities": "|".join(all_entities),
            "design": design,
        }

    # 2. No leaf match — category-level fallback.
    cat_matches = _match_terms(full_text, CATEGORY_FALLBACK_TERMS)
    if cat_matches:
        categories = sorted(set(cat_matches))
        branches = sorted({CATEGORY_TO_BRANCH[c] for c in categories})
        branch = branches[0] if len(branches) == 1 else "Mixed"
        if len(categories) >= 2:
            return {
                "branch": branch,
                "category": BASKET_MULTI_LABEL,
                "entity": BASKET_MULTI_LABEL,
                "entities": "",
                "design": "Basket/Multidisease",
            }
        primary_category = categories[0]
        return {
            "branch": branch,
            "category": primary_category,
            "entity": primary_category,
            "entities": "",
            "design": "Single disease",
        }

    # 3. Branch-level basket fallbacks.
    if _contains_any(full_text, SOLID_BASKET_TERMS):
        return {
            "branch": "Solid-onc",
            "category": SOLID_BASKET_LABEL,
            "entity": SOLID_BASKET_LABEL,
            "entities": "",
            "design": "Basket/Multidisease",
        }
    if _contains_any(full_text, HEME_BASKET_TERMS):
        return {
            "branch": "Heme-onc",
            "category": HEME_BASKET_LABEL,
            "entity": HEME_BASKET_LABEL,
            "entities": "",
            "design": "Basket/Multidisease",
        }

    return {
        "branch": "Unknown",
        "category": UNCLASSIFIED_LABEL,
        "entity": UNCLASSIFIED_LABEL,
        "entities": "",
        "design": "Single disease",
    }


# ---------------------------------------------------------------------------
# Exclusion (autoimmune-only indications)
# ---------------------------------------------------------------------------

def _is_hard_excluded(nct_id: str) -> bool:
    nct = nct_id.strip()
    return nct in HARD_EXCLUDED_NCT_IDS or nct in _LLM_EXCLUDED_NCT_IDS


def _is_indication_excluded(row: dict) -> bool:
    """Exclude trials whose only indication is autoimmune / rheumatologic.
    A trial with an onco hit (entity, category, branch basket, or onco target)
    is NOT excluded even if the text also mentions an autoimmune term.
    """
    text = _row_text(row)
    if not _contains_any(text, EXCLUDED_INDICATION_TERMS):
        return False
    has_entity = any(
        any(_term_in_text(text, t) for t in terms) for terms in ENTITY_TERMS.values()
    )
    if has_entity:
        return False
    has_category = any(
        any(_term_in_text(text, t) for t in terms) for terms in CATEGORY_FALLBACK_TERMS.values()
    )
    if has_category:
        return False
    if _contains_any(text, HEME_BASKET_TERMS) or _contains_any(text, SOLID_BASKET_TERMS):
        return False
    return True


def _exclude_by_indication(row: dict) -> bool:
    if _is_hard_excluded(_safe_text(row.get("NCTId"))):
        return True
    return _is_indication_excluded(row)


# ---------------------------------------------------------------------------
# Target and product classification
# ---------------------------------------------------------------------------

def _detect_targets(text: str) -> list[str]:
    matches: list[str] = []
    for label, terms in HEME_TARGET_TERMS.items():
        if any(_term_in_text(text, t) for t in terms):
            matches.append(label)
    for label, terms in SOLID_TARGET_TERMS.items():
        if any(_term_in_text(text, t) for t in terms):
            matches.append(label)
    # Prefix collisions like EGFR / EGFRvIII are now handled by the word-boundary
    # match in _term_in_text. No post-filter needed.
    return matches


def _assign_target(row: dict) -> str:
    nct = _safe_text(row.get("NCTId")).strip()
    if nct in _LLM_OVERRIDES:
        t = _LLM_OVERRIDES[nct].get("target_category")
        if t:
            return t

    text = _row_text(row)

    # Named-product short-circuit.
    named = _lookup_named_product(text, NAMED_PRODUCT_TARGETS)
    if named:
        return named

    # Platform detection.
    has_car_nk = _contains_any(text, CAR_NK_TERMS)
    has_caar_t = _contains_any(text, CAAR_T_TERMS)
    has_car_treg = _contains_any(text, CAR_TREG_TERMS) or ("treg" in text and "car" in text)
    has_car_gd = _contains_any(text, CAR_GD_T_TERMS)

    targets_found = _detect_targets(text)
    targets_set = set(targets_found)

    # Dual-target combos.
    for (a, b), label in DUAL_TARGET_LABELS:
        if a in targets_set and b in targets_set:
            if has_car_nk:
                return f"CAR-NK: {label}"
            return label

    # Platform with no antigen.
    if has_car_nk and not targets_found:
        return "CAR-NK"
    if has_caar_t and not targets_found:
        return "CAAR-T"
    if has_car_treg and not targets_found:
        return "CAR-Treg"
    if has_car_gd and not targets_found:
        return "CAR-γδ T"

    if len(targets_found) == 1:
        label = targets_found[0]
        if has_car_nk:
            return f"CAR-NK: {label}"
        return label
    if targets_found:
        if has_car_nk:
            return f"CAR-NK: {targets_found[0]}"
        return targets_found[0]

    if _contains_any(text, CAR_CORE_TERMS):
        return "CAR-T_unspecified"
    return "Other_or_unknown"


def _assign_product_type(row: dict) -> tuple[str, str]:
    """Return (product_type, confidence_source).

    confidence_source is a short tag indicating *why* this label was chosen,
    later aggregated into a user-facing ClassificationConfidence column:
      "llm_override"      → LLM-validated, treat as high confidence
      "explicit_*"        → explicit keyword/named product, high confidence
      "named_product"     → known product lookup, high confidence
      "weak_*"            → loose keyword, medium confidence
      "default_autologous_no_allo_markers" → default rule, medium confidence
      "no_signal"         → truly unclear, Unclear label, low confidence
    """
    nct = _safe_text(row.get("NCTId")).strip()
    if nct in _LLM_OVERRIDES:
        p = _LLM_OVERRIDES[nct].get("product_type")
        if p:
            return p, "llm_override"

    text = _row_text(row)
    title = _normalize_text(_safe_text(row.get("BriefTitle")))

    # In vivo — title is strongest signal.
    if "in vivo" in title:
        return "In vivo", "explicit_in_vivo_title"
    if any(term in text for term in IN_VIVO_TERMS):
        return "In vivo", "explicit_in_vivo_text"

    named = _lookup_named_product(text, NAMED_PRODUCT_TYPES)
    if named == "In vivo":
        return "In vivo", "named_product"

    if "autoleucel" in text or "autologous" in text:
        return "Autologous", "explicit_autologous"

    strong_allo_terms = [
        "ucart", "ucar",
        "universal car t", "universal car-t",
        "universal cd19", "universal bcma",
        "u car t", "u car-t",
        "off the shelf", "allogeneic",
        "healthy donor", "donor derived", "donor sourced",
    ]
    if any(term in text for term in strong_allo_terms):
        return "Allogeneic/Off-the-shelf", "explicit_allogeneic"

    if named == "Allogeneic/Off-the-shelf":
        return "Allogeneic/Off-the-shelf", "named_product"
    if named == "Autologous":
        return "Autologous", "named_product"

    if _contains_any(text, ALLOGENEIC_MARKERS):
        return "Allogeneic/Off-the-shelf", "weak_allogeneic_marker"
    if _contains_any(text, AUTOL_MARKERS):
        return "Autologous", "weak_autologous_marker"

    # Smart default: if the trial is confirmed as CAR-T but no product-type
    # markers surfaced, default to Autologous. Rationale: autologous is the
    # dominant modality in the current CAR-T landscape (~85% of approvals
    # and active trials). Mark as medium-confidence so users see it flagged.
    if _contains_any(text, CAR_CORE_TERMS):
        return "Autologous", "default_autologous_no_allo_markers"

    return "Unclear", "no_signal"


# ---------------------------------------------------------------------------
# ClinicalTrials.gov fetch
# ---------------------------------------------------------------------------

def fetch_raw_trials(max_records: int = 5000, statuses: list[str] | None = None) -> list[dict]:
    """Pull all CAR-based cell-therapy trials from ClinicalTrials.gov v2.

    Intentionally broad: no condition-search restriction. Downstream handling —
    the tri-level classifier assigns Branch/Category/Entity, and
    _exclude_by_indication drops trials whose only indication is autoimmune /
    rheumatologic. This is more robust than trying to enumerate every onco
    condition term ClinicalTrials.gov might use (generic labels like "Neoplasms"
    or "Hematological Malignancies" were being missed before).
    """
    term_query = (
        '"CAR T" OR "CAR-T" OR "chimeric antigen receptor" '
        'OR "CAR-NK" OR "CAR NK" OR "CAAR-T" OR "CAR-Treg" '
        'OR "gamma delta CAR" OR "CAR gamma delta"'
    )

    params = {"query.term": term_query, "pageSize": 200, "countTotal": "true"}
    if statuses:
        params["filter.overallStatus"] = ",".join(statuses)

    studies: list[dict] = []
    while True:
        resp = requests.get(BASE_URL, params=params, timeout=30)
        if resp.status_code != 200:
            raise requests.HTTPError(
                f"ClinicalTrials.gov API error {resp.status_code}: {resp.text}"
            )
        data = resp.json()
        studies.extend(data.get("studies", []))
        if len(studies) >= max_records:
            break
        token = data.get("nextPageToken")
        if not token:
            break
        params["pageToken"] = token
    return studies[:max_records]


def _flatten_study(study: dict) -> dict:
    ps = study.get("protocolSection", {})
    ident = ps.get("identificationModule", {})
    status = ps.get("statusModule", {})
    cond = ps.get("conditionsModule", {})
    design = ps.get("designModule", {})
    desc = ps.get("descriptionModule", {})
    loc_mod = ps.get("contactsLocationsModule", {})
    arms_mod = ps.get("armsInterventionsModule", {})
    sponsor_mod = ps.get("sponsorCollaboratorsModule", {})

    phase_list = design.get("phases") or []
    phase = (
        "|".join(str(p) for p in phase_list if p)
        if phase_list
        else (design.get("phase") or "Unknown")
    )

    interventions = []
    for inter in (arms_mod.get("interventions") or []):
        label = inter.get("name") or inter.get("description")
        if label:
            interventions.append(label)

    countries = sorted(
        {loc.get("country") for loc in (loc_mod.get("locations") or []) if loc.get("country")}
    )

    return {
        "NCTId": ident.get("nctId"),
        "BriefTitle": ident.get("briefTitle"),
        "OverallStatus": status.get("overallStatus"),
        "Phase": phase,
        "Conditions": "|".join(cond.get("conditions") or []) or None,
        "Interventions": "|".join(sorted(set(interventions))) or None,
        "StartDate": (status.get("startDateStruct") or {}).get("date"),
        "LastUpdatePostDate": (status.get("lastUpdatePostDateStruct") or {}).get("date"),
        "EnrollmentCount": (design.get("enrollmentInfo") or {}).get("count"),
        "Countries": "|".join(countries) or None,
        "BriefSummary": desc.get("briefSummary"),
        "LeadSponsor": (sponsor_mod.get("leadSponsor") or {}).get("name"),
    }


def _extract_sites(study: dict) -> list[dict]:
    ps = study.get("protocolSection", {})
    ident = ps.get("identificationModule", {})
    status = ps.get("statusModule", {})
    loc_mod = ps.get("contactsLocationsModule", {})

    sites = []
    for loc in (loc_mod.get("locations") or []):
        sites.append(
            {
                "NCTId": ident.get("nctId"),
                "BriefTitle": ident.get("briefTitle"),
                "OverallStatus": status.get("overallStatus"),
                "Facility": loc.get("facility"),
                "City": loc.get("city"),
                "State": loc.get("state"),
                "Zip": loc.get("zip"),
                "Country": loc.get("country"),
                "SiteStatus": loc.get("status"),
            }
        )
    return sites


# ---------------------------------------------------------------------------
# PRISMA-returning builder
# ---------------------------------------------------------------------------

def _process_trials_from_studies(studies: list[dict]) -> tuple[pd.DataFrame, dict]:
    """Classify studies, apply exclusions, and return (df, prisma_counts)."""
    df = pd.DataFrame([_flatten_study(s) for s in studies])

    n_fetched = len(df)
    df = df.dropna(subset=["NCTId"]).drop_duplicates(subset=["NCTId"])
    n_after_dedup = len(df)
    n_duplicates = n_fetched - n_after_dedup

    classification = df.apply(lambda r: _classify_disease(r.to_dict()), axis=1)
    df["Branch"] = classification.apply(lambda d: d["branch"])
    df["DiseaseCategory"] = classification.apply(lambda d: d["category"])
    df["DiseaseEntity"] = classification.apply(lambda d: d["entity"])
    df["DiseaseEntities"] = classification.apply(lambda d: d["entities"])
    df["TrialDesign"] = classification.apply(lambda d: d["design"])
    df["LLMOverride"] = df["NCTId"].isin(_LLM_OVERRIDES)

    hard_mask = df["NCTId"].apply(_is_hard_excluded)
    n_hard_excluded = int(hard_mask.sum())

    df_after_hard = df[~hard_mask].copy()
    indication_mask = df_after_hard.apply(lambda r: _is_indication_excluded(r.to_dict()), axis=1)
    n_indication_excluded = int(indication_mask.sum())

    df = df_after_hard[~indication_mask].copy()
    n_included = len(df)

    df["TargetCategory"] = df.apply(lambda r: _assign_target(r.to_dict()), axis=1)
    product_results = df.apply(lambda r: _assign_product_type(r.to_dict()), axis=1)
    df["ProductType"] = product_results.apply(lambda t: t[0])
    df["ProductTypeSource"] = product_results.apply(lambda t: t[1])

    # Per-trial ClassificationConfidence — summarises the strength of signal
    # behind each row's Branch/Category/Entity/Target/Product labels. Surfaced
    # in the Data tab and data-quality expander so users know which rows to
    # trust at face value vs investigate.
    def _confidence(row) -> str:
        if row["LLMOverride"]:
            return "high"
        if row["Branch"] == "Unknown" or row["DiseaseEntity"] == UNCLASSIFIED_LABEL:
            return "low"
        unclear_target = row["TargetCategory"] in ("CAR-T_unspecified", "Other_or_unknown")
        default_product = row["ProductTypeSource"] in (
            "default_autologous_no_allo_markers",
            "weak_autologous_marker",
            "weak_allogeneic_marker",
        )
        if unclear_target and default_product:
            return "low"
        if unclear_target or default_product:
            return "medium"
        return "high"

    df["ClassificationConfidence"] = df.apply(_confidence, axis=1)

    df["StartDate"] = pd.to_datetime(df["StartDate"], errors="coerce")
    df["StartYear"] = df["StartDate"].dt.year
    df["LastUpdatePostDate"] = pd.to_datetime(df["LastUpdatePostDate"], errors="coerce")
    df["EnrollmentCount"] = pd.to_numeric(df["EnrollmentCount"], errors="coerce")
    df["SnapshotDate"] = datetime.utcnow().date().isoformat()

    prisma = {
        "n_fetched": n_fetched,
        "n_duplicates_removed": n_duplicates,
        "n_after_dedup": n_after_dedup,
        "n_hard_excluded": n_hard_excluded,
        "n_indication_excluded": n_indication_excluded,
        "n_total_excluded": n_hard_excluded + n_indication_excluded,
        "n_included": n_included,
    }

    return df.reset_index(drop=True), prisma


def _sites_from_studies(studies: list[dict]) -> pd.DataFrame:
    site_rows: list[dict] = []
    for s in studies:
        site_rows.extend(_extract_sites(s))
    df_sites = pd.DataFrame(site_rows)
    if df_sites.empty:
        return df_sites
    return df_sites.dropna(subset=["NCTId"]).drop_duplicates().reset_index(drop=True)


def build_all_from_api(
    max_records: int = 5000, statuses: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Fetch from live API and return (df_trials, df_sites, prisma_counts)."""
    studies = fetch_raw_trials(max_records=max_records, statuses=statuses)
    df, prisma = _process_trials_from_studies(studies)
    df_sites = _sites_from_studies(studies)
    return df, df_sites, prisma


# ---------------------------------------------------------------------------
# Backward-compatible wrappers
# ---------------------------------------------------------------------------

def build_clean_dataframe(max_records: int = 5000, statuses: list[str] | None = None) -> pd.DataFrame:
    df, _ = _process_trials_from_studies(fetch_raw_trials(max_records=max_records, statuses=statuses))
    return df


def build_sites_dataframe(max_records: int = 5000, statuses: list[str] | None = None) -> pd.DataFrame:
    return _sites_from_studies(fetch_raw_trials(max_records=max_records, statuses=statuses))


# ---------------------------------------------------------------------------
# Snapshot I/O
# ---------------------------------------------------------------------------

def save_snapshot(
    df: pd.DataFrame,
    df_sites: pd.DataFrame,
    prisma: dict,
    snapshot_dir: str = "snapshots",
    statuses: list[str] | None = None,
) -> str:
    snapshot_date = datetime.utcnow().date().isoformat()
    out_dir = os.path.join(snapshot_dir, snapshot_date)
    os.makedirs(out_dir, exist_ok=True)

    df.to_csv(os.path.join(out_dir, "trials.csv"), index=False)
    df_sites.to_csv(os.path.join(out_dir, "sites.csv"), index=False)

    with open(os.path.join(out_dir, "prisma.json"), "w") as f:
        json.dump(prisma, f, indent=2)

    metadata = {
        "snapshot_date": snapshot_date,
        "created_utc": datetime.utcnow().isoformat(),
        "statuses_filter": statuses or [],
        "n_trials": len(df),
        "n_sites": len(df_sites),
        "api_base_url": BASE_URL,
    }
    with open(os.path.join(out_dir, "metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2)

    return snapshot_date


def load_snapshot(
    snapshot_date: str,
    snapshot_dir: str = "snapshots",
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    out_dir = os.path.join(snapshot_dir, snapshot_date)

    df = pd.read_csv(os.path.join(out_dir, "trials.csv"))
    df["StartDate"] = pd.to_datetime(df["StartDate"], errors="coerce")
    df["LastUpdatePostDate"] = pd.to_datetime(df["LastUpdatePostDate"], errors="coerce")
    for col, default in [
        ("Branch", "Unknown"),
        ("DiseaseCategory", UNCLASSIFIED_LABEL),
        ("DiseaseEntities", df.get("DiseaseEntity", "").fillna("") if "DiseaseEntity" in df.columns else ""),
        ("TrialDesign", "Single disease"),
    ]:
        if col not in df.columns:
            df[col] = default
    if "LLMOverride" not in df.columns:
        df["LLMOverride"] = df["NCTId"].isin(_LLM_OVERRIDES)

    sites_path = os.path.join(out_dir, "sites.csv")
    df_sites = pd.read_csv(sites_path) if os.path.exists(sites_path) else pd.DataFrame()

    prisma_path = os.path.join(out_dir, "prisma.json")
    if os.path.exists(prisma_path):
        with open(prisma_path) as f:
            prisma = json.load(f)
    else:
        prisma = {}

    return df, df_sites, prisma


def list_snapshots(snapshot_dir: str = "snapshots") -> list[str]:
    if not os.path.isdir(snapshot_dir):
        return []
    dates = [
        d for d in os.listdir(snapshot_dir)
        if os.path.isdir(os.path.join(snapshot_dir, d))
        and os.path.exists(os.path.join(snapshot_dir, d, "trials.csv"))
    ]
    return sorted(dates, reverse=True)
