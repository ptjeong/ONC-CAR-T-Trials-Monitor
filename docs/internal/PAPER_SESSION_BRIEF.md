# JCO CCI manuscript — app-side publication-grade data production brief

**Status:** in flight, 2026-04-26 evening sprint.
**Target journal:** Journal of Clinical Oncology Clinical Cancer Informatics (JCO CCI).
**Manuscript scope:** the ONC-CAR-T Trials Monitor as a published methodology paper, presenting the dashboard + the validation infrastructure that backs it.

This brief documents what's being built **app-side** to produce the data, statistics, and provenance needed for a publication-grade methods + results section. Drop into the manuscript Slack / Google Doc / co-author thread.

---

## What we are presenting (one paragraph)

The CAR-T Oncology Trials Monitor is a public Streamlit dashboard that classifies 2 100+ ClinicalTrials.gov entries on six axes (Branch, DiseaseCategory, DiseaseEntity, TargetCategory, ProductType, SponsorType) using a hybrid rule-based pipeline with LLM-assisted overrides. The manuscript presents (1) the classification methodology, (2) a three-layer validation infrastructure (locked benchmark, independent-LLM cross-validation, snapshot-to-snapshot diff), and (3) a community-driven quality-improvement loop (GitHub-Issue-backed flagging with moderator gating). To establish ground-truth performance, we are running a **two-rater inter-rater reliability study** on a pre-registered random sample of 200 trials.

---

## What's already shipped (data + infrastructure ready to cite)

### Three-layer validation infrastructure (already documented in `docs/methods.md`)
1. **Locked regression benchmark** — `tests/benchmark_set.csv`, 25 trials, hand-curated ground truth on every axis. Per-axis F1 reported on every CI run; regression below floor fails CI. Includes pivotal CAR-T approvals + allogeneic + dual-target + CAR-NK + in-vivo CAR + 13 solid-tumour additions covering CNS / GI / pediatric / Gyn / Thoracic / Sarcoma.
2. **Independent-LLM cross-validation** — `scripts/validate_independent_llm.py`. Multi-vendor (Gemini Flash, Llama 3.3 70B/8B via Groq, GPT-4o, Claude Haiku). Stratified sampling. Per-axis Cohen's κ vs the pipeline. Closed-vocabulary prompting (DiseaseCategory list passed to the LLM) — collapsed an early 24% to 70% agreement by removing vocabulary mismatch from the disagreement bucket.
3. **Snapshot-to-snapshot diff** — `scripts/snapshot_diff.py`. Categorises every reclassification between dated snapshots as `expected (LLM override)` / `hard-listed` / `unexplained`. The `unexplained` bucket surfaces pipeline edits with wider blast radius than intended.

### Community classification-flag system (full loop, end-to-end)
Public users click **Suggest a classification correction** on any trial card → opens a pre-filled GitHub issue with structured YAML payload → consensus-detection workflow (`.github/workflows/flag_consensus.yml`) auto-applies `consensus-reached` label after `CONSENSUS_THRESHOLD` reviewer agreements (currently 1; tunable env var) → moderator (PJ) reviews via private Moderation tab in the dashboard → approved corrections promoted to `llm_overrides.json` via `scripts/promote_consensus_flags.py`. **Full audit trail in GitHub Issues, zero auth code in the app.**

Now self-bootstrapping: `auto_label_flags.yml` workflow ensures missing labels are created on the fly so the first flag in any new deployment works without manual setup.

### Per-axis Cohen's κ already wired in the moderation tab
`_cohens_kappa` helper (closed-form, no sklearn dep, anchored against Sim-Wright 2005 BMC textbook example to ±0.01 in unit tests). Live panel in the Moderation tab tracks moderator-vs-pipeline κ as the validation pool grows.

---

## What's being built right now (the headline for the methods section)

### **Two-rater inter-rater κ validation study** (`validation_study/` directory)

**Sample design (pre-registered):**
- N = 200 trials, drawn from the 2026-04-24 snapshot
- Stratified 50% Heme-onc / 50% Solid-onc (excludes Mixed and Unknown — too rare for clean κ at this N)
- Within each branch, ≥ 5 trials per major DiseaseCategory (defined as ≥ 10 trials in source)
- Trials with insufficient text for human classification (no Title / Summary / Conditions / Interventions ≥ 50 chars) excluded prior to sampling
- Locked sample manifest committed at `validation_study/sample_v1.json`
- **sha256 = `61473bd8600c6c2f0b6f1c6827eec6b4a29b699e0d795f0562cbe6470a4fa559`** (record this in the methods section as the pre-registration hash; equivalent to a CT.gov registration before enrollment)

