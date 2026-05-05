# Systematic named-product classification audit — reusable prompt

Paste this into a fresh Claude Code session (or pair-program with it) any
time you want to verify the CAR-T product classifier hasn't regressed,
discover misclassified trials, or evaluate a fresh snapshot before
publishing.

The audit infrastructure lives at:
- `scripts/audit/known_products.py` — curated knowledge base (38+ products)
- `scripts/audit/named_product_audit.py` — runs the comparison

---

--- BEGIN PROMPT ---

# Task

Run a thorough, systematic named-product classification audit on the
ONC CAR-T trials dataset. Identify every clinical CAR-T construct
appearing in the trial corpus, verify its TargetCategory / Branch /
ProductType labels match what's known about the product, and surface
every disagreement with a clear root cause.

# Context

This codebase classifies ~2,100 CAR-T trials from ClinicalTrials.gov
into structured axes (Branch / DiseaseCategory / DiseaseEntity /
TargetCategory / ProductType / SponsorType / TrialDesign / Platform).
The classifier uses three layers in this precedence:

1. **LLM overrides** (`llm_overrides.json`) — per-trial hand-curated
   labels. Highest priority IF the LLM gave a specific answer.
2. **Named-product short-circuit** (`config.py: NAMED_PRODUCT_TARGETS`)
   — if a known product appears in the trial text, return its target.
   Beats LLM punts (`Other_or_unknown`, `CAR-T_unspecified`).
3. **Term-detection fallback** (`config.py: HEME_TARGET_TERMS`,
   `SOLID_TARGET_TERMS`) — substring match for antigens.

Bugs in this layered system have characteristic patterns:

| Symptom | Likely cause |
|---|---|
| Product correctly named in title, but TargetCategory is `CAR-T_unspecified` | LLM punted before product was added to NAMED_PRODUCT_TARGETS; precedence change resolves once committed |
| Product in title but TargetCategory is a different antigen | LLM override has SPECIFIC wrong answer (not a punt); needs manual override correction |
| Product alias contains hyphen but doesn't match | `_normalize_text` replaces `-` with space; alias must also have a space-form variant (e.g. `lmy-920` AND `lmy 920`) |
| `huCART19` matches as `UCART19` | Alias is too short / lacks word-boundary; needs more specific synonym |
| ProductType=Autologous but title says allogeneic | `_assign_product_type` defaulted; trial title needs explicit allogeneic marker for non-default detection |

# Steps

1. **Read** the audit knowledge base at `scripts/audit/known_products.py`.
   Each entry encodes (aliases, expected target, expected branch,
   expected product_type, notes). Confirm it's current — if a new
   product is in clinical trials but not in the KB, add it before
   running.

2. **Generate a live-classifier view** of the snapshot. Don't trust
   the snapshot CSV directly — the labels there reflect whatever
   classifier code generated the snapshot, not the current code.
   Re-classify in-memory:

   ```bash
   python3 << 'PY' > /tmp/live_view.csv
   import sys
   sys.path.insert(0, '.')
   from pipeline import (
       load_snapshot, _assign_target_with_source,
       _assign_product_type,
   )
   df, _, _ = load_snapshot('YYYY-MM-DD')  # ← latest snapshot
   df['TargetCategory'] = df.apply(
       lambda r: _assign_target_with_source(r.to_dict())[0], axis=1)
   df['ProductType'] = df.apply(
       lambda r: _assign_product_type(r.to_dict())[0], axis=1)
   df[['NCTId', 'BriefTitle', 'Branch', 'DiseaseCategory',
       'DiseaseEntities', 'TrialDesign', 'TargetCategory',
       'ProductType']].to_csv(sys.stdout, index=False)
   PY
   ```

3. **Run the audit**:

   ```bash
   python3 scripts/audit/named_product_audit.py /tmp/live_view.csv
   ```

   Expected baseline (as of 2026-05-05): ≥97% trial-level accuracy,
   ≥32 of 35 products fully correct.

4. **Triage every PARTIAL row** by category:

   a. **Stale CSV labels** (CSV pre-dates a config fix) — none if
      step 2 used the live re-classification. Skip if you see this
      in a CSV-as-input run.

   b. **Knowledge-base bugs** (audit KB is wrong, not classifier).
      Symptoms: product type defaults to Autologous when actually
      allogeneic (check sponsor/title carefully), branch is too
      narrow (e.g. KB says heme but trials cover solid too).
      Fix: edit `known_products.py`.

   c. **Genuine classifier bugs** — three sub-types:
      - **LLM-punted but product known**: precedence change should
        catch it. If still failing, the named-product alias is
        missing or doesn't match (check `_normalize_text` behavior).
      - **LLM specific-but-wrong**: manually update the LLM override
        in `llm_overrides.json`. Set `confidence: "high"` and a
        clear `notes` field naming the audit run that caught it.
      - **Term-detection false positive**: alias too broad (matches
        eligibility text like `"anti-CD38 monoclonal antibody"`).
        Tighten the term list or add a named-product short-circuit.

   d. **Default-rule edge cases**: ProductType `Unclear` or
      defaulted-Autologous when the title omits explicit markers.
      Sometimes acceptable; sometimes needs an explicit pattern in
      `_assign_product_type`.

