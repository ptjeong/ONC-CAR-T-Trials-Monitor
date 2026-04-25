# Rheum CAR-T Trials Monitor — paste-ready brief

> **Context.** This is a self-contained handoff document for the rheum
> sister app (https://github.com/ptjeong/rheum-car-t-trial-monitor). The
> oncology monitor (this repo) just shipped six features on
> 2026-04-25 that are all worth porting. Drop this whole file into
> the rheum repo's internal docs folder and execute it as a single
> sprint — every item below is independent of the others, but they're
> ordered by ROI: row-click drilldowns first (the unlocks are biggest),
> moderation infra last (only needed once flags actually accumulate).
>
> Author: Peter (@ptjeong). Drafted with Claude as engineering lead.
> Date: 2026-04-25.

## Scope

Six features, all currently live in the oncology repo at the SHAs
listed. Each one is a self-contained PR in the oncology repo and can
be ported as-is, with only the rheum-specific column lists changing.

| # | Feature                                          | Onc commit(s)              | Onc LOC delta |
|---|--------------------------------------------------|----------------------------|---------------|
| 1 | Row-click trial drilldown helper                 | 202f2fa                    | +180 / -0     |
| 2 | Geography city-trials drilldown                  | 587bf16                    | +40 / -0      |
| 3 | Deep Dive by-disease + by-product drilldowns     | 421fdd8                    | +110 / -0     |
| 4 | Deep Dive by-sponsor: search + scrollable + pick | d164813                    | +95 / -10     |
| 5 | NEW Deep Dive sub-tab — By target                | 5e6553b                    | +250 / -0     |
| 6 | Community flagging system (full loop)            | b4402d1, 8ed8787, 76bdfc4, 816dcef, f006d8e | +1,500 / -10 |

Total: ~5 commits' worth of porting work, mostly mechanical.

---

## 1. Row-click trial drilldown helper

**Pattern.** Streamlit's `st.dataframe(on_select="rerun",
selection_mode="single-row", key=…)` returns an event with
`event.selection.rows` after a click. Capture it, look up the row,
render a per-trial detail card.

Extract this into a single shared helper:

```python
def _render_trial_drilldown(record, *, key_suffix: str = "") -> None:
    """Render the per-trial detail card used everywhere a single trial is
    selected (Data tab, Geography city table, Deep Dive sub-tabs).

    Parameters
    ----------
    record : pd.Series or dict-like
        A single trial row. Accessed via .get(); missing fields render as "—".
    key_suffix : str
        Disambiguator for any session_state-keyed widgets inside the card
        (e.g. the Suggest-correction form). Required when multiple
        drilldowns might appear on the same page or tab.

    The card has three layers:
      1. Two-column metadata table (disease/clinical + product/sponsor)
      2. Free-text payload (BriefSummary, eligibility, locations)
      3. Suggest-correction form (calls _render_suggest_correction
         conditionally — wrapped in try/except so the helper is
         backward-compatible if you port this before #6)
    """
    # … [exact body in oncology app.py at line ~322 — copy verbatim]
```

**Why `key_suffix` matters:** if the same drilldown card is rendered on
multiple tabs in one session (e.g. user clicks a trial on Geography
then on Data), the form widgets need distinct session_state keys or
Streamlit raises DuplicateWidgetID. The suffix is just a string
prepended to every internal `key=` call.

**Wiring.** Find every existing trial-table `st.dataframe(...)` call,
add `on_select="rerun", selection_mode="single-row", key=…` if not
present, capture `event.selection.rows`, and call the helper:

```python
event = st.dataframe(table_df[show_cols], on_select="rerun",
                     selection_mode="single-row",
                     key=f"my_table_{some_disambiguator}")
rows = event.selection.rows if event and hasattr(event, "selection") else []
if rows:
    _render_trial_drilldown(table_df.iloc[rows[0]],
                             key_suffix=f"my_table_{some_disambiguator}")
