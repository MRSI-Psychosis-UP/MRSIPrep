"""Optional rigid orientation correction for raw MRSI maps.

Post-quantification MRSI maps occasionally come out of the vendor/quantification
pipeline with a wrong sform/qform -- close enough to plausible that spike
filtering, PVC, and even the real (deformable) MRSI-to-T1w registration all
"succeed", but the whole recording ends up subtly or badly misaligned. This
module fixes that upstream of everything else: a single quick rigid-only
registration of the reference metabolite map to the T1w anatomical, applied
identically to every other map in the recording, before any preprocessing runs.

Only active when config.correct_mrsi_orientation is set; a default run never
calls into this module.
"""

from __future__ import annotations

from pathlib import Path

import nibabel as nib
import numpy as np

from mrsiprep.registration.transforms import all_exist, ants_transform_prefix, apply_image_transform, transform_paths
from mrsiprep.utils.debug import note_cache_hit, note_computed
from mrsiprep.utils.images import load_3d_data, save_nifti


def _pick_orientation_reference(metabolite_maps: dict[str, Path], preferred_met: str | None) -> Path:
    if preferred_met and preferred_met in metabolite_maps:
        return metabolite_maps[preferred_met]
    if not metabolite_maps:
        raise ValueError("No metabolite maps available to drive MRSI orientation correction.")
    return next(iter(metabolite_maps.values()))


def _corrected_grid(reference_in_t1_space: nib.Nifti1Image, native_reference: nib.Nifti1Image) -> tuple[tuple[int, ...], np.ndarray]:
    """The rigid-corrected position/orientation, on a grid sized and spaced
    like the *original* MRSI reference -- not T1w's.

    ``reference_in_t1_space`` (the MRSI reference resampled through the rigid
    transform, at T1w resolution) carries the corrected rotation/position;
    ``rescale_affine`` keeps that rotation and the RAS location of the
    central voxel while swapping in the original MRSI voxel spacing and
    shape, so every map this is applied to stays at native MRSI resolution.
    """
    from nibabel.affines import rescale_affine

    native_shape = native_reference.shape[:3]
    native_zooms = native_reference.header.get_zooms()[:3]
    corrected_affine = rescale_affine(
        reference_in_t1_space.affine,
        reference_in_t1_space.shape[:3],
        native_zooms,
        new_shape=native_shape,
    )
    return native_shape, corrected_affine


def correct_mrsi_orientation(
    config,
    subject: str,
    session: str | None,
    metabolite_maps: dict[str, Path],
    t1_path: Path,
    crlb_maps: dict[str, Path] | None = None,
    snr_map: Path | None = None,
    linewidth_map: Path | None = None,
    water_map: Path | None = None,
) -> dict[str, Path]:
    """Rigid-register ``metabolite_maps[config.ref_met]`` (or the first
    available map) to ``t1_path``, then apply that one rigid transform to
    every map passed in, writing the result back over each input path.

    Every path passed in must already be a writable location this run owns
    (e.g. a derivatives-tree copy) -- not an input BIDS path, which is
    commonly mounted read-only.

    A brainmask is deliberately not accepted here: unlike the maps above, an
    externally-provided one is never copied into the derivatives tree ahead
    of this call, so there is no writable target to correct in place.
    :func:`mrsiprep.mrsi.masks.ensure_brainmask` runs after this and, when no
    separate mask was provided, derives one straight from these
    already-corrected metabolite/water maps -- so it comes out aligned
    without needing to be corrected itself.

    Returns a dict of every path actually rewritten, keyed the same way the
    input dicts were (metabolite maps by metabolite name, others by their
    own fixed key: ``"crlb-<met>"``, ``"snr"``, ``"fwhm"``, ``"water"``).
    """
    backend = config.registration_backend
    prefix = ants_transform_prefix(config.derivative_dir, subject, session, "orient", backend=backend)
    forward = transform_paths(prefix, "forward", backend=backend)
    reference_path = _pick_orientation_reference(metabolite_maps, config.ref_met)

    if all_exist(forward) and not (getattr(config, "overwrite_t1_reg", False) or config.overwrite):
        note_cache_hit()
    else:
        note_computed()
        if backend == "fsl":
            from mrsiprep.interfaces.fsl import register_flirt

            register_flirt(t1_path, reference_path, prefix, flirt_dof=6, flirt_cost=config.fsl_cost, verbose=config.verbose >= 3)
        else:
            from mrsiprep.interfaces.ants import register

            register(t1_path, reference_path, prefix, transform="Rigid", verbose=config.verbose >= 3, threads=config.nthreads)
        forward = transform_paths(prefix, "forward", backend=backend, include_missing=False)

    native_img = nib.load(str(reference_path))
    reference_in_t1_img = nib.load(str(apply_image_transform(t1_path, reference_path, forward, prefix.with_suffix(".ref_in_t1.nii.gz"), threads=config.nthreads)))
    target_shape, target_affine = _corrected_grid(reference_in_t1_img, native_img)

    items: list[tuple[str, Path]] = [(met, path) for met, path in metabolite_maps.items()]
    for met, path in (crlb_maps or {}).items():
        items.append((f"crlb-{met}", path))
    if snr_map is not None:
        items.append(("snr", snr_map))
    if linewidth_map is not None:
        items.append(("fwhm", linewidth_map))
    if water_map is not None:
        items.append(("water", water_map))

    corrected: dict[str, Path] = {}
    for key, path in items:
        corrected[key] = _resample_in_place(path, target_shape, target_affine, order=1)
    return corrected


def _resample_in_place(path: Path, target_shape: tuple[int, ...], target_affine: np.ndarray, order: int = 1) -> Path:
    from nibabel.processing import resample_from_to

    img, data = load_3d_data(path, dtype=np.float32, label="MRSI map")
    resampled = resample_from_to(nib.Nifti1Image(data, img.affine, img.header), (target_shape, target_affine), order=order)
    return save_nifti(np.asanyarray(resampled.dataobj).astype(np.float32), resampled, path, dtype=np.float32)
