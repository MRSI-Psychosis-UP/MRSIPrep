"""Streamlit form that assembles a runnable `mrsiprep-docker` command.

Auto-derived from the real CLI parser (mrsiprep.cli.parser.build_parser), so
the form's fields, choices, and defaults stay in sync with the actual CLI --
no second, hand-maintained copy of the 80+ flags to drift out of date. The
generated command uses the `mrsiprep-docker` host-side wrapper (see
docs/usage_basic.md), not `mrsiprep` directly -- mrsiprep itself only runs
inside the Docker image, not on the host.

This tool builds and displays the command string; it never shells out to
`docker run` (out of scope for a lightweight command-builder). It does,
however, offer a "Run preflight check" button that validates the current
form's inputs (file presence/validity for T1w, raw MRSI maps, mrsinmrs.json)
directly in-process -- the same read-only checks as `--validate-only`,
needing only mrsiprep's own pip dependencies (no Docker, no nipype/ANTs/
FreeSurfer, nothing written to disk).

Run with:
    streamlit run mrsiprep/interfaces/command_builder_app.py
"""

from __future__ import annotations

import argparse
import base64
import html
import mimetypes
import re
import shlex
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from mrsiprep.cli.parser import build_parser
from mrsiprep.utils.version import mrsiprep_version
from mrsiprep.config.chimera_schemes import (
    SUPRA_REGION_LABELS,
    SUPRA_REGIONS,
    build_scheme_code,
    valid_letters,
)
from mrsiprep.config.nuclei import DEFAULT_NUCLEUS, NucleusError, metabolite_aliases
from mrsiprep.workflows.nipype_engine.steps_registry import STEP_DEPENDENCIES, validate_step_order

# Debug/internal flags not useful in a user-facing form.
EXCLUDED_FLAGS = {"--hello-world", "--help", "-h"}

# Analysis-step outcome-card thumbnails (see _render_wizard_analysis_step).
WIZARD_ASSETS_DIR = Path(__file__).parent / "assets"
WIZARD_NORMALIZE_THUMBNAIL = WIZARD_ASSETS_DIR / "wizard_normalize_thumbnail.svg"
WIZARD_PARCELLATION_THUMBNAIL = WIZARD_ASSETS_DIR / "wizard_parcellation_thumbnail.png"
WIZARD_THUMBNAIL_HEIGHT_PX = 220


def _render_wizard_thumbnail(path: Path, height_px: int = WIZARD_THUMBNAIL_HEIGHT_PX) -> None:
    """Render `path` into a fixed-height, full-width box, cropping (not
    stretching) to fill it -- st.image alone has no crop mode, and the two
    outcome-card source images have very different native aspect ratios
    (a wide/short metabolite-map montage vs. a near-square brain render),
    so stretching each to the column width independently made them look
    wildly disproportionate next to each other."""
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    st.markdown(
        f"<div style='width:100%;height:{height_px}px;border-radius:0.5rem;overflow:hidden;'>"
        f"<img src='data:{mime};base64,{encoded}' "
        f"style='width:100%;height:100%;object-fit:cover;display:block;'></div>",
        unsafe_allow_html=True,
    )

# store_true/store_false flag pairs sharing one dest (e.g. --fsl-deformable /
# --no-fsl-deformable): only the positive flag gets a widget; the negative
# flag is inferred by omission, matching how the two actually interact.
NEGATIVE_FLAG_PAIRS = {"--no-fsl-deformable"}

POSITIONAL_HELP = {
    "bids_dir": "Path to the BIDS dataset root.",
    "output_dir": "Path to write derivatives to.",
}

# Which CLI flags are relevant to each pipeline step, for the Custom
# Pipeline tab's and the guided wizard's Processing step's per-step
# expanders. Hand-maintained against the real per-step `config.*` reads
# traced in mrsiprep/workflows/steps.py (and its callees). parser.py's own
# argparse groups now mirror this same per-step structure (one group per
# STEP_SEQUENCE step), but this dict is kept independently hand-maintained
# rather than derived from it, since a handful of flags are read by more
# than one step and an argparse group can only pick one primary home for
# each. In particular:
# --regional-summary affects metprofiles, not regional; the quality-
# threshold flags (--snr-min/--linewidth-max/--crlb-max/--quantification-tool/
# --linewidth-unit/--nucleus/--quality-metrics) belong to mrsi_quality (where
# make_quality_masks runs), not mrsi_load; --metabolites belongs to prepare
# (it gates which metabolite maps load_mrsi_inputs loads at all, inside
# validate_recording -- see mrsiprep/io/validators.py), not mrsi_quality or
# mrsi_load, neither of which reads config.metabolites directly; --ref-met
# belongs to mrsi_reference (where generate_reference runs) as well as
# mrsi_load, where it also seeds orientation correction; --crlb-unit/
# --connectivity-space are validation-only/legacy no-ops never read by any
# step's own logic, so neither gets a widget here.
#
# Order within each step's list matters where one flag's visibility depends
# on another's value (e.g. "mrsi_parcellation"'s --parcellation-mode must
# render before --chimera-scheme/--atlas/etc.).
#
# Steps with an empty list have no step-specific flags of their own -- the
# Custom tab still lists them (for ordering/validation) but renders only a
# "No step-specific options" caption.
CUSTOM_STEP_FLAGS: dict[str, list[str]] = {
    "prepare": ["--metabolites"],
    "tissue_seg": ["--tissue-backend", "--overwrite-seg"],
    "anatprep": ["--registration-t1-target", "--csf-pv-threshold", "--overwrite-t1-reg"],
    "mrsi_load": ["--mrsinmrs-file", "--correct-mrsi-orientation", "--registration-backend", "--fsl-cost", "--ref-met"],
    "spike_filter": [
        "--no-filter", "--filter-fwhm-mm", "--spikepc", "--spike-max-cluster-voxels",
        "--spike-extreme-zscore", "--overwrite-filt",
    ],
    "t1_saturation_correction": ["--t1-correction", "--t1-correction-water-status", "--overwrite-t1corr"],
    "mrsi_reference": ["--ref-met"],
    "mrsi_quality": [
        "--quantification-tool", "--linewidth-unit", "--nucleus",
        "--quality-metrics", "--snr-min", "--linewidth-max", "--crlb-max",
    ],
    "registration": [
        "--registration-backend", "--ants-mrsi-to-t1-transform", "--ants-t1-to-template-transform",
        "--fsl-mrsi-to-t1-dof", "--fsl-mrsi-to-t1-init", "--fsl-t1-to-template-dof", "--fsl-cost",
        "--fsl-deformable", "--fsl-fnirt-warpres", "--fsl-fnirt-lambda", "--normalization",
        "--output-spaces", "--registration-t1-target", "--longitudinal",
        "--overwrite-t1-reg", "--overwrite-template-reg",
    ],
    "tissue_probmaps": ["--tissue-backend"],
    "tissue_qc": [],
    "pvc": ["--no-pvc", "--overwrite-pve"],
    "resampling": ["--output-spaces", "--output-mrsi-t1w", "--transform-spikemask", "--overwrite-transform"],
    "leakage_qc": [],
    "anat_parcellation_qc": [],
    "mrsi_parcellation": [
        "--parcellation-mode", "--chimera-scheme", "--chimera-scale", "--chimera-grow",
        "--fs-license", "--fs-subjects-dir", "--overwrite-chimera",
        "--atlas", "--custom-atlas", "--custom-atlas-lut",
    ],
    "regional": [],
    "connectivity": [
        "--write-connectivity", "--connectivity-method", "--connectivity-n-perturbations",
        "--connectivity-sigma-scale", "--connectivity-exclude-parcels", "--connectivity-max-parcel-id",
    ],
    "metprofiles": ["--regional-summary"],
    "reports": [],
}

assert set(CUSTOM_STEP_FLAGS) == set(STEP_DEPENDENCIES), (
    f"CUSTOM_STEP_FLAGS (command_builder_app.py) is out of sync with STEP_DEPENDENCIES "
    f"(steps_registry.py): {set(CUSTOM_STEP_FLAGS) ^ set(STEP_DEPENDENCIES)}"
)

# The two branches that converge at "registration", for the Custom Pipeline
# tab's two-column add-step UI: prepare/tissue_seg/anatprep (anatomical prep)
# runs independently of mrsi_load/spike_filter/t1_saturation_correction/
# mrsi_reference/mrsi_quality (MRSI loading/correction) -- neither needs the
# other to finish first, so they're offered as two parallel columns rather
# than one flat ordered list. Every other step runs after both converge,
# offered via a single selectbox below.
ANAT_BRANCH_STEPS = ["prepare", "tissue_seg", "anatprep"]
MRSI_BRANCH_STEPS = ["mrsi_load", "spike_filter", "t1_saturation_correction", "mrsi_reference", "mrsi_quality"]
DOWNSTREAM_STEPS = [
    name for name in CUSTOM_STEP_FLAGS if name not in ANAT_BRANCH_STEPS and name not in MRSI_BRANCH_STEPS
]

# Human-readable (label, help) overrides for the guided wizard, keyed by
# `action.dest` (not the raw "--flag" spelling, since that's what every
# argparse.Action already carries as its own stable identity regardless of
# option-string spelling). Consulted by _widget_for's label_override/
# help_override kwargs -- the raw CLI flag name is always appended as
# secondary text by the wizard's own rendering (see _render_wizard_data_step/
# _render_wizard_processing_step), never hidden, satisfying "CLI names
# secondary, not removed." A dest not listed here just falls back to
# _widget_for's own defaults (today's _dest_label(action)/action.help).
WIZARD_FIELD_LABELS: dict[str, tuple[str, str]] = {
    "bids_dir": ("Dataset folder", "Paste the path to your BIDS dataset root."),
    "output_dir": ("Output folder", "Where MRSIPrep derivatives and reports will be written."),
    "t1_pattern": (
        "T1w image pattern",
        "BIDS entity/suffix pattern used to locate the skull-stripped T1w image for each recording.",
    ),
    "mrsinmrs_file": ("Acquisition metadata file", "The mrsinmrs.json file describing your MRSI acquisition."),
    "mrsi_input_dir": ("Raw MRSI data folder", "Root folder containing the raw MRSI derivatives."),
    "participant_label": (
        "Subjects",
        "Subject labels to process, without the 'sub-' prefix. To pin a specific session per subject, "
        "name it directly, e.g. '5301_ses-V6, 5323_ses-V4' -- no need to fill in Sessions for those.",
    ),
    "session_label": (
        "Sessions",
        "Session labels to process, without the 'ses-' prefix. Only applies to Subjects entries that "
        "don't already name their own session (e.g. plain '5301', not '5301_ses-V6').",
    ),
    "participants": ("Participant list file", "A TSV/CSV file listing which subject/session pairs to process."),
    "metabolites": ("Metabolites", "Which metabolite maps to process."),
    "ref_met": ("Reference metabolite", "The metabolite map used to register MRSI to the T1w anatomical."),
    "parcellation_mode": (
        "Parcellation method",
        "How brain regions are labeled for per-region metabolite and connectivity output.",
    ),
    "write_connectivity": (
        "Compute connectivity matrix",
        "Build a regional metabolic connectivity (similarity) matrix on top of the regional profiles.",
    ),
    "fs_license": ("FreeSurfer license file", "Required only when the parcellation method is 'chimera'."),
    "atlas": ("Atlas", "Which standardized atlas to warp into subject space."),
    "nthreads": ("Threads per recording", "ANTs/ITK thread count per subject/session process."),
    "nproc": ("Parallel recordings", "Number of subject/session recordings to process in parallel."),
    "work_dir": ("Work folder", "Scratch/intermediate files folder; safe to delete between runs."),
    "reports_only": (
        "Only regenerate reports",
        "Reuse every already-computed derivative as-is (tissue segmentation, registration, parcellation, "
        "etc. are never recomputed) and just rewrite QC tables, figures, and the HTML report. Use this "
        "after a run already completed, e.g. to pick up a report-template change, without reprocessing. "
        "Fails a recording with a clear error if a required upstream derivative is missing, rather than "
        "silently recomputing it.",
    ),
}

# Per-step flag groups shown as the Processing step's four expanders (plan
# §3, Step 3). Each entry's flags are looked up from CUSTOM_STEP_FLAGS
# (the per-step, hand-maintained flag-ownership dict above) -- unioned across
# every step name listed, in CUSTOM_STEP_FLAGS iteration order, with
# duplicates (a flag legitimately owned by more than one step, e.g.
# --ref-met) collapsed to their first occurrence. "Runtime and existing
# outputs" has no step of its own in CUSTOM_STEP_FLAGS (nthreads/nproc/
# work-dir/overwrite* have no per-step home -- see steps_registry.py's own
# notes) so it's listed as a fixed flag list instead of step names.
PROCESSING_EXPANDER_STEP_GROUPS: dict[str, list[str]] = {
    "Registration": ["registration", "anatprep"],
    "Tissue and relaxation corrections": [
        "tissue_seg", "spike_filter", "t1_saturation_correction", "pvc", "tissue_probmaps",
    ],
    "Parcellation and connectivity": ["mrsi_parcellation", "regional", "connectivity", "metprofiles"],
}

RUNTIME_EXPANDER_FLAGS: list[str] = [
    "--reports-only",
    "--nthreads", "--nproc", "--work-dir", "--overwrite",
    "--overwrite-seg", "--overwrite-t1-reg", "--overwrite-template-reg", "--overwrite-filt",
    "--overwrite-t1corr", "--overwrite-pve", "--overwrite-transform", "--overwrite-chimera",
]

# Branch colors for the flowchart (see _render_step_flowchart) -- matches
# the Custom Pipeline tab's own branch badges (_branch_badge), plus one more
# for the display-only pseudo-nodes (anat_load/load_template).
_FLOWCHART_BRANCH_COLOR = {"anat": "#79a269", "mrsi": "#2c96ab", "down": "#9376c5", "pseudo": "#ce9752"}

# Fixed, display-only pseudo-nodes -- never real --steps values (none is in
# CUSTOM_STEP_FLAGS, addable/removable in the Custom Pipeline tab, or passed
# to validate_step_order), drawn purely so the diagram reads clearly:
#
# - ANAT_LOAD_NODE: the anat branch's own loading stage, mirroring mrsi_load
#   starting the mrsi branch -- real code has no separate "load" step before
#   tissue_seg, prepare's own T1w/BIDS lookup covers it, but drawing the two
#   branches with visually matching starting points is clearer than leaving
#   the anat branch looking like it starts mid-stream.
# - TEMPLATE_NODE: T1w-to-MNI ("anat-template") registration is a real
#   second stage inside the single real "registration" step itself
#   (run_registration_workflow runs it conditionally, only when MNI output/
#   parcellation is requested -- see mrsiprep/workflows/registration.py),
#   not a separate STEP_SEQUENCE entry -- drawn feeding a second, separately
#   labeled box for that same "registration" step (see
#   REGISTRATION_MRSI_T1_NODE/REGISTRATION_TEMPLATE_NODE below).
ANAT_LOAD_NODE = "anat_load"
TEMPLATE_NODE = "load_template"

