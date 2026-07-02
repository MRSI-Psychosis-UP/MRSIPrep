"""Chimera native-space parcellation workflow."""

from __future__ import annotations

from pathlib import Path

from mrsiprep.interfaces.ants import apply_transforms
from mrsiprep.interfaces.chimera import run_chimera
from mrsiprep.interfaces.freesurfer import freesurfer_subject_id, run_recon_all, subject_dir_valid
from mrsiprep.io.bids import BIDSLayout
from mrsiprep.io.naming import chimera_derivative
from mrsiprep.parcellation.base import ParcellationResult
from mrsiprep.parcellation.labels import copy_labels
from mrsiprep.utils.debug import Debug


def run_chimera_parcellation(config, subject: str, session: str | None, mrsi_reference: Path, t1_to_mrsi_transforms: list[Path]) -> ParcellationResult:
    debug = Debug(verbose=config.verbose)
    layout = BIDSLayout(config.bids_dir)
    rerun_chimera = config.overwrite or config.overwrite_chimera
    source_atlas = None if rerun_chimera else layout.chimera_atlas(subject, session, config.chimera_scheme, config.chimera_scale, config.chimera_grow, space="orig")
    if source_atlas is None:
        raw_t1 = layout.raw_t1(subject, session)
        if raw_t1 is None:
            raise FileNotFoundError(f"Missing raw T1w required for Chimera: sub-{subject} ses-{session}")
        fs_subject = freesurfer_subject_id(raw_t1)
        if not subject_dir_valid(config.freesurfer_dir, fs_subject):
            run_recon_all(raw_t1, config.freesurfer_dir, fs_subject, force=False, nthreads=config.nthreads, verbose=config.verbose >= 3, debug=debug)
        source_atlas = run_chimera(
            config.bids_dir,
            config.output_dir,
            config.freesurfer_dir,
            raw_t1,
            subject,
            session,
            config.chimera_scheme,
            config.chimera_scale,
            config.chimera_grow,
            verbose=config.verbose >= 3,
            milestones=config.verbose >= 2,
            force=rerun_chimera,
            debug=debug,
        )
    scale = f"scale{config.chimera_scale}"
    atlas_name = f"chimera{config.chimera_scheme}"
    t1_out = chimera_derivative(config.output_dir, subject, session, space="T1w", atlas=atlas_name, scale=scale)
    mrsi_out = chimera_derivative(config.output_dir, subject, session, space="MRSI", atlas=atlas_name, scale=scale)
    labels_out = chimera_derivative(config.output_dir, subject, session, atlas=atlas_name, scale=scale, suffix_override="tsv")
    if not t1_out.exists() or rerun_chimera:
        import shutil

        t1_out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_atlas, t1_out)
    if not mrsi_out.exists() or rerun_chimera:
        apply_transforms(mrsi_reference, t1_out, t1_to_mrsi_transforms, mrsi_out, interpolation="genericLabel")
    source_labels = source_atlas.with_suffix("").with_suffix(".tsv") if source_atlas.name.endswith(".nii.gz") else source_atlas.with_suffix(".tsv")
    if source_labels.exists():
        copy_labels(source_labels, labels_out)
    else:
        _labels_from_image(mrsi_out, labels_out)
    return ParcellationResult(atlas_t1=t1_out, atlas_mrsi=mrsi_out, labels=labels_out, mode="chimera", atlas_name=atlas_name, scale=scale)


def _labels_from_image(image_path: Path, labels_path: Path) -> None:
    import nibabel as nib
    import numpy as np

    from mrsiprep.parcellation.labels import write_labels

    data = nib.load(str(image_path)).get_fdata().astype(int)
    indices = np.unique(data)
    indices = indices[indices != 0]
    write_labels(indices, [str(i) for i in indices], labels_path)