**Stratification breakdown (audit trail):**
| Branch | DiseaseCategory | N |
|---|---|---|
| Heme-onc | B-NHL | 25 |
| Heme-onc | B-ALL, Multiple myeloma, Basket/Multidisease | 15 each |
| Heme-onc | AML, CLL/SLL | 7 each |
| Heme-onc | T-cell | 6 |
| Heme-onc | Heme basket, Hodgkin | 5 each |
| Solid-onc | Advanced solid tumors | 16 |
| Solid-onc | GI, B/M, CNS | 12-15 |
| Solid-onc | GU, Sarcoma | 7-9 |
| Solid-onc | Breast, Gyn | 6 each |
| Solid-onc | H&N, Pediatric solid, Thoracic | 5 each |

**Raters:**
- Rater A: PJ (corresponding author)
- Rater B: clinical collaborator with cellular immunotherapy trial experience (TBC — Peter to identify and invite)
- Both rate independently, blinded to (a) the pipeline's labels and (b) each other's labels

**Rater UX (separate Streamlit app, invitation-only):**
- Token-gated `?token=<unique_token_per_rater>`
- Pretty, calm typography; one trial at a time; ~1100 px content width
- Shows ONLY raw evidence: title, brief summary, conditions, interventions, phase, sponsor, trial design
- Pipeline labels deliberately hidden (no anchoring)
- Six axes with "Unsure" as a first-class option on every axis
- Time-per-trial tracked silently (median + ETA reported to rater for motivation)
- **Garden gamification:** 200-cell grid that blooms as you progress (🪴 → 🌱 → random 🌷🌹🌺🌻🌸); milestone celebrations every 25 trials
- **10-layer data safety architecture** (server-side autosave + git-committed canonical store + crash recovery + visible "last saved" indicator + manual download + auto-prompts every 10 trials + email mailto: template + schema-versioned JSON + atomic writes + non-destructive merge on resume)
- Skip option — recorded as data, not as failure (lets us report skip rate)

**Statistical plan:**
- **Primary outcome:** Pairwise Cohen's κ (PJ vs Rater B) per axis, with 95% CI from 10 000 bootstrap resamples
- **Secondary outcomes:**
  - Agreement of each rater with the pipeline (single-rater κ)
  - Three-way agreement rate (% trials where both raters + pipeline all agree per axis)
  - Confusion matrices per axis per rater pair
  - Rater-specific median time per trial, skip rate
- **Tertiary:** Adjudication round — all disagreed-upon trials reviewed by both raters together; final consensus label assigned. Adjudicated set becomes the gold-standard benchmark used to recompute pipeline F1 on this sample.

**Implementation status:**
- ✅ Sample generator: `scripts/generate_validation_sample.py` (committed, run, sha256 pre-registered)
- ✅ Locked sample: `validation_study/sample_v1.json` (committed)
- ✅ Rater app: `validation_study/app.py` (~700 LOC, syntax-validated, ready for deploy)
- 🔜 Compute κ + bootstrap CI: `scripts/compute_validation_kappa.py`
- 🔜 Adjudication mode in admin view
- 🔜 Methods section text drop-in
- 🔜 Deployment to a separate Streamlit Cloud app + invitation links

**Timeline:**
- Tonight: finish κ analysis script + adjudication mode + commit
- Day 1: Peter deploys validation app, identifies + invites Rater B
- Days 2–4: both raters complete their 200 trials independently (estimated 2–3 hours per rater)
- Day 5: Peter runs `compute_validation_kappa.py` → adjudication round on disagreements → final report
- Day 6–7: Methods + Results sections drafted from output

---

## Numbers / artefacts the manuscript will cite

