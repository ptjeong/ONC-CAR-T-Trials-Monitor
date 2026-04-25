# Methods detail — CAR-T Oncology Trials Monitor

Canonical methodology reference for manuscripts citing the dashboard. The
in-app Methods & Appendix tab generates the equivalent text dynamically
from the live config; this static file pins the methodology at a
specific repository revision so a manuscript citation remains stable
across future code changes.

**Cite as**: Jeong P. *CAR-T Oncology Trials Monitor — Methods detail*.
Universitätsklinikum Köln, 2026. Available at
`https://github.com/ptjeong/ONC-CAR-T-Trials-Monitor/blob/v0.4.0/docs/methods.md`
(or pin to whatever release tag the manuscript references).

For the underlying software, cite the Zenodo concept DOI
[10.5281/zenodo.19738097](https://doi.org/10.5281/zenodo.19738097)
plus the snapshot date used in the analysis (visible in every
provenance-tagged CSV export).

---

## 1. Data source and search strategy

Clinical trial records were retrieved from the ClinicalTrials.gov public
registry via the v2 REST API (https://clinicaltrials.gov/api/v2/studies).

A deliberately broad query was applied using only CAR-based
cell-therapy terms ("CAR T", "CAR-T", "chimeric antigen receptor",
"CAR-NK", "CAR NK", "CAAR-T", "CAR-Treg", "gamma delta CAR",
"CAR gamma delta"). No `AREA[ConditionSearch]` restriction was applied,
so trials registered under generic labels such as "Hematological
Malignancies", "Neoplasms", "B-Cell Malignancies" or "Cancer" — which
specific-disease keyword queries miss — are captured. Scope is enforced
downstream by the three-tier classifier and the autoimmune-exclusion
filter (Section 3). No restriction was placed on study phase,
recruitment status, or geographic location at the query stage.

## 2. Inclusion criteria

Studies were included if they:

1. described a CAR-based cellular therapy: CAR-T (autologous, allogeneic,
   or in vivo), CAR-NK, CAAR-T, CAR-Treg, or CAR-γδ T;
2. targeted a hematologic or solid malignancy.

No restriction was applied to study phase, sponsor type, or country.

TCR-T products (e.g., afami-cel, NY-ESO-1-directed TCRs) are explicitly
out of scope for the present version of the dashboard.

## 3. Exclusion criteria

Studies were excluded if they met any of the following criteria:

1. The NCT identifier appeared on a curated hard-exclusion list OR on
   the LLM-generated exclusion list (Section 4.4). Excluded categories
   include: non-CAR-T interventions (bispecifics, monoclonal antibodies,
   chemo / TKI, TIL, TCR-T, mRNA vaccines), supportive-care or
   patient-reported-outcome studies, long-term follow-up registries,
   observational / biomarker / device trials, and out-of-scope
   indications (COVID-19, non-malignant blood disorders,
   transplant-rejection prophylaxis).
2. Text fields (`conditions`, `briefTitle`, `briefSummary`,
   `interventions`) contained one or more of 44 predefined autoimmune /
   rheumatologic keywords AND no oncology-adjacent hit. This is the
   inverse of the sister rheumatology dashboard
   (https://github.com/ptjeong/Rheumatology-CAR-T-Trials-Monitor-);
   a trial with both autoimmune and oncology indications is *retained*
   on the oncology side.

## 4. Hybrid classification architecture

The classifier combines deterministic rule-based matching, named-product
lookups, calibrated defaults, and a two-layer LLM mechanism (initial
curation + ongoing independent cross-validation). Resolution order for
each trial:

### 4.1 Disease classification (`Branch` / `Category` / `Entity`)

1. **LLM override** — if the trial's NCT ID has an entry in
   `llm_overrides.json` with confidence `high` or `medium`, the override
   is trusted wholesale.
2. **Per-chunk leaf matching** — the `conditions` field is split on `|`;
   each chunk is matched against `ENTITY_TERMS`. If a chunk matches no
   leaf, it is matched against `CATEGORY_FALLBACK_TERMS` (generic
   tumor-type wordings) for a category-level signal. ≥2 distinct
   categories detected across chunks → `Basket/Multidisease`.
3. **Full-text leaf matching** — same `ENTITY_TERMS` matching on the
   concatenated text of `conditions | title | summary | interventions`.
4. **Branch-level basket fallbacks** — `HEME_BASKET_TERMS` /
   `SOLID_BASKET_TERMS` for trials where no specific entity matched but
   a branch-level basket descriptor is present.
5. **Fall-through** — `Branch=Unknown / Category=Unclassified`.

Word-boundary regex matching is used for all term lengths. This
prevents prefix collisions (e.g., `EGFR` vs `EGFRvIII`,
`CD19` vs `CD190`, `hodgkin` vs `non-hodgkin`).

A post-classification normaliser catches logically incoherent
combinations (e.g., `Branch=Unknown + Category=Basket/Multidisease` is
incoherent because basket implies multi-category coverage; promoted to
`Branch=Mixed`).

### 4.2 Antigen target classification

1. LLM override (same precedence as disease).
2. Named-product short-circuit (`NAMED_PRODUCT_TARGETS`) maps approved
   and late-stage products to their disclosed antigen (tisa-cel,
   axi-cel, brexu-cel, liso-cel, ide-cel, cilta-cel, obe-cel,
   relma-cel, eque-cel, zevor-cel, GC012F, CT041 / satri-cel, MT027,
   HBI0101, ALLO-501/715, …).
3. Platform detection — CAR-NK, CAAR-T, CAR-Treg, CAR-γδ T (text-level
   match with word-boundary enforcement).
4. Antigen detection across 22 heme-typical antigens (CD19, BCMA, CD20,
   CD22, CD5, CD7, CD30, CD33, CD38, CD70, CD123, GPRC5D, FcRH5, SLAMF7,
   CD79b, Kappa LC, FLT3, CLL1, CD147, CD4, CD1a, IL-5) and 28
   solid-typical antigens (GPC3, Claudin 18.2, Mesothelin, GD2, HER2,
   EGFR, EGFRvIII, B7-H3, PSMA, PSCA, CEA, EpCAM, MUC1, CLDN6, NKG2D-L,
   ROR1, L1CAM, CD133, AFP, IL13Rα2, HER3, DLL3, CDH17, GUCY2C, GPNMB,
   FAP, MET, FGFR4).
5. Dual-target combos (7 explicit pairs): CD19/CD22, CD19/CD20,
   CD19/BCMA, BCMA/GPRC5D, BCMA/CD70, HER2/MUC1, GPC3/MSLN.
6. Residual: `CAR-T_unspecified` (CAR mentioned but antigen not in
   public text) or `Other_or_unknown` (no CAR-T confirmation).

### 4.3 Product type classification with calibrated default

Labels: `Autologous` / `Allogeneic/Off-the-shelf` / `In vivo` /
`Unclear`. Resolution order:

1. LLM override.
2. `in vivo` in the title; or `IN_VIVO_TERMS` in combined text
   (circular RNA, mRNA-LNP, lentiviral nanoparticle, vivovec).
3. Explicit autologous markers: `autoleucel`, `autologous`.
4. Explicit allogeneic markers: `UCART`, `off the shelf`,
   `universal CAR-T`, `universal CD19`, `healthy donor`,
   `donor-derived`, `allogenic` (single-`e` variant common in Chinese
   trial titles).
5. Named-product lookup (`NAMED_PRODUCT_TYPES`).
6. Weak autologous / allogeneic keywords (`ALLOGENEIC_MARKERS`,
   `AUTOL_MARKERS`).
7. **Calibrated default** — if the trial is confirmed as CAR-T but no
   product-type marker surfaces, default to `Autologous`. This is a
   calibrated choice: autologous cells are the dominant modality in
   the current CAR-T landscape (~85% of approvals and ongoing trials).
   Each assignment carries a `ProductTypeSource` tag
   (`explicit_autologous`, `named_product`,
   `default_autologous_no_allo_markers`, `weak_autologous_marker`,
   `llm_override`, `no_signal`) so downstream analyses can distinguish
   high-signal from inferred labels.

### 4.4 LLM curation and validation infrastructure

The deterministic rule layer is supplemented by two LLM mechanisms,
treated as conceptually separate:

**Initial curation** (Claude Opus, 2-round, recorded in
`llm_overrides.json`). The Methods & Appendix tab exports
`curation_loop.csv` listing every trial flagged as
`Branch=Unknown` OR `DiseaseEntity=Unclassified` OR
`TargetCategory ∈ {CAR-T_unspecified, Other_or_unknown}` OR
`ProductType=Unclear`. A batched subagent workflow processed each
flagged trial; results were merged into `llm_overrides.json`. Each
entry contains `nct_id`, `branch`, `disease_category`,
`disease_entity`, `target_category`, `product_type`, `exclude`,
`exclude_reason`, `confidence`, and a free-text `notes` field. Only
entries with confidence `high` or `medium` are honoured by the
pipeline; entries flagged `exclude=true` are dropped at the PRISMA
hard-exclusion stage alongside the manually curated hard-exclusion
list.

**Ongoing independent cross-validation**
(`scripts/validate_independent_llm.py`). Stratified samples of N
trials are sent to a non-Claude LLM — Gemini 2.5 Flash Lite, Llama 3.3
70B / 8B Instant via Groq, or others — for blind re-classification.
Choosing a different vendor breaks the Claude-curates-Claude agreement
bias of the initial curation. The script computes per-axis Cohen's κ
between the live pipeline output and the independent reviewer; trials
where every reviewer agrees on a label different from the pipeline
appear in a "consensus disagreements" section of the output report.
This is the highest-signal triage list because two independent vendors
converging on the same non-pipeline label cannot be one model's quirk.
Per-provider rate pacing (Gemini 12 RPM, Groq 25 RPM by default) and
fail-fast detection of daily-token-quota exhaustion enable sustained
free-tier operation. The script re-classifies each sampled row through
the *current* pipeline before comparison, so post-hoc classifier fixes
are reflected in the metrics immediately rather than waiting for a
fresh snapshot.

### 4.5 Classification confidence

Every trial carries a `ClassificationConfidence` label
(`high` / `medium` / `low`) combining LLM-validation status and rule
strength:

- **high** — LLM-validated OR explicit markers + known branch / entity
  / target.
- **medium** — default rules (Autologous fallback) OR unclear antigen
  target but known branch / entity.
- **low** — `Branch=Unknown` OR `DiseaseEntity=Unclassified` (rare
  after the LLM curation layer).

Surfaced as a sidebar filter and a column in the Data tab so analyses
can be restricted to high-confidence rows.

## 5. Sponsor classification

Lead sponsors are routed to one of four buckets — `Industry`,
`Academic`, `Government`, `Other` — via a hierarchical heuristic that
combines `LeadSponsorClass` (CT.gov's enum) with keyword matching on
the sponsor name. Resolution order:

1. **Strong government signals** — word-boundary acronyms (`NIH`, `NCI`,
   `FDA`, `EMA`, `DOD`, `VA`, `CDC`) and full-phrase anchors
   ("National Institutes of Health", "Department of Veterans Affairs").
   These override academic markers because agencies like NCI are
   genuine federal funders despite containing the word "institute".
2. **Strong academic markers** — hospital, university, medical center,
   cancer center, klinik, affiliated hospital, PLA hospital, and named
   institutions (Memorial Sloan, Dana-Farber, MD Anderson, …). These
   override CT.gov's `OTHER_GOV` class, which over-applies to Chinese
   provincial hospitals and Russian "Federal Research Institute"
   entries that function academically.
3. **CT.gov class map** for unambiguous codes: `INDUSTRY → Industry`,
   `NIH / FED → Government`, `INDIV → Academic`. `OTHER_GOV` is
   deliberately dropped (an audit reduced misclassified `Government`
   entries from 147 to 36 genuine NCI cases).
4. **Known pharma brand names** without a corporate suffix (Novartis,
   Kite, Gilead, Janssen, Legend, Autolus, …).
5. **Industry corporate suffixes / language keywords** (`Inc`, `GmbH`,
   `AG`, `S.p.A`, `Pharma`, `Biotech`, `Therapeutics`, …).
6. **Secondary academic hints** — "Institute of …", "Research
   Institute", Inserm, provincial, fondazione.
7. **PI detection** (`_looks_like_personal_name`) — investigator-
   initiated trials where the sponsor field is the principal
   investigator's name (with optional degree markers like "M.D.",
   "Ph.D.") get explicit routing to `Academic`.
8. **Default to `Academic`** for non-empty unclassified names
   (overwhelmingly investigator-initiated in practice). `Other` is
   reserved for truly empty strings.

## 6. Cell-therapy modality

Each trial is assigned to one of eight mechanistically distinct
modality categories: `Auto CAR-T`, `Allo CAR-T`, `CAR-T (unclear)`,
`CAR-γδ T`, `CAR-NK`, `CAR-Treg`, `CAAR-T`, `In vivo CAR`. Modality is
derived from `TargetCategory` + `ProductType` + text-level γδ-T
detection.

## 7. Enrollment analysis

Planned enrollment counts were extracted from the CT.gov
`EnrollmentCount` field (type = `Anticipated` or `Actual`) and coerced
to numeric; missing or non-numeric values were excluded from
enrollment analyses. To remove data-entry artefacts (registry
placeholders such as `99,999,999`; real-world-data cost studies with
160,000+ rows), enrollment is capped at 1,000 patients — a threshold
safely above the largest prospective CAR-T trial (cilta-cel
CARTITUDE, n ≈ 790). Excluded outliers are reported in a caption.

Figure 4 presents a three-panel enrollment landscape:

- **4a** — Branch-stratified trial-size composition across five clinical
  buckets: Dose-escalation (≤ 20), Small cohort (21–50), Expansion
  (51–100), Mid-size (101–300), Pivotal (> 300). Rendered as a
  100%-stacked horizontal bar (one bar per branch, single-hue
  sequential navy ramp so bucket order is pre-attentively readable).
- **4b** — Median planned enrollment by Phase × Branch.
- **4c** — Per-trial enrollment dot plot, phase-ordered.

## 8. Validation and reproducibility

Three complementary validation layers ship with the repository:

1. **Locked regression benchmark** (`tests/benchmark_set.csv` +
   `tests/test_benchmark.py`). 25 hand-curated pivotal trials —
   12 hematologic and 13 solid-tumor — with verified ground truth
   across `Branch`, `DiseaseCategory`, `DiseaseEntity`,
   `TargetCategory`, `ProductType`, `Modality`, and `SponsorType`.
   Per-axis F1 floor enforced; CI fails on regression. Every classifier
   change is checked against this benchmark before merge.
2. **Independent-LLM cross-validation** (Section 4.4).
3. **Snapshot-to-snapshot diff** (`scripts/snapshot_diff.py`).
   Compares two dated snapshots and categorises every reclassification
   as `expected (LLM override)` / `hard-listed` / `unexplained`. The
   `unexplained` bucket surfaces pipeline / config edits with wider
   blast radius than intended.

## 9. Data processing

All processing is performed in Python (pandas) using a custom ETL
pipeline. Text normalisation includes lowercasing, Unicode
normalisation, `R/R → "relapsed refractory"` expansion,
hyphen-to-space conversion (so "b-cell", "chromosome-positive" match
the space-separated forms), and `non hodgkin → nonhodgkin` collapse to
prevent `hodgkin lymphoma` matching inside `non-Hodgkin lymphoma`
context. Term matching uses whole-word boundary regex for all term
lengths, so prefix collisions (e.g., EGFR vs EGFRvIII) do not produce
false positives. Classification rules, term dictionaries, and named-
product lookups are versioned in `config.py` and iteratively updated
via the validation loop.

## 10. Reproducibility artefacts

Each CSV export from the dashboard carries a `#`-prefixed provenance
header recording:

- Snapshot date (when the underlying CT.gov data was retrieved)
- Source URL (CT.gov v2 API base)
- Live-fetch vs pinned-snapshot indication
- Active filter state (every sidebar filter)
- Row count
- **Classifier git SHA** — the short revision of the pipeline code
  that produced the labels

A reviewer downloading any export can join (snapshot date, classifier
git SHA) to deterministically reproduce the classification by checking
out the exact code revision and replaying.

Dated snapshots (`snapshots/<YYYY-MM-DD>/`) ship as four files:
`trials.csv` (per-trial classifications), `sites.csv` (site-level
records with lat/lon), `prisma.json` (PRISMA-flow counts), and
`metadata.json` (snapshot date, API base, filter state at save time).
The bootstrap snapshot (`snapshots/2026-04-24/`) is committed to the
repository so a fresh deployment has a fallback when the CT.gov API
is unreachable on first load.

---

*This document pins the methodology at repository tag `v0.4.0`.
Subsequent revisions of the dashboard may change behaviour; cite the
specific tag your manuscript references.*
