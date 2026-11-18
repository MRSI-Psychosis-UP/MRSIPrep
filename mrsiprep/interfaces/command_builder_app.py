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
import html
import shlex
from pathlib import Path

import pandas as pd
import streamlit as st

from mrsiprep.cli.parser import build_parser
from mrsiprep.io.bids import _normalize_mrsi_input_dir
from mrsiprep.utils.version import mrsiprep_version
from mrsiprep.config.chimera_schemes import (
    SUPRA_REGION_LABELS,
    SUPRA_REGIONS,
    build_scheme_code,
    valid_letters,
)
from mrsiprep.workflows.nipype_engine.steps_registry import STEP_DEPENDENCIES, validate_step_order

# Debug/internal flags not useful in a user-facing form.
EXCLUDED_FLAGS = {"--hello-world", "--help", "-h"}

# store_true/store_false flag pairs sharing one dest (e.g. --fsl-deformable /
# --no-fsl-deformable): only the positive flag gets a widget; the negative
# flag is inferred by omission, matching how the two actually interact.
NEGATIVE_FLAG_PAIRS = {"--no-fsl-deformable"}

# Human-readable URL fragment for the Preflight Results page (st.Page's
# url_path=, set in main()'s st.navigation() setup) -- st.switch_page()
# itself needs the actual Page object, not this string (see
# st.session_state["_preflight_page"], stashed by main()), but this still
# gives the page a stable, shareable URL.
PREFLIGHT_PAGE_URL_PATH = "preflight-results"

POSITIONAL_HELP = {
    "bids_dir": "Path to the BIDS dataset root.",
    "output_dir": "Path to write derivatives to.",
}

# Which CLI flags are relevant to each pipeline step, for the "Custom
# Pipeline" tab's per-step expanders. Hand-maintained against the real
# per-step `config.*` reads traced in mrsiprep/workflows/steps.py (and its
# callees). parser.py's own argparse groups now mirror this same per-step
# structure (one group per STEP_SEQUENCE step; see TAB_GROUPS below), but
# this dict is kept independently hand-maintained rather than derived from
# it, since a handful of flags are read by more than one step and an
# argparse group can only pick one primary home for each. In particular:
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
    "mrsi_load": ["--correct-mrsi-orientation", "--registration-backend", "--fsl-cost", "--ref-met"],
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


def _render_participants_widget(action: argparse.Action, bids_dir: str, key_prefix: str = "field_"):
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
    the Standardized tab's)."""
    label = _dest_label(action)
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


def _render_atlas_widget(action: argparse.Action, key_prefix: str = "field_"):
    """Dropdown of every bundled atlas actually found under mrsiprep/data/atlas/
    (instead of a free-text field defaulting to one hardcoded name), plus the
    parameterized synthetic choices --atlas also accepts (custom/schaefer<N>/
    mist197/cubic<N>mm).

    `key_prefix` isolates this widget's session-state keys from another
    caller rendering the same flag elsewhere (see _render_participants_widget)."""
    from mrsiprep.parcellation.atlas_registry import available_bundled_atlases

    bundled = available_bundled_atlases()
    synthetic = ["custom", "schaefer100", "schaefer400", "schaefer1000", "mist197", "cubic10mm"]
    options = bundled + synthetic + ["(custom value...)"]
    default = action.default if action.default in options else options[0]
    key = f"{key_prefix}{action.dest}"
    selected = st.selectbox(
        _dest_label(action), options, index=options.index(default),
        help=(action.help or "").strip(), key=key,
    )
    if selected == "(custom value...)":
        return st.text_input(
            f"{_dest_label(action)} (custom value)",
            help="e.g. 'schaefer200', 'cubic15mm', or another bundled/registered atlas name not listed above.",
            key=f"{key}_custom",
        ) or None
    return selected


