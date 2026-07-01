"""CLI parser for MRSIPrep."""

from __future__ import annotations

import argparse
from pathlib import Path

from mrsiprep.config.defaults import METABOLITES_3T, METABOLITES_7T, QUALITY_DEFAULTS
from mrsiprep.config.settings import MRSIPrepConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mrsiprep", description="Preprocess quantified whole-brain MRSI derivatives.")
    parser.add_argument("bids_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("analysis_level", choices=["participant"])

    selection = parser.add_argument_group("subject/session selection")
    selection.add_argument("--participant-label", nargs="+", default=[])
    selection.add_argument("--session-label", nargs="+", default=[])
    selection.add_argument("--participants", type=Path, default=None, help="TSV/CSV subject-session list.")

    quality = parser.add_argument_group("quality thresholds")
    quality.add_argument("--b0", type=float, default=3.0, choices=[3.0, 7.0])
    quality.add_argument("--metabolites", nargs="+", default=None)
    quality.add_argument("--quality-metrics", nargs="+", default=["snr", "linewidth", "crlb"])
    quality.add_argument("--snr-min", type=float, default=QUALITY_DEFAULTS["snr_min"])
    quality.add_argument("--linewidth-max", type=float, default=QUALITY_DEFAULTS["linewidth_max"])
    quality.add_argument("--crlb-max", type=float, default=QUALITY_DEFAULTS["crlb_max"])

    processing = parser.add_argument_group("processing mode")
    processing.add_argument("--mode", "--processing-mode", dest="processing_mode", choices=["mni-norm", "parc-con"], default="mni-norm")
    processing.add_argument(
        "--tissue-backend",
        choices=["synthseg-fast", "existing", "none"],
        default="synthseg-fast",
        help="Tissue segmentation backend for PVC. 'none' disables tissue segmentation and PVC entirely.",
    )

    registration = parser.add_argument_group("registration and normalization")
    registration.add_argument("--registration-backend", choices=["ants"], default="ants")
    registration.add_argument("--normalization", choices=["simple", "ants-syn", "existing"], default="simple")
    registration.add_argument("--output-spaces", nargs="+", default=["T1w", "MNI152NLin2009cAsym"])
    registration.add_argument(
        "--mni-resolution",
        default="t1wres",
        help="MNI template resolution: 'origres' (MRSI native), 't1wres' (T1w native), or '<N>mm' (e.g. '2mm').",
    )
    registration.add_argument("--registration-t1-target", choices=["brain-csf", "brain", "raw"], default=None)
    registration.add_argument("--csf-pv-threshold", type=float, default=0.95)
    registration.add_argument("--ref-met", default="CrPCr")
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

    processing_control = parser.add_argument_group("processing control")
    processing_control.add_argument("--transform", default="", help="Legacy output transform override; prefer --output-spaces.")
    processing_control.add_argument("--no-filter", action="store_true")
    processing_control.add_argument("--spikepc", type=float, default=99.0)
    processing_control.add_argument("--no-pvc", action="store_true")
    processing_control.add_argument("--proc-mnilong", action="store_true")
    processing_control.add_argument("--transform-spikemask", action="store_true", help="Also transform per-metabolite spike masks into T1w/MNI space.")
    processing_control.add_argument("--nthreads", type=int, default=16, help="ANTs/ITK thread count per subject/session process.")
    processing_control.add_argument(
        "--nproc",
        type=int,
        default=1,
        help="Number of subject/session recordings to process in parallel. Each parallel process gets --nthreads threads; "
        "if nproc*nthreads exceeds the available CPU count, --nthreads is coerced down and a warning is shown at startup.",
    )
    processing_control.add_argument("--work-dir", type=Path, default=None)

    overwrite = parser.add_argument_group("overwrite/recompute")
    overwrite.add_argument("--overwrite", action="store_true")
    overwrite.add_argument("--overwrite-filt", action="store_true")
    overwrite.add_argument("--overwrite-seg", action="store_true", help="Force recompute of tissue segmentation (SynthSeg brain extraction + dseg/probseg), even if cached outputs exist.")
    overwrite.add_argument("--overwrite-pve", action="store_true")
    overwrite.add_argument("--overwrite-t1-reg", action="store_true")
    overwrite.add_argument("--overwrite-mni-reg", action="store_true")
    overwrite.add_argument("--overwrite-transform", action="store_true")

    runtime = parser.add_argument_group("runtime")
    runtime.add_argument("--validate-only", action="store_true", help="Check selected subject/session inputs and exit without running preprocessing.")
    runtime.add_argument("--check-external-libs", action="store_true", help="Verify required external binaries are available and exit.")
    runtime.add_argument(
        "--verbose",
        "-v",
        type=int,
        choices=[0, 1, 2, 3],
        default=1,
        help="0=subject start/finish only, 1=+processing steps, 2=+step details, 3=+raw ANTs/recon-all/mri_synthseg output.",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> MRSIPrepConfig:
    args = build_parser().parse_args(argv)
    metabolites = args.metabolites
    if metabolites is None:
        metabolites = list(METABOLITES_7T if args.b0 == 7.0 else METABOLITES_3T)
    return MRSIPrepConfig(
        bids_dir=args.bids_dir,
        output_dir=args.output_dir,
        analysis_level=args.analysis_level,
        participant_label=args.participant_label,
        session_label=args.session_label,
        participants_file=args.participants,
        b0=args.b0,
        metabolites=metabolites,
        quality_metrics=args.quality_metrics,
        snr_min=args.snr_min,
        linewidth_max=args.linewidth_max,
        crlb_max=args.crlb_max,
        processing_mode=args.processing_mode,
        tissue_backend=args.tissue_backend,
        registration_backend=args.registration_backend,
        normalization=args.normalization,
        output_spaces=args.output_spaces,
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
        spike_percentile=args.spikepc,
        no_pvc=args.no_pvc,
        proc_mnilong=args.proc_mnilong,
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
        validate_only=args.validate_only,
        check_external_libs=args.check_external_libs,
        verbose=args.verbose,
    )


def _parse_scale(value) -> int:
    text = str(value)
    if text.startswith("scale"):
        text = text[len("scale") :]
    return int(text)
