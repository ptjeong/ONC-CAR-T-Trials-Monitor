"""Comprehensive named CAR-T product knowledge base for audit.

For each product, we encode:
  - aliases: every form the product might appear as in trial text
            (lowercase, normalized — same convention as NAMED_PRODUCT_TARGETS)
  - target: the canonical TargetCategory the classifier should emit
  - branch: Heme-onc / Solid-onc / Mixed (rare)
  - product_type: Autologous / Allogeneic/Off-the-shelf / In vivo
  - notes: short explanation of the design / target biology

Sources: FDA labels, sponsor press releases, ClinicalTrials.gov metadata,
peer-reviewed pharmacology reviews. Curated 2026-05-05.
"""

KNOWN_PRODUCTS = [
    # ---- FDA-approved CD19 CAR-T (B-NHL / B-ALL) ----
    {"aliases": ["tisagenlecleucel", "kymriah", "tisa-cel"],
     "target": "CD19", "branch": "Heme-onc", "product_type": "Autologous",
     "notes": "Novartis. CD19 CAR-T for B-ALL + DLBCL + FL."},
    {"aliases": ["axicabtagene ciloleucel", "yescarta", "axi-cel"],
     "target": "CD19", "branch": "Heme-onc", "product_type": "Autologous",
     "notes": "Kite/Gilead. CD19 CAR-T for DLBCL + FL."},
    {"aliases": ["brexucabtagene autoleucel", "tecartus", "brexu-cel"],
     "target": "CD19", "branch": "Heme-onc", "product_type": "Autologous",
     "notes": "Kite. CD19 CAR-T for MCL + adult B-ALL."},
    {"aliases": ["lisocabtagene maraleucel", "breyanzi", "liso-cel"],
     "target": "CD19", "branch": "Heme-onc", "product_type": "Autologous",
     "notes": "BMS/Juno. CD19 CAR-T for DLBCL + CLL/SLL + FL + MCL."},
    {"aliases": ["obecabtagene autoleucel", "aucatzyl", "obe-cel"],
     "target": "CD19", "branch": "Heme-onc", "product_type": "Autologous",
     "notes": "Autolus. CD19 CAR-T for adult R/R B-ALL (FDA 2024)."},
    {"aliases": ["relmacabtagene autoleucel", "carteyva", "relma-cel"],
     "target": "CD19", "branch": "Heme-onc", "product_type": "Autologous",
     "notes": "JW Therapeutics. CD19 CAR-T (China-approved). DLBCL + FL."},

    # ---- FDA-approved BCMA CAR-T (MM) ----
    {"aliases": ["idecabtagene vicleucel", "abecma", "ide-cel"],
     "target": "BCMA", "branch": "Heme-onc", "product_type": "Autologous",
     "notes": "BMS/Bluebird. BCMA CAR-T for R/R MM."},
    {"aliases": ["ciltacabtagene autoleucel", "carvykti", "cilta-cel"],
     "target": "BCMA", "branch": "Heme-onc", "product_type": "Autologous",
     "notes": "Janssen/Legend. Dual-epitope BCMA CAR-T for R/R MM."},
    {"aliases": ["equecabtagene autoleucel", "fucaso", "eque-cel"],
     "target": "BCMA", "branch": "Heme-onc", "product_type": "Autologous",
     "notes": "IASO/Innovent. BCMA CAR-T (China-approved). R/R MM."},
    {"aliases": ["zevorcabtagene autoleucel", "zevor-cel"],
     "target": "BCMA", "branch": "Heme-onc", "product_type": "Autologous",
     "notes": "CARsgen. BCMA CAR-T (China-approved 2024). R/R MM."},
    {"aliases": ["anitocabtagene autoleucel", "anito-cel"],
     "target": "BCMA", "branch": "Heme-onc", "product_type": "Autologous",
     "notes": "Arcellx/Kite. D-Domain BCMA CAR-T for R/R MM."},
    {"aliases": ["inaticabtagene autoleucel", "inati-cel"],
     "target": "CD19", "branch": "Heme-onc", "product_type": "Autologous",
     "notes": "Cellular Biomedicine. CD19 CAR-T for R/R B-ALL."},

    # ---- Allogeneic CD19 ----
    {"aliases": ["allo-501", "allo-501a"],
     "target": "CD19", "branch": "Heme-onc",
     "product_type": "Allogeneic/Off-the-shelf",
     "notes": "Allogene. UCART CD19 CAR-T."},
    # NOTE: removed bare "ucart19"/"ucart 19" because they false-match
    # against "huCART19" (humanized CART19, an autologous product) in
    # trial text. UCART19 (Servier/Allogene allogeneic) is detectable
    # via more specific aliases below.
    {"aliases": ["servier ucart", "servier-ucart"],
     "target": "CD19", "branch": "Heme-onc",
     "product_type": "Allogeneic/Off-the-shelf",
     "notes": "Servier/Allogene. UCART19 (genuine allogeneic CD19)."},

    # ---- Allogeneic BCMA ----
    {"aliases": ["allo-715"],
     "target": "BCMA", "branch": "Heme-onc",
     "product_type": "Allogeneic/Off-the-shelf",
     "notes": "Allogene. UCART BCMA for R/R MM."},

    # ---- Dual targets ----
    {"aliases": ["gc012f"],
     "target": "CD19/BCMA dual", "branch": "Heme-onc",
     "product_type": "Autologous",
     "notes": "Gracell/AstraZeneca. CD19/BCMA FasTCAR. MM + B-NHL + autoimmune."},
    {"aliases": ["azd0120"],
     "target": "CD19/BCMA dual", "branch": "Heme-onc",
     "product_type": "Autologous",
     "notes": "AstraZeneca/Gracell. CD19/BCMA dual (same construct as GC012F)."},
    {"aliases": ["mb-cart2019.1", "mb-cart2019"],
     "target": "CD19/CD20 dual", "branch": "Heme-onc",
     "product_type": "Autologous",
     "notes": "Miltenyi MB-CART2019.1 = zamtocabtagene autoleucel = tandem CD20/CD19."},
    {"aliases": ["mb-cart19.1"],
     "target": "CD19", "branch": "Heme-onc", "product_type": "Autologous",
     "notes": "Miltenyi MB-CART19.1 = MONOvalent CD19 (NOT the tandem MB-CART2019.1)."},
    {"aliases": ["zamtocabtagene autoleucel", "zamto-cel"],
     "target": "CD19/CD20 dual", "branch": "Heme-onc",
     "product_type": "Autologous",
     "notes": "Miltenyi. Same as MB-CART2019.1 — tandem CD20/CD19."},
    {"aliases": ["bms-986453", "bms986453"],
     "target": "BCMA/GPRC5D dual", "branch": "Heme-onc",
     "product_type": "Autologous",
     "notes": "BMS/Juno. Dual BCMA × GPRC5D CAR-T for R/R MM (user-confirmed 2026-04-27)."},

    # ---- GPRC5D ----
    {"aliases": ["bms-986393", "bms986393", "arlocabtagene autoleucel", "arlo-cel"],
     "target": "GPRC5D", "branch": "Heme-onc", "product_type": "Autologous",
     "notes": "BMS/Juno. GPRC5D CAR-T for R/R MM. iMMagine trials."},

    # ---- CLDN6 (solid) ----
    {"aliases": ["bnt211"],
     "target": "CLDN6", "branch": "Solid-onc", "product_type": "Autologous",
     "notes": "BioNTech. CLDN6 CAR-T + CLDN6 RNA-LPX vaccine."},

    # ---- Claudin 18.2 (solid) ----
    {"aliases": ["ct041", "satricabtagene autoleucel", "satri-cel"],
     "target": "Claudin 18.2", "branch": "Solid-onc",
     "product_type": "Autologous",
     "notes": "CARsgen. CLDN18.2 CAR-T for gastric/pancreatic adenocarcinoma."},

    # ---- BCMA additional ----
    {"aliases": ["ct053"],
     "target": "BCMA", "branch": "Heme-onc", "product_type": "Autologous",
     "notes": "CARsgen. Pre-zevor-cel BCMA CAR-T codename."},
    {"aliases": ["ct0596"],
     "target": "BCMA", "branch": "Heme-onc", "product_type": "Autologous",
     "notes": "CARsgen. BCMA CAR-T candidate."},
    {"aliases": ["hbi0101"],
     "target": "BCMA", "branch": "Heme-onc", "product_type": "Autologous",
     "notes": "Hadassah/Bnaipharm. BCMA CAR-T."},

    # ---- NKG2D-L (solid + heme) ----
    {"aliases": ["cyad-01", "cyad01"],
     "target": "NKG2D-L", "branch": "Mixed", "product_type": "Autologous",
     "notes": "Celyad. NKG2D-L CAR-T (NKG2D as binder, MICA/B etc. on tumor)."},
    {"aliases": ["kd-025", "kd025"],
     "target": "NKG2D-L", "branch": "Solid-onc", "product_type": "Autologous",
     "notes": "Wuhan U. NKG2D-L CAR-T for solid tumors."},

    # ---- Other antigens (clinical codenames) ----
    # MT027 corrected: it's allogeneic per multiple trial titles
    # ("Allogeneic CAR-T for Recurrent Glioma"). Branch=Mixed since
    # MT027 trials span solid (glioma, peritoneal, pleural) AND were
    # initially expected for solid only — keep Mixed to allow either.
    {"aliases": ["mt027"],
     "target": "B7-H3", "branch": "Mixed",
     "product_type": "Allogeneic/Off-the-shelf",
     "notes": "Multitude Therapeutics. B7-H3 allogeneic CAR-T (multiple solid tumors)."},
    {"aliases": ["boxr1030"],
     "target": "GPC3", "branch": "Solid-onc", "product_type": "Autologous",
     "notes": "SOTIO/BOXR. GPC3 CAR-T for HCC."},
    {"aliases": ["taa05"],
     "target": "FLT3", "branch": "Heme-onc", "product_type": "Autologous",
     "notes": "PersonGen. FLT3 CAR-T for AML."},
    {"aliases": ["gcar1"],
     "target": "GPNMB", "branch": "Solid-onc", "product_type": "Autologous",
     "notes": "Glycostem. GPNMB CAR-T."},
    # UTAA06 corrected: trials cover BOTH heme (NCT05722171 AML) AND
    # solid (NCT06372236 advanced solid tumors). Branch=Mixed.
    {"aliases": ["utaa06"],
     "target": "B7-H3", "branch": "Mixed", "product_type": "Autologous",
     "notes": "PersonGen. B7-H3 CAR-T (AML + solid tumor trials)."},

    # ---- LMY-920 (BAFF) ----
    {"aliases": ["lmy-920", "lmy920"],
     "target": "BAFF-R", "branch": "Heme-onc", "product_type": "Autologous",
     "notes": "Luminary. BAFF-CAR (BAFF as binder → BAFF-R/TACI/BCMA)."},

    # ---- Curation-loop additions (Chinese CD19) ----
    {"aliases": ["jy231"],
     "target": "CD19", "branch": "Heme-onc", "product_type": "Autologous",
     "notes": "JW Therapeutics CD19 candidate."},
    {"aliases": ["meta10-19"],
     "target": "CD19", "branch": "Heme-onc", "product_type": "Autologous",
     "notes": "China clinical-stage CD19 CAR-T."},
    {"aliases": ["ct1190b"],
     "target": "CD19", "branch": "Heme-onc", "product_type": "Autologous",
     "notes": "China clinical-stage CD19 CAR-T."},
    {"aliases": ["ptoc1"],
     "target": "CD19", "branch": "Heme-onc", "product_type": "Autologous",
     "notes": "China clinical-stage CD19 CAR-T."},
]
