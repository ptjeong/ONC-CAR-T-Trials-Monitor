# Security policy

## Scope

This dashboard displays only public data from the ClinicalTrials.gov
registry. It **does not** collect, store, or process any patient-level
protected health information (PHI), user accounts, or personally
identifiable information beyond the technical connection metadata handled
by the Streamlit Community Cloud hosting environment.

See the [Impressum / Datenschutz](https://onc-car-t-trial-monitor.streamlit.app/)
section inside the dashboard's **About** tab for the full hosting /
data-protection statement.

## Reporting a vulnerability

If you believe you have found a security-relevant issue — for example:

- a way the dashboard could leak environment secrets or internal paths,
- a classification override that could be abused to hide trials from a
  user's view (data-integrity concern),
- a dependency in `requirements.txt` with a known CVE,
- any other deployment-security flaw,

please **do not** open a public issue.

Instead, email the maintainer directly:

**peter.jeong@uk-koeln.de**

with:

- a short description of the issue,
- steps to reproduce (URL path, filter state, uploaded input if any),
- expected vs observed behaviour.

Acknowledgement within 7 working days, with a coordinated disclosure
timeline agreed for anything beyond cosmetic.

## What's out of scope

- **Trial classification errors** are research / curation issues, not
  security issues — please use the regular
  [Classification correction](./.github/ISSUE_TEMPLATE/classification_correction.md)
  issue template instead.
- **ClinicalTrials.gov data quality** (wrong enrollment counts, missing
  conditions in source records) should be reported to NLM via
  https://clinicaltrials.gov/.
