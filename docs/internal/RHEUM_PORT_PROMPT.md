# Rheum app port — paste-ready Claude prompt

Open a fresh Claude Code session in the **rheum-car-t-trial-monitor** repo
and paste everything below the `--- BEGIN PROMPT ---` line. It's
self-contained — no other context needed.

Pinned to onc commit `5c201db` (HEAD as of 2026-04-26 after the
flag-UX refactor + dead-code cleanup).

---

--- BEGIN PROMPT ---

I want you to port six features from the sister oncology app
(github.com/ptjeong/ONC-CAR-T-Trials-Monitor) into this rheum repo.
Pin to commit `5c201db` of the onc repo — that's HEAD as of the
moment this prompt was written and includes the final flag-UX
refactor (inline 🚩 prefix, not a reserved column).

## Goal

Bring this rheum app to functional parity with the oncology monitor's
2026-04-26 state (v0.5.0 + the flag-UX patch). Six features in
dependency order:

### 1. Row-click trial drilldown helper (onc commit `202f2fa`)

Extract `_render_trial_drilldown(record, *, key_suffix="")`. Renders
a per-trial detail card. Three layers:
  - **Flag banner** at the top (covered in step 6 — until then,
    wrap the call in `try/except NameError` for forward-compat)
  - Two-column metadata table
  - Free-text payload (BriefSummary, eligibility, locations)
  - Suggest-correction expander at the bottom

Used everywhere a single trial is rendered.

### 2. Geography city-trials drilldown (onc commit `587bf16`)

Wire the helper into the city-zoom trial table. Look up the full
record in `df_filt` (not the country-subset view) so the card has
all columns. Use `key_suffix=f"geo_city_{country}_{city}"`.

### 3. Deep Dive by-disease + by-product drilldowns (onc commit `421fdd8`)

By-disease is single-step. By-product is **two-step**: product pivot →
trial list → drilldown. The trial list's dataframe `key=` MUST include
the picked product name or it caches the wrong selection across picks.

### 4. Deep Dive by-sponsor improvements (onc commit `d164813`)

Three changes:
- Drop the `.head(10)` cap on the sponsor list (full scrollable)
- Add `st.text_input("Search sponsor")` filter (case-insensitive
  substring on LeadSponsor)
- Make the sponsor list selectable; same two-step drill as by-product

### 5. NEW Deep Dive sub-tab — By target (onc commit `5e6553b`)

~250 LOC. Two modes:

**Landscape** (no antigen selected): top-25 antigens table with trial
counts, modality split, disease-area breadth, top sponsor.

**Single-antigen focus**: 4 metric tiles + 2×2 panel grid (top
diseases / phase / modality / top sponsors) + click-to-drill trial
list + CSV download.

**RHEUM-SPECIFIC ANTIGEN LIST.** The onc version EXCLUDES platform
labels (CAAR-T, CAR-Treg) from the antigen picker because they're not
antigens in oncology. **For rheum, KEEP CAAR-T and CAR-Treg** — they're
central modalities here. Also keep CD19 / BCMA — they appear off-label
in lupus / myasthenia / RA trials. The exclusion list should be just
`("Other_or_unknown",)` for rheum.

### 6. Community classification-flag system, full loop

Six sub-parts. The HEADLINE feature.

#### 6a. Suggest-correction form (onc commit `b4402d1`)

Inside `_render_trial_drilldown`. Multiselect axes + per-axis correction
widget + free-text rationale + `st.link_button` opening a pre-filled
GitHub issue at THIS rheum repo's URL.

Title format: `[Flag] NCT01234567 — axes`. Body contains a markdown
table for humans + a `<!-- BEGIN_FLAG_DATA … END_FLAG_DATA -->` YAML
block for parsers.

**RHEUM-SPECIFIC:**
- `GITHUB_REPO_SLUG = "ptjeong/rheum-car-t-trial-monitor"`
- `_FLAG_AXIS_OPTIONS` dict — rheum branches (Lupus / Myasthenia /
  RA / Other-rheum) and rheum-specific TargetCategory list
  (CAAR-T, CAR-Treg, CD19, BCMA, CD20, CD7, …)

#### 6b. Inline 🚩 prefix on flagged trials (onc commits `8ed8787`, `c3e2388`)

**IMPORTANT — read both commits.** The first added a dedicated `_Flag`
column. The second (one day later, after UX feedback) **replaced** the
column with an inline 🚩 prefix on `BriefTitle` + a banner in the
drilldown. **Implement the second version, not the first** — the column
approach wasted ~5% of every table's width for an empty cell 99% of
the time.

The inline approach has 4 pieces:

1. **`_attach_flag_column(df, show_cols)`** — DESPITE THE NAME, this
   function no longer adds a column. It modifies `BriefTitle` in place
   to prepend `🚩 ` for trials in the cached flag set. Idempotent
   (re-applying doesn't produce 🚩 🚩 Title). Returns `(df, show_cols)`
   tuple unchanged. Function name is kept stable so the 5+ call sites
   don't have to change.

2. **`_render_flag_banner(record)`** — called from inside
   `_render_trial_drilldown` at the very top. `st.error` for
   consensus-reached, `st.warning` for open flags. Below the alert,
   shows an inline table: `Axis | Current label | Proposed correction
   | Discussion (link)`. Uses `_load_flag_issue_details` (cached, see
   below) to fetch each issue's body and parse the BEGIN_FLAG_DATA
   YAML blocks so the user sees what's being challenged without
   leaving the app.

3. **`_load_flag_issue_details(issue_url)`** — `@st.cache_data(ttl=300)`
   fetch of a single issue's body via the public GH API. Parses the
   YAML blocks inside; tries `yaml.safe_load` first, falls back to
   regex if pyyaml is unavailable. Add `pyyaml>=6.0` to
   requirements.txt.

4. **"🚩 Flagged only (N)" checkbox** on the Data tab. Lives in a
   third column alongside the search box and country zoom. Live count;
   `disabled=True` when N=0 so it's not a tease.

Also: `_load_active_flags()` (the 5-min cached fetch of the open-issue
list) is shared between the prefix logic and the banner.

#### 6c. GitHub Action for consensus detection (onc commit `76bdfc4`)

Copy `.github/workflows/flag_consensus.yml` and
`scripts/detect_flag_consensus.py` verbatim. The workflow + script are
repo-agnostic — only env vars (REPO_SLUG) differ.

Add `tests/test_flag_consensus.py` (8 parser tests) verbatim.

#### 6d. Private Moderation tab (onc commit `816dcef`)

Token-gated via `?mod=<MODERATOR_TOKEN>` env var or
`st.secrets["moderator_token"]`. Three sections:
  - **Mode A**: Triage consensus-reached issues (Approve/Reject/Defer)
  - **Mode B**: Stratified-by-branch random-validation when no flags pending
  - **Stats**: Per-axis Cohen's κ (helper `_cohens_kappa` + 7 tests)

**RHEUM-SPECIFIC:** `_MODERATOR_AXES` — verify against rheum's
`pipeline.py` schema. Probably the same 6 (Branch / DiseaseCategory /
DiseaseEntity / TargetCategory / ProductType / SponsorType) but
double-check.

**CRITICAL BUG TO AVOID:** when wiring the moderator-mode gate, wrap
`st.secrets.get(...)` in try/except. It raises
`StreamlitSecretNotFoundError` if no secrets.toml exists, which will
silently SKIP your test_methods_text fixture and break CI without
any visible failure. The onc repo hit this exact bug — see commit
`816dcef`'s commit message for the fix pattern.

#### 6e. Promotion script (onc commit `f006d8e`)

`scripts/promote_consensus_flags.py`. Default dry-run; `--apply`
mutates `llm_overrides.json`; `--close-issues` tags + closes the
GitHub issue; `--require-moderator-approval` gates by
`moderator_validations.json`.

**RHEUM-SPECIFIC:** `AXIS_TO_OVERRIDE_FIELD` — check rheum's
`llm_overrides.json` schema for field names. Probably the same
snake_case mapping (`Branch` → `branch`, `TargetCategory` →
`target_category`, etc.) but verify.

Add `tests/test_promote_consensus.py` (8 patch-builder tests).

#### 6f. Issue template

`.github/ISSUE_TEMPLATE/classification_flag.md` — documents the
BEGIN_FLAG_DATA YAML schema other reviewers must follow. Verbatim
from onc, just change the example NCT and the repo URL in the
methods.md link at the bottom.

## How to read the onc repo

Don't blindly copy — first **read** the relevant onc commits:

```bash
gh repo clone ptjeong/ONC-CAR-T-Trials-Monitor /tmp/onc-monitor
cd /tmp/onc-monitor
git checkout 5c201db
git log --oneline 202f2fa^..5c201db
```

For each commit, run `git show <sha>` to see the diff. Translate to
this rheum repo. The shape is the same; only the column lists, axis
enums, antigen exclusion logic, and the `GITHUB_REPO_SLUG` change.

There's also a more detailed brief at
`docs/internal/RHEUM_APP_KICKOFF.md` in the onc repo (commit
`b49f50e`) — read that too for the full design rationale and
copy-pasteable code skeletons.

## Definition of done

Functional:
- [ ] All trial tables (Data, Geography city, every Deep Dive sub-tab)
      are click-to-drill-down via the shared helper
- [ ] By-product and by-sponsor drilldowns are two-step
- [ ] By-sponsor has search + full scrollable list
- [ ] Deep Dive has a By-target sub-tab with both modes
- [ ] Every trial card has a Suggest-correction expander linking out
      to a pre-filled GitHub issue at this rheum repo
- [ ] Flagged trials show 🚩 prefix in BriefTitle (NOT a separate column)
- [ ] Drilldown card opens with a flag banner showing proposed
      corrections inline, not just a count
- [ ] Data tab has a "🚩 Flagged only (N)" checkbox
- [ ] `flag_consensus.yml` workflow auto-applies `consensus-reached`
      label after 3 distinct YAML-block votes
- [ ] Moderation tab renders only with `?mod=<token>` matching
      server-side `MODERATOR_TOKEN`
- [ ] `scripts/promote_consensus_flags.py --help` works; `--require-
      moderator-approval` gates by `moderator_validations.json`

Tests + governance:
- [ ] All ported unit tests pass (~29 new tests across 4 files)
- [ ] `python3 -m pytest tests/` is green (target: 100+ tests)
- [ ] CHANGELOG entry mirrors onc's `[0.5.0]` + `[Unreleased]`
      flag-UX section, adapted for rheum scope
- [ ] CITATION.cff bumped to a matching version
- [ ] Every `st.secrets.get(...)` call wrapped in try/except (raises
      if no secrets.toml exists; would silently break the test suite)
- [ ] No emojis added unless they were in the original onc commits
      (the 🚩 IS in the onc commits — that's intentional)

## GitHub repo configuration

**Labels are auto-created.** Copy the
`.github/workflows/auto_label_flags.yml` workflow from the onc repo
(commit `4121d9a`) — it fires on every new flag issue and creates any
missing labels (`classification-flag`, `consensus-reached`,
`moderator-approved`, `axis-*`) before applying them. So the first
flag a user files in the rheum app will work end-to-end without you
running any `gh label create` setup commands.

**Why this matters:** GitHub silently drops any label in
`issues/new?labels=...` URL params that doesn't already exist in the
repo. Without the auto-label workflow, the first flag would be
filed with an empty labels array, the dashboard's `_load_active_flags`
filter would never see it, and the badge wouldn't render. The onc
app hit this bug live; the fix is the workflow.

In Streamlit Cloud (Settings → Secrets), add:
```toml
moderator_token = "pick-something-long-and-random"
```

## Non-goals

- **No OAuth in the dashboard.** Auth happens on github.com when the
  user clicks the link-out button. The app never sees a token.
- **No auto-promote.** Even consensus-reached issues need a manual
  click in the Moderation tab + `--require-moderator-approval` on
  the promotion script.
- **No private database.** Everything is GitHub Issues + a single JSON
  log file (`moderator_validations.json`) committed to this repo.
- **Do not loosen tests.** When you find disagreement between this
  rheum app and the porting target, fix the rheum app or flag it to
  me — don't loosen the test threshold or add `# noqa`.

## Workflow

Plan the port commit-by-commit, mirroring the onc commit structure
(C1 through C11 + the inline-prefix UX patch). Run tests after every
commit. Push when each commit is green. **Don't batch — small commits
make the rheum CHANGELOG readable later.**

The recommended commit order:

```
C1   202f2fa  Extract _render_trial_drilldown helper
C2   587bf16  Geography city-trials drilldown
C3+4 421fdd8  Deep Dive by-disease + by-product drilldowns
C5   d164813  By-sponsor: search + scroll + select
C6   5e6553b  Deep Dive sub-tab — By target
C7   b4402d1  Suggest-correction form + URL builder + issue template
C8a  8ed8787  Flag-badge column (initial — will be refactored in C8c)
C8b  76bdfc4  Consensus-detection GitHub Action
C8c  c3e2388  Flag UX refactor: column → inline prefix + banner + filter
C9   816dcef  Moderation tab + Cohen's κ
C10  f006d8e  promote_consensus_flags.py
```

**OR** skip C8a entirely and implement the final inline-prefix UX
directly. Cleaner history but you lose the option to roll back to
the column UX if you change your mind. Your call.

Estimated 5 days of focused work. Commits 1-4 are mechanical (~half
day each). C5 is the largest pure feature (~1 day). C6 is the long
pole (~2 days for the full loop with tests).

Start by reading the onc repo at `5c201db` (HEAD), then read the
detailed brief at `docs/internal/RHEUM_APP_KICKOFF.md`, then build
a plan and start with C1.

--- END PROMPT ---