```

Add `st.caption("Click any row to open the full trial record below.")`
above each table — users don't discover the affordance otherwise.

---

## 2. Geography city-trials drilldown

In the rheum app, the equivalent table is the country-zoom city list.
Pattern is identical to #1 above. Two specific gotchas from the
oncology port:

1. **Subset lookup.** The city-table data frame is usually a
   country-filtered subset (e.g. `country_study_view`) that lacks
   columns the drilldown card wants (Modality, AgeGroup,
   ClassificationConfidence, BriefSummary). Look up the full record in
   the master `df_filt` by NCT, with a fallback to the subset row:

   ```python
   sel_nct = city_trial_view.iloc[rows[0]]["NCTId"]
   full_rec = df_filt[df_filt["NCTId"] == sel_nct]
   if not full_rec.empty:
       _render_trial_drilldown(full_rec.iloc[0],
                                key_suffix=f"geo_city_{country}_{city}")
   else:
       _render_trial_drilldown(city_trial_view.iloc[rows[0]], key_suffix=…)
   ```

2. **Composite session keys.** Use `f"city_trial_table_{country}_{city}"`
   as the dataframe key — otherwise selecting a row in city A and then
   navigating to city B replays city A's selection state.

---

## 3. Deep Dive by-disease + by-product drilldowns

For **by-disease**: the focus-cohort trial list is already a `pd.DataFrame`
in the rheum app (per-disease pivot). Just add the `on_select` props
and call the helper. Single-step drill (no intermediate table).

For **by-product**: this is a **two-step drill**. The product-pivot table
shows aggregated rows; clicking a product reveals its trial list, which
is itself selectable. Wire it like:

```python
# Step 1: product pivot is selectable
prod_event = st.dataframe(pivot, on_select="rerun",
                          selection_mode="single-row",
                          key="deep_product_pivot")
prod_rows = prod_event.selection.rows if prod_event else []
if prod_rows:
    picked = pivot.iloc[prod_rows[0]]["ProductName"]
    prod_trials = full_df[full_df["ProductName"] == picked]
    # Step 2: that product's trial list is also selectable
    trial_event = st.dataframe(prod_trials[trial_cols],
                                on_select="rerun",
                                selection_mode="single-row",
                                key=f"deep_product_trial_table_{picked}")
    trial_rows = trial_event.selection.rows if trial_event else []
    if trial_rows:
        _render_trial_drilldown(prod_trials.iloc[trial_rows[0]],
                                 key_suffix=f"deep_product_{picked}")
```

The `key=f"…_{picked}"` is essential — Streamlit caches the event by
key, so a static key would never update when the user picks a
different product.

---

## 4. Deep Dive by-sponsor: search + scrollable + pick

The oncology version was capped at top-10 sponsors and unsearchable.
Three changes:

1. **Drop the `.head(10)` cap** — show all sponsors, scrollable.
2. **Add a `st.text_input("Search sponsor", key="…")`** above the
   table; filter by case-insensitive substring on the LeadSponsor
   column.
3. **Make the sponsor list selectable** — same `on_select` pattern.
   Selected sponsor → trial list → trial click → drilldown helper
   (same two-step pattern as by-product).

Keep the existing aggregate panels (top-categories, top-products,
branch-split) below the trial list; they're useful context once the
moderator is focused on one sponsor.

---

## 5. NEW Deep Dive sub-tab — By target

This is the biggest single feature. ~250 LOC. Two modes:

**Landscape mode** (no antigen selected): top-25 antigens table with
trial counts, modality split (auto / allo / NK / γδ / in-vivo),
disease-area breadth (#disease-categories the antigen is being tried
in), top sponsor.

**Single-antigen focus** (after picking one): four metric tiles —
total trials, recruiting, phase distribution, % industry — plus a 2×2
panel grid:
  - Top diseases (pivot of focus cohort)
  - Phase distribution (bar chart)
  - Modality split (pie or stacked bar)
  - Top sponsors (table)

Below the panels, the **trial list with row-click → drilldown helper**
(same pattern as #1) and a CSV download button.

**Rheum-specific antigen list.** The oncology version excludes platform
labels (CAAR-T, CAR-Treg) and catch-all buckets ("Other") from the
antigen picker — for rheum, you want CAAR-T and CAR-Treg KEPT (they're
the central modalities) and the heme-onc antigens (CD19, BCMA) ALSO
kept (they appear off-label in lupus / myasthenia / RA trials). The
exclusion list should be just `("Other_or_unknown",)` for rheum.

---

## 6. Community flagging system (FULL LOOP)

This is the headline feature, designed with Peter on 2026-04-25. Six
parts, all live in the oncology app. The big design decision: **GitHub
Issues are the storage layer, not a private database**. This eliminates
auth/PAT/secret management on our side and gives the community an
audit trail by default. The dashboard is a **link-out client only** —
it never POSTs to GitHub.

### 6a. Suggest-correction form on every trial card

Inside `_render_trial_drilldown`, conditionally append a
`st.expander("Suggest a classification correction")`:

```python
def _render_suggest_correction(record, *, key_suffix: str) -> None:
    with st.expander("Suggest a classification correction"):
        st.markdown(
            "Spotted a wrong label? File a flag on GitHub. Three reviewer "
            "agreements promote the correction to `llm_overrides.json` "
            "after moderator approval."
        )
        axes = st.multiselect("Axis (or axes) to correct",
                              options=list(_FLAG_AXIS_OPTIONS.keys()),
                              key=f"suggest_axes_{key_suffix}")
        corrections: dict[str, str] = {}
        for ax in axes:
            options = _FLAG_AXIS_OPTIONS[ax]  # list or () for free-text
            if options:
                corrections[ax] = st.selectbox(
                    f"Proposed {ax}", options=options,
                    key=f"suggest_{ax}_{key_suffix}")
            else:
                corrections[ax] = st.text_input(
                    f"Proposed {ax}", key=f"suggest_{ax}_{key_suffix}")
        notes = st.text_area("Reviewer notes (optional, public)",
                             key=f"suggest_notes_{key_suffix}")
        if axes:
            url = _build_flag_issue_url(record, axes=axes,
                                         corrections=corrections, notes=notes)
            st.link_button("Open as GitHub issue ↗", url, type="primary")
