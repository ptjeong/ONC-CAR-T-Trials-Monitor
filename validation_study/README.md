# Inter-rater κ validation study

Standalone Streamlit app for the JCO CCI inter-rater reliability study.
Runs as a **separate Streamlit Cloud deployment** from the main
dashboard, accessible only via invitation links containing per-rater
tokens. The main dashboard does not link to this app.

## Architecture

```
validation_study/
├── app.py                # Rater UI + admin view (~700 LOC)
├── sample_v1.json        # Locked sample of 200 NCTs (sha256 in manifest)
├── README.md             # This file
└── responses/            # Committed rater submissions
    └── *.json            # One file per rater (peter.json, raterB.json)

scripts/
├── generate_validation_sample.py   # One-shot: produce sample_v1.json
└── compute_validation_kappa.py     # κ + bootstrap CI report

tests/
└── test_validation_kappa.py        # Anchored against Sim & Wright textbook
```

## Sample (locked, 2026-04-26)

- **Version:** v1
- **N:** 200 trials
- **sha256:** `ac297f4559461914a9c273ad230a9564937e4038997cc390a0cc359325d51f27`
- **Source snapshot:** 2026-04-24
- **Stratification:** 50% Heme-onc / 50% Solid-onc; ≥5 trials per major DiseaseCategory
- **Seed:** 20260426 (reproducible — re-running the generator with the
  same args produces an identical manifest)

Recorded in commit `<filled-on-commit>` as the pre-registration anchor.
**Do not regenerate `sample_v1.json` after raters start work.** If the
methodology evolves, increment to `sample_v2.json`.

## Deployment

### One-time setup (Streamlit Cloud)

1. Go to https://share.streamlit.io
2. **New app** → connect to `ptjeong/ONC-CAR-T-Trials-Monitor` repo
3. **Main file path:** `validation_study/app.py`
4. **App URL:** something like `validation-onc-cart.streamlit.app`
5. In **Settings → Secrets**, add:

```toml
validation_tokens = """
{
  "PETER-ABC123-XYZ789": {"rater_id": "peter", "role": "rater"},
  "DRSMITH-DEF456-UVW012": {"rater_id": "drsmith", "role": "rater"},
  "ADMIN-GHI789-RST345": {"rater_id": "ptjeong", "role": "admin"}
}
"""
```

Generate strong tokens (e.g. `python3 -c 'import secrets; print(secrets.token_urlsafe(24))'`).
Each rater gets exactly one token; never reuse across raters or you lose attribution.

### Sharing invitation links

Email each rater:

```
Subject: Invitation to the CAR-T trial classification validation study

Hi <name>,

You've been invited to participate as an independent rater in our
publication-grade validation of the CAR-T Trials Monitor classification
pipeline. The study takes ~2-3 hours, can be split across sessions,
and the work is saved as you go.

Please use this private link (do not share):
  https://validation-onc-cart.streamlit.app/?token=<their-token>

What to do:
1. Click the link
2. Read each trial's title + summary + interventions
3. Classify it on six axes (Branch, DiseaseCategory, ...)
4. Mark "Unsure" if you can't make a confident call — that's data
5. Click Submit + next, repeat for all 200 trials

A growing garden visualization tracks your progress 🌷. There are
milestone celebrations every 25 trials. Take breaks — fatigue
affects inter-rater reliability.

When you finish, click "Download FINAL submission" and email it to me.
I'll run the analysis and send you the final report.

Thanks!
Peter
```

## Data safety architecture (10 layers)

For a multi-hour clinical rater session, every single rating MUST be durable from the moment the rater hits Submit. The app implements:

