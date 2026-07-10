"""Subject-level longitudinal template construction and template-to-MNI registration.

Builds one unbiased ANTs template across a subject's sessions (via
``antsMultivariateTemplateConstruction2.sh``), then registers that template to
MNI once (via ``antsRegistrationSyN.sh``). Session-to-MNI transforms are then
composed as (session -> template) + (template -> MNI), instead of registering
each session directly to MNI. Mirrors the algorithm used by the
`mrsitoolbox_package` research pipeline's `registration_multivisit.sh`.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from mrsiprep.interfaces.ants import require_cli, run_cli
from mrsiprep.registration.transforms import all_exist, ants_transform_prefix, transform_paths
from mrsiprep.utils.images import resolve_mni_resolution


@dataclass
class SubjectTemplateResult:
    template_path: Path
    per_session_forward: dict[str, list[Path]]
    template_to_mni_forward: list[Path]
    template_to_mni_inverse: list[Path]


def build_subject_template(config, subject: str, session_t1_paths: dict[str, Path]) -> SubjectTemplateResult | None:
    """Build (or reuse) a subject-level template and its MNI registration.

    ``session_t1_paths`` maps session label -> that session's
    ``registration_t1w`` path (the same T1w each session already registers
    MRSI onto). Returns ``None`` when fewer than 2 sessions are given (single
    session: no template to build, caller falls back to direct per-session
    T1-to-MNI registration).
    """
    if len(session_t1_paths) < 2:
        return None

    sessions = sorted(session_t1_paths)
    template_prefix = ants_transform_prefix(config.derivative_dir, subject, sessions[0], "t1-template").parent
    template_path = template_prefix / f"sub-{subject}_ses-all_desc-template_T1w.nii.gz"
    mni_forward = transform_paths(ants_transform_prefix(config.derivative_dir, subject, None, "template-mni"), "forward")
    mni_inverse = transform_paths(ants_transform_prefix(config.derivative_dir, subject, None, "template-mni"), "inverse")
    per_session_forward = {
        session: transform_paths(ants_transform_prefix(config.derivative_dir, subject, session, "t1-template"), "forward")
        for session in sessions
    }

    already_built = (
        template_path.exists()
        and all_exist(mni_forward)
        and all(all_exist(paths) for paths in per_session_forward.values())
    )
    if already_built and not (config.overwrite_mni_reg or config.overwrite):
        return SubjectTemplateResult(template_path, per_session_forward, mni_forward, mni_inverse)

    require_cli("antsMultivariateTemplateConstruction2.sh")
    require_cli("antsRegistrationSyN.sh")

    from nilearn import datasets

    with tempfile.TemporaryDirectory(prefix="mrsiprep_subject_template_") as tmpdir:
        tmp = Path(tmpdir)
        session_inputs = []
        for session in sessions:
            dst = tmp / f"sub-{subject}_ses-{session}_T1w.nii.gz"
            shutil.copy2(session_t1_paths[session], dst)
            session_inputs.append(dst)

        build_prefix = tmp / f"sub-{subject}_template_"
        run_cli(
            [
                "antsMultivariateTemplateConstruction2.sh",
                "-d", "3",
                "-i", "4",
                "-g", "0.2",
                "-k", "1",
                "-r", "1",
                "-o", str(build_prefix),
                *[str(path) for path in session_inputs],
            ],
            verbose=config.verbose >= 3,
            threads=config.nthreads,
        )
        built_template = build_prefix.with_name(build_prefix.name + "template0.nii.gz")
        if not built_template.exists():
            raise FileNotFoundError(f"antsMultivariateTemplateConstruction2.sh did not produce {built_template}")

        template_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(built_template, template_path)

        for index, (session, session_input) in enumerate(zip(sessions, session_inputs)):
            out_prefix = ants_transform_prefix(config.derivative_dir, subject, session, "t1-template")
            out_prefix.parent.mkdir(parents=True, exist_ok=True)
            # antsMultivariateTemplateConstruction2.sh names each session's final
            # (last-iteration) transform "{build_prefix}input{NNNN}-{input
            # basename without extension}-{0GenericAffine.mat,1Warp.nii.gz}" --
            # confirmed by reading the script (OUTWARPFN=${OUTPUTNAME}input$(printf
            # "%04d" $j)-${IMGbase...}-) and by inspecting a real run's tmpdir.
            # Every iteration (including the last) deletes all *Warp.nii*/
            # *GenericAffine.mat files upfront and regenerates them, so only the
            # final iteration's files remain once the script exits.
            input_stem = session_input.name
            for suffix in (".nii.gz", ".nii"):
                if input_stem.endswith(suffix):
                    input_stem = input_stem[: -len(suffix)]
                    break
            warp_prefix = build_prefix.with_name(build_prefix.name + f"input{index:04d}-{input_stem}-")
            affine = warp_prefix.with_name(warp_prefix.name + "0GenericAffine.mat")
            warp = warp_prefix.with_name(warp_prefix.name + "1Warp.nii.gz")
            if not affine.exists() or not warp.exists():
                raise FileNotFoundError(
                    f"antsMultivariateTemplateConstruction2.sh did not produce expected transforms for session {session}: "
                    f"{affine} / {warp}"
                )
            shutil.copy2(warp, out_prefix.with_suffix(".syn.nii.gz"))
            shutil.copy2(affine, out_prefix.with_suffix(".affine.mat"))

        resolution = resolve_mni_resolution(config.mni_resolution, template_path)
        mni_template = datasets.load_mni152_template(resolution)
        mni_template_path = tmp / "mni152_template.nii.gz"
        mni_template.to_filename(str(mni_template_path))

        mni_prefix = ants_transform_prefix(config.derivative_dir, subject, None, "template-mni")
        mni_prefix.parent.mkdir(parents=True, exist_ok=True)
        cli_prefix = tmp / "template_to_mni_"
        run_cli(
            [
                "antsRegistrationSyN.sh",
                "-d", "3",
                "-f", str(mni_template_path),
                "-m", str(template_path),
                "-o", str(cli_prefix),
                "-t", "s",
            ],
            verbose=config.verbose >= 3,
            threads=config.nthreads,
        )
        shutil.copy2(cli_prefix.with_name(cli_prefix.name + "1Warp.nii.gz"), mni_forward[0])
        shutil.copy2(cli_prefix.with_name(cli_prefix.name + "0GenericAffine.mat"), mni_forward[1])
        shutil.copy2(cli_prefix.with_name(cli_prefix.name + "0GenericAffine.mat"), mni_inverse[0])
        shutil.copy2(cli_prefix.with_name(cli_prefix.name + "1InverseWarp.nii.gz"), mni_inverse[1])

    return SubjectTemplateResult(template_path, per_session_forward, mni_forward, mni_inverse)
