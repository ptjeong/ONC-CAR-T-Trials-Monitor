"""Unit tests for the classifier — lock in tricky edge cases we've fixed.

Every case here corresponds to a bug we actually hit during development;
letting these regress would quietly degrade the dashboard's classifications.
Run with: `python -m pytest tests/ -v`
"""

import os
import sys

# Allow running from repo root without install
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from pipeline import (  # noqa: E402
    _classify_disease,
    _assign_target,
    _assign_product_type,
    _exclude_by_indication,
    _age_group,
    _sponsor_type,
    _classify_sponsor,
    _extract_product_name,
    _normalize_text,
    _term_in_text,
)


# ---------------------------------------------------------------------------
# Text normalization
# ---------------------------------------------------------------------------

def test_normalize_hyphen_to_space():
    assert _normalize_text("B-Cell Lymphoma") == "b cell lymphoma"


def test_normalize_non_hodgkin_collapse():
    """non hodgkin must become nonhodgkin to prevent 'hodgkin lymphoma'
    from matching inside non-Hodgkin contexts."""
    assert "nonhodgkin" in _normalize_text("Non-Hodgkin Lymphoma")
    assert "nonhodgkin" in _normalize_text("B-Cell Non-Hodgkin Lymphoma")


def test_normalize_rr_expansion():
    assert "relapsed refractory" in _normalize_text("R/R Multiple Myeloma")


def test_term_in_text_word_boundary():
    """Word-boundary matching prevents prefix collisions."""
    # EGFR must NOT match inside EGFRvIII
    text = _normalize_text("EGFRvIII CAR-T for recurrent GBM")
    assert _term_in_text(text, "egfrviii")
    assert not _term_in_text(text, "egfr")
    # CD19 must NOT match inside CD190
    text = _normalize_text("CD190 study")
    assert not _term_in_text(text, "cd19")


def test_term_in_text_hodgkin_boundary():
    """hodgkin lymphoma must NOT match inside non-hodgkin lymphoma after
    the non-hodgkin → nonhodgkin normalization."""
    text = _normalize_text("B-Cell Non-Hodgkin Lymphoma")
    assert not _term_in_text(text, "hodgkin lymphoma")


# ---------------------------------------------------------------------------
# Disease classification
# ---------------------------------------------------------------------------

def _mk(**kwargs):
    base = {
        "NCTId": "NCT00000000",
        "Conditions": "",
        "BriefTitle": "",
        "BriefSummary": "",
        "Interventions": "",
    }
    base.update(kwargs)
    return base


def test_b_nhl_not_classified_as_hodgkin():
    """Regression: "B-Cell Non-Hodgkin Lymphoma" was being routed to
    Hodgkin via substring match on 'hodgkin lymphoma'."""
    row = _mk(
        NCTId="T1",
        Conditions="B-Cell Non-Hodgkin Lymphoma",
        BriefTitle="CT1190B in R/R B-NHL",
    )
    result = _classify_disease(row)
    assert result["branch"] == "Heme-onc"
    assert result["category"] == "B-NHL"
    assert result["entity"] != "Classical HL"


def test_dlbcl_classified_correctly():
    row = _mk(
        Conditions="Diffuse Large B-Cell Lymphoma",
        BriefTitle="CD19 CAR-T in DLBCL",
    )
    result = _classify_disease(row)
    assert result["branch"] == "Heme-onc"
    assert result["category"] == "B-NHL"
    assert result["entity"] == "DLBCL"


def test_classical_hodgkin_still_matches():
    """Ensure the non-hodgkin fix doesn't break legitimate Hodgkin trials."""
    row = _mk(
        Conditions="Classical Hodgkin Lymphoma",
        BriefTitle="CD30 CAR-T in classical HL",
    )
    result = _classify_disease(row)
    assert result["branch"] == "Heme-onc"
    assert result["category"] == "Hodgkin"


def test_ph_positive_b_all():
    """Regression: "Philadelphia Chromosome-Positive ALL" with the hyphen
    used to fail the B-ALL match."""
    row = _mk(
        Conditions="Philadelphia Chromosome-Positive Acute Lymphoblastic Leukemia",
    )
    result = _classify_disease(row)
    assert result["branch"] == "Heme-onc"
    assert result["category"] == "B-ALL"


def test_multi_category_basket():
    """≥2 Tier-2 categories → Basket/Multidisease within the branch."""
    row = _mk(Conditions="Multiple Myeloma|B-Cell Non-Hodgkin Lymphoma")
    result = _classify_disease(row)
    assert result["branch"] == "Heme-onc"
    assert result["category"] == "Basket/Multidisease"
    assert result["design"] == "Basket/Multidisease"


