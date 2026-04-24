"""Configuration for the Oncology CAR-T Trials Monitor.

Contains the three-tier disease ontology (Branch → Category → Entity),
term maps for the classifier, expanded target antigen lists (heme + solid),
named-product seed data, exclusion rules, and the allowed-label lists used
by validate.py.
"""

# ---------------------------------------------------------------------------
# Three-tier disease ontology
# ---------------------------------------------------------------------------

ONTOLOGY: dict[str, dict[str, list[str]]] = {
    "Heme-onc": {
        "B-NHL": [
            "DLBCL", "FL", "MCL", "MZL", "Burkitt",
            "PMBCL", "PCNSL", "Transformed indolent",
        ],
        "B-ALL": ["Adult B-ALL", "Pediatric B-ALL", "Ph+ B-ALL"],
        "CLL_SLL": ["CLL", "SLL", "Richter transformation"],
        "T-cell": [
            "T-ALL", "T-LL", "PTCL-NOS", "AITL",
            "ALCL", "CTCL", "Sezary",
        ],
        "Multiple myeloma": [
            "Newly diagnosed MM", "R/R MM", "AL amyloidosis",
            "Smoldering MM", "Plasma cell leukemia",
        ],
        "Hodgkin": ["Classical HL", "NLPHL"],
        "AML": ["De novo AML", "R/R AML", "Secondary AML"],
        "MDS_MPN": ["MDS", "MPN", "CMML"],
        "Heme-onc_other": [],
    },
    "Solid-onc": {
        "CNS": [
            "GBM", "Anaplastic glioma", "DIPG",
            "Medulloblastoma", "Ependymoma", "Brain metastases",
        ],
        "Thoracic": ["NSCLC", "SCLC", "Mesothelioma"],
        "GI": [
            "HCC", "Gastric/GEJ", "Pancreatic",
            "Colorectal", "Cholangio", "Esophageal",
        ],
        "GU": ["Prostate", "RCC", "Bladder"],
        "Gyn": ["Ovarian", "Endometrial", "Cervical"],
        "Breast": ["HER2+ breast", "TNBC", "HR+ breast"],
        "H&N": ["HNSCC", "Nasopharyngeal"],
        "Skin": ["Melanoma", "Merkel"],
        "Sarcoma": [
            "Osteosarcoma", "Ewing", "Synovial",
            "Soft tissue sarcoma",
        ],
        "Pediatric solid": [
            "Neuroblastoma", "Rhabdomyosarcoma", "Wilms", "Retinoblastoma",
        ],
        "Solid-onc_other": [],
    },
}

# Derived lookups
CATEGORY_TO_BRANCH: dict[str, str] = {
    cat: br for br, cats in ONTOLOGY.items() for cat in cats
}
ENTITY_TO_CATEGORY: dict[str, str] = {
    ent: cat for br, cats in ONTOLOGY.items() for cat, ents in cats.items() for ent in ents
}
ENTITY_TO_BRANCH: dict[str, str] = {
    ent: CATEGORY_TO_BRANCH[cat] for ent, cat in ENTITY_TO_CATEGORY.items()
}

HEME_CATEGORIES: set[str] = set(ONTOLOGY["Heme-onc"].keys())
SOLID_CATEGORIES: set[str] = set(ONTOLOGY["Solid-onc"].keys())

# Special labels
BASKET_MULTI_LABEL = "Basket/Multidisease"
HEME_BASKET_LABEL = "Heme basket"
SOLID_BASKET_LABEL = "Advanced solid tumors"
UNCLASSIFIED_LABEL = "Unclassified"

# Validation allow-list (used by validate.py / LLM)
VALID_DISEASE_ENTITIES: list[str] = (
    sorted({e for cats in ONTOLOGY.values() for ents in cats.values() for e in ents})
    + [BASKET_MULTI_LABEL, HEME_BASKET_LABEL, SOLID_BASKET_LABEL]
    + sorted({c for cats in ONTOLOGY.values() for c in cats.keys()})
    + [UNCLASSIFIED_LABEL, "Exclude"]
)
VALID_BRANCHES = ["Heme-onc", "Solid-onc", "Mixed", "Unknown"]
VALID_CATEGORIES = sorted(
    list(HEME_CATEGORIES | SOLID_CATEGORIES)
    + [BASKET_MULTI_LABEL, HEME_BASKET_LABEL, SOLID_BASKET_LABEL, UNCLASSIFIED_LABEL]
)

