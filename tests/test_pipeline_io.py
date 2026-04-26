"""Tests for snapshot byte-determinism + CT.gov fetch retry.

Two contracts:

1. **Snapshot byte-determinism.** `save_snapshot(df, df_sites, prisma)`
   produces identical SHA-256 of trials.csv / sites.csv / prisma.json /
   metadata.json regardless of the input row order, on repeated runs.
   Wall-clock + git SHA are segregated to runinfo.json (which IS allowed
   to vary). This is what lets a reviewer replicate an analysis and
   verify they got the same artifacts down to the byte.

2. **CT.gov fetch retry semantics.** Transient 5xx → retried with
   exponential backoff. Persistent failure → exception message includes
   the cumulative-studies count so the operator sees how much was lost.
   4xx → fast-fail (no retry — the error is terminal).

Pattern ported from rheum's REVIEW.md Phase 2 hardening.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pipeline  # noqa: E402


# ---------------------------------------------------------------------------
# Snapshot determinism
# ---------------------------------------------------------------------------

def _hash_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _seed_dataframes() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    df = pd.DataFrame({
        "NCTId": ["NCT00000003", "NCT00000001", "NCT00000002"],
        "BriefTitle": ["C", "A", "B"],
        "Branch": ["Heme-onc", "Solid-onc", "Mixed"],
    })
    df_sites = pd.DataFrame({
        "NCTId": ["NCT00000003", "NCT00000003", "NCT00000001"],
        "FacilityName": ["Hospital Z", "Hospital A", "Hospital M"],
        "City": ["Berlin", "Aachen", "Munich"],
    })
    prisma = {"n_after_dedup": 3, "n_excluded": 0}
    return df, df_sites, prisma


class TestSnapshotDeterminism:

    def test_trials_csv_hashes_identically_across_input_order(self, tmp_path):
        df, df_sites, prisma = _seed_dataframes()
        # First save: original order
        d1 = pipeline.save_snapshot(df, df_sites, prisma,
                                     snapshot_dir=str(tmp_path / "a"))
        # Second save: reverse order — should hash identically
        df_reordered = df.iloc[::-1].reset_index(drop=True)
        d2 = pipeline.save_snapshot(df_reordered, df_sites, prisma,
                                     snapshot_dir=str(tmp_path / "b"))
        h1 = _hash_file(tmp_path / "a" / d1 / "trials.csv")
        h2 = _hash_file(tmp_path / "b" / d2 / "trials.csv")
        assert h1 == h2, "trials.csv must be byte-identical regardless of input order"

    def test_sites_csv_hashes_identically_across_input_order(self, tmp_path):
        df, df_sites, prisma = _seed_dataframes()
        d1 = pipeline.save_snapshot(df, df_sites, prisma,
                                     snapshot_dir=str(tmp_path / "a"))
        df_sites_reordered = df_sites.iloc[::-1].reset_index(drop=True)
        d2 = pipeline.save_snapshot(df, df_sites_reordered, prisma,
                                     snapshot_dir=str(tmp_path / "b"))
        h1 = _hash_file(tmp_path / "a" / d1 / "sites.csv")
        h2 = _hash_file(tmp_path / "b" / d2 / "sites.csv")
        assert h1 == h2, "sites.csv must be byte-identical regardless of input order"

    def test_prisma_json_uses_sort_keys(self, tmp_path):
        df, df_sites, _ = _seed_dataframes()
        # Two prisma dicts with different key orders but same content
        prisma_a = {"n_after_dedup": 3, "n_excluded": 0}
        prisma_b = {"n_excluded": 0, "n_after_dedup": 3}
        d1 = pipeline.save_snapshot(df, df_sites, prisma_a,
                                     snapshot_dir=str(tmp_path / "a"))
        d2 = pipeline.save_snapshot(df, df_sites, prisma_b,
                                     snapshot_dir=str(tmp_path / "b"))
        h1 = _hash_file(tmp_path / "a" / d1 / "prisma.json")
        h2 = _hash_file(tmp_path / "b" / d2 / "prisma.json")
        assert h1 == h2, "prisma.json must be byte-identical with sort_keys=True"

    def test_metadata_json_excludes_wallclock(self, tmp_path):
        df, df_sites, prisma = _seed_dataframes()
        d = pipeline.save_snapshot(df, df_sites, prisma,
                                    snapshot_dir=str(tmp_path))
        meta = json.loads((tmp_path / d / "metadata.json").read_text())
        assert "created_utc" not in meta, (
            "Wall-clock must live in runinfo.json, not metadata.json — "
            "otherwise metadata.json varies between runs."
        )
        # Conversely runinfo.json SHOULD have it
        runinfo = json.loads((tmp_path / d / "runinfo.json").read_text())
        assert "created_utc" in runinfo

    def test_runinfo_json_records_pipeline_sha(self, tmp_path):
        df, df_sites, prisma = _seed_dataframes()
        d = pipeline.save_snapshot(df, df_sites, prisma,
                                    snapshot_dir=str(tmp_path))
        runinfo = json.loads((tmp_path / d / "runinfo.json").read_text())
        # SHA may be 'unknown' if not in a git repo — but the field exists
        assert "pipeline_sha" in runinfo


# ---------------------------------------------------------------------------
# Fetch retry
# ---------------------------------------------------------------------------

class TestFetchRetry:

    def _mk_response(self, status_code: int, text: str = "",
                      json_body: dict | None = None) -> MagicMock:
        r = MagicMock()
        r.status_code = status_code
        r.text = text
        r.json.return_value = json_body or {}
        return r

    def test_5xx_retries_and_eventually_succeeds(self):
        ok = self._mk_response(200, json_body={"studies": [{"id": "x"}]})
        fail = self._mk_response(503, "service unavailable")

        with patch("pipeline.requests.get", side_effect=[fail, fail, ok]):
            with patch("pipeline._FETCH_BACKOFFS_SEC", (0.0, 0.0, 0.0)):
                # Use the lower-level helper to avoid pagination loop
                data = pipeline._fetch_with_retry({}, cumulative_n=0)
                assert data == {"studies": [{"id": "x"}]}

    def test_4xx_does_not_retry(self):
        bad = self._mk_response(404, "not found")
        with patch("pipeline.requests.get", return_value=bad) as mock_get:
            with pytest.raises(Exception) as excinfo:
                pipeline._fetch_with_retry({}, cumulative_n=42)
            # Should be called once (no retry)
            assert mock_get.call_count == 1
            assert "404" in str(excinfo.value)
            # Cumulative count surfaced for blast-radius visibility
            assert "42" in str(excinfo.value)

    def test_total_failure_includes_cumulative_count(self):
        fail = self._mk_response(503, "always fails")
        with patch("pipeline.requests.get", return_value=fail):
            with patch("pipeline._FETCH_BACKOFFS_SEC", (0.0, 0.0, 0.0)):
                with pytest.raises(Exception) as excinfo:
                    pipeline._fetch_with_retry({}, cumulative_n=137)
                assert "137" in str(excinfo.value), (
                    "Cumulative-studies count missing from failure message — "
                    "operator can't tell partial-fetch blast radius."
                )

    def test_connection_error_retried(self):
        import requests as _r
        ok = self._mk_response(200, json_body={"studies": []})
        with patch("pipeline.requests.get",
                   side_effect=[_r.ConnectionError("nope"), ok]):
            with patch("pipeline._FETCH_BACKOFFS_SEC", (0.0, 0.0, 0.0)):
                data = pipeline._fetch_with_retry({}, cumulative_n=0)
                assert data == {"studies": []}

    def test_timeout_retried(self):
        import requests as _r
        ok = self._mk_response(200, json_body={"studies": []})
        with patch("pipeline.requests.get",
                   side_effect=[_r.Timeout("slow"), ok]):
            with patch("pipeline._FETCH_BACKOFFS_SEC", (0.0, 0.0, 0.0)):
                data = pipeline._fetch_with_retry({}, cumulative_n=0)
                assert data == {"studies": []}