def _widget_for(action: argparse.Action, key_prefix: str = "field_"):
    """`key_prefix` isolates this widget's session-state key from another
    caller rendering the same flag elsewhere -- the Custom Pipeline tab
    passes "custom_field_" so its per-step widgets never collide with the
    Standardized tab's widgets for the same flag."""
    label = _dest_label(action)
    help_text = (action.help or "").strip()
    key = f"{key_prefix}{action.dest}"

    if _is_flag(action):
        return st.checkbox(label, value=bool(action.default), help=help_text, key=key)

    if action.choices:
        choices = list(action.choices)
        if label == "--registration-backend":
            # The parser also accepts 'flirt-fnirt'/'flirt_fnirt'/'flirt/fnirt' as
            # deprecated spellings of 'fsl' (FNIRT is FSL's own deformable stage,
            # not a separate backend) -- the form only ever needs to offer 'fsl'.
            choices = ["ants", "fsl"]
        if label == "--normalization":
            # 'simple' and 'ants-syn' are behaviorally identical (both just
            # recompute using --registration-backend); 'ants-syn' only exists
            # for backward compatibility with older configs -- don't offer it
            # as if it were a meaningfully different third choice.
            choices = ["simple", "existing"]
        if action.nargs in ("+", "*"):
            default = action.default if isinstance(action.default, list) else []
            return st.multiselect(label, choices, default=default, help=help_text, key=key)
        options = ["(unset)"] + choices if not action.required else choices
        default = action.default if action.default in options else options[0]
        index = options.index(default)
        selected = st.selectbox(label, options, index=index, help=help_text, key=key)
        return None if selected == "(unset)" else selected

    if action.type is int:
        default = action.default if isinstance(action.default, int) else 0
        return st.number_input(label, value=default, step=1, help=help_text, key=key, format="%d")

    if action.type is float:
        default = action.default if isinstance(action.default, float) else 0.0
        return st.number_input(label, value=default, help=help_text, key=key)

    if action.nargs in ("+", "*"):
        default = ",".join(action.default) if isinstance(action.default, list) else ""
        raw = st.text_input(label, value=default, help=f"{help_text} (comma-separated)", key=key)
        return [v.strip() for v in raw.split(",") if v.strip()] or None

    default = "" if action.default in (None, argparse.SUPPRESS) else str(action.default)
    raw = st.text_input(label, value=default, help=help_text, key=key)
    return raw or None


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


# Argparse group titles combined under one tab each, in display order. A
# title not listed here falls into "Other" (see _tab_for_title). Each title
# here must match a parser.py add_argument_group(...) title exactly -- that
# parser now declares one group per pipeline step (mirroring STEP_SEQUENCE/
# the flowchart's branches), so this dict collapses the finer step groups
# back into the same coarser topic tabs this GUI has always shown.
TAB_GROUPS: dict[str, list[str]] = {
    "BIDS input": ["Prepare: input selection", "Workflow: step selection"],
    "Anatomical": ["Anatomical branch: tissue segmentation", "Anatomical branch: anatomical preparation"],
    "MRSI": [
        "MRSI branch: loading",
        "MRSI branch: spike filtering",
        "MRSI branch: T1 saturation correction",
        "MRSI branch: quality masking",
    ],
    "Registration": ["Shared: registration"],
    "Parcellation": ["parcellation"],
    "Connectivity": ["Outputs: regional profiles and connectivity"],
    "Workflow": ["Shared: tissue probability maps and PVC", "Outputs: resampling", "Workflow configuration"],
    "Overwrite / runtime": ["overwrite/recompute", "Other options"],
}


def _tab_for_title(title: str) -> str:
    for tab, titles in TAB_GROUPS.items():
        if title in titles:
            return tab
    return "Other"


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