# "registration" is drawn as two boxes (same single real step, two labeled
# faces) since it does two independent things: MRSI<->T1w (always) and
# T1w<->MNI template (conditionally) -- see TEMPLATE_NODE's note above.
REGISTRATION_MRSI_T1_NODE = "registration_mrsi_t1"
REGISTRATION_TEMPLATE_NODE = "registration_t1_template"

_PSEUDO_NODES = {ANAT_LOAD_NODE, TEMPLATE_NODE, REGISTRATION_MRSI_T1_NODE, REGISTRATION_TEMPLATE_NODE}

_NODE_LABELS = {
    ANAT_LOAD_NODE: "anat_load",
    TEMPLATE_NODE: "load_template",
    REGISTRATION_MRSI_T1_NODE: "registration (MRSI↔T1w)",
    REGISTRATION_TEMPLATE_NODE: "registration (T1w↔MNI)",
    # transform_mrsi_maps resamples into whichever of T1w/MNI space(s)
    # --output-spaces actually requests, same dual nature as registration,
    # but it's one real function call (not two stages), so it stays one box
    # -- just a label clarifying what it resamples into.
    "resampling": "resampling (T1w + MNI)",
}


# Which real step's CUSTOM_STEP_FLAGS entry a display node's hover tooltip
# should pull its argument list from. Display nodes not listed here either
# are a real step already (so CUSTOM_STEP_FLAGS[step_name] applies directly)
# or have no args of their own (ANAT_LOAD_NODE/TEMPLATE_NODE -- purely
# cosmetic placeholders, see their own docstring notes above).
_NODE_FLAG_SOURCE = {
    REGISTRATION_MRSI_T1_NODE: "registration",
    REGISTRATION_TEMPLATE_NODE: "registration",
}


def _node_tooltip(step: str, values: dict) -> str:
    """Hover text for one flowchart node: its current argument values, one
    per line. Rebuilt fresh on every render (same `values` dict the rest of
    the form already uses), so it reflects whatever the user has typed in
    so far -- no JS needed, since Streamlit reruns and redraws this whole
    SVG on every widget change already."""
    flags = CUSTOM_STEP_FLAGS.get(_NODE_FLAG_SOURCE.get(step, step), [])
    if not flags:
        return _NODE_LABELS.get(step, step)
    lines = [_NODE_LABELS.get(step, step)]
    for flag in flags:
        value = values.get(flag)
        if value in (None, "", False, []):
            continue
        lines.append(f"{flag} = {value}")
    if len(lines) == 1:
        lines.append("(all defaults)")
    return "\n".join(lines)


def _flowchart_branch(step_name: str) -> str:
    if step_name in _PSEUDO_NODES:
        return "pseudo"
    if step_name in ANAT_BRANCH_STEPS:
        return "anat"
    if step_name in MRSI_BRANCH_STEPS:
        return "mrsi"
    return "down"


def _is_qc_only_step(step_name: str) -> bool:
    """True when `step_name`'s outputs are never required/optional by any
    step except "reports" -- derived straight from STEP_DEPENDENCIES rather
    than a hardcoded name list, so any *future* step shaped the same way
    (a QC/report-building side-effect nothing downstream consumes) diverges
    in the flowchart automatically, regardless of which module its code
    ends up living in. A step with no real downstream consumer at all
    (empty `consumers`) also counts, matching "reports" itself (which is
    excluded separately, it's the merge point, not a QC leaf)."""
    if step_name not in STEP_DEPENDENCIES or step_name == "reports":
        return False
    produced = STEP_DEPENDENCIES[step_name].produces
    consumers = {
        other for other, deps in STEP_DEPENDENCIES.items()
        if other != step_name and (produced & deps.requires or produced & deps.optional)
    }
    return consumers <= {"reports"}


def _display_chains(step_names: list[str], filter_enabled: bool, t1_correction_enabled: bool):
    """Builds the display chains (lists of display node ids, mixing real
    step names with the fixed pseudo-nodes above), applying every
    display-only rule in one place:
    - "prepare" is never drawn (shared prerequisite of both branches, not a
      per-branch stage).
    - The anat branch always starts with the display-only ANAT_LOAD_NODE.
    - "spike_filter" is only drawn when `filter_enabled` (i.e. --no-filter
      is not set) -- otherwise it's a pure no-op pass-through (see
      run_spike_filter_workflow), same convention as t1_saturation_correction
      below.
    - "t1_saturation_correction" is only drawn when `t1_correction_enabled`
      (i.e. --t1-correction is not "none") -- otherwise it's a pure no-op
      pass-through and showing it as a stage implies it does something.
    - "registration", if present, is drawn as REGISTRATION_MRSI_T1_NODE
      (always) immediately followed by REGISTRATION_TEMPLATE_NODE (always,
      fed additionally by TEMPLATE_NODE) in the downstream chain -- both
      represent the single real "registration" step; downstream steps are
      wired from REGISTRATION_TEMPLATE_NODE.
    - Any step for which _is_qc_only_step() is true (today: tissue_qc,
      leakage_qc) is pulled out of the main downstream chain entirely --
      it's a side effect nothing but "reports" ever reads, so the main
      chain shouldn't visually route through it. It's returned separately
      as (step, producer) pairs: `producer` is the nearest earlier step in
      `present_order` that is NOT itself QC-only (so a QC step always
      branches off its real upstream dependency, not another QC step).

    Returns (anat_chain, mrsi_chain, downstream_chain, qc_branches) where
    qc_branches is a list of (qc_step, producer_step) pairs.
    """
    present_order = [s for s in CUSTOM_STEP_FLAGS if s in step_names]

    anat_chain = [ANAT_LOAD_NODE] + [s for s in present_order if s in ANAT_BRANCH_STEPS and s != "prepare"]

    mrsi_chain = []
    for s in present_order:
        if s not in MRSI_BRANCH_STEPS:
            continue
        if s == "spike_filter" and not filter_enabled:
            continue
        if s == "t1_saturation_correction" and not t1_correction_enabled:
            continue
        mrsi_chain.append(s)

    downstream_chain = []
    qc_branches: list[tuple[str, str]] = []
    last_main_step = None
    for s in present_order:
        if s not in DOWNSTREAM_STEPS:
            continue
        if _is_qc_only_step(s):
            if last_main_step is not None:
                qc_branches.append((s, last_main_step))
            continue
        if s == "registration":
            downstream_chain.append(REGISTRATION_MRSI_T1_NODE)
            downstream_chain.append(REGISTRATION_TEMPLATE_NODE)
            last_main_step = REGISTRATION_TEMPLATE_NODE
            continue
        downstream_chain.append(s)
        last_main_step = s

    return anat_chain, mrsi_chain, downstream_chain, qc_branches


def _step_edges(
    step_names: list[str], filter_enabled: bool = True, t1_correction_enabled: bool = False
) -> list[tuple[str, str]]:
    """(from, to) edges among the display chains built by _display_chains:
    one edge per consecutive pair within each of the three main lanes (anat
    branch, mrsi branch, downstream), plus the two branches' own convergence
    edges into the downstream chain's first entry, plus TEMPLATE_NODE's
    fixed edge into REGISTRATION_TEMPLATE_NODE when registration is drawn,
    plus the QC column's own edges: one short producer->qc_step edge per QC
    branch, one edge chaining each QC step down to the next one in the
    column (so the column reads top-to-bottom as its own mini-chain instead
    of each branch independently reaching back across to "reports"), and a
    single final edge from the column's last entry into "reports".
    Deliberately simplified relative to STEP_DEPENDENCIES' full transitive
    accuracy (a step like "reports" legitimately requires most of the
    pipeline's outputs, and drawing all of that produces an unreadable
    tangle) -- full key-level dependencies remain enforced by
    validate_step_order() regardless of what this diagram draws."""
    anat_chain, mrsi_chain, downstream_chain, qc_branches = _display_chains(
        step_names, filter_enabled, t1_correction_enabled
    )

    edges: list[tuple[str, str]] = []
    for chain in (anat_chain, mrsi_chain, downstream_chain):
        for a, b in zip(chain, chain[1:]):
            edges.append((a, b))
    if downstream_chain:
        first_downstream = downstream_chain[0]
        if anat_chain:
            edges.append((anat_chain[-1], first_downstream))
        if mrsi_chain:
            edges.append((mrsi_chain[-1], first_downstream))
        if REGISTRATION_TEMPLATE_NODE in downstream_chain:
            edges.append((TEMPLATE_NODE, REGISTRATION_TEMPLATE_NODE))
    # Only the column's very first entry gets a direct producer->qc_step
    # edge; every later entry is reached purely by the chain below, even
    # when it happens to share the same real producer as an earlier entry
    # (e.g. connectivity and metprofiles both come from "regional") --
    # otherwise that producer would get a second, redundant, crossing edge
    # straight to the later entry too.
    if qc_branches:
        edges.append((qc_branches[0][1], qc_branches[0][0]))
    for (a, _producer_a), (b, _producer_b) in zip(qc_branches, qc_branches[1:]):
        edges.append((a, b))
    if qc_branches and "reports" in downstream_chain:
        edges.append((qc_branches[-1][0], "reports"))
    return edges


def _flowchart_layout(
    step_names: list[str], filter_enabled: bool = True, t1_correction_enabled: bool = False
) -> dict[str, tuple[float, float]]:
    """Node center positions for the display chains built by
    _display_chains: anat-branch chain in a left column, mrsi-branch chain
    in a right column (each its own straight line, independent of the
    other), then the downstream chain centered below in one single straight
    line -- matching _step_edges' lanes exactly, so the drawn lines never
    cross. TEMPLATE_NODE is placed in a fourth, far-right column at
    mrsi_load's own row height (row 0), the same height ANAT_LOAD_NODE/
    mrsi_load themselves sit at, not at the (lower) registration row. All
    QC-only steps (tissue_qc, leakage_qc, connectivity, metprofiles, ...)
    share one single far-right column, stacked top-to-bottom in pipeline
    order -- not one column per producer -- since that reads as the
    column's own short, clean mini-chain (short horizontal leg in from its
    producer, short vertical leg down to the next QC entry) instead of
    several long diagonals each reaching back across to "reports"."""
    card_w, card_h, col_gap, row_gap = 170, 50, 110, 60
    positions: dict[str, tuple[float, float]] = {}

    anat_chain, mrsi_chain, downstream_chain, qc_branches = _display_chains(
        step_names, filter_enabled, t1_correction_enabled
    )
    left_x = card_w / 2 + 10
    right_x = left_x + card_w + col_gap
    for i, step in enumerate(anat_chain):
        positions[step] = (left_x, 10 + card_h / 2 + i * (card_h + row_gap))
    for i, step in enumerate(mrsi_chain):
        positions[step] = (right_x, 10 + card_h / 2 + i * (card_h + row_gap))

    if downstream_chain:
        center_x = (left_x + right_x) / 2 if (anat_chain and mrsi_chain) else (
            left_x if anat_chain else (right_x if mrsi_chain else card_w / 2 + 10)
        )
        base_y = 10 + max(len(anat_chain), len(mrsi_chain), 1) * (card_h + row_gap) + row_gap
        producer_row: dict[str, int] = {}
        for i, step in enumerate(downstream_chain):
            positions[step] = (center_x, base_y + i * (card_h + row_gap))
            producer_row[step] = i

        if REGISTRATION_TEMPLATE_NODE in downstream_chain:
            template_x = right_x + card_w + col_gap
            positions[TEMPLATE_NODE] = (template_x, 10 + card_h / 2)

        # One shared column: stacked in the order _step_edges already chains
        # them in (pipeline order, i.e. qc_branches' own order), starting
        # one row below the main chain's first entry so the column's first
        # box lines up near its own producer rather than the very top.
        qc_x = center_x + card_w + col_gap
        qc_start_row = min((producer_row.get(p, 0) for _q, p in qc_branches), default=0)
        for i, (qc_step, _producer) in enumerate(qc_branches):
            positions[qc_step] = (qc_x, base_y + (qc_start_row + i) * (card_h + row_gap))

    return positions


