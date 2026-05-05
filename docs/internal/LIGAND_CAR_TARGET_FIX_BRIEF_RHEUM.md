# Rheum port — ligand-based CAR target classifier fix

Paste the section between `--- BEGIN PROMPT ---` and `--- END PROMPT ---`
into a fresh Claude Code session in the **rheum-car-t-trial-monitor** repo.
Self-contained, no other context needed.

Onc-side equivalent landed 2026-04-27. Pins to onc commit:
`<fill in after onc commit lands>`.

---

--- BEGIN PROMPT ---

There is a class of CAR-T construct designs (ligand-based CARs) where
the binding domain of the CAR is a natural cytokine ligand rather than
an scFv. Examples in the broader CAR-T literature:

- **IL3 CAR** (binds CD123 on AML blasts) — onc-only
- **APRIL CAR** (binds BCMA + TACI on plasma cells) — onc-only
- **NKG2D CAR** (binds NKG2D-L = MICA/MICB/ULBP1-6 on stressed cells) — onc-only
- **BAFF CAR** (binds BAFF-R + TACI + BCMA on B cells) — **present in the rheum dataset**

The classification convention (now standardized across both apps) is:
**record the receptor on the target cell, NOT the binding-domain ligand.**
A BAFF-CAR for SLE → TargetCategory = `BAFF-R`, not `BAFF`.

In this rheum repo, scan the snapshot for these specific NCTs:

```
NCT06340750  "BAFF CAR-T Cells (LMY-920) for Systemic Lupus Erythematosus"
NCT07022197  "Safety and Efficacy of BAFF-R CART for Refractory Neuroimmun…"
```

Both are real BAFF-CAR designs. Currently they classify as `CAR-T_unspecified`
(the rheum classifier has no BAFF-only branch — only `CD19/BAFF dual` for
the cd19+BAFF case; standalone BAFF falls through). After this fix they
should classify as `BAFF-R`.

## The fix — exactly two file edits

### Edit 1 — `config.py`

In the `CAR_SPECIFIC_TARGET_TERMS` dict (currently has `CD19` and `BCMA`
entries), add a new entry **after** the BCMA block:

```python
    # Ligand-based CAR convention (synced from onc 2026-04-27).
    # BAFF-CAR (LMY-920 etc.) uses BAFF as the binding domain; the
    # receptor on the B cell is BAFF-R / TACI / BCMA. Record the
    # dominant therapeutic receptor (BAFF-R for autoimmune B-cell
    # depletion). Synonyms are construct-anchored (no bare "baff")
    # to avoid false matches in eligibility text discussing BAFF
    # biology.
    "BAFF-R": [
        "baff-r",
        "baff r",
        "baff receptor",
        "tnfrsf13c",
        "baff car",
        "baff-car",
        "baff car-t",
        "baff cart",
        "baff-car-t",
        "baff-cart",
    ],
```

### Edit 2 — `pipeline.py`

In `_assign_target(row)`:

**(a)** After the existing `has_baff = "baff" in text` line, add:

```python
    # Construct-anchored BAFF-R detection (synced from onc 2026-04-27).
    # `has_baff` (bare token) is kept for the CD19/BAFF dual-target
    # case below; `has_baff_r` is the precise ligand-CAR detector
    # that maps BAFF-CAR designs to the receptor (BAFF-R) per the
    # ligand-CAR convention used across the onc + rheum pipelines.
    has_baff_r = _contains_any(text, CAR_SPECIFIC_TARGET_TERMS["BAFF-R"])
```

**(b)** After `if has_bcma: return "BCMA"` and BEFORE `if has_cd20:`,
add the new branch:

```python
    # Ligand-CAR: BAFF-CAR → BAFF-R (ahead of the bare-baff fall-through
    # because the rheum classifier had no BAFF-only branch before this,
    # so LMY-920-style trials silently fell to CAR-T_unspecified.)
    if has_baff_r:
        return "BAFF-R"
```

## Verification

Run this to confirm the only change is the 2 expected NCTs:

```bash
python3 -c "
import pandas as pd
import pipeline as p
df = pd.read_csv('snapshots/<latest_date>/trials.csv')
new = df.apply(lambda r: p._assign_target(r.to_dict()), axis=1)
mask = (df['TargetCategory'] != new) & (new == 'BAFF-R')
print(df[mask][['NCTId', 'BriefTitle', 'TargetCategory']].assign(NewLabel=new[mask]))
"
```

Expected output: 2 rows, NCT06340750 and NCT07022197, both new label `BAFF-R`.

## What NOT to do

- Don't widen `BAFF-R` synonyms to bare `"baff"` — autoimmune trial
  eligibility text often discusses BAFF biology without targeting
  it (e.g. "patients on prior anti-BAFF therapy"). The construct-
  anchored synonyms above prevent that false-positive class.
- Don't touch the `has_cd19 and has_baff → CD19/BAFF dual` branch —
  it correctly captures NCT06279923 (CD19-BAFF dual CAR).

## Pre-existing issue worth flagging separately (NOT this PR)

While running the audit on the rheum snapshot, I noticed a much
larger discrepancy: ~89 of 284 snapshot trials would re-classify
to *worse* labels under the current `_assign_target` than what's
in the snapshot CSV. Examples: `CD19 → Other_or_unknown` (33 trials),
`BCMA → CAR-T_unspecified` (4 trials). This means an earlier version
of the rheum classifier was richer, and someone removed branches
without updating the snapshot. That is a separate problem from
this BAFF-R fix (additive, isolated) — flag it for the rheum
maintainer to investigate independently. Do NOT regenerate the
snapshot as part of this PR.

## Commit message suggestion

```
fix(target-classifier): add BAFF-R for ligand-based CAR-Ts

NCT06340750 (LMY-920 SLE) and NCT07022197 (BAFF-R CART
neuroimmune) silently fell to CAR-T_unspecified because the
classifier had no BAFF-only branch — only CD19/BAFF dual.

Ligand-CAR convention (synced with onc): record the receptor
on the target cell (BAFF-R), not the binding-domain ligand
(BAFF). Construct-anchored synonyms only — bare "baff" would
false-match eligibility text discussing BAFF biology.
```

--- END PROMPT ---
