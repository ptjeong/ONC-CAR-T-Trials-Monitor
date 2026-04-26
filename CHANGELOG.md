# Changelog

All notable changes to the ONC-CAR-T Trials Monitor are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions reference the classification-layer semantics; they are independent
of minor UI / figure tweaks.

## [Unreleased]

### Changed

- **Flag UX from reserved column to inline 🚩 prefix.** The dedicated
  `_Flag` column was reserving ~5% of every trial table's width for a
  cell that was empty 99% of the time. Now flagged trials get a 🚩
  prepended to their `BriefTitle` (no width reserved), and the per-trial
  drilldown card opens with a status banner — `st.error` for
  consensus-reached, `st.warning` for open flags — that lists the
  proposed corrections inline (axis | current | proposed) with direct
  GitHub-issue links.
- **Data tab gets a "🚩 Flagged only (N)" filter checkbox.** Live count;
  disabled when N=0. Lets the moderator subset to just the trials with
  open flags without scrolling the table.
- New cached helper `_load_flag_issue_details(issue_url)` (5-min TTL)
  fetches each flag issue's body and parses out the `BEGIN_FLAG_DATA`
  YAML blocks so the drilldown banner shows the actual proposed
  corrections, not just a count. Falls back to a regex scrape when
  pyyaml isn't available.
- `requirements.txt`: pin `pyyaml>=6.0` for robust flag-issue parsing.
- 6 new tests in `tests/test_flag_inline_prefix.py` covering the new
  prefix behaviour (idempotent re-prefix, zero-count edge case, empty
  flags early-return).

## [0.5.0] — 2026-04-25 — Click-to-drill UX + community quality-improvement loop

Headline: every trial table in the app is now click-to-drill, a new
By-target Deep Dive sub-tab landed, and the full community-flagging
quality-improvement loop is wired end-to-end (Suggest-correction
button → GitHub issue → 3-reviewer consensus → moderator approval
→ `llm_overrides.json` patch).

### Added — UX

- **Shared trial-drilldown helper** (`_render_trial_drilldown`).
  Single render path for the per-trial detail card used by Data tab,
  Geography city table, and every Deep Dive sub-tab. Two-column
  metadata + free-text payload + Suggest-correction expander.
- **Row-click trial drilldown** wired into:
  - Data tab (was already there)
  - Geography city-trials table ("Trials with open <country> sites in <city>")
  - Deep Dive by-disease focus-cohort trial list
  - Deep Dive by-product (two-step: product pivot → trials → detail)
  - Deep Dive by-sponsor (two-step: sponsor → trials → detail)
  - Deep Dive by-target (two-step: antigen → trials → detail)
- **Deep Dive by-sponsor improvements**: removed `.head(10)` cap, full
  scrollable sponsor list, search box (case-insensitive substring on
  LeadSponsor), select-to-trials drill.
- **NEW Deep Dive sub-tab — By target.** Two modes: (1) Landscape
  table of top-25 antigens with trial counts + modality split +
  disease breadth + top sponsor; (2) Single-antigen focus with 4
  metric tiles + 2×2 panel grid (top diseases / phase / modality /
  top sponsors) + click-to-drill trial list + CSV download.

### Added — community classification-flag system

- **Suggest-correction form** on every trial card (`_render_suggest_correction`).
  Multiselect axes + per-axis correction widget + free-text rationale +
  link-out to a pre-filled GitHub issue (`?title=…&labels=…&body=…`)
  containing both a markdown table for humans and a structured YAML
  block (`<!-- BEGIN_FLAG_DATA … END_FLAG_DATA -->`) for parsers.
- **Flag-badge column** on every trial table. `_load_active_flags()`
  hits the public GitHub Issues API (cached 5 min). `_flag_badge()`
  renders `⚑ N` for open flags or `⚑ consensus (N)` once threshold
  is met. Failure mode silent-degrades.
- **Issue template** (`.github/ISSUE_TEMPLATE/classification_flag.md`)
  documents the BEGIN_FLAG_DATA YAML block schema other reviewers
  must follow when adding their assessment as a comment.
- **Consensus-detection GitHub Action**
  (`.github/workflows/flag_consensus.yml` + `scripts/detect_flag_consensus.py`).
  Fires on issue/comment events, parses every YAML block in the issue
  body + comments, applies `consensus-reached` label when ≥3 distinct
  human authors agree on the same `(axis, proposed_correction)` tuple.
  Idempotent — re-running on the same issue is a no-op when label state
  is already correct. Bot-author exclusion. 8 parser unit tests.
- **Private Moderation tab** (token-gated via `?mod=<MODERATOR_TOKEN>`).
  Triages consensus-reached issues with Approve/Reject/Defer + rationale,
  with the actions appending per-axis records to
  `moderator_validations.json`. When no consensus issues are pending,
  switches to a stratified-by-branch random-validation mode that grows
  the moderator-validated ground-truth pool. Stats panel shows per-axis
  Cohen's κ between pipeline and moderator labels (gated to N≥10).
