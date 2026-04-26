# Rheum app port — paste-ready Claude prompt

Open a fresh Claude Code session in the **rheum-car-t-trial-monitor** repo
and paste everything below the `--- BEGIN PROMPT ---` line. It's
self-contained — no other context needed.

---

--- BEGIN PROMPT ---

I want you to port six features from the sister oncology app
(github.com/ptjeong/ONC-CAR-T-Trials-Monitor) into this rheum repo.
Everything you need is in that repo at the listed commit SHAs — read
the diffs first, then port them here with rheum-specific tweaks.

## Goal

Bring this rheum app to functional parity with the oncology monitor's
2026-04-25 release (v0.5.0). Six features, in dependency order:

1. **Row-click trial drilldown helper** (onc commit `202f2fa`)
   Extract `_render_trial_drilldown(record, *, key_suffix="")` from
   the Data tab. It renders a per-trial detail card and a Suggest-
   correction expander (added in step 6a). Used everywhere.

2. **Geography city-trials drilldown** (onc commit `587bf16`)
   Wire the helper into the city-zoom trial table. Look up the full
   record in `df_filt` (not the country-subset view) so the card has
   all columns. Use `key_suffix=f"geo_city_{country}_{city}"`.

3. **Deep Dive by-disease + by-product drilldowns** (onc commit `421fdd8`)
   By-disease is single-step. By-product is two-step: product pivot →
   trial list → drilldown. The trial list's dataframe key MUST include
   the picked product name or it caches the wrong selection.

4. **Deep Dive by-sponsor improvements** (onc commit `d164813`)
   Drop the `.head(10)` cap. Add a `st.text_input("Search sponsor")`
   above the table. Make the sponsor list selectable. Two-step drill
   like by-product.

5. **NEW Deep Dive sub-tab — By target** (onc commit `5e6553b`)
   ~250 LOC. Two modes: landscape (top-25 antigens table) and
   single-antigen focus (4 metrics + 2x2 panel grid: top diseases /
   phase / modality / top sponsors + click-to-drill trial list +
   CSV download).

   **Rheum-specific antigen list:** the oncology version EXCLUDES
   platform labels (CAAR-T, CAR-Treg) from the antigen picker because
   they're not antigens. For rheum, **KEEP** CAAR-T and CAR-Treg —
   they're central modalities here. The exclusion list should be just
   `("Other_or_unknown",)`. Also keep CD19 and BCMA — they appear
   off-label in lupus / myasthenia / RA trials.

6. **Community classification-flag system, full loop** (onc commits
   `b4402d1`, `8ed8787`, `76bdfc4`, `816dcef`, `f006d8e`)
   The headline feature. Six sub-parts:

   6a. **Suggest-correction form** on every trial card. Renders inside
       `_render_trial_drilldown`. Multiselect axes + per-axis correction
       widget + free-text rationale + `st.link_button` that opens a
       pre-filled GitHub issue at this rheum repo's URL. Title format:
       `[Flag] NCT01234567 — axes`. Body contains a markdown table for
       humans + a `<!-- BEGIN_FLAG_DATA … END_FLAG_DATA -->` YAML block
       for the consensus-detection workflow.

       **Rheum-specific:** change `GITHUB_REPO_SLUG` to
       `ptjeong/rheum-car-t-trial-monitor`. The `_FLAG_AXIS_OPTIONS`
       dict needs rheum branches (Lupus / Myasthenia / RA / Other-rheum)
       and the rheum-specific TargetCategory list (CD19, BCMA, CD20,
       CAAR-T, CAR-Treg, …).

   6b. **Flag-badge column** on every trial table. Cached fetch via
       `_load_active_flags()` (5-min TTL hits public GitHub Issues API).
       `_attach_flag_column(df, show_cols)` helper prepends a `_Flag`
       column populated by `_flag_badge(flags.get(nct))`. Apply it at
       every `st.dataframe(...)` for a trial table.

   6c. **GitHub Action for consensus detection.** Copy
       `.github/workflows/flag_consensus.yml` and
       `scripts/detect_flag_consensus.py` from the onc repo verbatim.
       The script is repo-agnostic — only env vars (REPO_SLUG, etc.)
       differ. Add `tests/test_flag_consensus.py` (8 parser tests)
       also verbatim.

   6d. **Private Moderation tab.** Token-gated via
       `?mod=<MODERATOR_TOKEN>` env var or
       `st.secrets["moderator_token"]`. Three sections:
         - Mode A: triage consensus-reached issues (Approve/Reject/Defer)
         - Mode B: stratified random validation when no flags pending
         - Stats: per-axis Cohen's κ (helper `_cohens_kappa`, 7 tests)

       **Rheum-specific:** the `_MODERATOR_AXES` tuple should mirror
       the rheum app's actual classification axes (probably the same
       6 as onc, but verify against rheum's `pipeline.py` schema).

   6e. **Promotion script** at `scripts/promote_consensus_flags.py`.
       Default dry-run. `--apply` mutates `llm_overrides.json`.
       `--close-issues` tags + closes the GitHub issue. The
       `AXIS_TO_OVERRIDE_FIELD` dict maps human-readable axis names to
       the snake_case JSON field names — check rheum's
       `llm_overrides.json` schema and adjust if field names differ.
       Add `tests/test_promote_consensus.py` (8 patch-builder tests).

   6f. **Issue template** at
       `.github/ISSUE_TEMPLATE/classification_flag.md` documenting the
       BEGIN_FLAG_DATA YAML schema other reviewers must follow when
       adding their assessment as a comment.

