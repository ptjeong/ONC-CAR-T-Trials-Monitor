# Oncology CAR-T Trials Monitor — Kickoff Brief

Sister app to the Rheumatology CAR-T Trials Monitor. Same architecture, different domain. This document is the starting basis for a fresh session: read it first, confirm the open decisions, then build.

**Source app to mirror:** `Rheumatology-CAR-T-Trials-Monitor-` (this repo). Files to reference: `app.py`, `pipeline.py`, `config.py`, `validate.py`, `.streamlit/config.toml`, `requirements.txt`.

---

## 1. Goal & scope

Build a Streamlit dashboard that tracks CAR-T (and CAR-NK / CAAR-T / CAR-γδ T / in-vivo CAR) clinical trials in **oncology** — both **hematologic** and **solid** tumors — mirroring the visual language, figure set, and methods rigor of the rheumatology app. The product question being answered: *who is running what CAR-T trial, where, in which cancer, with which target, at what development stage.*

**Core UX requirement:** cascading disease filter.

1. **Top-level (Tier 1):** Branch — `Heme-onc` · `Solid-onc` · `Mixed/both`
2. **Mid-level (Tier 2):** Category within the selected branch(es) — e.g. B-NHL, B-ALL, MM, AML in heme; CNS, GI, Thoracic, GU in solid
3. **Leaf (Tier 3):** Specific disease entity — e.g. DLBCL, FL, MCL; or GBM, HCC, Pancreatic

Selecting a Tier-1 branch should narrow Tier-2 options; selecting Tier-2 should narrow Tier-3. Basket trials that enrol across categories appear in every category they touch.

**Non-goals (v1):** response/safety outcomes, biomarkers, dose-level granularity, commercial forecasting. The app classifies and visualises the trial landscape — it is not an outcomes meta-analysis.

---

## 2. Design principles (carry over from rheum app)

- **Flat, NEJM-style aesthetic.** Navy primary, hairline borders, no shadows, white canvas. Re-use `THEME` dict and CSS block from rheum `app.py` verbatim.
- **Single source of truth = ClinicalTrials.gov v2 API.** No scraping, no third-party aggregators.
- **PRISMA-style accounting.** Every exclusion is counted and reportable.
- **Reproducible snapshots.** `save_snapshot` / `load_snapshot` with embedded metadata and PRISMA counts.
- **Auto-generated Methods section.** Prose rebuilt from config and pipeline constants so documentation never drifts from code.
- **LLM-assisted curation loop** with `llm_overrides.json`, Cohen's κ validation sample, and stratified re-review. Mirror the rheum `validate.py` structure.
- **Publication-ready figures.** High-res Plotly exports with consistent captions, sample-size tags, and download buttons.

---

## 3. Repo strategy — recommendation

**Option A (recommended for v1): Separate repo, copy-and-adapt.**

- New repo: `Oncology-CAR-T-Trials-Monitor`
- Copy `.streamlit/`, `requirements.txt`, and the skeletons of `app.py` / `pipeline.py` / `config.py` / `validate.py` from the rheum repo.
- Rewrite domain constants; keep plot code, snapshot I/O, and UI chrome untouched.
- Faster to ship. Acceptable duplication for two apps.

**Option B (later): Extract shared core.**

- Once both apps stabilise, refactor the common pieces (`fetch_raw_trials`, `_flatten_study`, snapshot I/O, theme, figure helpers, PRISMA accounting, curation-loop UI) into a `carttrials-core` package that each app imports.
- Do this only after v1 of the onco app is working — premature abstraction will slow the first build.

**Decision to confirm before building:** Option A vs B. Assume A unless user overrides.

---

## 4. Reuse map (what to copy, fork, rewrite)