| Section | What | Source |
|---|---|---|
| Methods §1 | "2 100+ trials classified across six axes" | Live snapshot count (auto-derived) |
| Methods §2 | "Locked benchmark of 25 hand-curated trials covering pivotal approvals + 13 solid-tumour additions" | `tests/benchmark_set.csv` |
| Methods §3 | "Three-layer validation infrastructure" | `docs/methods.md` (already written) |
| Methods §4 | "Pre-registered random sample of 200 trials, stratified by Branch and DiseaseCategory, sha256 `61473bd8…`" | `validation_study/sample_v1.json` |
| Methods §5 | "Two raters independently classified each trial blinded to pipeline output and each other's labels using a custom Streamlit interface" | This brief + `validation_study/app.py` source |
| Methods §6 | "Cohen's κ per axis with 95% bootstrap CI from 10 000 resamples" | `scripts/compute_validation_kappa.py` (pending) |
| Methods §7 | "Disagreements adjudicated by joint review; adjudicated labels = gold-standard benchmark" | adjudication-mode output (pending) |
| Methods §8 | "Community-driven quality improvement: GitHub-Issue-backed classification flags, configurable consensus threshold, moderator approval gate, audit-trailed promotion to LLM-override file" | `app.py` Suggest-correction + Moderation tab + `scripts/promote_consensus_flags.py` |
| Results §A | Per-axis pairwise κ (PJ vs Rater B) with CI | study output |
| Results §B | Per-axis pipeline agreement vs adjudicated gold standard | study output |
| Results §C | Cumulative count of community-flagged → moderator-approved → llm_overrides corrections (over time) | dashboard's open issue history + moderator log |
| Results §D | Confusion matrices per axis | study output |
| Discussion | The classification system is **continuously improving** — every flag promoted is a permanent quality ratchet, every snapshot diff catches drift | n/a — narrative |

---

## Open questions for the writing session

1. **Rater B identity** — who's the clinical collaborator? Need to confirm before the validation study can run. Suggested candidates from the Köln group?
2. **Authorship order** — PJ is corresponding; Rater B contributes substantively to validation; should they appear in the author list (probably yes, mid-position) or in acknowledgments?
3. **Publication scope** — does the manuscript also describe the rheum sister app (cross-citation) or stay strictly oncology? The companion repo is at `github.com/ptjeong/rheum-car-t-trial-monitor`.
4. **Code availability statement** — Zenodo DOI `10.5281/zenodo.19738097` (concept DOI) + the specific commit SHA at submission time. Standard JCO CCI requirement.
5. **κ threshold for "good agreement"** — Landis & Koch (1977) cutoffs (κ ≥ 0.60 = substantial, ≥ 0.81 = almost perfect)? Or McHugh (2012) tighter thresholds (≥ 0.80 for clinical use)? Need to pre-specify before computing.
6. **Sample versioning policy** — if the study extends to v2 (e.g. expanded to 500 trials in a future revision), how do we handle that in the methods? Pre-register both, report v1 as the headline + v2 as exploratory?

---

## Design principles the manuscript should foreground

These are the things that make this work different from a typical "we built a dashboard" paper:

1. **The data is alive.** Snapshot-to-snapshot diff catches pipeline drift at every refresh. The published numbers are reproducible to a specific snapshot date (cited in every CSV export with the classifier git SHA).
2. **The classification is fallible — and the system knows.** Every trial card surfaces a Suggest-correction button. Every flag becomes an audit-trailed GitHub issue. Every approved correction is permanent + provenance-tagged.
3. **Validation is a continuous service, not a one-off.** The benchmark fails CI on regression. The independent-LLM harness re-runs on every release. The two-rater κ study establishes baseline; community flags + moderator approvals improve on it.
4. **Zero auth in the app.** Authentication is delegated to GitHub for flags, to Streamlit secrets for the moderator tab, to invitation tokens for the validation study. The dashboard never holds a credential.
5. **Honest about confidence.** Every classification carries a confidence label (high / medium / low) derived from the strength of the matching evidence. The Methods section explains the confidence calculation; the Results section reports performance stratified by confidence.
6. **Reproducible by construction.** Pre-registered sample (sha256 in commit). Locked benchmark (csv in repo). Snapshot dates on every export. Pipeline classifier SHA on every CSV. CITATION.cff with versioned releases.

---

## What I need from the writing session

1. Confirm Rater B identity (or commit to identifying them this week)
2. Pre-specify the κ thresholds (Landis-Koch vs McHugh — a one-line decision)
3. Confirm Zenodo concept DOI is the right ID for the code-availability statement (it is, but worth confirming with the journal's specific requirements)
4. Decide whether the rheum sister app is cross-cited (probably yes — it's the parallel proof that this framework generalises across indications)
5. Approve the methodology paragraph above (or send edits) so I can drop it into the methods section verbatim once the validation data is in

The infrastructure is ready. The next bottleneck is human time — 2–3 hours from PJ + 2–3 hours from Rater B + ~1 hour adjudication + writing time. Everything else is automated.