# ---------------------------------------------------------------------------
# Entity term maps (Tier 3 — leaf detection)
# ---------------------------------------------------------------------------

ENTITY_TERMS: dict[str, list[str]] = {
    # --- B-NHL ---
    "DLBCL": [
        "dlbcl", "diffuse large b cell lymphoma", "diffuse large b-cell lymphoma",
        "large b-cell lymphoma", "large b cell lymphoma",
    ],
    "FL": [
        "follicular lymphoma",
        "grade 1 follicular lymphoma", "grade 2 follicular lymphoma", "grade 3a follicular lymphoma",
    ],
    "MCL": ["mantle cell lymphoma", "mcl"],
    "MZL": [
        "marginal zone lymphoma", "malt lymphoma",
        "splenic marginal zone lymphoma", "nodal marginal zone lymphoma",
    ],
    "Burkitt": ["burkitt lymphoma", "burkitt s lymphoma"],
    "PMBCL": ["primary mediastinal b cell lymphoma", "pmbcl", "primary mediastinal large b cell lymphoma"],
    "PCNSL": ["primary cns lymphoma", "primary central nervous system lymphoma", "pcnsl"],
    "Transformed indolent": [
        "transformed follicular lymphoma", "transformed indolent lymphoma",
        "richter transformation to dlbcl",
    ],
    # --- B-ALL ---
    "Pediatric B-ALL": [
        "pediatric acute lymphoblastic leukemia",
        "pediatric b cell acute lymphoblastic leukemia",
        "childhood b cell acute lymphoblastic leukemia",
        "paediatric b all",
    ],
    "Adult B-ALL": [
        "adult b cell acute lymphoblastic leukemia",
        "adult acute lymphoblastic leukemia",
        "adult b all",
    ],
    "Ph+ B-ALL": [
        "philadelphia chromosome positive", "ph positive acute lymphoblastic leukemia",
        "bcr abl positive all",
    ],
    # --- CLL_SLL ---
    "CLL": ["chronic lymphocytic leukemia", "chronic lymphocytic leukaemia", "cll"],
    "SLL": ["small lymphocytic lymphoma", "sll"],
    "Richter transformation": ["richter transformation", "richter s transformation", "richter syndrome"],
    # --- T-cell ---
    "T-ALL": ["t cell acute lymphoblastic leukemia", "t all", "t lymphoblastic leukemia"],
    "T-LL": ["t cell lymphoblastic lymphoma", "t lymphoblastic lymphoma"],
    "PTCL-NOS": ["peripheral t cell lymphoma", "ptcl", "ptcl nos"],
    "AITL": ["angioimmunoblastic t cell lymphoma", "aitl"],
    "ALCL": ["anaplastic large cell lymphoma", "alcl"],
    "CTCL": ["cutaneous t cell lymphoma", "ctcl", "mycosis fungoides"],
    "Sezary": ["sezary syndrome", "sezary s syndrome"],
    # --- Multiple myeloma ---
    "Newly diagnosed MM": [
        "newly diagnosed multiple myeloma", "newly diagnosed mm",
        "transplant eligible multiple myeloma",
    ],
    "R/R MM": [
        "relapsed refractory multiple myeloma", "relapsed or refractory multiple myeloma",
        "r r multiple myeloma", "rrmm",
    ],
    "AL amyloidosis": ["al amyloidosis", "light chain amyloidosis"],
    "Smoldering MM": ["smoldering multiple myeloma", "smoldering myeloma"],
    "Plasma cell leukemia": ["plasma cell leukemia", "plasma cell leukaemia"],
    # --- Hodgkin ---
    "Classical HL": ["classical hodgkin lymphoma", "classical hodgkin s lymphoma", "hodgkin lymphoma"],
    "NLPHL": ["nodular lymphocyte predominant hodgkin lymphoma", "nlphl"],
    # --- AML ---
    "De novo AML": ["de novo acute myeloid leukemia"],
    "R/R AML": [
        "relapsed refractory acute myeloid leukemia",
        "relapsed or refractory acute myeloid leukemia",
        "r r aml", "relapsed aml", "refractory aml",
    ],
    "Secondary AML": ["secondary acute myeloid leukemia", "therapy related aml"],
    # --- MDS_MPN ---
    "MDS": ["myelodysplastic syndrome", "myelodysplastic syndromes", "mds"],
    "MPN": ["myeloproliferative neoplasm", "myeloproliferative neoplasms", "mpn"],
    "CMML": ["chronic myelomonocytic leukemia", "cmml"],
    # --- CNS ---
    "GBM": ["glioblastoma", "glioblastoma multiforme", "gbm"],
    "Anaplastic glioma": ["anaplastic glioma", "anaplastic astrocytoma"],
    "DIPG": ["diffuse intrinsic pontine glioma", "dipg", "diffuse midline glioma"],
    "Medulloblastoma": ["medulloblastoma"],
    "Ependymoma": ["ependymoma"],
    "Brain metastases": ["brain metastases", "brain metastasis", "cns metastases"],
    # --- Thoracic ---
    "NSCLC": ["non small cell lung cancer", "non-small cell lung cancer", "nsclc"],
    "SCLC": ["small cell lung cancer", "sclc"],
    "Mesothelioma": ["mesothelioma", "pleural mesothelioma", "peritoneal mesothelioma"],
    # --- GI ---
    "HCC": ["hepatocellular carcinoma", "hcc", "liver cancer"],
    "Gastric/GEJ": [
        "gastric cancer", "gastric adenocarcinoma",
        "gastroesophageal junction", "gej adenocarcinoma",
    ],
    "Pancreatic": ["pancreatic cancer", "pancreatic adenocarcinoma", "pdac"],
    "Colorectal": ["colorectal cancer", "colorectal adenocarcinoma", "colon cancer", "rectal cancer", "crc"],
    "Cholangio": ["cholangiocarcinoma", "biliary tract cancer", "bile duct cancer"],
    "Esophageal": ["esophageal cancer", "esophageal adenocarcinoma", "esophageal squamous cell carcinoma"],
    # --- GU ---
    "Prostate": ["prostate cancer", "metastatic castration resistant prostate cancer", "mcrpc"],
    "RCC": ["renal cell carcinoma", "renal cell cancer", "rcc"],
    "Bladder": ["bladder cancer", "urothelial carcinoma", "urothelial cancer"],
    # --- Gyn ---
    "Ovarian": ["ovarian cancer", "epithelial ovarian cancer", "high grade serous ovarian cancer"],
    "Endometrial": ["endometrial cancer", "uterine cancer"],
    "Cervical": ["cervical cancer"],
    # --- Breast ---
    "HER2+ breast": ["her2 positive breast cancer", "her2 breast cancer"],
    "TNBC": ["triple negative breast cancer", "tnbc"],
    "HR+ breast": ["hormone receptor positive breast cancer", "er positive breast cancer"],
    # --- H&N ---
    "HNSCC": ["head and neck squamous cell carcinoma", "hnscc", "head and neck cancer"],
    "Nasopharyngeal": ["nasopharyngeal carcinoma", "nasopharyngeal cancer"],
    # --- Skin ---
    "Melanoma": ["melanoma", "metastatic melanoma", "uveal melanoma"],
    "Merkel": ["merkel cell carcinoma"],
    # --- Sarcoma ---
    "Osteosarcoma": ["osteosarcoma"],
    "Ewing": ["ewing sarcoma", "ewing s sarcoma"],
    "Synovial": ["synovial sarcoma"],
    "Soft tissue sarcoma": ["soft tissue sarcoma"],
    # --- Pediatric solid ---
    "Neuroblastoma": ["neuroblastoma"],
    "Rhabdomyosarcoma": ["rhabdomyosarcoma"],
    "Wilms": ["wilms tumor", "wilms tumour", "nephroblastoma"],
    "Retinoblastoma": ["retinoblastoma"],
}

