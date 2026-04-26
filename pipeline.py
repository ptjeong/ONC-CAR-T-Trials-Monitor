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

def _normalize_disease_result(result: dict) -> dict:
    """Post-classification normalisation: catch logically-incoherent
    combinations regardless of upstream source (rule-based or LLM override).

    Rule: Branch=Unknown + Category=Basket/Multidisease is incoherent — a
    basket trial spans multiple categories by definition, which means we
    know enough about its scope to call it Mixed rather than Unknown.
    Surfaced by the independent-LLM run flagging Llama=Mixed for several
    LLM-overridden Unknown-basket trials (NCT05437328, NCT05438368, etc.).
    """
    if (result.get("branch") == "Unknown"
            and result.get("category") == BASKET_MULTI_LABEL):
        result["branch"] = "Mixed"
    return result


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
        return _normalize_disease_result({
            "branch": branch, "category": category, "entity": entity,
            "entities": entity, "design": design,
        })

    conditions_raw = _safe_text(row.get("Conditions"))
    full_text = _row_text(row)
    condition_chunks = [
        _normalize_text(c) for c in conditions_raw.split("|") if _normalize_text(c)
    ]

    # 1. Per-chunk leaf-level OR category-fallback matching.
    # ----------------------------------------------------
    # Each condition chunk gets BOTH passes — first ENTITY_TERMS for a
    # specific leaf match, and if that misses, CATEGORY_FALLBACK_TERMS for
    # a category-level signal. This catches basket trials where one chunk
    # lists a specific subtype ("Chronic Lymphocytic Leukemia" → CLL entity)
    # while another lists only the generic family ("Acute Lymphoblastic
    # Leukemia" → B-ALL category fallback). Surfaced by NCT05739227 which
    # had been mis-classified as CLL_SLL even though the conditions field
    # explicitly listed B-ALL + B-NHL + CLL.
    cond_entities: list[str] = []
    cond_categories: set[str] = set()
    for chunk in condition_chunks:
        ents = _match_terms(chunk, ENTITY_TERMS)
        if ents:
            cond_entities.extend(ents)
            cond_categories.update(ENTITY_TO_CATEGORY[e] for e in ents)
        else:
            cond_categories.update(_match_terms(chunk, CATEGORY_FALLBACK_TERMS))

    # Full-text scan still uses entity-only (avoids "lymphoma" anywhere
    # in a paragraph triggering B-NHL spuriously; the chunk-level fallback
    # already handles the legitimate cases).
    cond_matches = sorted(set(cond_entities))
    full_matches = sorted(set(_match_terms(full_text, ENTITY_TERMS)))
    all_entities = sorted(set(cond_matches + full_matches))
    cond_categories.update(ENTITY_TO_CATEGORY[e] for e in full_matches)

    if all_entities or cond_categories:
        categories = sorted(cond_categories) if cond_categories else \
            sorted({ENTITY_TO_CATEGORY[e] for e in all_entities})
        branches = sorted({CATEGORY_TO_BRANCH[c] for c in categories})
        branch = branches[0] if len(branches) == 1 else "Mixed"

        # Multi-category (entity-derived OR category-fallback-derived) → Basket.
        if len(categories) >= 2:
            return _normalize_disease_result({
                "branch": branch,
                "category": BASKET_MULTI_LABEL,
                "entity": BASKET_MULTI_LABEL,
                "entities": "|".join(all_entities),
                "design": "Basket/Multidisease",
            })
        # Single category — prefer the specific entity if we have one.
        primary_category = categories[0]
        if all_entities:
            primary_entity = cond_matches[0] if cond_matches else all_entities[0]
        else:
            primary_entity = primary_category  # category-fallback only
        design = "Basket/Multidisease" if len(all_entities) >= 2 else "Single disease"
        return _normalize_disease_result({
            "branch": branch,
            "category": primary_category,
            "entity": primary_entity,
            "entities": "|".join(all_entities),
            "design": design,
        })

    # 2. No leaf match — category-level fallback.
    cat_matches = _match_terms(full_text, CATEGORY_FALLBACK_TERMS)
    if cat_matches:
        categories = sorted(set(cat_matches))
        branches = sorted({CATEGORY_TO_BRANCH[c] for c in categories})
        branch = branches[0] if len(branches) == 1 else "Mixed"
        if len(categories) >= 2:
            return _normalize_disease_result({
                "branch": branch,
                "category": BASKET_MULTI_LABEL,
                "entity": BASKET_MULTI_LABEL,
                "entities": "",
                "design": "Basket/Multidisease",
            })
        primary_category = categories[0]
        return _normalize_disease_result({
            "branch": branch,
            "category": primary_category,
            "entity": primary_category,
            "entities": "",
            "design": "Single disease",
        })

    # 3. Branch-level basket fallbacks.
    if _contains_any(full_text, SOLID_BASKET_TERMS):
        return _normalize_disease_result({
            "branch": "Solid-onc",
            "category": SOLID_BASKET_LABEL,
            "entity": SOLID_BASKET_LABEL,
            "entities": "",
            "design": "Basket/Multidisease",
        })
    if _contains_any(full_text, HEME_BASKET_TERMS):
        return _normalize_disease_result({
            "branch": "Heme-onc",
            "category": HEME_BASKET_LABEL,
            "entity": HEME_BASKET_LABEL,
            "entities": "",
            "design": "Basket/Multidisease",
        })

    return _normalize_disease_result({
        "branch": "Unknown",
        "category": UNCLASSIFIED_LABEL,
        "entity": UNCLASSIFIED_LABEL,
        "entities": "",
        "design": "Single disease",
    })


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
        # Both "allogeneic" (US/EU) and "allogenic" (single-e variant common
        # in Chinese trial titles, e.g. NCT05739227 "Allogenic CD19-CAR-NK")
        # surface in CT.gov text. Missing the variant misclassifies the
        # trial as Autologous via the smart default.
        "off the shelf", "allogeneic", "allogenic",
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
# Derived-column helpers (product identity, age group, sponsor type)
# ---------------------------------------------------------------------------

