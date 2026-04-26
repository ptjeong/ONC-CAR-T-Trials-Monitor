# Per-trial drilldown UI — canonical spec v1.3

Status: **active** as of 2026-04-26.

Changelog:
- **v1.3** (2026-04-26): **NEJM-clean visual discipline.** The only
  emoji permitted anywhere in either app is the canonical 🚩 flag
  indicator (and even that ONLY where it conveys the "trial has open
  community-flag issues" semantic — never decoratively). All other
  emoji glyphs (icons, page icons, expander icons, traffic-light
  confidence indicators, garden gamification, milestone badges,
  download icons, etc.) MUST be replaced with text labels or
  professional unicode equivalents (block characters, arrows,
  thin glyphs). Section "Visual discipline" below codifies the
  permitted vocabulary. Sweep of both apps performed in commit
  series following this spec bump.
- **v1.2** (2026-04-26): each metadata column carries a bold
  section header ("Disease" / "Product" / "Sponsor"). Without
  the header, when scrolling many drilldowns the 3-column grid
  visually collapses into a wall of bullets. Header makes the
  structure unmissable. Additive UX change; no schema impact.
  Rheum had this from the start; onc adopting brings parity.
- **v1.1** (2026-04-26): codify `compute_confidence_factors` return
  schema explicitly (resolves rheum's round-4 quibble — both apps
  now use the nested `{factors: {axis: {score, driver}}}` shape, no
  parallel `drivers` list with redundant fields). Additive change;
  no breaking semantics for existing renderers.
- **v1.0** (2026-04-26): initial canonical spec; both apps
  conforming.
Applies to: `onc-car-t-trials-monitor` AND `rheum-car-t-trials-monitor`.
Both apps declare conformance to this spec via `_render_trial_drilldown`.

This spec is the **single source of truth** for the per-trial detail
card visible whenever a user clicks a trial row in either dashboard.
The two apps had drifted independently; this v1.0 merges the best
elements of each. Future revisions go through this doc, not via
unilateral edits to either `app.py`.

## Why a shared spec

The drilldown is the user's primary interaction surface — they spend
more time looking at one trial card than at any other element.
Diverging UX across the two apps means:

- Cross-citation in the methods paper is awkward (different screenshots)
- Users who use both apps relearn the same affordance twice
- Bug fixes don't propagate
- The methodology paper has to enumerate per-app differences

Best practice for cross-app UI alignment: write the spec, version it,
both apps declare which version they implement. Spec edits get a
bump (v1.1, v2.0); each app's CHANGELOG records the version it
currently conforms to.

## Anatomy

```
┌─ st.expander(f"**{NCT_ID}** — {BriefTitle}", expanded=True) ───────────┐
│                                                                          │
│  [1. Flag banner] _render_flag_banner(record)                           │
│      Invisible when no flags. Otherwise st.error (consensus) or         │
│      st.warning (open) + inline proposed-corrections table.             │
│                                                                          │
│  [2. External link row]                                                 │
│      📎 Open on ClinicalTrials.gov ↗                                    │
│      (placed BEFORE metadata so the rater can verify against the live   │
│      record without scrolling)                                          │
│                                                                          │
│  [3. Three-column metadata grid]                                        │
│      Each column carries a bold ### section header rendered via         │
│      st.markdown("### Disease") / "### Product" / "### Sponsor"         │
│      (spec v1.2 — without the header, the 3-column layout visually      │
│      collapses into a wall of bullets when scrolling many drilldowns)   │
│      ┌─────────────────┬─────────────────┬─────────────────┐            │
│      │ ### DISEASE     │ ### PRODUCT     │ ### SPONSOR     │            │
│      ├─────────────────┼─────────────────┼─────────────────┤            │
│      │ Branch / Family │ Target          │ LeadSponsor     │            │
│      │ Category        │   *(via Source)*│ SponsorType     │            │
│      │ Entity          │ ProductType     │ Enrollment      │            │
│      │ All entities    │   *(via Source)*│ Countries       │            │
│      │ TrialDesign     │ Modality†       │ Age group       │            │
│      │ Phase / Status  │ Named product‡  │                 │            │
│      │ Start year      │ LLM override‡   │                 │            │
│      └─────────────────┴─────────────────┴─────────────────┘            │
│      †: onc only.   ‡: only render when present.                        │
│      *(via Source)*: italicised inline source tag for instant audit.    │
│                                                                          │
│  [4. Free-text payload]                                                 │
│      Render only fields that are non-empty:                             │
│      - **Primary endpoints**: <semicolon-joined>                        │
│      - **Conditions**: <comma-joined; replace pipe with comma>          │
│      - **Interventions**: <comma-joined; replace pipe with comma>       │
│      - **Brief summary**:                                               │
│        > <BriefSummary in markdown block-quote>                         │
│                                                                          │
│  [5. expander: "How was this classified?"]                              │
│      _render_classification_rationale(record, key_suffix)               │
│      Three sub-sections:                                                │
│        a) Composite confidence header                                   │
│           "Composite confidence: 🟡 medium (72%)"                        │
│        b) Row of st.metric tiles, one per axis                          │
│           Each tile: axis name, score %, driver as tooltip              │
│        c) "What's holding the score down" caption                       │
│           Bulleted list of (axis, driver) for worst-scoring axes        │
│        d) Tabular rationale: dataframe with column_config               │
│           Columns: Axis | Label | Source | Matched terms | Explanation  │
│        e) (st.info) LLM-override note when applicable                   │
│                                                                          │
│  [6. expander: "Suggest a classification correction"]                   │
│      _render_suggest_correction(record, key_suffix)                     │
│      Multiselect axes → per-axis correction (selectbox or text)         │
│      → notes textarea → "Open as GitHub issue ↗" link button.           │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

## Implementation contract

Both apps MUST expose:

```python
def _render_trial_drilldown(record, *, key_suffix: str = "") -> None:
    """Render the per-trial detail card. Conforms to UI_DRILLDOWN_SPEC v1.0."""
    ...
```

`record` is a `pd.Series` or dict; `key_suffix` disambiguates session-state
widget keys when the same trial may be drilled into from multiple
contexts in one render (e.g. Geography city table + Data tab).

The helper MUST:
- Be the SOLE drilldown render path used by every trial-table call site
  in the app (no inline drilldown blocks)
- Wrap the entire card in `st.expander(..., expanded=True)`
- Tolerate missing optional fields by rendering "—"
- Survive a missing `_render_flag_banner` / `_render_classification_rationale`
  / `_render_suggest_correction` (wrap each in `try/except` so a
  subsystem failure degrades to a silent skip, not a crashed card)

## App-specific axis differences (intentional)

Onc and rheum have different classification axes by design. This is
NOT a spec divergence:

| Axis | Onc | Rheum |
|---|---|---|
| Top-level grouping | Branch (Heme-onc / Solid-onc / Mixed / Unknown) | DiseaseFamily (single — autoimmune rheumatologic) |
| Mid-level grouping | DiseaseCategory (~30 categories) | (none — flatter taxonomy) |
| Leaf | DiseaseEntity (~70 entities) | DiseaseEntity (~13 entities) |
| Modality column | Yes — Auto / Allo / In-vivo / CAR-NK / etc. | No — handled via TargetCategory `CAR-NK: X` etc. |

The 3-column metadata grid renders only the axes the app's pipeline
populates. Empty axes ("Modality" in rheum) are not rendered.

## Source-tag display

Both apps annotate the Target and ProductType labels with their source
tag inline:

```
Target: CD19 *(via antigen_match)*
ProductType: Allogeneic/Off-the-shelf *(via explicit_allogeneic_marker)*
```

This is the single most-discoverable audit affordance — the rater sees
WHERE the label came from without expanding anything. Source tags
are surfaced from the pipeline's existing source-tag columns
(`TargetSource`, `ProductTypeSource`).

The full per-axis explanation lives in the "How was this classified?"
expander; the inline tag is the at-a-glance hint.

## Confidence model — canonical schema (v1.1)

Both apps surface the multi-factor confidence model
(`compute_confidence_factors(row)`) inside the rationale expander.

**Canonical return shape** — both apps MUST emit exactly this:

```python
{
  "score":   float,           # composite ∈ [0, 1], unweighted mean of factor scores
  "level":   str,             # "high" | "medium" | "low" — bucket calibrated to legacy
                              # composite ≥ 0.85 → "high", ≥ 0.55 → "medium", < 0.55 → "low"
  "factors": dict[str, dict], # see below — NESTED, not flat
  "drivers": list[tuple[str, str]],   # k-worst (axis, driver) pairs, default k=3
}
```

`factors` is a NESTED dict — one entry per axis, each value is a sub-dict:

```python
"factors": {
  "Branch":          {"score": 1.00, "driver": "Clean single-branch"},
  "DiseaseCategory": {"score": 1.00, "driver": "Specific category match"},
  "DiseaseEntity":   {"score": 0.55, "driver": "Basket-level fallback"},
  "TargetCategory":  {"score": 1.00, "driver": "Antigen identified: CD19"},
  "ProductType":     {"score": 0.50, "driver": "Defaulted to autologous"},
}
```

`drivers` is a pre-computed convenience: the `k` axes with the lowest
sub-scores (default `k=3`), as `(axis_name, driver_text)` pairs.
Renderers use this to populate the "What's holding the score down"
caption without re-sorting `factors` themselves.

### Why nested, not flat

Rheum's pre-v1.1 implementation had a flat shape:
`{factors: {axis: float}}` plus a parallel `drivers: [(axis, score, reason)]`
list. Both shapes carry the same information, but the nested form is
canonical because:

1. **Single source of truth per axis.** Nested `factors[axis]["driver"]`
   is the ONLY place the per-axis driver text lives. Flat-with-parallel
   duplicates it (driver appears in both `drivers` list and is implied
   by axis identity in `factors`).
2. **Trivially serializable.** Nested dicts round-trip through JSON
   without tuple-list coercion gymnastics.
3. **Cross-app consumers** (any future `cart-trials-core` package, or
   the methods-paper analysis scripts) get a single shape to bind
   against.

Rheum's flat-shape implementation should flip on next snapshot regen
or whenever `compute_confidence_factors` is touched. Pure refactor —
no UI consumer change required since renderers already extract
`factors[axis]["driver"]` directly.

The legacy 3-bucket `ClassificationConfidence` (high/medium/low) is
preserved bit-for-bit in both apps for snapshot back-compat. The
multi-factor model lives alongside it as a per-axis read-only enrichment.

## Visual discipline (v1.3+)

Two surfaces, two rules:

### Main public dashboards (onc + rheum) — strict NEJM-clean

The only emoji glyph permitted is **🚩** (the canonical flag indicator),
and only where it conveys the "trial has open community-flag GitHub
issues" semantic. Never decoratively. Everywhere else, use:

- **Text labels** instead of icon emoji ("Refresh ↻" not "🔄",
  "Moderation" not "⚙ Moderation", "Open on ClinicalTrials.gov ↗"
  not "📎 Open …")
- **Word-based confidence indicators** instead of traffic lights
  ("**High** (87%)" not "🟢 high (87%)"; canonical word vocabulary:
  "High" / "Moderate" / "Limited")
- **Unicode arrows** for navigation hints (`↗ ↻ ↺ →`) — these are
  thin line glyphs, not coloured emoji
- **`page_icon=None`** in `st.set_page_config` — no leaf icon, no
  test-tube icon, no DNA helix
- **Plain-text tab labels** (no leading emoji)

NEJM publishes the most-cited cancer-research methodology in the
world without a single emoji on the cover. Match that bar.

### Validation app (rater experience) — sophisticated gamification

The validation app has a longer-term user (raters spend 2-3 hours)
and benefits from polish that motivates without being childish.
Permitted UX elements:

- **CSS-styled progress heatmap** (GitHub-contributions-style cell
  grid that fills in deep clinical blue as trials are rated). Visual
  reward through saturation, not glyphs. See `validation_study/app.py`
  `.pgrid` / `.pcell` CSS classes.
- **Stat-tile row** (Linear/Stripe-style: large number + small
  all-caps label) showing trials rated, median time per trial, total
  session time, ETA. The reward is informative metrics.
- **Milestone messages with methodology context** rather than
  cartoon badges. Example: "Halfway: 100 trials rated. Median pace
  says ~85 min remaining. Now is the right time for a short break —
  fatigue effects on κ become detectable past ~60 min of
  uninterrupted rating (Gwet 2014)." Reward = useful knowledge.
- **Subtle CSS micro-interactions** (cell hover scale, smooth color
  transitions). No animations from `st.balloons()` or similar.

The validation app **must not use emoji either** — gamification is
achieved through CSS, typography, and copy that respects the rater's
intelligence. Indie-game polish (think Linear, Stripe Atlas, Things 3),
not Duolingo.

## Versioning

Current version: **v1.3** (2026-04-26).

When this spec changes:
1. Bump version in this file's header
2. Both apps' `_render_trial_drilldown` docstrings reference the new version
3. Both apps' CHANGELOG records the conformance update
4. Cross-app sync brief notes the version delta

For backward-incompatible changes (e.g. column count change), bump
the major version (v2.0). For additive changes (e.g. a new optional
field in the metadata grid), bump the minor (v1.1).

## Reference implementations

- `onc-car-t-trials-monitor` `app.py:_render_trial_drilldown` — **v1.3 conforming**
  (column headers + emoji sweep shipped 2026-04-26).
  `pipeline.compute_confidence_factors` emits canonical nested schema.
- `rheum-car-t-trials-monitor` `app.py:_render_trial_drilldown` @ commit `4cce635`
  — **v1.0 conforming, pending v1.1 + v1.2 + v1.3 micro-updates**:
    1. Flip `compute_confidence_factors` from flat `{axis: float}` to
       nested `{axis: {score, driver}}` per v1.1 canonical schema
    2. Confirm column headers ("Disease" / "Product" / "Sponsor") are
       rendered as `st.markdown("### …")` per v1.2 (rheum already had
       this UX from the start; just mark conformance)
    3. Strip non-flag emojis (page_icon, refresh button, traffic-light
       confidence indicators, tab labels, expander icons) per v1.3
    4. Drop the "Flagged only" filter checkbox if still present —
       this was removed from onc in commit `a95147b` after we agreed
       it had no real use case (the 🚩 prefix in the table already
       gives at-a-glance discoverability; proper triage lives in the
       Moderation tab)
    5. Add a public refresh-flags button next to the search bar
       (text-based: "Refresh ↻", not "🔄"). Calls
       `_load_active_flags.clear() + _load_flag_issue_details.clear()`
       then `st.rerun()`.
  All five items are pure UX/schema; no breaking change for consumers.