| File / block | Action | Notes |
|---|---|---|
| `.streamlit/config.toml` | **Copy verbatim** | Theme is identical. |
| `requirements.txt` | **Copy verbatim** | Same deps. |
| `THEME` dict + CSS block in `app.py` | **Copy verbatim** | Visual identity. |
| `STATUS_OPTIONS`, `STATUS_DISPLAY`, `PHASE_ORDER`, `PHASE_LABELS` | **Copy verbatim** | CT.gov schema, not domain-specific. |
| `_pub_title`, `_pub_header`, `_pub_caption`, `_cagr` | **Copy verbatim** | Figure chrome. |
| `_csv_with_provenance` | **Copy, adapt filter list** | New filter names for cascading disease filter. |
| Figure blocks (Fig 1–7 plot code) | **Copy, re-wire data** | Pie/bar/line/choropleth code is generic; only the grouped column changes. |
| Data-quality expander | **Copy, adapt ambiguous tokens** | Token list changes (see §6). |
| Methods & Appendix tab skeleton | **Copy, rewrite prose in `_build_methods_text`** | Text references oncology ontology, exclusions, query terms. |
| Curation loop / κ validation tools | **Copy verbatim** | Mechanism is domain-agnostic. |
| Snapshot I/O (`save_snapshot`, `load_snapshot`, `list_snapshots`) | **Copy verbatim** | Schema-agnostic. |
| `fetch_raw_trials` structure | **Copy, rewrite `term_query`** | Search string becomes oncology-focused; see §7. |
| `_flatten_study`, `_extract_sites` | **Copy verbatim** | CT.gov response shape unchanged. |
| `_process_trials_from_studies` | **Copy, add `Branch` and `DiseaseCategory` columns** | Hierarchy wiring. |
| `_classify_disease` | **Rewrite** | Tri-level classifier. See §5–§6. |
| `_assign_target` | **Rewrite and expand** | Many more antigens. |
| `_assign_product_type` | **Keep logic, expand named-product list** | More approved and clinical-stage products. |
| `validate.py` | **Copy, replace `VALID_DISEASES` + system prompt** | LLM prompt needs onco framing. |
| `HARD_EXCLUDED_NCT_IDS` | **Start empty, fill via curation loop** | New list for onco false-positives. |
| `EXCLUDED_INDICATION_TERMS` | **Invert** | Rheum excluded *oncology*; onco excludes *autoimmune-only* indications. |
| `DISEASE_ENTITIES`, `_DISEASE_TERMS`, `OTHER_IMMUNE_MEDIATED_TERMS`, `GENERIC_AUTOIMMUNE_TERMS` | **Delete and replace** with onco ontology | Core domain rewrite. |
| `NAMED_PRODUCT_TARGETS`, `NAMED_PRODUCT_TYPES` | **Replace with onco product list** | Large — see §8. |

---

## 5. Oncology disease ontology (v1 draft)

Three-tier hierarchy. Labels shown are the stored values; user-facing display can wrap or relabel.

### Tier 1 — Branch

- `Heme-onc`
- `Solid-onc`
- `Mixed` *(trial straddles both — rare; flag separately rather than force-picking)*

### Tier 2 — Category (within branch)

**Heme-onc**
- `B-NHL` (B-cell non-Hodgkin lymphoma)
- `B-ALL` (B-cell acute lymphoblastic leukemia)
- `CLL_SLL` (chronic lymphocytic leukemia / small lymphocytic lymphoma)
- `T-cell malignancy` (T-ALL, T-LL, T-NHL, PTCL, CTCL)
- `Multiple myeloma`
- `Hodgkin lymphoma`
- `AML`
- `MDS_MPN` (myelodysplastic / myeloproliferative)
- `Heme-onc_other` (rare/unspecified heme)

**Solid-onc**
- `CNS` (GBM, DIPG, medulloblastoma, meningioma)
- `Thoracic` (NSCLC, SCLC, mesothelioma)
- `GI` (HCC, CRC, gastric, pancreatic, cholangio, esophageal)
- `GU` (prostate, RCC, bladder, testicular)
- `Gynecologic` (ovarian, endometrial, cervical)
- `Breast`
- `Head & neck`
- `Skin` (melanoma, Merkel, non-melanoma)
- `Sarcoma`
- `Pediatric solid` (neuroblastoma, osteosarcoma, Ewing, rhabdomyosarcoma) — cross-cuts adult categories; keep as its own Tier 2 bucket for oncology-specific views
- `Solid-onc_other`

### Tier 3 — Entity (leaf)

Specific disease labels. Draft starter set (expect to grow via curation loop):

**B-NHL:** DLBCL, FL, MCL, MZL, Burkitt, PMBCL, PCNSL, Transformed indolent
**B-ALL:** Adult B-ALL, Pediatric B-ALL, Ph+ B-ALL
**CLL_SLL:** CLL, SLL, Richter transformation
**T-cell:** T-ALL, T-LL, PTCL-NOS, AITL, ALCL, CTCL, Sezary
**Multiple myeloma:** Newly diagnosed MM, R/R MM, AL amyloidosis, Smoldering MM, Plasma cell leukemia
**Hodgkin:** Classical HL, NLPHL
**AML:** De novo AML, R/R AML, Secondary AML
**MDS_MPN:** MDS, MPN, CMML