def _extract_product_name(row: dict) -> str | None:
    """Return the canonical named product if the trial text contains one.

    Scans NAMED_PRODUCT_TARGETS in order — longest alias match wins, then
    the raw alias is translated to its canonical display name via
    CANONICAL_PRODUCT_NAME so aliases like "axicabtagene ciloleucel" /
    "yescarta" / "axi-cel" collapse to a single row in the per-product view.
    """
    from config import CANONICAL_PRODUCT_NAME  # local import to avoid cycle concerns
    text = _row_text(row)
    best = None
    for _target, products in NAMED_PRODUCT_TARGETS.items():
        for p in products:
            if _normalize_text(p) in text:
                if best is None or len(p) > len(best):
                    best = p
    if best is None:
        return None
    return CANONICAL_PRODUCT_NAME.get(best.lower(), best)


_AGE_YEAR_RE = re.compile(r"(\d+)\s*year", re.IGNORECASE)


def _age_to_years(age_str: str | None) -> float | None:
    """Parse CT.gov eligibility age strings like '18 Years', '6 Months' → years."""
    if not age_str or not isinstance(age_str, str):
        return None
    s = age_str.strip().lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*(year|month|week|day)", s)
    if not m:
        return None
    n = float(m.group(1))
    unit = m.group(2)
    if unit.startswith("year"):
        return n
    if unit.startswith("month"):
        return n / 12
    if unit.startswith("week"):
        return n / 52
    if unit.startswith("day"):
        return n / 365
    return None


