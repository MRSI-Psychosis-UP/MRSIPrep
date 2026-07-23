"""CLI parser for MRSIPrep."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import fields as _dataclass_fields
from pathlib import Path

from mrsiprep.config.defaults import QUALITY_DEFAULTS
from mrsiprep.config.settings import MRSIPrepConfig

PRESETS_DIR = Path(__file__).resolve().parent.parent / "config" / "presets"
_MRSIPREP_CONFIG_FIELDS = {f.name for f in _dataclass_fields(MRSIPrepConfig)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mrsiprep", description="Preprocess quantified whole-brain MRSI derivatives.")
    parser.add_argument("bids_dir", type=Path, help="The root folder of a BIDS valid dataset (sub-XXXXX folders at the top level).")
    parser.add_argument("output_dir", type=Path, help="The output path for MRSIPrep derivatives and reports.")
    parser.add_argument(
        "analysis_level",
        choices=["participant"],
        help="Processing stage to be run, only 'participant' in the case of MRSIPrep (see BIDS-Apps specification).",
    )

    selection = parser.add_argument_group("Options for filtering BIDS queries")
    selection.add_argument("--participant-label", nargs="+", default=[])
    selection.add_argument("--session-label", nargs="+", default=[])
    selection.add_argument("--participants", type=Path, default=None, help="TSV/CSV subject-session list.")
    selection.add_argument(
        "--bids-filter-file",
        type=Path,
        default=None,
        help="Path to a JSON file of PyBIDS-style entity filters used to select among ambiguous input candidates, "
        "e.g. {\"t1w\": {\"acquisition\": \"memprage\", \"run\": \"01\"}} to force a specific T1w acquisition/run "
        "when a session has more than one. Only the \"t1w\" key is currently supported.",
    )

    quality = parser.add_argument_group("quality thresholds")
    quality.add_argument(
        "--metabolites",
        type=_parse_comma_list,
        required=True,
        help="Comma-separated metabolite names to process, e.g. 'CrPCr,GluGln,GPCPCh,NAANAAG,Ins'.",
    )
    quality.add_argument("--quality-metrics", nargs="+", default=["snr", "linewidth", "crlb"])
    quality.add_argument("--snr-min", type=float, default=QUALITY_DEFAULTS["snr_min"])
    quality.add_argument("--linewidth-max", type=float, default=QUALITY_DEFAULTS["linewidth_max"])
    quality.add_argument("--crlb-max", type=float, default=QUALITY_DEFAULTS["crlb_max"])

    processing = parser.add_argument_group("Options for performing only a subset of the workflow")
    processing.add_argument(
        "--mode",
        "--processing-mode",
        dest="processing_mode",
        choices=["mni-norm", "parc-con", "midas"],
        default="mni-norm",
        help="Processing mode. 'midas' runs a MIDAS-faithful pipeline (Maudsley et al. 2006): fuzzy c-means "
        "tissue segmentation, PSF-convolved tissue fractions, rigid MRSI->T1 registration, and per-parcel "
        "Eq. 4 pure-GM/pure-WM regression instead of PETPVC.",
    )
    processing.add_argument(
        "--tissue-backend",
        choices=["synthseg-fast", "existing", "none"],
        default="synthseg-fast",
        help="Tissue segmentation backend for PVC. 'none' disables tissue segmentation and PVC entirely. "
        "Ignored in --mode midas, which always uses its own fuzzy c-means segmentation.",
    )

    registration = parser.add_argument_group("Specific options for registrations")
    registration.add_argument(
        "--registration-backend",
        choices=["ants", "fsl", "flirt-fnirt", "flirt_fnirt", "flirt/fnirt"],
        default="ants",
        help="Registration toolchain. 'ants' is the default; 'fsl'/'flirt-fnirt' uses FLIRT affine registration "
        "(no deformable stage -- FNIRT is not implemented).",
    )
    registration.add_argument(
        "--ants-mrsi-to-t1-transform",
        default="sr",
        help="ANTs transform preset/code for MRSI-to-T1w registration. Default matches the previous implementation: 'sr'.",
    )
    registration.add_argument(
        "--ants-t1-to-mni-transform",
        default="s",
        help="ANTs transform preset/code for T1w-to-MNI registration. Default matches the previous implementation: 's'.",
    )
    registration.add_argument("--fsl-mrsi-to-t1-dof", type=int, choices=[6, 7, 9, 12], default=6)
    registration.add_argument(
        "--fsl-mrsi-to-t1-init",
        choices=["flirt", "usesqform"],
        default="flirt",
        help="FSL MRSI-to-T1w initialization. 'usesqform' applies the NIfTI qform/sform geometry with FLIRT.",
    )
    registration.add_argument("--fsl-t1-to-mni-dof", type=int, choices=[6, 7, 9, 12], default=12)
    registration.add_argument("--fsl-cost", default="mutualinfo", help="FLIRT cost function for FSL registrations.")
    registration.add_argument("--normalization", choices=["simple", "ants-syn", "existing"], default="simple")
    registration.add_argument("--output-spaces", nargs="+", default=["MNI152NLin2009cAsym"])
    registration.add_argument(
        "--output-mrsi-t1w",
        action="store_true",
        help="Also resample all metabolite (and CRLB/SNR/FWHM/spikemask) maps into T1w space as permanent "
        "derivatives (mrsi-t1w/). Off by default; the registration-overview report generates its own single "
        "reference-metabolite T1w map in the work directory regardless of this flag.",
    )
    registration.add_argument(
        "--mni-resolution",
        default="t1wres",
        help="MNI template resolution: 'origres' (MRSI native), 't1wres' (T1w native), or '<N>mm' (e.g. '2mm').",
    )
    registration.add_argument("--registration-t1-target", choices=["brain-csf", "brain", "raw"], default=None)
    registration.add_argument("--csf-pv-threshold", type=float, default=0.95)
    registration.add_argument(
        "--ref-met",
        required=True,
        help="Reference metabolite map used to build the MRSI registration target, e.g. 'CrPCr'.",
    )
    registration.add_argument("--t1", dest="t1_pattern", default="desc-brain_T1w")

    parcellation = parser.add_argument_group("parcellation")
    parcellation.add_argument("--parcellation-mode", choices=["synthseg", "chimera", "mni"], default=None)
    parcellation.add_argument("--synthseg-mode", choices=["fast", "standard", "robust"], default="robust")
    parcellation.add_argument("--chimera-scheme", default="LFMIHIFIFF")
    parcellation.add_argument("--chimera-scale", type=_parse_scale, default=3)
    parcellation.add_argument("--chimera-grow", type=int, default=2)
    parcellation.add_argument("--atlas", default="chimera-LFMIHIFIS-3")
    parcellation.add_argument("--custom-atlas", type=Path, default=None)
    parcellation.add_argument("--custom-atlas-lut", type=Path, default=None)
    parcellation.add_argument("--fs-subjects-dir", type=Path, default=None)

    connectivity = parser.add_argument_group("connectivity")
    connectivity.add_argument("--write-connectivity", action="store_true")
    connectivity.add_argument("--connectivity-method", choices=["pearson", "spearman", "cosine", "euclidean_distance"], default="spearman")
    connectivity.add_argument("--connectivity-space", choices=["MRSI", "T1w", "MNI"], default="MRSI")
    connectivity.add_argument("--connectivity-n-perturbations", type=int, default=50, help="Number of CRLB-scaled noise perturbations per metabolite used to build the connectivity similarity matrix.")
    connectivity.add_argument("--connectivity-sigma-scale", type=float, default=2.0, help="Scale factor applied to the CRLB-derived noise sigma when perturbing metabolite maps for connectivity.")
    connectivity.add_argument(
        "--connectivity-exclude-parcels",
        default=None,
        help="Comma-separated substrings; parcels whose name contains any of them are excluded from the connectivity matrix (e.g. 'wm-lh,cer-').",
    )
    connectivity.add_argument(
        "--connectivity-max-parcel-id",
        type=int,
        default=None,
        help="Exclude parcels whose label/ID is greater than or equal to this value from the connectivity matrix.",
    )
    connectivity.add_argument("--regional-summary", choices=["mean", "median", "weighted_mean"], default="mean")

    processing_control = parser.add_argument_group("Workflow configuration")
    processing_control.add_argument("--transform", default="", help="Legacy output transform override; prefer --output-spaces.")
    processing_control.add_argument("--no-filter", action="store_true", help="Disable biharmonic spike filtering (enabled by default in every processing mode).")
    processing_control.add_argument(
        "--filter-fwhm-mm",
        type=float,
        default=None,
        help="Smoothing FWHM (mm) used when splicing repaired biharmonic-filter voxels back in. "
        "Default: derived from the native MRSI voxel size (mean voxel dimension x sqrt(2)).",
    )
    processing_control.add_argument("--spikepc", type=float, default=99.0)
    processing_control.add_argument("--no-pvc", action="store_true")
    processing_control.add_argument(
        "--longitudinal",
        action="store_true",
        help="Build one unbiased ANTs template across a subject's sessions and register it to MNI once, "
        "composing (session-to-template)+(template-to-MNI) instead of registering each session directly to MNI. "
        "No-op for subjects with a single session. Requires --registration-backend ants.",
    )
    processing_control.add_argument("--transform-spikemask", action="store_true", help="Also transform per-metabolite spike masks into T1w/MNI space.")
    processing_control.add_argument("--nthreads", type=int, default=16, help="ANTs/ITK thread count per subject/session process.")
    processing_control.add_argument(
        "--nproc",
        type=int,
        default=1,
        help="Number of subject/session recordings to process in parallel. Each parallel process gets --nthreads threads; "
        "if nproc*nthreads exceeds the available CPU count, --nthreads is coerced down and a warning is shown at startup.",
    )
    processing_control.add_argument("--work-dir", "-w", type=Path, default=None)

    overwrite = parser.add_argument_group("overwrite/recompute")
    overwrite.add_argument("--overwrite", action="store_true")
    overwrite.add_argument("--overwrite-filt", action="store_true")
    overwrite.add_argument("--overwrite-seg", action="store_true", help="Force recompute of tissue segmentation (SynthSeg brain extraction + dseg/probseg), even if cached outputs exist.")
    overwrite.add_argument("--overwrite-pve", action="store_true")
    overwrite.add_argument("--overwrite-t1-reg", action="store_true")
    overwrite.add_argument("--overwrite-mni-reg", action="store_true")
    overwrite.add_argument("--overwrite-transform", action="store_true")
    overwrite.add_argument("--overwrite-chimera", action="store_true", help="Force re-run Chimera parcellation even if the output dseg file already exists.")

    runtime = parser.add_argument_group("Other options")
    runtime.add_argument(
        "--config-preset",
        default=None,
        help="Load processing-parameter defaults from a named built-in preset (see --list-presets) or a path to a "
        "custom preset JSON file with the same shape. Explicit CLI flags always override preset values. Presets "
        "reproduce the exact parameters of a published study; the report's Citations section credits the source.",
    )
    runtime.add_argument(
        "--list-presets",
        action="store_true",
        help="Print available built-in --config-preset names and their source citation, then exit.",
    )
    runtime.add_argument("--validate-only", action="store_true", help="Check selected subject/session inputs and exit without running preprocessing.")
    runtime.add_argument(
        "--skip-file-integrity-check",
        action="store_true",
        help="Skip forcing a full read of T1w/MRSI input files during preflight validation (existence-only checks instead). "
        "By default every run force-reads these files first and skips any recording with a missing or corrupt/truncated input.",
    )
    runtime.add_argument("--check-external-libs", action="store_true", help="Verify required external binaries are available and exit.")
    runtime.add_argument(
        "--stop-on-first-crash",
        action="store_true",
        help="Abort the whole run immediately on the first recording failure, instead of logging it and continuing with the rest of the batch.",
    )
    runtime.add_argument(
        "--verbose",
        "-v",
        type=int,
        choices=[0, 1, 2, 3],
        default=1,
        help="0=subject start/finish only, 1=+processing steps, 2=+step details, 3=+raw ANTs/recon-all/mri_synthseg output.",
    )
    return parser


def list_presets() -> dict[str, dict]:
    """Built-in preset name -> parsed preset dict (including _citation)."""
    presets = {}
    for path in sorted(PRESETS_DIR.glob("*.json")):
        presets[path.stem] = json.loads(path.read_text())
    return presets


def load_preset(name_or_path: str) -> dict:
    """Load a preset by built-in name or filesystem path.

    Returns the raw parsed dict, including the reserved "_citation" key
    (callers are responsible for stripping it before using the rest as
    MRSIPrepConfig field defaults).
    """
    builtin = PRESETS_DIR / f"{name_or_path}.json"
    path = builtin if builtin.exists() else Path(name_or_path)
    if not path.exists():
        available = ", ".join(sorted(list_presets())) or "(none)"
        raise ValueError(f"Unknown --config-preset '{name_or_path}'. Built-in presets: {available}")
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not parse --config-preset {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"--config-preset {path} must contain a JSON object at the top level.")
    return data


def print_presets() -> None:
    presets = list_presets()
    if not presets:
        print("No built-in presets available.")
        return
    for name, data in presets.items():
        citation = data.get("_citation", {})
        text = citation.get("text") or citation.get("label", "")
        doi = citation.get("doi")
        suffix = f" (doi:{doi})" if doi else ""
        print(f"{name}: {text}{suffix}")


def parse_args(argv: list[str] | None = None) -> MRSIPrepConfig:
    argv = list(sys.argv[1:] if argv is None else argv)

    preset_parser = argparse.ArgumentParser(add_help=False)
    preset_parser.add_argument("--config-preset", default=None)
    preset_args, _ = preset_parser.parse_known_args(argv)

    parser = build_parser()
    if preset_args.config_preset:
        preset = dict(load_preset(preset_args.config_preset))
        citation = preset.pop("_citation", None)
        unknown = set(preset) - _MRSIPREP_CONFIG_FIELDS
        if unknown:
            raise ValueError(f"--config-preset '{preset_args.config_preset}' has unsupported field(s): {sorted(unknown)}")
        parser.set_defaults(**preset)
        # argparse's `required=True` checks whether the option string was seen
        # on the command line, not whether a value is present -- set_defaults()
        # alone does not satisfy it. The preset already supplies a value, so
        # relax `required` for exactly the fields it covers.
        for action in parser._actions:
            if action.dest in preset:
                action.required = False
    else:
        citation = None

    args = parser.parse_args(argv)
    config = MRSIPrepConfig(
        bids_dir=args.bids_dir,
        output_dir=args.output_dir,
        analysis_level=args.analysis_level,
        participant_label=args.participant_label,
        session_label=args.session_label,
        participants_file=args.participants,
        bids_filter_file=args.bids_filter_file,
        metabolites=args.metabolites,
        quality_metrics=args.quality_metrics,
        snr_min=args.snr_min,
        linewidth_max=args.linewidth_max,
        crlb_max=args.crlb_max,
        processing_mode=args.processing_mode,
        tissue_backend=args.tissue_backend,
        registration_backend=args.registration_backend,
        ants_mrsi_to_t1_transform=args.ants_mrsi_to_t1_transform,
        ants_t1_to_mni_transform=args.ants_t1_to_mni_transform,
        fsl_mrsi_to_t1_dof=args.fsl_mrsi_to_t1_dof,
        fsl_mrsi_to_t1_init=args.fsl_mrsi_to_t1_init,
        fsl_t1_to_mni_dof=args.fsl_t1_to_mni_dof,
        fsl_cost=args.fsl_cost,
        normalization=args.normalization,
        output_spaces=args.output_spaces,
        output_mrsi_t1w=args.output_mrsi_t1w,
        mni_resolution=args.mni_resolution,
        registration_t1_target=args.registration_t1_target,
        csf_pv_threshold=args.csf_pv_threshold,
        ref_met=args.ref_met,
        t1_pattern=args.t1_pattern,
        parcellation_mode=args.parcellation_mode,
        synthseg_mode=args.synthseg_mode,
        chimera_scheme=args.chimera_scheme,
        chimera_scale=args.chimera_scale,
        chimera_grow=args.chimera_grow,
        atlas=args.atlas,
        custom_atlas=args.custom_atlas,
        custom_atlas_lut=args.custom_atlas_lut,
        fs_subjects_dir=args.fs_subjects_dir,
        write_connectivity=args.write_connectivity,
        connectivity_method=args.connectivity_method,
        connectivity_space=args.connectivity_space,
        connectivity_n_perturbations=args.connectivity_n_perturbations,
        connectivity_sigma_scale=args.connectivity_sigma_scale,
        connectivity_exclude_parcels=args.connectivity_exclude_parcels,
        connectivity_max_parcel_id=args.connectivity_max_parcel_id,
        regional_summary=args.regional_summary,
        transform=args.transform,
        filter_biharmonic=not args.no_filter,
        filter_fwhm_mm=args.filter_fwhm_mm,
        spike_percentile=args.spikepc,
        no_pvc=args.no_pvc,
        longitudinal=args.longitudinal,
        transform_spikemask=args.transform_spikemask,
        nthreads=args.nthreads,
        nproc=args.nproc,
        work_dir=args.work_dir,
        overwrite=args.overwrite,
        overwrite_filt=args.overwrite_filt,
        overwrite_seg=args.overwrite_seg,
        overwrite_pve=args.overwrite_pve,
        overwrite_t1_reg=args.overwrite_t1_reg,
        overwrite_mni_reg=args.overwrite_mni_reg,
        overwrite_transform=args.overwrite_transform,
        overwrite_chimera=args.overwrite_chimera,
        validate_only=args.validate_only,
        skip_file_integrity_check=args.skip_file_integrity_check,
        check_external_libs=args.check_external_libs,
        stop_on_first_crash=args.stop_on_first_crash,
        verbose=args.verbose,
    )
    config.preset_citation = citation
    return config


def _parse_comma_list(value: str) -> list[str]:
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _parse_scale(value) -> int:
    text = str(value)
    if text.startswith("scale"):
        text = text[len("scale") :]
    return int(text)