def _render_step_flowchart(step_names: list[str], values: dict | None = None) -> None:
    """Renders a flowchart of `step_names` as an inline SVG: two parallel
    branch columns (anat, mrsi) converging into one straight downstream
    line (see _step_edges/_flowchart_layout/_display_chains) -- a pure
    read-only diagram, no interactivity, built fresh from the current
    `step_names` every call so the Custom Pipeline tab's graph updates
    automatically on every rerun (i.e. every time a step is added/removed/
    reordered, since Streamlit reruns the whole script on each interaction).

    `values` is the form's current flag values (same dict _build_command
    reads), used only to resolve whether spike filtering/T1 water
    correction are actually enabled for display purposes -- defaults to
    "both as if not yet decided" (filtering on, since that's the CLI
    default; T1 correction off, since that's the CLI default) when no
    `values` is given."""
    if not step_names:
        st.caption("Add a step to see its flowchart.")
        return

    values = values or {}
    filter_enabled = not values.get("--no-filter", False)
    t1_correction_enabled = values.get("--t1-correction", "none") not in (None, "none")

    edges = _step_edges(step_names, filter_enabled, t1_correction_enabled)
    positions = _flowchart_layout(step_names, filter_enabled, t1_correction_enabled)
    card_w, card_h = 170, 50
    xs = [p[0] for p in positions.values()]
    ys = [p[1] for p in positions.values()]
    width = max(xs) + card_w / 2 + 20
    height = max(ys) + card_h / 2 + 20

    # CSS tooltip instead of SVG's native <title> -- <title> carries the
    # browser/OS's own hover delay (commonly ~1s, not controllable from
    # SVG/CSS), which read as sluggish. A plain CSS :hover rule shows its
    # target the instant the pointer enters the node, no delay.
    tooltip_css = (
        "<style>"
        ".fc-node{cursor:default}"
        ".fc-tip{opacity:0;transition:none;pointer-events:none}"
        ".fc-node:hover .fc-tip{opacity:1}"
        ".fc-tip-box{background:#0b0f16;border:1px solid #3a4a63;border-radius:6px;padding:6px 9px;"
        "font:11px/1.45 Arial,sans-serif;color:#e7ecf6;white-space:pre;box-shadow:0 4px 14px rgba(0,0,0,.4)}"
        "</style>"
    )
    parts = [
        tooltip_css,
        f"<svg viewBox='0 0 {width:.0f} {height:.0f}' width='100%' "
        f"style='max-width:{width:.0f}px' xmlns='http://www.w3.org/2000/svg'>",
        "<defs><marker id='fc-arrow' viewBox='0 0 8 8' markerWidth='6.5' markerHeight='6.5' "
        "refX='7' refY='4' orient='auto' markerUnits='userSpaceOnUse'>"
        "<path d='M1 1 L7 4 L1 7 Z' fill='#9aa7bd'/></marker></defs>",
    ]
    for a, b in edges:
        ax, ay = positions[a]
        bx, by = positions[b]
        if a == TEMPLATE_NODE:
            # TEMPLATE_NODE sits far to the right at row 0, while its target
            # (REGISTRATION_TEMPLATE_NODE) is several rows down in the
            # center column -- a top-to-bottom curve would visually cross
            # straight through REGISTRATION_MRSI_T1_NODE's box sitting right
            # above it. Route side-to-side instead: leave from the left
            # edge of the template card, enter the right edge of its
            # target, so the curve passes to the right of every node
            # in between rather than through them.
            x1, y1 = ax - card_w / 2, ay
            x2, y2 = bx + card_w / 2, by
            mid_x = (x1 + x2) / 2
            d = f"M {x1:.1f} {y1:.1f} C {mid_x:.1f} {y1:.1f}, {mid_x:.1f} {y2:.1f}, {x2:.1f} {y2:.1f}"
            parts.append(f"<path d='{d}' stroke='#9aa7bd' stroke-width='1.6' fill='none' marker-end='url(#fc-arrow)'/>")
            continue
        x1, y1 = ax, ay + card_h / 2
        x2, y2 = bx, by - card_h / 2
        mid_y = (y1 + y2) / 2
        if abs(x2 - x1) > 4:
            d = f"M {x1:.1f} {y1:.1f} C {x1:.1f} {mid_y:.1f}, {x2:.1f} {mid_y:.1f}, {x2:.1f} {y2:.1f}"
        else:
            d = f"M {x1:.1f} {y1:.1f} L {x2:.1f} {y2:.1f}"
        parts.append(f"<path d='{d}' stroke='#9aa7bd' stroke-width='1.6' fill='none' marker-end='url(#fc-arrow)'/>")
    tip_w, tip_h = 230, 90
    for step in positions:
        cx, cy = positions[step]
        color = _FLOWCHART_BRANCH_COLOR[_flowchart_branch(step)]
        x, y = cx - card_w / 2, cy - card_h / 2
        label = _NODE_LABELS.get(step, step)
        # CSS-hover tooltip (see tooltip_css above) rather than SVG's native
        # <title>, for instant feedback. Rebuilt fresh from `values` on
        # every Streamlit rerun, so its content is always the form's
        # current state, not stale. Positioned above the card, clamped so
        # it doesn't run off the left/top edge of the canvas.
        tooltip_lines = _node_tooltip(step, values).split("\n")
        tooltip_html = "<br/>".join(html.escape(line) for line in tooltip_lines)
        tip_x = max(4, min(cx - tip_w / 2, width - tip_w - 4))
        tip_y = max(0, y - tip_h - 8)
        parts.append(
            f"<g class='fc-node'>"
            f"<rect x='{x:.1f}' y='{y:.1f}' width='{card_w}' height='{card_h}' rx='8' "
            f"fill='#1d2534' stroke='#303c52' stroke-width='1'/>"
            f"<rect x='{x:.1f}' y='{y + 8:.1f}' width='4' height='{card_h - 16}' rx='2' fill='{color}'/>"
            f"<text x='{x + 12:.1f}' y='{cy + 4:.1f}' font-size='11.5' font-weight='700' "
            f"fill='#e7ecf6' font-family='Arial,sans-serif'>{label}</text>"
            f"<foreignObject class='fc-tip' x='{tip_x:.1f}' y='{tip_y:.1f}' width='{tip_w}' height='{tip_h}'>"
            f"<div xmlns='http://www.w3.org/1999/xhtml' class='fc-tip-box'>{tooltip_html}</div>"
            f"</foreignObject>"
            f"</g>"
        )
    parts.append("</svg>")
    st.markdown(
        f"<div style='border:1px solid #303c52;border-radius:10px;background:#11161f;"
        f"padding:12px;overflow-x:auto'>{''.join(parts)}</div>",
        unsafe_allow_html=True,
    )


def _dest_label(action: argparse.Action) -> str:
    return action.option_strings[0] if action.option_strings else action.dest


def _is_flag(action: argparse.Action) -> bool:
    return action.nargs == 0


def _path_check(path_str: str) -> bool:
    """True when `path_str` is non-empty and exists on disk -- used to show
    an inline green checkmark next to a required-argument path field, purely
    a UI hint (not re-validation; real validation stays in _compute_preflight)."""
    return bool(path_str) and Path(path_str).exists()


def _render_check(ok: bool, missing_hint: str = "") -> None:
    """Small inline status marker rendered right after a required field:
    a green check once it resolves to something real, a muted placeholder
    otherwise so the row doesn't jump around as fields fill in."""
    if ok:
        st.markdown(
            "<div style='padding-top:1.9rem;font-size:1.3rem;color:#1a7f37;text-align:center' title='Looks good'>✔</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"<div style='padding-top:1.9rem;font-size:1.3rem;color:#c7cdd6;text-align:center' title='{missing_hint}'>·</div>",
            unsafe_allow_html=True,
        )


def _render_participants_widget(
    action: argparse.Action, bids_dir: str, key_prefix: str = "field_", label: str | None = None
):
    """Text input for --participants plus a "View" button that previews the
    TSV/CSV's first rows, since a bad/mistyped subject-session list here
    silently filters out every subject rather than erroring loudly.

    Live-autocompletes to <bids_dir>/participants_allsessions.tsv (the file
    BIDSLayout.discover_recordings() itself falls back to) until the
    "Custom path" checkbox is checked, same pattern as mrsi_input_dir and
    --mrsinmrs-file above.

    `key_prefix` isolates this widget's session-state keys from another
    caller rendering the same flag elsewhere (the Custom Pipeline tab uses
    "custom_field_" so its own --participants widget never collides with
    the Standardized tab's). `label` optionally overrides the displayed
    label (defaults to `_dest_label(action)`, preserving every existing
    call site's behavior)."""
    label = label if label is not None else _dest_label(action)
    help_text = (action.help or "").strip()
    key = f"{key_prefix}{action.dest}"
    default_path = f"{bids_dir.rstrip('/')}/participants_allsessions.tsv" if bids_dir else ""
    custom_before = st.session_state.get(f"{key}_custom", False)
    if not custom_before:
        # See mrsi_input_dir/--mrsinmrs-file above: only force-sync the
        # default while disabled, or a `value=` on every rerun would revert
        # whatever the user types once custom mode is on.
        st.session_state[key] = default_path
    # Input, "Custom path" checkbox, "View" button, and a status check share
    # one row instead of stacking across three lines -- the checkbox/button/
    # check only need a narrow column each, so most of the row stays with
    # the text field.
    col_input, col_custom, col_view, col_mark = st.columns([5, 2, 1, 1])
    with col_input:
        path_str = st.text_input(label, help=help_text, key=key, disabled=not custom_before)
    with col_custom:
        st.markdown("<div style='height:1.6rem'></div>", unsafe_allow_html=True)
        custom = st.checkbox(
            "Custom path",
            value=custom_before,
            key=f"{key}_custom",
            help="Off by default, which keeps --participants at "
            "<bids_dir>/participants_allsessions.tsv. Check this only if the subject/session "
            "list lives somewhere else.",
        )
    with col_view:
        st.markdown("<div style='height:1.6rem'></div>", unsafe_allow_html=True)
        view_clicked = st.button("View", key=f"{key}_view", disabled=not path_str)
    with col_mark:
        # Informational only -- --participants has a directory-scan fallback
        # when missing, so it never gates the preflight-ready highlight.
        _render_check(_path_check(path_str), "Optional: falls back to a directory scan if missing")
    if view_clicked:
        path = Path(path_str)
        if not path.exists():
            st.error(f"File not found: {path}")
        else:
            try:
                sep = "\t" if path.suffix.lower() == ".tsv" else None
                preview = pd.read_csv(path, sep=sep, engine="python", nrows=20)
                st.dataframe(preview)
            except UnicodeDecodeError:
                st.warning(
                    f"{path} is not plain text -- likely encrypted at rest (e.g. GPG) rather than "
                    "corrupt. MRSIPrep falls back to a directory scan to discover recordings when "
                    "this file can't be read, so processing still works; it just can't be "
                    "previewed here."
                )
            except Exception as exc:  # noqa: BLE001 -- best-effort preview, any parse error is shown as-is
                st.error(f"Could not preview {path}: {exc}")
    return path_str if (custom and path_str) else None


# mrsiprep's own recommended --chimera-scheme default: not the same as each
# position's upstream-chimera "default" letter (several positions, e.g.
# Thalamus/Amygdala/Hippocampus/Hypothalamus/Brainstem, use a more specific
# FreeSurfer sub-parcellation instead of upstream's own plain Aseg default).
RECOMMENDED_CHIMERA_CODE = "LFMIHIFIFF"


def _render_chimera_scheme_picker(
    scheme_action: argparse.Action, scale_action: argparse.Action, grow_action: argparse.Action, key_prefix: str = ""
):
    """One dropdown per supra-region (instead of a raw 10-letter code), composing
    --chimera-scheme live; the cortex dropdown's scale/seg choices (e.g. Lausanne's
    1-5 vs. Schaefer's 100-1000) replace --chimera-scale's own generic widget,
    since valid values depend entirely on which cortical atlas is picked.

    `key_prefix` isolates this widget's session-state keys from another
    caller rendering the same picker elsewhere (see _render_participants_widget)."""
    recommended = {region: letter for region, letter in zip(SUPRA_REGIONS, RECOMMENDED_CHIMERA_CODE)}
    by_region: dict[str, str] = {}
    cols = st.columns(5)
    for i, region in enumerate(SUPRA_REGIONS):
        letters = valid_letters(region)
        options = sorted(letters)
        label = SUPRA_REGION_LABELS.get(region, region)
        if len(options) == 1:
            by_region[region] = options[0]
            cols[i % 5].caption(f"**{label}**: {letters[options[0]]['name']} ({options[0]}) (only option)")
            continue
        default_letter = recommended.get(region, options[0])
        fmt = lambda letter, letters=letters, default_letter=default_letter: (
            f"{letters[letter]['name']} ({letter})" + (" (default)" if letter == default_letter else "")
        )
        selected = cols[i % 5].selectbox(
            label, options, index=options.index(default_letter), format_func=fmt, key=f"{key_prefix}chimera_{region}"
        )
        by_region[region] = selected

    code = build_scheme_code(by_region)
    st.code(code, language=None)

    scale_value, grow_value = None, None
    cortical_letter = by_region["Cortical"]
    cortical_info = valid_letters("Cortical")[cortical_letter]
    scales = cortical_info["scales"]
    if scales:
        label = f"--chimera-scale ({cortical_info['name']} resolution)"
        default = "3" if "3" in scales else scales[0]
        # Key includes the cortical letter: scale's valid options depend
        # entirely on which cortical atlas is chosen (Lausanne's 1-5 vs.
        # Schaefer's 100-1000, etc), so switching atlas must start this
        # widget fresh rather than try to reconcile old state against a
        # new, unrelated options list.
        scale_value = st.selectbox(
            label, scales, index=scales.index(default) if default in scales else 0,
            key=f"{key_prefix}chimera_scale_adaptive_{cortical_letter}",
        )
    else:
        st.caption(f"{cortical_info['name']} has no --chimera-scale resolution variants; --chimera-scale is ignored for this cortical choice.")

    grow_value = str(st.number_input(
        _dest_label(grow_action),
        value=int(grow_action.default),
        min_value=0,
        help=(grow_action.help or "").strip(),
        key=f"{key_prefix}chimera_grow_adaptive",
    ))

    return code, scale_value, grow_value


def _render_atlas_widget(action: argparse.Action, key_prefix: str = "field_", label: str | None = None):
    """Dropdown of every bundled atlas actually found under mrsiprep/data/atlas/
    (instead of a free-text field defaulting to one hardcoded name), plus the
    parameterized synthetic choices --atlas also accepts (custom/schaefer<N>/
    mist197/cubic<N>mm).

    `key_prefix` isolates this widget's session-state keys from another
    caller rendering the same flag elsewhere (see _render_participants_widget).
    `label` optionally overrides the displayed label (defaults to
    `_dest_label(action)`, preserving every existing call site's behavior)."""
    from mrsiprep.parcellation.atlas_registry import available_bundled_atlases

    label = label if label is not None else _dest_label(action)
    bundled = available_bundled_atlases()
    synthetic = ["custom", "schaefer100", "schaefer400", "schaefer1000", "mist197", "cubic10mm"]
    options = bundled + synthetic + ["(custom value...)"]
    default = action.default if action.default in options else options[0]
    key = f"{key_prefix}{action.dest}"
    selected = st.selectbox(
        label, options, index=options.index(default),
        help=(action.help or "").strip(), key=key,
    )
    if selected == "(custom value...)":
        return st.text_input(
            f"{label} (custom value)",
            help="e.g. 'schaefer200', 'cubic15mm', or another bundled/registered atlas name not listed above.",
            key=f"{key}_custom",
        ) or None
    return selected


