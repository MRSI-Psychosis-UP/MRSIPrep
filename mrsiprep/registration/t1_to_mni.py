"""T1-to-MNI registration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mrsiprep.utils.debug import note_cache_hit, note_computed
from mrsiprep.interfaces.ants import register
from mrsiprep.interfaces.fsl import register_flirt
from mrsiprep.registration.transforms import all_exist, ants_transform_prefix, transform_paths
from mrsiprep.config.templates import template_t1w


@dataclass
class T1ToMNIResult:
    forward: list[Path]
    inverse: list[Path]
    prefix: Path
    template: object


def run_t1_to_mni(config, subject: str, session: str | None, t1_path: Path, mrsi_reference: Path | None = None) -> T1ToMNIResult:

    backend = config.registration_backend
    prefix = ants_transform_prefix(config.derivative_dir, subject, session, "anat", backend=backend)
    forward = transform_paths(prefix, "forward", backend=backend)
    inverse = transform_paths(prefix, "inverse", backend=backend)
    resolution = config.resolution_for("MNI152NLin2009cAsym", t1_path, mrsi_reference, prefer_t1w=True)
    template = template_t1w(resolution)
    if all_exist(forward) and all_exist(inverse) and not (config.overwrite_template_reg or config.overwrite):
        note_cache_hit()
        return T1ToMNIResult(forward, inverse, prefix, template)
    note_computed()
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
            flirt_dof=config.fsl_t1_to_template_dof,
            flirt_cost=config.fsl_cost,
            verbose=config.verbose >= 3,
        )
    else:
        register(template, t1_path, prefix, transform=config.ants_t1_to_template_transform, verbose=config.verbose >= 3, threads=config.nthreads)
    return T1ToMNIResult(
        transform_paths(prefix, "forward", backend=backend, include_missing=False),
        transform_paths(prefix, "inverse", backend=backend, include_missing=False),
        prefix,
        template,
    )


def compose_longitudinal_t1_to_mni(config, subject: str, session: str, template_result, t1_path: Path, mrsi_reference: Path | None = None) -> T1ToMNIResult:
    """Compose (session -> subject template) + (template -> MNI) forward transforms.

    ``template_result`` is a ``SubjectTemplateResult`` from
    ``mrsiprep.registration.subject_template.build_subject_template``, already
    built for this subject. The composed forward list is applied in order by
    ``apply_transforms``/antspyx (session-to-template transform first, then
    template-to-MNI), matching the existing forward-transform-list convention
    used everywhere else in the codebase (see ``registration.transforms``).
    """

    session_forward = template_result.per_session_forward.get(session)
    if not session_forward or not all_exist(session_forward):
        raise FileNotFoundError(
            f"Missing session-to-template transform for sub-{subject} ses-{session}; "
            "build_subject_template() should have produced it."
        )
    forward = session_forward + template_result.template_to_mni_forward
    inverse = template_result.template_to_mni_inverse
    # Must match the resolution build_subject_template() actually registered
    # the shared subject template to MNI at (see the identical fallback
    # there): the template spans multiple sessions, possibly at different
    # native MRSI resolutions, so 'origres' has no single well-defined answer
    # for the shared template-to-MNI stage specifically, even though this
    # session's own mrsi_reference is available.
    resolution = config.resolution_for("MNI152NLin2009cAsym", t1_path, mrsi_reference, prefer_t1w=True)
    template = template_t1w(resolution)
    prefix = ants_transform_prefix(config.derivative_dir, subject, session, "anat")
    return T1ToMNIResult(forward, inverse, prefix, template)
