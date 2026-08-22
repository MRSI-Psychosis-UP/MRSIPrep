"""Chimera native-space parcellation workflow."""

from __future__ import annotations

from pathlib import Path

from mrsiprep.interfaces.chimera import run_chimera
from mrsiprep.interfaces.freesurfer import freesurfer_subject_id, run_recon_all, subject_dir_valid
from mrsiprep.io.bids import BIDSLayout
from mrsiprep.io.naming import chimera_derivative
from mrsiprep.parcellation.base import ParcellationResult
from mrsiprep.parcellation.labels import copy_labels
from mrsiprep.registration.transforms import apply_image_transform
from mrsiprep.utils.debug import Debug


def run_chimera_parcellation(config, subject: str, session: str | None, mrsi_reference: Path, t1_to_mrsi_transforms: list[Path]) -> list[ParcellationResult]:
    """Build every requested Chimera parcellation and project it into MRSI space.

    ``--chimera-scheme``/``--chimera-scale``/``--chimera-grow`` each accept a
    comma-separated list, combined as a cross product (Chimera's own
    semantics). Chimera is invoked once for the whole set, so recon-all and
    the surface reconstruction are shared across every combination.

    :returns: One :class:`ParcellationResult` per parcellation actually built,
        in request order. Combinations Chimera didn't produce are skipped --
        see :func:`mrsiprep.interfaces.chimera.run_chimera`.
    """
    debug = Debug(verbose=config.verbose)
    layout = BIDSLayout.from_config(config)
    rerun_chimera = config.overwrite or config.overwrite_chimera
    schemes = config.chimera_schemes()
    scales = config.chimera_scales()
    grows = config.chimera_grows()

    # Cached lookup per combination, so a partially cached set only
    # recomputes what is actually missing.
    cached: list[tuple[str, int, int, Path]] = []
    pending: list[tuple[str, int, int]] = []
    for scheme in schemes:
        for scale in scales:
            for grow in grows:
                source = None
                if not rerun_chimera:
                    source = layout.chimera_atlas(subject, session, scheme, scale, grow, space="orig")
                if source is None:
                    pending.append((scheme, scale, grow))
                else:
                    cached.append((scheme, scale, grow, source))

    produced: list[tuple[str, int, int, Path]] = list(cached)
    if pending:
        raw_t1 = layout.raw_t1(subject, session)
        if raw_t1 is None:
            raise FileNotFoundError(f"Missing raw T1w required for Chimera: sub-{subject} ses-{session}")
        fs_subject = freesurfer_subject_id(raw_t1)
        if not subject_dir_valid(config.freesurfer_dir, fs_subject):
            run_recon_all(raw_t1, config.freesurfer_dir, fs_subject, force=False, nthreads=config.nthreads, verbose=config.verbose >= 3, debug=debug)
        # One invocation for every missing combination: chimera cross-products
        # the comma lists itself, so this shares recon-all across all of them.
        produced.extend(
            run_chimera(
                config.bids_dir,
                config.output_dir,
                config.freesurfer_dir,
                raw_t1,
                subject,
                session,
                sorted({scheme for scheme, _, _ in pending}, key=schemes.index),
                sorted({scale for _, scale, _ in pending}, key=scales.index),
                sorted({grow for _, _, grow in pending}, key=grows.index),
                verbose=config.verbose >= 3,
                milestones=config.verbose >= 2,
                force=rerun_chimera,
                debug=debug,
            )
        )

    # Only tag outputs with their grow distance when several were requested,
    # so the ordinary single-grow run keeps today's exact output paths.
    tag_grow = len(grows) > 1
    results: list[ParcellationResult] = []
    seen: set[tuple[str, int, int]] = set()
    for scheme, scale, grow, source_atlas in produced:
        if (scheme, scale, grow) in seen:
            continue
        seen.add((scheme, scale, grow))
        results.append(
            _finalize_parcellation(
                config,
                subject,
                session,
                mrsi_reference,
                t1_to_mrsi_transforms,
                scheme,
                scale,
                grow if tag_grow else None,
                source_atlas,
                rerun_chimera,
            )
        )
    return results


def _finalize_parcellation(
    config,
    subject: str,
    session: str | None,
    mrsi_reference: Path,
    t1_to_mrsi_transforms: list[Path],
    scheme: str,
    scale: int,
    grow: int | None,
    source_atlas: Path,
    rerun_chimera: bool,
) -> ParcellationResult:
    """Copy one Chimera output into the derivatives tree, project it into MRSI
    space, and resolve its label table."""
    scale_entity = f"scale{scale}"
    atlas_name = f"chimera{scheme}"
    # desc is only populated when several grow distances were requested, so
    # single-grow runs keep byte-identical paths to before this feature.
    extra = {"desc": f"grow{grow}mm"} if grow is not None else {}
    t1_out = chimera_derivative(config.output_dir, subject, session, space="T1w", atlas=atlas_name, scale=scale_entity, **extra)
    mrsi_out = chimera_derivative(config.output_dir, subject, session, space="MRSI", atlas=atlas_name, scale=scale_entity, **extra)
    labels_out = chimera_derivative(config.output_dir, subject, session, atlas=atlas_name, scale=scale_entity, suffix_override="tsv", **extra)
    if not t1_out.exists() or rerun_chimera:
        import shutil

        t1_out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_atlas, t1_out)
    if not mrsi_out.exists() or rerun_chimera:
        apply_image_transform(mrsi_reference, t1_out, t1_to_mrsi_transforms, mrsi_out, interpolation="genericLabel", threads=config.nthreads)
    source_labels = source_atlas.with_suffix("").with_suffix(".tsv") if source_atlas.name.endswith(".nii.gz") else source_atlas.with_suffix(".tsv")
    if source_labels.exists():
        copy_labels(source_labels, labels_out)
    else:
        _labels_from_image(mrsi_out, labels_out)
    return ParcellationResult(
        atlas_t1=t1_out, atlas_mrsi=mrsi_out, labels=labels_out, mode="chimera", atlas_name=atlas_name, scale=scale_entity, grow=grow
    )


def _labels_from_image(image_path: Path, labels_path: Path) -> None:
    import nibabel as nib
    import numpy as np

    from mrsiprep.parcellation.labels import write_labels

    data = nib.load(str(image_path)).get_fdata().astype(int)
    indices = np.unique(data)
    indices = indices[indices != 0]
    write_labels(indices, [str(i) for i in indices], labels_path)
