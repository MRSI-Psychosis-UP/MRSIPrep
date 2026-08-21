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
    selection.add_argument(
        "--participant-label",
        nargs="+",
        default=[],
        help="One or more subject labels to process, without the 'sub-' prefix (e.g. 'S001 S002'). "
        "Default: process every subject found under --bids-dir.",
    )
    selection.add_argument(
        "--session-label",
        nargs="+",
        default=[],
        help="One or more session labels to process, without the 'ses-' prefix (e.g. 'V1 V2'). "
        "Default: process every session found for each selected subject.",
    )
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
    quality.add_argument(
        "--quality-metrics",
        nargs="+",
        default=["snr", "linewidth", "crlb"],
        choices=["snr", "linewidth", "crlb"],
        help="Which per-voxel quality maps are required inputs (any of 'snr', 'linewidth', 'crlb'); a "
        "recording missing one of the listed maps fails preflight validation. Default: all three. Maps "
        "that are present are always applied as voxel-inclusion thresholds regardless of this flag (see "
        "--snr-min/--linewidth-max/--crlb-max); this flag only controls whether their absence is an error.",
    )
    quality.add_argument(
        "--snr-min",
        type=float,
        default=QUALITY_DEFAULTS["snr_min"],
        help="Minimum per-voxel SNR to include a voxel, when 'snr' is in --quality-metrics.",
    )
    quality.add_argument(
        "--linewidth-max",
        type=float,
        default=QUALITY_DEFAULTS["linewidth_max"],
        help="Maximum per-voxel linewidth (FWHM) to include a voxel, when 'linewidth' is in --quality-metrics.",
    )
    quality.add_argument(
        "--crlb-max",
        type=float,
        default=QUALITY_DEFAULTS["crlb_max"],
        help="Maximum per-voxel Cramér-Rao lower bound (%%) to include a voxel, when 'crlb' is in --quality-metrics.",
    )

    t1_correction = parser.add_argument_group("T1 saturation correction")
    t1_correction.add_argument(
        "--t1-correction",
        choices=["none", "literature"],
        default="none",
        help="Correct metabolite maps for incomplete T1 relaxation recovery (T1 saturation) using the "
        "steady-state spoiled-gradient-echo signal equation (default: 'none', no correction applied). "
        "'literature' applies a single scalar correction factor per metabolite, derived from the "
        "acquisition's TR/flip angle (read from mrsinmrs.json) and a curated literature T1 value per "
        "metabolite per field strength (see mrsiprep/config/t1_literature.json). Requires a dataset-level "
        "mrsinmrs.json with unambiguous TR/FlipAngle/MagneticFieldStrength entries -- fails loudly, "
        "per-recording, if these or a requested metabolite's T1 value are missing, rather than silently "
        "skipping or substituting. A future 'voxelwise' mode (per-voxel correction using a measured B1+ "
        "map) is planned but not yet implemented; mrsiprep does not currently ingest B1+ maps.",
    )
    t1_correction.add_argument(
        "--t1-correction-water-status",
        choices=["uncorrected", "corrected", "unknown"],
        default="unknown",
        help="Whether the input metabolite maps are already water-referenced/water-T1-corrected upstream "
        "(e.g. by the quantification pipeline's own internal water-scaling step). 'unknown' (default, "
        "conservative) applies the metabolite-T1-only correction and flags the ambiguity in the QC/"
        "provenance output. Ignored when --t1-correction none.",
    )
    t1_correction.add_argument(
        "--overwrite-t1corr",
        action="store_true",
        help="Force recomputation of T1-corrected maps even if cached outputs exist.",
    )

    processing = parser.add_argument_group("Options for performing only a subset of the workflow")
    processing.add_argument(
        "--tissue-backend",
        choices=["synthseg-fast", "existing", "none"],
        default="synthseg-fast",
        help="Tissue segmentation backend for PVC. 'none' disables tissue segmentation and PVC entirely.",
    )

    registration = parser.add_argument_group("Specific options for registrations")
    registration.add_argument(
        "--registration-backend",
        choices=["ants", "fsl", "flirt-fnirt", "flirt_fnirt", "flirt/fnirt"],
        default="ants",
        help="Registration toolchain. 'ants' is the default and generally most accurate (rigid+affine+SyN). "
        "'fsl'/'flirt-fnirt' uses FLIRT+FNIRT (deformable) for MRSI-to-T1w by default; pass --no-fsl-deformable "
        "for FLIRT-only (faster, less accurate).",
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
    registration.add_argument(
        "--fsl-mrsi-to-t1-dof",
        type=int,
        choices=[6, 7, 9, 12],
        default=6,
        help="FLIRT degrees of freedom for MRSI-to-T1w registration: 6=rigid, 7=rigid+global scale, "
        "9=rigid+per-axis scale, 12=full affine. Default 6 (rigid), appropriate for the low-resolution "
        "MRSI reference map.",
    )
    registration.add_argument(
        "--fsl-mrsi-to-t1-init",
        choices=["flirt", "usesqform"],
        default="flirt",
        help="FSL MRSI-to-T1w initialization. 'usesqform' applies the NIfTI qform/sform geometry with FLIRT and no "
        "further optimization. 'flirt' (default) seeds FLIRT from that same qform/sform frame, then runs a local "
        "(no-search) optimization from it -- FLIRT's own unrestricted global search was found to reliably diverge "
        "on MRSI-reference-vs-T1w registration and is not offered.",
    )
    registration.add_argument(
        "--fsl-t1-to-mni-dof",
        type=int,
        choices=[6, 7, 9, 12],
        default=12,
        help="FLIRT degrees of freedom for T1w-to-MNI registration: 6=rigid, 7=rigid+global scale, "
        "9=rigid+per-axis scale, 12=full affine. Default 12 (full affine), appropriate for inter-subject "
        "spatial normalization.",
    )
    registration.add_argument(
        "--fsl-cost",
        default="corratio",
        help="FLIRT cost function for FSL registrations. Default changed from FLIRT's own 'mutualinfo' default to "
        "'corratio': mutualinfo was found to diverge on the small, low-contrast MRSI reference maps used for "
        "MRSI-to-T1w registration.",
    )
    registration.add_argument(
        "--fsl-deformable",
        dest="fsl_deformable",
        action="store_true",
        default=True,
        help="Add an FNIRT deformable stage after FLIRT for the fsl MRSI-to-T1w registration, to more closely "
        "mimic ANTs' default SyN warp. On by default when --registration-backend fsl is selected (confirmed to "
        "give consistently better MRSI-brainmask/T1w-brain overlap than FLIRT-only across a 3T and a 7T subject, "
        "see experiments/registration_backend_benchmark.py); pass --no-fsl-deformable for FLIRT-only (faster, "
        "seconds instead of several minutes per subject). Has no effect on --registration-backend ants.",
    )
    registration.add_argument(
        "--no-fsl-deformable",
        dest="fsl_deformable",
        action="store_false",
        help="Use FLIRT-only for the fsl MRSI-to-T1w registration (no FNIRT deformable stage). See --fsl-deformable.",
    )
    registration.add_argument(
        "--fsl-fnirt-warpres",
        type=int,
        nargs=3,
        metavar=("X", "Y", "Z"),
        default=None,
        help="FNIRT --warpres (B-spline control-point grid spacing, mm) for the fsl-deformable MRSI-to-T1w stage. "
        "Default: auto-computed as ~2x the MRSI reference image's own native voxel size per axis, floored at 6mm "
        "(a higher-resolution MRSI acquisition can support a finer deformation grid without just fitting noise; "
        "validated at warpres=10mm for 5mm MRSI data -- see mrsiprep.interfaces.fsl.default_fnirt_warpres). Pass "
        "three values (e.g. --fsl-fnirt-warpres 6 6 6) to override.",
    )
    registration.add_argument(
        "--fsl-fnirt-lambda",
        default="300,200,150,150",
        help="FNIRT --lambda regularization-weight schedule for the fsl-deformable MRSI-to-T1w stage.",
    )
    registration.add_argument(
        "--normalization",
        choices=["simple", "ants-syn", "existing"],
        default="simple",
        help="Legacy T1w-to-MNI normalization strategy (superseded by --registration-backend for new code; "
        "kept for backward compatibility). 'simple' registers via the backend selected by "
        "--registration-backend. 'ants-syn' forces ANTs SyN regardless of --registration-backend. "
        "'existing' reuses a previously computed T1w-to-MNI transform instead of recomputing it.",
    )
    registration.add_argument(
        "--output-spaces",
        nargs="+",
        default=["MNI152NLin2009cAsym"],
        help="One or more target spaces to resample final MRSI derivatives into. Accepts case-insensitive "
        "aliases: 'mni'/'mni152'/'mni152nlin2009casym' (MNI152NLin2009cAsym, default), 't1'/'t1w' (T1w space, "
        "equivalent to also passing --output-mrsi-t1w), 'mrsi'/'orig' (native MRSI grid). See "
        "docs/usage_normalization.md.",
    )
    registration.add_argument(
        "--output-mrsi-t1w",
        action="store_true",
        help="Also resample all metabolite (and CRLB/SNR/FWHM/spikemask) maps into T1w space as permanent "
        "derivatives (mrsi-t1w/). Off by default; the registration-overview report generates its own single "
        "reference-metabolite T1w map in the work directory regardless of this flag.",
    )
    registration.add_argument(
        "--mni-resolution",
        default="origres",
        help="MNI template resolution: 'origres' (MRSI native, default -- avoids implying spatial precision "
        "the MRSI acquisition never had, and matches the resolution mrsiprep's own spatial-smoothness "
        "benchmark evaluates), 't1wres' (T1w native), or '<N>mm' (e.g. '2mm').",
    )
    registration.add_argument(
        "--registration-t1-target",
        choices=["brain-csf", "brain", "raw"],
        default=None,
        help="Which T1w image registration targets. 'brain' registers directly to the skull-stripped T1w "
        "(default when --parcellation-mode synthseg). 'brain-csf' re-adds the CSF compartment to the "
        "skull-stripped image before registering, so CSF-adjacent MRSI signal isn't clipped at the "
        "brain-only boundary (default when --parcellation-mode chimera or atlas; requires a CAT12 p3 CSF "
        "map). 'raw' registers to the original, non-skull-stripped T1w with no fixed mask.",
    )
    registration.add_argument(
        "--csf-pv-threshold",
        type=float,
        default=0.95,
        help="CSF partial-volume probability threshold used when building the 'brain-csf' registration "
        "target: voxels with CAT12 p3 CSF probability at or above this value are added back to the "
        "skull-stripped brain image.",
    )
    registration.add_argument(
        "--ref-met",
        required=True,
        help="Reference metabolite map used to build the MRSI registration target, e.g. 'CrPCr'.",
    )
    registration.add_argument(
        "--t1",
        dest="t1_pattern",
        default="desc-brain_T1w",
        help="BIDS entity/suffix pattern used to locate the skull-stripped T1w derivative for each "
        "recording (e.g. 'desc-brain_T1w', or 'acq-mprage_T1w' to select among multiple raw T1w "
        "acquisitions -- see --bids-filter-file for finer-grained disambiguation).",
    )

    parcellation = parser.add_argument_group("parcellation")
    parcellation.add_argument(
        "--parcellation-mode",
        choices=["synthseg", "chimera", "atlas"],
        default="synthseg",
        help="Parcellation scheme, and the primary switch for how much of the pipeline runs. 'synthseg' "
        "(default) uses SynthSeg's own cortical/subcortical labels for parcellation, needs no FreeSurfer "
        "recon-all, and is the lighter-weight default (see --registration-t1-target). 'chimera' runs the "
        "Chimera multi-atlas fusion tool live, combining several region-specific atlases per "
        "--chimera-scheme (requires FreeSurfer recon-all and FS_LICENSE). 'atlas' warps a pre-bundled or "
        "custom standardized MNI-space atlas (see --atlas) into subject space instead of running Chimera. "
        "Regional metabolite extraction, per-parcel metabolite-profile export, and CRLB-scaled Monte Carlo "
        "profile estimation all run unconditionally regardless of this flag's value -- 'chimera'/'atlas' "
        "additionally run that parcellation step itself on top of SynthSeg's own parcellation, which "
        "always runs for QC. See --write-connectivity for the optional connectivity matrix.",
    )
    parcellation.add_argument(
        "--synthseg-mode",
        choices=["fast", "standard", "robust"],
        default="robust",
        help="mri_synthseg inference mode, trading speed for accuracy/robustness: 'fast' (quickest, "
        "lower-memory), 'standard', or 'robust' (default; most accurate but the most memory-hungry -- can "
        "exceed 16GB RAM on some inputs, consider 'fast' on memory-constrained runners).",
    )
    parcellation.add_argument(
        "--chimera-scheme",
        default="LFMIHIFIFF",
        help="10-character Chimera parcellation code, one letter per supra-region in order: cortex, basal "
        "ganglia, thalamus, amygdala, hippocampus, hypothalamus, cerebellum, brainstem, gyral WM, WM. "
        "Default 'LFMIHIFIFF' = Lausanne cortex, FreeSurfer/Aseg subcortex/cerebellum/WM, MIALThalParc "
        "thalamus, FSAmygHippoParc amygdala, HBT hippocampus, FSHypoThalParc hypothalamus, FSBrainStemParc "
        "brainstem. See the Chimera documentation for the full per-position letter set. Accepts a "
        "comma-separated list (e.g. 'LFMIHIFIFF,LFMIHIFIS') to build several parcellations in one run; "
        "see --chimera-scale for how the lists combine.",
    )
    parcellation.add_argument(
        "--chimera-scale",
        default="3",
        help="Lausanne2018 cortical parcellation granularity (1-5; higher = more, finer parcels), used only "
        "when --chimera-scheme's cortex position is 'L'. Accepts a bare integer or 'scaleN'. Also accepts a "
        "comma-separated list (e.g. '1,3'), which is combined with --chimera-scheme and --chimera-grow as a "
        "cross product -- '--chimera-scheme A,B --chimera-scale 1,3' builds four parcellations. Every "
        "parcellation gets its own regional table, metabolite profiles, and connectivity outputs, all off a "
        "single shared preprocessing pass. Schemes whose cortex position isn't 'L' aren't multi-resolution, "
        "so they yield one parcellation regardless of how many scales are listed.",
    )
    parcellation.add_argument(
        "--chimera-grow",
        default="2",
        help="Distance (mm) to grow cortical/subcortical gray-matter parcel labels into adjacent white "
        "matter when building the gyral-WM parcellation. Set to 0 to disable growing. Accepts a "
        "comma-separated list, combined as a cross product with --chimera-scheme/--chimera-scale.",
    )
    parcellation.add_argument(
        "--atlas",
        default="chimera-LFMIHIFIS_scale3",
        help="Atlas used when --parcellation-mode atlas. One of: a bundled atlas name (see "
        "mrsiprep.parcellation.atlas_registry.available_bundled_atlases(), e.g. 'chimera-LFMIHIFIS_scale3'); "
        "'custom' (requires --custom-atlas and --custom-atlas-lut); 'schaefer<N>' for the Schaefer 2018 "
        "N-parcel cortical atlas (e.g. 'schaefer400'); or 'mist197'/'mist-197' for the BASC multiscale "
        "atlas at scale 197. Accepts a comma-separated list to project several atlases in one run.",
    )
    parcellation.add_argument(
        "--custom-atlas",
        type=Path,
        default=None,
        help="Path to a custom MNI-space atlas NIfTI (integer parcel-ID label image). Requires "
        "--atlas custom and --custom-atlas-lut.",
    )
    parcellation.add_argument(
        "--custom-atlas-lut",
        type=Path,
        default=None,
        help="Path to the lookup table (TSV) for --custom-atlas. Must have a 'parcel_id' column (or legacy "
        "'index') matching the label image's integer values; optional 'parcel_name' ('name') and "
        "'hemisphere' columns (hemisphere is inferred from the name if omitted).",
    )
    parcellation.add_argument(
        "--fs-subjects-dir",
        type=Path,
        default=None,
        help="FreeSurfer SUBJECTS_DIR to reuse pre-existing recon-all output from, instead of running "
        "recon-all inside MRSIPrep. Only relevant with --parcellation-mode chimera.",
    )

    connectivity = parser.add_argument_group("connectivity")
    connectivity.add_argument(
        "--write-connectivity",
        action="store_true",
        help="Build and write a regional metabolic connectivity (similarity) matrix on top of the "
        "regional metabolic profiles that mrsiprep already computes unconditionally for every recording, "
        "using CRLB-scaled noise perturbations to estimate edge similarity between parcels' metabolite profiles.",
    )
    connectivity.add_argument(
        "--connectivity-method",
        choices=["pearson", "spearman", "cosine", "euclidean_distance"],
        default="spearman",
        help="Similarity/distance measure between parcels' perturbed metabolite profiles used to build "
        "connectivity edges: 'pearson' or 'spearman' correlation, 'cosine' similarity, or "
        "'euclidean_distance'.",
    )
    connectivity.add_argument(
        "--connectivity-space",
        choices=["MRSI", "T1w", "MNI"],
        default="MRSI",
        help="Space the regional metabolite profiles are extracted in before building the connectivity "
        "matrix: native MRSI grid (default), T1w space, or MNI space.",
    )
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
    connectivity.add_argument(
        "--regional-summary",
        choices=["mean", "median", "weighted_mean"],
        default="mean",
        help="How each parcel's per-voxel metabolite values are summarized into a single regional value: "
        "'mean', 'median', or 'weighted_mean' (SNR-weighted average; falls back to an unweighted mean if no "
        "SNR map is available for that recording).",
    )

    processing_control = parser.add_argument_group("Workflow configuration")
    processing_control.add_argument("--transform", default="", help="Legacy output transform override; prefer --output-spaces.")
    processing_control.add_argument("--no-filter", action="store_true", help="Disable biharmonic spike filtering (enabled by default).")
    processing_control.add_argument(
        "--filter-fwhm-mm",
        type=float,
        default=None,
        help="Smoothing FWHM (mm) used when splicing repaired biharmonic-filter voxels back in. "
        "Default: derived from the native MRSI voxel size (mean voxel dimension x sqrt(2)).",
    )
    processing_control.add_argument(
        "--spikepc",
        type=float,
        default=99.0,
        help="Percentile threshold (0-100) above which a voxel is flagged as a spike for biharmonic "
        "filtering/repair. Ignored when --no-filter is set.",
    )
    processing_control.add_argument(
        "--spike-max-cluster-voxels",
        type=int,
        default=None,
        help="A connected cluster of spike-thresholded voxels larger than this is treated as real focal "
        "signal (e.g. a genuine metabolic abnormality) and left unfiltered, rather than median-repaired/"
        "biharmonic-inpainted like an isolated noise spike. Default: derived from the native MRSI voxel "
        "size (6 voxels at ~5.0mm/3T-like resolution, 9 voxels at ~3.4mm/7T-like resolution, empirically "
        "the 90th-percentile spike-cluster size measured on real acquisitions at each resolution). Set to "
        "a very large number to disable cluster-size filtering (every above-threshold voxel is filtered "
        "regardless of cluster size, matching pre-existing behavior).",
    )
    processing_control.add_argument(
        "--spike-extreme-zscore",
        type=float,
        default=4.0,
        help="Safety net on top of --spike-max-cluster-voxels: a cluster larger than the size cap is still "
        "repaired (rather than exempted as real focal signal) if its mean intensity is an implausible "
        "outlier -- a z-score (against the map's own inside-brain mean/std) above this value. On real data, "
        "large spike clusters are just as likely as small ones to be extreme intensity outliers (acquisition "
        "artifacts, typically near the FOV/slab edge), which the size cap alone would otherwise leave "
        "unfiltered and visibly distort the report's display scale. Default 4.0. Set to a very large number "
        "or a negative value has no safety effect (nothing exceeds it); pass a value close to 0 to make the "
        "safety net dominate the size cap entirely.",
    )
    processing_control.add_argument(
        "--no-pvc",
        action="store_true",
        help="Skip partial-volume correction (PETPVC) entirely. Equivalent to --tissue-backend none, "
        "except tissue segmentation itself still runs (its maps are just not used for PVC).",
    )
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
    processing_control.add_argument(
        "--work-dir",
        "-w",
        type=Path,
        default=None,
        help="Directory for the Nipype engine's node cache and scratch/intermediate files. Default: "
        "<output_dir>/work. Safe to delete between runs to reclaim space; permanent derivatives under "
        "<output_dir>/mrsiprep/ are unaffected, though deleting it invalidates the rerun-skip cache for "
        "already-processed recordings.",
    )

    overwrite = parser.add_argument_group("overwrite/recompute")
    overwrite.add_argument(
        "--overwrite",
        action="store_true",
        help="Force recompute of every cached step for selected recordings, ignoring the Nipype node cache "
        "entirely. Equivalent to passing all of the --overwrite-* flags below at once.",
    )
    overwrite.add_argument(
        "--overwrite-filt",
        action="store_true",
        help="Force recompute of biharmonic spike filtering, even if cached filtered maps exist.",
    )
    overwrite.add_argument("--overwrite-seg", action="store_true", help="Force recompute of tissue segmentation (SynthSeg brain extraction + dseg/probseg), even if cached outputs exist.")
    overwrite.add_argument(
        "--overwrite-pve",
        action="store_true",
        help="Force recompute of partial-volume correction (PETPVC), even if cached corrected maps exist.",
    )
    overwrite.add_argument(
        "--overwrite-t1-reg",
        action="store_true",
        help="Force recompute of MRSI-to-T1w registration, even if a cached transform exists.",
    )
    overwrite.add_argument(
        "--overwrite-mni-reg",
        action="store_true",
        help="Force recompute of T1w-to-MNI registration, even if a cached transform exists.",
    )
    overwrite.add_argument(
        "--overwrite-transform",
        action="store_true",
        help="Force recompute of resampling MRSI maps through existing transforms into output spaces, even "
        "if cached resampled maps exist. Does not itself force-recompute the transforms -- see "
        "--overwrite-t1-reg/--overwrite-mni-reg.",
    )
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
        "--reports-only",
        action="store_true",
        help="Skip recomputation of already-completed steps (tissue segmentation, registration, parcellation, etc. "
        "are reused as-is when their output derivatives already exist) and only rewrite QC tables, figures, and "
        "HTML reports. Fails a recording with a clear error, rather than silently recomputing, if a required "
        "upstream derivative (e.g. registration transforms) is missing.",
    )
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
        tissue_backend=args.tissue_backend,
        registration_backend=args.registration_backend,
        ants_mrsi_to_t1_transform=args.ants_mrsi_to_t1_transform,
        ants_t1_to_mni_transform=args.ants_t1_to_mni_transform,
        fsl_mrsi_to_t1_dof=args.fsl_mrsi_to_t1_dof,
        fsl_mrsi_to_t1_init=args.fsl_mrsi_to_t1_init,
        fsl_t1_to_mni_dof=args.fsl_t1_to_mni_dof,
        fsl_cost=args.fsl_cost,
        fsl_deformable=args.fsl_deformable,
        fsl_fnirt_warpres=tuple(args.fsl_fnirt_warpres) if args.fsl_fnirt_warpres else None,
        fsl_fnirt_lambda=args.fsl_fnirt_lambda,
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
        spike_max_cluster_voxels=args.spike_max_cluster_voxels,
        spike_extreme_zscore=args.spike_extreme_zscore,
        no_pvc=args.no_pvc,
        t1_correction=args.t1_correction,
        t1_correction_water_status=args.t1_correction_water_status,
        overwrite_t1corr=args.overwrite_t1corr,
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
        reports_only=args.reports_only,
        skip_file_integrity_check=args.skip_file_integrity_check,
        check_external_libs=args.check_external_libs,
        stop_on_first_crash=args.stop_on_first_crash,
        verbose=args.verbose,
    )
    config.preset_citation = citation
    return config


def _parse_comma_list(value: str) -> list[str]:
    return [item.strip() for item in str(value).split(",") if item.strip()]