def _age_group(row: dict) -> str:
    """Categorise a trial as Pediatric / Adult / Both / Unknown.

    Uses StdAges when present (CT.gov's authoritative enum: CHILD / ADULT /
    OLDER_ADULT), else derives from MinAge / MaxAge bounds.
    """
    std_ages = (row.get("StdAges") or "").upper().split("|")
    std_ages = {a.strip() for a in std_ages if a.strip()}
    has_child = "CHILD" in std_ages
    has_adult = "ADULT" in std_ages or "OLDER_ADULT" in std_ages
    if has_child and has_adult:
        return "Both"
    if has_child:
        return "Pediatric"
    if has_adult:
        return "Adult"

    # Fallback to age bounds
    min_yrs = _age_to_years(row.get("MinAge"))
    max_yrs = _age_to_years(row.get("MaxAge"))
    if min_yrs is None and max_yrs is None:
        return "Unknown"
    if max_yrs is not None and max_yrs <= 18:
        return "Pediatric"
    if min_yrs is not None and min_yrs >= 18:
        return "Adult"
    if min_yrs is not None and max_yrs is not None and min_yrs < 18 < max_yrs:
        return "Both"
    if min_yrs is not None and min_yrs < 18:
        return "Both"  # conservative: includes children if lower bound < 18
    return "Adult"


# CT.gov leadSponsor.class values. NOTE: OTHER_GOV is deliberately NOT
# mapped here — CT.gov over-applies it to non-US public hospitals (e.g.
# Chinese provincial hospitals, Czech public research institutes, Russian
# federal institutes) that are functionally academic. Those cases are
# routed through the name-based academic heuristic instead.
_CTGOV_SPONSOR_CLASS_MAP = {
    "INDUSTRY":   "Industry",
    "NIH":        "Government",
    "FED":        "Government",
    # "OTHER_GOV" → fall through (see note above)
    "NETWORK":    "Academic",
    "INDIV":      "Academic",     # individual investigator — treat as academic
    # "OTHER", "UNKNOWN", "AMBIG", "" → fall through to name heuristic
}

# Expanded academic hints (covers international terms the English-only list missed)
_ACADEMIC_HINTS = (
    # English
    "hospital", "university", "college",
    "medical center", "medical centre", "medical college", "medical school",
    "school of medicine", "school of nursing",
    "children's hospital", "childrens hospital",
    "general hospital", "affiliated hospital", "teaching hospital",
    "cancer center", "cancer centre", "comprehensive cancer",
    "research center", "research centre", "research institute",
    "institute for", "institute of", "institut", "instituto",
    "faculty of", "faculty", "faculdade", "facultad",
    "academic", "academy", "academia",
    "clinic",  # matches "Mayo Clinic", "Cleveland Clinic"
    "foundation for", "fondazione",
    # European
    "universität", "universitaet", "universitat", "università",
    "université", "universite", "universidad", "universidade", "universitair",
    "klinik", "klinikum", "krankenhaus",
    "hôpital", "hopital", "centre hospitalier", "center hospitalier",
    "ospedale", "policlinico",
    "ziekenhuis", "sjukhus",
    "assistance publique", "ap-hp",
    "charite", "charité",
    # UK / National
    "nhs ", "nhs trust", "national health service",
    "inserm",
    # Asian
    "pla general hospital", "pla hospital",
    "chinese academy", "chinese pla",
    "affiliated with", "affiliated of",
    "first hospital", "people's hospital", "peoples hospital",
    # Named US institutions with no obvious keyword
    "fred hutchinson", "memorial sloan", "dana-farber", "md anderson",
    "mayo clinic", "cleveland clinic", "johns hopkins",
    "st. jude", "st jude",
    "stanford", "harvard", "yale",  # common bare names
)

# Industry hints — corporate suffixes + industry-language keywords.
_INDUSTRY_HINTS = (
    # Corporate suffixes — padded with space to avoid matching inside other words
    " inc", " inc.", " incorporated",
    " ltd", " ltd.", " limited",
    " llc", " l.l.c",
    " corp", " corp.", " corporation",
    " plc", " pte", " pty",
    # Continental Europe
    " gmbh", " mbh", " ag ", " ag,", " kg ", " oy",
    " s.a.", " s.p.a", " spa ", " sas ", " sarl ", " srl ",
    # Asia / Americas
    " kk", " k.k.", " co., ltd", " co ltd", " co.",
    " bv ", " nv ",
    # Industry-language keywords
    "pharmaceutical", "pharmaceuticals", "pharma",
    "biotech", "biotechnology", "bioscience", "biosciences",
    "biopharmaceutical", "biopharma", "biologics",
    "therapeutics", "diagnostics", "genomics",
    "biotherapy", "biologic",
    "medicines", "biomedicine",
    "cell therapy", "cell therapies",
    "immuno", "immunology",  # frequently in company names
)