# ---------------------------------------------------------------------------
# Category-level fallback terms (Tier 2 — when no leaf matches)
# ---------------------------------------------------------------------------

CATEGORY_FALLBACK_TERMS: dict[str, list[str]] = {
    "B-NHL": [
        "b cell non hodgkin lymphoma", "b cell nhl", "b nhl",
        "indolent b cell lymphoma", "aggressive b cell lymphoma",
        "b cell lymphoma", "b lymphoma", "non hodgkin lymphoma", "lymphoma",
    ],
    "B-ALL": [
        "b cell acute lymphoblastic leukemia", "b all", "b cell all",
        "acute lymphoblastic leukemia", "acute lymphoid leukemia", "lymphoid leukemia",
    ],
    "CLL_SLL": ["chronic lymphocytic leukemia", "small lymphocytic lymphoma"],
    "T-cell": ["t cell lymphoma", "t cell malignancy", "t cell malignancies"],
    "Multiple myeloma": ["multiple myeloma", "myeloma", "plasma cell neoplasm", "plasma cell neoplasms"],
    "Hodgkin": ["hodgkin lymphoma"],
    "AML": ["acute myeloid leukemia", "aml"],
    "MDS_MPN": ["myelodysplastic", "myeloproliferative"],
    "CNS": ["glioma", "high grade glioma", "brain tumor", "brain tumour", "cns tumor"],
    "Thoracic": ["lung cancer", "thoracic cancer", "thoracic malignancy"],
    "GI": ["gastrointestinal cancer", "gi cancer", "gi malignancy"],
    "GU": ["genitourinary cancer", "gu malignancy"],
    "Gyn": ["gynecologic cancer", "gynaecologic cancer", "gynecologic malignancy"],
    "Breast": ["breast cancer", "metastatic breast cancer", "advanced breast cancer"],
    "H&N": ["head and neck cancer"],
    "Skin": ["skin cancer", "cutaneous malignancy"],
    "Sarcoma": ["sarcoma"],
    "Pediatric solid": [
        "pediatric solid tumor", "pediatric solid tumors",
        "paediatric solid tumour", "childhood solid tumor", "childhood solid tumors",
    ],
}