def test_solid_tumor_generic():
    """Generic 'advanced solid tumors' maps to branch-level solid basket."""
    row = _mk(Conditions="Advanced Solid Tumors", BriefTitle="CLDN18.2 CAR-T")
    result = _classify_disease(row)
    assert result["branch"] == "Solid-onc"


def test_gbm_classification():
    row = _mk(Conditions="Glioblastoma", BriefTitle="EGFRvIII CAR-T for GBM")
    result = _classify_disease(row)
    assert result["branch"] == "Solid-onc"
    assert result["category"] == "CNS"
    assert result["entity"] == "GBM"


def test_unclassified_fallback():
    row = _mk(Conditions="Some rare condition")
    result = _classify_disease(row)
    assert result["branch"] == "Unknown"


# ---------------------------------------------------------------------------
# Target classification
# ---------------------------------------------------------------------------

def test_egfrviii_overrides_egfr():
    """Regression: EGFR was matching inside EGFRvIII."""
    row = _mk(BriefTitle="EGFRvIII CAR-T for GBM")
    assert _assign_target(row) == "EGFRvIII"


def test_named_product_short_circuits_antigen():
    """Known products hit NAMED_PRODUCT_TARGETS before generic antigen scan."""
    row = _mk(Interventions="ciltacabtagene autoleucel")
    assert _assign_target(row) == "BCMA"


def test_dual_target_detection():
    row = _mk(BriefTitle="CD19/CD22 bispecific CAR-T")
    assert _assign_target(row) == "CD19/CD22 dual"


def test_car_nk_platform():
    row = _mk(BriefTitle="CAR-NK for R/R AML", Interventions="CD123 CAR-NK cells")
    result = _assign_target(row)
    assert "CAR-NK" in result  # either bare CAR-NK or "CAR-NK: CD123"


def test_gpc3_hcc():
    row = _mk(BriefTitle="GPC3-directed CAR-T in advanced HCC")
    assert _assign_target(row) == "GPC3"


def test_claudin_18_2_extraction():
    row = _mk(BriefTitle="Claudin 18.2 CAR-T in gastric cancer")
    assert _assign_target(row) == "Claudin 18.2"


# ---------------------------------------------------------------------------
# Product-type classification
# ---------------------------------------------------------------------------

def test_explicit_autologous():
    row = _mk(BriefTitle="Autologous CAR-T")
    ptype, source = _assign_product_type(row)
    assert ptype == "Autologous"
    assert "autologous" in source


def test_explicit_allogeneic():
    row = _mk(BriefTitle="Universal off-the-shelf UCART19")
    ptype, source = _assign_product_type(row)
    assert ptype == "Allogeneic/Off-the-shelf"


def test_in_vivo_title():
    row = _mk(BriefTitle="In vivo CAR-T via mRNA-LNP")
    ptype, _ = _assign_product_type(row)
    assert ptype == "In vivo"


def test_default_autologous_when_no_allo_markers():
    """Regression: we used to label all these "Unclear" — now default to
    Autologous with confidence-source flag."""
    row = _mk(BriefTitle="CD19 CAR-T cells", Interventions="CAR T cells")
    ptype, source = _assign_product_type(row)
    assert ptype == "Autologous"
    assert source == "default_autologous_no_allo_markers"


def test_no_car_no_signal():
    """Trial with no CAR-T markers should be Unclear (no default applied)."""
    row = _mk(BriefTitle="Pembrolizumab in melanoma")
    ptype, source = _assign_product_type(row)
    assert ptype == "Unclear"
    assert source == "no_signal"


def test_allogenic_single_e_spelling():
    """Single-'e' "Allogenic" (common in Chinese trial titles) must trigger
    explicit_allogeneic — surfaced by NCT05739227 misclassified as autologous."""
    row = _mk(
        BriefTitle="Allogenic CD19-CAR-NK cells in B-cell malignancies",
        Interventions="allogenic CD19-CAR-NK cells",
    )
    ptype, source = _assign_product_type(row)
    assert ptype == "Allogeneic/Off-the-shelf"
    assert source == "explicit_allogeneic"


# ---------------------------------------------------------------------------
# Multi-condition basket detection
# ---------------------------------------------------------------------------

def test_multi_chunk_category_fallback_basket():
    """When conditions list spans multiple categories — even where some only
    match category-fallback terms (e.g., generic "B-cell Lymphoma" without a
    specific subtype) — pipeline must collapse to Basket/Multidisease.
    Surfaced by NCT05739227: B-ALL + B-NHL + CLL was being labelled CLL_SLL."""
    row = _mk(
        Conditions=(
            "Acute Lymphoblastic Leukemia|"
            "B-cell Lymphoma|"
            "Chronic Lymphocytic Leukemia"
        ),
        BriefTitle="CD19 CAR-T in B-cell malignancies",
    )
    result = _classify_disease(row)
    assert result["category"] == "Basket/Multidisease"
    assert result["branch"] == "Heme-onc"


