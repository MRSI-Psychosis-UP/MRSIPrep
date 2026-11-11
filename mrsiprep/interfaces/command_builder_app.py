"""Streamlit form that assembles a runnable `mrsiprep-docker` command.

Auto-derived from the real CLI parser (mrsiprep.cli.parser.build_parser), so
the form's fields, choices, and defaults stay in sync with the actual CLI --
no second, hand-maintained copy of the 80+ flags to drift out of date. The
generated command uses the `mrsiprep-docker` host-side wrapper (see
docs/usage_basic.md), not `mrsiprep` directly -- mrsiprep itself only runs
inside the Docker image, not on the host.

This tool only builds and displays the command string; it never runs
anything itself (shelling out to `docker run` is out of scope for a
lightweight command-builder).

Run with:
    streamlit run mrsiprep/interfaces/command_builder_app.py
"""

from __future__ import annotations

import argparse
import shlex
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

# Debug/internal flags not useful in a user-facing form.
EXCLUDED_FLAGS = {"--hello-world", "--help", "-h"}

# store_true/store_false flag pairs sharing one dest (e.g. --fsl-deformable /
# --no-fsl-deformable): only the positive flag gets a widget; the negative
# flag is inferred by omission, matching how the two actually interact.
NEGATIVE_FLAG_PAIRS = {"--no-fsl-deformable"}

POSITIONAL_HELP = {
    "bids_dir": "Path to the BIDS dataset root.",
    "output_dir": "Path to write derivatives to.",
}


def _dest_label(action: argparse.Action) -> str:
    return action.option_strings[0] if action.option_strings else action.dest


def _is_flag(action: argparse.Action) -> bool:
    return action.nargs == 0


def _render_participants_widget(action: argparse.Action):
    """Text input for --participants plus a "View" button that previews the
    TSV/CSV's first rows, since a bad/mistyped subject-session list here
    silently filters out every subject rather than erroring loudly."""
    label = _dest_label(action)
    help_text = (action.help or "").strip()
    key = f"field_{action.dest}"
    path_str = st.text_input(label, value="", help=help_text, key=key)
    if path_str and st.button("View", key=f"{key}_view"):
        path = Path(path_str)
        if not path.exists():
            st.error(f"File not found: {path}")
        else:
            try:
                sep = "\t" if path.suffix.lower() == ".tsv" else None
                preview = pd.read_csv(path, sep=sep, engine="python", nrows=20)
                st.dataframe(preview)
            except Exception as exc:  # noqa: BLE001 -- best-effort preview, any parse error is shown as-is
                st.error(f"Could not preview {path}: {exc}")
    return path_str or None


# mrsiprep's own recommended --chimera-scheme default: not the same as each
# position's upstream-chimera "default" letter (several positions, e.g.
# Thalamus/Amygdala/Hippocampus/Hypothalamus/Brainstem, use a more specific
# FreeSurfer sub-parcellation instead of upstream's own plain Aseg default).
RECOMMENDED_CHIMERA_CODE = "LFMIHIFIFF"


def _render_chimera_scheme_picker(scheme_action: argparse.Action, scale_action: argparse.Action, grow_action: argparse.Action):
    """One dropdown per supra-region (instead of a raw 10-letter code), composing
    --chimera-scheme live; the cortex dropdown's scale/seg choices (e.g. Lausanne's
    1-5 vs. Schaefer's 100-1000) replace --chimera-scale's own generic widget,
    since valid values depend entirely on which cortical atlas is picked."""
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
        selected = cols[i % 5].selectbox(label, options, index=options.index(default_letter), format_func=fmt, key=f"chimera_{region}")
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
            key=f"chimera_scale_adaptive_{cortical_letter}",
        )
    else:
        st.caption(f"{cortical_info['name']} has no --chimera-scale resolution variants; --chimera-scale is ignored for this cortical choice.")

    grow_value = str(st.number_input(
        _dest_label(grow_action),
        value=int(grow_action.default),
        min_value=0,
        help=(grow_action.help or "").strip(),
        key="chimera_grow_adaptive",
    ))

    return code, scale_value, grow_value


def _render_atlas_widget(action: argparse.Action):
    """Dropdown of every bundled atlas actually found under mrsiprep/data/atlas/
    (instead of a free-text field defaulting to one hardcoded name), plus the
    parameterized synthetic choices --atlas also accepts (custom/schaefer<N>/
    mist197/cubic<N>mm)."""
    from mrsiprep.parcellation.atlas_registry import available_bundled_atlases

    bundled = available_bundled_atlases()
    synthetic = ["custom", "schaefer100", "schaefer400", "schaefer1000", "mist197", "cubic10mm"]
    options = bundled + synthetic + ["(custom value...)"]
    default = action.default if action.default in options else options[0]
    key = f"field_{action.dest}"
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


