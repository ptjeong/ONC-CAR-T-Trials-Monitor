# Direct-to-main fast-iteration workflow

Imported from the rheum sister monitor 2026-05-06 — applies here in
the same pre-public iteration regime (sole-maintainer Peter Jeong,
URL not yet shared with collaborators / not yet citation-anchored).

## When this applies (onc-side)

* Streamlit Cloud auto-redeploys from `main` (~60-120s lag); the
  deployed app reflects every commit without PR-merge overhead.
* Fast iteration: edit → commit → push (both refs) → refresh deploy.
* Maintainer-as-sole-user regime; no patient-facing claim, no
  pre-registered analysis locked to a specific commit.

## When NOT (revert to PR flow)

* Pre-print, manuscript, or DOI cites a specific commit.
* External users hit the URL routinely.
* Inter-rater κ validation pipeline is locked to a sample sha256.
* `main` gets branch protection / required CI checks.

## The command

```bash
git push origin <branch> <branch>:main 2>&1 | tail -5
```

Pushes the branch tip to BOTH `origin/<branch>` and `origin/main` in
one invocation. Both refs land at the same SHA.

## First-time merge gotcha

If `main` has commits the branch doesn't (previous PR-merged work),
the direct push to main will be rejected with `[rejected] (fetch first)`.
Fix:

```bash
git fetch origin
git merge origin/main --no-edit
git push origin <branch> <branch>:main
```

After this, branch tracks main; subsequent commits push cleanly.

## Verification after push

```bash
git log --oneline -1                    # local HEAD
git ls-remote origin main <branch>      # both refs at same SHA?
git status -sb                          # no [ahead N] marker?
```

## When the runtime denies the push

The Claude Code harness blocks direct-main pushes by default. Path through:

1. User grants permission interactively, OR
2. User types something equivalent to "push to main" / "push directly"
   / "deploy this" / explicitly authorises the dual-push pattern.

User authorisation pattern from rheum: *"can you push also directly to
main? the website isnt public yet, so we can still tinker"*. After
that, subsequent pushes go through without re-asking.

## Streamlit Cloud rebuild check

If the user doesn't see the change after ~2 min:

1. Check `requirements.txt` — new imports must be pinned (kaleido was a
   real gotcha here: pinned, then unpinned when SVG moved to the
   browser-side modebar path).
2. Suggest "Manage app" → "Reboot app" in the Streamlit Cloud
   dashboard to force a fresh container.
3. Hard-refresh the browser tab (Cmd+Shift+R) — Streamlit Cloud
   sometimes serves a cached HTML shell.

## Commit-message convention

For changes that touch both apps, prefix with `cross-app:` or
`round-N:` so the parallel session can grep for sync-relevant
commits. Adopted in onc 2026-05-06.