```

The URL builder generates a `github.com/{slug}/issues/new?…` link
with title, labels, and a body containing a markdown table + a
machine-parseable YAML block bracketed by HTML comments:

```python
GITHUB_REPO_SLUG = "ptjeong/rheum-car-t-trial-monitor"  # change for rheum

def _build_flag_issue_url(record, *, axes, corrections, notes) -> str:
    nct = record.get("NCTId", "NCT00000000")
    title = f"[Flag] {nct} — {', '.join(axes)}"
    labels = ["classification-flag", "needs-review"] + \
             [f"axis-{a}" for a in axes]
    body_lines = [
        f"**Trial:** [{nct}](https://clinicaltrials.gov/study/{nct})",
        f"**Title:** {record.get('BriefTitle', '')}", "",
        "### Pipeline classification",
        "| Axis | Current label |", "|---|---|",
    ]
    for ax in axes:
        body_lines.append(f"| {ax} | `{record.get(ax, '—')}` |")
    body_lines += ["", "### Proposed correction", "| Axis | Proposed |",
                   "|---|---|"]
    for ax in axes:
        body_lines.append(f"| {ax} | `{corrections[ax]}` |")
    body_lines += ["", "### Reviewer notes", notes or "_(none)_", "",
                   "<!-- BEGIN_FLAG_DATA",
                   f"nct_id: {nct}", "flagged_axes:"]
    for ax in axes:
        body_lines += [
            f"  - axis: {ax}",
            f"    pipeline_label: \"{record.get(ax, '')}\"",
            f"    proposed_correction: \"{corrections[ax]}\"",
        ]
    body_lines.append("END_FLAG_DATA -->")
    body = "\n".join(body_lines)
    from urllib.parse import urlencode
    return (
        f"https://github.com/{GITHUB_REPO_SLUG}/issues/new?" +
        urlencode({"title": title, "labels": ",".join(labels), "body": body})
    )
```

Add a manual-fallback issue template at
`.github/ISSUE_TEMPLATE/classification_flag.md` documenting the same
YAML block format other reviewers must follow.

### 6b. Flag-badge column on every trial table

Cached fetch from the GitHub public issues API + a tiny badge string
helper:

```python
@st.cache_data(ttl=60 * 5, show_spinner=False)
def _load_active_flags() -> dict:
    """Returns {nct_id: {"count": int, "consensus": bool, "issue_urls": [...]}}.
    5-min cache → 1 API call per page render → well under the 60 req/hr
    unauthenticated ceiling."""
    # … [exact body in onc app.py at line ~620 — copy verbatim]

def _flag_badge(flag_entry: dict | None) -> str:
    if not flag_entry: return ""
    n = flag_entry.get("count", 0)
    if n == 0: return ""
    if flag_entry.get("consensus"): return f"⚑ consensus ({n})"
    return f"⚑ {n}"

def _attach_flag_column(df, show_cols):
    flags = _load_active_flags()
    out = df.copy()
    out["_Flag"] = out["NCTId"].map(lambda n: _flag_badge(flags.get(n)))
    return out, ["_Flag"] + [c for c in show_cols if c != "_Flag"]
