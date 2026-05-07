# Rheum port — keep deployed Streamlit Cloud app awake

Paste the section between `--- BEGIN PROMPT ---` and `--- END PROMPT ---`
into a fresh Claude Code session in the **car-t-rheumatology-monitor** repo.
Self-contained, no other context needed.

Onc-side decision (2026-05-07): **UpTimeRobot** as the keep-awake path.
GitHub-Actions cron was considered and briefly committed, but removed
once the maintainer set up UpTimeRobot — pinging twice would be
redundant and waste runner minutes for no gain.

---

--- BEGIN PROMPT ---

The onc sister monitor recently set up UpTimeRobot to keep its
Streamlit Cloud deploy from going to sleep. Same fix should apply
on the rheum side. This brief is a no-code config recipe — you just
need to sign up for UpTimeRobot and add a single monitor.

## Why

Streamlit Community Cloud puts apps to sleep after a few hours of
inactivity (full eviction after ~7 days). First visitor pays a
~30-60 s cold-start. For a research dashboard shared ad-hoc with
collaborators, that cold-start is a real friction point — especially
if you're sharing the URL during a meeting.

UpTimeRobot's free tier supports 50 HTTP monitors with a 5-minute
check interval. Pinging the deploy URL every 5 min keeps the
container warm AND gives you uptime alerts as a side benefit
(email when the URL is actually down, not just sleeping).

## Setup (no-code, ~5 min)

1. Sign up at [uptimerobot.com](https://uptimerobot.com) — free tier
   is fine.
2. Click "+ New monitor".
3. Configure:
   * **Monitor type**: HTTP(s) (the default)
   * **Friendly name**: `Rheum CAR-T Trials Monitor — keep-awake`
   * **URL**: the rheum deploy URL (likely
     `https://<your-app>.streamlit.app` — confirm in the Streamlit
     Cloud dashboard)
   * **Monitoring interval**: 5 minutes (the most aggressive free-tier
     setting; 30 min would also work but 5 min keeps the container
     warmer and gives better alert resolution)
   * **HTTP method**: GET (HEAD might not count as session activity)
   * **Alert contacts**: your email — leave the default "When down,
     when up, when SSL expires" alerts on
4. Save.

## Verification

* Within 5 min the dashboard should show a green dot + "Up" status
  for the new monitor.
* Visit the deployed URL the next morning (or after a long quiet
  period) — should load instantly, no cold-start spinner.
* Check the UpTimeRobot dashboard's "Response time" graph — should
  show consistent response under ~2 s; spikes to ~30 s would
  indicate the app went to sleep and the ping just woke it up.

## Why NOT GitHub Actions cron

Considered on the onc side, briefly committed (a
`.github/workflows/keep-awake.yml` curl ping every 30 min), then
removed when UpTimeRobot was set up. Reasons UpTimeRobot is better:

* **5-min interval vs 30-min** — keeps the container warmer
* **Real HTTP-session activity** — UpTimeRobot does a full GET
  and parses the response; bare `curl` from GH Actions is more
  likely to be classified as bot traffic by Streamlit's sleep
  detection
* **Free uptime alerts** — email when the URL is actually down,
  not just sleeping
* **No code maintenance** — no YAML to keep in sync with workflow
  schema changes

The GH Actions path is still viable as a fallback if you don't
want to depend on a third-party service; ping me for the YAML.

## When this is NOT enough

* **You hit UpTimeRobot's free-tier ceiling (50 monitors)** —
  upgrade to their paid tier ($7-15/mo) or split monitors across
  multiple accounts.
* **The app still goes to sleep despite 5-min pings** — Streamlit
  Cloud occasionally tightens sleep heuristics. Escalate to
  Streamlit Cloud's paid "Cloud for Teams" tier (no sleep
  guaranteed) or use a real-browser ping (Puppeteer / Playwright on
  GH Actions).

## Commit / config artifact

UpTimeRobot is configured outside the repo, so there's no commit
to make. If you want a record in the repo, add a one-liner to the
README under "Operations" or similar:

```markdown
### Keep-awake

Streamlit Cloud deploy is pinged every 5 min by an UpTimeRobot HTTP
monitor (no in-repo config). Disable / reconfigure at
uptimerobot.com under monitor `<friendly name>`.
```

--- END PROMPT ---