def _render_command_builder_page() -> None:
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
    # Flags marked required=True (e.g. --metabolites, --ref-met) belong in the
    # "Required arguments" section, not buried in a tab.
    required_optionals = [a for a in optionals if a.required]
    other_optionals = [a for a in optionals if not a.required]

    # --parcellation-mode and --fs-license need to be known/rendered before
    # the rest of "Required arguments", since --fs-license is only mandatory
    # when chimera is selected -- pull both out of the normal options flow.
    parcellation_mode_action = next(a for a in other_optionals if _dest_label(a) == "--parcellation-mode")
    fs_license_action = next(a for a in other_optionals if _dest_label(a) == "--fs-license")
    chimera_scheme_action = next(a for a in other_optionals if _dest_label(a) == "--chimera-scheme")
    chimera_scale_action = next(a for a in other_optionals if _dest_label(a) == "--chimera-scale")
    chimera_grow_action = next(a for a in other_optionals if _dest_label(a) == "--chimera-grow")
    t1_pattern_action = next(a for a in other_optionals if _dest_label(a) == "--t1")
    participants_action = next(a for a in other_optionals if _dest_label(a) == "--participants")
    other_optionals = [
        a for a in other_optionals
        if _dest_label(a) not in (
            "--parcellation-mode", "--fs-license", "--mrsi-input-dir", "--t1", "--mrsinmrs-file", "--participants",
        )
    ]
    action_lookup = _flag_action_lookup(optionals)

    # Required arguments are shared by both modes below -- rendered once,
    # here, with a single set of widget keys, so filling them out doesn't
    # depend on (or get cleared by) which mode tab is active.
    positional_values, values, parcellation_mode = _render_required_args_section(
        positionals, required_optionals, optionals, parcellation_mode_action, fs_license_action,
        t1_pattern_action, participants_action,
        key_prefix="field_", show_preflight=True,
    )

    st.markdown("---")
    # One shared "Generated command" box above the mode switch, instead of
    # each tab rendering its own -- whichever mode is active fills this same
    # slot. Relies on the tabs below having state tracking enabled
    # (key=... + on_change="rerun"), which also makes only the active tab's
    # body run each time (lazy execution) -- otherwise both tabs would
    # execute every rerun and race to overwrite this one placeholder.
    st.header("Generated command")
    st.caption("Updates live as you fill in the form below. Copy and run it yourself -- this page never executes it.")
    command_slot = st.empty()

    st.markdown(
        "<style>"
        # Scoped to the .st-key-mode_select_tabs wrapper only (see the
        # st.container(key=...) below), so the Standardized tab's own
        # nested topic tabs (Registration/Parcellation/...) keep their
        # normal size -- only this top-level Standardized/Custom choice
        # is enlarged.
        ".st-key-mode_select_tabs div[data-testid='stTabs'] button[data-baseweb='tab'] p "
        "{font-size: 1.9rem; font-weight: 800;}"
        ".st-key-mode_select_tabs div[data-testid='stTabs'] button[data-baseweb='tab'] "
        "{padding: 1.1rem 2.2rem;}"
        "</style>",
        unsafe_allow_html=True,
    )
    with st.container(key="mode_select_tabs"):
        top_tabs = st.tabs(
            ["Standardized Pipeline", "Custom Pipeline"], key="mode_tabs", on_change="rerun",
        )
        with top_tabs[0]:
            if top_tabs[0].open:
                command = _render_standardized_pipeline_tab(
                    optionals, other_optionals, positional_values, dict(values), parcellation_mode,
                    chimera_scheme_action, chimera_scale_action, chimera_grow_action,
                )
                command_slot.code(command, language="bash")
        with top_tabs[1]:
            if top_tabs[1].open:
                command = _render_custom_pipeline_tab(
                    optionals, action_lookup, positional_values, dict(values),
                )
                command_slot.code(command, language="bash")


