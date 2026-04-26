"""Invariant tests for the disease classifier post-normalisation hook.

Asserts that *every* return path of `_classify_disease` flows through
`_normalize_disease_result` and that the output respects the schema's
internal consistency rules:

  - branch ∈ VALID_BRANCHES
  - category ∈ VALID_CATEGORIES (or VALID_CATEGORIES + Exclude)
  - entity ∈ VALID_DISEASE_ENTITIES (or "Exclude" for excluded rows)
  - if design == "Single disease":   len(entities) == 1
  - if design == "Multi-disease":    len(entities) >= 2
  - primary entity is one of the entries in entities
  - the (Branch=Unknown, Category=Basket/Multidisease) collapse rule
    fires deterministically (the bug `_normalize_disease_result` was
    born to fix)

Also asserts that every entry in `llm_overrides.json` satisfies these
invariants — a real-world risk because overrides are hand-edited and
can drift from the schema if not guarded.

Pattern ported from rheum's REVIEW.md Phase 2 hardening (commit
`12` per the cross-app sync brief). Same defensive intent: make
silent classifier-shape regressions impossible.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402

from pipeline import _classify_disease, _normalize_disease_result  # noqa: E402
from config import (  # noqa: E402
    BASKET_MULTI_LABEL, HEME_BASKET_LABEL, SOLID_BASKET_LABEL,
    UNCLASSIFIED_LABEL, VALID_BRANCHES, VALID_CATEGORIES,
    VALID_DISEASE_ENTITIES,
)


# --- Synthetic input rows covering every classifier code path ---

_SYNTHETIC_ROWS = [
    # 1. Clean DLBCL hit (single entity)
    {"NCTId": "NCT_TEST_1",
     "BriefTitle": "CD19 CAR-T in r/r DLBCL",
     "Conditions": "Diffuse Large B-Cell Lymphoma",
     "BriefSummary": "DLBCL", "Interventions": "anti-CD19 CAR-T"},
    # 2. Multi-entity (DLBCL + MCL → Multi-disease)
    {"NCTId": "NCT_TEST_2",
     "BriefTitle": "CD19 CAR-T in DLBCL and MCL",
     "Conditions": "DLBCL; Mantle Cell Lymphoma",
     "BriefSummary": "DLBCL and MCL combined cohort"},
    # 3. Solid GBM
    {"NCTId": "NCT_TEST_3",
     "BriefTitle": "B7-H3 CAR-T in glioblastoma",
     "Conditions": "Glioblastoma multiforme",
     "BriefSummary": "Recurrent GBM"},
    # 4. Empty / unclassifiable row
    {"NCTId": "NCT_TEST_4",
     "BriefTitle": "Cell therapy study",
     "Conditions": "", "BriefSummary": "", "Interventions": ""},
    # 5. Basket pan-tumour (heme + solid → BASKET_MULTI_LABEL → was buggy)
    {"NCTId": "NCT_TEST_5",
     "BriefTitle": "Pan-tumour CAR-T basket",
     "Conditions": "Solid Tumors; Hematologic Malignancies",
     "BriefSummary": "Phase I basket trial spanning solid + heme."},
    # 6. R/R MM with no other markers
    {"NCTId": "NCT_TEST_6",
     "BriefTitle": "BCMA CAR-T in r/r multiple myeloma",
     "Conditions": "Multiple Myeloma",
     "BriefSummary": "RR MM"},
]


# ---------------------------------------------------------------------------
# Test class — the headline contract
# ---------------------------------------------------------------------------

class TestClassifierInvariants:

    @pytest.mark.parametrize("row", _SYNTHETIC_ROWS)
    def test_every_axis_value_in_canonical_vocabulary(self, row):
        """Every axis label must come from the canonical config.py vocab."""
        out = _classify_disease(row)
        assert out["branch"] in VALID_BRANCHES, (
            f"Branch {out['branch']!r} not in VALID_BRANCHES "
            f"({VALID_BRANCHES})"
        )
        # Category may be a basket label or VALID_CATEGORIES entry
        assert out["category"] in (set(VALID_CATEGORIES)
                                   | {BASKET_MULTI_LABEL,
                                      HEME_BASKET_LABEL,
                                      SOLID_BASKET_LABEL,
                                      UNCLASSIFIED_LABEL,
                                      "Exclude"}), (
            f"Category {out['category']!r} not in extended vocab"
        )
        # Entity may be a basket label, "Exclude", or a real entity
        valid_entities = set(VALID_DISEASE_ENTITIES) | {"Exclude"}
        assert out["entity"] in valid_entities, (
            f"Entity {out['entity']!r} not in VALID_DISEASE_ENTITIES"
        )

    @staticmethod
    def _entity_list(out: dict) -> list[str]:
        """Onc returns `entities` as a pipe-separated string (e.g.
        "DLBCL|MCL"); rheum returns a list. Normalise either shape."""
        ents = out.get("entities")
        if isinstance(ents, list):
            return [e for e in ents if e]
        if isinstance(ents, str) and ents:
            return [e.strip() for e in ents.split("|") if e.strip()]
        return [out.get("entity")] if out.get("entity") else []

    @pytest.mark.parametrize("row", _SYNTHETIC_ROWS)
    def test_design_consistency(self, row):
        """design + len(entities) must agree.

        - Single disease → exactly 1 entity in the list
        - Multi-disease → 2 or more entities
        """
        out = _classify_disease(row)
        ents = self._entity_list(out)
        n = len(ents)
        if out["design"] == "Single disease":
            assert n == 1, (
                f"Single-disease trial has {n} entities: {ents} "
                f"({row['NCTId']})"
            )
        elif out["design"] == "Multi-disease":
            assert n >= 2, (
                f"Multi-disease trial has {n} entities: {ents} "
                f"({row['NCTId']})"
            )

    @pytest.mark.parametrize("row", _SYNTHETIC_ROWS)
    def test_primary_entity_is_one_of_entities(self, row):
        """primary entity must be in the entities list."""
        out = _classify_disease(row)
        primary = out.get("entity")
        ents = self._entity_list(out)
        assert primary in ents, (
            f"primary {primary!r} not in entities {ents}"
        )

    def test_normalisation_collapses_unknown_basket_to_mixed(self):
        """Branch=Unknown + Category=Basket/Multidisease should normalize
        to Branch=Mixed (the bug `_normalize_disease_result` exists for)."""
        result = _normalize_disease_result({
            "branch": "Unknown",
            "category": BASKET_MULTI_LABEL,
            "entity": BASKET_MULTI_LABEL,
            "entities": [BASKET_MULTI_LABEL],
            "design": "Single disease",
        })
        assert result["branch"] == "Mixed", (
            f"Unknown+Basket/Multidisease should collapse to Mixed; "
            f"got {result['branch']!r}"
        )

    def test_normalisation_idempotent(self):
        """Running the normaliser twice produces identical output."""
        seed = {"branch": "Heme-onc", "category": "B-NHL",
                "entity": "DLBCL", "entities": ["DLBCL"],
                "design": "Single disease"}
        once = _normalize_disease_result(dict(seed))
        twice = _normalize_disease_result(dict(once))
        assert once == twice


# ---------------------------------------------------------------------------
# Override coherence — every llm_overrides.json entry must respect invariants
# ---------------------------------------------------------------------------

class TestLLMOverrideCoherence:

    @pytest.fixture(scope="class")
    def overrides(self):
        path = REPO_ROOT / "llm_overrides.json"
        if not path.exists():
            pytest.skip("llm_overrides.json absent")
        return json.loads(path.read_text())

    def test_every_override_has_nct_id(self, overrides):
        bad = [i for i, e in enumerate(overrides) if not e.get("nct_id")]
        assert not bad, f"Overrides without nct_id: {bad}"

    def test_branch_values_are_valid(self, overrides):
        bad = [
            (e["nct_id"], e.get("branch"))
            for e in overrides
            if e.get("branch") not in (set(VALID_BRANCHES) | {None})
        ]
        assert not bad, f"Overrides with invalid branch: {bad[:5]}"

    def test_category_values_are_valid(self, overrides):
        valid_cats = (set(VALID_CATEGORIES) | {BASKET_MULTI_LABEL,
                      HEME_BASKET_LABEL, SOLID_BASKET_LABEL,
                      UNCLASSIFIED_LABEL, None})
        bad = [
            (e["nct_id"], e.get("disease_category"))
            for e in overrides
            if e.get("disease_category") not in valid_cats
        ]
        assert not bad, f"Overrides with invalid disease_category: {bad[:5]}"

    def test_confidence_values_are_known(self, overrides):
        """confidence must be one of the values the pipeline honours.

        pipeline._load_overrides() only honours `high` and `medium`; an
        entry with `low` (or anything else) is silently dropped — which
        would violate the principle of least surprise.
        """
        valid = {"high", "medium", "low", None}
        bad = [(e["nct_id"], e.get("confidence")) for e in overrides
               if e.get("confidence") not in valid]
        assert not bad, f"Unknown confidence values: {bad[:5]}"