def test_liver_metastases_routes_to_gi():
    """Generic "Liver Metastases" must route to GI (most liver-mets primary
    tumours are GI). Surfaced by NCT02862704 (MG7 CAR-T) which had been
    falling to Unknown / Unclassified."""
    row = _mk(
        Conditions="Liver Metastases",
        BriefTitle="MG7 CAR-T for advanced liver metastases",
    )
    result = _classify_disease(row)
    assert result["branch"] == "Solid-onc"
    assert result["category"] == "GI"


# ---------------------------------------------------------------------------
# Exclusion
# ---------------------------------------------------------------------------

def test_autoimmune_only_excluded():
    row = _mk(
        Conditions="Systemic Lupus Erythematosus",
        BriefTitle="CD19 CAR-T in SLE",
    )
    assert _exclude_by_indication(row) is True


def test_autoimmune_plus_onco_kept():
    """Trial with both autoimmune AND oncology mentions should NOT be excluded."""
    row = _mk(
        Conditions="SLE|DLBCL",
        BriefTitle="CD19 CAR-T for lupus or lymphoma",
    )
    assert _exclude_by_indication(row) is False


def test_generic_autoimmune_excluded():
    """Regression: generic 'autoimmune diseases' was not in the exclusion
    list and left trials in Branch=Unknown."""
    row = _mk(Conditions="Autoimmune Diseases", BriefTitle="CAR-T")
    assert _exclude_by_indication(row) is True


def test_covid_excluded():
    row = _mk(Conditions="COVID-19", Interventions="Vaccine")
    assert _exclude_by_indication(row) is True


# ---------------------------------------------------------------------------
# Age group
# ---------------------------------------------------------------------------

def test_age_group_std_ages_child():
    assert _age_group({"StdAges": "CHILD"}) == "Pediatric"


def test_age_group_std_ages_adult():
    assert _age_group({"StdAges": "ADULT|OLDER_ADULT"}) == "Adult"


def test_age_group_std_ages_both():
    assert _age_group({"StdAges": "CHILD|ADULT"}) == "Both"


def test_age_group_fallback_from_bounds():
    assert _age_group({"MinAge": "18 Years", "MaxAge": None}) == "Adult"
    assert _age_group({"MinAge": "1 Month", "MaxAge": "17 Years"}) == "Pediatric"
    assert _age_group({"MinAge": None, "MaxAge": None}) == "Unknown"


# ---------------------------------------------------------------------------
# Sponsor type
# ---------------------------------------------------------------------------

def test_sponsor_type_industry_class():
    assert _sponsor_type({"LeadSponsorClass": "INDUSTRY", "LeadSponsor": "Janssen"}) == "Industry"


def test_sponsor_type_academic_class():
    assert _sponsor_type({"LeadSponsorClass": "OTHER", "LeadSponsor": "Univ of Pennsylvania"}) == "Academic"


def test_sponsor_type_name_fallback_industry():
    row = {"LeadSponsorClass": "", "LeadSponsor": "Novartis Pharmaceuticals Inc."}
    assert _sponsor_type(row) == "Industry"


def test_sponsor_type_name_fallback_academic():
    row = {"LeadSponsorClass": "", "LeadSponsor": "Memorial Sloan Kettering Cancer Center"}
    assert _sponsor_type(row) == "Academic"


def test_sponsor_type_known_pharma_without_suffix():
    """Brand names without corporate suffix should hit the known-pharma list."""
    row = {"LeadSponsorClass": "", "LeadSponsor": "Novartis"}
    assert _sponsor_type(row) == "Industry"


def test_sponsor_type_government_us():
    row = {"LeadSponsorClass": "", "LeadSponsor": "National Cancer Institute (NCI)"}
    assert _sponsor_type(row) == "Government"


def test_sponsor_type_european_academic():
    """International academic terms (Universität, Hôpital, Ospedale)."""
    for name in [
        "Charité Universitätsmedizin Berlin",
        "Hôpital Saint-Louis Paris",
        "Ospedale San Raffaele",
        "Universitätsklinikum Köln",
    ]:
        row = {"LeadSponsorClass": "", "LeadSponsor": name}
        assert _sponsor_type(row) == "Academic", f"{name} → {_sponsor_type(row)}"


