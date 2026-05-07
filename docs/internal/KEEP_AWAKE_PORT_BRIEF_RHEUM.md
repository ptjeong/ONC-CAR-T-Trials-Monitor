# Rheum port — keep-awake GitHub Actions workflow

Paste the section between `--- BEGIN PROMPT ---` and `--- END PROMPT ---`
into a fresh Claude Code session in the **car-t-rheumatology-monitor** repo.
Self-contained, no other context needed.

Onc-side commit (reference): added 2026-05-07 alongside the
`README` refresh / dual-push cycle. Path: `.github/workflows/keep-awake.yml`.

---

--- BEGIN PROMPT ---

The onc sister monitor just added a GitHub Actions cron workflow that
pings the deployed Streamlit Cloud URL every 30 minutes to suppress
Streamlit's sleep timer. Port the same workflow here with the
rheum-specific URL.

## Why

Streamlit Community Cloud puts apps to sleep after a few hours of
inactivity (full eviction after ~7 days). First visitor pays a
~30-60 s cold-start. For a research dashboard that gets ad-hoc
collaborator visits, that cold-start is a real friction point —
especially when sharing the URL during a meeting.

The fix is a cron-based HTTP ping that keeps the container warm.
Costs nothing on a public repo (GH Actions minutes are unlimited
for public).

## What to add

Single new file: `.github/workflows/keep-awake.yml`. Drop in the
contents below verbatim, then update the `URL=` line to the rheum
deploy URL.

```yaml
name: Keep deployed Streamlit Cloud app awake

# Streamlit Community Cloud puts apps to sleep after a few hours of
# inactivity (full eviction after ~7 days). First visitor pays a
# ~30-60s cold-start cost when the container has been evicted. This
# workflow pings the deployed URL every 30 minutes to suppress the
# inactivity timer, so collaborators and reviewers don't hit the
# cold start.
#
# Cost: GitHub-hosted-runner minutes are unlimited on PUBLIC repos
# and capped at 2,000/mo on private. This workflow uses ~5-10 s per
# run × 48 runs/day × 30 days ≈ 2 hours/month — negligible either way.
#
# Caveat: Streamlit Cloud's sleep detection uses real session activity,
# not just HTTP requests. Bare `curl` may not always count as activity.
# If the app still goes to sleep despite this workflow, upgrade to a
# Puppeteer-on-Actions browser ping or use UpTimeRobot's full-page
# monitor instead.

on:
  schedule:
    - cron: '*/30 * * * *'
  workflow_dispatch:

jobs:
  ping:
    runs-on: ubuntu-latest
    timeout-minutes: 2
    steps:
      - name: Wake the Streamlit Cloud deploy
        run: |
          set -eo pipefail
          URL="<RHEUM_DEPLOY_URL_HERE>"
          echo "Pinging $URL"
          STATUS=$(curl -fsSL --max-time 60 -o /dev/null -w "%{http_code}" "$URL" || echo "000")
          echo "HTTP $STATUS"
          if [ "$STATUS" = "000" ]; then
            echo "::error::Could not reach $URL"
            exit 1
          fi
```

Replace `<RHEUM_DEPLOY_URL_HERE>` with the actual rheum URL (likely
something like `https://car-t-rheum-monitor.streamlit.app` — check
the README or the deploy in the Streamlit Cloud dashboard).

## Verification

After commit + push:

1. Go to the repo's Actions tab → confirm the workflow appears as
   "Keep deployed Streamlit Cloud app awake" with a green run on the
   first manual trigger.
2. Click "Run workflow" once manually to verify the curl returns
   HTTP 200 (or 503 during wake transition — both fine).
3. Wait ~30 min for the first scheduled run; check the Actions log.

Expected log output:

```
Pinging https://...
HTTP 200
```

## When this is NOT enough

If the app continues to go to sleep despite the 30-min ping (some
Streamlit Cloud edge cases require real browser session activity to
suppress the sleep timer), escalate to:

* **UpTimeRobot full-page monitor** — sign up at uptimerobot.com,
  add a "Page Speed" monitor (loads the full HTML, not just HEAD)
  with a 5-min interval. Free tier supports 50 monitors. Bonus:
  email alerts when the URL is actually down.
* **Streamlit Cloud paid tier** — guarantees no sleep, faster
  cold-starts, custom domains. Worth it if collaborator traffic
  becomes routine.

## Commit message suggestion

```
ci: add keep-awake workflow — ping Streamlit deploy every 30 min

Streamlit Community Cloud sleeps inactive apps after a few hours
(full eviction after ~7 days). First visitor pays a ~30-60s
cold-start. Workflow pings the deploy URL every 30 min to suppress
the sleep timer, eliminating the cold-start for collaborator visits.

Cost: ~2 hrs/month of GH Actions minutes (unlimited on public repos).

Ported from onc sister monitor commit <sha>.
```

--- END PROMPT ---