# Known pharma/biotech companies that don't always carry a corporate suffix
# in their CT.gov listing (e.g., "Novartis", "Kite", "Legend").
_KNOWN_INDUSTRY_NAMES = (
    "novartis", "roche", "genentech", "pfizer", "merck",
    "bristol", "bristol-myers", "bristol myers", "bms",
    "johnson & johnson", "j&j", "janssen",
    "gilead", "kite", "kite pharma",
    "astra", "astrazeneca", "sanofi", "bayer",
    "amgen", "regeneron", "abbvie", "lilly", "eli lilly",
    "takeda", "daiichi", "boehringer",
    "gsk", "glaxosmithkline",
    "celgene", "servier", "fosun",
    "allogene", "legend", "legend biotech", "cellectis", "precision bio",
    "carsgen", "jw therapeutics", "autolus", "cabaletta",
    "adicet", "arcus", "sotio", "poseida",
    "cargo", "carisma", "century therapeutics",
    "intellia", "crispr", "editas", "tessera",
    "tmunity", "nkarta", "caribou", "chinook",
    "juno", "immatics", "innate", "miltenyi",
    "mustang bio", "moderna", "biontech",
)

# Strong government signals — only genuine research-funding / regulatory
# agencies. Split into two lists:
#
#   _GOV_ACRONYMS  — short 2-4 char acronyms (nih, nci, fda, ema, dod, va,
#                    cdc). MUST be matched with word boundaries; otherwise
#                    "ema" matches inside "hematology", "dod" inside
#                    "blood", etc. (real bugs we hit).
#
#   _GOV_PHRASES   — multi-word phrases that are safe as substring checks.
#
# Deliberately excludes the generic "federal " prefix (too many non-US
# academic "Federal Research Institute"s got caught by it) and "ministry
# of" (ambiguous across jurisdictions).
_GOV_ACRONYMS = ("nih", "nci", "fda", "ema", "dod", "cdc", "va")

_GOV_PHRASES = (
    "national institutes of health",
    "national cancer institute",
    "department of veterans affairs", "veterans affairs",
    "department of defense",
    "centers for disease control",
    "u.s. food and drug",
    "nhs england",
)


# Investigator-initiated trials often list the PI as lead sponsor with
# CT.gov class "OTHER" (not "INDIV"). Without explicit PI detection these
# names ("Carl June, M.D., Ph.D.", "Stephan Grupp", "Bruce Cree") fall
# through to the default Academic branch — producing the right label
# but with zero transparency. The heuristic below names the reasoning.
_PERSON_DEGREE_MARKERS = (
    "m.d.", " md,", " md ", ", md", " md.", "md,",
    "ph.d", "phd", " d.o.", ", do",
    "pharmd", " dsc", " msc", "professor ",
)


def _looks_like_personal_name(name: str) -> bool:
    """True when the sponsor string is almost certainly a person's name
    (investigator-initiated trial), not an organization.

    Two positive signals:
      1. A medical/academic degree marker ("M.D.", "Ph.D.", "Professor").
      2. 2–4 short alphabetical tokens with no corporate / academic /
         government institutional keyword.
    """
    if not name:
        return False
    n = name.lower().strip()
    padded = f" {n} "

    # Degree markers — high-precision "this is a person"
    if any(m in n or m in padded for m in _PERSON_DEGREE_MARKERS):
        return True

    # Any institutional keyword disqualifies — it's an organization
    if any(h in n for h in _ACADEMIC_HINTS):
        return False
    if any(h in padded for h in _INDUSTRY_HINTS):
        return False
    if any(p in n for p in _GOV_PHRASES):
        return False
    if any(
        re.search(rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9])", n)
        for a in _GOV_ACRONYMS
    ):
        return False

    # Name-structure signal: 2–4 alphabetical tokens, each ≤15 chars
    tokens = [t.strip(",.'-") for t in name.split() if t.strip(",.'-")]
    if 2 <= len(tokens) <= 4 and all(t.replace("-", "").isalpha() for t in tokens):
        if all(len(t) <= 15 for t in tokens):
            return True

    return False


