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
    # "liver metastases" / "metastatic liver" route through GI because the
    # vast majority of liver-mets primary tumours (CRC, gastric, pancreatic,
    # HCC) are GI primaries. Surfaced by NCT02862704 (MG7 CAR-T for liver
    # metastases) which had been falling to Unknown.
    "GI": ["gastrointestinal cancer", "gi cancer", "gi malignancy",
           "liver metastases", "liver metastasis", "metastatic liver"],
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
    # Generic autoimmune / non-onco wrappers (caught 24+ Unknown-branch trials)
    "autoimmune disease", "autoimmune diseases",
    "systemic autoimmune disease", "systemic autoimmune diseases",
    "refractory autoimmune diseases",
    "relapsed/refractory autoimmune diseases",
    "rheumatic diseases", "rheumatologic disease",
    "b cell mediated autoimmune", "b-cell mediated autoimmune",
    # Meta / non-therapeutic (CAR-T follow-up, CRS registries, COVID etc.)
    "covid-19", "covid 19", "sars-cov-2",
    "neurotoxicity",
    "cytokine release syndrome",
    "nephrotic syndrome",
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
    # "allogenic" (single 'e') is a common spelling variant in non-English
    # CT.gov titles — keep both. Without it, NCT05739227 etc. fall through
    # to the autologous smart-default.
    "allogeneic", "allogenic", "off-the-shelf", "off the shelf",
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
    "CD19": [
        "cd19", "anti-cd19", "cd19-directed", "cd19 directed",
        "cd19-targeted", "cd19 targeted", "car19",
        # Common intervention-field variants missed before:
        "cart-19", "cart19", "cd19 cart", "cd19-cart", "cd19 car t", "cd19-car-t",
        "cd19 positive", "cd19 specific", "anti cd19",
    ],
    "BCMA": ["bcma", "anti-bcma", "bcma-directed", "bcma-targeted",
             "b cell maturation antigen",
             # Ligand-based CAR convention (record receptor on tumor, not
             # binding domain on construct). APRIL is the natural ligand
             # for BCMA + TACI; APRIL-CARs (e.g. AUTO2 / NCT03287804) are
             # primarily classified to BCMA as the dominant therapeutic
             # receptor in MM. NCT04657861 / NCT03287804 both have
             # "BCMA" in the title so this is mostly belt-and-braces.
             "april car", "april-car", "april cart", "april car-t"],
    "CD20": ["cd20", "anti-cd20"],
    "CD22": ["cd22", "anti-cd22"],
    "CD5": ["cd5"],
    "CD7": ["cd7", "anti-cd7"],
    "CD30": ["cd30", "anti-cd30"],
    "CD33": ["cd33", "anti-cd33"],
    "CD38": ["cd38", "anti-cd38"],
    "CD70": ["cd70", "anti-cd70"],
    "CD123": ["cd123", "anti-cd123",
              # Ligand-based CAR (NCT04599543 — IL3 CAR-T). IL3 is the
              # natural ligand of CD123 (= IL3RA); the CAR uses IL3 as
              # binding domain to recognize CD123 on AML blasts. Record
              # the receptor (CD123) per ligand-CAR convention.
              "il3 car", "il-3 car", "il3-car", "il-3-car",
              "il3 cart", "il3-cart", "il-3 cart"],
    "GPRC5D": ["gprc5d", "anti-gprc5d"],
    "FcRH5": ["fcrh5", "fcrl5"],
    "SLAMF7": ["slamf7", "cs1"],
    "CD79b": ["cd79b"],
    "Kappa LC": ["kappa light chain", "kappa-light-chain"],
    "FLT3": ["flt3", "anti-flt3", "flt3 positive"],
    "CLL1": ["cll1", "clec12a", "clec 12a"],
    "CD147": ["cd147", "basigin", "emmprin"],
    # Added 2026-04-25 from independent-LLM validation (Llama 3.3 surfaced
    # all four; user confirmed each on CT.gov):
    # CD4 as a TARGET (not the host cell). Bare "cd4" was previously
    # accepted but it false-matches "CD4+ T cells" / "CD4 helper" in
    # ANY CAR-T trial that mentions T-cell biology — e.g. NCT03500991
    # (HER2 GBM) and NCT06094842 (L1CAM neuroblastoma) were both
    # silently mis-targeted to CD4 before this tightening. Use
    # construct-anchored phrases only. NCT06071624 (CMML, the actual
    # CD4-CAR trial that motivated adding CD4) is preserved because
    # its title says "anti-CD4 CAR".
    "CD4":  ["anti-cd4", "cd4 car", "cd4-car", "cd4 cart", "cd4-cart",
             "cd4-directed", "cd4 directed", "cd4-targeted",
             "cd4 targeted", "cd4-specific", "cd4 specific"],
    "CD1a": ["cd1a", "anti-cd1a"],        # NCT05745181 (T-ALL)
    "IL-5": ["il-5", "il5", "interleukin-5", "interleukin 5"],  # NCT07257640 (eosinophilic leukemia)
    # Added 2026-04-27 from ligand-CAR audit (IL3/APRIL/BAFF/NKG2D
    # families surfaced during validation pilot prep):
    # BAFF is the natural ligand of three receptors (BAFF-R, TACI, BCMA).
    # BAFF-CARs (LMY-920) target B-cell malignancies primarily via
    # BAFF-R, the most B-cell-specific receptor. NCT05312801 / NCT06916767
    # were misclassified as Other_or_unknown before this entry. Naming
    # the target "BAFF-R" reflects the dominant therapeutic receptor;
    # raters can flag if a trial specifies a different downstream receptor.
    "BAFF-R": ["baff-r", "baff r", "baff receptor", "tnfrsf13c",
               "baff car", "baff-car", "baff car-t", "baff cart",
               "baff-car-t", "baff-cart"],
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
    "NKG2D-L": ["nkg2d ligand", "nkg2d ligands", "nkg2dl",
                # In CAR context, "NKG2D CAR" universally means the CAR
                # uses NKG2D (the natural activating receptor) as binding
                # domain to recognize NKG2D-Ligands (MICA/MICB/ULBP1-6)
                # on tumors. Record the receptor on the tumor (NKG2D-L)
                # per ligand-CAR convention. Without these, NKG2D CAR-NK
                # trials (NCT06503497, NCT05213195, NCT05776355,
                # NCT06856278, NCT05247957, NCT05734898, NCT06478459)
                # silently fell to platform-only classification "CAR-NK"
                # instead of "CAR-NK: NKG2D-L".
                "nkg2d car", "nkg2d-car", "nkg2d cart", "nkg2d car-t",
                "nkg2d-car-t", "mica/micb", "mica mica",
                "ulbp1", "ulbp2", "ulbp3"],
    "ROR1": ["ror1"],
    "L1CAM": ["l1cam", "cd171"],
    "CD133": ["cd133"],
    "AFP": ["alpha fetoprotein", "afp"],
    "IL13Rα2": ["il13ra2", "il13r alpha 2", "il13 receptor alpha 2"],
    "HER3": ["her3", "erbb3"],
    "DLL3": ["dll3"],
    "CDH17": ["cdh17", "cadherin 17", "cadherin-17"],
    "GUCY2C": ["gucy2c", "guanylyl cyclase 2c"],
    "GPNMB": ["gpnmb", "glycoprotein nmb"],
    # Added 2026-04-25 from independent-LLM validation (Llama 3.3 surfaced
    # all three; user confirmed each on CT.gov). Word-boundary regex in
    # _term_in_text handles 3-letter abbrev safety without padding.
    "FAP":   ["fap", "fibroblast activation protein"],   # NCT01722149 (mesothelioma)
    # MET is a 3-letter token that overlaps the English verb "met" — only
    # use receptor-specific patterns. "c-met"/"cmet" (normaliser strips the
    # hyphen so both forms collapse to "cmet"), "anti-met", "met receptor",
    # "met-positive" / "met positive", and CAR-construct phrases like
    # "met scfv" / "met chimeric antigen receptor" / "met car". All are
    # unambiguous; they won't fire on "patients met the criteria".
    "MET":   ["c-met", "cmet", "anti-met", "met receptor", "met-positive",
              "met positive", "met scfv", "met chimeric antigen receptor",
              "met car-t", "met car t", "hepatocyte growth factor receptor"],   # NCT03060356
    "FGFR4": ["fgfr4", "fgfr 4", "anti-fgfr4",
              "fibroblast growth factor receptor 4"],   # NCT06865664 (rhabdomyosarcoma)
    # Added 2026-05-05 after ASGCT Q1 2026 Landscape Report cross-check —
    # these antigens have ≥13 active gene-therapy programs each (per ASGCT
    # /Citeline data) but were absent from our taxonomy. Construct-anchored
    # synonyms only because all three are commonly mentioned in eligibility
    # text (e.g. "KRAS-mutant patients", "NY-ESO-1 positive tumors",
    # "PRAME expression required") which would false-fire bare-token matches.
    #
    # KRAS — 20 programs per ASGCT Q1 2026. Mostly NSCLC, CRC, pancreatic.
    # KRAS-mutant subtypes (G12D, G12C) often referenced as eligibility,
    # so require explicit construct phrasing.
    "KRAS":     ["anti-kras", "kras car", "kras-car", "kras cart",
                 "kras-cart", "kras-targeted", "kras targeted",
                 "kras-directed", "kras directed", "kras scfv",
                 "kras g12d-targeted", "kras g12c-targeted",
                 "anti-kras-g12d", "anti-kras-g12c"],
    # NY-ESO-1 — 15 programs per ASGCT (CTAG1B / cancer testis antigen 1B).
    # Mostly TCR-T (synovial sarcoma, melanoma, ovarian, NSCLC) but CAR-T
    # exists too. Construct-anchored only — "NY-ESO-1 positive patients"
    # is a common eligibility phrase.
    "NY-ESO-1": ["anti-ny-eso-1", "anti-ny eso 1", "anti-nyeso",
                 "ny-eso-1 car", "ny-eso-1-car", "nyeso car", "nyeso-car",
                 "ny-eso-1 cart", "ny-eso-1-cart",
                 "ny-eso-1-targeted", "ny-eso-1 targeted",
                 "ny-eso-1-directed", "ny-eso-1 directed",
                 "ctag1b car", "ctag1b-car"],
    # PRAME — 13 programs per ASGCT. Solid (melanoma, sarcoma) + heme (AML).
    # PRAME is also a common eligibility marker; construct-anchored only.
    "PRAME":    ["anti-prame", "prame car", "prame-car", "prame cart",
                 "prame-cart", "prame car-t", "prame-car-t",
                 "prame-targeted", "prame targeted",
                 "prame-directed", "prame directed", "prame scfv"],
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
        # Curation-loop additions (Chinese / clinical-stage CD19 products)
        "jy231", "meta10-19", "ct1190b", "ptoc1",
        # Miltenyi MB-CART19.1 — CD19 MONOvalent (NOT the tandem
        # MB-CART2019.1 which is CD20/CD19 dual). Was previously
        # mis-mapped to CD19/CD20 dual in NAMED_PRODUCT_TARGETS,
        # causing NCT03853616 ("MB-CART19.1 r/r CD19+ B-cell
        # Malignancies") to false-classify as dual instead of CD19.
        "mb-cart19.1",
        # MB-CART20.1 — CD20 MONOvalent (different from MB-CART2019.1)
        # Note: classified as CD19 here only if it's combined with
        # CD19 — but standalone MB-CART20.1 should be CD20. We keep
        # CD19 as a default given the rarity of standalone CD20-only
        # in this dataset; revisit if a standalone trial appears.
        # Added 2026-05-05 from ASGCT Q1 2026 Landscape Report.
        # All confirmed CD19-targeted CAR-Ts via sponsor product info /
        # press releases / regulatory filings.
        "varnimcabtagene autoleucel", "qartemi",   # Immuneel — India / Spain B-NHL approval 2025
        "renikeolunsai", "hicara",                  # Hrain Bio — China r/r LBCL approval 2025
        "pulkilumab", "pulidekai",                  # Chongqing Precision — China ALL approval 2025
        "anbal-cel", "anbalcel",                    # Curocell — South Korea pre-reg
        "kite-753", "kite753",                      # Kite/Gilead — DLBCL (RMAT designation Q1 2026)
        # Prulacabtagene leucel — autoimmune CAR-T (lupus nephritis +
        # SLE, FDA meetings expected Q2 2026). Won't appear in onc CT.gov
        # queries but kept here so cross-referencing the rheum repo
        # via this config doesn't double-add. Same construct as the
        # rheum-classified CD19 autoimmune CAR-Ts.
        "prulacabtagene leucel", "prulacabtagene autoleucel", "prula-cel",
    ],
    "BCMA": [
        "idecabtagene vicleucel", "abecma", "ide-cel",
        "ciltacabtagene autoleucel", "carvykti", "cilta-cel",
        "equecabtagene autoleucel", "fucaso", "eque-cel",
        "zevorcabtagene autoleucel", "zevor-cel",
        # `anito-cel` is the abbreviation; the FULL name
        # `anitocabtagene autoleucel` is also added because trial
        # titles often spell it out (NCT06413498) and the substring
        # lookup over `anito-cel` (with hyphen) misses the spelled-out
        # form. Without this, NCT06413498 false-matched CD38 from
        # the eligibility text "anti-CD38 monoclonal antibody".
        "anitocabtagene autoleucel",
        "allo-715", "anito-cel", "ct053",
        # Curation-loop additions
        "ct0596", "hbi0101",
        # Added 2026-05-05 from ASGCT Q1 2026 Landscape Report —
        # NXC-201 (Immix Biopharma) BCMA CAR-T received FDA Breakthrough
        # Therapy Designation Jan 2026 for AL amyloidosis. Heme-onc
        # rare disease; included here because BCMA is the construct's
        # antigen even though indication isn't standard MM.
        "nxc-201", "nxc201",
    ],
    # CD7 — added the WU-CART-007 named-product alias (Wugen, allogeneic
    # CD7 CAR-T, BTD for ALL Jan 2026 per ASGCT). The CD7 single-antigen
    # term-list above already catches "anti-CD7" / "CD7-directed" via
    # the standard pattern, but the product code "WU-CART-007" needs
    # the explicit alias to short-circuit cleanly.
    # Note: CD7 is in HEME_TARGET_TERMS, not SOLID_TARGET_TERMS, so
    # this entry sits under the CD7 heme key in NAMED_PRODUCT_TARGETS.
    "CD7": [
        "wu-cart-007", "wucart-007", "wucart007", "wu-cart007",
    ],
    "CD19/BCMA dual": ["gc012f", "azd0120"],
    # MB-CART2019.1 = zamtocabtagene autoleucel = tandem CD20/CD19.
    # NOTE: `mb-cart19.1` (without the "20") is the MONOvalent CD19
    # product and was incorrectly listed here pre-2026-05-05 — moved
    # to the CD19 list. `mb-cart2019.1` substring does NOT contain
    # `mb-cart19.1` (the "2019" vs "19" differs), so the two are
    # cleanly separable by the substring lookup.
    "CD19/CD20 dual": ["mb-cart2019.1", "mb-cart2019",
                       "zamtocabtagene autoleucel", "zamto-cel"],
    # BMS-986453 = dual BCMA × GPRC5D CAR-T (BMS/Juno R/R MM, NCT06153251).
    # User-confirmed 2026-04-27. Maps the named-product short-circuit
    # so the LLM-override-locked CAR-T_unspecified is bypassed.
    "BCMA/GPRC5D dual": ["bms-986453", "bms986453"],
    # ---- BAFF-R named product (added 2026-05-05 from audit) ----
    # LMY-920 (Luminary) is the BAFF-CAR construct. NCT05546723 (R/R MM)
    # had no LLM override and was term-detected as BCMA from
    # "BCMA targeting CAR-T cell treatment" in the BriefSummary —
    # which actually describes a PRIOR therapy, not the CAR's target.
    # The named-product short-circuit fixes this. (NCT05312801 +
    # NCT06916767 already have explicit BAFF-R LLM overrides.)
    "BAFF-R": ["lmy-920", "lmy 920", "lmy920"],
    # ---- BMS-986393 = arlocabtagene autoleucel (GPRC5D CAR-T) ----
    "GPRC5D": ["bms-986393", "bms986393",
                "arlocabtagene autoleucel", "arlo-cel"],
    "NKG2D-L": ["cyad-01"],
    # New target labels seen repeatedly in curation loop
    "Claudin 18.2": ["ct041", "satricabtagene autoleucel", "satri-cel"],
    "B7-H3": ["mt027"],
    "GPC3": ["boxr1030"],
    "FLT3": ["taa05"],
    "GPNMB": ["gcar1"],
    "CDH17": ["cdh17/gucy2c"],
}