**CNS:** GBM, Anaplastic glioma, DIPG, Medulloblastoma, Ependymoma, Brain metastases
**Thoracic:** NSCLC, SCLC, Mesothelioma
**GI:** HCC, Gastric/GEJ, Pancreatic, Colorectal, Cholangio, Esophageal
**GU:** Prostate, RCC, Bladder
**Gyn:** Ovarian, Endometrial, Cervical
**Breast:** HER2+ breast, TNBC, HR+ breast
**H&N:** HNSCC, Nasopharyngeal
**Skin:** Melanoma, Merkel
**Sarcoma:** Osteosarcoma, Ewing, Synovial, Soft tissue sarcoma
**Pediatric solid:** Neuroblastoma, Rhabdomyosarcoma, Wilms, Retinoblastoma
**Basket:** `Basket/Multidisease` (multi-entity within a branch) · `Advanced solid tumors` (pan-solid basket) · `Heme basket` (pan-heme basket)

**Keep these special labels:**
- `Basket/Multidisease` — ≥2 Tier-3 entities enrolled within one branch
- `Advanced solid tumors` — pan-solid basket trial with no specific tumour type
- `Heme basket` — pan-heme basket trial with no specific disease
- `Unclassified` — CAR-T oncology trial that cannot be sub-classified from available text

---

## 6. Classification algorithm

Mirror `_classify_disease` from rheum, but emit three labels instead of two.

```python
def _classify_disease(row: dict) -> tuple[list[str], str, str, str, str]:
    """Return (entities, design, primary_entity, category, branch).

    entities       — pipe-joined leaf labels (for DiseaseEntities column)
    design         — "Single disease" | "Basket/Multidisease"
    primary_entity — leaf label for charts (DiseaseEntity column)
    category       — Tier 2 label (DiseaseCategory column)
    branch         — Tier 1 label (Branch column) — "Heme-onc" | "Solid-onc" | "Mixed"
    """
```

**Resolution order** (same pattern as rheum):
1. LLM override if present → trust `branch`, `category`, `entity` from override.
2. Check each condition chunk against leaf term map; collect matches.
3. Check full text for leaf terms; union.
4. Derive `category` = set of Tier-2 parents of matched leaves.
5. Derive `branch` = set of Tier-1 parents of matched categories. If both → `Mixed`.
6. Basket detection: ≥2 leaf matches → `Basket/Multidisease` *within the inferred branch*.
7. Category-only match without leaf → return the category as primary entity and flag single-disease.
8. Fall through to branch-only match (e.g. "advanced solid tumors") → branch basket label.
9. Otherwise → `Unclassified` branch=Unknown category=Unknown.