def _classify_sponsor(lead_sponsor: str | None,
                      lead_sponsor_class: str | None = None) -> str:
    """Return 'Industry' | 'Academic' | 'Government' | 'Other'.

    Resolution order (refined after an audit showed many non-US academic
    hospitals were being over-labelled 'Government'):

      1. Strong government signals in the name (NIH / NCI / VA / DoD /
         FDA / CDC / NHS England). These ALWAYS win — even over academic
         markers — because 'National Cancer Institute' is genuinely a
         government funding agency even though the name contains
         'institute'.

      2. Strong academic markers in the name (hospital / university /
         medical center / cancer center / klinik / medical college / etc.
         — see _ACADEMIC_HINTS). These OVERRIDE CT.gov's OTHER_GOV class,
         which over-applies to Chinese provincial hospitals, Czech public
         research institutes, Russian 'Federal Research Institute' entries
         etc. that are functionally academic.

      3. CT.gov class for remaining cases: INDUSTRY / NIH / FED only.
         OTHER_GOV is intentionally dropped — too many false positives.

      4. Known pharma brand names without corporate suffix.
      5. Industry corporate suffixes / keywords.
      6. Secondary academic hints (institute of / research institute /
         foundation / inserm / provincial).
      7. Default to Academic for non-empty, unclassified names.
      8. 'Other' only for truly-empty strings.
    """
    if not lead_sponsor:
        return "Other"
    s = lead_sponsor.lower().strip()
    if not s:
        return "Other"
    padded = f" {s} "

    # 1. Strong government signals — highest precedence, override academic.
    #    Acronyms matched with word boundaries (so "ema" doesn't hit inside
    #    "hematology", "dod" doesn't hit inside "blood", etc.).
    if any(
        re.search(rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9])", s)
        for a in _GOV_ACRONYMS
    ):
        return "Government"
    if any(p in s for p in _GOV_PHRASES):
        return "Government"

    # 2. Strong academic markers — override CT.gov's OTHER_GOV.
    if any(h in s for h in _ACADEMIC_HINTS):
        return "Academic"

    # 3. Trust CT.gov class for clear cases (Industry + NIH/FED). OTHER_GOV
    #    is intentionally absent from _CTGOV_SPONSOR_CLASS_MAP — it falls
    #    through to the keyword heuristic below.
    cls = (lead_sponsor_class or "").upper().strip()
    mapped = _CTGOV_SPONSOR_CLASS_MAP.get(cls)
    if mapped is not None:
        return mapped

    # 4. Known pharma brand names without corporate suffix (Novartis, Kite,
    #    Janssen, etc.).
    if any(h in s for h in _KNOWN_INDUSTRY_NAMES):
        return "Industry"

    # 5. Industry corporate suffixes and industry-language keywords.
    if any(h in padded for h in _INDUSTRY_HINTS):
        return "Industry"

    # 6. Secondary academic hints — 'institute of X', 'research institute',
    #    'foundation', 'inserm', etc. — handle non-hospital academic entities.
    secondary_acad = (
        "institute for", "institute of", "research institute",
        "research center", "research centre", "scientific center",
        "scientific-practical center", "scientific practical center",
        "foundation for", "fondazione", "inserm",
        "provincial", "national research",
    )
    if any(h in s for h in secondary_acad):
        return "Academic"

    # 7. Investigator-initiated trials — the lead sponsor is often the PI's
    #    name (with or without degree markers). Explicit detection so the
    #    reasoning is transparent, not a silent fall-through.
    if _looks_like_personal_name(lead_sponsor):
        return "Academic"

    # 8. Smart default — ambiguous cases land in Academic. In practice CT.gov
    #    class=OTHER trials without corporate suffixes are overwhelmingly
    #    investigator-initiated / academic.
    return "Academic"


