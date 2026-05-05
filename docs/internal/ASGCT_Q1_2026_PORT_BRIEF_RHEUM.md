# Rheum port — ASGCT Q1 2026 cross-check additions

Paste the section between `--- BEGIN PROMPT ---` and `--- END PROMPT ---`
into a fresh Claude Code session in the **car-t-rheumatology-monitor** repo.
Self-contained, no other context needed.

Onc-side commit (reference): `f852daa` ("Classifier: ASGCT Q1 2026
cross-check — KRAS/NY-ESO-1/PRAME + 7 named products"), landed on
the `classifier-asgct-q1-2026` branch as part of a PR.

---

--- BEGIN PROMPT ---

The American Society of Gene & Cell Therapy (ASGCT) Q1 2026 Landscape
Report (April 2026, joint with Citeline / Pharmaprojects-Trialtrove,
data cutoff ~end of March 2026, available at
https://www.asgct.org/uploads/files/general/Landscape-Report-2026-Q1.pdf)
flagged several CAR-T regulatory events in Q1 2026 that are highly
relevant to the autoimmune-CAR-T pipeline this rheum app tracks. The
oncology sister monitor has already incorporated these into its
classifier; please port the rheum-relevant subset.

## Context: ASGCT autoimmune-CAR-T signal

ASGCT explicitly calls out the autoimmune-CAR-T expansion in Q1 2026:

* **SLE is now the #4 most-targeted indication across ALL gene therapies**
  (71 active programs), behind only "Cancer, solid, unspecified" (359),
  "Autoimmune disease, unspecified" (104), and "Cancer, unspecified" (103).
* **CD19 in non-oncology indications: 100 active programs** (up sharply
  YoY) — driven by lupus, scleroderma, MG, IIM.
* **BCMA in non-oncology: 35 programs** — autoimmune plasma-cell-driven
  disease (e.g., refractory MG, AQP4-IgG NMOSD, anti-MAG neuropathy).
* **CAR-T overall non-oncology share: 19%** (up from prior).
* This is the single biggest validation of the autoimmune-CAR-T thesis
  this rheum app is built on. Worth surfacing in the rheum app's
  Methods text or Discussion narrative.

## Concrete Q1 2026 regulatory events to add to the classifier

These products are CAR-Ts being developed for autoimmune indications.
The first three should be added to `CAR_SPECIFIC_TARGET_TERMS` in the
rheum repo's `config.py` (the analogue of the onc repo's
`NAMED_PRODUCT_TARGETS` named-product short-circuit).

### 1. Prulacabtagene leucel — CD19 CAR-T

* Sponsor / target: CD19 autoimmune CAR-T
* Indications: lupus nephritis + SLE (FDA meetings expected Q2 2026)
* Add aliases: `"prulacabtagene leucel"`, `"prulacabtagene autoleucel"`,
  `"prula-cel"` to the `CD19` aliases list in `CAR_SPECIFIC_TARGET_TERMS`.

### 2. Rese-cel — CD19 CAR-T (likely)

* Status: Orphan Drug Designation (Mar 14, 2026) for **pemphigus vulgaris**
* Indication is autoimmune skin disease — clear in-scope for this rheum repo.
* Target: not explicitly disclosed in ASGCT report; likely CD19 (the
  dominant autoimmune CAR-T target) but verify via sponsor press
  release before assigning.
* Add aliases: `"rese-cel"`, `"resecel"` (verify target first).

### 3. NXC-201 — BCMA CAR-T

* Sponsor: Immix Biopharma
* Indication: AL amyloidosis (Breakthrough Therapy Designation Jan 2026)
* AL amyloidosis sits at the heme-onc / autoimmune-rheumatology
  boundary — included in the onc dataset but worth checking whether
  the rheum app surfaces it via systemic-amyloidosis searches.
* Add aliases: `"nxc-201"`, `"nxc201"` to the `BCMA` aliases list.
  (Same construct was previously called HBI0101.)

### 4. WU-CART-007 — CD7 CAR-T (allogeneic)

* Sponsor: Wugen
* Indication: ALL (Breakthrough Therapy Designation Jan 2026)
* Heme malignancy — likely out-of-scope for this rheum repo unless
  cross-classified for some autoimmune T-cell condition. **Do not add
  unless you find a rheum-relevant trial.**

## Audit pass on rheum data

After adding the prulacabtagene-leucel + rese-cel aliases (and
verifying rese-cel's target), re-run the rheum classifier and confirm:

```bash
python3 -c "
import pandas as pd
import pipeline as p
df = pd.read_csv('snapshots/<latest_date>/trials.csv')
new = df.apply(lambda r: p._assign_target(r.to_dict()), axis=1)
mask = (df['TargetCategory'] != new)
print(df[mask][['NCTId', 'BriefTitle', 'TargetCategory']].assign(NewLabel=new[mask]))
"
```

Expected: a small handful of trials (the prulacabtagene + rese-cel
trials, plus any other Q1 2026 entrants) move from `CAR-T_unspecified`
or `Other_or_unknown` to `CD19`.

## Methods text addition (mirrors onc)

Add an "External Comparator and Validation" section to the rheum
app's Methods narrative, citing the ASGCT report. Suggested text
(adapt phrasing to rheum app's existing Methods style):

> The classifier output was cross-checked against the ASGCT/Citeline
> Q1 2026 Gene, Cell, & RNA Therapy Landscape Report
> (https://www.asgct.org/uploads/files/general/Landscape-Report-2026-Q1.pdf,
> data cutoff approximately end of March 2026). The report explicitly
> identifies SLE as the #4 most-targeted gene-therapy indication
> globally (71 programs) and reports 100 active non-oncology CD19
> programs and 35 non-oncology BCMA programs — directly validating
> the autoimmune-CAR-T pipeline this analysis catalogs. ASGCT does
> not disaggregate by autoimmune indication or by per-trial
> autologous/allogeneic split, gaps the present analysis fills via
> direct CT.gov queries with curated CAR-T classification.

## What to skip from the onc port

These onc-only changes do NOT need to be ported to rheum:
* KRAS / NY-ESO-1 / PRAME antigen additions (oncology-specific)
* Qartemi / Hicara / Pulidekai / Anbal-cel / KITE-753 / WU-CART-007
  (oncology indications)

## Commit message suggestion

```
Classifier: ASGCT Q1 2026 cross-check — autoimmune-CAR-T products

Adds CAR-T products with Q1 2026 regulatory events that target
autoimmune indications:
  * Prulacabtagene leucel (CD19, SLE + lupus nephritis)
  * Rese-cel (CD19, pemphigus vulgaris) — verify target
  * NXC-201 / HBI0101 (BCMA, AL amyloidosis)

Methods narrative updated with ASGCT Q1 2026 external-comparator
citation. ASGCT data validates the autoimmune-CAR-T thesis (SLE
#4 most-targeted gene-therapy indication globally, 100 non-onc
CD19 programs, 35 non-onc BCMA programs).
```

--- END PROMPT ---