def _widget_for(action: argparse.Action):
    label = _dest_label(action)
    help_text = (action.help or "").strip()
    key = f"field_{action.dest}"

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


def _build_command(positional_values: dict, optionals: list[argparse.Action], values: dict) -> str:
    # mrsiprep itself only runs inside the Docker image -- mrsiprep-docker is
    # the host-side wrapper that builds and runs the equivalent `docker run`
    # for you, and is what every doc example (and pip install mrsiprep-docker)
    # expects the user to actually type.
    parts = [
        "mrsiprep-docker",
        shlex.quote(str(positional_values.get("bids_dir") or "<bids_dir>")),
        shlex.quote(str(positional_values.get("output_dir") or "<output_dir>")),
        "participant",
    ]

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
            parts.append(flag)
        elif isinstance(value, list):
            if isinstance(action.default, list) and sorted(value) == sorted(action.default):
                continue
            parts.append(flag)
            parts.extend(shlex.quote(str(v)) for v in value)
        else:
            if value == action.default:
                continue
            parts.append(flag)
            parts.append(shlex.quote(str(value)))

    return " ".join(parts)


# Argparse group titles combined under one tab each, in display order. A
# title not listed here falls into "Other" (see _tab_for_title).
TAB_GROUPS: dict[str, list[str]] = {
    "BIDS input": ["Options for filtering BIDS queries"],
    "Registration": ["Specific options for registrations"],
    "Parcellation": ["parcellation"],
    "Connectivity": ["connectivity"],
    "Quality": ["quality thresholds", "T1 saturation correction"],
    "Workflow": ["Options for performing only a subset of the workflow", "Workflow configuration"],
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


def main() -> None:
    st.set_page_config(page_title="MRSIPrep Command Builder", layout="wide")
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
    other_optionals = [
        a for a in other_optionals
        if _dest_label(a) not in ("--parcellation-mode", "--fs-license")
    ]

    st.header("Generated command")
    st.caption("Updates live as you fill in the form below. Copy and run it yourself -- this page never executes it.")
    command_slot = st.empty()

    st.header("Required arguments")
    col1, col2 = st.columns(2)
    with col1:
        bids_dir = st.text_input("bids_dir", help=POSITIONAL_HELP.get("bids_dir", ""))
    with col2:
        output_dir = st.text_input("output_dir", help=POSITIONAL_HELP.get("output_dir", ""))
    if output_dir:
        st.caption(f"This will create a folder `{output_dir.rstrip('/')}/mrsiprep`.")

    positional_values = {"bids_dir": bids_dir, "output_dir": output_dir}
    for action in positionals:
        if action.dest in positional_values:
            continue
        positional_values[action.dest] = _widget_for(action)

    values: dict[str, object] = {}
    for action in required_optionals:
        values[_dest_label(action)] = _widget_for(action)

    st.caption(
        "Tissue segmentation always runs via SynthSeg and never needs a FreeSurfer license. "
        "`--parcellation-mode` below only picks the region-labeling backend for connectivity/per-parcel "
        "output -- a separate concern."
    )
    parcellation_mode = _widget_for(parcellation_mode_action)
    values[_dest_label(parcellation_mode_action)] = parcellation_mode
    if parcellation_mode == "chimera":
        fs_license_action.required = True
        st.warning(
            "`chimera` runs real FreeSurfer `recon-all` and needs a license -- fill in `--fs-license` below.",
            icon="⚠️",
        )
        values[_dest_label(fs_license_action)] = _widget_for(fs_license_action)
    else:
        st.info(
            "No FreeSurfer license needed for this mode. `--fs-license` only becomes required if "
            "`--parcellation-mode` above is set to `chimera`.",
            icon="ℹ️",
        )

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

                    if flag == "--participants":
                        values[flag] = _render_participants_widget(action)
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

        # Keep the generated command live-updated as each tab's widgets are
        # filled in, without waiting for the full script rerun.
        command_slot.code(_build_command(positional_values, optionals, values), language="bash")

    command_slot.code(_build_command(positional_values, optionals, values), language="bash")


def launch() -> None:
    """Entry point for `mrsiprep-build-command` (see pyproject.toml): launches
    this script under `streamlit run` rather than calling main() directly,
    since Streamlit apps require its script-running machinery. Any extra
    arguments (e.g. --server.port 9000) are forwarded to `streamlit run`."""
    import sys

    from streamlit.web import cli as stcli

    sys.argv = ["streamlit", "run", __file__, *sys.argv[1:]]
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()
