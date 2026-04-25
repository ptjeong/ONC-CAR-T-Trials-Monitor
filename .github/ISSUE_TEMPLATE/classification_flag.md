---
name: Classification correction (flag)
about: Suggest a correction to a trial's automated classification
title: "[Flag] NCT00000000 — axes…"
labels: classification-flag, needs-review
assignees: ''
---

> **Note**: this template is normally pre-filled by the dashboard's
> "Suggest a classification correction" button (`Open as GitHub issue ↗`).
> If you're filing manually, follow the same structure so the
> consensus-detection workflow can parse your submission.

## Trial classification correction

**Trial**: [NCT00000000](https://clinicaltrials.gov/study/NCT00000000)
**Title**: <full trial title>

### Current pipeline classification
| Axis | Current label |
|---|---|
| Branch | `Solid-onc` |
| TargetCategory | `Other_or_unknown` |

### Proposed correction
| Axis | Proposed |
|---|---|
| Branch | `Heme-onc` |
| TargetCategory | `CD19` |

### Reviewer notes

(Optional. Cite trial text or a reference if helpful. Public.)

### Reviewer information
- **GitHub identity**: visible above (issue author).

### Moderator workflow
1. **Other reviewers** add their own assessment as a *comment* using the
   same axis schema below. Use one comment per reviewer; the
   consensus-detection workflow parses every comment with a `BEGIN_FLAG_DATA`
   block.
2. Once **3 independent reviewers agree** on the same proposed
   correction for an axis, the issue gets the `consensus-reached`
   label automatically.
3. The moderator (@ptjeong) approves the consensus, which promotes
   the correction to `llm_overrides.json` via
   `scripts/promote_consensus_flags.py`.

---

<!-- BEGIN_FLAG_DATA
nct_id: NCT00000000
flagged_axes:
  - axis: Branch
    pipeline_label: "Solid-onc"
    proposed_correction: "Heme-onc"
  - axis: TargetCategory
    pipeline_label: "Other_or_unknown"
    proposed_correction: "CD19"
END_FLAG_DATA -->

<sub>Validation methodology described in
[`docs/methods.md`](https://github.com/ptjeong/ONC-CAR-T-Trials-Monitor/blob/main/docs/methods.md)
§ 4.4.</sub>