```

Wire the helper into every trial table (Data tab, Geography city
table, all Deep Dive sub-tab trial tables). Failure mode is silent —
any exception in the fetch returns `{}` and the column renders blank.

### 6c. GitHub Action for consensus detection

Single workflow file at `.github/workflows/flag_consensus.yml` that
fires on issue/comment events with `classification-flag` label,
parses every BEGIN_FLAG_DATA block in the issue body + comments, counts
distinct authors agreeing on the same `(axis, proposed_correction)`
tuple, and applies the `consensus-reached` label when ≥3 distinct
authors agree.

Companion script at `scripts/detect_flag_consensus.py` does the actual
logic — pure Python, ~150 LOC, no external deps beyond requests and
pyyaml. Fully unit-tested in `tests/test_flag_consensus.py` (8 tests
covering parser robustness, threshold enforcement, same-author
deduplication, bot-author exclusion).

### 6d. Moderation tab (private)

Token-gated tab that only renders when:
1. Server has `MODERATOR_TOKEN` env var (or `st.secrets["moderator_token"]`)
2. URL has `?mod=<token>` matching exactly

Three sections:
- **Mode A — Triage consensus-reached flags.** For each consensus issue,
  side-by-side pipeline-label vs proposed correction, accept/reject
  buttons, free-text rationale. Records to `moderator_validations.json`.
- **Mode B — Random validation.** Stratified-by-branch random pick from
  the live snapshot. Per-axis editable text input pre-filled with
  pipeline label. Confirms-by-default, corrects-when-wrong. Each
  submit appends to `moderator_validations.json`.
- **Stats panel — per-axis Cohen's κ.** For every axis with N≥10
  validations, computes Cohen's κ between pipeline_label and
  moderator_label. Below threshold shows %agreement only.

The κ helper (`_cohens_kappa`) is closed-form, no sklearn dep,
~20 LOC. Anchored in tests against the Sim-Wright (2005) BMC textbook
example (κ ≈ 0.1304, asserted to ±0.01).

### 6e. Promotion script

`scripts/promote_consensus_flags.py` is the moderator-side closing
of the loop. Default dry-run; `--apply` mutates `llm_overrides.json`;
`--close-issues` also tags the issue moderator-approved + closes it.
`--require-moderator-approval` adds a gate that requires the NCT to
appear in `moderator_validations.json` with a flag-source Approve
decision (strongly recommended for routine use).

8 unit tests cover patch construction (insert vs update),
unsupported-axis handling (SponsorType doesn't live in the override
file), and NCT extraction from issue title/body.

### 6f. Moderation tab fixture for testing

The κ helper in `_cohens_kappa` is testable standalone — the test file
AST-extracts just that function from `app.py` and execs it in
isolation, avoiding a full Streamlit import. Pattern is in
`tests/test_moderator_helpers.py` — copy-paste it.

---

## Definition of done

A successful port satisfies all of:

- [ ] All trial tables (Data, Geography city, every Deep Dive sub-tab)
      are click-to-drill-down via the shared helper
- [ ] By-product and by-sponsor drilldowns are two-step (table → trials → drill)
- [ ] By-sponsor has search + full scrollable list (no top-N cap)
- [ ] Deep Dive has a By-target sub-tab with landscape + single-antigen modes
- [ ] Every trial card has a Suggest-correction expander that link-outs to GitHub
- [ ] Trial tables show a Flag column reflecting open GitHub-issue counts
- [ ] `flag_consensus.yml` workflow auto-applies `consensus-reached` label
- [ ] Private Moderation tab renders triage + random-validation + κ stats
- [ ] `scripts/promote_consensus_flags.py` dry-runs cleanly against a
      real test issue
- [ ] All 6 features have unit tests (κ helper, parser, patch builder,
      Methods text antigen list)
- [ ] CHANGELOG entry written, version bumped, CITATION.cff updated

## Non-goals

- **No OAuth in the dashboard.** Auth happens on github.com when the user
  clicks the link-out button. Our app never sees a token.
- **No auto-promote.** The moderator queue is a hard gate. Even
  consensus-reached issues need a manual click.
- **No private database.** Everything is GitHub Issues + a single JSON
  log file (`moderator_validations.json`) committed to the repo.

## Estimated effort

- Items 1–4: half-day each, mostly mechanical, ~600 LOC total
- Item 5: full day, ~250 LOC
- Item 6: 2 days end-to-end (the moderation tab is the long pole)

Total: ~5 days for one engineer, faster if the porter is comfortable
with copy-pasting from the oncology repo (which is the recommended
approach for everything except the antigen list in #5).

---

*This brief is a snapshot in time. Pin to commit `f006d8e` of the
oncology repo (the C10 commit that closes the flagging loop) for the
exact code referenced above.*