HEME_BASKET_TERMS: list[str] = [
    "hematologic malignancy", "hematologic malignancies",
    "haematologic malignancy", "haematologic malignancies",
    "relapsed refractory hematologic malignancies",
    "heme malignancy", "blood cancer", "blood cancers",
]

SOLID_BASKET_TERMS: list[str] = [
    "advanced solid tumor", "advanced solid tumors",
    "advanced solid tumour", "advanced solid tumours",
    "metastatic solid tumor", "metastatic solid tumors",
    "refractory solid tumor", "refractory solid tumors",
    "solid tumor", "solid tumors", "solid tumour", "solid tumours",
    "epithelial tumor", "epithelial tumors",
]

# ---------------------------------------------------------------------------
# Exclusions (autoimmune — inverse of rheum app's oncology exclusion)
# ---------------------------------------------------------------------------

EXCLUDED_INDICATION_TERMS: list[str] = [
    # Rheumatologic / classical autoimmune
    "systemic lupus erythematosus", "lupus nephritis",
    "systemic sclerosis", "scleroderma",
    "idiopathic inflammatory myopathy", "dermatomyositis", "polymyositis",
    "sjogren syndrome", "sjogren s syndrome",
    "anca associated vasculitis", "granulomatosis with polyangiitis",
    "microscopic polyangiitis",
    "rheumatoid arthritis",
    "igg4 related disease",
    "behcet disease", "behcet s disease",
    # Other immune-mediated (non-oncology)
    "type 1 diabetes", "myasthenia gravis", "multiple sclerosis",
    "neuromyelitis optica", "nmosd", "pemphigus vulgaris",
    "immune thrombocytopenia", "autoimmune hemolytic anemia",
    "membranous nephropathy", "anti gbm",
    "antiphospholipid syndrome",
    "hidradenitis suppurativa",
]

HARD_EXCLUDED_NCT_IDS: set[str] = set()  # seed empty; fill via curation loop

# ---------------------------------------------------------------------------
# CAR terms
# ---------------------------------------------------------------------------

CAR_CORE_TERMS: list[str] = [
    "car-t", "car t", "chimeric antigen receptor",
    "cd19 car", "bcma car", "anti-cd19 car", "anti-bcma car",
    "car-nk", "car nk", "caar-t", "car-treg",
    "gamma delta car", "car gamma delta",
]