def _widget_for(
    action: argparse.Action,
    key_prefix: str = "field_",
    label_override: str | None = None,
    help_override: str | None = None,
):
    """`key_prefix` isolates this widget's session-state key from another
    caller rendering the same flag elsewhere -- the Custom Pipeline tab
    passes "custom_field_" so its per-step widgets never collide with the
    Standardized tab's widgets for the same flag.

    `label_override`/`help_override` let a caller (the wizard) substitute a
    human-readable label/help string while keeping every other dispatch rule
    (choices, defaults, widget kind) identical -- both default to today's
    `_dest_label(action)`/`action.help` when omitted, so every pre-existing
    call site (which never passes them) behaves exactly as before.

    When `key_prefix` is the wizard's own WIZARD_KEY_PREFIX, this also
    participates in the shadow-state mechanism (see WIZARD_SHADOW_PREFIX's
    module-level comment): Streamlit deletes a widget-backed session_state
    entry the moment that widget isn't instantiated on a rerun, which would
    otherwise reset every field to its CLI default each time the wizard
    revisits a step after leaving it. Seeding `value=`/`index=`/`default=`
    from the shadow key (falling back to `action.default` only the first
    time a field is ever seen) and writing the widget's result back to the
    shadow key after makes a field's value durable across step changes --
    exactly like a plain (non-widget) session_state entry would be."""
    label = label_override if label_override is not None else _dest_label(action)
    help_text = help_override if help_override is not None else (action.help or "").strip()
    key = f"{key_prefix}{action.dest}"
    is_wizard = key_prefix == WIZARD_KEY_PREFIX
    shadow_default = _wizard_shadow_get(action.dest) if is_wizard else None

    def _finish(result):
        if is_wizard:
            _wizard_shadow_set(action.dest, result)
        return result

    if _is_flag(action):
        value = shadow_default if (is_wizard and shadow_default is not None) else bool(action.default)
        return _finish(st.checkbox(label, value=value, help=help_text, key=key))

    if action.choices:
        choices = list(action.choices)
        flag_name = _dest_label(action)
        if flag_name == "--registration-backend":
            # The parser also accepts 'flirt-fnirt'/'flirt_fnirt'/'flirt/fnirt' as
            # deprecated spellings of 'fsl' (FNIRT is FSL's own deformable stage,
            # not a separate backend) -- the form only ever needs to offer 'fsl'.
            choices = ["ants", "fsl"]
        if flag_name == "--normalization":
            # 'simple' and 'ants-syn' are behaviorally identical (both just
            # recompute using --registration-backend); 'ants-syn' only exists
            # for backward compatibility with older configs -- don't offer it
            # as if it were a meaningfully different third choice.
            choices = ["simple", "existing"]
        if action.nargs in ("+", "*"):
            default = action.default if isinstance(action.default, list) else []
            if is_wizard and shadow_default is not None:
                default = [v for v in shadow_default if v in choices]
            return _finish(st.multiselect(label, choices, default=default, help=help_text, key=key))
        options = ["(unset)"] + choices if not action.required else choices
        default = action.default if action.default in options else options[0]
        if is_wizard and shadow_default in options:
            default = shadow_default
        index = options.index(default)
        selected = st.selectbox(label, options, index=index, help=help_text, key=key)
        return _finish(None if selected == "(unset)" else selected)

    if action.type is int:
        default = action.default if isinstance(action.default, int) else 0
        if is_wizard and isinstance(shadow_default, int):
            default = shadow_default
        return _finish(st.number_input(label, value=default, step=1, help=help_text, key=key, format="%d"))

    if action.type is float:
        default = action.default if isinstance(action.default, float) else 0.0
        if is_wizard and isinstance(shadow_default, (int, float)):
            default = shadow_default
        return _finish(st.number_input(label, value=default, help=help_text, key=key))

    if action.nargs in ("+", "*"):
        if is_wizard and isinstance(shadow_default, list):
            default = ",".join(shadow_default)
        else:
            default = ",".join(action.default) if isinstance(action.default, list) else ""
        raw = st.text_input(label, value=default, help=f"{help_text} (comma-separated)", key=key)
        return _finish([v.strip() for v in raw.split(",") if v.strip()] or None)

    cli_default = "" if action.default in (None, argparse.SUPPRESS) else str(action.default)
    default = shadow_default if (is_wizard and isinstance(shadow_default, str)) else cli_default
    raw = st.text_input(label, value=default, help=help_text, key=key)
    return _finish(raw or None)


# Flags that take a single comma-separated token (type=_parse_comma_list in
# the parser), not argparse nargs="+" -- a space-separated argv list would be
# parsed by argparse as one flag value plus stray positionals. Values for
# these flags are still stored as Python lists in `values` (Review and the
# status checks read them that way), so _build_argv_groups must join them
# with commas into a single token itself, rather than spreading them like
# every other list-valued flag.
COMMA_JOINED_FLAGS = {"--metabolites", "--steps"}


# Registration-backend-specific flags: only shown once a backend is picked,
# and only the flags relevant to that specific backend (keyed by the dest
# this app renders its own --registration-backend selectbox under).
FSL_ONLY_FLAGS = {
    "--fsl-mrsi-to-t1-dof",
    "--fsl-mrsi-to-t1-init",
    "--fsl-t1-to-template-dof",
    "--fsl-cost",
    "--fsl-deformable",
    "--fsl-fnirt-warpres",
    "--fsl-fnirt-lambda",
}
ANTS_ONLY_FLAGS = {
    "--ants-mrsi-to-t1-transform",
    "--ants-t1-to-template-transform",
}
BACKEND_SPECIFIC_FLAGS = FSL_ONLY_FLAGS | ANTS_ONLY_FLAGS


def _build_argv_groups(positional_values: dict, optionals: list[argparse.Action], values: dict) -> list[list[str]]:
    """Raw (unquoted) token groups: one group per positional or per flag (with
    its value(s)). Shared by the displayed `mrsiprep-docker` command and by
    the native argv used to run preflight validation in-process -- the two
    only differ in how the bids_dir/output_dir positionals and executable
    name are filled in, not in which optional flags are present."""
    groups: list[list[str]] = []

    for action in optionals:
        flag = _dest_label(action)
        if flag not in values:
            continue
        value = values[flag]
        if value in (None, "", False, []):
            continue
        if value is True:
            if action.default is True:
                continue
            groups.append([flag])
        elif isinstance(value, list):
            if isinstance(action.default, list) and sorted(value) == sorted(action.default):
                continue
            if flag in COMMA_JOINED_FLAGS:
                groups.append([flag, ",".join(str(v) for v in value)])
            else:
                groups.append([flag, *(str(v) for v in value)])
        else:
            if value == action.default:
                continue
            groups.append([flag, str(value)])

    return groups


def _build_command(positional_values: dict, optionals: list[argparse.Action], values: dict) -> str:
    # mrsiprep itself only runs inside the Docker image -- mrsiprep-docker is
    # the host-side wrapper that builds and runs the equivalent `docker run`
    # for you, and is what every doc example (and pip install mrsiprep-docker)
    # expects the user to actually type.
    #
    # Built as one "group" per line (a flag plus its value(s), or the leading
    # positionals) rather than a flat token list, so the command can be
    # rendered with a trailing `\` per line -- these commands grow long with
    # every optional flag the user sets.
    groups: list[list[str]] = [
        ["mrsiprep-docker"],
        [shlex.quote(str(positional_values.get("bids_dir") or "<bids_dir>"))],
        [shlex.quote(str(positional_values.get("output_dir") or "<output_dir>"))],
        ["participant"],
    ]
    for group in _build_argv_groups(positional_values, optionals, values):
        groups.append([shlex.quote(token) for token in group])

    return " \\\n    ".join(" ".join(group) for group in groups)


def _mrsiprep_docker_version() -> str:
    """The installed `mrsiprep-docker` wrapper's version, or a hint to install
    it -- it's a separate pip package from `mrsiprep` itself (see
    docs/installation.md), so it may be missing even when this app runs."""
    try:
        from mrsiprep_docker import __version__

        return __version__
    except ImportError:
        return "not installed (pip install mrsiprep-docker)"


def _flag_action_lookup(optionals: list[argparse.Action]) -> dict[str, argparse.Action]:
    """One-time `--flag` -> argparse.Action index, built once in main() and
    shared by both tabs so neither re-scans `optionals` repeatedly."""
    return {_dest_label(a): a for a in optionals}


# ---------------------------------------------------------------------------
# Guided wizard: Analysis -> Data -> Processing -> Review
# ---------------------------------------------------------------------------
#
# One shared state prefix for every flag's own widget key, used by every
# wizard step (not per-step prefixes) -- a field's value must survive
# regardless of which step is currently being rendered, since each step
# function is only called on the rerun where it's the active step.
WIZARD_KEY_PREFIX = "wizard_field_"

# IMPORTANT: Streamlit deletes a widget-backed session_state entry from
# st.session_state the moment that widget is no longer instantiated on a
# rerun (confirmed directly against this Streamlit version with a minimal
# repro -- not something any code in this file does). Since each wizard
# step function only calls the widgets for *its own* fields, a value typed
# on Data would otherwise vanish from st.session_state the instant the user
# moves to Processing or Review, exactly the "lost on step change" bug the
# wizard must not have. The fix: every wizard widget's value is mirrored
# into a second, non-widget-backed "shadow" key under this prefix
# immediately after the widget call (_wizard_shadow_set), and every
# consumer that is not the widget's own render call (Review, the sidebar
# summary, _collect_wizard_values, and every widget's own pre-seeding of
# its displayed value) reads the shadow key instead of the live widget key,
# which may not exist on steps where that widget isn't rendered.
WIZARD_SHADOW_PREFIX = "wizard_value_"

WIZARD_STEP_TITLES = ["Analysis", "Data", "Processing", "Review"]


def _wizard_shadow_set(dest: str, value) -> None:
    st.session_state[f"{WIZARD_SHADOW_PREFIX}{dest}"] = value


def _wizard_shadow_get(dest: str, default=None):
    return st.session_state.get(f"{WIZARD_SHADOW_PREFIX}{dest}", default)


def _wizard_label_help(dest: str, fallback_label: str, fallback_help: str) -> tuple[str, str]:
    """Looks up a human label/help pair from WIZARD_FIELD_LABELS, falling
    back to the given defaults (normally `_dest_label(action)`/`action.help`)
    when `dest` isn't in that table."""
    if dest in WIZARD_FIELD_LABELS:
        return WIZARD_FIELD_LABELS[dest]
    return fallback_label, fallback_help


def _render_participant_selection(
    participant_label_action: argparse.Action,
    session_label_action: argparse.Action,
    participants_action: argparse.Action,
    bids_dir: str,
) -> None:
    """Explicit 3-way choice replacing the old ambiguous combination of
    --participant-label/--session-label/--participants: "All participants"
    (emits nothing -- the literal collect_recordings() directory-scan
    fallback, mrsiprep/workflows/participant.py's own default path when
    neither --participants nor --participant-label is given), "Select
    participants" (reveals --participant-label/--session-label text inputs),
    or "Use a participant file" (reveals the existing
    _render_participants_widget, relabeled). Writes directly into
    st.session_state under the wizard's own shared key prefix; does not
    return a value -- _collect_wizard_values reads the same keys back out,
    same convention as every other wizard field."""
    mode_key = f"{WIZARD_KEY_PREFIX}participant_mode"
    # participant_mode is read by Review/the sidebar/_collect_wizard_values
    # even on reruns where this radio isn't rendered at all -- shadow it
    # like every other field (see WIZARD_SHADOW_PREFIX's module comment),
    # since a plain `key=` alone would be deleted by Streamlit the instant
    # the user leaves the Data step.
    if mode_key not in st.session_state:
        st.session_state[mode_key] = _wizard_shadow_get("participant_mode", "All participants")
    mode = st.radio(
        "Which participants should be processed?",
        ["All participants", "Select participants", "Use a participant file"],
        key=mode_key,
        help="All participants scans the dataset folder and processes everyone found there. "
        "Select participants lets you type specific subject/session labels -- each one can optionally "
        "name its own session (e.g. '5301_ses-V6') to mix different subject/session pairs in one list. "
        "Use a participant file points at a TSV/CSV listing subject/session pairs.",
    )
    _wizard_shadow_set("participant_mode", mode)
    if mode == "Select participants":
        label, help_text = _wizard_label_help_args("participant_label", participant_label_action)
        _widget_for(
            participant_label_action, key_prefix=WIZARD_KEY_PREFIX,
            label_override=label, help_override=help_text,
        )
        st.caption(
            "Need a different session per subject? Name it right in the entry, e.g. "
            "`5301_ses-V6, 5323_ses-V4` -- then skip Sessions below for those."
        )
        with st.expander("Also apply the same session(s) to any plain subject entries above"):
            label, help_text = _wizard_label_help_args("session_label", session_label_action)
            _widget_for(
                session_label_action, key_prefix=WIZARD_KEY_PREFIX,
                label_override=label, help_override=help_text,
            )
    elif mode == "Use a participant file":
        label, _help = _wizard_label_help("participants", _dest_label(participants_action), "")
        participants_key = f"{WIZARD_KEY_PREFIX}participants"
        if participants_key not in st.session_state:
            shadow_participants = _wizard_shadow_get("participants")
            if shadow_participants:
                st.session_state[f"{participants_key}_custom"] = True
                st.session_state[participants_key] = shadow_participants
        participants_value = _render_participants_widget(
            participants_action, bids_dir, key_prefix=WIZARD_KEY_PREFIX, label=label
        )
        _wizard_shadow_set("participants", participants_value)
    else:
        st.caption("Every subject/session found under the dataset folder will be processed.")


def _wizard_label_help_args(dest: str, action: argparse.Action) -> tuple[str, str]:
    """Convenience: resolves (label_override, help_override) positional-ish
    values for a `_widget_for(..., label_override=..., help_override=...)`
    call from WIZARD_FIELD_LABELS, falling back to the action's own label/
    help text (never None) so the two kwargs are always real strings."""
    label, help_text = _wizard_label_help(dest, _dest_label(action), (action.help or "").strip())
    return label, help_text


_MET_TOKEN_RE = re.compile(r"_met-([^_.]+)")


def _scan_metabolites_from_filenames(mrsi_input_dir: str | Path) -> list[str]:
    """Scan `<mrsi_input_dir>/derivatives/mrsi-*/**/*.nii*` filenames for
    every `met-<NAME>` BIDS entity (see BIDSLayout._mrsi_filename's own
    "met-{met}" token in mrsiprep/io/bids.py) and return the distinct names
    found, sorted. Used by the "Scan for metabolites" button so a user
    pointed at real data doesn't have to already know which metabolite
    spellings their own files use."""
    root = Path(mrsi_input_dir)
    if not root.is_dir():
        return []
    found: set[str] = set()
    for pattern in ("derivatives/mrsi-*/**/*.nii.gz", "derivatives/mrsi-*/**/*.nii"):
        for path in root.glob(pattern):
            match = _MET_TOKEN_RE.search(path.name)
            if match:
                found.add(match.group(1))
    return sorted(found)