def _sponsor_type(row: dict) -> str:
    """Thin row-wrapper for _classify_sponsor (kept for pipeline call-site)."""
    return _classify_sponsor(row.get("LeadSponsor"), row.get("LeadSponsorClass"))


# ---------------------------------------------------------------------------
# ClinicalTrials.gov fetch
# ---------------------------------------------------------------------------

_FETCH_BACKOFFS_SEC = (1.5, 3.0, 6.0)  # 4 attempts total: initial + 3 retries


def _fetch_with_retry(params: dict, *, cumulative_n: int) -> dict:
    """One paginated request with retry + exponential backoff.

    On total failure (all attempts exhausted), the raised error message
    includes `cumulative_n` so the operator immediately knows how much
    of the fetch had already succeeded — preventing surprise when a
    partial-fetch crash discards 90% of work.
    """
    import time as _time
    last_exc: Exception | None = None
    for attempt, sleep_secs in enumerate(
        (0.0, *_FETCH_BACKOFFS_SEC), start=1,
    ):
        if sleep_secs:
            _time.sleep(sleep_secs)
        try:
            resp = requests.get(BASE_URL, params=params, timeout=30)
            if resp.status_code == 200:
                return resp.json()
            # Treat 5xx as retryable; 4xx as terminal (don't waste retries)
            if 400 <= resp.status_code < 500:
                raise requests.HTTPError(
                    f"ClinicalTrials.gov API {resp.status_code} (terminal, "
                    f"4xx): {resp.text[:300]} "
                    f"[after {cumulative_n} cumulative studies fetched]"
                )
            last_exc = requests.HTTPError(
                f"ClinicalTrials.gov API {resp.status_code} on attempt "
                f"{attempt}/{1 + len(_FETCH_BACKOFFS_SEC)}: "
                f"{resp.text[:300]}"
            )
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
    raise requests.HTTPError(
        f"ClinicalTrials.gov fetch failed after "
        f"{1 + len(_FETCH_BACKOFFS_SEC)} attempts (backoffs: "
        f"{_FETCH_BACKOFFS_SEC}): {last_exc} "
        f"[after {cumulative_n} cumulative studies fetched]"
    )