def _render_required_args_section(
    positionals: list[argparse.Action],
    required_optionals: list[argparse.Action],
    optionals: list[argparse.Action],
    parcellation_mode_action: argparse.Action,
    fs_license_action: argparse.Action,
    t1_pattern_action: argparse.Action,
    participants_action: argparse.Action,
    key_prefix: str = "field_",
    show_preflight: bool = True,
) -> tuple[dict, dict, str | None]:
    """Renders the "Required arguments" section (bids_dir/output_dir/
    mrsi_input_dir/--t1/--mrsinmrs-file/--participants/--metabolites/
    --ref-met/etc., plus the --parcellation-mode/--fs-license pair) shared
    by both the Standardized and Custom Pipeline tabs. `key_prefix` isolates
    each tab's copy's session-state keys (see _widget_for); `show_preflight`
    is off for the Custom tab, where the same file-presence checks would be
    redundant with the Standardized tab's own button.

    Returns (positional_values, values, parcellation_mode) -- the two dicts
    the caller keeps populating, plus the resolved --parcellation-mode value
    (needed by callers to gate mode-specific widgets further down)."""
    st.header("Required arguments")
    col1, chk1, col2, col3 = st.columns([4, 1, 4, 5])
    with col1:
        bids_dir = st.text_input("bids_dir", help=POSITIONAL_HELP.get("bids_dir", ""), key=f"{key_prefix}bids_dir_text")
    with chk1:
        _render_check(_path_check(bids_dir), "bids_dir must point to an existing folder")
    with col2:
        output_dir = st.text_input("output_dir", help=POSITIONAL_HELP.get("output_dir", ""), key=f"{key_prefix}output_dir_text")
    # --mrsi-input-dir accepts either a bids_dir-equivalent root or the
    # mrsi-<space> data folder itself (e.g. ".../derivatives/mrsi-orig") --
    # BIDSLayout normalizes either spelling to the same root
    # (mrsiprep/io/bids.py:_normalize_mrsi_input_dir), so the caption below
    # mirrors that same normalization rather than blindly appending
    # "derivatives/mrsi-orig" onto whatever was typed.
    with col3:
        mrsi_input_dir_custom_before = st.session_state.get(f"{key_prefix}mrsi_input_dir_custom", False)
        if not mrsi_input_dir_custom_before:
            # Disabled (auto-filled) mode: force-sync to bids_dir every rerun,
            # since the field is read-only here. Once custom mode is on, the
            # widget's own session-state (keyed below) takes over and must
            # NOT be overwritten by a `value=` on every rerun, or the user's
            # typed path would be reverted to bids_dir on every interaction.
            st.session_state[f"{key_prefix}mrsi_input_dir"] = bids_dir
        # Input, its "Custom path" checkbox, and a status check share one
        # sub-row instead of stacking, so this column's height matches
        # bids_dir/output_dir's single-line columns rather than making the
        # whole row taller.
        sub_input, sub_check, sub_mark = st.columns([3, 1, 1])
        with sub_input:
            mrsi_input_dir = st.text_input(
                "mrsi_input_dir",
                disabled=not mrsi_input_dir_custom_before,
                key=f"{key_prefix}mrsi_input_dir",
                help="Root folder with the raw MRSI derivatives. Either bids_dir's own kind of root, "
                "or the data folder itself (e.g. ending in 'derivatives/mrsi-orig') -- both are "
                "accepted. Leave unchecked to use bids_dir itself.",
            )
        with sub_check:
            st.markdown(
                "<div style='font-size:.72rem;font-weight:700;color:#58667d'>Custom Path</div>",
                unsafe_allow_html=True,
            )
            mrsi_input_dir_custom = st.checkbox(
                "Custom",
                value=mrsi_input_dir_custom_before,
                key=f"{key_prefix}mrsi_input_dir_custom",
                label_visibility="collapsed",
                help="Off by default, which keeps mrsi_input_dir the same as bids_dir -- the usual "
                "MRSIPrep convention. Check this only if the MRSI acquisition tree lives in a "
                "separate folder from bids_dir.",
            )
        effective_mrsi_input_dir = mrsi_input_dir if (mrsi_input_dir_custom and mrsi_input_dir) else bids_dir
        with sub_mark:
            _render_check(_path_check(effective_mrsi_input_dir), "The MRSI input root must exist")
    normalized_mrsi_root = str(_normalize_mrsi_input_dir(effective_mrsi_input_dir)) if effective_mrsi_input_dir else ""
    default_mrsi_data_dir = f"{normalized_mrsi_root}/derivatives/mrsi-orig" if normalized_mrsi_root else ""
    default_mrsinmrs_file = f"{default_mrsi_data_dir}/mrsinmrs.json" if default_mrsi_data_dir else ""
    if output_dir:
        st.caption(f"This will create a folder `{output_dir.rstrip('/')}/mrsiprep`.")
    if default_mrsi_data_dir:
        st.caption(f"This will load raw MRSI images from `{default_mrsi_data_dir}`.")

    analysis_level_action = next(a for a in positionals if a.dest == "analysis_level")
    col_analysis, col4, col5 = st.columns([1, 2, 2])
    with col_analysis:
        analysis_level = _widget_for(analysis_level_action, key_prefix=key_prefix)
    with col4:
        t1_pattern = st.text_input(
            "--t1",
            value=t1_pattern_action.default,
            help=t1_pattern_action.help,
            key=f"{key_prefix}t1_pattern_text",
        )
    with col5:
        mrsinmrs_file_custom_before = st.session_state.get(f"{key_prefix}mrsinmrs_file_custom", False)
        if not mrsinmrs_file_custom_before:
            st.session_state[f"{key_prefix}mrsinmrs_file"] = default_mrsinmrs_file
        sub_input2, sub_check2, sub_mark2 = st.columns([3, 1, 1])
        with sub_input2:
            mrsinmrs_file = st.text_input(
                "--mrsinmrs-file",
                disabled=not mrsinmrs_file_custom_before,
                key=f"{key_prefix}mrsinmrs_file",
            )
        with sub_check2:
            st.markdown(
                "<div style='font-size:.72rem;font-weight:700;color:#58667d'>Custom Path</div>",
                unsafe_allow_html=True,
            )
            mrsinmrs_file_custom = st.checkbox(
                "Custom",
                value=mrsinmrs_file_custom_before,
                key=f"{key_prefix}mrsinmrs_file_custom",
                label_visibility="collapsed",
                help="Off by default, which keeps --mrsinmrs-file at <mrsi_input_dir>/derivatives/"
                "mrsi-orig/mrsinmrs.json -- the usual MRSIPrep convention. Check this only if the "
                "acquisition metadata file lives somewhere else.",
            )
        with sub_mark2:
            effective_mrsinmrs_file = mrsinmrs_file if (mrsinmrs_file_custom and mrsinmrs_file) else default_mrsinmrs_file
            _render_check(_path_check(effective_mrsinmrs_file), "mrsinmrs.json must exist")
    # Fold the two path captions into one compact line instead of two,
    # and skip it entirely once neither path is known yet (nothing to show).
    path_notes = []
    if output_dir:
        path_notes.append(f"creates `{output_dir.rstrip('/')}/mrsiprep`")
    if default_mrsi_data_dir:
        path_notes.append(f"loads raw MRSI from `{default_mrsi_data_dir}`")
    if mrsinmrs_file_custom and mrsinmrs_file:
        path_notes.append(f"metadata from `{mrsinmrs_file}`")
    elif default_mrsinmrs_file:
        path_notes.append(f"metadata from `{default_mrsinmrs_file}`")
    if path_notes:
        st.caption(" &middot; ".join(path_notes), unsafe_allow_html=False)

    positional_values = {
        "bids_dir": bids_dir, "output_dir": output_dir, "analysis_level": analysis_level,
    }
    values_input_paths = {}
    if mrsi_input_dir_custom and mrsi_input_dir:
        values_input_paths["--mrsi-input-dir"] = mrsi_input_dir
    if mrsinmrs_file_custom and mrsinmrs_file:
        values_input_paths["--mrsinmrs-file"] = mrsinmrs_file
    for action in positionals:
        if action.dest in positional_values:
            continue
        positional_values[action.dest] = _widget_for(action, key_prefix=key_prefix)

    # --participants keeps its own row (it already packs input/checkbox/View
    # into one line internally -- see _render_participants_widget); nesting
    # it into a column here would leave too little width for its own
    # sub-columns. --metabolites/--ref-met/--parcellation-mode (and any
    # other required flag) instead share one packed row below it, rather
    # than each taking a full-width line of its own -- the single biggest
    # height saving in this section.
    participants_value = _render_participants_widget(participants_action, bids_dir, key_prefix=key_prefix)

    metabolites_action = next(a for a in required_optionals if _dest_label(a) == "--metabolites")
    other_required = [a for a in required_optionals if _dest_label(a) != "--metabolites"]
    # Each required selectbox/input gets a slightly wider column than its
    # checkmark, which only needs enough room for one glyph.
    col_widths = [3, 1] * (1 + len(other_required)) + [3]
    cols = st.columns(col_widths)
    col_m, chk_m, *rest_cols = cols
    with col_m:
        metabolites_value = _widget_for(metabolites_action, key_prefix=key_prefix)
    with chk_m:
        _render_check(bool(metabolites_value), "At least one metabolite is required")
    required_values = {}
    other_required_ok = True
    for i, action in enumerate(other_required):
        col, chk = rest_cols[2 * i], rest_cols[2 * i + 1]
        with col:
            value = _widget_for(action, key_prefix=key_prefix)
        required_values[_dest_label(action)] = value
        ok = bool(value)
        other_required_ok = other_required_ok and ok
        with chk:
            _render_check(ok, f"{_dest_label(action)} is required")
    with rest_cols[-1]:
        parcellation_mode = _widget_for(parcellation_mode_action, key_prefix=key_prefix)

    values: dict[str, object] = dict(values_input_paths)
    if participants_value:
        values[_dest_label(participants_action)] = participants_value
    values[_dest_label(t1_pattern_action)] = t1_pattern
    values[_dest_label(metabolites_action)] = metabolites_value
    values.update(required_values)
    values[_dest_label(parcellation_mode_action)] = parcellation_mode

    # Everything the Preflight button actually needs to run meaningfully:
    # the three path fields resolve to something that exists, plus both
    # required flags are filled in. --participants is excluded -- it has a
    # directory-scan fallback, so it's shown with a check but never gates
    # readiness.
    preflight_ready = (
        _path_check(bids_dir)
        and _path_check(effective_mrsi_input_dir)
        and _path_check(effective_mrsinmrs_file)
        and bool(metabolites_value)
        and other_required_ok
    )

    if show_preflight:
        # st.container(key=...) stamps a `.st-key-<key>` class on the
        # container's own wrapping div, giving the CSS below a stable
        # selector to center/enlarge the button in, and (when ready) to
        # color and pulse it -- without touching any other button on the
        # page (the Standardized/Custom tabs each render their own copy
        # with a distinct key_prefix, so the two containers never collide).
        wrap_key = f"{key_prefix}preflight_btn_wrap"
        css = (
            # Center by shrinking every wrapper div down to the button's own
            # width and auto-margining it, rather than relying on a flex
            # parent -- robust regardless of how many intermediate
            # Streamlit-internal wrapper divs sit between the keyed
            # container and the <button> itself.
            f".st-key-{wrap_key}, .st-key-{wrap_key} > div, .st-key-{wrap_key} [data-testid='stButton'] "
            f"{{width:fit-content !important;margin-left:auto !important;margin-right:auto !important;}}"
            f".st-key-{wrap_key} {{margin-top:14px;margin-bottom:4px;}}"
            f".st-key-{wrap_key} button {{min-width:300px;height:3.2rem;font-size:1.15rem;font-weight:800;}}"
        )
        if preflight_ready:
            css += (
                f".st-key-{wrap_key} button {{background:#1a7f37;border-color:#166e2e;color:white;"
                "animation:preflightPulse 1.8s ease-in-out infinite;}"
                f".st-key-{wrap_key} button:hover {{background:#176b2f;border-color:#166e2e;color:white;}}"
                "@keyframes preflightPulse{0%{box-shadow:0 0 0 0 rgba(26,127,55,.55);}"
                "70%{box-shadow:0 0 0 14px rgba(26,127,55,0);}100%{box-shadow:0 0 0 0 rgba(26,127,55,0);}}"
            )
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
        with st.container(key=wrap_key):
            run_preflight = st.button(
                "▶  Run preflight check" if preflight_ready else "Run preflight check",
                help="Checks the existence and validity of the input files (T1w, raw MRSI "
                "maps, mrsinmrs.json) for every recording matched above -- no Docker, no "
                "processing, nothing written to disk."
                + ("" if preflight_ready else " Fill in the checked fields above to enable this."),
                key=f"{key_prefix}run_preflight_btn",
            )
        if run_preflight:
            progress_bar = st.progress(0.0, text="Checking inputs...")

            def _update_progress(done, total, recording_id):
                progress_bar.progress(
                    done / total if total else 1.0,
                    text=f"Checking inputs... ({done}/{total}) {recording_id}",
                )

            st.session_state["preflight_result"] = _compute_preflight(
                positional_values, optionals, values, progress=_update_progress
            )
            progress_bar.empty()
            # Results live on their own navigable page (see main()'s
            # st.navigation/st.Page setup) rather than inline below the
            # form -- switch there now instead of scrolling down to them.
            st.switch_page(st.session_state["_preflight_page"])

    if parcellation_mode == "chimera":
        fs_license_action.required = True
        st.caption(
            "⚠️ `chimera` runs real FreeSurfer `recon-all` and needs a license -- fill in `--fs-license` below."
        )
        values[_dest_label(fs_license_action)] = _widget_for(fs_license_action, key_prefix=key_prefix)

    return positional_values, values, parcellation_mode


