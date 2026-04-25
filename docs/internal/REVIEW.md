# REVIEW — CAR-T Oncology Trials Monitor

Date: 2026-04-25 · Repo: ptjeong/ONC-CAR-T-Trials-Monitor · Reviewed at commit `1a9398a`
Snapshot read: `snapshots/2026-04-24/` (2,152 trials; 1,530 heme · 599 solid · 15 unknown · 8 mixed)
Tests: 65/65 passing · Benchmark: 12/12 across 7 axes

---

## Part A — Per-dimension review

### Executive summary

Onc is in better operational shape than rheum on validation infrastructure (three-layer harness shipping real classifier improvements at iteration cadence) and worse on documentation hygiene (README+CHANGELOG+CITATION drifting fast since the last release). The dataset is heme-skewed (71% / 28% / <1% Branch) and the regression benchmark mirrors that skew (11 heme : 1 solid). Pre-preprint, the binding constraint is methods-text accuracy: the auto-generated Methods section under-counts antigens (`16` heme shown vs `22` actual; `25` solid vs `28`) and gets copied verbatim into the manuscript. Top-3 wins to bank: validation feedback loop (11 real fixes in 4 days, regression-tested), per-provider rate pacing infrastructure, fragment+session-state caching architecture (snappy widget interactions). Top-3 risks: stale Methods text → citable misinformation; stale README → onboarding friction; single-snapshot policy with no rollback path.

### Classifier quality — Strong

- 65 unit tests + 12-trial benchmark, both green at HEAD.
- Three-layer validation infrastructure live: `tests/test_benchmark.py`, `scripts/validate_independent_llm.py:1`, `scripts/snapshot_diff.py:1`. Last validation report at `reports/independent_llm_validation.md` (2026-04-25 14:56).
- Post-classification normaliser (`pipeline.py:193`) catches `Branch=Unknown + Category=Basket/Multidisease` incoherence, applied at all 7 return paths in `_classify_disease`.
- 11 real classifier improvements landed since 2026-04-24 from 4 validation iterations (commits `277a9fe`, `3d8cfde`, `76bfbce`).
- Heme antigens: 22 (`config.py:364`); solid antigens: 28 (`config.py:397`); 7 dual combos (`config.py:441`).
- MET disambiguation test (`tests/test_classifier.py:312`) is a model — locks both positive contexts AND a "patients met the criteria" negative case.

Concerns — minor:
- 14 low-confidence LLM-override entries silently ignored (`pipeline.py:84-91` filter to high/medium only). Worth a one-time triage to confirm none are real signal.
- `HARD_EXCLUDED_NCT_IDS` is empty (`config.py:317`: `set()`) but referenced in three docstrings + the methods text + a Methods-tab UI panel (`app.py:4395+`). Either backfill or delete the affordance.

### Scientific rigor & reproducibility — Concern