CAR_NK_TERMS: list[str] = ["car-nk", "car nk"]
CAAR_T_TERMS: list[str] = ["caar-t", "caar t"]
CAR_TREG_TERMS: list[str] = ["car-treg", "car treg"]
CAR_GD_T_TERMS: list[str] = [
    "gamma delta car", "car gamma delta",
    "gamma delta t cell", "gammadelta car",
]

ALLOGENEIC_MARKERS: list[str] = [
    "allogeneic", "off-the-shelf", "off the shelf",
    "universal car-t", "universal car t", "ucar", "ucart",
    "healthy donor", "donor-derived", "donor derived", "allo1",
    "umbilical cord blood", "cord blood",
]

AUTOL_MARKERS: list[str] = [
    "autologous", "patient-derived", "patient derived",
    "patient-specific", "patient specific",
]

IN_VIVO_TERMS: list[str] = [
    "in vivo car", "in-vivo car",
    "in vivo programming", "in vivo generated", "in vivo transduction",
    "vivovec", "lentiviral nanoparticle",
    "circular rna", "mrna-lnp", "mrna lnp",
]

# ---------------------------------------------------------------------------
# Target antigens — heme + solid
# ---------------------------------------------------------------------------

HEME_TARGET_TERMS: dict[str, list[str]] = {
    "CD19": ["cd19", "anti-cd19", "cd19-directed", "cd19 directed", "cd19-targeted", "cd19 targeted", "car19"],
    "BCMA": ["bcma", "anti-bcma", "bcma-directed", "bcma-targeted", "b cell maturation antigen"],
    "CD20": ["cd20", "anti-cd20"],
    "CD22": ["cd22", "anti-cd22"],
    "CD5": ["cd5"],
    "CD7": ["cd7", "anti-cd7"],
    "CD30": ["cd30", "anti-cd30"],
    "CD33": ["cd33", "anti-cd33"],
    "CD38": ["cd38", "anti-cd38"],
    "CD70": ["cd70", "anti-cd70"],
    "CD123": ["cd123", "anti-cd123"],
    "GPRC5D": ["gprc5d", "anti-gprc5d"],
    "FcRH5": ["fcrh5", "fcrl5"],
    "SLAMF7": ["slamf7", "cs1"],
    "CD79b": ["cd79b"],
    "Kappa LC": ["kappa light chain", "kappa-light-chain"],
}

SOLID_TARGET_TERMS: dict[str, list[str]] = {
    "GPC3": ["gpc3", "glypican 3", "glypican-3"],
    "Claudin 18.2": ["claudin 18.2", "claudin18.2", "cldn18.2", "cldn 18.2", "cldn 18 2"],
    "Mesothelin": ["mesothelin", "msln"],
    "GD2": ["gd2", "anti-gd2"],
    "HER2": ["her2", "erbb2"],
    "EGFR": ["egfr", "epidermal growth factor receptor"],
    "EGFRvIII": ["egfrviii", "egfr viii"],
    "B7-H3": ["b7-h3", "b7 h3", "cd276"],
    "PSMA": ["psma", "prostate specific membrane antigen"],
    "PSCA": ["psca", "prostate stem cell antigen"],
    "CEA": ["carcinoembryonic antigen", "ceacam5"],
    "EpCAM": ["epcam"],
    "MUC1": ["muc1"],
    "CLDN6": ["cldn6", "claudin 6", "claudin-6"],
    "NKG2D-L": ["nkg2d ligand", "nkg2d ligands", "nkg2dl"],
    "ROR1": ["ror1"],
    "L1CAM": ["l1cam", "cd171"],
    "CD133": ["cd133"],
    "AFP": ["alpha fetoprotein", "afp"],
    "IL13Rα2": ["il13ra2", "il13r alpha 2", "il13 receptor alpha 2"],
    "HER3": ["her3", "erbb3"],
    "DLL3": ["dll3"],
}

