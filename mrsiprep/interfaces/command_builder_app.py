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

import streamlit as st

from mrsiprep.cli.parser import build_parser

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


def _widget_for(action: argparse.Action):
    label = _dest_label(action)
    help_text = (action.help or "").strip()
    key = f"field_{action.dest}"

    if _is_flag(action):
        return st.checkbox(label, value=bool(action.default), help=help_text, key=key)

    if action.choices:
        choices = list(action.choices)
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


def main() -> None:
    st.set_page_config(page_title="MRSIPrep Command Builder", layout="wide")
    st.title("MRSIPrep Command Builder")
    st.caption(
        "Builds a runnable `mrsiprep-docker` command from the actual CLI definition. "
        "This page does not execute anything -- copy the generated command and run it yourself."
    )

    parser = build_parser()
    positionals = [a for a in parser._actions if not a.option_strings and a.dest != "help"]
    optionals = [
        a for a in parser._actions
        if a.option_strings
        and _dest_label(a) not in EXCLUDED_FLAGS
        and _dest_label(a) not in NEGATIVE_FLAG_PAIRS
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

    st.header("Options")
    st.caption("Grouped to match the Read the Docs CLI reference; only changed values are included in the command.")

    # Preserve the parser's own argument_group order and titles.
    groups: dict[str, list[argparse.Action]] = {}
    for action in optionals:
        title = getattr(action.container, "title", None) or "Other options"
        groups.setdefault(title, []).append(action)

    values: dict[str, object] = {}
    for title, actions in groups.items():
        with st.expander(title, expanded=False):
            backend_choice = None
            for action in actions:
                flag = _dest_label(action)

                if flag == "--registration-backend":
                    backend_choice = _widget_for(action)
                    values[flag] = backend_choice
                    continue

                if flag in BACKEND_SPECIFIC_FLAGS:
                    # Rendered right after the backend selectbox is known,
                    # further down this same expander -- skip here.
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

        # Keep the generated command live-updated as each expander's
        # widgets are filled in, without waiting for the full script rerun.
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
