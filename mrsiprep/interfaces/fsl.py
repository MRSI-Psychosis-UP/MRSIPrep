"""FSL FLIRT/FNIRT registration interface."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import nibabel as nib

from mrsiprep.utils.subprocess_utils import run_checked


class FSLError(RuntimeError):
    """Raised when FSL cannot complete a requested operation."""


def require_cli(command: str) -> str:
    path = shutil.which(command)
    if not path:
        raise FSLError(f"Required FSL command not found on PATH: {command}")
    return path


def require(command: str) -> str:
    return require_cli(command)


def run_cli(cmd: list[str], verbose: bool = False) -> None:
    run_checked(cmd, verbose=verbose, error_cls=FSLError, error_prefix=cmd[0])


def run_fast(t1_path: str | Path, out_prefix: str | Path, verbose: bool = False) -> dict[str, Path]:
    require_cli("fast")
    out_prefix = Path(out_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["fast", "-t", "1", "-n", "3", "-H", "0.1", "-I", "4", "-l", "20.0", "-o", str(out_prefix), str(t1_path)]
    run_checked(cmd, verbose=verbose, error_cls=FSLError, error_prefix="fast")
    return {
        "CSF": out_prefix.parent / f"{out_prefix.name}_pve_0.nii.gz",
        "GM": out_prefix.parent / f"{out_prefix.name}_pve_1.nii.gz",
        "WM": out_prefix.parent / f"{out_prefix.name}_pve_2.nii.gz",
    }


def register_flirt(
    fixed,
    moving,
    out_prefix: str | Path,
    *,
    fixed_mask=None,
    flirt_dof: int = 12,
    flirt_cost: str = "corratio",
    flirt_init: str = "flirt",
    flirt_nosearch: bool = True,
    verbose: bool = False,
) -> dict[str, list[Path]]:
    """Register ``moving`` to ``fixed`` with FLIRT (affine only; see
    ``register_fnirt`` for the deformable FSL backend).

    Defaults (``flirt_cost="corratio"``, seeded from ``-usesqform`` with
    ``-nosearch``) replace FLIRT's own out-of-the-box defaults
    (``mutualinfo`` cost, unrestricted global rotation/translation search),
    which were found to actively diverge on a real MRSI-reference-vs-T1w
    registration: a naive qform/sform-only alignment with zero optimization
    already scored r=0.63 (Pearson correlation, in-brain-mask voxels)
    against the equivalent ANTs SyN registration, while FLIRT's own search
    stage -- with either cost function -- walked away to a worse, sometimes
    strongly anti-correlated (r=-0.09 to -0.29), local optimum. This is
    because the moving image here (a small, low-contrast MRSI reference
    map, e.g. 44x44x25) gives FLIRT's coarse-resolution cost evaluation too
    little information to reliably find the right optimum during a blind
    search. Seeding from the physically-meaningful qform/sform frame and
    skipping the search (``-nosearch``, only local gradient-descent
    refinement from that seed) recovers and improves on the qform-only
    baseline (r=0.65). See ``experiments/fnirt_vs_syn_comparison.py`` and
    its ``metrics.tsv`` output for the full before/after comparison this
    was validated against.
    """
    require_cli("flirt")
    require_cli("convert_xfm")
    fixed_path = _as_image_path(fixed)
    moving_path = _as_image_path(moving)
    fixed_mask_path = _as_image_path(fixed_mask) if fixed_mask is not None else None
    out_prefix = Path(out_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    affine = out_prefix.with_suffix(".flirt.mat")
    inverse_affine = out_prefix.with_suffix(".flirt_inv.mat")

    with tempfile.TemporaryDirectory(prefix="mrsiprep_fslreg_") as tmpdir:
        tmp_registered = Path(tmpdir) / "flirt_registered.nii.gz"
        if flirt_init == "usesqform":
            cmd = [
                "flirt",
                "-in",
                str(moving_path),
                "-ref",
                str(fixed_path),
                "-applyxfm",
                "-usesqform",
                "-omat",
                str(affine),
                "-out",
                str(tmp_registered),
            ]
        elif flirt_init == "flirt":
            sqform_init = Path(tmpdir) / "sqform_init.mat"
            run_cli(
                [
                    "flirt", "-in", str(moving_path), "-ref", str(fixed_path),
                    "-applyxfm", "-usesqform",
                    "-omat", str(sqform_init), "-out", str(Path(tmpdir) / "sqform_only.nii.gz"),
                ],
                verbose=verbose,
            )
            cmd = [
                "flirt",
                "-in",
                str(moving_path),
                "-ref",
                str(fixed_path),
                "-init",
                str(sqform_init),
                "-omat",
                str(affine),
                "-out",
                str(tmp_registered),
                "-dof",
                str(flirt_dof),
                "-cost",
                flirt_cost,
            ]
            if flirt_nosearch:
                cmd.append("-nosearch")
            if fixed_mask_path is not None:
                cmd.extend(["-refweight", str(fixed_mask_path)])
        else:
            raise FSLError(f"Unsupported FLIRT initialization mode: {flirt_init}")
        run_cli(cmd, verbose=verbose)

    _invert_affine(affine, inverse_affine, verbose=verbose)
    return {"forward": [affine], "inverse": [inverse_affine]}


def register_fnirt(
    fixed,
    moving,
    out_prefix: str | Path,
    *,
    fixed_mask,
    moving_mask,
    flirt_dof: int = 12,
    flirt_cost: str = "corratio",
    warpres: tuple[int, int, int] | None = None,
    lambda_weight: str = "300,200,150,150",
    regmod: str = "bending_energy",
    verbose: bool = False,
) -> dict[str, list[Path]]:
    """Register ``moving`` to ``fixed`` with FLIRT (seeded, corrected
    defaults -- see ``register_flirt``) followed by FNIRT, mrsiprep's
    deformable ``fsl`` registration stage, mimicking the deformable
    (SyN) component of ANTs' default ``sr`` preset.

    ``fixed_mask``/``moving_mask`` are required (not optional): FNIRT, unlike
    FLIRT's own ``-refweight`` masking, needs explicit masking on both sides
    (``--refmask``/``--inmask``) to avoid trying to deform regions with no
    MRSI signal to match background noise.

    ``warpres`` should ordinarily come from ``default_fnirt_warpres()``,
    called with the MRSI reference image's own native voxel size, rather
    than a fixed value -- see that function's docstring for why.
    """
    require_cli("flirt")
    require_cli("fnirt")
    require_cli("invwarp")
    out_prefix = Path(out_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    fixed_path = _as_image_path(fixed)
    moving_path = _as_image_path(moving)
    fixed_mask_path = _as_image_path(fixed_mask)
    moving_mask_path = _as_image_path(moving_mask)

    flirt_result = register_flirt(
        fixed_path, moving_path, out_prefix,
        fixed_mask=fixed_mask_path, flirt_dof=flirt_dof, flirt_cost=flirt_cost,
        verbose=verbose,
    )
    affine = flirt_result["forward"][0]

    if warpres is None:
        warpres = (10, 10, 10)
    warpres_arg = ",".join(str(int(value)) for value in warpres)

    warp = out_prefix.with_suffix(".fnirt_warp.nii.gz")
    warp_inv = out_prefix.with_suffix(".fnirt_warp_inv.nii.gz")

    with tempfile.TemporaryDirectory(prefix="mrsiprep_fslfnirt_") as tmpdir:
        # fnirt's own --ref/--refmask and --in/--inmask dimension checks are
        # strict about matching affines exactly -- two derivatives that are
        # genuinely on the same grid but were produced by separate
        # operations can differ by sub-micron floating-point noise (e.g.
        # ~1e-7) and still fail this check. Regrid each mask onto its
        # image's exact grid first rather than relying on upstream
        # derivatives being bit-identical.
        fixed_mask_regridded = _regrid_mask_onto(fixed_mask_path, fixed_path, Path(tmpdir) / "fixed_mask.nii.gz", verbose=verbose)
        moving_mask_regridded = _regrid_mask_onto(moving_mask_path, moving_path, Path(tmpdir) / "moving_mask.nii.gz", verbose=verbose)
        iout = Path(tmpdir) / "fnirt_registered.nii.gz"
        run_cli(
            [
                "fnirt",
                f"--ref={fixed_path}",
                f"--in={moving_path}",
                f"--aff={affine}",
                f"--refmask={fixed_mask_regridded}",
                f"--inmask={moving_mask_regridded}",
                f"--warpres={warpres_arg}",
                f"--regmod={regmod}",
                f"--lambda={lambda_weight}",
                f"--fout={warp}",
                f"--iout={iout}",
                "--interp=linear",
            ],
            verbose=verbose,
        )
    run_cli(["invwarp", f"--ref={moving_path}", f"--warp={warp}", f"--out={warp_inv}"], verbose=verbose)

    # fnirt --aff bakes the affine into --fout: the warp field alone already
    # maps moving -> fixed end to end. Order matters for transform_paths()'s
    # forward/inverse convention (warp listed first, matching how
    # apply_transforms()/applywarp only needs --warp, no --premat, for a
    # forward-direction resample -- see apply_transforms()'s FNIRT branch).
    return {"forward": [warp, affine], "inverse": [flirt_result["inverse"][0], warp_inv]}


def _regrid_mask_onto(mask: Path, reference: Path, out_path: Path, verbose: bool = False) -> Path:
    """Resample ``mask`` onto ``reference``'s exact voxel grid (nearest-
    neighbor), via FLIRT's own qform-derived resampling. Used before FNIRT,
    whose ``--refmask``/``--inmask`` dimension check is strict about exact
    affine equality between an image and its mask -- see ``register_fnirt``."""
    require_cli("flirt")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    run_cli(
        [
            "flirt", "-in", str(mask), "-ref", str(reference),
            "-applyxfm", "-usesqform",
            "-out", str(out_path), "-interp", "nearestneighbour",
        ],
        verbose=verbose,
    )
    return out_path


def default_fnirt_warpres(mrsi_voxel_mm: tuple[float, float, float], floor_mm: int = 6) -> tuple[int, int, int]:
    """FNIRT ``--warpres`` (B-spline control-point grid spacing, mm),
    auto-scaled to the MRSI acquisition's own native voxel size rather than
    a fixed constant.

    ``--warpres`` sets the spacing of FNIRT's deformation-field control-point
    grid in the *fixed* (T1w) image's space -- but the real constraint here
    is how much local deformation detail the *moving* (MRSI) image's
    resolution can actually justify without the warp just fitting noise. A
    higher-resolution MRSI acquisition (e.g. ~3.2mm at 7T) carries more
    spatial degrees of freedom than a coarser one (e.g. ~5mm at 3T), so it
    can support a finer control-point grid.

    Rule of thumb, validated against a real 3T subject (5.0mm MRSI, where
    warpres=10mm -- i.e. ~2x voxel size -- scored best against the ANTs SyN
    reference, see experiments/fnirt_vs_syn_comparison.py): ``warpres ~= 2 x
    native MRSI voxel size``, floored at ``floor_mm`` (default 6mm --
    FNIRT's practical lower bound before the control-point grid outnumbers
    the spatial information the MRSI data can actually support).
    """
    return tuple(max(floor_mm, round(2 * float(voxel))) for voxel in mrsi_voxel_mm)


def apply_transforms(
    fixed,
    moving,
    transforms: list[str | Path],
    out_path: str | Path,
    interpolation: str = "linear",
    verbose: bool = False,
) -> Path:
    """Apply an FSL FLIRT affine, or a FNIRT warp, to ``moving``.

    A FNIRT warp (``.fnirt_warp.nii.gz``) takes priority over any affine
    also present in ``transforms``: when ``fnirt`` is run with ``--aff``
    (as ``register_fnirt`` always does), its ``--fout`` warp field already
    encodes the full affine+nonlinear composition end to end, so the warp
    is applied alone via ``applywarp`` with no ``--premat``. Passing the
    affine as well (``--premat``) would double-apply it -- this was hit and
    confirmed empirically: with ``--premat``, the resampled map's
    correlation against the ANTs SyN reference collapsed from r=0.71 to
    r=-0.24 and lost roughly a third of its in-brain voxel coverage.
    """
    existing = [Path(path) for path in transforms if Path(path).exists()]
    if not existing:
        raise FSLError(f"No transform files exist in list: {transforms}")
    fixed_path = _as_image_path(fixed)
    moving_path = _as_image_path(moving)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    warps = [path for path in existing if path.name.endswith(".fnirt_warp.nii.gz") or path.name.endswith(".fnirt_warp_inv.nii.gz")]
    if warps:
        if len(warps) > 1:
            raise FSLError(f"FSL backend expects a single FNIRT warp per direction, got {len(warps)}: {warps}")
        # Any affine(s) also in `transforms` alongside the warp are a
        # *separate* registration stage on top of it (e.g. t1w->mni FLIRT,
        # composed with an mrsi->t1w FNIRT warp when resampling straight to
        # MNI space) -- NOT the warp's own seed affine, which fnirt already
        # bakes into the warp field (see the docstring above) and which
        # shares the warp's own filename prefix (register_fnirt writes both
        # under the same out_prefix). Exclude that same-stage affine by
        # prefix match; only a genuinely different stage's affine remains.
        # These must still be applied, via applywarp --postmat (post-warp
        # affine, applied in the space the warp resamples into), not
        # silently dropped: dropping them was found to leave the
        # "MNI-space" output actually sitting in T1w space, undetected
        # until compared against an MNI brain mask (~65% "outside brain"
        # instead of the ~15-30% every other variant showed).
        warp_stage_prefix = warps[0].name.split(".fnirt_warp")[0]
        stage_affines = [
            path
            for path in existing
            if (path.name.endswith(".flirt.mat") or path.name.endswith(".flirt_inv.mat"))
            and not path.name.startswith(warp_stage_prefix)
        ]
        if len(stage_affines) > 1:
            raise FSLError(f"FSL backend expects at most one post-warp affine stage, got {len(stage_affines)}: {stage_affines}")
        postmat = stage_affines[0] if stage_affines else None
        _apply_warp(fixed_path, moving_path, warps[0], out_path, interpolation=interpolation, postmat=postmat, verbose=verbose)
        return out_path

    affines = [path for path in existing if path.name.endswith(".flirt.mat") or path.name.endswith(".flirt_inv.mat")]
    if len(affines) > 1:
        # Multiple affines (e.g. mrsi->t1w composed with t1w->mni, when
        # resampling straight to MNI space): compose them into one via
        # convert_xfm -concat before applying, rather than rejecting -- this
        # mirrors ANTs' own multi-transform composition (antsApplyTransforms
        # chains its transform list natively), which FLIRT does not do on
        # its own. Callers list transforms last-applied-first (matching the
        # existing ANTs convention, e.g. t1_to_mni + mrsi_to_t1 means
        # mrsi_to_t1 is applied first), so `-concat` receives them in the
        # same right-to-left order convert_xfm expects.
        with tempfile.TemporaryDirectory(prefix="mrsiprep_fslconcat_") as tmpdir:
            combined = Path(tmpdir) / "combined.mat"
            require_cli("convert_xfm")
            run_cli(["convert_xfm", "-omat", str(combined), "-concat", *[str(path) for path in affines]], verbose=verbose)
            _apply_affine(fixed_path, moving_path, combined, out_path, interpolation=interpolation, verbose=verbose)
        return out_path

    if len(existing) > 1:
        raise FSLError(f"FSL backend expects a single affine or FNIRT warp transform, got {len(existing)}: {existing}")
    _apply_affine(fixed_path, moving_path, existing[0], out_path, interpolation=interpolation, verbose=verbose)
    return out_path


def _invert_affine(affine: Path, inverse_affine: Path, verbose: bool = False) -> None:
    require_cli("convert_xfm")
    run_cli(["convert_xfm", "-omat", str(inverse_affine), "-inverse", str(affine)], verbose=verbose)


def _apply_affine(fixed: Path, moving: Path, affine: Path, out_path: Path, interpolation: str, verbose: bool = False) -> None:
    require_cli("flirt")
    cmd = [
        "flirt",
        "-in",
        str(moving),
        "-ref",
        str(fixed),
        "-applyxfm",
        "-init",
        str(affine),
        "-out",
        str(out_path),
        "-interp",
        _flirt_interpolation(interpolation),
    ]
    run_cli(cmd, verbose=verbose)


def _apply_warp(fixed: Path, moving: Path, warp: Path, out_path: Path, interpolation: str, postmat: Path | None = None, verbose: bool = False) -> None:
    require_cli("applywarp")
    cmd = [
        "applywarp",
        f"--ref={fixed}",
        f"--in={moving}",
        f"--warp={warp}",
        f"--out={out_path}",
        f"--interp={_applywarp_interpolation(interpolation)}",
    ]
    if postmat is not None:
        cmd.append(f"--postmat={postmat}")
    run_cli(cmd, verbose=verbose)


def _as_image_path(image) -> Path:
    if isinstance(image, (str, Path)):
        path = Path(image)
        if not path.exists():
            raise FSLError(f"Image path does not exist: {path}")
        return path
    if isinstance(image, nib.Nifti1Image):
        tmp = tempfile.NamedTemporaryFile(suffix=".nii.gz", delete=False)
        tmp_path = Path(tmp.name)
        tmp.close()
        nib.save(image, str(tmp_path))
        return tmp_path
    raise FSLError("FSL interface requires image paths or nibabel images.")


def _flirt_interpolation(interpolation: str) -> str:
    mapping = {
        "linear": "trilinear",
        "nearestNeighbor": "nearestneighbour",
        "genericLabel": "nearestneighbour",
        "bSpline": "spline",
    }
    return mapping.get(interpolation, interpolation)


def _applywarp_interpolation(interpolation: str) -> str:
    """``applywarp --interp`` uses different names than ``flirt -interp``
    (notably ``nn`` instead of ``nearestneighbour``) -- see FSL's own
    ``applywarp --help``."""
    mapping = {
        "linear": "trilinear",
        "nearestNeighbor": "nn",
        "genericLabel": "nn",
        "bSpline": "spline",
    }
    return mapping.get(interpolation, interpolation)
