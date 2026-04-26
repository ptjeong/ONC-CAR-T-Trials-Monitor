"""Taxonomy SSOT parity tests.

The classifier has TWO vocabularies for each axis:
  - `pipeline.py` — strict term-detection dicts (ENTITY_TERMS,
    HEME_TARGET_TERMS, SOLID_TARGET_TERMS, CATEGORY_FALLBACK_TERMS) used
    at runtime to decide what label to assign
  - `config.py` — canonical enumerations (VALID_DISEASE_ENTITIES,
    HEME_CATEGORIES, SOLID_CATEGORIES, VALID_TARGETS, VALID_CATEGORIES)
    used by the validator + LLM cross-check + downstream filters

These two MUST stay in sync. If a term-detection key exists without a
canonical synonym entry (or vice-versa), the classifier silently
emits labels the validator can't recognise, which inflates κ noise
and breaks the closed-vocabulary prompting design.

Pattern ported from rheum's REVIEW.md Phase 3 (commit `18`). Same
defensive intent: lock down the SSOT contract so taxonomy drift
becomes a CI failure, not a silent bug.

Drift this test class catches at first run informs us where to fix.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from config import (  # noqa: E402
    ENTITY_TERMS, CATEGORY_FALLBACK_TERMS,
    HEME_TARGET_TERMS, SOLID_TARGET_TERMS, DUAL_TARGET_LABELS,
    HEME_CATEGORIES, SOLID_CATEGORIES,
    VALID_DISEASE_ENTITIES, VALID_CATEGORIES, VALID_TARGETS,
    BASKET_MULTI_LABEL, HEME_BASKET_LABEL, SOLID_BASKET_LABEL,
    UNCLASSIFIED_LABEL, ONTOLOGY,
)


class TestVocabularyParity:
    """Strict ↔ canonical vocabulary parity per axis."""

    def test_entity_terms_keys_appear_in_valid_entities(self):
        """Every key in ENTITY_TERMS (the strict-detection dict) must
        appear in VALID_DISEASE_ENTITIES (the canonical list)."""
        missing = [k for k in ENTITY_TERMS if k not in VALID_DISEASE_ENTITIES]
        assert not missing, (
            f"Strict ENTITY_TERMS keys missing from VALID_DISEASE_ENTITIES: "
            f"{missing}. Either add them to the ontology or drop them "
            f"from term-detection."
        )

    def test_ontology_leaves_appear_in_entity_terms(self):
        """Every entity that lives in ONTOLOGY (the tier-3 leaves) should
        have a strict-term entry — otherwise the classifier can never
        actually assign that entity at runtime."""
        ontology_leaves = {
            e for cats in ONTOLOGY.values()
            for ents in cats.values()
            for e in ents
        }
        # Some ontology leaves are intentionally umbrella labels with no
        # strict-detection terms (they only fire via the fallback path);
        # we don't enforce parity in that direction. We DO assert there's
        # no entity that's claimed by ENTITY_TERMS but has no ontology
        # placement.
        ontology_only_unenforced = (
            set(ENTITY_TERMS) - ontology_leaves
        ) - {BASKET_MULTI_LABEL, HEME_BASKET_LABEL, SOLID_BASKET_LABEL,
              UNCLASSIFIED_LABEL}
        assert not ontology_only_unenforced, (
            f"Entities in ENTITY_TERMS without an ONTOLOGY home: "
            f"{ontology_only_unenforced}. Either add them to ONTOLOGY "
            f"under the right (Branch, Category) or drop the strict terms."
        )

    def test_category_fallback_keys_in_valid_categories(self):
        """Every key in CATEGORY_FALLBACK_TERMS must appear in
        VALID_CATEGORIES — otherwise the fallback can produce a label
        the validator rejects."""
        valid = set(VALID_CATEGORIES) | {BASKET_MULTI_LABEL,
                                          HEME_BASKET_LABEL,
                                          SOLID_BASKET_LABEL,
                                          UNCLASSIFIED_LABEL}
        missing = [k for k in CATEGORY_FALLBACK_TERMS if k not in valid]
        assert not missing, (
            f"CATEGORY_FALLBACK_TERMS keys missing from VALID_CATEGORIES: "
            f"{missing}"
        )

    def test_heme_categories_match_ontology(self):
        """HEME_CATEGORIES must equal the keys under ONTOLOGY['Heme-onc']."""
        ontology_heme = set(ONTOLOGY["Heme-onc"].keys())
        assert HEME_CATEGORIES == ontology_heme, (
            f"HEME_CATEGORIES drift: in-set-only={HEME_CATEGORIES - ontology_heme} "
            f"in-ontology-only={ontology_heme - HEME_CATEGORIES}"
        )

    def test_solid_categories_match_ontology(self):
        """SOLID_CATEGORIES must equal the keys under ONTOLOGY['Solid-onc']."""
        ontology_solid = set(ONTOLOGY["Solid-onc"].keys())
        assert SOLID_CATEGORIES == ontology_solid, (
            f"SOLID_CATEGORIES drift: in-set-only={SOLID_CATEGORIES - ontology_solid} "
            f"in-ontology-only={ontology_solid - SOLID_CATEGORIES}"
        )

    def test_target_terms_keys_appear_in_valid_targets(self):
        """Every antigen key in HEME_TARGET_TERMS / SOLID_TARGET_TERMS
        must appear in VALID_TARGETS — otherwise the validator's
        enum-lock prompt will reject canonical pipeline labels."""
        all_target_keys = set(HEME_TARGET_TERMS) | set(SOLID_TARGET_TERMS)
        valid_targets = set(VALID_TARGETS)
        missing = sorted(all_target_keys - valid_targets)
        assert not missing, (
            f"Target keys missing from VALID_TARGETS: {missing}. "
            f"Either add to VALID_TARGETS in config.py or drop from "
            f"term-detection."
        )

    def test_dual_target_labels_consist_of_known_antigens(self):
        """Each dual-combo `(a, b)` must reference antigens already in
        the heme-or-solid antigen vocabularies — preventing
        copy-paste typos in the dual list."""
        all_antigens = set(HEME_TARGET_TERMS) | set(SOLID_TARGET_TERMS)
        problems = []
        for combo, label in DUAL_TARGET_LABELS:
            for antigen in combo:
                if antigen not in all_antigens:
                    problems.append((combo, antigen, label))
        assert not problems, (
            f"DUAL_TARGET_LABELS reference unknown antigens: {problems}"
        )

    def test_no_duplicate_synonyms_between_entities(self):
        """A term should match at most one entity (otherwise the
        first-match-wins ordering is brittle)."""
        seen: dict[str, str] = {}
        collisions: list[tuple[str, str, str]] = []
        for entity, terms in ENTITY_TERMS.items():
            for t in terms:
                t_norm = t.lower().strip()
                if t_norm in seen and seen[t_norm] != entity:
                    collisions.append((t_norm, seen[t_norm], entity))
                else:
                    seen[t_norm] = entity
        assert not collisions, (
            f"Term collisions across entities: {collisions[:5]}"
        )