**Exclusion rules (new):**
- Exclude trials where the *only* indication is autoimmune/rheumatologic (mirror of the rheum app's oncology exclusion).
- Keep `HARD_EXCLUDED_NCT_IDS` mechanism — start empty, fill via curation loop.
- Keep exclusion for observational / registry / non-CAR-T immune interventions.

**Ambiguous tokens for the data-quality expander:**
`["unclassified", "car_t_unspecified", "other_or_unknown", "heme-onc_other", "solid-onc_other"]`

---

## 7. Query strategy

Oncology CAR-T has **far more** trials than rheumatology CAR-T — expect 1,500–3,000 active/completed. Implications:

- Raise `max_records` default to 5000 in `build_all_from_api`.
- Paginate via `nextPageToken` (already in rheum code — verify it handles larger result sets).
- Cache aggressively (`@st.cache_data(ttl=3600)`).

**`term_query` for `fetch_raw_trials`:**

```python
term_query = (
    '("CAR T" OR "CAR-T" OR "chimeric antigen receptor" '
    ' OR "CAR-NK" OR "CAR NK" OR "CAAR-T" OR "CAR-Treg" '
    ' OR "gamma delta CAR" OR "CAR gamma delta")'
    ' AND AREA[ConditionSearch] ('
    ' leukemia OR lymphoma OR myeloma OR "multiple myeloma" '
    ' OR "solid tumor" OR "solid tumors" OR glioma OR glioblastoma '
    ' OR hepatocellular OR pancreatic OR gastric OR colorectal '
    ' OR ovarian OR breast OR prostate OR sarcoma OR melanoma '
    ' OR neuroblastoma OR mesothelioma OR carcinoma'
    ')'
)
```

**Exclude up front** trials whose indication is purely autoimmune/rheumatologic — invert the rheum app's `EXCLUDED_INDICATION_TERMS`.

---

## 8. Target antigens (expanded)

`TargetCategory` values — keep the same shape as rheum (single label per trial + dual-target labels) but add oncology-relevant antigens:

**Heme-typical:** `CD19`, `BCMA`, `CD20`, `CD22`, `CD7`, `CD5`, `CD30`, `CD33`, `CD38`, `CD70`, `CD123`, `GPRC5D`, `FcRH5`, `SLAMF7`, `CD79b`, `Kappa-light-chain`

**Solid-typical:** `GPC3`, `Claudin 18.2`, `Mesothelin`, `GD2`, `HER2`, `EGFR`, `EGFRvIII`, `B7-H3`, `PSMA`, `PSCA`, `CEA`, `EpCAM`, `MUC1`, `CLDN6`, `NKG2D ligands`, `ROR1`, `L1CAM`, `CD133`, `AFP`, `NY-ESO-1` (TCR — flag as non-CAR? decide), `MAGE-A4` (same), `IL13Rα2`, `HER3`, `DLL3`

**Dual / multi:** `CD19/CD22 dual`, `CD19/CD20 dual`, `CD19/BCMA dual`, `BCMA/GPRC5D dual`, `BCMA/CD19 dual`, `HER2/MUC1`, `GPC3/MSLN`, etc.

**Platform labels (unchanged):** `CAR-NK`, `CAAR-T`, `CAR-Treg`, `CAR-γδ T` *(Treg/CAAR rare in onco but keep)*

**Unknowns:** `CAR-T_unspecified`, `Other_or_unknown`

**Decision to confirm:** TCR-T products (NY-ESO-1, MAGE-A4, afami-cel) — include or scope out? They are not strictly CAR-T. Recommend **exclude v1** and add a clear Methods note; revisit if users ask.

---

## 9. Named products (starter list)

Seed `NAMED_PRODUCT_TARGETS` and `NAMED_PRODUCT_TYPES` with the approved and late-stage products. This reduces "Unclassified" significantly on day one.

**Approved (US/EU/China, as of 2026-01):**
- `tisagenlecleucel` / `kymriah` → CD19, Autologous
- `axicabtagene ciloleucel` / `yescarta` → CD19, Autologous
- `brexucabtagene autoleucel` / `tecartus` → CD19, Autologous
- `lisocabtagene maraleucel` / `breyanzi` → CD19, Autologous
- `idecabtagene vicleucel` / `abecma` → BCMA, Autologous
- `ciltacabtagene autoleucel` / `carvykti` → BCMA, Autologous
- `obecabtagene autoleucel` / `aucatzyl` → CD19, Autologous
- `relmacabtagene autoleucel` / `carteyva` → CD19, Autologous
- `inaticabtagene autoleucel` → CD19, Autologous
- `equecabtagene autoleucel` / `fucaso` → BCMA, Autologous
- `zevorcabtagene autoleucel` → BCMA, Autologous

**Clinical-stage:** ALLO-501/501A (CD19, allo), ALLO-715 (BCMA, allo), CYAD-01, MB-CART2019.1, anito-cel, GC012F (CD19/BCMA dual), CT053, etc. Fill via curation loop.

---

## 10. Figure set (what changes vs rheum)

Keep the same seven-figure structure; change what's stacked/coloured/sliced:

| # | Figure | Change from rheum |
|---|---|---|
| 1 | Temporal | Stack by `Branch` (Heme vs Solid). Add approved-product overlay (annotations at first-approval years). |
| 2 | Phase | Group by `Branch`, faceted sub-bars by `DiseaseCategory`. |
| 3 | Geography | Same choropleth; add toggle to colour by heme vs solid trial count. Fix `locationmode` to `"ISO-3"` while rebuilding. |
| 4 | Enrollment | Same box/violin; facet by `Branch`. Median enrollment is usually smaller in solid-onc — interesting story. |
| 5 | Disease (Sankey / sunburst) | **New layout:** Branch → Category → Entity sunburst. High-impact visual for this app. |
| 6 | Target | Split into two stacked bars: one for heme targets, one for solid targets. Same top-N treatment. |
| 7 | Innovation | Dual-target / allo / in-vivo adoption over time, split by branch. |

---

## 11. Sidebar filter implementation

Cascading select pattern in Streamlit:

```python
# Tier 1
branch_options = ["Heme-onc", "Solid-onc", "Mixed"]
branch_sel = st.sidebar.multiselect("Branch", branch_options, default=branch_options)

# Tier 2 — derive from df after applying branch filter
df_after_branch = df[df["Branch"].isin(branch_sel)]
category_options = sorted(df_after_branch["DiseaseCategory"].dropna().unique())
category_sel = st.sidebar.multiselect(
    "Disease category", category_options, default=category_options,
    help="Options narrow based on the selected branch(es).",
)

# Tier 3 — further narrow by category
df_after_cat = df_after_branch[df_after_branch["DiseaseCategory"].isin(category_sel)]
_entities = set()
for val in df_after_cat["DiseaseEntities"].dropna():
    _entities.update(e.strip() for e in str(val).split("|") if e.strip())
entity_options = sorted(_entities)
entity_sel = st.sidebar.multiselect(
    "Disease entity", entity_options, default=entity_options,
    help="Basket/multi-disease trials appear under every entity they enrol.",
)
```

Everything downstream (phase, status, target, product, modality, country) stays identical to rheum.

---

## 12. Phased work plan

**Phase 1 — MVP (end-to-end working app, ugly data)**
1. New repo scaffold. Copy `.streamlit/`, `requirements.txt`, `THEME`/CSS, snapshot I/O, CT.gov flatteners.
2. New `config.py` with the ontology from §5 (seed lists; will iterate).
3. New `pipeline.py::_classify_disease` emitting `Branch` / `DiseaseCategory` / `DiseaseEntity`.
4. Minimal `app.py`: data source, cascading filter, PRISMA, one figure (Temporal) + Data tab.
5. Pull live data, eyeball 50 trials, fix obvious misclassifications. **This is the gate for Phase 2.**

**Phase 2 — Parity (match rheum feature set)**
6. All seven figures re-implemented with oncology slices.
7. Methods & Appendix tab with auto-generated text.
8. Data quality expander.
9. `validate.py` adapted; run κ validation on stratified sample of ~200 trials.
10. First snapshot saved.

**Phase 3 — Oncology-specific polish**
11. Sunburst figure (Branch → Category → Entity).
12. Approved-product overlay on temporal figure.
13. Heme-vs-solid side-by-side comparisons where useful (enrollment, phase mix).
14. Deploy to Streamlit Cloud on the same pattern as rheum app.

Do not move to Phase 2 until Phase 1 classifies ≥80% of pulled trials non-`Unclassified` on a spot check. If classification is poor, iterate on config before building more UI.

---

## 13. Open decisions for the new session to confirm

1. **Repo strategy:** Option A (separate repo, copy-and-adapt) vs Option B (extract shared core first). *Default A.*
2. **TCR-T products:** include or exclude? *Default exclude v1.*
3. **Approved-product overlay on temporal figure:** include in Phase 1 or defer to Phase 3? *Default Phase 3.*
4. **Pediatric split:** treat pediatric as its own Tier-2 category under Solid-onc (as drafted), or as a cross-cutting tag on entities? *Default: own category for solid; treat heme pediatric via age-based split if needed.*
5. **Max records:** start at 5000 or go higher? *Default 5000; raise if PRISMA shows truncation.*
6. **Snapshot carry-over:** start fresh (no snapshots) or seed with a first pull? *Default: seed with a first live pull and save snapshot day one.*

---

## 14. First prompt for the fresh session

Paste this into the new session (run from `/Users/peterjeong/Documents/onc-car-t-trials-monitor`):

> I'm starting a sister app to the Rheumatology CAR-T Trials Monitor — an Oncology CAR-T Trials Monitor covering heme-onc and solid-onc.
>
> Read `ONCOLOGY_APP_KICKOFF.md` in this directory. It has the full architecture, ontology, filter design, and phased plan.
>
> A read-only reference copy of the rheum app lives at `./car-t-rheumatology-monitor/` (subfolder of this directory). It contains `app.py`, `pipeline.py`, `config.py`, `requirements.txt`, `README.md`, and `.streamlit/config.toml` — mirrored from the live GitHub repo (https://github.com/ptjeong/Rheumatology-CAR-T-Trials-Monitor-), plus the theme file. Do not edit anything in there. Note: `validate.py` referenced in §4 of the kickoff does not exist in this copy — write it fresh following the pattern described in the kickoff.
>
> Start Phase 1 from §12. Before writing code, confirm with me the open decisions in §13. Then scaffold the onco app in the current directory (not in a subfolder), port the reusable pieces, and implement the tri-level classifier and cascading filter. Stop after Phase 1 step 5 (spot-check the classifier on live data) so we can review before continuing.

---

*End of brief. Maintainer: Peter Jeong. Created 2026-04-24.*