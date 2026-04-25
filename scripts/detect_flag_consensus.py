"""Detect consensus on a classification-flag GitHub issue.

Invoked by `.github/workflows/flag_consensus.yml`. Reads the issue body
plus every comment, parses any `BEGIN_FLAG_DATA … END_FLAG_DATA` YAML
blocks, and counts how many *distinct* authors agree on the same
(axis, proposed_correction) pair. When ≥ CONSENSUS_THRESHOLD authors
agree, applies the `consensus-reached` label.

Idempotent: if the label is already present and consensus still holds,
no-op. If a previously-met consensus has been broken (e.g. someone
deleted a comment), the label is removed.

Environment:
    GH_TOKEN              — GitHub Actions token (auto-provided)
    ISSUE_NUMBER          — issue number to inspect
    REPO_SLUG             — owner/name (e.g. ptjeong/ONC-CAR-T-Trials-Monitor)
    CONSENSUS_THRESHOLD   — distinct agreeing authors required (default 3)

Comment authors include the issue opener (their proposal counts as one
vote). The bot itself (`github-actions[bot]`) is excluded.
"""

from __future__ import annotations

import os
import re
import sys
from collections import defaultdict
from typing import Iterable

import requests
import yaml

GH_API = "https://api.github.com"
FLAG_BLOCK_RE = re.compile(
    r"<!--\s*BEGIN_FLAG_DATA\s*\n(.*?)END_FLAG_DATA\s*-->",
    re.DOTALL,
)
CONSENSUS_LABEL = "consensus-reached"
BOT_AUTHORS = {"github-actions[bot]", "dependabot[bot]"}


def _gh_request(method: str, path: str, token: str, **kwargs):
    headers = kwargs.pop("headers", {})
    headers.setdefault("Authorization", f"Bearer {token}")
    headers.setdefault("Accept", "application/vnd.github+json")
    headers.setdefault("X-GitHub-Api-Version", "2022-11-28")
    url = f"{GH_API}{path}"
    return requests.request(method, url, headers=headers, timeout=15, **kwargs)


def _parse_flag_blocks(text: str) -> list[dict]:
    """Pull every BEGIN_FLAG_DATA YAML block from the given text.

    Returns a list of parsed dicts. Malformed YAML is silently skipped
    so a single typo can't break consensus detection for the whole issue.
    """
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


def _proposals_from_block(block: dict) -> Iterable[tuple[str, str]]:
    """Yield (axis, proposed_correction) tuples from a single flag block.

    Tolerates the schema variant where `flagged_axes` is a list of dicts
    each containing `axis` and `proposed_correction` keys.
    """
    axes = block.get("flagged_axes") or []
    if not isinstance(axes, list):
        return
    for entry in axes:
        if not isinstance(entry, dict):
            continue
        axis = (entry.get("axis") or "").strip()
        prop = entry.get("proposed_correction")
        if axis and prop is not None:
            # Normalize whitespace and case-insensitive equality so that
            # "CD19" / "cd19 " count as the same proposal.
            yield axis, str(prop).strip()


def _count_consensus(
    issue_author: str | None,
    issue_body: str | None,
    comments: list[dict],
) -> dict[tuple[str, str], set[str]]:
    """Returns {(axis, proposed_correction): {author1, author2, ...}}."""
    agreement: dict[tuple[str, str], set[str]] = defaultdict(set)

    if issue_author and issue_body:
        for proposal in _proposals_from_block_list(_parse_flag_blocks(issue_body)):
            agreement[proposal].add(issue_author)

    for c in comments:
        author = (c.get("user") or {}).get("login", "")
        if not author or author in BOT_AUTHORS:
            continue
        for proposal in _proposals_from_block_list(
            _parse_flag_blocks(c.get("body") or "")
        ):
            agreement[proposal].add(author)

    return agreement


def _proposals_from_block_list(blocks: list[dict]) -> Iterable[tuple[str, str]]:
    for b in blocks:
        yield from _proposals_from_block(b)


def main() -> int:
    token = os.environ.get("GH_TOKEN")
    issue_number = os.environ.get("ISSUE_NUMBER")
    repo_slug = os.environ.get("REPO_SLUG")
    threshold = int(os.environ.get("CONSENSUS_THRESHOLD", "3"))

    if not (token and issue_number and repo_slug):
        print("Missing GH_TOKEN / ISSUE_NUMBER / REPO_SLUG; bailing.", file=sys.stderr)
        return 1

    # 1. Fetch issue
    r = _gh_request("GET", f"/repos/{repo_slug}/issues/{issue_number}", token)
    r.raise_for_status()
    issue = r.json()
    issue_author = (issue.get("user") or {}).get("login", "")
    issue_body = issue.get("body") or ""
    current_labels = {lbl["name"] for lbl in issue.get("labels", [])}

    # 2. Fetch all comments (paginated)
    comments: list[dict] = []
    page = 1
    while True:
        cr = _gh_request(
            "GET",
            f"/repos/{repo_slug}/issues/{issue_number}/comments?per_page=100&page={page}",
            token,
        )
        cr.raise_for_status()
        batch = cr.json()
        if not batch:
            break
        comments.extend(batch)
        page += 1

    # 3. Count consensus
    agreement = _count_consensus(issue_author, issue_body, comments)

    has_consensus = any(len(authors) >= threshold for authors in agreement.values())

    print(f"Issue #{issue_number} — analyzed {len(comments)} comments.")
    if not agreement:
        print("No structured BEGIN_FLAG_DATA blocks found.")
    for (axis, prop), authors in sorted(agreement.items(), key=lambda x: -len(x[1])):
        marker = "✓" if len(authors) >= threshold else " "
        print(f"  {marker} {axis} → {prop!r}: {len(authors)} reviewer(s) "
              f"({', '.join(sorted(authors))})")

    # 4. Reconcile label
    label_present = CONSENSUS_LABEL in current_labels
    if has_consensus and not label_present:
        print(f"Adding `{CONSENSUS_LABEL}` label.")
        _gh_request(
            "POST",
            f"/repos/{repo_slug}/issues/{issue_number}/labels",
            token,
            json={"labels": [CONSENSUS_LABEL]},
        ).raise_for_status()
    elif not has_consensus and label_present:
        print(f"Removing stale `{CONSENSUS_LABEL}` label.")
        _gh_request(
            "DELETE",
            f"/repos/{repo_slug}/issues/{issue_number}/labels/{CONSENSUS_LABEL}",
            token,
        )
        # 200 or 404 are both fine here.
    else:
        print(f"Label state already correct (consensus={has_consensus}, "
              f"label_present={label_present}).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