1. **Server-side autosave** on every submit — `/tmp/validation_responses/{rater_id}.json`. Survives Streamlit reruns and same-session navigation.
2. **Git-committed canonical store** — `validation_study/responses/{rater_id}.json`. Authoritative across sessions. App reads on load.
3. **Crash recovery** — if the local /tmp backup is newer than the committed file (e.g. session was interrupted), the more recent one wins.
4. **Visible "Last saved" indicator** — pulses red if > 2 min stale (shouldn't happen, but provides reassurance).
5. **Always-visible manual download button** — top-right corner. Generates a JSON the rater can save anywhere.
6. **Auto-prompt every 10 trials** — toast notification reminds the rater to download a backup.
7. **"Email progress" mailto: button** — pre-filled mailto: link for the non-technical rater. They open their mail client, attach the JSON they just downloaded, send.
8. **Schema-versioned JSON** — every record carries `schema_version`, `app_version`, `sample_sha256`. Future readers can validate.
9. **Atomic writes** — write to `.tmp`, then rename. No half-written files even if the process dies mid-write.
10. **Non-destructive resume** — uploaded JSONs MERGE with existing state. Existing ratings are never overwritten.

## Running the analysis (after both raters submit)

1. Each rater emails you their final JSON
2. Save them as `validation_study/responses/peter.json` and `.../drsmith.json`
3. Commit those files
4. Run:
   ```bash
   python3 scripts/compute_validation_kappa.py --output study_report.md
   ```
5. The script writes:
   - `study_report.md` — full markdown report (drop into manuscript)
   - `validation_study/disagreements.csv` — adjudication queue
6. Adjudicate the disagreements jointly with Rater B → record consensus labels → update `responses/` with adjudicated truth → re-run analysis to compute final pipeline-vs-gold-standard κ

## Methodology summary (for the paper's Methods section)

> Inter-rater reliability of the automated trial classification was assessed
> on a pre-registered random sample of 200 trials (sample manifest sha256:
> ac297f45…) stratified by primary indication branch (50% hematologic,
> 50% solid) and disease category (≥5 trials per major category, defined as
> ≥10 trials in the source snapshot). Trials with insufficient text
> (no title, summary, conditions, or interventions ≥50 characters) were
> excluded prior to sampling.
>
> Two independent raters — the corresponding author (PJ) and a clinical
> collaborator with experience in cellular immunotherapy trials —
> classified each trial on six axes (Branch, DiseaseCategory,
> DiseaseEntity, TargetCategory, ProductType, SponsorType) using a custom
> Streamlit interface that displayed only the trial's title, brief
> summary, conditions, interventions, phase, lead sponsor, and trial
> design. Pipeline-generated labels were not visible to raters during
> classification, and raters were blinded to each other's classifications.
> Each axis offered "Unsure" as a first-class option to avoid forced
> guessing.
>
> Cohen's κ was computed per axis between raters with 95% confidence
> intervals from 10,000 bootstrap resamples. Pairwise agreement with the
> pipeline was reported as a secondary statistic. Disagreements were
> resolved in an adjudication round where both raters reviewed
> disagreed-upon trials and assigned a consensus ground-truth label,
> which then served as the gold standard for computing pipeline F1.

## FAQ

**What if the Streamlit Cloud app restarts mid-session?** Server-side autosave covers same-session resilience. If the actual server restarts (rare but possible on Cloud), the most recent download from the rater's "Download progress" click is the recovery point. Hence the every-10-trial prompt.

**What if a rater types DiseaseEntity inconsistently (e.g. "DLBCL" vs "Diffuse Large B-cell Lymphoma")?** The κ analysis uses exact-string matching. If raters know each other's spelling preferences won't match, normalize during the adjudication round. This is one reason DiseaseEntity was made free-text rather than dropdown — capturing rater preferences is itself useful data.

**Can a third rater be added later?** Yes — generate a new token, give them the URL, they rate the same 200 trials. The κ analysis automatically computes pairwise κ for every pair of raters.

**How long does this take per rater?** Median ~45-60 sec per trial in pilot testing. 200 trials = 2.5–3.5 hours total, easily split across multiple sessions.