def _render_standardized_pipeline_tab(
    optionals: list[argparse.Action],
    other_optionals: list[argparse.Action],
    positional_values: dict,
    values: dict,
    parcellation_mode: str | None,
    chimera_scheme_action: argparse.Action,
    chimera_scale_action: argparse.Action,
    chimera_grow_action: argparse.Action,
) -> str:
    """Today's full-pipeline form: every flag grouped into topic tabs
    (Registration/Parcellation/Connectivity/Quality/Workflow/...), unchanged
    from before the Custom Pipeline tab was added. Required arguments
    (`positional_values`/`values`/`parcellation_mode`, including
    --participants) are rendered once in main() and shared with the Custom
    Pipeline tab, not re-rendered here. Returns the generated command string
    (the caller owns the shared "Generated command" box above the mode
    tabs and writes it there) rather than rendering its own copy."""
    # Preserve the parser's own argument_group order and titles, grouped into tabs.
    groups: dict[str, list[argparse.Action]] = {}
    for action in other_optionals:
        title = getattr(action.container, "title", None) or "Other options"
        groups.setdefault(title, []).append(action)

    tab_titles = list(TAB_GROUPS) + (["Other"] if any(_tab_for_title(t) == "Other" for t in groups) else [])
    tabs = st.tabs(tab_titles)

    for tab_name, tab in zip(tab_titles, tabs):
        with tab:
            group_titles = [t for t in groups if _tab_for_title(t) == tab_name]
            for title in group_titles:
                actions = groups[title]
                st.subheader(title)
                backend_choice = None
                for action in actions:
                    flag = _dest_label(action)

                    if flag == "--registration-backend":
                        backend_choice = _widget_for(action)
                        values[flag] = backend_choice
                        continue

                    if flag in BACKEND_SPECIFIC_FLAGS:
                        # Rendered right after the backend selectbox is known,
                        # further down this same tab -- skip here.
                        continue

                    if flag in ("--chimera-scheme", "--chimera-scale", "--chimera-grow"):
                        # Rendered together as the guided per-position picker,
                        # right after --parcellation-mode is known to be chimera
                        # -- skip the generic widgets here.
                        continue

                    if flag == "--fs-subjects-dir" and parcellation_mode != "chimera":
                        # Only relevant with --parcellation-mode chimera (reuses
                        # existing recon-all output instead of running it).
                        continue

                    if flag in ("--atlas", "--custom-atlas", "--custom-atlas-lut") and parcellation_mode != "atlas":
                        # Only relevant with --parcellation-mode atlas -- hidden
                        # under synthseg/chimera to keep the paths from blurring
                        # together (chimera has its own guided scheme picker below).
                        continue

                    if flag == "--atlas":
                        values[flag] = _render_atlas_widget(action)
                        continue

                    values[flag] = _widget_for(action)

                if backend_choice is not None:
                    # choices are "ants" or one of the fsl spellings
                    # ("fsl"/"flirt-fnirt"/"flirt_fnirt"/"flirt/fnirt").
                    wanted = ANTS_ONLY_FLAGS if backend_choice == "ants" else FSL_ONLY_FLAGS
                    for action in actions:
                        flag = _dest_label(action)
                        if flag in wanted:
                            values[flag] = _widget_for(action)

                if title == "parcellation" and parcellation_mode == "chimera":
                    st.markdown("**Chimera scheme** -- one atlas per supra-region, guided:")
                    code, scale, grow = _render_chimera_scheme_picker(
                        chimera_scheme_action, chimera_scale_action, chimera_grow_action
                    )
                    values["--chimera-scheme"] = code
                    values["--chimera-scale"] = scale
                    values["--chimera-grow"] = grow

    # Rendered after every topic-tab widget above so --no-filter/
    # --t1-correction are already resolved into `values` -- the flowchart
    # must reflect the form's actual current settings, not just the
    # required-args defaults it would see if rendered earlier.
    with st.expander("Pipeline flowchart (fixed 19-step order)", expanded=False):
        # CUSTOM_STEP_FLAGS' key order matches STEP_SEQUENCE's exactly (the
        # module-level assertion near its definition guarantees this stays
        # true) -- reused here rather than importing nodes.STEP_SEQUENCE,
        # which would pull in nipype just to list step names.
        _render_step_flowchart(list(CUSTOM_STEP_FLAGS), values)

    return _build_command(positional_values, optionals, values)


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