- CSV provenance headers on 17/19 download buttons via `_csv_with_provenance` (`app.py:1100`). Two miss it: `curation_loop.csv` (`app.py:4477`, has its own header but lacks snapshot/filter context) and `validation sample CSV` (`app.py:4541`, raw `to_csv`).
- Provenance headers contain snapshot date, source URL, filter state, row count. They do NOT contain the classifier git SHA. A reviewer downloading a CSV today and another in six months can't distinguish data drift from classifier drift.
- Methods text drift (severe — copied into manuscripts):
  - `app.py:4137`: "Heme-typical (16): … FLT3, CLL1, CD147" — actual is 22 (today's CD4/CD1a/IL-5 additions missing). Hard-coded count plus hand-maintained list, both wrong.
  - `app.py:4139`: "Solid-typical (25): … CDH17, GUCY2C, GPNMB" — actual is 28 (FAP/MET/FGFR4 missing).
  - `app.py:4183`: "LLM-Assisted Curation Loop (validate.py + llm_overrides.json)" — describes the original 2-round Claude Opus curation. No mention of the new independent-LLM validation harness, the locked benchmark, or snapshot-diff. Methods describes the past, not the present.
- Single snapshot at `snapshots/2026-04-24/`. Saved before commits `277a9fe`/`3d8cfde`/`76bfbce`/`1a9398a`. Snapshot's pipeline labels are *stale relative to current code* — e.g. NCT02862704 in the snapshot is `Branch=Unknown / Category=Unclassified`, but the live classifier (after my llm_overrides patch + GI keyword) returns `Branch=Solid-onc / Category=GI`. This is why `scripts/validate_independent_llm.py` re-classifies live (commit `0cdbf25`).
- `APPROVED_PRODUCTS_LAST_REVIEWED = "2026-04-24"` (`app.py:108`) surfaced in Fig 1 caption. Quarterly review issue template at `.github/ISSUE_TEMPLATE/approvals_review.md`. Good cadence affordance.

### Data freshness & pipeline robustness — OK

- Live mode default with 24h `@st.cache_data` TTL (`app.py:688`). First user of the day pays cold-start; rest get warm cache.
- Frozen-snapshot opt-in via sidebar "Reproducibility — pin a frozen dataset" expander (`app.py:880-924`). Auto-fallback to most recent snapshot on CT.gov 5xx.
- Pipeline post-processing cached via `_post_process_trials` (`app.py:931`); modality vectorised (`app.py:334`); NCTLink baked into `df` once (`app.py:935-942`).
- Cold-start ETL has 8 row-wise `df.apply(lambda r: f(r.to_dict()), axis=1)` calls (`pipeline.py:1015-1045`). Not on rerun hot path but adds 0.5-2s each on 2,500 trials = ~30s cold start on cache miss. Vectorisation candidate.
- Site-level lat/lon backfilled into snapshot via `scripts/backfill_site_geo.py` (one-shot fix for older snapshots predating geoPoint extraction).

### UX & analytics — Strong

- 7 tabs (Overview / Geography / Data / Deep Dive / Publication Figures / Methods & Appendix / About) at `app.py:1465-1467`. Each filters via shared sidebar; downloads provenance-tagged.
- 8 publication figures, all NEJM-flat aesthetic. Color palette compliant — 4 grep hits for `purple|violet|indigo` (`app.py:160, 2386, 2392, 2400`), all in comments documenting removals.
- Captions hardened against filter narrowing — `app.py:3654` ("panels render when each has data"), `app.py:3205` ("when more than one branch is present"), Overview shared color key (`app.py:1581+`) only renders for branches actually present.
- Two `@st.fragment` wraps live: Fig 1 (`app.py:2958`) and Fig 7b (`app.py:3813`). Pill clicks isolated.
- Three remaining widgets that still trigger full reruns: Data tab search + zoom (`app.py:2212-2226`), Geography per-country selectbox (`app.py:1958`). Fragment-wrappable.
- Geography tab redesigned to single merged map (choropleth + open-site dot overlay) with per-provider pacing pills (`app.py:1761-1781`).
- Color-only signalling in Figs 2/3/4/7 (no shape redundancy for branch). Fig 1 mitigates with circle/diamond/square per regulator (`app.py:2917-2918`). Other figures could borrow this for color-blind safety.

### Code health — OK

- 4,823 LOC in `app.py`; 1,203 in `pipeline.py`; 628 in `config.py`. Total ~8,680 across .py files.
- `metric_card()` is a deprecation shim (`app.py:710-714`) forwarding to `st.metric`. Safe to delete.
- `validate.py` (293 LOC) is a Claude-only tool that predates `scripts/validate_independent_llm.py` (581 LOC, multi-provider). Not marked deprecated. README's "Running the LLM validator" section (`README.md:144-156`) only references the old one.
- `ONCOLOGY_APP_KICKOFF.md` at repo root (19KB, 2026-04-24 10:19, untouched since). Likely one-shot kickoff doc that should move to `docs/` or be deleted.
- `car-t-rheumatology-monitor/` sister-app folder at repo root — gitignored (`.gitignore:6`) but present in workdir. Clutter hazard.
- Empty hidden `reports/.Rhistory` accidental file.
- 2 TODO markers (`grep -rn "TODO|FIXME|XXX" --include="*.py"`): `validate.py:53` (sample NCT placeholder, intentional) + the same in a stale .claude/worktrees copy. Effectively zero real TODOs.
- Type hints: good in `pipeline.py` and helper modules, light in `app.py` where Streamlit code is procedural.

### Performance — Strong

- 23 hits for `st.cache_data | st.fragment | session_state.get` in `app.py`. All major hot paths cached.
- Per-provider pacing in independent-LLM script (`scripts/validate_independent_llm.py:142-156`) — Gemini at 12 RPM, Groq at 25 RPM, etc. Fast providers don't get throttled to slow ones' cadence.
- Fail-fast on TPD daily-quota exhaustion (commit `67fbc0d`) — script bails after first 429 from a provider rather than burning 4 minutes on doomed retries.
- Plotly Scattergeo with ~3,000 site dots is SVG (no WebGL alternative for geo). Render is laggy on cold load but mitigated by layer toggle and dot-density cap (1 row per (NCT, Facility, City)).

### Deployment & ops — Concern

- Deployed at https://onc-car-t-trial-monitor.streamlit.app via Streamlit Cloud (CITATION.cff:20).
- CI: `.github/workflows/test.yml` exists, runs Python 3.11 + 3.12 matrix, py_compile + pytest, on push and PR to main. (Confirms claim 1, see Part B.)
- `requirements.txt` (`requirements.txt:1-9`) is missing `google-genai` and `groq` — both required by `scripts/validate_independent_llm.py` at lines 209 (`from google import genai`) and 248 (`from groq import Groq`). A fresh checkout that runs the validation harness gets `ModuleNotFoundError`.
- Single snapshot in `snapshots/` (`2026-04-24/`), gitignored except for that one (`.gitignore:14-15`). No retention policy: when does a citation snapshot get pruned vs kept? No automation creates daily snapshots.
- Secrets: env-var-only (`ANTHROPIC_API_KEY` / `GEMINI_API_KEY` / `GROQ_API_KEY` / nothing committed). `.streamlit/` directory exists; would need a peek at `.streamlit/secrets.toml` if present. SECURITY.md exists (1,711 bytes).
- `git tag -l` returns one tag: `v1.0.0`. Doesn't match CHANGELOG's latest tag `[0.3.0]` — version drift inside the repo.

### Documentation — Concern

- README.md drift catalogue (file:line in REVIEW_2026-04-25.md, abbreviated here):
  - Branch list missing Unknown (`README.md:30`)
  - Heme antigen list missing CLL1, FLT3, CD147, CD4, CD1a, IL-5 (`README.md:33`)
  - Solid antigen list missing CDH17, GUCY2C, GPNMB, FAP, MET, FGFR4 (`README.md:35`)
  - Fig 4 description references removed forest plot (`README.md:47`)
  - Snapshots section describes removed sidebar source toggle (`README.md:162-176`)
  - LLM validator section only references `validate.py` (`README.md:144-156`)
  - Repository layout table omits scripts/, tests/, .github/, llm_overrides.json, reports/ (`README.md:178-190`)
- CHANGELOG.md last entry is `[0.3.0]` (2026-04-24). 30+ commits since are uncatalogued — independent validation layers, classifier fixes, Fig 1 redesign, Geography map merge, live-first data loading, site lat/lon backfill, etc.
- CITATION.cff: `version: "1.0.0"` (line 16) vs CHANGELOG's `[0.3.0]`. `date-released: "2026-04-24"` superseded. `orcid: null  # TODO` open since file creation.
- In-app help text accuracy: per-figure captions are filter-safe (already audited and tightened); the auto-generated Methods text has the antigen-count drift covered above.

### Strategic coherence with the rheum app — OK

- Onc and rheum share ~95% of helpers verbatim (sponsor classification, age parsing, text utils, snapshot I/O, `_term_in_text`, `_match_terms`).
- Divergence points (intentional): heme-vs-solid Branch dimension exists only in onc; modality buckets differ (onc has CAR-NK/CAAR-T/CAR-γδ T heme-relevant; rheum has CAR-Treg primary).
- Both apps now have independent-LLM validation infrastructure but neither has a shared library. Code is copy-pasted; manual sync risk exists.
- Naming conventions match (e.g. `_classify_sponsor`, `_normalize_text`, `_assign_target`, `_assign_product_type`, snapshot folder layout).
- See Part D for cross-app dependencies that need synchronization.

---

## Part B — Confirm / refute table

| # | Claim | Verdict | File:line |
|---|---|---|---|
| 1 | CI exists; matrix Python 3.11+3.12; py_compile + pytest on push/PR to main | **CONFIRM** | `.github/workflows/test.yml:1-39` |
| 2 | `_normalize_text` collapses hyphens to spaces and applies `non hodgkin → nonhodgkin` token-collapse | **CONFIRM** | `pipeline.py:120-134` |
| 3 | Sponsor classification deliberately removes OTHER_GOV → Government default; routes through name heuristic so non-US public hospitals classify as Academic | **CONFIRM** | `pipeline.py:600-613` (note in lines 600-604; map at 606-613; routing via `_ACADEMIC_HINTS` at 615+) |
| 4 | `_normalize_disease_result` post-hook exists, fixes incoherent label combos at exit | **CONFIRM** | `pipeline.py:193-206` |
| 5 | `validate.py` injects a closed-vocab system prompt with VALID_BRANCHES / VALID_CATEGORIES / VALID_DISEASE_ENTITIES / VALID_TARGETS / VALID_PRODUCT_TYPES | **CONFIRM** | `validate.py:113-120` (ranges match: `_make_system` calls at lines 113-120 format the system template with all five VALID_* constants) |
| 6 | `_assign_target` returns a bare string, not a (target, source) tuple. Source-tagging only on `_assign_product_type` | **CONFIRM** | `_assign_target` signature `pipeline.py:396` returns `str`; `_assign_product_type` signature `pipeline.py:451` returns `tuple[str, str]` |
| 7 | CHANGELOG.md, CITATION.cff, SECURITY.md exist at repo root | **CONFIRM** | `ls -la` shows all three at repo root, sizes 6272 / 1731 / 1711 bytes |
| 8 | `scripts/validate_independent_llm.py` is 581 lines with function signatures `_live_pipeline_labels`, `_call_llm`, `_stratified_sample`, `_cohen_kappa` | **CONFIRM** | `wc -l` = 581. Functions at `scripts/validate_independent_llm.py:63, 199, 257, 295` |
| 9 | Onc has no Modality axis (no `_add_modality_vectorized`); rheum does | **REFUTE** | Onc fully has the Modality axis. `_modality(row)` at `app.py:303`; `_add_modality_vectorized` at `app.py:334`; `MODALITY_ORDER` imported `app.py:49`; sidebar filter `app.py:1055-1058`; figure Fig 7b uses `app.py:3801+` |
| 10 | Onc has no sub-family classifier, no L1-promotion, no audit panel split | **CONFIRM with caveat** | No `_promote_to_L1`/`subfamily` functions found via grep. Catch-all buckets DO exist (`Heme-onc_other` / `Solid-onc_other` categories in `config.py:13-58`; `Other_or_unknown` / `CAR-T_unspecified` targets at `pipeline.py:448, 444`). Audit affordance exists as the "Curation loop — unclear / unclassified trials" panel `app.py:4407+`. The *infrastructure to surface ambiguous catch-all trials* exists; the *L1-promotion automation* does not. |

---

## Part C — Cross-pollination decisions

For each: **decision** · **cost** · rationale.

### C1 — Adopt rheum's source-tag tuple return on `_assign_target`

**DEFER · M (~6h including test rewrite)**

Current signature `_assign_target(row) -> str` (`pipeline.py:396`). Promoting to `tuple[str, str]` would mirror `_assign_product_type` and let the Data tab display target-source provenance (named-product vs LLM-override vs keyword vs default). Rationale to defer: ~25 unit tests in `tests/test_classifier.py` assert against the bare-string return (lines 169, 175, 180, 186, 191, 200-228, 283-338) — every one needs updating. Pipeline call-sites (1) at `pipeline.py:1033`. Rheum should ship it first since they conceived it; onc adopts after seeing the marginal value vs the test-rewrite cost. **[blocked by rheum]**

### C2 — Adopt rheum's sub-family classifier + L1 promotion + audit panel split

**DEFER · L (~3 days)**

Onc has 374 trials sitting in catch-alls (`Other_or_unknown` 211 + `CAR-T_unspecified` 163 = 17% of dataset). Rheum's L1-promotion mechanism would auto-route some of these once a critical mass of evidence accrues. Onc already has the curation panel (`app.py:4407+`) but lacks the auto-promotion layer. Defer: rheum should prove the value at their scale (smaller dataset) before onc commits. The 3-tier ontology already gives pretty good resolution; the catch-all percentage is high but most are genuine ambiguity (CAR-T trial with antigen not disclosed) that no rule-based promotion will fix. The independent-LLM loop is already chipping away at these one trial at a time. **[blocked by rheum]**

### C3 — Add a Modality axis to onc

**DON'T · S (zero work)**

Refuted in Part B #9. Onc has had the Modality axis since at least commit `4213922` ("Add Deep Dive tab, age/sponsor/confidence filters, classifier tests, CHANGELOG"). Eight modality buckets: Auto CAR-T / Allo CAR-T / CAR-T (unclear) / CAR-γδ T / CAR-NK / CAR-Treg / CAAR-T / In vivo CAR (`app.py:303-323`). Filter is wired into the sidebar at `app.py:1055-1058` and used in Fig 7b. The CAR-NK/CAAR-T/in-vivo distinction is genuinely meaningful in onc — heme/solid is not the only binary that matters. Already done.

### C4 — Extract a shared `cart-trials-core` package

**DEFER · L (~5 days, plus indefinite ongoing maintenance burden)**

Honest surface for shared package: text utilities (`_normalize_text`, `_term_in_text`, `_match_terms`, `_contains_any`), sponsor classification (`_classify_sponsor` + the helpers + `_PERSON_DEGREE_MARKERS`), age parsing (`_age_to_years`, `_age_group`), snapshot I/O (`save_snapshot`, `load_snapshot`, `list_snapshots`), `scripts/snapshot_diff.py`, `scripts/validate_independent_llm.py`. Roughly 1,500 LOC. Deliberately keep separate per-app: `ENTITY_TERMS`, `CATEGORY_FALLBACK_TERMS` (different ontologies), `_classify_disease` body (branch logic differs), `app.py` UI (figures differ), `_modality` (buckets differ). Defer: extraction is premature when both apps are still actively iterating. The current copy-paste pattern with manual sync (writing reciprocal briefs after each side ships something) is acceptable for a 2-app dev team. Reconsider after both papers ship and the shared surface stabilises. **[blocks both]**

### C5 — Adopt rheum's broader benchmark (~25 trials)

**DO · M (~4h)**

Onc's `tests/benchmark_set.csv` is 12 trials, 11 heme + 1 solid. Solid-tumour classifier regressions are silently uncatchable. Mirror rheum's expansion shape: target ~25 trials including (a) one trial per major disease entity, (b) one negative-case trial (hard exclusion), (c) one Unclear-ProductType trial. Concrete onc adds: GD2 neuroblastoma pivotal, CLDN18.2 gastric (CT041/satri-cel), GPC3 HCC (Carsgen), MSLN ovarian, HER2 breast, EGFRvIII GBM, FAP mesothelioma (today's addition), FGFR4 rhabdomyosarcoma (today's addition), one off-scope trial for the hard-exclude path, one trial where ProductType genuinely cannot be inferred. Aligns with rheum's shape and closes the heme-skew gap. Independent of rheum schedule. Already in onc's roadmap (Phase 1 #2 in `REVIEW_2026-04-25.md`).

---

## Part D — Roadmap with cross-app dependency flags

### Phase 1 — Pre-preprint (1–2 weeks)

Items below block manuscript submission.

1. **Live-derive Methods-text antigen counts** · S · high · `app.py:_build_methods_text` lines 4137-4141. Replace hard-coded `(16)` / `(25)` with `len(HEME_TARGET_TERMS)` / `len(SOLID_TARGET_TERMS)` and replace enumerated lists with `", ".join(sorted(... .keys()))`. Add regression test that rendered text contains every antigen key. Independent.
2. **Methods-text validation-loop section rewrite** · M · high · `app.py:4183+` describes only the 2-round Claude Opus curation. Rewrite to mention the independent-LLM harness (different vendor for genuine independence), the locked benchmark, and the snapshot-diff. Independent.
3. **Pin `google-genai` + `groq` in `requirements.txt`** · S · high · `requirements.txt:1-9`. Closes the fresh-checkout-can't-run-validation gap. Independent.
4. **Mark `validate.py` as deprecated** · S · high · 5-line docstring at top pointing to `scripts/validate_independent_llm.py`. Same note in `README.md:144-156`. Independent.
5. **CITATION.cff bump** · S · med · `version: "0.4.0"` (or whatever the next manuscript-citable version is); `date-released: 2026-04-25`. Resolve `orcid: null` TODO. Independent.
6. **CHANGELOG `[0.4.0]` entry** · M · med · One unreleased section summarising 30+ commits since `[0.3.0]`. Cite the validation infrastructure as the headline addition. Independent.
7. **Bump benchmark to ~25 trials with solid-onc coverage** · M · high · `tests/benchmark_set.csv`. See Part C5. Catches solid regressions. Independent.
8. **README rewrite to current state** · M · high · branch list, antigen lists (programmatic dump or accept maintenance burden), Fig 4 description, Snapshots section, LLM-validator section, repository-layout table. Independent.

### Phase 2 — Post-preprint hardening (1–2 months)

9. **Embed classifier git SHA in CSV provenance headers** · S · high · `app.py:_csv_with_provenance` line 1100. One-line `subprocess.check_output(["git", "rev-parse", "--short", "HEAD"])` (already used by `_git_version` at `app.py:4632`). Self-documenting downloads. Independent.
10. **Snapshot retention policy + pruning** · M · med · `docs/snapshots.md` defining "citation snapshots preserved indefinitely (marked with KEEP file); daily working snapshots pruned to 14 days." `scripts/prune_snapshots.py`. Independent.
11. **Audit the 14 silenced low-confidence LLM overrides** · S · med · `llm_overrides.json` filter `confidence == "low"`. Either re-curate or document. Independent.
12. **Decide HARD_EXCLUDED_NCT_IDS fate** · S · low · `config.py:317`. Either backfill ~10-20 trials or delete the affordance + adjust methods text. Independent.
13. **Wrap remaining interactive widgets in `@st.fragment`** · M · med · Data tab search+zoom (`app.py:2212-2226`); Geography per-country selectbox (`app.py:1958`). Same pattern as Fig 1 / Fig 7b wraps. Independent.
14. **Schedule the validation loop in CI** · M · high · GitHub Action `.github/workflows/independent_llm.yml` running weekly: `python scripts/validate_independent_llm.py --n 100 --providers groq --model llama-3.1-8b-instant` (TPD-friendly). Commit report; auto-issue if any axis κ drops below floor. Independent.
15. **Vectorise `_process_trials_from_studies`** · L · med · `pipeline.py:1015-1045` has 8 row-wise `df.apply` calls. Replace with vectorised pandas ops. Cold-start drops from ~30s to ~5s for 2,500 trials. Property-test parity. Independent.

### Phase 3 — Strategic (3–6 months)

16. **Extract `cart-trials-core` shared package** · L · med · See Part C4. **[blocks both]** — only happens after both apps stabilise the shared surface.
17. **Adopt source-tag tuple on `_assign_target`** · M · low-med · See Part C1. **[blocked by rheum]** — adopt after rheum ships and proves marginal value.
18. **Sub-family classifier + L1 promotion** · L · med · See Part C2. **[blocked by rheum]**.
19. **Solid-tumor classifier focused audit** · L · high · Run independent-LLM with `--branch solid` filter (new flag) sampling only Branch=Solid-onc. Triage and ship resulting fixes. Closes the heme-bias of the validation loop itself. Independent.
20. **Two-LLM consensus reliability column in Data tab** · L · med · Once both Gemini and Groq runs complete on the same sample, surface `IndependentReviewStatus` per trial: `consensus_pipeline` / `consensus_dissent` / `single_dissent` / `not_reviewed`. Permanent triage list in the UI rather than only in markdown reports. Independent.
21. **Ontology-snapshot pinning per-paper** · M · med · `save_snapshot` also serialises `config.py`'s ENTITY_TERMS / target tables alongside trials.csv. Reviewer 2 years later can re-classify with the *exact* rules at publication time. Independent.

### Cross-app dependency summary

| Item | Flag | Rationale |
|---|---|---|
| C1 / Phase 3 #17 | **[blocked by rheum]** | Rheum should ship the source-tag tuple first; onc adopts |
| C2 / Phase 3 #18 | **[blocked by rheum]** | Rheum should prove L1-promotion at their scale first |
| C4 / Phase 3 #16 | **[blocks both]** | Extraction must follow stabilisation of both apps |
| Phase 1 #1-#8, Phase 2, Phase 3 #19-#21 | independent | Onc ships these on its own clock |

---

## Out of scope / explicit non-recommendations

- Mobile / responsive treatment. Streamlit's column collapse on narrow viewports is fine for tables; the side-by-side map+bar layouts (Geography per-country) will look cramped on phones. Acceptable for a research dashboard. Defer until reviewers raise it.
- Migration off Streamlit Cloud. Free tier is adequate; scale is bounded; deployment cost is zero. No reason to change.
- Pivots away from heme + solid CAR-T scope. Settled.
- Wholesale rewrite of `app.py` (4,823 LOC). Incremental refactors only.
- Adding live data loading (already there, 24h cache).
- Adding validation infrastructure (already there: benchmark + independent-LLM + snapshot-diff).
- TCR-T scope expansion (explicit out-of-scope per README).

---

## Part E — Open questions for the human

1. **Preprint submission horizon** — when does the manuscript hit medRxiv? Determines whether Phase 1 is a 1-week sprint or a 4-week slog.
2. **κ acceptance threshold for the validation loop** — currently we react per-disagreement. Should we set explicit floor (e.g. "if κ for any axis drops below 0.50, halt CI")? What floor per axis?
3. **Snapshot lifecycle** — daily, weekly, per-paper? Should the validation script auto-save a snapshot tagged with its run date so each run is traceable?
4. **Mobile support** — defer indefinitely, or treat as a v2 feature? Current behaviour is "works but ugly" on phones.
5. **Hard-excluded NCT list** — keep the affordance and backfill from manual curation, or delete entirely and let LLM-curation be the only exclusion path?
6. **`validate.py` deprecation** — soft-deprecate (docstring warning) or hard-remove from the repo? It's still functional and was the basis of the curation that produced today's `llm_overrides.json`.
7. **Cross-app convergence direction** — is rheum the canonical source for shared abstractions (it's smaller, simpler), or onc (it's more battle-tested on validation infrastructure)? Both can't be canonical for the same things.
8. **Snapshot-vs-live staleness** — should the snapshot be auto-rebuilt every time `pipeline.py` or `config.py` changes? Currently NCT02862704's snapshot label is `Unknown/Unclassified` while the live classifier returns `Solid-onc/GI`. The validation harness re-classifies live to bypass this; the dashboard does not.
9. **Author cadence on `[blocked by rheum]` items** — does Peter want to explicitly ship `_assign_target` source-tag and L1-promotion on the rheum side first, then port? Or should onc go first and rheum follow?
10. **REVIEW.md vs REVIEW_2026-04-25.md** — both files exist now at repo root. Same review, different templates. Keep both? Move the older one to `docs/`? Delete one?

---
