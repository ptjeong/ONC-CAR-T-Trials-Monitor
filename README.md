# CAR-T Oncology Trials Monitor

**Live app: [onc-car-t-trial-monitor.streamlit.app](https://onc-car-t-trial-monitor.streamlit.app)**

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

- **Live pull** from ClinicalTrials.gov API v2 or reproducible **frozen snapshots**
- **Three-tier ontology** — Branch (Heme-onc / Solid-onc / Mixed) → Category (20
  Tier-2 buckets) → Entity (~70 Tier-3 leaves), with basket-trial handling
- **Cascading sidebar filter** — selecting Branch narrows Category, which narrows Entity
- **Target classifier** covering heme antigens (CD19, BCMA, CD20, CD22, CD7, CD30,
  CD33, CD38, CD70, CD123, GPRC5D, FcRH5, SLAMF7, CD79b, Kappa LC) and solid
  antigens (GPC3, Claudin 18.2, Mesothelin, GD2, HER2, EGFR, EGFRvIII, B7-H3,
  PSMA, PSCA, CEA, EpCAM, MUC1, CLDN6, NKG2D-L, ROR1, L1CAM, CD133, AFP, IL13Rα2,
  HER3, DLL3), plus dual-target combos
- **Named-product short-circuit** — approved & late-stage products (tisa-cel,
  axi-cel, brexu-cel, liso-cel, ide-cel, cilta-cel, obe-cel, eque-cel, zevor-cel,
  GC012F, ALLO-501/715, …)
- **Approved-product temporal overlay** on the start-year figure
- **LLM-assisted classification** via `validate.py` (Claude-powered) — persistent
  per-trial overrides in `llm_overrides.json` picked up by the pipeline
- **PRISMA-style flow** documenting study selection
- **Auto-generated methods section** with live counts and ontology table
- **Publication figures** (8 figures, oncology-tuned):
  1. Temporal trends by branch, with approved-product overlay
  2. Phase distribution by branch
  3. Geographic distribution, stratified by branch
  4. Enrollment landscape (histogram + phase × branch + forest plot)
  5. Branch → Category → Entity sunburst
  6. Heme vs solid antigen target panels
  7. Innovation signals (product type + modality over time)
  8. Disease × target heatmap (oncology-specific signature figure)
- **Germany-specific view** (site-level map, city breakdown, enrolling centers)
- **CSV exports** with `#`-prefixed provenance headers (snapshot date, filter state,
  row count, API source)
- **Curation loop** + stratified validation sample + Cohen's κ inter-rater tools
- Full **Impressum, Datenschutz, and citation block** for academic use

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
3. (Optional) Add `ANTHROPIC_API_KEY` under **Secrets** to run the LLM validator
   from the deployed instance.

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

### Running the LLM validator

```bash
export ANTHROPIC_API_KEY=sk-ant-...

python validate.py                   # review borderline trials (≤30)
python validate.py --nct NCT0612...  # review one trial
python validate.py --limit 100       # expand batch
```

Results merge into `llm_overrides.json` — previously validated trials are
preserved across runs. For a one-shot full curation of every low-confidence
trial, see the "Curation loop" section of the Methods & Appendix tab inside
the app.

---

## Snapshots

The app can save reproducible snapshots of a live pull:

1. Use the sidebar **Save snapshot** button in live mode.
2. The snapshot (`trials.csv`, `sites.csv`, `prisma.json`, `metadata.json`) is
   written to `snapshots/<YYYY-MM-DD>/`.
3. Switch the sidebar source toggle to **Frozen snapshot** to reload any previous
   snapshot — useful for locking figure data for publication.

Publication CSVs include a `#`-prefixed header block with snapshot date, filter
state, row count, and API source — readable via
`pd.read_csv(path, comment="#")`.

---

## Repository layout

| File | Purpose |
|---|---|
| `app.py` | Streamlit UI, filters, tabs, figures, exports |
| `pipeline.py` | API fetch, tri-level classifier, PRISMA, snapshot I/O |
| `config.py` | Disease ontology, target antigens, products, exclusions |
| `validate.py` | Standalone Claude-powered validation tool |
| `llm_overrides.json` | Generated per-trial classification overrides |
| `snapshots/<date>/` | Reproducible frozen datasets |
| `requirements.txt` | Pinned Python dependencies |
| `LICENSE` | MIT |

---

## Citation

> Jeong P. CAR-T Oncology Trials Monitor [Internet].
> Klinik I für Innere Medizin, Klinische Immunologie und Rheumatologie,
> Universitätsklinikum Köln; 2026.
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
