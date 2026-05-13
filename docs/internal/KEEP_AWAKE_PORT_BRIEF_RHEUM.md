# Rheum port — keep deployed Streamlit Cloud app awake

Paste the section between `--- BEGIN PROMPT ---` and `--- END PROMPT ---`
into a fresh Claude Code session in the **car-t-rheumatology-monitor** repo.
Self-contained, no other context needed.

## Decision history (onc side)

| Date | Approach | Outcome |
|---|---|---|
| 2026-05-07 (morning) | GH Actions cron `curl`-pings the deploy URL every 30 min | Committed, then reverted same day in favour of UpTimeRobot |
| 2026-05-07 (afternoon) | UpTimeRobot HTTP monitor every 5 min (no in-repo config) | **Did not work** — Streamlit Cloud classified bot pings as non-session activity; container kept sleeping |
| 2026-05-07 (evening) | GH Actions scheduled **empty push** every 6h, forces redeploy | Current onc-side path; works because Streamlit Cloud webhook fires on any push to main, triggering a fresh container build |

UpTimeRobot URL-pings are dead — moving on. Empty-push approach is what
the brief below ports.

---

--- BEGIN PROMPT ---

The onc sister monitor's keep-awake path went through two iterations
before landing: (1) GH Actions URL-ping → reverted in favour of
UpTimeRobot, (2) UpTimeRobot → didn't keep the container warm
(Streamlit Cloud classified the GETs as bot traffic). The working
approach is **scheduled empty push** via GitHub Actions, forcing a
Streamlit Cloud redeploy every 6 hours. This brief ports that fix.

## Why empty-push works when URL pings don't

- Streamlit Cloud watches the repo via webhook. Any push to main —
  including empty commits — triggers a fresh container build (~2-3 min).
- A freshly-rebuilt container resets the sleep timer to zero.
- URL pings (whether from `curl` or UpTimeRobot) get classified as
  bot-style GETs; Streamlit's sleep heuristics ignore them.
- Trade-off: each empty push = ~2-3 min cold-start latency for any
  visitor loading during the rebuild window. At 6-hour cadence, ~12
  min/day of potential downtime — acceptable for ad-hoc-demo dashboards.

## Setup (one-file commit, ~3 min)

Create `.github/workflows/keep-awake.yml` with this content (verbatim):

```yaml
name: Keep-awake (scheduled empty push)

on:
  schedule:
    - cron: '17 */6 * * *'   # every 6 hours, offset from :00 to dodge cron-storm
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: keep-awake
  cancel-in-progress: true

jobs:
  empty-push:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: main
          fetch-depth: 0
          token: ${{ secrets.GITHUB_TOKEN }}
      - run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
      - run: |
          TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
          git commit --allow-empty -m "ci(keep-awake): scheduled empty push at ${TS}"
          git push origin main
```

That's it. No secrets to configure (uses the default `GITHUB_TOKEN`).
No external service. No UpTimeRobot account to maintain.

## Cadence tuning

Default `'17 */6 * * *'` = every 6 hours at minute :17 (the offset
avoids GH's :00 cron-storm window where runs get queued):

| Cadence | Cron | CI min/mo | When to use |
|---|---|---|---|
| Every 6h (default) | `17 */6 * * *` | ~480 | App rarely sleeps within 6h of last redeploy |
| Every 3h (aggressive) | `17 */3 * * *` | ~960 | App still cold when collaborators visit at random times |
| Every 12h (conservative) | `17 */12 * * *` | ~240 | You're already pushing real commits daily — this is just a safety net |

All three fit within GH Actions free tier (2000 min/mo for private repos;
unlimited for public). For private repos with other CI workloads, watch
the cumulative usage.

## Verification

After committing the workflow file:

1. Wait for the next scheduled run (or trigger manually via Actions tab
   → "Keep-awake (scheduled empty push)" → "Run workflow").
2. Check the Actions tab — should show a green run with one empty
   commit. Run log should show `Create empty commit and push` succeed.
3. Check the repo's commit history on main — should show
   `ci(keep-awake): scheduled empty push at YYYY-MM-DDTHH:MM:SSZ`
   commits at the chosen cadence.
4. Visit the deployed Streamlit Cloud URL ~5 min after a scheduled
   push completes — should load instantly (just-rebuilt container).

## When this is NOT enough

- **Container still goes stale despite 6h pings** — drop cadence to 3h
  (single-character cron edit: `17 */6 * * *` → `17 */3 * * *`).
- **Even 3h cadence isn't enough** — Streamlit Cloud's sleep heuristics
  may have tightened. Options:
  - Streamlit Cloud's paid "Cloud for Teams" (no sleep guaranteed)
  - Real-browser ping via Playwright on GH Actions
    (exercises the page like a user, not a bot)
- **Pushes show up in commit history annoyingly** — the
  `ci(keep-awake): ...` prefix is grep-able for filtering with
  `git log --invert-grep --grep='keep-awake'`. Or push to a separate
  branch (but then Streamlit Cloud won't redeploy — defeats the purpose).
- **You're publishing the repo + don't want auto-bot commits in the
  citation history** — exclude them from the citable-snapshot tagging
  pipeline (filter by author email `41898282+github-actions[bot]`).

## Why NOT GitHub Pages-style staging redeploys

Considered: deploy to a staging branch that auto-redeploys via Streamlit
Cloud, while main stays clean. Streamlit Cloud doesn't support multi-
branch deploys in the free tier (one app per branch, configured at app
creation). Plus: the citation DOI references main's commit SHA, so
keeping main as the live data path is correct.

## Commit / config artifact

This brief lives in onc at `docs/internal/KEEP_AWAKE_PORT_BRIEF_RHEUM.md`.
The workflow file `.github/workflows/keep-awake.yml` is the actual
deployment artifact — one file, ~30 lines including comments.

--- END PROMPT ---