# ---------------------------------------------------------------------------
# Canonical display name per product (alias → canonical).
# Per-product pipeline view aggregates by this canonical so that e.g.
# "axicabtagene ciloleucel", "yescarta", and "axi-cel" collapse to one row.
# Keys are ALL the aliases in NAMED_PRODUCT_TARGETS (lowercase, as stored).
# Where a product has no widely-used brand name yet, the canonical is the
# most-recognisable codename.
# ---------------------------------------------------------------------------

CANONICAL_PRODUCT_NAME: dict[str, str] = {
    # FDA-approved CAR-Ts
    "axicabtagene ciloleucel": "axi-cel (Yescarta)",
    "yescarta":                "axi-cel (Yescarta)",
    "axi-cel":                 "axi-cel (Yescarta)",

    "tisagenlecleucel":        "tisa-cel (Kymriah)",
    "kymriah":                 "tisa-cel (Kymriah)",

    "lisocabtagene maraleucel": "liso-cel (Breyanzi)",
    "liso-cel":                 "liso-cel (Breyanzi)",
    "breyanzi":                 "liso-cel (Breyanzi)",

    "ciltacabtagene autoleucel": "cilta-cel (Carvykti)",
    "cilta-cel":                 "cilta-cel (Carvykti)",
    "carvykti":                  "cilta-cel (Carvykti)",

    "brexucabtagene autoleucel": "brexu-cel (Tecartus)",
    "brexu-cel":                 "brexu-cel (Tecartus)",
    "tecartus":                  "brexu-cel (Tecartus)",

    "idecabtagene vicleucel":    "ide-cel (Abecma)",
    "ide-cel":                   "ide-cel (Abecma)",
    "abecma":                    "ide-cel (Abecma)",

    "obecabtagene autoleucel":   "obe-cel (Aucatzyl)",
    "obe-cel":                   "obe-cel (Aucatzyl)",
    "aucatzyl":                  "obe-cel (Aucatzyl)",

    # NMPA (China)
    "relmacabtagene autoleucel": "relma-cel (Carteyva)",
    "relma-cel":                 "relma-cel (Carteyva)",
    "carteyva":                  "relma-cel (Carteyva)",

    "equecabtagene autoleucel":  "eque-cel (Fucaso)",
    "eque-cel":                  "eque-cel (Fucaso)",
    "fucaso":                    "eque-cel (Fucaso)",

    "zevorcabtagene autoleucel": "zevor-cel",
    "zevor-cel":                 "zevor-cel",

    "inaticabtagene autoleucel": "inati-cel",
    "inati-cel":                 "inati-cel",

    # Clinical-stage CAR-Ts (by codename)
    "ct041":                       "CT041 / satri-cel",
    "satri-cel":                   "CT041 / satri-cel",
    "satricabtagene autoleucel":   "CT041 / satri-cel",

    "gc012f":                      "GC012F",
    "allo-501":                    "ALLO-501",
    "allo-501a":                   "ALLO-501A",
    "allo-715":                    "ALLO-715",
    "anito-cel":                   "anito-cel",
    "ct053":                       "CT053",
    "mt027":                       "MT027",
    "meta10-19":                   "Meta10-19",
    "jy231":                       "JY231",
    "ct1190b":                     "CT1190B",
    "ptoc1":                       "PTOC1",
    "gcar1":                       "GCAR1",
    "azd0120":                     "AZD0120",
    "hbi0101":                     "HBI0101",
    "ct0596":                      "CT0596",
    "taa05":                       "TAA05",
    "boxr1030":                    "BOXR1030",
    "cyad-01":                     "CYAD-01",
    "mb-cart2019.1":               "MB-CART19.1",
    "mb-cart2019":                 "MB-CART19.1",
    "mb-cart19.1":                 "MB-CART19.1",
    "cdh17/gucy2c":                "CDH17/GUCY2C",
}


NAMED_PRODUCT_TYPES: dict[str, list[str]] = {
    "In vivo": [],
    "Allogeneic/Off-the-shelf": [
        "allo-501", "allo-501a", "allo-715",
        "mt027",  # MT027 explicitly allogeneic in trial titles
    ],
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
        # Curation-loop additions
        "jy231", "meta10-19", "ct1190b", "ptoc1",
        "ct0596", "hbi0101",
        "ct041", "satricabtagene autoleucel", "satri-cel",
        "boxr1030", "taa05", "gcar1",
        "azd0120",
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