- **Promotion script** (`scripts/promote_consensus_flags.py`). Reads
  `consensus-reached` issues, optionally cross-checks against
  `moderator_validations.json` (`--require-moderator-approval`), builds
  a JSON patch against `llm_overrides.json`. Default dry-run; `--apply`
  mutates the file; `--close-issues` also tags + closes the issue on
  GitHub. SponsorType corrections are tracked but skipped on apply
  (separate promotion path needed). 8 unit tests.

### Added — tests

- `tests/test_flag_consensus.py` (8 tests) — YAML parser robustness,
  threshold enforcement, same-author dedup, bot exclusion, whitespace
  normalization, disagreement handling.
- `tests/test_moderator_helpers.py` (7 tests) — `_cohens_kappa`
  closed-form helper, anchored against the Sim-Wright (2005) BMC
  textbook example (κ ≈ 0.1304 to ±0.01).
- `tests/test_promote_consensus.py` (8 tests) — patch insert vs
  update, unsupported-axis handling, NCT extraction from title/body.

### Added — docs

- **`docs/internal/RHEUM_APP_KICKOFF.md`** — paste-ready brief for
  porting all 6 features in this release to the rheum sister app.
  Pinned to commit `f006d8e`. ~5-day sprint estimate, mostly mechanical
  copy from this repo with rheum-specific tweaks called out (e.g.
  the antigen exclusion list differs).

### Fixed

- Latent import-time bug: `st.secrets.get(...)` raised
  `StreamlitSecretNotFoundError` during the `test_methods_text`
  fixture's app.py import, silently SKIPPING 6 tests. Wrapped in
  try/except so missing secrets.toml degrades to None.

## [0.4.0] — 2026-04-25 — Independent-LLM validation infrastructure

Headline: a working three-layer validation harness (locked benchmark +
independent-LLM cross-validation + snapshot diff) plus the classifier and
documentation improvements that fell out of running it. Eleven real
classifier improvements landed across four iteration cycles, all
regression-tested. Benchmark held at 12/12 throughout.

### Added — validation infrastructure

- **Locked regression benchmark** (`tests/test_benchmark.py` +
  `tests/benchmark_set.csv`). 12 hand-curated pivotal trials covering
  pivotal CAR-T approvals, allogeneic CD19 (ALLO-501A), dual-target CARs
  (AUTO3 CD19/CD22), CAR-NK (PCAR-119 + allogeneic CD19 CAR-NK), in-vivo
  CAR-T (CD20), and a solid-tumour B7-H3 GBM allogeneic. Per-axis F1
  reported on every test run; regression below per-axis floor fails CI.
- **Independent-LLM cross-validation** (`scripts/validate_independent_llm.py`,
  581 LOC). Multi-vendor: Gemini 2.5 Flash Lite (free tier), Llama 3.3
  70B / 8B Instant via Groq (free tier), gpt-4o, Claude Haiku. Stratified
  sampling by Branch × DiseaseCategory; per-axis Cohen's κ; consensus-
  disagreement bucket (highest signal — both reviewers agree on a
  non-pipeline label). Per-provider rate pacing (Gemini 12 RPM / Groq
  25 RPM); fail-fast on TPD daily-quota exhaustion. Live re-classification
  through the current pipeline so post-hoc fixes show up immediately in
  the metrics. Closed-vocabulary prompt (DiseaseCategory list passed to
  the LLM) collapsed an early 24% agreement to 70% by removing
  vocabulary mismatch from the disagreement bucket.
- **Snapshot-to-snapshot diff** (`scripts/snapshot_diff.py`, 224 LOC).
  Compares two dated snapshots and categorises every reclassification
  as `expected (LLM override)` / `hard-listed` / `unexplained`. The
  `unexplained` bucket surfaces pipeline / config edits with wider
  blast radius than intended.
- **Site-level lat/lon** in snapshots via `scripts/backfill_site_geo.py`
  (one-shot CT.gov re-fetch keyed on NCT IDs from existing snapshot).
  Pipeline `_extract_sites` now pulls `geoPoint.lat/lon`.

### Added — classifier (from validation iterations)

- **Six new antigens** (independent-LLM-validated, user-confirmed on
  CT.gov): IL-5 (eosinophilic leukemia), CD1a (T-ALL), CD4 (CMML), FAP
  (mesothelioma), MET (melanoma / breast — with explicit verb-context
  disambiguation), FGFR4 (rhabdomyosarcoma).
- **Per-chunk category-fallback in `_classify_disease`** — multi-disease
  baskets where conditions mix specific entities ("CLL") with generic
  family names ("B-cell Lymphoma", "Acute Lymphoblastic Leukemia") now
  collapse to Basket/Multidisease (was: single-category misclassification).
  Surfaced by NCT05739227.
