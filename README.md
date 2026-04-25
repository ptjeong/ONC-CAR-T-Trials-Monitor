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
(global + Germany-specific), publication-ready figures with provenance-tagged CSV
exports, and an auto-generated methods section.

Designed as a research and educational resource — **not** a medical, regulatory,
or decision-support tool.

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
- **Target classifier** covering 22 heme antigens (CD19, BCMA, CD20, CD22, CD5,
  CD7, CD30, CD33, CD38, CD70, CD123, GPRC5D, FcRH5, SLAMF7, CD79b, Kappa LC,
  FLT3, CLL1, CD147, CD4, CD1a, IL-5) and 28 solid antigens (GPC3, Claudin 18.2,
  Mesothelin, GD2, HER2, EGFR, EGFRvIII, B7-H3, PSMA, PSCA, CEA, EpCAM, MUC1,
  CLDN6, NKG2D-L, ROR1, L1CAM, CD133, AFP, IL13Rα2, HER3, DLL3, CDH17, GUCY2C,
  GPNMB, FAP, MET, FGFR4), plus 7 dual-target combos
- **Named-product short-circuit** — approved & late-stage products (tisa-cel,
  axi-cel, brexu-cel, liso-cel, ide-cel, cilta-cel, obe-cel, relma-cel, eque-cel,
  zevor-cel, GC012F, CT041 / satri-cel, MT027, HBI0101, ALLO-501/715, …)
- **Cell-therapy modality classification** — 8 mechanistically distinct buckets
  (Auto / Allo CAR-T, CAR-NK, CAAR-T, CAR-Treg, CAR-γδ T, In vivo CAR, unclear)
- **Sponsor classification** with explicit PI detection — Industry / Academic /
  Government / Other via 8-step hierarchical heuristic
- **PRISMA-style flow** + auto-generated Methods section that live-derives
  antigen lists, counts, LLM-curation stats, and ontology table from the live
  config/code (no hand-maintained drift)
- **Publication figures** (8 figures, oncology-tuned, NEJM-flat aesthetic):
  1. Temporal trends by branch with two-panel approval-milestone strip
     (FDA / EMA / NMPA dots filterable via pill chips)
  2. Phase distribution by branch
  3. Geographic distribution + global site-level scatter overlay
  4. Enrollment landscape — 100%-stacked clinical-size buckets +
     phase × branch + per-trial dot plot
  5. Branch → Category → Entity sunburst
  6. Heme vs solid antigen target panels
  7. Innovation signals — product type + modality over time (with absolute /
     % share toggle)
  8. Disease × antigen target heatmap (white-for-zero, label-on-shaded-cells)
- **Geography tab** — single merged world map (country choropleth + open-site
  dot overlay), per-country drilldown with city scatter, country-zoom in Data tab
- **CSV exports** with `#`-prefixed provenance headers (snapshot date, filter
  state, row count, API source, **classifier git SHA**) — readable via
  `pd.read_csv(path, comment="#")`
- **Three-layer validation infrastructure**:
  1. Locked regression benchmark (`tests/benchmark_set.csv` + per-axis F1 floor)
  2. Independent-LLM cross-validation (`scripts/validate_independent_llm.py` —
     multi-vendor: Gemini / Groq / OpenAI / Anthropic — Cohen's κ + consensus
     disagreement bucket)
  3. Snapshot-to-snapshot diff (`scripts/snapshot_diff.py` — categorises
     reclassifications as expected / hard-listed / unexplained)
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

TCR-T products (NY-ESO-1, MAGE-A4, afami-cel) are out of scope for v1 — they are
not strictly CAR-T constructs.

---

## Classification strategy

The pipeline uses a **hybrid four-layer classifier**: deterministic rules for
the bulk, a calibrated default for inference gaps, and a two-round LLM
validation loop for the residual ambiguous cases.

1. **Rule-based keyword layer** — `config.py` term tables:
   `ENTITY_TERMS`, `CATEGORY_FALLBACK_TERMS`, `HEME_TARGET_TERMS`,
   `SOLID_TARGET_TERMS`, `DUAL_TARGET_LABELS`, exclusions. Word-boundary
   regex for all term lengths prevents prefix collisions (EGFR vs EGFRvIII,
   hodgkin vs non-hodgkin).
2. **Named-product lookup** — `NAMED_PRODUCT_TARGETS` /
   `NAMED_PRODUCT_TYPES` map known products (tisa-cel, axi-cel, ide-cel,
   cilta-cel, GC012F, CT041, HBI0101, MT027, ThisCART19A, JY231, …) to
   their disclosed antigen and manufacturing type.
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
5. **Hard-exclusion list** — `HARD_EXCLUDED_NCT_IDS` in `config.py` for
   manually curated exceptions.

Every trial carries a **`ClassificationConfidence`** label
(`high` / `medium` / `low`) combining rule strength, `ProductTypeSource`,
and LLM-override status. Surfaced in the Data tab and Data-Quality panel
so users can filter analyses to high-confidence rows only.

### Validation infrastructure

Three independent layers of validation ship with the repo:

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

#### Legacy single-vendor curation (`validate.py`)

`validate.py` (Claude-only) generated the entries currently in
`llm_overrides.json`. Kept for historical reproducibility but
**deprecated** — use the multi-vendor harness above for new curation.

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

Publication CSVs include a `#`-prefixed header block with snapshot date,
filter state, row count, source URL, and **classifier git SHA** — readable
via `pd.read_csv(path, comment="#")`. The classifier-SHA tag means a
reviewer downloading the same snapshot through a future code revision can
detect classification drift even if the trial set is identical.

---

## Repository layout

| Path | Purpose |
|---|---|
| `app.py` | Streamlit UI, filters, tabs, figures, exports (~4,800 LOC) |
| `pipeline.py` | API fetch, tri-level classifier, PRISMA, snapshot I/O |
| `config.py` | Disease ontology, target antigens, named products, exclusions |
| `llm_overrides.json` | Per-trial classification overrides from LLM curation |
| `tests/` | Unit tests (`test_classifier.py`), regression benchmark (`benchmark_set.csv` + `test_benchmark.py`), Methods-text drift guards (`test_methods_text.py`) |
| `scripts/` | `validate_independent_llm.py` (multi-vendor LLM cross-validation), `snapshot_diff.py`, `backfill_site_geo.py` |
| `snapshots/<YYYY-MM-DD>/` | Reproducible frozen datasets (`trials.csv`, `sites.csv`, `prisma.json`, `metadata.json`) |
| `reports/` | Validation-loop output (gitignored) |
| `.github/workflows/` | CI: pytest matrix on Python 3.11 + 3.12 |
| `.github/ISSUE_TEMPLATE/` | Quarterly approvals review, bug report, classification correction |
| `validate.py` | **Deprecated** — single-vendor Claude curation that produced `llm_overrides.json`. Kept for historical reproducibility |
| `requirements.txt` | Pinned Python dependencies |
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
