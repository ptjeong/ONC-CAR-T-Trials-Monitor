"""ETL pipeline for the Oncology CAR-T Trials Monitor.

Fetches studies from ClinicalTrials.gov v2, flattens them, and classifies
each trial into a three-tier disease hierarchy (Branch → Category → Entity),
a target-antigen label, and a product-type label.
"""

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
    HEME_TARGET_TERMS,
    SOLID_TARGET_TERMS,
    DUAL_TARGET_LABELS,
    NAMED_PRODUCTS,
)

BASE_URL = "https://clinicaltrials.gov/api/v2/studies"


# ---------------------------------------------------------------------------
# Text normalization helpers (mirrors rheum patterns)
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
    # Treat hyphens as word separators so "b-cell", "cd19-directed",
    # "chromosome-positive", "non-hodgkin" etc. collapse to the
    # space-separated forms used in the term lists.
    text = text.replace("-", " ")
    text = re.sub(r"\s+", " ", text).strip()
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


def _term_in_text(normalized_text: str, term: str) -> bool:
    normalized_term = _normalize_text(term)
    if not normalized_term:
        return False
    if len(normalized_term) <= 3:
        return bool(
            re.search(
                rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])",
                normalized_text,
            )
        )
    return normalized_term in normalized_text


def _contains_any(text: str | None, terms: list[str]) -> bool:
    if not text:
        return False
    normalized = _normalize_text(text)
    return any(_term_in_text(normalized, term) for term in terms)


def _match_terms(text: str, term_map: dict[str, list[str]]) -> list[str]:
    matches = []
    for label, terms in term_map.items():
        if any(_term_in_text(text, term) for term in terms):
            matches.append(label)
    return matches


# ---------------------------------------------------------------------------
# Tri-level disease classifier
# ---------------------------------------------------------------------------

def _classify_disease(row: dict) -> dict:
    """Tri-level classifier.

    Returns a dict with keys: branch, category, entity, entities, design.
      branch         — 'Heme-onc' | 'Solid-onc' | 'Mixed' | 'Unknown'
      category       — Tier 2 label
      entity         — primary leaf label (for charts)
      entities       — pipe-joined list of matched leaves (for basket detection)
      design         — 'Single disease' | 'Basket/Multidisease'
    """
    conditions_raw = _safe_text(row.get("Conditions"))
    full_text = _row_text(row)
    condition_chunks = [
        _normalize_text(c) for c in conditions_raw.split("|") if _normalize_text(c)
    ]

    # 1. Leaf-level term matching — collect matches per condition chunk, then fold into a union.
    cond_matches: list[str] = []
    for chunk in condition_chunks:
        cond_matches.extend(_match_terms(chunk, ENTITY_TERMS))
    cond_matches = sorted(set(cond_matches))

    full_matches = sorted(set(_match_terms(full_text, ENTITY_TERMS)))
    all_entities = sorted(set(cond_matches + full_matches))

    # 2. If we have leaf matches — derive category and branch from them.
    if all_entities:
        categories = sorted({ENTITY_TO_CATEGORY[e] for e in all_entities})
        branches = sorted({CATEGORY_TO_BRANCH[c] for c in categories})

        branch = branches[0] if len(branches) == 1 else "Mixed"

        # Prefer a leaf that appeared in the Conditions field (stronger signal)
        if cond_matches:
            primary_entity = cond_matches[0]
        else:
            primary_entity = all_entities[0]
        primary_category = ENTITY_TO_CATEGORY[primary_entity]

        # Basket: 2+ entities, especially across categories
        if len(all_entities) >= 2:
            if len(categories) >= 2:
                return {
                    "branch": branch,
                    "category": BASKET_MULTI_LABEL,
                    "entity": BASKET_MULTI_LABEL,
                    "entities": "|".join(all_entities),
                    "design": "Basket/Multidisease",
                }

        return {
            "branch": branch,
            "category": primary_category,
            "entity": primary_entity,
            "entities": "|".join(all_entities),
            "design": "Single disease",
        }

    # 3. No leaf matches — try category-level fallback.
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

    # 4. No category match — try branch-level basket terms.
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

    # 5. Fall through.
    return {
        "branch": "Unknown",
        "category": UNCLASSIFIED_LABEL,
        "entity": UNCLASSIFIED_LABEL,
        "entities": "",
        "design": "Single disease",
    }


