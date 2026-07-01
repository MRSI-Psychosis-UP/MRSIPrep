"""Runtime configuration objects."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from .defaults import METABOLITES_3T, QUALITY_DEFAULTS


@dataclass
class MRSIPrepConfig:
    bids_dir: Path
    output_dir: Path
    analysis_level: str
    participant_label: list[str] = field(default_factory=list)
    session_label: list[str] = field(default_factory=list)
    participants_file: Path | None = None
    b0: float = 3.0
    metabolites: list[str] = field(default_factory=lambda: list(METABOLITES_3T))
    quality_metrics: list[str] = field(default_factory=lambda: ["snr", "linewidth", "crlb"])
    snr_min: float = QUALITY_DEFAULTS["snr_min"]
    linewidth_max: float = QUALITY_DEFAULTS["linewidth_max"]
    crlb_max: float = QUALITY_DEFAULTS["crlb_max"]
    processing_mode: str = "mni-norm"
    tissue_backend: str = "synthseg-fast"
    registration_backend: str = "ants"
    normalization: str = "simple"
    output_spaces: list[str] = field(default_factory=lambda: ["T1w", "MNI152NLin2009cAsym"])
    mni_resolution: str = "t1wres"
    registration_t1_target: str | None = None
    csf_pv_threshold: float = 0.95
    parcellation_mode: str | None = None
    synthseg_mode: str = "robust"
    chimera_scheme: str = "LFMIHIFIS"
    chimera_scale: int = 3
    chimera_grow: int = 2
    atlas: str = "chimera-LFMIHIFIS-3"
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
    ref_met: str = "CrPCr"
    t1_pattern: str = "desc-brain_T1w"
    transform: str = ""
    filter_biharmonic: bool = True
    spike_percentile: float = 99.0
    no_pvc: bool = False
    proc_mnilong: bool = False
    transform_spikemask: bool = False
    overwrite: bool = False
    overwrite_filt: bool = False
    overwrite_seg: bool = False
    overwrite_pve: bool = False
    overwrite_t1_reg: bool = False
    overwrite_mni_reg: bool = False
    overwrite_transform: bool = False
    work_dir: Path | None = None
    verbose: int = 1
    validate_only: bool = False
    check_external_libs: bool = False

    def __post_init__(self) -> None:
        self.bids_dir = Path(self.bids_dir).resolve()
        self.output_dir = Path(self.output_dir).resolve()
        self.output_spaces = _normalize_output_spaces(self.output_spaces)
        if self.work_dir is None:
            self.work_dir = self.output_dir / "work"
        else:
            self.work_dir = Path(self.work_dir).resolve()
        if self.fs_subjects_dir is not None:
            self.fs_subjects_dir = Path(self.fs_subjects_dir).resolve()
        if self.processing_mode not in {"mni-norm", "parc-con"}:
            raise ValueError(f"Unsupported processing mode: {self.processing_mode}")
        if self.synthseg_mode not in {"fast", "standard", "robust"}:
            raise ValueError(f"Unsupported SynthSeg mode: {self.synthseg_mode}")
        if self.tissue_backend not in {"synthseg-fast", "existing", "none"}:
            raise ValueError(f"Unsupported tissue backend: {self.tissue_backend}")
        if self.tissue_backend == "none":
            self.no_pvc = True
        if self.registration_t1_target is None:
            self.registration_t1_target = "brain" if self.processing_mode == "mni-norm" else "brain-csf"
        if self.parcellation_mode is None:
            self.parcellation_mode = "synthseg" if self.processing_mode == "mni-norm" else "chimera"
        if self.processing_mode == "mni-norm" and self.parcellation_mode != "synthseg":
            raise ValueError("mni-norm only supports SynthSeg parcellation. Use --mode parc-con for Chimera or MNI atlases.")
        if self.processing_mode == "mni-norm" and self.registration_t1_target not in {"brain", "raw"}:
            raise ValueError("mni-norm supports SynthSeg brain or raw T1w registration targets.")
        if self.processing_mode == "parc-con" and self.parcellation_mode == "synthseg":
            raise ValueError("parc-con requires Chimera or MNI atlas parcellation.")
        if self.processing_mode == "mni-norm":
            self.no_pvc = True
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
    def source_derivatives_dir(self) -> Path:
        return self.bids_dir / "derivatives"

    @property
    def logs_dir(self) -> Path:
        return self.derivative_dir / "logs"

    @property
    def freesurfer_dir(self) -> Path:
        if self.fs_subjects_dir is not None:
            return self.fs_subjects_dir
        return self.output_dir / "freesurfer"

    @property
    def mrsi_parcel_dir(self) -> Path:
        return self.output_dir / "mrsi_parcel"

    def to_dict(self) -> dict:
        out = asdict(self)
        for key, value in list(out.items()):
            if isinstance(value, Path):
                out[key] = str(value)
            elif isinstance(value, list):
                out[key] = [str(item) if isinstance(item, Path) else item for item in value]
        return out


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