# Dual / multi-target combos (checked pair-wise against detected targets)
DUAL_TARGET_LABELS: list[tuple[tuple[str, str], str]] = [
    (("CD19", "CD22"), "CD19/CD22 dual"),
    (("CD19", "CD20"), "CD19/CD20 dual"),
    (("CD19", "BCMA"), "CD19/BCMA dual"),
    (("BCMA", "GPRC5D"), "BCMA/GPRC5D dual"),
    (("BCMA", "CD70"), "BCMA/CD70 dual"),
    (("HER2", "MUC1"), "HER2/MUC1 dual"),
    (("GPC3", "Mesothelin"), "GPC3/MSLN dual"),
]

VALID_TARGETS: list[str] = (
    list(HEME_TARGET_TERMS.keys())
    + list(SOLID_TARGET_TERMS.keys())
    + [label for (_p, label) in DUAL_TARGET_LABELS]
    + ["CAR-NK", "CAAR-T", "CAR-Treg", "CAR-γδ T", "CAR-T_unspecified", "Other_or_unknown"]
)

VALID_PRODUCT_TYPES: list[str] = ["Autologous", "Allogeneic/Off-the-shelf", "In vivo", "Unclear"]

# ---------------------------------------------------------------------------
# Named products — approved + clinical-stage oncology CAR-T products
# ---------------------------------------------------------------------------
# Format: {target_label: [product_name_lowercase, ...]}. A substring match of any
# product name in the trial text short-circuits target assignment.

NAMED_PRODUCT_TARGETS: dict[str, list[str]] = {
    "CD19": [
        "tisagenlecleucel", "kymriah",
        "axicabtagene ciloleucel", "yescarta", "axi-cel",
        "brexucabtagene autoleucel", "tecartus", "brexu-cel",
        "lisocabtagene maraleucel", "breyanzi", "liso-cel",
        "obecabtagene autoleucel", "aucatzyl", "obe-cel",
        "relmacabtagene autoleucel", "carteyva", "relma-cel",
        "inaticabtagene autoleucel", "inati-cel",
        "allo-501", "allo-501a",
    ],
    "BCMA": [
        "idecabtagene vicleucel", "abecma", "ide-cel",
        "ciltacabtagene autoleucel", "carvykti", "cilta-cel",
        "equecabtagene autoleucel", "fucaso", "eque-cel",
        "zevorcabtagene autoleucel", "zevor-cel",
        "allo-715", "anito-cel", "ct053",
    ],
    "CD19/BCMA dual": ["gc012f"],
    "CD19/CD20 dual": ["mb-cart2019.1", "mb-cart2019", "mb-cart19.1"],
    "NKG2D-L": ["cyad-01"],
}

NAMED_PRODUCT_TYPES: dict[str, list[str]] = {
    "In vivo": [],
    "Allogeneic/Off-the-shelf": ["allo-501", "allo-501a", "allo-715"],
    "Autologous": [
        "tisagenlecleucel", "kymriah",
        "axicabtagene ciloleucel", "yescarta", "axi-cel",
        "brexucabtagene autoleucel", "tecartus", "brexu-cel",
        "lisocabtagene maraleucel", "breyanzi", "liso-cel",
        "idecabtagene vicleucel", "abecma", "ide-cel",
        "ciltacabtagene autoleucel", "carvykti", "cilta-cel",
        "obecabtagene autoleucel", "aucatzyl", "obe-cel",
        "relmacabtagene autoleucel", "carteyva", "relma-cel",
        "inaticabtagene autoleucel", "inati-cel",
        "equecabtagene autoleucel", "fucaso", "eque-cel",
        "zevorcabtagene autoleucel", "zevor-cel",
        "gc012f", "anito-cel", "ct053",
    ],
}

# ---------------------------------------------------------------------------
# Data-quality labels
# ---------------------------------------------------------------------------

AMBIGUOUS_ENTITY_TOKENS: list[str] = [
    "unclassified", "heme-onc_other", "solid-onc_other",
]

AMBIGUOUS_TARGET_TOKENS: list[str] = [
    "car-t_unspecified", "car_t_unspecified",
    "other_or_unknown",
]

# Cell therapy modality ordering (for figures and filters)
MODALITY_ORDER: list[str] = [
    "Auto CAR-T", "Allo CAR-T", "CAR-T (unclear)",
    "CAR-γδ T", "CAR-NK", "CAR-Treg", "CAAR-T", "In vivo CAR",
]