def _render_preflight_results_page() -> None:
    """Its own navigable page (st.navigation, see main()) rather than a
    block rendered inline at the bottom of the command-builder form --
    running the preflight check now switches here directly instead of
    scrolling the form page down to reveal the results."""
    st.title("Preflight Results")
    result = st.session_state.get("preflight_result")
    if result is None:
        st.info(
            "No preflight check has been run yet. Go to the Command Builder page, fill in the "
            "required arguments, and click **Run preflight check** once it lights up green."
        )
        return
    _render_preflight_result(result)


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
    builder_page = st.Page(_render_command_builder_page, title="Command Builder", icon=":material/terminal:", default=True)
    preflight_page = st.Page(
        _render_preflight_results_page, title="Preflight Results", icon=":material/fact_check:",
        url_path=PREFLIGHT_PAGE_URL_PATH,
    )
    # st.switch_page() needs the actual Page object, not its url_path string
    # (confirmed: passing a bare string raises StreamlitPageNotFoundError) --
    # stashed here since st.Page(...) is called with no arguments by
    # st.navigation's own dispatch, so _render_command_builder_page has no
    # other way to reach this run's Page instance.
    st.session_state["_preflight_page"] = preflight_page
    nav = st.navigation([builder_page, preflight_page])
    nav.run()


if __name__ == "__main__":
    main()