# ---------------------------------------------------------------------------
# Exclusion logic
# ---------------------------------------------------------------------------

def _exclude_by_indication(row: dict) -> bool:
    """Exclude trials whose *only* indication is autoimmune / rheumatologic.

    A trial is excluded if:
      - NCT ID is on the hard-excluded list, OR
      - The text contains an excluded indication term AND does not contain
        any oncology-adjacent hit (entity / category / branch basket / target).
    """
    nct_id = _safe_text(row.get("NCTId")).strip()
    if nct_id in HARD_EXCLUDED_NCT_IDS:
        return True

    text = _row_text(row)
    if not _contains_any(text, EXCLUDED_INDICATION_TERMS):
        return False

    # Hit on autoimmune term — only exclude if we did NOT find any onco hit.
    # Check: any entity, any category fallback, any branch basket, or a heme/solid target mention.
    has_entity = any(any(_term_in_text(text, t) for t in terms) for terms in ENTITY_TERMS.values())
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


# ---------------------------------------------------------------------------
# Target antigen classification
# ---------------------------------------------------------------------------

def _detect_targets(text: str) -> list[str]:
    """Return list of target labels found in normalized text (no dual-combining yet)."""
    matches: list[str] = []
    for label, terms in HEME_TARGET_TERMS.items():
        if any(_term_in_text(text, t) for t in terms):
            matches.append(label)
    for label, terms in SOLID_TARGET_TERMS.items():
        if any(_term_in_text(text, t) for t in terms):
            matches.append(label)

    # Resolve known prefix collisions — the more-specific target wins.
    if "EGFRvIII" in matches and "EGFR" in matches:
        matches.remove("EGFR")
    return matches


def _match_named_product(text: str) -> dict | None:
    for product_key, info in NAMED_PRODUCTS.items():
        if _term_in_text(text, product_key):
            return info
    return None


def _assign_target(row: dict) -> str:
    text = _row_text(row)

    # 1. Named-product short-circuit.
    prod = _match_named_product(text)
    if prod:
        return prod["target"]

    # 2. Platform detection — CAR-NK / CAAR-T / CAR-Treg / CAR-γδ T.
    has_car_nk = _contains_any(text, CAR_NK_TERMS)
    has_caar_t = _contains_any(text, CAAR_T_TERMS)
    has_car_treg = _contains_any(text, CAR_TREG_TERMS) or ("treg" in text and "car" in text)
    has_car_gd = _contains_any(text, CAR_GD_T_TERMS)

    # 3. Detect all antigens present.
    targets_found = _detect_targets(text)

    # 4. Dual-target combos (ordered by list — first match wins).
    targets_set = set(targets_found)
    for (a, b), label in DUAL_TARGET_LABELS:
        if a in targets_set and b in targets_set:
            if has_car_nk:
                return f"CAR-NK: {label}"
            return label

    # 5. Platforms with no clear antigen.
    if has_car_nk and not targets_found:
        return "CAR-NK"
    if has_caar_t and not targets_found:
        return "CAAR-T"
    if has_car_treg and not targets_found:
        return "CAR-Treg"
    if has_car_gd and not targets_found:
        return "CAR-γδ T"

    # 6. Single antigen.
    if len(targets_found) == 1:
        label = targets_found[0]
        if has_car_nk:
            return f"CAR-NK: {label}"
        return label

    # 7. Multiple antigens not in DUAL_TARGET_LABELS — return first.
    if targets_found:
        if has_car_nk:
            return f"CAR-NK: {targets_found[0]}"
        return targets_found[0]

    # 8. Generic CAR mention with no identified target.
    if _contains_any(text, CAR_CORE_TERMS):
        return "CAR-T_unspecified"

    return "Other_or_unknown"


