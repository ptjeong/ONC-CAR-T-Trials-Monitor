# Changelog

All notable changes to the ONC-CAR-T Trials Monitor are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions reference the classification-layer semantics; they are independent
of minor UI / figure tweaks.

## [Unreleased]

### Added
- **Deep Dive tab** — two focused sub-views:
  - *By disease*: drill into a Branch / Category / Entity combination. Shows
    phase distribution, target breakdown, start-year trend, top sponsors,
    and the full trial list. Exports the focus cohort as a provenance-tagged
    CSV.
  - *By product*: per-product pipeline table. Each row is one named CAR-T
    product (from `NAMED_PRODUCT_TARGETS`) with its primary target, modality,
    product type, furthest phase, unique sponsors, branches, categories,
    countries, and median enrollment.
- New sidebar filters: **Age group**, **Sponsor type**, **Classification
  confidence**. All wired into the reset button.
- New pipeline-derived columns: `AgeGroup` (Pediatric / Adult / Both / Unknown;
  from CT.gov `StdAges` / `MinAge` / `MaxAge`), `SponsorType` (Academic /
  Industry / Government / Unknown; from `LeadSponsor.class` with name-token
  fallback), `ProductName` (canonical named-product name if recognised),
  `PrimaryEndpoints` (pipe-joined from `outcomesModule.primaryOutcomes`).
- Classifier unit tests (`tests/test_classifier.py`, 39 cases) locking in
  every tricky edge case fixed during development: Hodgkin vs
  Non-Hodgkin word-boundary bug, EGFR vs EGFRvIII prefix collision,
  basket-multidisease multi-category detection, autoimmune-only exclusion,
  calibrated Autologous default, COVID / meta-therapeutic exclusions,
  age-group derivation, sponsor-type classification.

## [0.3.0] — 2026-04-24 — Hybrid classification architecture

### Added
- **Smart Autologous default** — if a trial is confirmed as CAR-T but has no
  explicit product-type marker, default to Autologous (~85% accurate). Each
  assignment records a `ProductTypeSource` tag so inferred labels are
  distinguishable from explicit ones.
- **ClassificationConfidence column** (high / medium / low) surfaced in the
  Data tab and sidebar data-quality panel.
- **Two-round LLM curation loop** using parallel Claude Opus subagents:
  round 1 classified the initial 783 flagged trials (616 high, 160 medium,
  126 excluded); round 2 cleaned the remaining 358 low-confidence trials
  (191 classified, 167 excluded). Overrides merged into `llm_overrides.json`
  with 831 active and 293 exclude-flagged entries. `_LLM_EXCLUDED_NCT_IDS`
  integrates at the PRISMA hard-exclusion stage.
- **New antigens**: FLT3, CLL1, CD147 (heme); CDH17, GUCY2C, GPNMB (solid).
- **Expanded named products**: 10+ additions including Chinese clinical-stage
  products (JY231, CT1190B, Meta10-19, CT0596, CT041 / satri-cel, MT027,
  HBI0101, TAA05, GCAR1, AZD0120, BOXR1030).

### Changed
- **Broad CT.gov fetch** — dropped the `AREA[ConditionSearch]` restriction.
  Downstream autoimmune-exclusion filter handles the non-onco false positives;
  recovered ~186 real onco trials that were registered under generic labels
  like "Hematological Malignancies" or "Neoplasms".
- **Removed Statuses-to-pull sidebar multiselect** — pulls all statuses by
  default now; the existing Overall-status filter gives the same in-session
  control.

### Fixed
- **Hodgkin vs Non-Hodgkin substring bug**: "hodgkin lymphoma" term was
  matching inside "non hodgkin lymphoma" text, sending ~50 B-NHL trials to
  the Hodgkin bucket. Fix: normalize "non hodgkin" → "nonhodgkin", and use
  word-boundary regex for all term lengths.
- **EGFR vs EGFRvIII prefix collision**: word-boundary matching now prevents
  EGFR from matching inside EGFRvIII.
- **Fig 4 enrollment outliers**: cap at 1,000 patients (NCT01166009's
  99,999,999 placeholder and NCT05366257's 160,602 real-world-data rows
  were dominating the total). Excluded outliers surfaced in a caption.
- **Fig 6 target panels**: `sort_values(ascending=True).head(20)` was
  selecting the 20 smallest targets, dropping CD19 from heme and GPC3 /
  MSLN / GD2 / HER2 / CLDN18.2 from solid. Replaced with top-15 descending
  + aggregated "Other (N antigens)" tail.
- **Fig 7b / Fig 3b / Fig 4c label-legend overlap**: bumped bottom margin
  and pushed legend further down.

## [0.2.0] — 2026-04-24 — Full rheum-app feature parity

### Added
- **Six-tab layout** matching the sister rheum app: Overview, Geography,
  Data, Publication Figures, Methods & Appendix, About.
- **PRISMA flow** documenting study selection.
- **Snapshot I/O** (save / load frozen datasets with `trials.csv`,
  `sites.csv`, `prisma.json`, `metadata.json`).
- **`validate.py`** — Claude-powered LLM validation tool.
- **Eight oncology-tuned publication figures**: temporal trends by branch
  with FDA-approval overlay; phase distribution by branch; geography
  choropleth + top-10 by branch; enrollment landscape with Heme-vs-Solid
  forest plot; Branch → Category → Entity sunburst; heme vs solid target
  panels; innovation signals (product type + modality over time); disease
  × target heatmap.
- **Cascading disease filter** (Branch → Category → Entity) in the sidebar.
- **Light NEJM theme** (navy + white) matching the sister rheum app.
- **FDA / NMPA / EMA approval overlay** on Fig 1 — FDA primary (bold navy
  vertical lines), NMPA (China) and EMA (EU) as muted secondary caption.
- **Impressum + Datenschutz** block in the About tab for German academic use.
- **Cohen's κ inter-rater tool** for stratified validation samples.
- **Curation loop CSV export** for human-in-the-loop refinement.

## [0.1.0] — 2026-04-24 — Initial MVP

### Added
- Streamlit dashboard with cascading Branch → Category → Entity filter.
- Tri-level disease ontology (3 branches, 20 categories, ~70 leaf entities).
- Target classifier covering 16 heme and 22 solid antigens + 7 dual
  combos + 4 platforms.
- Named-product short-circuit with 26 approved and clinical-stage products.
- Germany deep-dive (global choropleth + city-level Germany view).
- Autoimmune-indication exclusion (inverse of the rheum app).
- Provenance-tagged CSV exports.
- Published to GitHub as `ptjeong/ONC-CAR-T-Trials-Monitor` branch
  `initial-mvp`.
