"""Default values for MRSIPrep."""

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