def test_sponsor_type_ambiguous_defaults_to_academic():
    """Ambiguous names (no suffix, no keyword) default to Academic, never 'Other'."""
    row = {"LeadSponsorClass": "OTHER", "LeadSponsor": "Smith, John"}
    assert _sponsor_type(row) == "Academic"


def test_sponsor_type_other_only_for_empty():
    """'Other' is reserved for truly empty sponsor strings."""
    assert _sponsor_type({"LeadSponsorClass": "", "LeadSponsor": ""}) == "Other"
    assert _sponsor_type({"LeadSponsorClass": "", "LeadSponsor": None}) == "Other"


# --- Regression tests from the user-audit of over-labelled Government ---

def test_nci_stays_government():
    """NCI is genuinely a federal research agency."""
    row = {"LeadSponsorClass": "NIH", "LeadSponsor": "National Cancer Institute (NCI)"}
    assert _sponsor_type(row) == "Government"


def test_chinese_provincial_hospital_is_academic():
    """CT.gov OTHER_GOV was misclassifying Chinese hospitals."""
    for name in [
        "Henan Cancer Hospital",
        "Anhui Provincial Hospital",
        "Zhejiang Provincial People's Hospital",
        "Institute of Hematology & Blood Diseases Hospital, China",
    ]:
        row = {"LeadSponsorClass": "OTHER_GOV", "LeadSponsor": name}
        assert _sponsor_type(row) == "Academic", f"{name} → {_sponsor_type(row)}"


def test_international_medical_centers_academic():
    """Public teaching hospitals abroad are academic, not government."""
    for name in [
        "Sheba Medical Center",
        "KK Women's and Children's Hospital",
    ]:
        row = {"LeadSponsorClass": "OTHER_GOV", "LeadSponsor": name}
        assert _sponsor_type(row) == "Academic", f"{name} → {_sponsor_type(row)}"


def test_research_institute_academic_even_with_federal_prefix():
    """'Federal Research Institute of Pediatric Hematology…' should be Academic,
    not Government — the entity functions as an academic research center
    even though the word 'Federal' appears in the name."""
    row = {
        "LeadSponsorClass": "OTHER_GOV",
        "LeadSponsor": "Federal Research Institute of Pediatric Hematology, Oncology and Immunology",
    }
    assert _sponsor_type(row) == "Academic"


def test_institute_of_academic():
    """'Institute of …' patterns should route to Academic."""
    row = {
        "LeadSponsorClass": "OTHER_GOV",
        "LeadSponsor": "Institute of Hematology and Blood Transfusion, Czech Republic",
    }
    assert _sponsor_type(row) == "Academic"


# --- PI-detection regression tests (investigator-initiated trials) ---

def test_indiv_pi_is_academic():
    """CT.gov class INDIV is a single-investigator sponsor — treat as Academic."""
    assert _classify_sponsor("David Porter", "INDIV") == "Academic"


def test_other_class_with_degree_markers_is_academic():
    """'Carl June, M.D.' under OTHER class should be detected as a PI."""
    assert _classify_sponsor("Carl June, M.D.", "OTHER") == "Academic"


def test_other_class_plain_person_name_is_academic():
    """Plain 2-token personal names under OTHER should route to Academic."""
    assert _classify_sponsor("Stephan Grupp", "OTHER") == "Academic"


def test_company_with_industry_keywords_stays_industry():
    """Brand names and pharma suffixes must not be misread as personal names."""
    assert _classify_sponsor("Kite Pharma", None) == "Industry"
    assert _classify_sponsor("Novartis", None) == "Industry"


# ---------------------------------------------------------------------------
# Product name extraction
# ---------------------------------------------------------------------------

def test_extract_product_name_axi_cel_canonicalizes():
    """Aliases collapse to the canonical display name so the per-product view
    doesn't split the same drug across multiple rows."""
    row = _mk(Interventions="axicabtagene ciloleucel")
    assert _extract_product_name(row) == "axi-cel (Yescarta)"
    # brand name alias maps to the same canonical
    row2 = _mk(BriefTitle="Yescarta in R/R DLBCL")
    assert _extract_product_name(row2) == "axi-cel (Yescarta)"
    # short-form alias maps to the same canonical
    row3 = _mk(Interventions="axi-cel")
    assert _extract_product_name(row3) == "axi-cel (Yescarta)"


def test_extract_product_name_codename():
    row = _mk(BriefTitle="CT041 in gastric cancer")
    # CT041 is the canonical codename for satri-cel → returns longest match
    assert _extract_product_name(row) is not None


def test_extract_product_name_none_when_generic():
    row = _mk(BriefTitle="Generic CAR-T study")
    assert _extract_product_name(row) is None