def _render_metabolites_widget(
    metabolites_action: argparse.Action, nucleus: str = DEFAULT_NUCLEUS, mrsi_input_dir: str | None = None
) -> list[str]:
    """Multiselect "chip" widget (Streamlit's native multi-select) populated
    from the real nucleus-aware alias table (mrsiprep.config.nuclei.
    metabolite_aliases), replacing the old bare comma-separated text input.
    Streamlit 1.67's st.multiselect supports `accept_new_options=True`,
    letting the user type a metabolite name not in the curated list (e.g. a
    custom/unlisted metabolite) directly into the same widget -- no separate
    text-input fallback needed.

    `nucleus` selects which curated alias table to offer as options; callers
    pass whatever --nucleus value is currently chosen (falling back to
    DEFAULT_NUCLEUS, "1H", when none is set yet -- matching the CLI's own
    documented fallback order)."""
    try:
        aliases = metabolite_aliases(nucleus)
    except NucleusError:
        aliases = metabolite_aliases(DEFAULT_NUCLEUS)
    options = set(aliases)
    key = f"{WIZARD_KEY_PREFIX}metabolites"
    label, help_text = _wizard_label_help(
        "metabolites", _dest_label(metabolites_action), (metabolites_action.help or "").strip()
    )

    scanned = _wizard_shadow_get("metabolites_scanned", [])
    col_label, col_button = st.columns([3, 1])
    with col_button:
        st.write("")  # vertical-align the button with the label row above.
        if st.button("Scan for metabolites", key="wizard_scan_metabolites", disabled=not mrsi_input_dir):
            found = _scan_metabolites_from_filenames(mrsi_input_dir) if mrsi_input_dir else []
            scanned = found
            _wizard_shadow_set("metabolites_scanned", scanned)
            if found:
                merged = sorted(set(st.session_state.get(key, [])) | set(found))
                st.session_state[key] = merged
                _wizard_shadow_set("metabolites", merged)
                st.toast(f"Found {len(found)} metabolite(s): {', '.join(found)}")
            else:
                st.toast("No met-<name> filenames found under that MRSI input directory.", icon="⚠️")
    options |= set(scanned)
    options = sorted(options)
    # Streamlit deletes this widget's session_state entry once this step
    # stops being rendered (see WIZARD_SHADOW_PREFIX's module comment) --
    # reseed from the shadow copy (which custom entries typed via
    # accept_new_options may not be in `options`, so no further filtering)
    # whenever the live key doesn't exist yet this run, rather than
    # resetting to empty.
    if key not in st.session_state:
        st.session_state[key] = _wizard_shadow_get("metabolites", [])
    with col_label:
        selected = st.multiselect(
            f"{label} (--metabolites)",
            options,
            help=f"{help_text} Type a name and press Enter to add one not in this list, or use "
            "\"Scan for metabolites\" to discover them from the met-<name> BIDS entity in your "
            "raw MRSI filenames.",
            key=key,
            accept_new_options=True,
            placeholder="Choose one or more metabolites...",
        )
    _wizard_shadow_set("metabolites", list(selected))
    return list(selected)


def _render_ref_met_widget(ref_met_action: argparse.Action, metabolites: list[str]) -> str | None:
    """Dropdown for --ref-met populated from exactly the metabolites chosen
    in the Data step, instead of an unpopulated free-text box (today's form
    offers a plain text_input with no hint of which spellings are valid).
    Shows a warning caption instead of an empty dropdown when no metabolites
    have been chosen yet -- there is nothing valid to offer, and a dropdown
    with zero real options would look broken rather than merely premature."""
    label, help_text = _wizard_label_help(
        "ref_met", _dest_label(ref_met_action), (ref_met_action.help or "").strip()
    )
    key = f"{WIZARD_KEY_PREFIX}ref_met"
    if not metabolites:
        st.warning(
            f"Choose at least one metabolite in the Data step before picking a {label.lower()} "
            f"(--ref-met)."
        )
        _wizard_shadow_set("ref_met", None)
        return None
    # Reseed from the shadow copy when this widget's own key was deleted by
    # Streamlit on a rerun that didn't render it (see WIZARD_SHADOW_PREFIX's
    # module comment) -- without this, returning to Processing after
    # visiting another step would silently reset --ref-met to whichever
    # metabolite happens to be first alphabetically.
    if key not in st.session_state:
        shadow_ref_met = _wizard_shadow_get("ref_met")
        if shadow_ref_met in metabolites:
            st.session_state[key] = shadow_ref_met
    current = st.session_state.get(key)
    index = metabolites.index(current) if current in metabolites else 0
    selected = st.selectbox(f"{label} (--ref-met)", metabolites, index=index, help=help_text, key=key)
    _wizard_shadow_set("ref_met", selected)
    return selected


# --- "Standard location / Specify a path" radio, replacing the old "Custom
# path" checkbox for --mrsi-input-dir/--mrsinmrs-file (plan §3, Step 2) ----
#
# Session-state keys used, for a given `field` ("mrsi_input_dir" or
# "mrsinmrs_file"):
#   wizard_field_{field}_mode  -- "Standard location" / "Specify a path"
#   wizard_field_{field}       -- the text_input's own value (only editable
#                                  in "Specify a path" mode; force-synced to
#                                  `default_value` every rerun while in
#                                  "Standard location" mode, same idiom as
#                                  the pre-wizard required-args section).


def _render_path_mode_field(field: str, cli_flag: str, default_value: str, help_text: str) -> tuple[str, bool]:
    """Returns (effective_path, is_custom) -- `is_custom` tells the caller
    whether to actually emit `cli_flag` (the "Standard location" mode emits
    nothing, relying on mrsiprep's own default-path convention, exactly like
    today's unchecked "Custom path" checkbox)."""
    mode_key = f"{WIZARD_KEY_PREFIX}{field}_mode"
    # Both this radio's own key and the text_input's key below are read
    # elsewhere (Review/the sidebar/_collect_wizard_values) on reruns where
    # this function isn't called at all -- Streamlit deletes a widget's
    # session_state entry when its widget isn't instantiated (see
    # WIZARD_SHADOW_PREFIX's module comment), so both are shadow-backed.
    if mode_key not in st.session_state:
        st.session_state[mode_key] = _wizard_shadow_get(f"{field}_mode", "Standard location")
    mode = st.radio(
        f"{cli_flag} location", ["Standard location", "Specify a path"], key=mode_key, horizontal=True,
        help=help_text,
    )
    _wizard_shadow_set(f"{field}_mode", mode)
    is_custom = mode == "Specify a path"
    text_key = f"{WIZARD_KEY_PREFIX}{field}"
    if not is_custom:
        # Disabled (auto-filled) mode: force-sync to the computed default
        # every rerun, mirroring the pre-wizard form's identical mrsi_input_dir/
        # --mrsinmrs-file handling -- once "Specify a path" is
        # chosen, the widget's own session-state takes over and must NOT be
        # overwritten here, or a typed path would be reverted on every rerun.
        st.session_state[text_key] = default_value
    elif text_key not in st.session_state:
        st.session_state[text_key] = _wizard_shadow_get(field, default_value)
    path_value = st.text_input(
        cli_flag, key=text_key, disabled=not is_custom,
        help="Leave on 'Standard location' to use mrsiprep's own default path convention.",
    )
    if is_custom:
        _wizard_shadow_set(field, path_value)
    effective = path_value if (is_custom and path_value) else default_value
    return effective, is_custom


def _compute_field_statuses(values: dict, positional_values: dict) -> dict[str, tuple[str, str]]:
    """Tier 1 validation (plan §4): instant, cheap, recomputed every rerun --
    no file contents are read, only Path.exists()/simple truthiness checks
    (matching what _render_check already did unconditionally, pre-wizard).
    Returns {dest: (level, message)}, level one of "ok"/"warn"/"block".

    Blocking checks (gate the Review step's "Ready to copy" state and the
    per-step Next button): bids_dir/output_dir empty or missing on disk,
    --metabolites empty, --ref-met empty once metabolites is non-empty,
    chimera mode without --fs-license, atlas mode missing --custom-atlas/
    --custom-atlas-lut. Everything else present here warns without
    blocking -- a dest with no entry at all is implicitly "ok" (nothing to
    say about it)."""
    statuses: dict[str, tuple[str, str]] = {}

    bids_dir = positional_values.get("bids_dir") or ""
    if not bids_dir:
        statuses["bids_dir"] = ("block", "Required: choose your BIDS dataset folder.")
    elif not Path(bids_dir).exists():
        statuses["bids_dir"] = ("block", f"Folder not found: {bids_dir}")
    else:
        statuses["bids_dir"] = ("ok", "Found.")

    output_dir = positional_values.get("output_dir") or ""
    if not output_dir:
        statuses["output_dir"] = ("block", "Required: choose where derivatives should be written.")
    else:
        statuses["output_dir"] = ("ok", f"Will create `{output_dir.rstrip('/')}/mrsiprep`.")

    metabolites = values.get("--metabolites") or []
    if not metabolites:
        statuses["metabolites"] = ("block", "Required: choose at least one metabolite.")
    else:
        statuses["metabolites"] = ("ok", f"{len(metabolites)} metabolite(s) selected.")

    ref_met = values.get("--ref-met")
    if metabolites and not ref_met:
        statuses["ref_met"] = ("block", "Required once metabolites are chosen: pick a reference metabolite.")
    elif ref_met:
        statuses["ref_met"] = ("ok", f"Using {ref_met}.")

    parcellation_mode = values.get("--parcellation-mode")
    if parcellation_mode == "chimera" and not values.get("--fs-license"):
        statuses["fs_license"] = ("block", "Required for the 'chimera' parcellation method: a FreeSurfer license.txt.")
    elif parcellation_mode == "atlas" and values.get("--atlas") == "custom" and (
        not values.get("--custom-atlas") or not values.get("--custom-atlas-lut")
    ):
        statuses["custom_atlas"] = ("block", "Required for a custom atlas: both --custom-atlas and --custom-atlas-lut.")

    mrsinmrs_file = values.get("--mrsinmrs-file")
    if mrsinmrs_file and not Path(mrsinmrs_file).exists():
        statuses["mrsinmrs_file"] = ("warn", f"File not found yet: {mrsinmrs_file}")

    mrsi_input_dir = values.get("--mrsi-input-dir")
    if mrsi_input_dir and not Path(mrsi_input_dir).exists():
        statuses["mrsi_input_dir"] = ("warn", f"Folder not found yet: {mrsi_input_dir}")

    return statuses


def _wizard_blocking_messages(statuses: dict[str, tuple[str, str]]) -> list[str]:
    return [message for level, message in statuses.values() if level == "block"]


def _collect_wizard_values(
    optionals: list[argparse.Action], positionals: list[argparse.Action]
) -> tuple[dict, dict]:
    """Reads every wizard field back out of its WIZARD_SHADOW_PREFIX shadow
    copy in st.session_state (written by the four step-render functions
    below and by _widget_for itself -- see WIZARD_SHADOW_PREFIX's module
    comment for why the *shadow* key, not the live widget key, is the only
    one guaranteed to still exist once a step is no longer being rendered)
    into the same `(positional_values, values)` shape _build_command/
    _compute_preflight already expect -- Review uses this instead of
    re-rendering live widgets, per plan §2."""
    bids_dir = _wizard_shadow_get("bids_dir", "") or ""
    output_dir = _wizard_shadow_get("output_dir", "") or ""
    analysis_level_action = next(a for a in positionals if a.dest == "analysis_level")
    assert len(analysis_level_action.choices) == 1, (
        f"analysis_level now has more than one choice ({list(analysis_level_action.choices)}) -- "
        "the wizard's Data step silently assumed exactly one and never rendered a widget for it; "
        "give the user a real choice there instead."
    )
    positional_values = {
        "bids_dir": bids_dir,
        "output_dir": output_dir,
        "analysis_level": analysis_level_action.choices[0],
    }

    values: dict[str, object] = {}

    participant_mode = _wizard_shadow_get("participant_mode")
    if participant_mode == "Select participants":
        participant_label = _wizard_shadow_get("participant_label") or []
        session_label = _wizard_shadow_get("session_label") or []
        if participant_label:
            values["--participant-label"] = participant_label
        if session_label:
            values["--session-label"] = session_label
    elif participant_mode == "Use a participant file":
        participants = _wizard_shadow_get("participants")
        if participants:
            values["--participants"] = participants

    t1_pattern = _wizard_shadow_get("t1_pattern")
    if t1_pattern:
        values["--t1"] = t1_pattern

    mrsi_input_dir_mode = _wizard_shadow_get("mrsi_input_dir_mode")
    if mrsi_input_dir_mode == "Specify a path":
        mrsi_input_dir = _wizard_shadow_get("mrsi_input_dir")
        if mrsi_input_dir:
            values["--mrsi-input-dir"] = mrsi_input_dir

    mrsinmrs_file_mode = _wizard_shadow_get("mrsinmrs_file_mode")
    if mrsinmrs_file_mode == "Specify a path":
        mrsinmrs_file = _wizard_shadow_get("mrsinmrs_file")
        if mrsinmrs_file:
            values["--mrsinmrs-file"] = mrsinmrs_file

    metabolites = _wizard_shadow_get("metabolites") or []
    if metabolites:
        values["--metabolites"] = list(metabolites)

    ref_met = _wizard_shadow_get("ref_met")
    if ref_met:
        values["--ref-met"] = ref_met

    # Every other optional flag: _widget_for mirrors its result into
    # wizard_value_{action.dest} (the shadow key) whenever it's called with
    # key_prefix=WIZARD_KEY_PREFIX, regardless of which step rendered it --
    # a flag not special-cased above (participants/metabolites/ref-met/t1/
    # mrsi-input-dir/mrsinmrs-file, all handled above because they have
    # bespoke wizard widgets rather than a plain _widget_for call) is read
    # back the same generic way here.
    _already_handled = {
        "participant_label", "session_label", "participants", "t1_pattern",
        "mrsi_input_dir", "mrsinmrs_file", "metabolites", "ref_met",
    }
    _unset = object()
    for action in optionals:
        if action.dest in _already_handled:
            continue
        flag = _dest_label(action)
        value = _wizard_shadow_get(action.dest, _unset)
        if value is _unset:
            continue
        if isinstance(value, str):
            value = value or None
        if value is False and action.default is True:
            # False is a meaningful, non-default value for a store_true flag
            # whose default is True (e.g. --fsl-deformable's "on by default"
            # checkbox being unchecked) -- always keep it, even though it
            # would otherwise look like one of the "empty" sentinels below.
            values[flag] = value
            continue
        if value in (None, "", [], False):
            continue
        values[flag] = value

    return positional_values, values


