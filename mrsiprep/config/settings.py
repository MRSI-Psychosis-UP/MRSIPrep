"""Runtime configuration objects."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from .defaults import QUALITY_DEFAULTS


@dataclass
class MRSIPrepConfig:
    bids_dir: Path
    output_dir: Path
    analysis_level: str
    participant_label: list[str] = field(default_factory=list)
    session_label: list[str] = field(default_factory=list)
    participants_file: Path | None = None
    bids_filter_file: Path | None = None
    metabolites: list[str] | None = None
    quality_metrics: list[str] = field(default_factory=lambda: ["snr", "linewidth", "crlb"])
    snr_min: float = QUALITY_DEFAULTS["snr_min"]
    linewidth_max: float = QUALITY_DEFAULTS["linewidth_max"]
    crlb_max: float = QUALITY_DEFAULTS["crlb_max"]
    tissue_backend: str = "synthseg-fast"
    registration_backend: str = "ants"
    ants_mrsi_to_t1_transform: str = "sr"
    ants_t1_to_mni_transform: str = "s"
    fsl_mrsi_to_t1_dof: int = 6
    fsl_mrsi_to_t1_init: str = "flirt"
    fsl_t1_to_mni_dof: int = 12
    fsl_cost: str = "corratio"
    fsl_deformable: bool = True
    fsl_fnirt_warpres: tuple[int, int, int] | None = None
    fsl_fnirt_lambda: str = "300,200,150,150"
    normalization: str = "simple"
    output_spaces: list[str] = field(default_factory=lambda: ["MNI152NLin2009cAsym"])
    output_mrsi_t1w: bool = False
    mni_resolution: str = "origres"
    registration_t1_target: str | None = None
    csf_pv_threshold: float = 0.95
    parcellation_mode: str = "synthseg"
    synthseg_mode: str = "robust"
    # Comma-separated lists are accepted on all four, matching Chimera's own
    # --parcodes/--scale/--growwm syntax: every combination is built in a
    # single run. Stored as given (str or int) so to_dict()/presets/provenance
    # round-trip unchanged; read them through the accessors below.
    chimera_scheme: str = "LFMIHIFIS"
    chimera_scale: str | int = 3
    chimera_grow: str | int = 2
    atlas: str = "chimera-LFMIHIFIS_scale3"
    custom_atlas: Path | None = None
    custom_atlas_lut: Path | None = None
    fs_subjects_dir: Path | None = None
    write_connectivity: bool = False
    connectivity_method: str = "spearman"
    connectivity_space: str = "MRSI"
    connectivity_n_perturbations: int = 50
    connectivity_sigma_scale: float = 2.0
    connectivity_exclude_parcels: str | None = None
    connectivity_max_parcel_id: int | None = None
    regional_summary: str = "mean"
    nthreads: int = 16
    nproc: int = 1
    ref_met: str | None = None
    t1_pattern: str = "desc-brain_T1w"
    transform: str = ""
    filter_biharmonic: bool = True
    filter_fwhm_mm: float | None = None
    spike_percentile: float = 99.0
    spike_max_cluster_voxels: int | None = None
    spike_extreme_zscore: float | None = 4.0
    no_pvc: bool = False
    t1_correction: str = "none"
    t1_correction_water_status: str = "unknown"
    overwrite_t1corr: bool = False
    longitudinal: bool = False
    transform_spikemask: bool = False
    overwrite: bool = False
    overwrite_filt: bool = False
    overwrite_seg: bool = False
    overwrite_pve: bool = False
    overwrite_t1_reg: bool = False
    overwrite_mni_reg: bool = False
    overwrite_transform: bool = False
    overwrite_chimera: bool = False
    work_dir: Path | None = None
    verbose: int = 1
    validate_only: bool = False
    reports_only: bool = False
    skip_file_integrity_check: bool = False
    check_external_libs: bool = False
    stop_on_first_crash: bool = False
    preset_citation: dict | None = None

    def _validate_required_fields(self) -> None:
        if not self.metabolites:
            raise ValueError("--metabolites is required (comma-separated list, e.g. 'CrPCr,GluGln,GPCPCh,NAANAAG,Ins').")
        if not self.ref_met:
            raise ValueError("--ref-met is required (reference metabolite used to build the MRSI registration target).")

    def _resolve_paths(self) -> None:
        from mrsiprep.io.bids import load_bids_filters
        from mrsiprep.io.mrsinmrs import load_mrsinmrs

        self.bids_dir = Path(self.bids_dir).resolve()
        self.output_dir = Path(self.output_dir).resolve()
        if self.bids_filter_file is not None:
            self.bids_filter_file = Path(self.bids_filter_file).resolve()
        self.bids_filters = load_bids_filters(self.bids_filter_file)
        self.mrsinmrs = load_mrsinmrs(self.bids_dir)
        self.output_spaces = _normalize_output_spaces(self.output_spaces)
        self.work_dir = Path(self.work_dir).resolve() if self.work_dir is not None else self.output_dir / "work"
        if self.fs_subjects_dir is not None:
            self.fs_subjects_dir = Path(self.fs_subjects_dir).resolve()

    def _validate_enum_choices(self) -> None:
        if self.parcellation_mode not in {"synthseg", "chimera", "atlas"}:
            raise ValueError(f"Unsupported parcellation mode: {self.parcellation_mode}")
        if self.synthseg_mode not in {"fast", "standard", "robust"}:
            raise ValueError(f"Unsupported SynthSeg mode: {self.synthseg_mode}")
        if self.tissue_backend not in {"synthseg-fast", "existing", "none"}:
            raise ValueError(f"Unsupported tissue backend: {self.tissue_backend}")
        if self.t1_correction not in {"none", "literature"}:
            raise ValueError(f"Unsupported --t1-correction: {self.t1_correction}")
        if self.t1_correction_water_status not in {"uncorrected", "corrected", "unknown"}:
            raise ValueError(f"Unsupported --t1-correction-water-status: {self.t1_correction_water_status}")
        self._validate_parcellation_lists()

    def _validate_parcellation_lists(self) -> None:
        """Validate the comma-separated parcellation options.

        Only meaningful for the mode that actually consumes them, so a
        synthseg run isn't rejected for a stale chimera value it never reads.
        """
        if self.parcellation_mode == "chimera":
            # Code *content* is Chimera's own business to validate -- lengths
            # vary in practice (mrsiprep's own default 'LFMIHIFIS' is 9), so
            # only the list shape is checked here.
            if not self.chimera_schemes():
                raise ValueError("--chimera-scheme must name at least one parcellation code.")
            try:
                scales = self.chimera_scales()
            except ValueError as exc:
                raise ValueError(f"--chimera-scale must be integers (or 'scaleN'): {self.chimera_scale!r}") from exc
            if not scales:
                raise ValueError("--chimera-scale must name at least one scale.")
            for scale in scales:
                if not 1 <= scale <= 5:
                    raise ValueError(f"--chimera-scale must be between 1 and 5, got {scale}")
            try:
                grows = self.chimera_grows()
            except ValueError as exc:
                raise ValueError(f"--chimera-grow must be integers (mm): {self.chimera_grow!r}") from exc
            if not grows:
                raise ValueError("--chimera-grow must name at least one distance.")
            if any(grow < 0 for grow in grows):
                raise ValueError(f"--chimera-grow must not be negative: {self.chimera_grow!r}")
        elif self.parcellation_mode == "atlas" and not self.atlases():
            raise ValueError("--atlas must name at least one atlas.")

    def _validate_registration_backend(self) -> None:
        if self.registration_backend in {"flirt/fnirt", "flirt_fnirt", "flirt-fnirt"}:
            self.registration_backend = "fsl"
        if self.registration_backend not in {"ants", "fsl"}:
            raise ValueError(f"Unsupported registration backend: {self.registration_backend}")
        if self.registration_backend == "fsl" and self.longitudinal:
            raise ValueError("--longitudinal currently requires --registration-backend ants.")
        if self.fsl_mrsi_to_t1_dof not in {6, 7, 9, 12}:
            raise ValueError("--fsl-mrsi-to-t1-dof must be one of 6, 7, 9, or 12.")
        if self.fsl_mrsi_to_t1_init not in {"flirt", "usesqform"}:
            raise ValueError("--fsl-mrsi-to-t1-init must be 'flirt' or 'usesqform'.")
        if self.fsl_t1_to_mni_dof not in {6, 7, 9, 12}:
            raise ValueError("--fsl-t1-to-mni-dof must be one of 6, 7, 9, or 12.")

    def _resolve_derived_defaults(self) -> None:
        if self.tissue_backend == "none":
            self.no_pvc = True
        if self.registration_t1_target is None:
            # brain-csf is also safe under synthseg parcellation: SynthSeg
            # always parcellates the raw T1w directly, independent of
            # registration_t1w/registration_t1_target, so there is no
            # coupling between the registration target and synthseg
            # parcellation that would make brain-csf unsafe here -- brain
            # just remains the lighter-weight default.
            self.registration_t1_target = "brain" if self.parcellation_mode == "synthseg" else "brain-csf"

    def _validate_registration_t1_target(self) -> None:
        if self.registration_t1_target not in {"brain", "raw", "brain-csf"}:
            raise ValueError(f"Unsupported registration target: {self.registration_t1_target}")

    def __post_init__(self) -> None:
        self._validate_required_fields()
        self._resolve_paths()
        self._validate_enum_choices()
        self._validate_registration_backend()
        self._resolve_derived_defaults()
        self._validate_registration_t1_target()
        self.nproc = max(1, int(self.nproc))
        self.nthreads = max(1, int(self.nthreads))

    def resolve_cpu_budget(self) -> tuple[int, int, str | None]:
        """Coerce nproc*nthreads to the available CPU count.

        Returns (nproc, nthreads, warning) where warning is set (and nthreads
        reduced) if the requested total thread budget exceeds the machine's
        CPU count.
        """
        import os

        cpu_count = os.cpu_count() or 1
        requested_total = self.nproc * self.nthreads
        if requested_total <= cpu_count:
            return self.nproc, self.nthreads, None
        coerced_nthreads = max(1, cpu_count // self.nproc)
        warning = (
            f"--nproc {self.nproc} x --nthreads {self.nthreads} = {requested_total} threads exceeds "
            f"{cpu_count} available CPUs; coercing --nthreads to {coerced_nthreads} "
            f"({self.nproc} x {coerced_nthreads} = {self.nproc * coerced_nthreads})."
        )
        return self.nproc, coerced_nthreads, warning

    @property
    def derivative_dir(self) -> Path:
        return self.output_dir if self.output_dir.name == "mrsiprep" else self.output_dir / "mrsiprep"

    @property
    def logs_dir(self) -> Path:
        return self.derivative_dir / "logs"

    @property
    def freesurfer_dir(self) -> Path:
        if self.fs_subjects_dir is not None:
            return self.fs_subjects_dir
        return self.output_dir / "freesurfer"

    def chimera_schemes(self) -> list[str]:
        """Chimera parcellation codes requested, in order."""
        return _split_multi(self.chimera_scheme)

    def chimera_scales(self) -> list[int]:
        """Lausanne scales requested, in order. Accepts 'scaleN' as well as N."""
        return [_parse_scale_token(token) for token in _split_multi(self.chimera_scale)]

    def chimera_grows(self) -> list[int]:
        """Gyral-WM growth distances (mm) requested, in order."""
        return [int(token) for token in _split_multi(self.chimera_grow)]

    def atlases(self) -> list[str]:
        """Bundled/custom MNI atlas names requested, in order."""
        return _split_multi(self.atlas)

    def to_dict(self) -> dict:
        out = asdict(self)
        for key, value in list(out.items()):
            if isinstance(value, Path):
                out[key] = str(value)
            elif isinstance(value, list):
                out[key] = [str(item) if isinstance(item, Path) else item for item in value]
        return out


def _split_multi(value) -> list[str]:
    """Split a comma-separated option into its elements.

    Mirrors Chimera's own parsing (``[x for x in value.split(",") if x]``), so
    stray/trailing commas are tolerated rather than producing empty entries.
    Non-string values (an int scale from a preset JSON, or an already-split
    list) are accepted as-is.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        items = [str(item).strip() for item in value]
    else:
        items = [item.strip() for item in str(value).split(",")]
    return [item for item in items if item]


def _parse_scale_token(value) -> int:
    text = str(value)
    if text.lower().startswith("scale"):
        text = text[len("scale") :]
    return int(text)


def _normalize_output_spaces(spaces: list[str]) -> list[str]:
    aliases = {
        "mrsi": "MRSI",
        "orig": "MRSI",
        "t1": "T1w",
        "t1w": "T1w",
        "mni": "MNI152NLin2009cAsym",
        "mni152": "MNI152NLin2009cAsym",
        "mni152nlin2009casym": "MNI152NLin2009cAsym",
    }
    normalized = []
    for value in spaces:
        key = str(value).strip().lower()
        if key not in aliases:
            supported = ", ".join(sorted(aliases))
            raise ValueError(f"Unsupported output space '{value}'. Supported values: {supported}")
        canonical = aliases[key]
        if canonical not in normalized:
            normalized.append(canonical)
    return normalized
