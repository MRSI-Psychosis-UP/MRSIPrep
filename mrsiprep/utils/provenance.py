"""Provenance helpers."""

from __future__ import annotations

import json
import platform
import shutil
import sys
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import numpy as np
from rich import box
from rich.table import Table

from mrsiprep.utils.debug import Debug

try:
    from mrsiprep import __version__
except ImportError:
    try:
        __version__ = version("mrsiprep")
    except PackageNotFoundError:
        __version__ = "unknown"


class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):  # noqa: D401
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.generic):
            return obj.item()
        if isinstance(obj, Path):
            return str(obj)
        return super().default(obj)


def required_external_tools(config=None) -> list[str]:
    tools = ["antsRegistrationSyN.sh", "antsRegistration", "antsApplyTransforms", "N4BiasFieldCorrection", "mri_synthseg"]
    full = config is None or getattr(config, "processing_mode", "parc-con") == "parc-con"
    tissue_backend = getattr(config, "tissue_backend", "synthseg-fast") if config is not None else "synthseg-fast"
    if full and tissue_backend == "synthseg-fast":
        tools.append("fast")
    if full and (config is None or not getattr(config, "no_pvc", False)):
        tools.append("petpvc")
    if full and (config is None or getattr(config, "parcellation_mode", "chimera") == "chimera"):
        tools.extend(["chimera", "recon-all"])
    return list(dict.fromkeys(tools))


def software_versions(config=None) -> dict[str, str | None]:
    tools = required_external_tools(config)
    return {tool: shutil.which(tool) for tool in tools}


def check_external_software(debug: Debug, config=None) -> bool:
    statuses = software_versions(config)
    table = Table(box=box.SIMPLE_HEAVY, show_lines=False, title="External software availability")
    table.add_column("Tool", style="cyan", no_wrap=True)
    table.add_column("Path", style="white")
    table.add_column("Status", justify="center")

    all_available = True
    for tool, path in statuses.items():
        if path:
            table.add_row(tool, path, "[green]INSTALLED[/green]")
        else:
            table.add_row(tool, "[red]missing[/red]", "[bold red]MISSING[/bold red]")
            all_available = False

    debug.separator()
    debug.title("External software availability")
    debug.console.print(table)
    if all_available:
        debug.success("All required external binaries are available.")
    else:
        debug.failure("One or more required external binaries are missing.")
    return all_available


def pipeline_trace(config) -> list[dict]:
    """Which pipeline steps ran vs. were skipped for this config, and why.

    Derived purely from config flags (not recorded live), so it always stays
    in sync with the gating logic in workflows/participant.py's _step_*
    functions -- no state needs to be threaded through them to build this.
    """
    parc_con = config.processing_mode == "parc-con"
    mode_reason = f"mode={config.processing_mode}, requires parc-con"
    pvc_ran = parc_con and not config.no_pvc
    pvc_reason = "" if pvc_ran else (mode_reason if not parc_con else "--no-pvc")
    trace = [
        {"step": "Tissue segmentation", "ran": True, "reason": ""},
        {"step": "Anatomical preparation", "ran": True, "reason": ""},
        {"step": "MRSI preprocessing", "ran": True, "reason": ""},
        {"step": "MRSI-T1w-MNI registration", "ran": True, "reason": ""},
        {"step": "Tissue probability maps in MRSI space", "ran": parc_con, "reason": "" if parc_con else mode_reason},
        {"step": "Partial volume correction", "ran": pvc_ran, "reason": pvc_reason},
        {"step": "Resampling MRSI maps to T1w/MNI space", "ran": True, "reason": ""},
        {"step": "SynthSeg parcellation and QC", "ran": True, "reason": ""},
        {"step": "Parcellation (chimera/mni atlas)", "ran": parc_con, "reason": "" if parc_con else mode_reason},
        {"step": "Regional metabolite extraction", "ran": True, "reason": ""},
        {"step": "Connectivity", "ran": bool(config.write_connectivity), "reason": "" if config.write_connectivity else "--write-connectivity not set"},
        {"step": "Metprofiles export", "ran": parc_con, "reason": "" if parc_con else mode_reason},
        {"step": "Reports", "ran": True, "reason": ""},
    ]
    for entry in trace:
        entry["status"] = "RAN" if entry["ran"] else "SKIPPED"
    return trace


def write_provenance(config, out_path: str | Path, extra: dict | None = None) -> Path:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mrsiprep_version": __version__,
        "python": sys.version,
        "platform": platform.platform(),
        "config": config.to_dict() if hasattr(config, "to_dict") else {},
        "software": software_versions(config),
        "pipeline_trace": pipeline_trace(config),
    }
    if extra:
        payload.update(extra)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, cls=NumpyEncoder), encoding="utf-8")
    return out_path
