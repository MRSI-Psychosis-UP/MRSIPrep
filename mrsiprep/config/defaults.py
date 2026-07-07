"""Default values for MRSIPrep."""

METABOLITES_3T = ["CrPCr", "GluGln", "GPCPCh", "NAANAAG", "Ins"]
METABOLITES_7T = ["NAA", "NAAG", "Ins", "GPCPCh", "Glu", "Gln", "CrPCr", "GABA", "GSH"]

METABOLITE_ALIASES = {
    "Glx": ["GluGln", "Glx"],
    "GluGln": ["GluGln", "Glx"],
    "NAA": ["NAA", "NAANAAG"],
    "tNAA": ["NAANAAG", "tNAA", "NAA"],
    "NAANAAG": ["NAANAAG", "tNAA", "NAA"],
    "Cho": ["GPCPCh", "Cho"],
    "GPCPCh": ["GPCPCh", "Cho"],
    "tCr": ["CrPCr", "tCr"],
    "CrPCr": ["CrPCr", "tCr"],
    "Ins": ["Ins"],
}

QUALITY_DEFAULTS = {
    "snr_min": 4.0,
    "linewidth_max": 0.1,
    "crlb_max": 20.0,
}

CHIMERA_SCALES = {"scale1": 1, "scale2": 2, "scale3": 3, "scale4": 4, "scale5": 5}