def _render_wizard_analysis_step() -> None:
    """Step 1: two outcome cards, replacing the old Standardized/Custom top-
    level tab choice as the first thing a user sees. Both outcomes emit
    the exact same --steps value -- none at all, i.e. the full 20-step
    pipeline always runs -- confirmed against STEP_DEPENDENCIES/
    validate_step_order (see this file's module docstring context and the
    plan). "wizard_outcome" only governs whether Processing's parcellation/
    connectivity expander opens collapsed-light or expanded-foregrounded by
    default; it is never read by _build_command."""
    st.header("What would you like to do?")
    st.caption(
        "Both options run the same full MRSIPrep pipeline end-to-end (loading, spike filtering, "
        "T1 correction, registration, tissue correction, and the final QC report) -- the choice "
        "below only decides which processing options are highlighted on the next screens."
    )

    outcome_key = "wizard_outcome"
    st.session_state.setdefault(outcome_key, None)

    col1, col2 = st.columns(2)
    with col1:
        with st.container(border=True):
            if WIZARD_NORMALIZE_THUMBNAIL.exists():
                _render_wizard_thumbnail(WIZARD_NORMALIZE_THUMBNAIL)
            st.subheader("Normalize metabolite maps")
            st.write(
                "Prepare and coregister metabolite maps into standard space, with the full quality "
                "control report. A lightweight parcellation runs automatically for QC."
            )
            if st.button("Choose this", key="wizard_outcome_normalize", type=(
                "primary" if st.session_state[outcome_key] == "normalize" else "secondary"
            )):
                st.session_state[outcome_key] = "normalize"
                st.session_state["wizard_step"] = 1
                st.rerun()
    with col2:
        with st.container(border=True):
            if WIZARD_PARCELLATION_THUMBNAIL.exists():
                _render_wizard_thumbnail(WIZARD_PARCELLATION_THUMBNAIL)
            st.subheader("Parcellation and connectivity")
            st.write(
                "Same underlying pipeline, plus a guided choice of parcellation method (including "
                "the heavier FreeSurfer-based Chimera parcellation) and metabolic connectivity "
                "output, foregrounded as an active decision in Processing."
            )
            if st.button("Choose this", key="wizard_outcome_parcellation", type=(
                "primary" if st.session_state[outcome_key] == "parcellation" else "secondary"
            )):
                st.session_state[outcome_key] = "parcellation"
                st.session_state["wizard_step"] = 1
                st.rerun()

    if st.session_state[outcome_key]:
        st.success(
            f"Selected: **{'Normalize metabolite maps' if st.session_state[outcome_key] == 'normalize' else 'Parcellation and connectivity'}**. "
            "Click Next below, or choose the other card to switch."
        )

    st.divider()
    st.caption(
        "Already know exactly which steps you want? "
        "Use the checkbox below to build a fully custom pipeline instead of the guided wizard."
    )
    # This checkbox's own widget is only ever rendered here, on the
    # Analysis step -- once checked, _render_wizard_page renders the Custom
    # Pipeline tab instead of any wizard step, so this widget (and
    # therefore its session_state entry, per WIZARD_SHADOW_PREFIX's module
    # comment) stops existing on the very next rerun. "wizard_advanced_steps"
    # itself (read by _render_wizard_page, not this widget's own key) is
    # therefore a plain state flag, never a widget key -- set directly by
    # this checkbox's on_change, not via `key=`.
    advanced_checked = st.checkbox(
        "Build a fully custom pipeline (advanced)",
        value=st.session_state.get("wizard_advanced_steps", False),
        key="wizard_advanced_steps_checkbox",
        help="Switches to the existing Custom Pipeline tool, where you compose your own ordered "
        "subset of pipeline steps directly (backs the --steps flag). This is the only place this "
        "tool ever emits --steps.",
    )
    if advanced_checked != st.session_state.get("wizard_advanced_steps", False):
        # _render_wizard_page's own advanced-mode check runs *before* this
        # checkbox is ever instantiated (reaching this checkbox at all means
        # we're not yet in advanced mode) -- so the new value must be
        # committed and an explicit rerun fired now, or the switch to the
        # Custom Pipeline tab would only take effect on a *second*
        # interaction (the next widget change), one rerun late. Mirrors
        # this file's existing _add_custom_step/_move_custom_step idiom.
        st.session_state["wizard_advanced_steps"] = advanced_checked
        st.rerun()


def _render_wizard_data_step(optionals: list[argparse.Action], positionals: list[argparse.Action]) -> None:
    """Step 2: bids_dir/output_dir/mrsi_input_dir/--t1/--mrsinmrs-file,
    participant selection, --metabolites. Drops analysis_level from being
    rendered at all (its choices is always exactly ["participant"] today --
    _collect_wizard_values's own assertion catches a future CLI change that
    gives it more than one choice). --ref-met and --parcellation-mode live
    in Processing instead (the reference metabolite depends on which
    metabolites are picked here; parcellation mode is a processing
    decision, not a data-selection one)."""
    action_lookup = {_dest_label(a): a for a in optionals}
    bids_dir_help = POSITIONAL_HELP.get("bids_dir", "")
    output_dir_help = POSITIONAL_HELP.get("output_dir", "")
    bids_label, bids_help = _wizard_label_help("bids_dir", "bids_dir", bids_dir_help)
    output_label, output_help = _wizard_label_help("output_dir", "output_dir", output_dir_help)

    # bids_dir/output_dir/t1_pattern are read by Review/the sidebar/
    # _collect_wizard_values on reruns where this step isn't rendered at
    # all -- shadow-seed/sync each one (see WIZARD_SHADOW_PREFIX's module
    # comment), since Streamlit deletes a widget's session_state entry
    # once its widget stops being instantiated.
    bids_dir_key = f"{WIZARD_KEY_PREFIX}bids_dir"
    if bids_dir_key not in st.session_state:
        st.session_state[bids_dir_key] = _wizard_shadow_get("bids_dir", "")
    output_dir_key = f"{WIZARD_KEY_PREFIX}output_dir"
    if output_dir_key not in st.session_state:
        st.session_state[output_dir_key] = _wizard_shadow_get("output_dir", "")

    st.header("Where is your data?")
    col1, col2 = st.columns(2)
    with col1:
        bids_dir = st.text_input(f"{bids_label} (bids_dir)", help=bids_help, key=bids_dir_key)
        _wizard_shadow_set("bids_dir", bids_dir)
        if bids_dir and not Path(bids_dir).exists():
            st.caption(f":red[Folder not found: {bids_dir}]")
        elif bids_dir:
            st.caption(":green[Found.]")
    with col2:
        output_dir = st.text_input(f"{output_label} (output_dir)", help=output_help, key=output_dir_key)
        _wizard_shadow_set("output_dir", output_dir)
        if output_dir:
            st.caption(f"Will create `{output_dir.rstrip('/')}/mrsiprep`.")

    t1_action = action_lookup["--t1"]
    t1_label, t1_help = _wizard_label_help("t1_pattern", "--t1", (t1_action.help or "").strip())
    t1_key = f"{WIZARD_KEY_PREFIX}t1_pattern"
    if t1_key not in st.session_state:
        st.session_state[t1_key] = _wizard_shadow_get("t1_pattern", t1_action.default)
    t1_pattern = st.text_input(f"{t1_label} (--t1)", help=t1_help, key=t1_key)
    _wizard_shadow_set("t1_pattern", t1_pattern)

    st.subheader("Raw MRSI data location")
    mrsi_input_label, mrsi_input_help = _wizard_label_help(
        "mrsi_input_dir", "--mrsi-input-dir", (action_lookup["--mrsi-input-dir"].help or "").strip()
    )
    # Standard-location default mirrors MRSIPrepConfig._resolve_paths exactly:
    # bare bids_dir, used verbatim -- never normalized/stripped, so a custom
    # path the user types is never silently altered either (see
    # default_mrsinmrs_file below, which appends to this same value as-is).
    effective_mrsi_input_dir, mrsi_input_custom = _render_path_mode_field(
        "mrsi_input_dir", "--mrsi-input-dir", bids_dir, f"{mrsi_input_label}. {mrsi_input_help}"
    )
    if effective_mrsi_input_dir:
        mrsi_space_dirs = sorted(Path(effective_mrsi_input_dir).joinpath("derivatives").glob("mrsi-*"))
        if mrsi_input_custom:
            st.caption(f"Raw MRSI data read from: `{effective_mrsi_input_dir}` (used exactly as entered).")
        else:
            st.caption(
                f"Raw MRSI data expected under: `{effective_mrsi_input_dir.rstrip('/')}/derivatives/mrsi-<space>/` "
                "(e.g. `derivatives/mrsi-orig/`) -- same root as your BIDS dataset."
            )
        if mrsi_space_dirs:
            st.caption(":green[✓ Found:] " + ", ".join(f"`{p.name}`" for p in mrsi_space_dirs))
        else:
            st.caption(f":red[No derivatives/mrsi-* folder found under {effective_mrsi_input_dir}]")
    default_mrsinmrs_file = (
        f"{effective_mrsi_input_dir.rstrip('/')}/derivatives/mrsi-orig/mrsinmrs.json" if effective_mrsi_input_dir else ""
    )

    mrsinmrs_label, mrsinmrs_help = _wizard_label_help(
        "mrsinmrs_file", "--mrsinmrs-file", (action_lookup["--mrsinmrs-file"].help or "").strip()
    )
    effective_mrsinmrs_file, _mrsinmrs_custom = _render_path_mode_field(
        "mrsinmrs_file", "--mrsinmrs-file", default_mrsinmrs_file, f"{mrsinmrs_label}. {mrsinmrs_help}"
    )
    if effective_mrsinmrs_file:
        st.caption(f"Acquisition metadata: `{effective_mrsinmrs_file}`")
        if Path(effective_mrsinmrs_file).is_file():
            st.caption(":green[✓ Found.]")
        else:
            st.caption(f":red[Not found yet: {effective_mrsinmrs_file}]")

    st.subheader("Which participants?")
    _render_participant_selection(
        action_lookup["--participant-label"], action_lookup["--session-label"],
        action_lookup["--participants"], bids_dir,
    )

    st.subheader("Metabolites")
    nucleus = _wizard_shadow_get("nucleus") or DEFAULT_NUCLEUS
    metabolites = _render_metabolites_widget(
        action_lookup["--metabolites"], nucleus=nucleus, mrsi_input_dir=effective_mrsi_input_dir
    )
    if not metabolites:
        st.warning("Choose at least one metabolite to continue.")


def _render_wizard_flag_group(
    flags: list[str], action_lookup: dict[str, argparse.Action], rendered_flags: set[str]
) -> None:
    """Renders exactly `flags`' widgets under WIZARD_KEY_PREFIX, reusing the
    same per-flag conditional-visibility rules _render_custom_step_widgets
    already applies (backend-specific flags shown only once a backend is
    picked, chimera-scheme-picker-when-chimera, atlas-only-when-atlas-mode)
    -- copied rather than reimplemented, per the plan. `rendered_flags` is
    shared across every call in one Processing-step render (flags owned by
    more than one CUSTOM_STEP_FLAGS step, e.g. --ref-met/--tissue-backend,
    must still get exactly one widget)."""
    backend_choice = None
    for flag in flags:
        if flag in rendered_flags:
            continue
        action = action_lookup.get(flag)
        if action is None:
            continue

        # Re-read on every iteration (rather than once before the loop):
        # when --parcellation-mode is itself one of `flags` (it always is,
        # for the "Parcellation and connectivity" expander, which lists
        # --parcellation-mode first in CUSTOM_STEP_FLAGS["mrsi_parcellation"]),
        # the very first time the user switches it to "chimera"/"atlas" this
        # loop must see the *new* value for the chimera-scheme/atlas flags
        # later in the same pass, not a value captured before that widget
        # ran this call.
        parcellation_mode_value = _wizard_shadow_get("parcellation_mode")

        if flag == "--ref-met":
            # Already rendered once at the top of the Processing step (its
            # own dropdown, populated from Data's chosen metabolites) --
            # never re-rendered generically here.
            rendered_flags.add(flag)
            continue
        if flag == "--registration-backend":
            backend_choice = _widget_for(action, key_prefix=WIZARD_KEY_PREFIX)
            rendered_flags.add(flag)
            continue
        if flag in BACKEND_SPECIFIC_FLAGS:
            continue  # rendered below, once backend_choice is known
        if flag in ("--chimera-scheme", "--chimera-scale", "--chimera-grow"):
            continue  # rendered together below, once --parcellation-mode is known
        if flag == "--fs-subjects-dir" and parcellation_mode_value != "chimera":
            continue
        if flag in ("--atlas", "--custom-atlas", "--custom-atlas-lut") and parcellation_mode_value != "atlas":
            continue
        if flag == "--atlas":
            # _render_atlas_widget doesn't go through _widget_for, so it
            # never shadow-syncs on its own (see WIZARD_SHADOW_PREFIX's
            # module comment) -- do it explicitly here, or --atlas would
            # silently never reach Review/_collect_wizard_values.
            if f"{WIZARD_KEY_PREFIX}atlas" not in st.session_state:
                shadow_atlas = _wizard_shadow_get("atlas")
                if shadow_atlas is not None:
                    st.session_state[f"{WIZARD_KEY_PREFIX}atlas"] = shadow_atlas
            atlas_value = _render_atlas_widget(action, key_prefix=WIZARD_KEY_PREFIX)
            _wizard_shadow_set("atlas", atlas_value)
            rendered_flags.add(flag)
            continue

        _widget_for(action, key_prefix=WIZARD_KEY_PREFIX)
        rendered_flags.add(flag)

    if backend_choice is not None:
        wanted = ANTS_ONLY_FLAGS if backend_choice == "ants" else FSL_ONLY_FLAGS
        for flag in flags:
            if flag in wanted and flag not in rendered_flags:
                st.caption(f"Shown because registration backend is set to {backend_choice}.")
                _widget_for(action_lookup[flag], key_prefix=WIZARD_KEY_PREFIX)
                rendered_flags.add(flag)

    if (
        "--chimera-scheme" in flags
        and _wizard_shadow_get("parcellation_mode") == "chimera"
        and "--chimera-scheme" not in rendered_flags
    ):
        st.caption("Shown because the parcellation method is set to 'chimera'.")
        st.markdown("**Chimera scheme** -- one atlas per supra-region, guided:")
        # _render_chimera_scheme_picker doesn't go through _widget_for
        # either -- shadow-sync its three return values explicitly (see
        # the --atlas handling above and WIZARD_SHADOW_PREFIX's module
        # comment), or they'd silently never reach Review.
        code, scale, grow = _render_chimera_scheme_picker(
            action_lookup["--chimera-scheme"], action_lookup["--chimera-scale"], action_lookup["--chimera-grow"],
            key_prefix=WIZARD_KEY_PREFIX,
        )
        _wizard_shadow_set("chimera_scheme", code)
        _wizard_shadow_set("chimera_scale", scale)
        _wizard_shadow_set("chimera_grow", grow)
        rendered_flags.update({"--chimera-scheme", "--chimera-scale", "--chimera-grow"})


