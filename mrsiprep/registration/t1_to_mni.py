"""T1-to-MNI registration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mrsiprep.interfaces.ants import register
from mrsiprep.interfaces.fsl import register_flirt
from mrsiprep.registration.transforms import all_exist, ants_transform_prefix, transform_paths
from mrsiprep.utils.images import resolve_mni_resolution


@dataclass
class T1ToMNIResult:
    forward: list[Path]
    inverse: list[Path]
    prefix: Path
    template: object


def run_t1_to_mni(config, subject: str, session: str | None, t1_path: Path, mrsi_reference: Path | None = None) -> T1ToMNIResult:
    from nilearn import datasets

    backend = config.registration_backend
    prefix = ants_transform_prefix(config.derivative_dir, subject, session, "anat", backend=backend)
    forward = transform_paths(prefix, "forward", backend=backend)
    inverse = transform_paths(prefix, "inverse", backend=backend)
    resolution = resolve_mni_resolution(config.mni_resolution, t1_path, mrsi_reference)
    template = datasets.load_mni152_template(resolution)
    if all_exist(forward) and all_exist(inverse) and not (config.overwrite_mni_reg or config.overwrite):
        return T1ToMNIResult(forward, inverse, prefix, template)
    if config.normalization == "existing":
        raise FileNotFoundError(
            f"--normalization existing requires precomputed T1-to-MNI transforms at {prefix} "
            f"({'.flirt.mat/.flirt_inv.mat' if backend == 'fsl' else '.syn.nii.gz/.affine.mat/.syn_inv.nii.gz/.affine_inv.mat'}), "
            "but they were not found."
        )
    if backend == "fsl":
        # FLIRT-only backend: affine, no deformable stage (see interfaces/fsl.py).
        register_flirt(
            template,
            t1_path,
            prefix,
            flirt_dof=config.fsl_t1_to_mni_dof,
            flirt_cost=config.fsl_cost,
            verbose=config.verbose >= 3,
        )
    else:
        register(template, t1_path, prefix, transform=config.ants_t1_to_mni_transform, verbose=config.verbose >= 3, threads=config.nthreads)
    return T1ToMNIResult(
        transform_paths(prefix, "forward", backend=backend, include_missing=False),
        transform_paths(prefix, "inverse", backend=backend, include_missing=False),
        prefix,
        template,
    )


def compose_longitudinal_t1_to_mni(config, subject: str, session: str, template_result, t1_path: Path) -> T1ToMNIResult:
    """Compose (session -> subject template) + (template -> MNI) forward transforms.

    ``template_result`` is a ``SubjectTemplateResult`` from
    ``mrsiprep.registration.subject_template.build_subject_template``, already
    built for this subject. The composed forward list is applied in order by
    ``apply_transforms``/antspyx (session-to-template transform first, then
    template-to-MNI), matching the existing forward-transform-list convention
    used everywhere else in the codebase (see ``registration.transforms``).
    """
    from nilearn import datasets

    session_forward = template_result.per_session_forward.get(session)
    if not session_forward or not all_exist(session_forward):
        raise FileNotFoundError(
            f"Missing session-to-template transform for sub-{subject} ses-{session}; "
            "build_subject_template() should have produced it."
        )
    forward = session_forward + template_result.template_to_mni_forward
    inverse = template_result.template_to_mni_inverse
    resolution = resolve_mni_resolution(config.mni_resolution, t1_path)
    template = datasets.load_mni152_template(resolution)
    prefix = ants_transform_prefix(config.derivative_dir, subject, session, "anat")
    return T1ToMNIResult(forward, inverse, prefix, template)