- **Allogenic spelling variant** (single-'e', common in Chinese trial
  titles) added to `ALLOGENEIC_MARKERS` and the strong-allo-terms list.
  Surfaced by NCT05739227 falling to the Autologous smart-default.
- **`liver metastases` / `metastatic liver` keyword** routes to GI
  category (NCT02862704 / MG7 CAR-T was falling to Unknown).
- **`Branch=Unknown + Category=Basket/Multidisease` normalisation** —
  `_normalize_disease_result` post-hook (`pipeline.py:193`) promotes
  Unknown to Mixed when the category is already Basket/Multidisease.
  Applied to all `_classify_disease` return paths.
- **Explicit PI detection** in sponsor classifier — `_looks_like_personal_name`
  routes investigator-initiated trials (PI-as-sponsor with degree markers
  like "M.D.", "Ph.D.") to Academic.

### Added — UI

- **Live-first data loading** with 24h cache (`@st.cache_data(ttl=86400)`).
  Sidebar refactored: live-default, with reproducibility-pinning expander.
  "Refresh now" / "Save current as snapshot" / "Pin a frozen dataset"
  exposed via expander.
- **Geography tab merged map** — single world map combining country
  choropleth + open-site dot overlay (was: separate maps). Per-country
  drilldown with city scatter + click-to-filter linkage. World-view
  scope fixed (was cropping to Europe when Asian/Americas dots off).
- **Site-level world + per-country maps** — `Scattergeo` overlay; per-
  country zoom auto-fits via `fitbounds="locations"`; dots colored by
  Branch with shape variation for greyscale safety.
- **Data tab consolidation** — single zoomable trial table with text
  search (NCT / title / sponsor / interventions), country zoom (replaces
  Countries column with Cities + SiteStatuses), three-button download row
  (current view / all filtered / site-level).
- **Fig 1 redesign** — two-panel figure (trial-start trend + regulatory
  milestone strip), shared x-axis. Per-regulator pill chips (FDA / EMA /
  NMPA) toggle dot visibility. Distinct colours + shapes per regulator
  so distinction survives greyscale.
- **Fig 7b absolute / % share toggle** — pill row above the chart.
- **Fig 8 white-for-zero treatment** — sparse-matrix idiom; only shaded
  cells get a label.
- **Three st.fragment wraps** (Fig 1, Fig 7b) to isolate widget reruns
  from the rest of the publication-figures tab.
- **Quarterly approvals-review cadence** — `APPROVED_PRODUCTS_LAST_REVIEWED`
  surfaced in Fig 1 caption; GitHub issue template at
  `.github/ISSUE_TEMPLATE/approvals_review.md`.
- **Overview tab shared branch colour key** at top — replaces per-figure
  legends so swatches don't repeat four times.
- **Filter-respect hardening** in captions: hero subtitle leads with
  "use the sidebar filters"; per-figure captions guard against narrow
  filters (e.g. "panels render when each has data").

### Changed — performance

- **Vectorised `_modality`** (was row-wise `df.apply` on ~2.5k trials).
- **Cached `_geo_sites`** in session_state (merge + drop_duplicates on
  ~10k site rows skipped when NCT filter unchanged).
- **Cached Germany subset** + `all_open_sites` similarly.
- **NCTLink baked into `df` once** at load (was per-rerun lambda).
- **Per-provider pacing** in independent-LLM script (not single shared
  RPM that throttled fast providers to slow ones).

### Changed — documentation

- **Methods text** now live-derives antigen counts and lists from config
  (was hand-maintained `(16) heme / (25) solid` while config held 22 / 28).
  Six regression tests in `tests/test_methods_text.py` lock against
  future drift.
- **Methods text describes all four validation layers** (was: only the
  original 2-round Claude curation).
- **Sponsor Classification methods section** added (8-step hierarchical
  heuristic).
- **Enrollment Analysis methods section** rewritten to describe the
  100%-stacked clinical-size-bucket Fig 4a (was: prior histogram
  description).
- **README rewrite** matching current state — branch list, antigen lists,
  Fig 4 description, Snapshots section, validation infrastructure
  section, repository-layout table.
- **CSV provenance headers now include classifier git SHA** — reviewer
  downloading the same snapshot through different code revisions can
  detect classification drift.

### Fixed

- Fig 1 layout / regulator overlay collisions (multiple iterations).
- Fig 4a legend overlap with x-tick labels.
- Geography tab "data_source" NameError after sidebar refactor (commit
  `fc4b8d8`).
- Various caption-data drift fixes.

### Removed

- Fig 4d forest plot (redundant with the size-bucket bar).
- Fig 7a product type by year (subsumed by Fig 7b modality).
- Sidebar Source toggle (replaced by reproducibility-pinning expander).

### Deprecated

- `validate.py` — single-vendor (Claude) curation tool. Generated the
  current `llm_overrides.json`; kept for historical reproducibility but
  superseded by `scripts/validate_independent_llm.py` (multi-vendor).

## [Earlier — pre-0.4.0 unreleased work]

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