5. **Apply fixes** in this order to minimize regression risk:
   - `config.py`: additive synonym additions to `NAMED_PRODUCT_TARGETS`
   - `llm_overrides.json`: per-NCT corrections (add a `notes` field
     with date and rationale — these are append-only history)
   - `pipeline.py`: precedence/normalization changes (rare, last resort)
   - `scripts/audit/known_products.py`: KB updates (audit-script side,
     not classifier)

6. **Re-run the audit** and confirm the partial count dropped. Aim
   for 100% of products fully correct on every alias the KB has
   (acceptable to leave MISS rows for products genuinely absent from
   the snapshot).

7. **Regenerate the locked validation sample** if any fix touched a
   trial that's in `validation_study/sample_v1.json`:

   ```bash
   python3 scripts/generate_validation_sample.py \
       --snapshot YYYY-MM-DD --version v1
   ```

   Diff old vs new sha256; document any pipeline-label changes.

8. **Report back** with this structure:

   ```
   ## Pre-audit accuracy: X.X%
   ## Post-audit accuracy: Y.Y%
   ## Fixes applied:
       - {file}: {one-line description, NCTs affected}
   ## Remaining edge cases (acceptable):
       - {NCT} ({reason})
   ## Locked sample diff:
       Old sha256: ...
       New sha256: ...
       Trials with relabeled axes: N (list)
   ```

# Constraints

- **Do NOT** edit the snapshot CSV directly — only edit classifier
  inputs (`config.py`, `llm_overrides.json`, `pipeline.py`).
- **Do NOT** add an alias to NAMED_PRODUCT_TARGETS unless you've
  verified (via sponsor press release, FDA label, or peer-reviewed
  source) what the product targets. Guessing is worse than leaving
  it as `CAR-T_unspecified`.
- **Do NOT** lower the `confidence` field in `llm_overrides.json`
  when correcting it — corrections are higher confidence than
  initial LLM passes (you have a manually-verified ground truth).
- **Do** add a comment in `config.py` next to every new alias
  explaining what it is and which audit run added it. Future
  audit runs will appreciate the context.
- **Do** check `_normalize_text` if a hyphenated alias mysteriously
  doesn't match — the normalizer replaces `-` with space, so
  `lmy-920` becomes `lmy 920` and the alias needs both forms.

# Deliverables

1. A clean audit run report (paste the final summary block).
2. List of file changes with one-line rationale per change.
3. Updated `known_products.py` if any new clinical-stage products
   were discovered during triage.
4. (If applicable) regenerated `validation_study/sample_v1.json`
   with old → new sha256 in the report.

--- END PROMPT ---

## Reference: bug archetypes from the 2026-05-05 audit run

Pre-audit baseline: 83.3% trial accuracy (24 of 35 products correct).
Post-audit: 98.2% trial accuracy (33 of 35 products correct).

Bugs found and fixed:

1. **Anitocabtagene autoleucel** (NCT06413498, NCT07045909) → was CD38,
   should be BCMA. Fix: added `"anitocabtagene autoleucel"` (full name)
   to BCMA NAMED_PRODUCT_TARGETS. Root cause: only `"anito-cel"`
   abbreviation was in the list; substring lookup over `"anito-cel"`
   doesn't match the spelled-out form.

2. **BMS-986453** (NCT06153251, NCT07333261) → was CAR-T_unspecified,
   should be BCMA/GPRC5D dual. Fix: added to NAMED_PRODUCT_TARGETS
   under existing `"BCMA/GPRC5D dual"` label + updated LLM override.

3. **MT027 / Mesothelin** (NCT06726564) → LLM override had specific
   wrong answer (Mesothelin from "pleural mesothelioma" disease text;
   MT027 is B7-H3). Fix: corrected LLM override to B7-H3.

4. **MB-CART19.1 vs MB-CART2019.1** — config wrongly placed
   `"mb-cart19.1"` (CD19 monovalent) under `"CD19/CD20 dual"`
   alongside the tandem `"mb-cart2019.1"`. Fix: moved monovalent to
   CD19, kept tandem in dual. Substring lookup safely separates them
   (`"mb-cart2019.1"` does not contain `"mb-cart19.1"`).

5. **Classifier precedence** (~9 trials: JY231 ×4, CT1190B ×3, CT0596,
   AZD0120) — LLM punts (`CAR-T_unspecified` / `Other_or_unknown`)
   were locking out subsequent named-product additions. Fix:
   `pipeline._assign_target_with_source` now prefers named-product
   match over LLM punts. LLM specific answers still win.

6. **LMY-920 hyphen normalization** (NCT05546723) — alias `"lmy-920"`
   alone didn't match because `_normalize_text` replaces `-` with
   space. Fix: added both `"lmy-920"` and `"lmy 920"` forms.

7. **Audit knowledge-base bugs** (not classifier bugs):
   - Removed bare `"ucart19"` alias (false-matched `"huCART19"`).
   - MT027: changed from Autologous to Allogeneic/Off-the-shelf
     (multiple trial titles say "Allogeneic CAR-T").
   - UTAA06: changed Branch from Heme-onc to Mixed (trials cover
     both AML and solid tumors).
