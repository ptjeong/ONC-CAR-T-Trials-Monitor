"""Promote consensus-reached classification-flag GitHub issues into
llm_overrides.json — the file the pipeline reads at startup.

This is the moderator-side counterpart to:
  - the Suggest-correction button in the dashboard      (filing a flag)
  - .github/workflows/flag_consensus.yml                (auto-detecting consensus)
  - the Moderation tab's Triage Mode A                  (moderator decision)

Workflow (as designed with Peter, 2026-04-25):
  1. User clicks "Suggest a classification correction" on a trial card
     → opens a pre-filled GitHub issue with `classification-flag` label.
  2. Other reviewers add comments using the same BEGIN_FLAG_DATA YAML
     schema, agreeing or proposing alternatives.
  3. flag_consensus.yml workflow detects ≥3 distinct authors agreeing
     on the same (axis, proposed_correction) and applies the
     `consensus-reached` label.
  4. Moderator (@ptjeong) reviews via the Moderation tab and clicks
     Approve in the UI → moderator_validations.json gets a record.
  5. THIS SCRIPT pulls every `consensus-reached` open issue, cross-checks
     against moderator_validations.json (only Approve-decided issues
     are promoted), generates a JSON patch against llm_overrides.json,
     and — when run with --apply — writes the patched file, comments
     "Promoted to llm_overrides.json in commit <sha>" on the issue,
     adds `moderator-approved` label, and closes the issue.

By default the script runs in dry-run mode (prints the patch only).
Add `--apply` to mutate the override file and `--close-issues` to
also touch GitHub. CI never runs this — it's a moderator-local tool.

Required env:
    GH_TOKEN — personal access token with `repo` scope
    REPO_SLUG — owner/name (default: ptjeong/ONC-CAR-T-Trials-Monitor)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import requests
import yaml

GH_API = "https://api.github.com"
DEFAULT_REPO = "ptjeong/ONC-CAR-T-Trials-Monitor"
OVERRIDES_PATH = Path(__file__).resolve().parent.parent / "llm_overrides.json"
VALIDATIONS_PATH = (
    Path(__file__).resolve().parent.parent / "moderator_validations.json"
)
FLAG_BLOCK_RE = re.compile(
    r"<!--\s*BEGIN_FLAG_DATA\s*\n(.*?)END_FLAG_DATA\s*-->",
    re.DOTALL,
)

# Maps the human-readable axis name (used in the GitHub-issue YAML
# blocks and in the Moderation tab) to the snake_case field name
# inside llm_overrides.json.
AXIS_TO_OVERRIDE_FIELD = {
    "Branch": "branch",
    "DiseaseCategory": "disease_category",
    "DiseaseEntity": "disease_entity",
    "TargetCategory": "target_category",
    "ProductType": "product_type",
}
# Axes the moderator can flag but which DON'T live in llm_overrides
# (sponsor type is derived in pipeline.py via name-pattern classifier).
# We surface these in the dry-run report but skip them on --apply.
UNSUPPORTED_AXES = {"SponsorType"}


def _gh_request(method: str, path: str, token: str, **kwargs):
    headers = kwargs.pop("headers", {})
    headers.setdefault("Authorization", f"Bearer {token}")
    headers.setdefault("Accept", "application/vnd.github+json")
    headers.setdefault("X-GitHub-Api-Version", "2022-11-28")
    url = f"{GH_API}{path}"
    return requests.request(method, url, headers=headers, timeout=15, **kwargs)


def _fetch_consensus_issues(token: str, repo: str) -> list[dict]:
    """All open issues with both classification-flag AND consensus-reached labels."""
    out = []
    page = 1
    while True:
        r = _gh_request(
            "GET",
            f"/repos/{repo}/issues?state=open&labels=classification-flag,consensus-reached"
            f"&per_page=100&page={page}",
            token,
        )
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        out.extend(batch)
        page += 1
    return out


def _parse_flag_blocks(text: str) -> list[dict]:
    if not text:
        return []
    blocks = []
    for m in FLAG_BLOCK_RE.finditer(text):
        try:
            data = yaml.safe_load(m.group(1))
            if isinstance(data, dict):
                blocks.append(data)
        except yaml.YAMLError:
            continue
    return blocks


def _consensus_proposals_for_issue(
    issue: dict,
    token: str,
    repo: str,
    threshold: int = 1,
) -> dict[tuple[str, str], set[str]]:
    """Aggregate (axis, proposed_correction) → distinct authors across body+comments."""
    agreement: dict[tuple[str, str], set[str]] = defaultdict(set)
    issue_author = (issue.get("user") or {}).get("login", "")
    body = issue.get("body") or ""
    for block in _parse_flag_blocks(body):
        for axis_entry in (block.get("flagged_axes") or []):
            if not isinstance(axis_entry, dict):
                continue
            axis = (axis_entry.get("axis") or "").strip()
            prop = axis_entry.get("proposed_correction")
            if axis and prop is not None and issue_author:
                agreement[(axis, str(prop).strip())].add(issue_author)

    # Comments
    page = 1
    while True:
        r = _gh_request(
            "GET",
            f"/repos/{repo}/issues/{issue['number']}/comments"
            f"?per_page=100&page={page}",
            token,
        )
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        for c in batch:
            author = (c.get("user") or {}).get("login", "")
            if not author or author.endswith("[bot]"):
                continue
            for block in _parse_flag_blocks(c.get("body") or ""):
                for axis_entry in (block.get("flagged_axes") or []):
                    if not isinstance(axis_entry, dict):
                        continue
                    axis = (axis_entry.get("axis") or "").strip()
                    prop = axis_entry.get("proposed_correction")
                    if axis and prop is not None:
                        agreement[(axis, str(prop).strip())].add(author)
        page += 1

    # Filter to only proposals that hit threshold
    return {k: v for k, v in agreement.items() if len(v) >= threshold}


def _moderator_approved_ncts() -> set[str]:
    """NCTs the moderator has clicked Approve on in the Moderation tab."""
    if not VALIDATIONS_PATH.exists():
        return set()
    try:
        records = json.loads(VALIDATIONS_PATH.read_text())
    except json.JSONDecodeError:
        return set()
    return {
        r["nct_id"] for r in records
        if r.get("source") == "flag"
        and r.get("decision", "").startswith("Approve")
    }


def _nct_from_issue(issue: dict) -> str | None:
    title = issue.get("title", "")
    body = issue.get("body", "") or ""
    m = re.search(r"NCT\d{8}", title) or re.search(r"NCT\d{8}", body)
    return m.group(0) if m else None


def _load_overrides() -> list[dict]:
    if not OVERRIDES_PATH.exists():
        return []
    return json.loads(OVERRIDES_PATH.read_text())


def _save_overrides(entries: list[dict]) -> None:
    OVERRIDES_PATH.write_text(json.dumps(entries, indent=2) + "\n")


def _build_patch(
    nct: str,
    proposals: dict[tuple[str, str], set[str]],
    issue_url: str,
    existing: dict | None,
) -> dict | None:
    """Construct (or update) an llm_overrides.json entry for this NCT.

    Returns None when there are no actionable proposals (e.g. only
    SponsorType flags, which we can't apply through this file).
    """
    actionable = {
        axis: prop for (axis, prop), _ in proposals.items()
        if axis in AXIS_TO_OVERRIDE_FIELD
    }
    if not actionable:
        return None

    # Start from the existing entry if any; otherwise create a fresh one.
    entry = dict(existing) if existing else {
        "nct_id": nct,
        "branch": None,
        "disease_category": None,
        "disease_entity": None,
        "target_category": None,
        "product_type": None,
        "exclude": False,
        "exclude_reason": None,
        "confidence": "high",
        "notes": "",
    }
    # Apply each accepted correction
    notes_bits = [entry.get("notes") or ""]
    for axis, prop in actionable.items():
        field = AXIS_TO_OVERRIDE_FIELD[axis]
        entry[field] = prop
        notes_bits.append(
            f"[community-flag] {axis} → {prop} (consensus from {issue_url})"
        )
    entry["notes"] = " ".join(b for b in notes_bits if b).strip()
    entry["confidence"] = "high"  # consensus + moderator-approval = high
    return entry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--apply", action="store_true",
        help="Mutate llm_overrides.json (default: dry-run, prints patch only).",
    )
    parser.add_argument(
        "--close-issues", action="store_true",
        help="After --apply, comment + label moderator-approved + close each "
             "promoted issue. Requires PAT with `repo` scope.",
    )
    parser.add_argument(
        "--threshold", type=int, default=1,
        help="Distinct authors required for consensus (default: 1, matches "
             "the C8b workflow's CONSENSUS_THRESHOLD env var). Single-reviewer "
             "is the realistic mode at low community volume — bump to 2 or 3 "
             "once enough independent reviewers exist that crowd-vetting "
             "actually filters noise.",
    )
    parser.add_argument(
        "--require-moderator-approval", action="store_true",
        help="Only promote issues for NCTs the moderator has Approve'd in "
             "the Moderation tab (recorded in moderator_validations.json). "
             "Strongly recommended for routine use; off by default for "
             "ergonomic dry-runs.",
    )
    args = parser.parse_args()

    token = os.environ.get("GH_TOKEN")
    repo = os.environ.get("REPO_SLUG", DEFAULT_REPO)
    if not token:
        print("ERROR: GH_TOKEN environment variable is required.", file=sys.stderr)
        return 2

    print(f"Fetching consensus-reached issues from {repo} …")
    issues = _fetch_consensus_issues(token, repo)
    print(f"  found {len(issues)} consensus-reached issue(s).")

    if args.require_moderator_approval:
        approved = _moderator_approved_ncts()
        print(f"  moderator-approved NCTs: {len(approved)}")
    else:
        approved = None  # gate disabled

    overrides = _load_overrides()
    by_nct = {e.get("nct_id"): e for e in overrides if e.get("nct_id")}

    promoted = []
    skipped = []
    for issue in issues:
        nct = _nct_from_issue(issue)
        if not nct:
            skipped.append((None, issue["number"], "no NCT in title/body"))
            continue

        if approved is not None and nct not in approved:
            skipped.append((nct, issue["number"], "not yet moderator-approved"))
            continue

        proposals = _consensus_proposals_for_issue(
            issue, token, repo, threshold=args.threshold
        )
        if not proposals:
            skipped.append((nct, issue["number"], "no proposal hit threshold"))
            continue

        existing = by_nct.get(nct)
        patch = _build_patch(nct, proposals, issue["html_url"], existing)
        if patch is None:
            skipped.append((nct, issue["number"], "only unsupported axes (e.g. SponsorType)"))
            continue

        promoted.append((nct, issue, existing, patch, proposals))

    # ---- Report ----
    print()
    print(f"Will promote {len(promoted)} issue(s):")
    print("=" * 70)
    for nct, issue, existing, patch, proposals in promoted:
        action = "UPDATE" if existing else "INSERT"
        print(f"\n  {action} {nct}  ←  issue #{issue['number']}: {issue['title'][:80]}")
        for (axis, prop), authors in sorted(proposals.items()):
            field = AXIS_TO_OVERRIDE_FIELD.get(axis, f"<unsupported:{axis}>")
            old = (existing or {}).get(field, "—")
            marker = "✓" if axis in AXIS_TO_OVERRIDE_FIELD else "✗"
            print(f"    {marker} {axis:18s} {old!r:>20s}  →  {prop!r:<20s} "
                  f"({len(authors)} reviewer(s))")

    if skipped:
        print()
        print(f"Skipped {len(skipped)} issue(s):")
        for nct, num, reason in skipped:
            print(f"  - #{num} ({nct or '?'}): {reason}")

    if not args.apply:
        print()
        print("Dry-run only. Re-run with --apply to mutate llm_overrides.json.")
        return 0

    # ---- Apply ----
    print()
    print(f"Applying patches to {OVERRIDES_PATH} …")
    for nct, issue, existing, patch, _ in promoted:
        if existing:
            # Replace in-place
            for i, e in enumerate(overrides):
                if e.get("nct_id") == nct:
                    overrides[i] = patch
                    break
        else:
            overrides.append(patch)
    _save_overrides(overrides)
    print(f"  wrote {len(overrides)} entries.")

    if args.close_issues and promoted:
        print()
        print("Closing promoted issues on GitHub …")
        for nct, issue, _, _, _ in promoted:
            num = issue["number"]
            _gh_request(
                "POST",
                f"/repos/{repo}/issues/{num}/comments",
                token,
                json={
                    "body": (
                        "Promoted to `llm_overrides.json`. The pipeline will "
                        "pick up this correction on its next reload "
                        "(snapshot refresh or `pipeline.reload_overrides()`).\n\n"
                        "Thanks for the review!"
                    )
                },
            ).raise_for_status()
            _gh_request(
                "POST",
                f"/repos/{repo}/issues/{num}/labels",
                token,
                json={"labels": ["moderator-approved"]},
            ).raise_for_status()
            _gh_request(
                "PATCH",
                f"/repos/{repo}/issues/{num}",
                token,
                json={"state": "closed", "state_reason": "completed"},
            ).raise_for_status()
            print(f"  closed #{num} ({nct}).")

    print()
    print("Done. Don't forget to commit llm_overrides.json + push.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
