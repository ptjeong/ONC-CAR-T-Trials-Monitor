# ONC-CAR-T-Trials-Monitor

CAR-T and Related Cell Therapies in Oncology (Heme and Solid): a monitoring dashboard for ClinicalTrials.gov studies with a three-tier disease hierarchy (Branch → Category → Entity), cascading filters, target classification, clickable NCT links, and a geography view with Germany deep-dive.

Sister app to the [Rheumatology-CAR-T-Trials-Monitor](https://github.com/ptjeong/Rheumatology-CAR-T-Trials-Monitor-).

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Scope

- **In scope:** CAR-T, CAR-NK, CAAR-T, CAR-Treg, CAR-γδ T trials in heme-onc and solid-onc.
- **Out of scope (v1):** TCR-T products (NY-ESO-1, MAGE-A4, afami-cel) — not strictly CAR-T. Outcomes, biomarkers, dose-level data.

## Data source

ClinicalTrials.gov API v2, pulled fresh per session (cached for 1 hour).
