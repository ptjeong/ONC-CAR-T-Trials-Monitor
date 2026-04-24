---
name: Quarterly approvals review
about: Refresh the APPROVED_PRODUCTS list in app.py (FDA / EMA / NMPA CAR-T approvals)
title: "[Chore] Quarterly approvals review — QX YYYY"
labels: chore, curation
assignees: ''
---

## Why

The `APPROVED_PRODUCTS` list in `app.py` drives Fig 1's regulatory-milestone strip. It's curated manually because no clean public API covers CAR-T biologics across all three regulators (FDA, EMA, NMPA). Without a quarterly review, the strip silently drifts out of date.

## Sources to check

Scan each source for CAR-T, CAR-NK, CAAR-T, CAR-γδ T approvals since the last review:

- **FDA (CBER)** — new BLAs / gene-therapy products
  - Index: https://www.fda.gov/vaccines-blood-biologics/cellular-gene-therapy-products/approved-cellular-and-gene-therapy-products
- **EMA (CHMP opinions & marketing authorisations)**
  - Human medicines: https://www.ema.europa.eu/en/medicines
  - Filter by ATC code L01XL (CAR-T) or search by known INN (e.g., tisagenlecleucel)
- **NMPA (中国国家药品监督管理局)** — CAR-T approvals
  - English summary via CDE: https://www.cde.org.cn/main/xxgk/listpage/9f9c74c73e0f8f562e9962a40a5f0e22
  - Cross-reference via trade press (BioCentury / Endpoints)

## Update checklist

- [ ] Compare each regulator's list against `APPROVED_PRODUCTS` in `app.py`.
- [ ] For each new approval, add a dict entry with `year`, `name` in the form `"<generic> (<Brand>)"`, `target`, `regulator`.
- [ ] Update the `# Last reviewed: YYYY-MM-DD` comment at the top of `APPROVED_PRODUCTS`.
- [ ] Sanity-check Fig 1 locally — new products should appear as a new row in the milestone strip, sorted by first-approval year.
- [ ] Update `CHANGELOG.md` under an "Approvals review" bullet.

## Notes / discussion

<!-- Paste links to press releases, CHMP opinions, BLA letters, etc. so future reviewers can trace provenance. -->