def fetch_raw_trials(max_records: int = 5000, statuses: list[str] | None = None) -> list[dict]:
    """Pull all CAR-based cell-therapy trials from ClinicalTrials.gov v2.

    Intentionally broad: no condition-search restriction. Downstream handling —
    the tri-level classifier assigns Branch/Category/Entity, and
    _exclude_by_indication drops trials whose only indication is autoimmune /
    rheumatologic. This is more robust than trying to enumerate every onco
    condition term ClinicalTrials.gov might use (generic labels like "Neoplasms"
    or "Hematological Malignancies" were being missed before).

    Resilience: each paginated request retries up to 3× with exponential
    backoff (1.5/3/6 sec) on 5xx or transient network errors. On total
    failure, the raised message includes the cumulative-studies count
    so a partial-fetch blast radius is immediately visible.
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
        data = _fetch_with_retry(params, cumulative_n=len(studies))
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
    elig_mod = ps.get("eligibilityModule", {})
    outcomes_mod = ps.get("outcomesModule", {})

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

    primary_outcomes = outcomes_mod.get("primaryOutcomes") or []
    primary_endpoints = "|".join(o.get("measure", "") for o in primary_outcomes if o.get("measure")) or None

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
        "LeadSponsorClass": (sponsor_mod.get("leadSponsor") or {}).get("class"),
        "MinAge": elig_mod.get("minimumAge"),
        "MaxAge": elig_mod.get("maximumAge"),
        "StdAges": "|".join(elig_mod.get("stdAges") or []) or None,
        "PrimaryEndpoints": primary_endpoints,
    }


def _extract_sites(study: dict) -> list[dict]:
    ps = study.get("protocolSection", {})
    ident = ps.get("identificationModule", {})
    status = ps.get("statusModule", {})
    loc_mod = ps.get("contactsLocationsModule", {})

    sites = []
    for loc in (loc_mod.get("locations") or []):
        gp = loc.get("geoPoint") or {}
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
                "Latitude": gp.get("lat"),
                "Longitude": gp.get("lon"),
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

    # ---- Derived: ProductName (named CAR-T product if recognised) ----
    df["ProductName"] = df.apply(lambda r: _extract_product_name(r.to_dict()), axis=1)

    # ---- Derived: AgeGroup from MinAge/MaxAge or StdAges ----
    df["AgeGroup"] = df.apply(lambda r: _age_group(r.to_dict()), axis=1)

    # ---- Derived: SponsorType (Academic / Industry / Government / Unknown) ----
    df["SponsorType"] = df.apply(lambda r: _sponsor_type(r.to_dict()), axis=1)

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
    backfill_geo: bool = False,
) -> str:
    """Persist a dated snapshot of trials + sites + PRISMA + metadata.

    Byte-deterministic across input row order:
      - trials.csv sorted by NCTId
      - sites.csv sorted by (NCTId, FacilityName, City)
      - JSON written with sort_keys=True + stable indent
      - Wall-clock timestamp segregated to runinfo.json so the
        deterministic outputs (trials/sites/prisma/metadata) hash
        identically across re-runs of the same input

    The deterministic bytes guarantee makes snapshot diffs across
    pipeline-only changes attributable to real classifier changes (vs
    incidental row-order shuffles); reviewers replicating an analysis
    can confirm SHA-256 round-trip of the published artifacts.

    Optional `backfill_geo=True` re-fetches site lat/lon from CT.gov
    via `backfill_site_geo` so brand-new snapshots are geo-complete on
    day one rather than needing a follow-up backfill pass.
    """
    snapshot_date = datetime.utcnow().date().isoformat()
    out_dir = os.path.join(snapshot_dir, snapshot_date)
    os.makedirs(out_dir, exist_ok=True)

    # ---- Sort for determinism ----
    df_sorted = (
        df.sort_values("NCTId", kind="mergesort").reset_index(drop=True)
        if "NCTId" in df.columns else df
    )
    if not df_sites.empty and "NCTId" in df_sites.columns:
        site_sort_keys = [k for k in ["NCTId", "FacilityName", "City"]
                          if k in df_sites.columns]
        df_sites_sorted = (
            df_sites.sort_values(site_sort_keys, kind="mergesort")
            .reset_index(drop=True)
        )
    else:
        df_sites_sorted = df_sites

    # Optional geo backfill BEFORE write so the persisted sites.csv
    # is geo-complete (no follow-up pass needed). On any failure we
    # fall back to the un-backfilled sites — never block snapshot save.
    if backfill_geo and not df_sites_sorted.empty:
        try:
            df_sites_sorted = backfill_site_geo(df_sites_sorted)
        except Exception as _e:  # noqa: BLE001
            print(f"  WARN: backfill_site_geo failed ({_e}); "
                  f"saving snapshot without geo enrichment.")

    df_sorted.to_csv(os.path.join(out_dir, "trials.csv"), index=False)
    df_sites_sorted.to_csv(os.path.join(out_dir, "sites.csv"), index=False)

    with open(os.path.join(out_dir, "prisma.json"), "w") as f:
        json.dump(prisma, f, indent=2, sort_keys=True)

    # Deterministic metadata: identical inputs → identical bytes
    metadata = {
        "snapshot_date": snapshot_date,
        "statuses_filter": sorted(statuses or []),
        "n_trials": len(df_sorted),
        "n_sites": len(df_sites_sorted),
        "api_base_url": BASE_URL,
    }
    with open(os.path.join(out_dir, "metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2, sort_keys=True)

    # Wall-clock + provenance segregated here — non-deterministic by
    # nature; not part of the SHA-256 round-trip contract
    runinfo = {
        "created_utc": datetime.utcnow().isoformat(),
        "pipeline_sha": _git_sha_or_unknown(),
        "backfill_geo": backfill_geo,
    }
    with open(os.path.join(out_dir, "runinfo.json"), "w") as f:
        json.dump(runinfo, f, indent=2, sort_keys=True)

    return snapshot_date


def _git_sha_or_unknown() -> str:
    """Best-effort short git SHA for runinfo. Returns 'unknown' if git
    is unavailable or this is being run outside a checkout."""
    try:
        import subprocess
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            text=True, stderr=subprocess.DEVNULL,
        )
        return out.strip()
    except Exception:
        return "unknown"


_BACKFILL_BATCH_SIZE = 100
_BACKFILL_SLEEP_SEC = 0.25  # polite pause between batches


def backfill_site_geo(df_sites: pd.DataFrame) -> pd.DataFrame:
    """Re-fetch site lat/lon from CT.gov for rows missing geo data.

    Canonical implementation lives in this module so both
    `save_snapshot(backfill_geo=True)` and the standalone
    `scripts/backfill_site_geo.py` CLI share the same code path.

    Returns a copy of df_sites with Latitude / Longitude filled where
    the CT.gov API now provides them. Rows the API can't enrich are
    left as-is (no error). Batches NCT IDs (100 per request) for
    efficiency; gracefully no-op when df_sites is empty or already
    has full geo coverage.
    """
    import time as _time
    if df_sites.empty:
        return df_sites
    out = df_sites.copy()
    if "Latitude" not in out.columns:
        out["Latitude"] = pd.NA
    if "Longitude" not in out.columns:
        out["Longitude"] = pd.NA

    # Only fetch for NCTs that have at least one missing coord
    needs_fetch = (
        out["Latitude"].isna() | out["Longitude"].isna()
    )
    nct_ids = sorted(out.loc[needs_fetch, "NCTId"].dropna().unique().tolist())
    if not nct_ids:
        return out

    # Batched fetch: 100 NCTs per CT.gov call via filter.ids
    fetched: dict[tuple[str, str, str], tuple[float, float]] = {}
    for i in range(0, len(nct_ids), _BACKFILL_BATCH_SIZE):
        chunk = nct_ids[i: i + _BACKFILL_BATCH_SIZE]
        params = {
            "filter.ids": ",".join(chunk),
            "pageSize": _BACKFILL_BATCH_SIZE,
            "format": "json",
        }
        try:
            resp = requests.get(BASE_URL, params=params, timeout=60)
            if resp.status_code != 200:
                continue
            for s in resp.json().get("studies", []):
                ps = s.get("protocolSection", {})
                nct = ps.get("identificationModule", {}).get("nctId")
                if not nct:
                    continue
                locs = (ps.get("contactsLocationsModule", {})
                          .get("locations") or [])
                for loc in locs:
                    gp = loc.get("geoPoint") or {}
                    lat, lon = gp.get("lat"), gp.get("lon")
                    if lat is None or lon is None:
                        continue
                    facility = loc.get("facility") or ""
                    city = loc.get("city") or ""
                    fetched[(nct, facility, city)] = (
                        float(lat), float(lon),
                    )
        except Exception:
            continue
        _time.sleep(_BACKFILL_SLEEP_SEC)

    if not fetched:
        return out

    def _lookup(row, idx_axis: int) -> float | None:
        key = (
            row.get("NCTId"),
            row.get("FacilityName") or row.get("Facility") or "",
            row.get("City") or "",
        )
        coords = fetched.get(key)
        return coords[idx_axis] if coords else (
            row["Latitude"] if idx_axis == 0 else row["Longitude"]
        )

    out["Latitude"] = out.apply(lambda r: _lookup(r, 0), axis=1)
    out["Longitude"] = out.apply(lambda r: _lookup(r, 1), axis=1)
    return out


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
    # Older snapshots predate lat/lon extraction — add empty columns so the
    # app's site-map path sees a consistent schema.
    for _col in ("Latitude", "Longitude"):
        if not df_sites.empty and _col not in df_sites.columns:
            df_sites[_col] = pd.NA

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
