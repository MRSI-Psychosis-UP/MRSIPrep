"""Preprocessing parameters + pipeline DAG section (Preproc tab)."""

from __future__ import annotations

# Human-readable label per STEP_SEQUENCE node name, in execution order --
# a static chain diagram, since the actual per-recording Nipype graph is
# only ever built when running through the Nipype engine (not e.g. under
# --reports-only, which executes the same steps directly), and a fixed
# linear pipeline needs no runtime introspection or Graphviz dependency to
# describe accurately.
_STEP_LABELS = (
    ("prepare", "Validate inputs"),
    ("tissue_seg", "Tissue segmentation"),
    ("anat", "Anatomical prep"),
    ("mrsi", "MRSI preprocessing"),
    ("registration", "Registration"),
    ("tissue_probmaps", "Tissue probability maps"),
    ("tissue_qc", "Tissue QC"),
    ("pvc", "Partial volume correction"),
    ("resampling", "Resampling"),
    ("leakage_qc", "Leakage QC"),
    ("synthseg_parc_qc", "SynthSeg parcellation QC"),
    ("parcellation", "Parcellation"),
    ("regional", "Regional extraction"),
    ("connectivity", "Connectivity"),
    ("metprofiles", "Metabolite profiles"),
    ("reports", "Reports"),
)

# (label, config attribute, formatter) -- the processing parameters most
# relevant to what actually ran for this recording, not every config field.
_PARAM_ROWS = (
    ("Tissue backend", "tissue_backend", str),
    ("Registration backend", "registration_backend", str),
    ("Registration T1w target", "registration_t1_target", str),
    ("Normalization", "normalization", str),
    ("Output spaces", "output_spaces", lambda value: ", ".join(value) if value else "none"),
    ("Parcellation mode", "parcellation_mode", str),
    ("Atlas", "atlas", str),
    ("SNR min", "snr_min", str),
    ("Linewidth max", "linewidth_max", str),
    ("CRLB max", "crlb_max", str),
    ("Biharmonic spike filtering", "filter_biharmonic", str),
    ("Spike percentile", "spike_percentile", str),
    ("PVC disabled", "no_pvc", str),
    ("T1 saturation correction", "t1_correction", str),
    ("Connectivity", "write_connectivity", str),
    ("nproc x nthreads", None, lambda config: f"{config.nproc} x {config.nthreads}"),
)


def build_preproc_overview_sections(config) -> list[tuple[str, str]]:
    """Returns the Preproc tab's (heading, body_html) sections: the
    processing parameters actually used for this run, and a static diagram
    of the fixed pipeline stage order."""
    rows = []
    for label, attr, formatter in _PARAM_ROWS:
        value = formatter(config) if attr is None else formatter(getattr(config, attr, None))
        rows.append(f"<tr><td>{label}</td><td>{value}</td></tr>")
    param_table = "<table><tr><th>Parameter</th><th>Value</th></tr>" + "".join(rows) + "</table>"

    chain = " &rarr; ".join(f"<span class='dag-node'>{label}</span>" for _name, label in _STEP_LABELS)
    dag_html = f"<div class='dag-chain'>{chain}</div>"

    return [
        ("Processing parameters", param_table),
        ("Pipeline stages", dag_html),
    ]