def _render_wizard_processing_step(optionals: list[argparse.Action]) -> None:
    """Step 3: a one-line plain-language summary, --ref-met (populated from
    Data's chosen metabolites), then four collapsed-by-default expanders
    grouping CUSTOM_STEP_FLAGS per plan §3. The "Parcellation and
    connectivity" expander is the one place wizard_outcome changes
    rendering: expanded by default for the "parcellation" outcome,
    collapsed (never hidden -- parcellation always runs) otherwise."""
    action_lookup = {_dest_label(a): a for a in optionals}

    st.header("Processing options")
    st.caption(
        "MRSIPrep always runs the full pipeline: load and quality-mask the MRSI data, correct and "
        "register it to your T1w anatomical and standard space, segment tissue for partial-volume "
        "correction, parcellate the brain into regions, and build the final QC report. The options "
        "below fine-tune how each stage runs; sensible defaults are already filled in."
    )

    metabolites = list(_wizard_shadow_get("metabolites") or [])
    ref_met_action = action_lookup["--ref-met"]
    _render_ref_met_widget(ref_met_action, metabolites)

    outcome = st.session_state.get("wizard_outcome")
    rendered_flags: set[str] = {"--metabolites"}

    with st.expander("Registration", expanded=False):
        flags = []
        for step in PROCESSING_EXPANDER_STEP_GROUPS["Registration"]:
            flags.extend(CUSTOM_STEP_FLAGS[step])
        _render_wizard_flag_group(flags, action_lookup, rendered_flags)

    with st.expander("Tissue and relaxation corrections", expanded=False):
        flags = []
        for step in PROCESSING_EXPANDER_STEP_GROUPS["Tissue and relaxation corrections"]:
            flags.extend(CUSTOM_STEP_FLAGS[step])
        _render_wizard_flag_group(flags, action_lookup, rendered_flags)

    with st.expander("Parcellation and connectivity", expanded=(outcome == "parcellation")):
        st.caption("Parcellation always runs (lightweight SynthSeg by default); these options are optional.")
        flags = []
        for step in PROCESSING_EXPANDER_STEP_GROUPS["Parcellation and connectivity"]:
            flags.extend(CUSTOM_STEP_FLAGS[step])
        _render_wizard_flag_group(flags, action_lookup, rendered_flags)

    with st.expander("Runtime and existing outputs", expanded=False):
        st.caption(
            "Already ran this recording before? Check **Only regenerate reports** below to skip "
            "straight to rewriting QC tables/figures/HTML from the existing derivatives, instead of "
            "reprocessing from scratch."
        )
        _render_wizard_flag_group(list(RUNTIME_EXPANDER_FLAGS), action_lookup, rendered_flags)


def _render_wizard_review_step(optionals: list[argparse.Action], positionals: list[argparse.Action]) -> None:
    """Step 4: plain-language summary, inline validation split into "Ready
    to copy" vs. "Incomplete configuration" (never both -- the command is
    withheld entirely, not shown with placeholder tokens, when anything
    blocks), the generated command in a copyable st.code block once valid,
    a short "where to run this" note, the existing preflight button/
    _compute_preflight/_render_preflight_result moved here (rendered
    inline, not via st.switch_page), and the existing pipeline flowchart in
    a collapsed-by-default expander."""
    positional_values, values = _collect_wizard_values(optionals, positionals)
    statuses = _compute_field_statuses(values, positional_values)
    blocking = _wizard_blocking_messages(statuses)

    st.header("Review and copy")

    metabolites = values.get("--metabolites") or []
    participant_mode = _wizard_shadow_get("participant_mode") or "All participants"
    outcome = st.session_state.get("wizard_outcome")
    outcome_label = {
        "normalize": "Normalize metabolite maps", "parcellation": "Parcellation and connectivity",
    }.get(outcome, "(not chosen)")

    st.markdown(
        f"- **Analysis:** {outcome_label}\n"
        f"- **Dataset folder:** `{positional_values.get('bids_dir') or '(not set)'}`\n"
        f"- **Output folder:** `{positional_values.get('output_dir') or '(not set)'}`\n"
        f"- **Participants:** {participant_mode}\n"
        f"- **Metabolites:** {len(metabolites)} selected"
        + (f" ({', '.join(metabolites)})" if metabolites else "")
    )

    if blocking:
        st.error("**Incomplete configuration** -- fix the following before copying a command:")
        for message in blocking:
            st.markdown(f"- {message}")
    else:
        st.success("**Ready to copy.**")
        command = _build_command(positional_values, optionals, values)
        with st.expander("Generated command", expanded=True):
            st.code(command, language="bash")
            st.caption(
                "Run this on the machine with Docker installed and your dataset mounted -- see "
                "`mrsiprep-docker` in docs/usage_basic.md. This tool never executes it for you."
            )

    for dest, (level, message) in statuses.items():
        if level == "warn":
            st.warning(message)

    st.divider()
    st.subheader("Preflight check")
    st.caption(
        "Checks the existence and validity of the input files (T1w, raw MRSI maps, mrsinmrs.json) "
        "for every recording matched above -- no Docker, no processing, nothing written to disk."
    )
    preflight_ready = not blocking
    if st.button(
        "Run preflight check", key="wizard_run_preflight_btn", disabled=not preflight_ready,
        help="Fill in every required field above to enable this." if not preflight_ready else None,
    ):
        progress_bar = st.progress(0.0, text="Checking inputs...")

        def _update_progress(done, total, recording_id):
            progress_bar.progress(
                done / total if total else 1.0, text=f"Checking inputs... ({done}/{total}) {recording_id}",
            )

        st.session_state["preflight_result"] = _compute_preflight(
            positional_values, optionals, values, progress=_update_progress
        )
        progress_bar.empty()

    if st.session_state.get("preflight_result") is not None:
        _render_preflight_result(st.session_state["preflight_result"])

    with st.expander("Pipeline diagram", expanded=False):
        _render_step_flowchart(list(CUSTOM_STEP_FLAGS), values)


def _render_step_nav(num_steps: int, statuses: dict[str, tuple[str, str]]) -> None:
    """Manual button row (st.columns), not st.tabs/st.radio -- neither
    supports programmatic "jump to step N" / "Next disabled until valid"
    cleanly (plan §5.1). Each step also gets its own Back/Next pair; Next is
    disabled while the *current* step has a blocking (tier 1) issue. Moving
    wizard_step is a direct session_state assignment + st.rerun(), mirroring
    this file's existing _move_custom_step idiom."""
    step = st.session_state["wizard_step"]
    # Each step only gates Next on the blocking checks that are actually
    # *its own* fields -- Data's Next must not stay disabled over a
    # Processing-only issue (e.g. --ref-met/--fs-license, neither of which
    # Data even renders), or the user could never leave Data until they'd
    # also finished Processing, defeating the step-by-step design.
    _DATA_STEP_STATUS_DESTS = {"bids_dir", "output_dir", "metabolites"}
    data_blocking = [
        message for dest, (level, message) in statuses.items()
        if level == "block" and dest in _DATA_STEP_STATUS_DESTS
    ]

    cols = st.columns(num_steps)
    for i, title in enumerate(WIZARD_STEP_TITLES):
        with cols[i]:
            marker = "●" if i == step else ("✔" if i < step else "○")
            if st.button(f"{marker} {i + 1}. {title}", key=f"wizard_nav_{i}", disabled=(i == step)):
                st.session_state["wizard_step"] = i
                st.rerun()

    st.markdown("---")
    col_back, col_spacer, col_next = st.columns([1, 4, 1])
    with col_back:
        if st.button("Back", key="wizard_back_btn", disabled=(step == 0)):
            st.session_state["wizard_step"] = step - 1
            st.rerun()
    with col_next:
        # Review (the last step) has no Next -- "Run preflight check" and
        # the copyable command are its own terminal actions.
        if step < num_steps - 1:
            next_disabled = step == 1 and bool(data_blocking)  # Data step: gate on bids_dir/output_dir/metabolites
            if st.button("Next", key="wizard_next_btn", disabled=next_disabled, type="primary"):
                st.session_state["wizard_step"] = step + 1
                st.rerun()
            if next_disabled:
                st.caption(":red[Finish the required fields above to continue.]")


def _render_wizard_sidebar_summary(statuses: dict[str, tuple[str, str]]) -> None:
    """Persistent summary in st.sidebar (this file used no sidebar before),
    populated every rerun: outcome chosen, participant mode, metabolite
    count, output folder status, and one "Next: <thing>" nudge computed
    from the same blocking-check dict, in a fixed priority order (plan
    §5.2)."""
    with st.sidebar:
        st.subheader("MRSIPrep Command Builder")
        outcome = st.session_state.get("wizard_outcome")
        outcome_label = {
            "normalize": "Normalize metabolite maps", "parcellation": "Parcellation and connectivity",
        }.get(outcome, "Not chosen yet")
        st.caption(f"**Analysis:** {outcome_label}")

        participant_mode = _wizard_shadow_get("participant_mode") or "All participants"
        st.caption(f"**Participants:** {participant_mode}")

        metabolites = _wizard_shadow_get("metabolites") or []
        st.caption(f"**Metabolites:** {len(metabolites)} selected")

        output_dir = _wizard_shadow_get("output_dir") or ""
        output_status = "not set" if not output_dir else ("found" if Path(output_dir).exists() else "will be created")
        st.caption(f"**Output folder:** {output_status}")

        priority = ["bids_dir", "output_dir", "metabolites", "ref_met", "fs_license"]
        next_thing = None
        for dest in priority:
            level_message = statuses.get(dest)
            if level_message and level_message[0] == "block":
                next_thing = level_message[1]
                break
        if next_thing:
            st.info(f"**Next:** {next_thing}")
        else:
            st.success("Ready for Review.")


def _render_wizard_page() -> None:
    st.title("MRSIPrep Command Builder")
    st.caption(
        "Builds a runnable `mrsiprep-docker` command from the actual CLI definition. "
        "This page does not execute anything -- copy the generated command and run it yourself."
    )
    st.caption(
        f"Command builder (mrsiprep) version: `{mrsiprep_version()}` &nbsp;|&nbsp; "
        f"mrsiprep-docker wrapper version: `{_mrsiprep_docker_version()}`",
        unsafe_allow_html=True,
    )

    parser = build_parser()
    positionals = [a for a in parser._actions if not a.option_strings and a.dest != "help"]
    optionals = [
        a for a in parser._actions
        if a.option_strings
        and _dest_label(a) not in EXCLUDED_FLAGS
        and _dest_label(a) not in NEGATIVE_FLAG_PAIRS
    ]
    action_lookup = _flag_action_lookup(optionals)

    st.session_state.setdefault("wizard_step", 0)
    st.session_state.setdefault("wizard_outcome", None)
    st.session_state.setdefault("wizard_advanced_steps", False)

    if st.session_state["wizard_advanced_steps"]:
        st.info(
            "Advanced mode: composing a custom --steps subset directly. Uncheck the box in Analysis "
            "to return to the guided wizard."
        )
        if st.button("← Back to guided wizard"):
            st.session_state["wizard_advanced_steps"] = False
            st.rerun()
        positional_values, values = _collect_wizard_values(optionals, positionals)
        command = _render_custom_pipeline_tab(optionals, action_lookup, positional_values, values)
        st.header("Generated command")
        st.code(command, language="bash")
        return

    # The nav row's Next-button gate and the sidebar summary both need this
    # run's freshest statuses -- but those depend on shadow state that the
    # step body below is what actually updates (e.g. the very first rerun
    # where Data's three fields all become valid: _collect_wizard_values
    # called here, before _render_wizard_data_step runs, would still see
    # last run's stale values, leaving Next looking disabled one extra
    # interaction longer than necessary). Reserve the nav's slot with
    # st.empty() now (so it still renders at the top, above the step body,
    # matching the plan's layout) but fill it only after the step body has
    # run and updated this run's shadow state.
    nav_slot = st.empty()

    step = st.session_state["wizard_step"]
    try:
        if step == 0:
            _render_wizard_analysis_step()
        elif step == 1:
            _render_wizard_data_step(optionals, positionals)
        elif step == 2:
            _render_wizard_processing_step(optionals)
        elif step == 3:
            _render_wizard_review_step(optionals, positionals)
    except Exception:
        # A step body can raise (e.g. the Review step's preflight button
        # calling into the real pipeline code) -- without this, Streamlit
        # aborts the script right there and the nav row below never
        # renders, stranding the user on a bare error page with no way to
        # navigate back short of restarting the app.
        st.exception(sys.exc_info()[1])

    positional_values, values = _collect_wizard_values(optionals, positionals)
    statuses = _compute_field_statuses(values, positional_values)
    _render_wizard_sidebar_summary(statuses)
    with nav_slot.container():
        _render_step_nav(len(WIZARD_STEP_TITLES), statuses)


def _branch_badge(step_name: str) -> str:
    if step_name in ANAT_BRANCH_STEPS:
        return "Anat branch"
    if step_name in MRSI_BRANCH_STEPS:
        return "MRSI branch"
    return "Downstream"


def _add_custom_step(step_name: str) -> None:
    """Appends `step_name` to the composed sequence. "prepare" produces the
    validated BIDS inputs (`ctx["inputs"]`/`t1_path`/`raw_t1`) every other
    step -- in either branch -- ultimately depends on, directly or
    transitively, and it is the only step with no dependencies of its own
    (see STEP_DEPENDENCIES in steps_registry.py): it must always come first.
    Rather than let a user add e.g. "mrsi_load" to an empty sequence and
    then be confused by a validation error naming a step they never clicked,
    "prepare" is auto-prepended the first time anything is added."""
    steps = st.session_state["custom_steps"]
    if not steps and step_name != "prepare":
        steps.append("prepare")
    if step_name not in steps:
        steps.append(step_name)
        st.rerun()


def _remove_custom_step(index: int) -> None:
    st.session_state["custom_steps"].pop(index)
    st.rerun()


def _move_custom_step(index: int, delta: int) -> None:
    steps = st.session_state["custom_steps"]
    new_index = index + delta
    if 0 <= new_index < len(steps):
        steps[index], steps[new_index] = steps[new_index], steps[index]
        st.rerun()