def _assign_product_type(row: dict) -> str:
    text = _row_text(row)

    # Named-product short-circuit.
    prod = _match_named_product(text)
    if prod:
        return prod["type"]

    if "autoleucel" in text or "autologous" in text:
        return "Autologous"

    strong_allo_terms = [
        "ucart",
        "ucar",
        "universal car t",
        "off the shelf",
        "allogeneic",
        "healthy donor",
        "donor derived",
        "donor sourced",
    ]
    if any(term in text for term in strong_allo_terms):
        return "Allogeneic/Off-the-shelf"

    if _contains_any(text, ALLOGENEIC_MARKERS):
        return "Allogeneic/Off-the-shelf"
    if _contains_any(text, AUTOL_MARKERS):
        return "Autologous"

    return "Unclear"


# ---------------------------------------------------------------------------
# CT.gov fetch / flatten
# ---------------------------------------------------------------------------

def fetch_raw_trials(
    max_records: int = 5000, statuses: list[str] | None = None
) -> list[dict]:
    """Pull oncology CAR-T trials from ClinicalTrials.gov v2."""
    term_query = (
        '('
        ' "CAR T" OR "CAR-T" OR "chimeric antigen receptor" '
        ' OR "CAR-NK" OR "CAR NK" OR "CAAR-T" OR "CAR-Treg" '
        ' OR "gamma delta CAR" OR "CAR gamma delta" '
        ') AND AREA[ConditionSearch] ('
        ' leukemia OR lymphoma OR myeloma OR "multiple myeloma" '
        ' OR "solid tumor" OR "solid tumors" OR glioma OR glioblastoma '
        ' OR hepatocellular OR pancreatic OR gastric OR colorectal '
        ' OR ovarian OR breast OR prostate OR sarcoma OR melanoma '
        ' OR neuroblastoma OR mesothelioma OR carcinoma '
        ')'
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
# Public builders
# ---------------------------------------------------------------------------

def build_clean_dataframe(
    max_records: int = 5000, statuses: list[str] | None = None
) -> pd.DataFrame:
    """Fetch, flatten, classify, and filter oncology CAR-T trials."""
    studies = fetch_raw_trials(max_records=max_records, statuses=statuses)
    df = pd.DataFrame([_flatten_study(s) for s in studies])
    df = df.dropna(subset=["NCTId"]).drop_duplicates(subset=["NCTId"])

    classification = df.apply(lambda r: _classify_disease(r.to_dict()), axis=1)
    df["Branch"] = classification.apply(lambda d: d["branch"])
    df["DiseaseCategory"] = classification.apply(lambda d: d["category"])
    df["DiseaseEntity"] = classification.apply(lambda d: d["entity"])
    df["DiseaseEntities"] = classification.apply(lambda d: d["entities"])
    df["Design"] = classification.apply(lambda d: d["design"])

    mask_excl = df.apply(lambda r: _exclude_by_indication(r.to_dict()), axis=1)
    df = df[~mask_excl].copy()

    df["TargetCategory"] = df.apply(lambda r: _assign_target(r.to_dict()), axis=1)
    df["ProductType"] = df.apply(lambda r: _assign_product_type(r.to_dict()), axis=1)

    df["StartDate"] = pd.to_datetime(df["StartDate"], errors="coerce")
    df["StartYear"] = df["StartDate"].dt.year
    df["LastUpdatePostDate"] = pd.to_datetime(df["LastUpdatePostDate"], errors="coerce")
    df["SnapshotDate"] = datetime.utcnow().date().isoformat()

    return df.reset_index(drop=True)


def build_sites_dataframe(
    max_records: int = 5000, statuses: list[str] | None = None
) -> pd.DataFrame:
    studies = fetch_raw_trials(max_records=max_records, statuses=statuses)
    site_rows: list[dict] = []
    for s in studies:
        site_rows.extend(_extract_sites(s))
    df_sites = pd.DataFrame(site_rows)
    if df_sites.empty:
        return df_sites
    return df_sites.dropna(subset=["NCTId"]).drop_duplicates().reset_index(drop=True)
