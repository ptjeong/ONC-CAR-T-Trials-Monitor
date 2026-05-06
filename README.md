# CAR-T Oncology Trials Monitor

**Live app: [onc-car-t-trial-monitor.streamlit.app](https://onc-car-t-trial-monitor.streamlit.app)**
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.19738097.svg)](https://doi.org/10.5281/zenodo.19738097)

Sister app to the [Rheumatology CAR-T Trials Monitor](https://github.com/ptjeong/Rheumatology-CAR-T-Trials-Monitor-).

An interactive dashboard that tracks CAR-T, CAR-NK, CAAR-T, and CAR-γδ T clinical
trials across **hematologic and solid tumors**, sourced from the public
ClinicalTrials.gov registry.

The app provides a filtered trial list, a three-tier disease hierarchy
(Branch → Category → Entity), cascading filters, target-antigen classification,
cell-therapy modality annotation, approved-product overlays, geographic mapping
(global + per-country drilldown), strategic-landscape analyses, publication-ready
figures with provenance-tagged CSV exports, and an auto-generated methods section.

Designed as a research and educational resource — **not** a medical, regulatory,
or decision-support tool.

---

## Tab structure

| Tab | What it does |
|---|---|
| **Overview** | At-a-glance: branch chips, disease-hierarchy sunburst, by-category / by-target / by-phase / by-year / by-platform panels, top sponsors, recruitment hotspots, snapshot freshness banner |
| **Geography / Map** | Regional aggregation (China / NA / EU / APAC / MEA / LatAm), country picker → per-country phase + sponsor distribution, world map with site-level scatter, multi-city drilldown table |
| **Data** | Filterable trial table with column-level search; per-trial drilldown card |
| **Deep Dive** | Four sub-tabs: **By disease** (cohort focus), **By target** (antigen focus + maturity heatmap + temporal trajectory + co-targeting + sponsor commitment + white-space coverage), **By product** (per-product portfolio + Gantt + activity rate), **Strategic landscape** (4 cross-cutting analyses) |
| **Publication Figures** | 11 oncology-tuned figures (Fig 1-10 + Fig 12; Fig 11 is the PRISMA flow in Methods) with provenance-tagged CSV exports |
| **Methods & Appendix** | Auto-generated methods narrative + ontology + excluded NCT list + curation queue + validation κ — collapsed into a sub-tab row |
| **About** | Citation, disclaimer, contact |

A **sidebar Display options** expander controls global chart export format
(PNG 5× resolution for slides, or SVG vector for journal / Illustrator) and a
high-contrast Tableau-20-based palette toggle.

---

## Features

- **Live-first data loading** — ClinicalTrials.gov v2 fetched on first daily
  visit and cached 24h; reproducibility-pinning expander lets reviewers freeze
  to any dated snapshot for paper citations
- **Three-tier ontology** — Branch (Heme-onc / Solid-onc / Mixed / Unknown) →
  Category (20 Tier-2 buckets) → Entity (~70 Tier-3 leaves), with basket-trial
  handling and post-classification normalisation
- **Cascading sidebar filter** — Branch → Category → Entity, plus filters for
  Phase, Antigen target, Status, Product type, Modality, Country, Age group,
  Sponsor type, and Classification confidence
- **Sidebar Display options** — global PNG/SVG export-format radio (drives every
  chart's modebar download) and a Tableau-20 high-contrast palette toggle for
  greyscale-printing / stacked-bar legibility
- **Target classifier** covering 23 heme antigens (CD19, BCMA, CD20, CD22, CD5,
  CD7, CD30, CD33, CD38, CD70, CD123, GPRC5D, FcRH5, SLAMF7, CD79b, Kappa LC,
  FLT3, CLL1, CD147, CD4, CD1a, IL-5, BAFF-R) and 31 solid antigens (GPC3,
  Claudin 18.2, Mesothelin, GD2, HER2, EGFR, EGFRvIII, B7-H3, PSMA, PSCA, CEA,
  EpCAM, MUC1, CLDN6, NKG2D-L, ROR1, L1CAM, CD133, AFP, IL13Rα2, HER3, DLL3,
  CDH17, GUCY2C, GPNMB, FAP, MET, FGFR4, KRAS, NY-ESO-1, PRAME), plus 7 dual-
  target combos (CD19/CD22, CD19/CD20, CD19/BCMA, BCMA/GPRC5D, BCMA/CD70,
  HER2/MUC1, GPC3/MSLN)
- **Ligand-CAR convention** — for ligand-based CARs (IL3 → CD123, APRIL → BCMA,
  BAFF → BAFF-R, NKG2D → NKG2D-L), the classifier records the receptor on the
  tumour cell, NOT the binding-domain ligand on the construct. Documented in
  the rater UI's TargetCategory help text
- **Named-product short-circuit** — 86 product aliases across 15 antigen groups,
  spanning all 7 FDA-approved CAR-Ts (tisa-cel, axi-cel, brexu-cel, liso-cel,
  ide-cel, cilta-cel, obe-cel), 5 NMPA-approved (relma-cel, eque-cel, zevor-cel,
  inati-cel/Yorwida, renikeolunsai/Hicara, pulkilumab/Pulidekai), 1
  India/EU-approved (varni-cel/Qartemi), and clinical-stage products including
  anitocabtagene autoleucel (anito-cel), BMS-986453, KITE-753, NXC-201,
  WU-CART-007, GC012F, CT041 (satri-cel), MT027, HBI0101, JY231, Anbal-cel
- **Cell-therapy modality classification** — 8 mechanistically distinct buckets
  (Auto / Allo CAR-T, CAR-NK, CAAR-T, CAR-Treg, CAR-γδ T, In vivo CAR, unclear)
- **Sponsor classification** with explicit PI detection — Industry / Academic /
  Government / Other via 8-step hierarchical heuristic
- **PRISMA-style flow** + auto-generated Methods section that live-derives
  antigen lists, counts, LLM-curation stats, and ontology table from the live
  config/code (no hand-maintained drift)
- **Publication figures** (11 in the dedicated tab; Fig 11 PRISMA in Methods,
  oncology-tuned, NEJM-flat aesthetic):
  1. Temporal trends by branch with two-panel approval-milestone strip
     (FDA / EMA / NMPA / CDSCO dots filterable via pill chips, hover tooltip
     surfaces target + indication per approval)
  2. Phase distribution by branch
  3. Geographic distribution + global site-level scatter overlay
  4. Enrollment landscape — 100%-stacked clinical-size buckets +
     phase × branch + per-trial dot plot
  5. Branch → Category → Entity sunburst
  6. Heme vs solid antigen target panels
  7. Innovation signals — product type + modality over time (with absolute /
     % share toggle)
  8. Disease × antigen target heatmap (white-for-zero, label-on-shaded-cells)
  9. Antigen × Branch matrix with phase encoding
  10. Solid-tumour antigen frontier (chronological emergence)
  12. Industry sponsor crowding by antigen
- **Strategic Landscape** sub-tab in Deep Dive — 4 cross-cutting analyses
  (antigen first-in-class timeline, sponsor competition matrix, heme-vs-solid
  maturity gap, target momentum 24mo windows). All views auto-update with the
  sidebar filters and degrade gracefully when filters narrow the dataset
- **Geography tab** — regional aggregation (China / North America / Europe /
  Asia-Pacific / Middle East & Africa / Latin America / Other), country picker
  with per-country phase distribution + top-sponsor leaderboard, single merged
  world map (country choropleth + open-site dot overlay), per-country drilldown
  with city scatter and multi-city select
- **CSV exports** with `#`-prefixed provenance headers (snapshot date, filter
  state, row count, API source, **classifier git SHA**) — readable via
  `pd.read_csv(path, comment="#")`
- **Four-layer validation infrastructure**:
  1. Locked regression benchmark (`tests/benchmark_set.csv` + per-axis F1 floor)
  2. Independent-LLM cross-validation (`scripts/validate_independent_llm.py` —
     multi-vendor: Gemini / Groq / OpenAI / Anthropic — Cohen's κ + consensus
     disagreement bucket)
  3. Snapshot-to-snapshot diff (`scripts/snapshot_diff.py` — categorises
     reclassifications as expected / hard-listed / unexplained)
  4. Named-product audit (`scripts/audit/named_product_audit.py` — 46-product
     knowledge base; verifies every trial mentioning a known product gets the
     expected target / branch / modality classification. Achieved 97.2%
     trial-level accuracy on 181 audited trials in the most recent run)
- **External comparator** — Methods-text auto-generated section cross-cites the
  ASGCT/Citeline Q1 2026 Gene, Cell, & RNA Therapy Landscape Report for
  cross-validation of antigen ranking, with explicit disclosure of the
  comparator's gaps (no CAR-T-specific geographic / sponsor-type / autologous-
  vs-allogeneic stratification — gaps the present analysis fills)
- **Inter-rater κ validation app** — separate companion app under
  `validation_study/` for blind two-rater Cohen's κ measurement on a locked
  200-trial sample
- Full **Impressum, Datenschutz, and citation block** for German academic use

---

## Quick start

### Local

```bash
git clone https://github.com/ptjeong/ONC-CAR-T-Trials-Monitor.git
cd ONC-CAR-T-Trials-Monitor
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

The app opens at `http://localhost:8501`.

### Streamlit Community Cloud

1. Fork this repository to your GitHub account.
2. On [share.streamlit.io](https://share.streamlit.io), create a new app from the
   repo with `app.py` as the entry point.
3. (Optional, for the validation harness only) add one or more LLM API keys
   under **Secrets** so `scripts/validate_independent_llm.py` can run from the
   deployed instance:
   - `GEMINI_API_KEY` — free tier at https://aistudio.google.com/apikey
   - `GROQ_API_KEY`   — free tier at https://console.groq.com
   - `ANTHROPIC_API_KEY` — for the deprecated `validate.py` (kept for
     reproducibility of the existing `llm_overrides.json`)

---

## Data source

All trial data comes from [ClinicalTrials.gov API v2](https://clinicaltrials.gov/api/v2/studies).
The query combines CAR-based cell-therapy terms with oncology condition-search
terms (leukemia, lymphoma, myeloma, solid tumor, glioma, hepatocellular, pancreatic,
gastric, colorectal, ovarian, breast, prostate, sarcoma, melanoma, neuroblastoma,
mesothelioma, carcinoma). Trials whose *only* indication is autoimmune /
rheumatologic are excluded via a curated keyword list (the inverse of the
sister rheum app).

TCR-T products (NY-ESO-1 TCRs, MAGE-A4, afami-cel) are out of scope for v1 — they
are not strictly CAR-T constructs. NY-ESO-1 is included as a *target* in the
solid-antigen taxonomy because some CAR-T variants exist, and the comparator
analyses (ASGCT) report it as a top oncology target.

---

## Classification strategy

The pipeline uses a **hybrid four-layer classifier**: deterministic rules for
the bulk, a calibrated default for inference gaps, named-product short-circuits,
and a multi-round LLM validation loop for the residual ambiguous cases.

1. **Rule-based keyword layer** — `config.py` term tables:
   `ENTITY_TERMS`, `CATEGORY_FALLBACK_TERMS`, `HEME_TARGET_TERMS`,
   `SOLID_TARGET_TERMS`, `DUAL_TARGET_LABELS`, exclusions. Word-boundary
   regex for all term lengths prevents prefix collisions (EGFR vs EGFRvIII,
   hodgkin vs non-hodgkin).
2. **Named-product lookup** — `NAMED_PRODUCT_TARGETS` /
   `NAMED_PRODUCT_TYPES` map known products (86 aliases across 15 antigen
   groups) to their disclosed antigen and manufacturing type. Includes
   ligand-CAR mappings (IL3 → CD123, APRIL → BCMA, BAFF → BAFF-R, NKG2D →
   NKG2D-L) so the classifier records the tumor receptor, not the construct
   binding-domain ligand.
3. **Calibrated Autologous default** — if a trial is confirmed as CAR-T
   but no product-type marker surfaces, the pipeline defaults to
   `Autologous`, reflecting the dominant modality in the current landscape
   (~85 % of approvals and ongoing trials). Each assignment records a
   `ProductTypeSource` tag so inferred labels are distinguishable from
   explicit ones.
4. **LLM validation loop** — `validate.py` (Claude Opus) plus a structured
   batched workflow processes every low-confidence trial:
   - Export `curation_loop.csv` from the Methods & Appendix tab.
   - Split into batches of ~130 trials.
   - Launch parallel Claude agents, each receiving the batch CSV and an
     `allowed_values.json` listing every valid label. Each agent returns
     a strict-schema JSON array (`nct_id`, `branch`, `disease_category`,
     `disease_entity`, `target_category`, `product_type`, `exclude`,
     `exclude_reason`, `confidence`, `notes`).
   - Merge into `llm_overrides.json`; pipeline loads:
     - `_LLM_OVERRIDES` — per-trial reclassification entries
       (high/medium confidence, not excluded).
     - `_LLM_EXCLUDED_NCT_IDS` — trials the LLM flagged as off-scope
       (PRO studies, follow-up registries, bispecifics/mAbs, device
       trials, out-of-scope indications). Dropped at the PRISMA
       hard-exclusion stage, alongside the manual list.
   - **Precedence rule**: LLM overrides win for specific labels; for
     "punted" labels (`Other_or_unknown` / `CAR-T_unspecified`) the
     named-product lookup wins if it finds a known product. Prevents
     stale LLM punts from blocking newly-added named products.
5. **Hard-exclusion list** — `HARD_EXCLUDED_NCT_IDS` in `config.py` for
   manually curated exceptions.

Every trial carries a **`ClassificationConfidence`** label
(`high` / `medium` / `low`) combining rule strength, `ProductTypeSource`,
and LLM-override status. Surfaced in the Data tab and the Methods tab's
Classifier-confidence chart so users can filter analyses to high-confidence
rows only.

### Validation infrastructure

Four independent layers of validation ship with the repo:

**1. Locked regression benchmark** — `tests/benchmark_set.csv` plus
`tests/test_benchmark.py`. Pivotal CAR-T trials with hand-curated ground
truth across every classification axis. F1 floor enforced per axis; CI
fails on regression.

```bash
python -m pytest tests/test_benchmark.py -v -s
```

**2. Independent-LLM cross-validation** — `scripts/validate_independent_llm.py`.
Stratified sample of N trials sent to a non-Claude LLM (Gemini / Groq /
OpenAI) for blind re-classification, with Cohen's κ + consensus-disagreement
bucket. Breaks the Claude-curates-Claude agreement bias of the original
curation tool. Free-tier friendly (`gemini-2.5-flash-lite`,
`llama-3.1-8b-instant`).

```bash
export GEMINI_API_KEY=...    # https://aistudio.google.com/apikey (free tier)
export GROQ_API_KEY=...      # https://console.groq.com           (free tier)
pip install google-genai groq

python scripts/validate_independent_llm.py --n 100             # both providers if both keys set
python scripts/validate_independent_llm.py --n 50 --providers groq
```

Output goes to `reports/independent_llm_validation.md` (gitignored) —
per-axis κ, plus a `Consensus disagreements` section listing trials where
every reviewer agrees on a label different from the pipeline. That
section is the highest-signal triage list.

**3. Snapshot-to-snapshot diff** — `scripts/snapshot_diff.py`. Categorises
every reclassification between two snapshots as `expected (LLM override)` /
`hard-listed` / `unexplained`. The `unexplained` bucket catches pipeline /
config edits with wider blast radius than intended.

```bash
python scripts/snapshot_diff.py snapshots/2026-04-24 snapshots/<new-date>
```

**4. Named-product audit** — `scripts/audit/named_product_audit.py`.
Maintains a 46-product knowledge base (`scripts/audit/known_products.py`)
covering FDA/NMPA/EMA/CDSCO-approved CAR-Ts plus clinical-stage codenames.
For every product, checks that all trials mentioning it in the dataset
are classified to the expected target / branch / product type. Achieved
**97.2% trial-level accuracy on 181 audited trials** in the most recent
run; mismatches surface as a structured PARTIAL / MISS report for triage.

```bash
python scripts/audit/named_product_audit.py /path/to/trials_view.csv
```

**5. Inter-rater κ companion app** — `validation_study/app.py` is a
separate Streamlit app for blind two-rater Cohen's κ measurement on a
locked 200-trial pre-registered sample (`validation_study/sample_v1.json`,
sha256-anchored). 8 axes (Branch, DiseaseCategory, DiseaseEntity,
TargetCategory, ProductType, SponsorType, Platform, TrialDesign). Token-
gated rater URLs; durable submission storage with append-only audit log.

#### Legacy single-vendor curation (`validate.py`)

`validate.py` (Claude-only) generated the entries currently in
`llm_overrides.json`. Kept for historical reproducibility but
**deprecated** — use the multi-vendor harness above for new curation.

---

## External comparator

The Methods tab auto-generated narrative cross-cites the
[ASGCT/Citeline Q1 2026 Gene, Cell, & RNA Therapy Landscape Report](https://www.asgct.org/uploads/files/general/Landscape-Report-2026-Q1.pdf)
(April 2026). Top oncology antigen targets reported by ASGCT (CD19 154
programs, BCMA 68, CD20 29, CD22 27, HER2 25, claudin 18 24, GPC3 23,
KRAS 20, mesothelin 17, CD70 16, NY-ESO-1 15, CD7 15, EGFR 14, CD33 14,
B7-H3 14, PRAME 13, MUC1 13, GPRC5D 11, CLEC12A 11) align with the antigens
captured by `HEME_TARGET_TERMS` / `SOLID_TARGET_TERMS`; KRAS, NY-ESO-1, and
PRAME were added in May 2026 to match.

ASGCT does NOT separate CAR-T from broader gene-therapy aggregates and
provides no geographic, sponsor-type, or autologous/allogeneic stratification
— gaps the present analysis fills via direct CT.gov queries with curated
CAR-T classification.

---

## Snapshots

The app defaults to live data with a 24h cache. For paper-citable
reproducibility, the sidebar exposes a **Reproducibility — pin a frozen
dataset** expander that:

1. Saves the current live data as a dated snapshot
   (`trials.csv`, `sites.csv`, `prisma.json`, `metadata.json` written to
   `snapshots/<YYYY-MM-DD>/`).
2. Pins any previously-saved snapshot for the rest of the session
   (sidebar status flips to "Pinned to … · n trials"). Click **Unpin** to
   return to live data.

Both data paths (`load_frozen` for pinned, `load_live` for default) include
mtime-based cache invalidation: edits to `config.py` / `pipeline.py` /
`llm_overrides.json` (or to the snapshot CSV directly) are detected on the
next render and the Streamlit cache rebuilds automatically.

Publication CSVs include a `#`-prefixed header block with snapshot date,
filter state, row count, source URL, and **classifier git SHA** — readable
via `pd.read_csv(path, comment="#")`. The classifier-SHA tag means a
reviewer downloading the same snapshot through a future code revision can
detect classification drift even if the trial set is identical.

---

## Repository layout

| Path | Purpose |
|---|---|
| `app.py` | Streamlit UI, filters, tabs, figures, exports (~9,300 LOC) |
| `pipeline.py` | API fetch, tri-level classifier, PRISMA, snapshot I/O (~1,750 LOC) |
| `config.py` | Disease ontology, target antigens, named products, exclusions (~780 LOC) |
| `llm_overrides.json` | Per-trial classification overrides from LLM curation |
| `tests/` | Unit tests (`test_classifier.py`), regression benchmark (`benchmark_set.csv` + `test_benchmark.py`), Methods-text drift guards (`test_methods_text.py`), filter NaN regression (`test_filter_completeness.py`) |
| `scripts/` | `validate_independent_llm.py` (multi-vendor LLM cross-validation), `snapshot_diff.py`, `backfill_site_geo.py`, `generate_validation_sample.py` |
| `scripts/audit/` | Named-product classification audit — `known_products.py` (46-product knowledge base) + `named_product_audit.py` |
| `validation_study/` | Companion inter-rater κ Streamlit app + locked 200-trial sample (`sample_v1.json`) + per-rater response-state files |
| `snapshots/<YYYY-MM-DD>/` | Reproducible frozen datasets (`trials.csv`, `sites.csv`, `prisma.json`, `metadata.json`) |
| `reports/` | Validation-loop output (gitignored) |
| `docs/internal/` | Cross-app sync briefs, port prompts, audit prompts (e.g. `LIGAND_CAR_TARGET_FIX_BRIEF_RHEUM.md`, `ASGCT_Q1_2026_PORT_BRIEF_RHEUM.md`, `NAMED_PRODUCT_AUDIT_PROMPT.md`) |
| `.github/workflows/` | CI: pytest matrix on Python 3.11 + 3.12 |
| `.github/ISSUE_TEMPLATE/` | Quarterly approvals review, bug report, classification correction |
| `validate.py` | **Deprecated** — single-vendor Claude curation that produced `llm_overrides.json`. Kept for historical reproducibility |
| `requirements.txt` | Pinned Python dependencies (no `kaleido` — image export uses Plotly's browser-side modebar, configured globally via the sidebar Display options) |
| `LICENSE` | MIT |
| `CITATION.cff` | Citation metadata (Zenodo DOI, version, author) |
| `SECURITY.md` | Vulnerability reporting policy |

---

## Citation

> Jeong P. CAR-T Oncology Trials Monitor [Internet].
> Klinik I für Innere Medizin, Hämatologie und Onkologie,
> Klinische Immunologie und Rheumatologie, Universitätsklinikum Köln; 2026.
> DOI: [10.5281/zenodo.19738097](https://doi.org/10.5281/zenodo.19738097).
> Available from: https://onc-car-t-trial-monitor.streamlit.app
> Source: ClinicalTrials.gov API v2.

The live app surfaces an auto-populated citation block under the **About** tab.

---

## License

[MIT](./LICENSE). Copyright (c) 2026 Peter Jeong, Universitätsklinikum Köln.

---

## Contact

**Peter Jeong**
Universitätsklinikum Köln
Klinik I für Innere Medizin — Klinische Immunologie und Rheumatologie
✉ [peter.jeong@uk-koeln.de](mailto:peter.jeong@uk-koeln.de)