def _render_add_step_controls() -> None:
    """Two side-by-side branch columns (anat/MRSI, each a fixed 3-button list
    in branch order) plus a single selectbox+Add row for every step from
    `registration` onward -- see the plan's rationale: the two branches run
    independently of each other (neither needs the other to finish first),
    while the downstream steps are a flat linear tail with no branching to
    visualize, so a selectbox fits better there than 12 buttons."""
    st.subheader("Add a step")
    custom_steps = st.session_state["custom_steps"]

    anat_col, mrsi_col = st.columns(2)
    with anat_col:
        st.markdown("**Anat branch**")
        st.caption(" -> ".join(ANAT_BRANCH_STEPS))
        for step in ANAT_BRANCH_STEPS:
            already_added = step in custom_steps
            if st.button(
                f"+ {step}", key=f"add_btn_{step}", disabled=already_added,
                help="Already added." if already_added else f"Add '{step}' to the end of your custom sequence.",
            ):
                _add_custom_step(step)

    with mrsi_col:
        st.markdown("**MRSI branch**")
        st.caption(" -> ".join(MRSI_BRANCH_STEPS))
        for step in MRSI_BRANCH_STEPS:
            already_added = step in custom_steps
            if st.button(
                f"+ {step}", key=f"add_btn_{step}", disabled=already_added,
                help="Already added." if already_added else f"Add '{step}' to the end of your custom sequence.",
            ):
                _add_custom_step(step)

    st.markdown("**Shared / downstream steps** (after both branches converge at `registration`)")
    downstream_available = [s for s in DOWNSTREAM_STEPS if s not in custom_steps]
    col_select, col_add = st.columns([4, 1])
    with col_select:
        downstream_choice = st.selectbox(
            "Step to add", downstream_available or ["(all added)"],
            key="custom_downstream_choice", label_visibility="collapsed",
        )
    with col_add:
        if st.button("Add", key="add_downstream_btn", disabled=not downstream_available):
            _add_custom_step(downstream_choice)


def _render_custom_step_widgets(
    step_name: str,
    action_lookup: dict[str, argparse.Action],
    parcellation_mode_value,
    values: dict,
    rendered_flags: set[str],
) -> None:
    """Renders exactly `CUSTOM_STEP_FLAGS[step_name]`'s widgets, reusing the
    same per-flag dispatch/conditional-visibility rules the Standardized
    tab's topic-tab loop already uses (_render_standardized_pipeline_tab),
    just scoped to one step's flag list instead of one argparse group's.

    A handful of flags (e.g. --ref-met, --tissue-backend, --fsl-cost) are
    legitimately read by more than one step and so appear in more than one
    step's CUSTOM_STEP_FLAGS entry -- `rendered_flags` is shared across every
    step in the composed sequence (not just this call) so such a flag gets
    exactly one widget, the first time it's encountered, instead of crashing
    on a duplicate Streamlit `key=` when a later step also lists it."""
    flags = [f for f in CUSTOM_STEP_FLAGS[step_name] if f not in rendered_flags]
    if not flags:
        st.caption("No step-specific options for this step (already configured by an earlier step in your sequence).")
        return

    backend_choice = None
    for flag in flags:
        action = action_lookup.get(flag)
        if action is None:
            continue  # defensive: flag renamed/removed upstream, skip rather than KeyError

        if flag == "--registration-backend":
            backend_choice = _widget_for(action, key_prefix="custom_field_")
            values[flag] = backend_choice
            rendered_flags.add(flag)
            continue
        if flag in BACKEND_SPECIFIC_FLAGS:
            continue  # rendered below, once backend_choice is known
        if flag in ("--chimera-scheme", "--chimera-scale", "--chimera-grow"):
            continue  # rendered together below, once --parcellation-mode is known
        if flag == "--fs-subjects-dir" and parcellation_mode_value != "chimera":
            continue
        if flag in ("--atlas", "--custom-atlas", "--custom-atlas-lut") and parcellation_mode_value != "atlas":
            continue
        if flag == "--atlas":
            values[flag] = _render_atlas_widget(action, key_prefix="custom_field_")
            rendered_flags.add(flag)
            continue

        values[flag] = _widget_for(action, key_prefix="custom_field_")
        rendered_flags.add(flag)
        if flag == "--parcellation-mode":
            parcellation_mode_value = values[flag]

    if backend_choice is not None:
        wanted = ANTS_ONLY_FLAGS if backend_choice == "ants" else FSL_ONLY_FLAGS
        for flag in flags:
            if flag in wanted and flag not in rendered_flags:
                values[flag] = _widget_for(action_lookup[flag], key_prefix="custom_field_")
                rendered_flags.add(flag)

    if (
        step_name == "mrsi_parcellation"
        and parcellation_mode_value == "chimera"
        and "--chimera-scheme" not in rendered_flags
    ):
        scheme_action = action_lookup["--chimera-scheme"]
        scale_action = action_lookup["--chimera-scale"]
        grow_action = action_lookup["--chimera-grow"]
        st.markdown("**Chimera scheme** -- one atlas per supra-region, guided:")
        code, scale, grow = _render_chimera_scheme_picker(
            scheme_action, scale_action, grow_action, key_prefix="custom_field_"
        )
        values["--chimera-scheme"] = code
        values["--chimera-scale"] = scale
        values["--chimera-grow"] = grow
        rendered_flags.update({"--chimera-scheme", "--chimera-scale", "--chimera-grow"})


def _build_custom_command(
    positional_values: dict, optionals: list[argparse.Action], values: dict, custom_steps: list[str]
) -> str:
    """Same as _build_command, plus an explicit --steps flag listing the
    user's composed sequence. --steps takes a single comma-separated token
    (type=_parse_comma_list, nargs=None -- like --metabolites, not a
    nargs="+" flag), so the value must be one joined string, not a Python
    list: _build_argv_groups would otherwise emit each step as its own
    space-separated argv token, which _parse_comma_list can't parse back
    into a list on the receiving end."""
    values_with_steps = dict(values)
    if custom_steps:
        values_with_steps["--steps"] = ",".join(custom_steps)
    return _build_command(positional_values, optionals, values_with_steps)


def _render_custom_pipeline_tab(
    optionals: list[argparse.Action],
    action_lookup: dict[str, argparse.Action],
    positional_values: dict,
    values: dict,
) -> str:
    """Compose a custom subset/order of the 18 pipeline steps, one Add at a
    time, configuring only each added step's own relevant flags -- backed by
    the real STEP_DEPENDENCIES registry for live validation, instead of the
    Standardized tab's flat topic-based tabs covering the full pipeline.
    Required arguments (`positional_values`/`values`, including
    --participants) are rendered once in main() and shared with the
    Standardized tab, not re-rendered here -- so filling them out on either
    tab carries over. Returns the generated command string (the caller owns
    the shared "Generated command" box above the mode tabs and writes it
    there) rather than rendering its own copy."""
    st.caption(
        "Compose a custom subset/order of pipeline steps (backs the `--steps` CLI flag). Only "
        "step-specific options are configured per added step; required arguments above are shared "
        "with the Standardized Pipeline tab."
    )
    st.session_state.setdefault("custom_steps", [])

    st.header("Compose your step sequence")
    _render_add_step_controls()

    custom_steps: list[str] = st.session_state["custom_steps"]
    if not custom_steps:
        st.info("No steps added yet. Use the controls above to build your sequence.")
    # Seed with every flag the required-args section above already rendered
    # (e.g. --ref-met is globally required, so it's rendered there once;
    # without this seed, mrsi_load/mrsi_reference -- which also list --ref-met
    # -- would try to render it a second time under the same widget key).
    rendered_flags: set[str] = set(values)
    for i, step_name in enumerate(custom_steps):
        row = st.columns([6, 1, 1, 1])
        row[0].markdown(f"**{i + 1}. {step_name}**  `{_branch_badge(step_name)}`")
        if row[1].button("↑", key=f"up_{i}_{step_name}", disabled=(i == 0)):
            _move_custom_step(i, -1)
        if row[2].button("↓", key=f"down_{i}_{step_name}", disabled=(i == len(custom_steps) - 1)):
            _move_custom_step(i, 1)
        if row[3].button("✕", key=f"remove_{i}_{step_name}"):
            _remove_custom_step(i)
        with st.expander(f"{step_name} options", expanded=False):
            _render_custom_step_widgets(
                step_name, action_lookup, values.get("--parcellation-mode"), values, rendered_flags
            )

    st.subheader("Step-order validation")
    if custom_steps:
        try:
            validate_step_order(custom_steps)
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.success("This step order is valid -- every step's required inputs are produced by an earlier step.")
    else:
        st.caption("Add at least one step above to see validation feedback.")

    # Rebuilt from st.session_state["custom_steps"] on every call, so it's
    # always in sync with the list above -- Streamlit reruns this whole
    # function on every add/remove/reorder click (see _add_custom_step/
    # _remove_custom_step/_move_custom_step, each ending in st.rerun()).
    st.subheader("Pipeline flowchart")
    _render_step_flowchart(custom_steps, values)

    return _build_custom_command(positional_values, optionals, values, custom_steps)


def _build_native_argv(positional_values: dict, optionals: list[argparse.Action], values: dict) -> list[str]:
    """Same flags as the displayed `mrsiprep-docker` command, but as a plain
    argv for mrsiprep's own parser (bids_dir/output_dir unwrapped from the
    /data,/out container paths) -- used to run preflight validation
    in-process, never to invoke Docker."""
    argv = [
        str(positional_values.get("bids_dir") or ""),
        str(positional_values.get("output_dir") or ""),
        "participant",
    ]
    for group in _build_argv_groups(positional_values, optionals, values):
        argv.extend(group)
    return argv


def _compute_preflight(positional_values: dict, optionals: list[argparse.Action], values: dict, progress=None) -> dict:
    """Runs real input validation (no processing, no Docker) against the
    form's current bids_dir/mrsi_input_dir/participant selection. Pure
    file-existence/NIfTI-validity checks -- the same ones `--validate-only`
    runs -- so this is safe to run directly on the host. Returns a plain
    dict for `_render_preflight_result` to display; never calls into
    Streamlit itself (besides the optional `progress` callback) so it can
    run inside `st.spinner(...)` cleanly.

    Reimplements `validate_participant_inputs`'s own per-recording loop
    (rather than calling it directly) so `progress(done, total, recording_id)`
    can be invoked after each recording -- a dataset's participant list can
    be large enough that a single opaque spinner isn't informative."""
    from mrsiprep.cli.parser import parse_args
    from mrsiprep.io.validators import validate_recording
    from mrsiprep.workflows.participant import _validate_backend_inputs, collect_recordings
    from mrsiprep.workflows.preflight import RecordingStatus, _gather_input_availability
    from mrsiprep.utils.misc import normalize_session, normalize_subject

    if not positional_values.get("bids_dir") or not positional_values.get("output_dir"):
        return {"error": "Fill in bids_dir and output_dir before running preflight."}

    argv = _build_native_argv(positional_values, optionals, values)
    try:
        config = parse_args(argv)
    except SystemExit:
        return {"error": "Could not parse the current form into a valid command -- check the required fields above."}
    except Exception as exc:  # noqa: BLE001 -- surfaced to the user, not a crash
        return {"error": f"Configuration error: {exc}"}

    try:
        config.require_mrsinmrs()
        recordings = collect_recordings(config)
    except Exception as exc:  # noqa: BLE001 -- surfaced to the user, not a crash
        return {"error": f"Preflight failed to run: {exc}"}

    statuses: list[RecordingStatus] = []
    availability: list[dict] = []
    total = len(recordings)
    for done, recording in enumerate(recordings, start=1):
        subject = normalize_subject(recording.subject)
        session = normalize_session(recording.session)
        recording_id = f"sub-{subject}" + (f"_ses-{session}" if session else "")
        try:
            summary = _gather_input_availability(config, subject, session)
            availability.append(summary)
            t1_path, inputs = validate_recording(config, subject, session)
            _validate_backend_inputs(config, subject, session)
            outputs = {
                "t1w": t1_path,
                "metabolites": sorted(inputs.metabolite_maps),
                "snr": inputs.snr_map,
                "linewidth": inputs.linewidth_map,
                "brainmask": inputs.brainmask,
            }
            statuses.append(RecordingStatus(subject, session, "success", outputs=outputs))
        except Exception as exc:  # noqa: BLE001 -- surfaced per-recording, not a crash
            statuses.append(RecordingStatus(subject, session, "failed", error=str(exc)))
        if progress is not None:
            progress(done, total, recording_id)

    return {"statuses": statuses, "availability": availability}


def _render_preflight_result(result: dict) -> None:
    if result.get("error"):
        st.error(result["error"])
        return

    statuses = result["statuses"]
    availability = result["availability"]
    if not statuses:
        st.warning("No recordings matched bids_dir / --participant-label / --session-label.")
        return

    n_ok = sum(1 for s in statuses if s.status == "success")
    n_bad = len(statuses) - n_ok
    (st.success if n_bad == 0 else st.warning)(
        f"{n_ok}/{len(statuses)} recording(s) ready to process" + (f", {n_bad} failed" if n_bad else ".")
    )

    _OK_MARK = "✔ present"
    _MISSING_MARK = "✖ missing"

    rows = []
    for status, summary in zip(statuses, availability):
        rows.append({
            "Recording": summary["recording_id"],
            "Status": "OK" if status.status == "success" else "FAILED",
            "T1w": _OK_MARK if summary["t1"] else _MISSING_MARK,
            "MRSI maps": f"{summary['mrsi_found']}/{summary['mrsi_expected']}",
            "CRLB": f"{summary['crlb_found']}/{summary['mrsi_expected']}",
            "SNR": _OK_MARK if summary["snr"] else _MISSING_MARK,
            "Linewidth": _OK_MARK if summary["fwhm"] else _MISSING_MARK,
            "Brain mask": _OK_MARK if summary["brainmask"] else _MISSING_MARK,
            "Corrupt files": ", ".join(summary["corrupt_items"]) or "-",
        })

    def _style_row(row: pd.Series) -> list[str]:
        styles = [""] * len(row)
        status_idx = row.index.get_loc("Status")
        styles[status_idx] = (
            "color: #1a7f37; font-weight: 600" if row["Status"] == "OK"
            else "color: #d1242f; font-weight: 600"
        )
        for col in ("T1w", "SNR", "Linewidth", "Brain mask"):
            idx = row.index.get_loc(col)
            styles[idx] = "color: #1a7f37" if str(row[col]).startswith("✔") else "color: #d1242f"
        return styles

    table = pd.DataFrame(rows)
    st.dataframe(table.style.apply(_style_row, axis=1), use_container_width=True, hide_index=True)


def launch() -> None:
    """Entry point for `mrsiprep-build-command` (see pyproject.toml): launches
    this script under `streamlit run` rather than calling main() directly,
    since Streamlit apps require its script-running machinery. Any extra
    arguments (e.g. --server.port 9000) are forwarded to `streamlit run`."""
    import sys

    from streamlit.web import cli as stcli

    sys.argv = ["streamlit", "run", __file__, *sys.argv[1:]]
    sys.exit(stcli.main())


def main() -> None:
    st.set_page_config(page_title="MRSIPrep Command Builder", layout="wide")
    _render_wizard_page()


if __name__ == "__main__":
    main()