## How to read the onc repo

Don't blindly copy — first **read** the relevant onc commits to see
the exact code:

```bash
gh repo clone ptjeong/ONC-CAR-T-Trials-Monitor /tmp/onc-monitor
cd /tmp/onc-monitor && git log --oneline 202f2fa^..92fbb0f
```

For each commit, run `git show <sha>` to see the diff. Then translate
to this rheum repo. The shape is the same; only the column lists,
axis enums, and antigen exclusion logic change.

There's also a more detailed brief at
`docs/internal/RHEUM_APP_KICKOFF.md` in the onc repo (commit
`b49f50e`) — read that too for the full design rationale and
copy-pasteable code skeletons.

## Definition of done (check each before marking complete)

Functional:
- [ ] All trial tables (Data, Geography city, every Deep Dive sub-tab)
      are click-to-drill-down via the shared helper
- [ ] By-product and by-sponsor drilldowns are two-step
- [ ] By-sponsor has search + full scrollable list
- [ ] Deep Dive has a By-target sub-tab with both modes
- [ ] Every trial card has a Suggest-correction expander linking out
      to a pre-filled GitHub issue at this rheum repo
- [ ] Trial tables show a Flag column
- [ ] `.github/workflows/flag_consensus.yml` deployed and labeled
      issues hit `consensus-reached` after 3 distinct YAML-block votes
- [ ] Moderation tab renders only with `?mod=<token>` matching server-
      side `MODERATOR_TOKEN`
- [ ] `scripts/promote_consensus_flags.py --help` works; `--require-
      moderator-approval` gates by `moderator_validations.json`

Tests + governance:
- [ ] All ported unit tests pass (~23 new tests across 3 files)
- [ ] `python3 -m pytest tests/` is green
- [ ] CHANGELOG entry mirrors onc's `[0.5.0]` section, adapted for
      rheum scope
- [ ] CITATION.cff bumped to a matching version
- [ ] No `st.secrets.get(...)` calls without try/except (raises if
      no secrets.toml exists; would silently break the test suite —
      this was a real bug in the onc port, fixed in commit `816dcef`)
- [ ] No emojis added unless they were in the original onc commits

## GitHub repo configuration (one-time, before first flag is filed)

Tell me when you're ready and I'll generate the `gh label create`
commands. Labels needed: `classification-flag`, `consensus-reached`,
`moderator-approved`, `axis-Branch`, `axis-DiseaseCategory`,
`axis-DiseaseEntity`, `axis-TargetCategory`, `axis-ProductType`,
`axis-SponsorType`, `needs-review`.

Streamlit Cloud secret needed: `moderator_token` (any long random
string; I'll never see it — this is for you to set in Streamlit
Cloud's Settings → Secrets).

## Non-goals

- **No OAuth in the dashboard.** Auth happens on github.com when the
  user clicks the link-out button. The app never sees a token.
- **No auto-promote.** Even consensus-reached issues need a manual
  click in the Moderation tab + `--require-moderator-approval` on
  the promotion script.
- **No private database.** Everything is GitHub Issues + a single JSON
  log file (`moderator_validations.json`) committed to this repo.
- **Do not make tests less strict.** When you find disagreement
  between this rheum app and the porting target, fix the rheum app or
  flag it to me — don't loosen the test threshold or add `# noqa`.

## Workflow

Plan the port commit-by-commit, mirroring the onc commit structure
(C1 through C11). Run tests after every commit. Push when each commit
is green. **Don't batch — small commits make the rheum CHANGELOG
readable later.**

Estimated 5 days of focused work. Commits 1-4 are mechanical (~half
day each). C5 is the largest pure feature (~1 day). C6 is the long
pole (~2 days for the full loop with tests).

Start by reading the onc repo at `b49f50e` (the C11 RHEUM_APP_KICKOFF
brief) and `f006d8e` (the C10 closing of the loop). Then build a plan
and start with C1.

--- END PROMPT ---

## Bonus: bash to set up the rheum GitHub labels in one shot

After the port is done, run this from inside the rheum-car-t-trial-monitor repo:

```bash
gh label create "classification-flag" --color "d93f0b" --description "User-suggested classification correction"
gh label create "consensus-reached" --color "0e8a16" --description "≥3 reviewers agree on the same correction"
gh label create "moderator-approved" --color "5319e7" --description "Promoted to llm_overrides.json"
gh label create "needs-review" --color "fbca04" --description "Awaiting community input"
gh label create "axis-Branch" --color "c5def5"
gh label create "axis-DiseaseCategory" --color "c5def5"
gh label create "axis-DiseaseEntity" --color "c5def5"
gh label create "axis-TargetCategory" --color "c5def5"
gh label create "axis-ProductType" --color "c5def5"
gh label create "axis-SponsorType" --color "c5def5"
```

Run the same in the onc repo if those labels aren't there yet.
